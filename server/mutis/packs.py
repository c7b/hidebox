# SPDX-License-Identifier: MIT
"""Space packs against griefing (spec §9.6).

Paid space is capped at `packs.paid_cap_fraction` of the pool (quota.compute). The cap has two slices:
purchases made with a judge pass (X-Mutis-Judge) draw from a reserved slice, `judge_fraction` of the cap,
that public buyers can't reach, and spill into the public slice once it is used up. `sold_out` is the
public slice's answer. Open invoices count against the slice they would draw from until they expire,
so paying several at once can't overbook a slice; a renewal adds no bytes and reserves nothing.

A drive holds one pack at a time. In the pack's last `renew_days` days it may buy the same pack again:
the days stack (from the old end), the bytes don't.

Sales a UTC day: the deployment-wide ceilings (`public_per_day`, `judge_per_day`) are counted here from
the invoices table, which holds no network, so a restart doesn't reset them; the per-network brakes are
in the API's memory (api.Ctx.daily) and a restart forgets them. An invoice that ended with nothing paid,
or a pack that ended early (release-pack, a deleted drive), stops counting; our own daily evidence
invoice (no drive) never counts.
"""
import sqlite3
from dataclasses import dataclass

from . import codec, quota

PUBLIC_ALERT = 0.80                  # /status.json turns amber when the public slice is this full
_ACTIVE = "paid_until IS NOT NULL AND paid_until > ? AND paid_bytes > 0"


@dataclass(frozen=True)
class Slices:
    cap: int                         # all paid space
    judge_cap: int                   # the judges' slice of it
    public_cap: int
    public_active: int               # bytes of active packs bought without a judge pass
    judge_active: int
    public_open: int                 # bytes open invoices would add
    judge_open: int

    @property
    def judge_spill(self) -> int:
        return max(0, self.judge_active + self.judge_open - self.judge_cap)

    @property
    def public_taken(self) -> int:
        """What the public slice holds or has promised: its packs, its open invoices, judges' overflow."""
        return self.public_active + self.public_open + self.judge_spill

    @property
    def public_sold(self) -> int:
        """Active packs only (for /stats): the public slice's packs and judges' overflow into it."""
        return self.public_active + max(0, self.judge_active - self.judge_cap)

    def room(self, nbytes: int, judge: bool) -> bool:
        if judge:
            over = max(0, self.judge_active + self.judge_open + nbytes - self.judge_cap)
            return self.public_active + self.public_open + over <= self.public_cap
        return self.public_taken + nbytes <= self.public_cap


def slices(conn: sqlite3.Connection, pool: quota.Pool, cfg_packs: dict, now: int) -> Slices:
    cap = int(cfg_packs["paid_cap_fraction"] * pool.pool)
    judge_cap = int(cfg_packs["judge_fraction"] * cap)
    active, pending = [0, 0], [0, 0]
    for row in conn.execute(f"SELECT paid_judge, COALESCE(SUM(paid_bytes), 0) FROM identities WHERE {_ACTIVE} "
                            "GROUP BY paid_judge", (now,)):
        active[row[0]] += row[1]
    for row in conn.execute("SELECT i.pack, i.judge FROM invoices i JOIN identities d ON d.id = i.identity_id "
                            "WHERE i.status IN ('pending','seen') AND i.expires_at > ? "
                            "AND NOT (d.paid_until IS NOT NULL AND d.paid_until > ? AND d.paid_bytes > 0)", (now, now)):
        pending[row[1]] += quota.PACKS[row[0]]["bytes"]
    return Slices(cap, judge_cap, cap - judge_cap, active[0], active[1], pending[0], pending[1])


def sold_today(conn: sqlite3.Connection, now: int, judge: bool) -> int:
    """Pack invoices made this UTC day by drives, with or without a judge pass, that still hold or promise
    space: open, partly paid, or paid while the drive still holds its pack. A pack ended early (an operator's
    `release-pack` after a test run) or a deleted drive stops counting, like an unpaid invoice that expired:
    the ceiling bounds how much of today's selling can hold space at once."""
    return conn.execute(
        "SELECT COUNT(*) FROM invoices i JOIN identities d ON d.id = i.identity_id WHERE i.judge = ? AND i.created_at >= ? "
        "AND ((i.status IN ('pending','seen') AND i.expires_at > ?) OR (i.received_ut > 0 AND i.status <> 'credited') "
        "OR (i.status = 'credited' AND d.paid_until IS NOT NULL AND d.paid_until > ? AND d.paid_bytes > 0))",
        (int(judge), now - now % 86400, now, now)).fetchone()[0]


def held(identity, now: int, renew_days: int) -> dict | None:
    """The pack a drive holds: its id (for packs bought before schema 6, the pack of that size today, else
    None), bytes, end, and when renewing opens."""
    if not (identity["paid_until"] and identity["paid_until"] > now and identity["paid_bytes"] > 0):
        return None
    pack = identity["paid_pack"] or next((pid for pid, p in quota.PACKS.items()
                                          if p["bytes"] == identity["paid_bytes"]), None)
    return {"id": pack, "bytes": identity["paid_bytes"], "until": identity["paid_until"],
            "renew_from": identity["paid_until"] - renew_days * 86400}


def status(conn: sqlite3.Connection, pool: quota.Pool, cfg_packs: dict, now: int) -> dict:
    """meta.packs for the healthcheck (written by cleanup every minute): no drive, no network."""
    s = slices(conn, pool, cfg_packs, now)
    sold = sold_today(conn, now, False)
    return {"day": codec.day(now), "updated_at": now,
            "public_80": s.public_cap > 0 and s.public_taken >= PUBLIC_ALERT * s.public_cap,
            "ceiling_hit": sold >= cfg_packs["public_per_day"]}
