# SPDX-License-Identifier: MIT
"""Upload admission: lanes, the global freeze and locker quotas (spec §9.1, §9.3, §9.4).

Every function here runs inside the caller's BEGIN IMMEDIATE transaction, so the byte
reservation it approves can't be overtaken by a concurrent upload.
"""
import sqlite3

from . import db, quota
from .http_util import ApiError


def lane_used(conn: sqlite3.Connection, lane: str) -> int:
    return conn.execute("SELECT COALESCE(SUM(size_stored), 0) FROM items "
                        "WHERE lane = ? AND state IN ('uploading','ready','doomed')", (lane,)).fetchone()[0]


def freeze_state(conn: sqlite3.Connection, pool: quota.Pool) -> str:
    """'none' | 'free' | 'all': the stricter of the operator's switch and the disk thresholds."""
    order = ["none", "free", "all"]
    disk = "none"
    if pool.d_avail < pool.reserve + quota.FREEZE_ALL_MARGIN:
        disk = "all"
    elif pool.d_avail < pool.reserve + quota.FREEZE_FREE_MARGIN:
        disk = "free"
    operator = db.get_meta(conn, "uploads_frozen", "none")
    return max(disk, operator if operator in order else "all", key=order.index)


def lane_for_anonymous(size_stored: int) -> str:
    return "small" if size_stored <= quota.max_stored(quota.SMALL_PLAINTEXT_MAX) else "anon"


def admit_lane(conn: sqlite3.Connection, pool: quota.Pool, lane: str, size_stored: int, frozen: str) -> None:
    """Check the freeze and the lane cap for an anonymous, drop or canary upload."""
    if frozen == "all" or (frozen == "free" and lane == "anon"):
        raise ApiError(503, "uploads_frozen", "Uploads are paused while the disk is nearly full.",
                       details={"scope": frozen})
    cap = {"small": pool.small, "drop": pool.drop, "anon": pool.anon}[lane]
    used = lane_used(conn, lane)
    if used + size_stored > cap:
        raise ApiError(507, "lane_full", "This lane is full right now.", details={"lane": lane})
    if lane == "small" and used + size_stored > cap - quota.DEMO_RESERVE \
            and size_stored > quota.max_stored(quota.DEMO_FILE_MAX):
        raise ApiError(507, "lane_full", "Only files up to 1 MB fit right now.", details={"lane": lane})


def admit_locker(conn: sqlite3.Connection, pool: quota.Pool, identity: sqlite3.Row, size_stored: int,
                 frozen: str, now: int) -> None:
    """Freeze, per-file and quota checks for a locker upload (or an adoption/claim)."""
    cls = quota.class_of(identity, now)
    if frozen == "all" or (frozen == "free" and cls != "paid"):
        raise ApiError(503, "uploads_frozen", "Uploads are paused while the disk is nearly full.",
                       details={"scope": frozen})
    limit = quota.locker_limit(identity, quota.free_quota(conn, pool), now)
    if identity["used_bytes"] + identity["reserved_bytes"] + size_stored > limit:
        code = "probation_limit" if cls == "probation" else "quota_exceeded"
        raise ApiError(507, code, "Not enough room in this locker.", details={"limit_bytes": limit})


def check_file_size(cls: str, size_stored: int) -> None:
    max_bytes = quota.CLASSES[cls]["max_file_bytes"]
    if size_stored > quota.max_stored(max_bytes):
        raise ApiError(413, "too_large", "This file is too large for this kind of link.",
                       details={"max_bytes": max_bytes, "class": cls})
