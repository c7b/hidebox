# SPDX-License-Identifier: MIT
"""mutis-cleanup (spec §8.2): runs every 60 s; each step is its own short transaction.

A link that ends by being opened, revoked or deleted loses its wrapped key in that request; one that
expires loses it here, within a minute. A doomed item's ciphertext is unlinked within a minute,
or, while a download ticket is still open, when that download finishes (at most 30 minutes).
"""
import sqlite3
import time

from . import codec, db, items, payments, quota, sales
from .storage import Blobs

TOMBSTONE_DAYS = 30
INACTIVE_DAYS = 180
LAPSE_GRACE_DAYS = 30
TRASH_DAYS = 30             # the Trash empties itself after this (16-drive-design §7, C47)
DB_BACKUP_DAYS = 7          # kept by deploy/scripts/backup.py; published in /config
UNSHARED_GRACE_S = 2 * 3600
JOB_KEEP_S = 86400          # finished jobs (tx ids of user deliveries) are forgotten after a day
EVIDENCE_JOB_KEEP_S = TOMBSTONE_DAYS * 86400
STALE_SEND_S = 1800         # the chain worker gives a send up after 15 minutes; this covers a worker that is down
DAILY_LOCAL_HOUR = 3


def _ids(conn: sqlite3.Connection, sql: str, args=()) -> list[str]:
    return [row[0] for row in conn.execute(sql, args).fetchall()]


def expire_links(conn: sqlite3.Connection, now: int) -> int:
    ids = _ids(conn, "SELECT id FROM shares WHERE state = 'active' AND expires_at IS NOT NULL AND expires_at <= ?", (now,))
    for share_id in ids:
        with db.tx(conn):
            items.end_share(conn, share_id, "expired", now)
    return len(ids)


def doom_items(conn: sqlite3.Connection, now: int) -> int:
    expired = _ids(conn, "SELECT id FROM items WHERE state = 'ready' AND expires_at IS NOT NULL AND expires_at <= ?",
                   (now,))
    for item_id in expired:
        with db.tx(conn):
            items.doom_item(conn, item_id, "expired", now)
    # An item whose links have all ended is doomed; one that never got a link gets the upload session's
    # two hours first, so a browser that just finished uploading still has time to make its link.
    unlinked = _ids(conn, "SELECT id FROM items WHERE state = 'ready' AND retention = 'ephemeral' AND canary = 0 "
                          "AND NOT EXISTS (SELECT 1 FROM shares WHERE item_id = items.id AND state = 'active') "
                          "AND (EXISTS (SELECT 1 FROM shares WHERE item_id = items.id) OR created_hour < ?)",
                    (now - UNSHARED_GRACE_S,))
    for item_id in unlinked:
        with db.tx(conn):
            items.doom_if_unlinked(conn, item_id, now)
    return len(expired) + len(unlinked)


def empty_trash(conn: sqlite3.Connection, blobs: Blobs, now: int) -> int:
    """What sat in the Trash for `TRASH_DAYS` leaves, each file with its exit receipt (16-drive-design §7).
    Everything a folder took into the Trash carries the same date, so it leaves with the folder."""
    ids = _ids(conn, "SELECT id FROM items WHERE state IN ('ready','uploading') AND trashed_at IS NOT NULL "
                     "AND trashed_at <= ?", (now - TRASH_DAYS * 86400,))
    for item_id in ids:
        with db.tx(conn):
            items.delete_tree(conn, blobs, item_id, "owner_deleted", now)
    return len(ids)


def unlink_blobs(conn: sqlite3.Connection, blobs: Blobs, now: int) -> int:
    count = 0
    for item_id in _ids(conn, "SELECT id FROM items WHERE state = 'doomed'"):
        with db.tx(conn):
            count += items.unlink_if_unreferenced(conn, blobs, item_id, now)
    return count


def drop_abandoned_uploads(conn: sqlite3.Connection, blobs: Blobs, now: int) -> int:
    stale = conn.execute("SELECT u.id, u.item_id, i.state FROM uploads u JOIN items i ON i.id = u.item_id "
                         "WHERE u.expires_at <= ?", (now,)).fetchall()
    for row in stale:
        with db.tx(conn):
            if row["state"] == "uploading":
                items.unlink(conn, blobs, row["item_id"], "deleted", now)
            conn.execute("DELETE FROM uploads WHERE id = ?", (row["id"],))
    return len(stale)


def fail_stale_sends(conn: sqlite3.Connection, now: int) -> int:
    """A send still unsettled 30 minutes after it was due or submitted ends as `interrupted`, and its
    destination is scrubbed: a live worker claims a job within about a minute of `not_before`."""
    with db.tx(conn):
        return conn.execute("UPDATE jobs SET state = 'failed', payload = NULL, result = NULL, error = 'interrupted', "
                            "updated_at = ? WHERE (state = 'sending' AND updated_at <= ?) "
                            "OR (state = 'queued' AND not_before <= ?)",
                            (now, now - STALE_SEND_S, now - STALE_SEND_S)).rowcount


