# SPDX-License-Identifier: MIT
"""Daily budgets in three slices (spec §9.5, with an evidence slice added by this build).

Units: `courier` and `decoy` count sends; `demo_pay` and `sponsor` count µT. `public` serves day-1
lockers and anonymous drop submitters, `reserved` lockers older than today and decoys, and `evidence`
our canary, the daily evidence payment and judge passes, so no locker can empty what they need.

A `mutis-admin budget set` override can only lower a slice below the TOML value: the API can write
the database, and a bug there must not be able to raise what the worker may spend (spec D4).
"""
import sqlite3

from . import codec, db

KINDS = {"courier": "courier", "decoy": "decoy", "demo_pay": "demo_pay_ut", "sponsor": "sponsor_ut"}
SLICES = ("public", "reserved", "evidence")


def limit(conn: sqlite3.Connection, cfg_budgets: dict, kind: str, slice_: str, now: int) -> int:
    configured = int(cfg_budgets[slice_].get(KINDS[kind], 0))
    override = db.get_meta_json(conn, "budget_overrides", {}).get(f"{codec.day(now)}:{kind}:{slice_}")
    return configured if override is None else min(configured, int(override))


def used(conn: sqlite3.Connection, kind: str, slice_: str, now: int) -> int:
    row = conn.execute("SELECT used FROM budgets WHERE day = ? AND kind = ? AND slice = ?",
                       (codec.day(now), kind, slice_)).fetchone()
    return row[0] if row else 0


def has_room(conn: sqlite3.Connection, cfg_budgets: dict, kind: str, slice_: str, cost: int, now: int) -> bool:
    return used(conn, kind, slice_, now) + cost <= limit(conn, cfg_budgets, kind, slice_, now)


def charge(conn: sqlite3.Connection, kind: str, slice_: str, cost: int, now: int) -> None:
    conn.execute("INSERT INTO budgets(day, kind, slice, used) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(day, kind, slice) DO UPDATE SET used = used + excluded.used",
                 (codec.day(now), kind, slice_, cost))


def set_override(conn: sqlite3.Connection, kind: str, slice_: str, value: int, now: int) -> None:
    overrides = {k: v for k, v in db.get_meta_json(conn, "budget_overrides", {}).items()
                 if k.startswith(codec.day(now))}
    overrides[f"{codec.day(now)}:{kind}:{slice_}"] = value
    db.set_meta(conn, "budget_overrides", overrides)


def table(conn: sqlite3.Connection, cfg_budgets: dict, now: int) -> list[dict]:
    rows = []
    for kind in KINDS:
        for slice_ in SLICES:
            cap = limit(conn, cfg_budgets, kind, slice_, now)
            rows.append({"kind": kind, "slice": slice_, "used": used(conn, kind, slice_, now), "limit": cap})
    return rows


def alert_levels(conn: sqlite3.Connection, cfg_budgets: dict, now: int) -> dict:
    """{'courier:public': 50|90, …} for every slice at or above 50 % of its limit."""
    levels = {}
    for row in table(conn, cfg_budgets, now):
        if row["limit"] <= 0:
            continue
        share = row["used"] / row["limit"]
        if share >= 0.5:
            levels[f"{row['kind']}:{row['slice']}"] = 90 if share >= 0.9 else 50
    return levels


def resets_at(now: int) -> int:
    return codec.next_utc_midnight(now)
