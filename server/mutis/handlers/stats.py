# SPDX-License-Identifier: MIT
"""GET /stats and /stats/wall (spec §6.3, brand §8.3 / P-3): live numbers, never anything per person.

Paid space shows the public slice only, sold and capped, each rounded down to a whole GiB.
Disk sizes are rounded to 0.1 GiB: uploads reserve their full size at once, so exact free bytes
refreshed every minute would show each upload's padded size and time.

The wall shows two coarse classes (size and exit rule) for at most 24 items from the last 7 days, only
when at least 8 exist, in random order, leaving out items under an hour old and files taken down. It
says nothing about whether or when a link was opened. It names no file, but someone who knows a file's
size class and rule may still recognise it there.
"""
import random

from .. import db, lanes, packs, quota, seallog
from ..http_util import json_response
from .courier import HEARTBEAT_MAX_AGE_S

WALL_MAX = 24
WALL_MIN = 8
WALL_HOLD_S = 7200               # created_hour is floored, so an item shows 1 to 2 hours after upload
LOCKERS_SHOWN_FROM = 100
DISK_STEP = quota.GiB // 10


def build_stats(ctx) -> dict:
    conn, now = ctx.db, ctx.now
    pool = quota.measure(conn, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], now)
    last = db.get_meta(conn, "last_sealed_at")
    active = conn.execute("SELECT COUNT(*) FROM identities WHERE last_seen_day >= date(?, 'unixepoch', '-30 days')",
                          (now,)).fetchone()[0]
    status = db.get_meta_json(conn, "chain_status", {})
    beat = int(db.get_meta(conn, "chain_heartbeat", "0"))
    checkpoint = seallog.latest_committed(conn)
    paid = packs.slices(conn, pool, ctx.cfg["packs"], now)
    return {
        "free_quota_bytes": quota.free_quota(conn, pool),
        "last_sealed_min": (now - int(last)) // 60 if last else None,
        "lockers_active_30d": active if active >= LOCKERS_SHOWN_FROM else None,
        "disk_used_pct": round(100 * (pool.d_total - pool.d_avail) / pool.d_total) if pool.d_total else None,
        "disk_total_bytes": pool.d_total - pool.d_total % DISK_STEP,
        "disk_free_bytes": pool.d_avail - pool.d_avail % DISK_STEP,
        "uploads_frozen": lanes.freeze_state(conn, pool),
        # Sixth pass: the public slice of paid space, in whole GiB (no drive, no judge slice).
        "packs_sold_public": paid.public_sold - paid.public_sold % quota.GiB,
        "packs_cap_public": paid.public_cap - paid.public_cap % quota.GiB,
        "chain_ok": now - beat <= HEARTBEAT_MAX_AGE_S and bool(status.get("walletd_ok")),
        "seal_log": {"tree_size": checkpoint["tree_size"], "epoch": checkpoint["epoch"]} if checkpoint else None,
        "updated_at": now,
    }


def stats(ctx):
    return json_response(200, ctx.app.cached("stats", 60, lambda: build_stats(ctx)), "public, max-age=60")


def _size_class(size: int) -> int:
    for cls, limit in enumerate((64 * quota.KiB, quota.MiB, 8 * quota.MiB, 64 * quota.MiB)):
        if size <= limit:
            return cls
    return 4


def build_wall(ctx) -> dict:
    conn, now = ctx.db, ctx.now
    rows = conn.execute("SELECT * FROM items WHERE canary = 0 AND kind = 'file' AND created_hour >= ? "
                        "AND created_hour <= ? AND state NOT IN ('uploading', 'removed') "
                        "ORDER BY created_hour DESC LIMIT ?",
                        (now - 7 * 86400, now - WALL_HOLD_S, WALL_MAX)).fetchall()
    lockers = []
    if len(rows) >= WALL_MIN:
        for item in rows:
            views = [r["max_views"] for r in conn.execute("SELECT max_views FROM shares WHERE item_id = ?",
                                                          (item["id"],))]
            if item["retention"] == "kept":
                exit_ = "kept"
            elif 1 in views:
                exit_ = "once"
            elif any(v is not None for v in views):
                exit_ = "views"
            else:
                exit_ = "time"
            lockers.append({"size": _size_class(item["size_stored"]), "exit": exit_})
        random.SystemRandom().shuffle(lockers)
    canary = None
    item_id = db.get_meta(conn, "canary_item_id")
    if item_id:
        row = conn.execute("SELECT size_stored FROM items WHERE id = ?", (item_id,)).fetchone()
        sealed_at = int(db.get_meta(conn, "canary_sealed_at", "0"))
        if row:
            canary = {"sealed_min": (now - sealed_at) // 60, "size_stored": row["size_stored"]}
    return {"lockers": lockers, "quiet": not lockers, "canary": canary}


def wall(ctx):
    return json_response(200, ctx.app.cached("wall", 300, lambda: build_wall(ctx)), "public, max-age=300")