def purge_expired(conn: sqlite3.Connection, now: int) -> None:
    with db.tx(conn):
        conn.execute("DELETE FROM tickets WHERE expires_at <= ? OR done = 1", (now,))
        conn.execute("DELETE FROM sessions WHERE expires_at <= ? OR last_used_day < ?",
                     (now, codec.day(now - 7 * 86400)))
        conn.execute("DELETE FROM used_nonces WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM jobs WHERE state IN ('done','failed') AND evidence = 0 AND updated_at <= ?",
                     (now - JOB_KEEP_S,))
        conn.execute("DELETE FROM jobs WHERE state IN ('done','failed') AND evidence = 1 AND updated_at <= ?",
                     (now - EVIDENCE_JOB_KEEP_S,))


def purge_tombstones(conn: sqlite3.Connection, now: int) -> None:
    cutoff = now - TOMBSTONE_DAYS * 86400
    with db.tx(conn):
        conn.execute("DELETE FROM shares WHERE state <> 'active' AND ended_at IS NOT NULL AND ended_at <= ?", (cutoff,))
        conn.execute("DELETE FROM items WHERE state IN ('deleted','removed') AND COALESCE(exit_hour, created_hour) <= ?",
                     (cutoff,))
        conn.execute("DELETE FROM drops WHERE state <> 'active' AND ended_day IS NOT NULL AND ended_day <= ?",
                     (codec.day(cutoff),))


def hourly(conn: sqlite3.Connection, pool: quota.Pool, now: int) -> None:
    """Move the free quota one smoothing step toward its target (spec §9.2)."""
    with db.tx(conn):
        old = db.get_meta(conn, "free_quota_bytes")
        new = pool.q_target if old is None else quota.smooth(int(old), pool.q_target)
        db.set_meta(conn, "free_quota_bytes", str(new))
        db.set_meta(conn, "free_quota_updated_at", str(now))


def _delete_items(conn: sqlite3.Connection, blobs: Blobs, item_ids: list[str], now: int) -> None:
    for item_id in item_ids:
        with db.tx(conn):
            items.doom_item(conn, item_id, "owner_deleted", now)
            items.unlink(conn, blobs, item_id, "deleted", now)


def daily(conn: sqlite3.Connection, blobs: Blobs, q: int, now: int) -> None:
    """Lapse policy and inactive lockers (spec §9.6), then PRAGMA optimize."""
    lapsed = conn.execute("SELECT id, used_bytes FROM identities WHERE paid_until IS NOT NULL AND paid_until <= ? "
                          "AND used_bytes > ?", (now - LAPSE_GRACE_DAYS * 86400, q)).fetchall()
    for identity in lapsed:
        over = identity["used_bytes"] - q
        doomed = []
        # Files in the Trash go first, then the oldest (C46); folders hold no bytes and stay.
        for row in conn.execute("SELECT id, size_stored FROM items WHERE owner_id = ? AND retention = 'kept' "
                                "AND state = 'ready' AND kind = 'file' "
                                "ORDER BY trashed_at IS NULL, trashed_at, created_hour, rowid", (identity["id"],)):
            if over <= 0:
                break
            doomed.append(row["id"])
            over -= row["size_stored"]
        _delete_items(conn, blobs, doomed, now)
    inactive = _ids(conn, "SELECT i.id FROM items i JOIN identities d ON d.id = i.owner_id "
                          "WHERE i.state IN ('ready','uploading') AND d.last_seen_day < ?",
                    (codec.day(now - INACTIVE_DAYS * 86400),))
    _delete_items(conn, blobs, inactive, now)
    conn.execute("PRAGMA optimize")


def run(conn: sqlite3.Connection, cfg, blobs: Blobs, statvfs, now: int) -> dict:
    counts = {"links_expired": expire_links(conn, now), "items_doomed": doom_items(conn, now),
              "trash_emptied": empty_trash(conn, blobs, now), "blobs_unlinked": unlink_blobs(conn, blobs, now),
              "uploads_dropped": drop_abandoned_uploads(conn, blobs, now),
              "sends_interrupted": fail_stale_sends(conn, now)}
    purge_expired(conn, now)
    purge_tombstones(conn, now)
    payments.expire_invoices(conn, now)
    sales.expire_claims(conn, now)
    hour = str(codec.floor_hour(now))
    if db.get_meta(conn, "cleanup_hour") != hour:
        pool = quota.measure(conn, statvfs, cfg.data_dir, cfg["limits"], now)
        hourly(conn, pool, now)
        with db.tx(conn):
            db.set_meta(conn, "cleanup_hour", hour)
    local = time.localtime(now)
    today_local = time.strftime("%Y-%m-%d", local)
    if local.tm_hour >= DAILY_LOCAL_HOUR and db.get_meta(conn, "cleanup_day") != today_local:
        pool = quota.measure(conn, statvfs, cfg.data_dir, cfg["limits"], now)
        daily(conn, blobs, quota.free_quota(conn, pool), now)
        with db.tx(conn):
            db.set_meta(conn, "cleanup_day", today_local)
    return counts
