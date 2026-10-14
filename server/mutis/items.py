# SPDX-License-Identifier: MIT
"""Item and link lifecycle shared by the API, cleanup and admin (spec §5.1, §5.2).

Callers hold a BEGIN IMMEDIATE transaction around every function that writes.
"""
import sqlite3

from . import codec, seallog, tree
from .storage import Blobs

ENDED_REASON = {"exhausted": "burned", "expired": "expired", "revoked": "revoked", "removed": "removed",
                "owner_deleted": "owner_deleted"}
TICKET_S = 1800              # a download ticket lives 30 minutes (spec §5.3)
EGRESS_PER_ITEM_DAY = 10 << 30     # bytes served per item per day, by every link and visit together
MAX_DELETE_AFTER_DAYS = 30    # Delete it after… on a kept file: at most this far ahead (16-drive-design §7)


def egress_ok(conn: sqlite3.Connection, item, now: int, size: int) -> bool:
    """Count `size` more bytes against an item's daily egress (EGRESS_PER_ITEM_DAY); False when over."""
    today = codec.day(now)
    used = item["egress_bytes"] if item["egress_day"] == today else 0
    if used + size > EGRESS_PER_ITEM_DAY:
        return False
    conn.execute("UPDATE items SET egress_day = ?, egress_bytes = ? WHERE id = ?", (today, used + size, item["id"]))
    return True


def end_share(conn: sqlite3.Connection, share_id: str, state: str, now: int) -> None:
    """Move an active link to an ended state and scrub its secrets; the row stays as a tombstone."""
    conn.execute("UPDATE shares SET state = ?, ended_at = ?, wrapped_key = NULL, access_hash = NULL, "
                 "link_hash = NULL WHERE id = ? AND state = 'active'", (state, now, share_id))


def doom_if_unlinked(conn: sqlite3.Connection, item_id: str, now: int) -> bool:
    """An ephemeral item whose last link ended becomes doomed (canary items wait for their own expiry)."""
    cur = conn.execute(
        "UPDATE items SET state = 'doomed', doomed_at = ? WHERE id = ? AND state = 'ready' "
        "AND retention = 'ephemeral' AND canary = 0 "
        "AND NOT EXISTS (SELECT 1 FROM shares WHERE item_id = items.id AND state = 'active')", (now, item_id))
    return cur.rowcount == 1


def doom_item(conn: sqlite3.Connection, item_id: str, share_state: str, now: int) -> None:
    """End every active link of an item and mark it doomed (owner deletion, expiry)."""
    for row in conn.execute("SELECT id FROM shares WHERE item_id = ? AND state = 'active'", (item_id,)).fetchall():
        end_share(conn, row["id"], share_state, now)
    conn.execute("UPDATE items SET state = 'doomed', doomed_at = ? WHERE id = ? AND state = 'ready'", (now, item_id))


def has_live_ticket(conn: sqlite3.Connection, item_id: str, now: int) -> bool:
    return conn.execute("SELECT 1 FROM tickets WHERE item_id = ? AND done = 0 AND expires_at > ? LIMIT 1",
                        (item_id, now)).fetchone() is not None


def release(conn: sqlite3.Connection, item: sqlite3.Row) -> None:
    """Give a locker back the bytes of an item that stops counting against its quota."""
    if item["owner_id"] and item["state"] in ("ready", "doomed"):
        conn.execute("UPDATE identities SET used_bytes = MAX(0, used_bytes - ?) WHERE id = ?",
                     (item["size_stored"], item["owner_id"]))


def unlink(conn: sqlite3.Connection, blobs: Blobs, item_id: str, final_state: str, now: int) -> None:
    """Delete an item's ciphertext and record the exit receipt (P-8). final_state: 'deleted' | 'removed'."""
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None or item["state"] in ("deleted", "removed"):
        return
    release(conn, item)
    if item["state"] == "uploading":
        conn.execute("DELETE FROM uploads WHERE item_id = ?", (item_id,))
        if item["owner_id"]:
            conn.execute("UPDATE identities SET reserved_bytes = MAX(0, reserved_bytes - ?) WHERE id = ?",
                         (item["size_stored"], item["owner_id"]))
    blobs.unlink(item_id)
    exit_hour = codec.floor_hour(now)
    conn.execute("UPDATE items SET state = ?, exit_hour = ? WHERE id = ?", (final_state, exit_hour, item_id))
    conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
    if item["ct_hash"] is not None:
        seallog.append(conn, "exit", seallog.exit_leaf(item_id, exit_hour))


def remove(conn: sqlite3.Connection, blobs: Blobs, item_id: str, now: int) -> None:
    """Abuse takedown: end every link with reason `removed` and delete the blob at once. An item that
    already left by its rule is marked removed too (its exit receipt stays), so it leaves the wall.
    A folder is removed with everything in it: a folder link shares its whole subtree."""
    for row in tree.subtree(conn, item_id, ("uploading", "ready", "doomed")):
        for share in conn.execute("SELECT id FROM shares WHERE item_id = ? AND state = 'active'",
                                  (row["id"],)).fetchall():
            end_share(conn, share["id"], "removed", now)
        conn.execute("UPDATE tickets SET done = 1 WHERE item_id = ?", (row["id"],))
        unlink(conn, blobs, row["id"], "removed", now)
        conn.execute("UPDATE items SET state = 'removed' WHERE id = ? AND state = 'deleted'", (row["id"],))


def delete_tree(conn: sqlite3.Connection, blobs: Blobs, item_id: str, share_state: str, now: int) -> int:
    """The owner deletes an item; a folder goes with its whole subtree, in the caller's transaction. Each
    file's ciphertext is unlinked now (with its exit receipt), or when a running download ends."""
    rows = tree.subtree(conn, item_id)
    for row in rows:
        if row["state"] == "uploading":
            unlink(conn, blobs, row["id"], "deleted", now)
        else:
            doom_item(conn, row["id"], share_state, now)
            unlink_if_unreferenced(conn, blobs, row["id"], now)
    return len(rows)


def trash(conn: sqlite3.Connection, item_id: str, now: int) -> None:
    """Into the Trash with everything below it (one timestamp marks what this move put there). Every
    active link of those items ends now (`revoked`); the bytes still count until the Trash empties."""
    for row in tree.subtree(conn, item_id):
        if row["trashed_at"] is not None and row["id"] != item_id:
            continue                            # trashed earlier on its own: keeps its own date
        conn.execute("UPDATE items SET trashed_at = ? WHERE id = ?", (now, row["id"]))
        for share in conn.execute("SELECT id FROM shares WHERE item_id = ? AND state = 'active'",
                                  (row["id"],)).fetchall():
            end_share(conn, share["id"], "revoked", now)
        doom_if_unlinked(conn, row["id"], now)  # a file set to leave with its link leaves now


def restore(conn: sqlite3.Connection, item, now: int) -> None:
    """Out of the Trash with what went in with it; links stay ended. To the drive's root when its folder
    is gone or still in the Trash (its wrap under that folder's key is dropped)."""
    parent = conn.execute("SELECT state, trashed_at FROM items WHERE id = ?", (item["parent_id"],)).fetchone() \
        if item["parent_id"] else None
    if item["parent_id"] and (parent is None or parent["state"] != "ready" or parent["trashed_at"] is not None):
        conn.execute("UPDATE items SET parent_id = NULL, parent_wrap = NULL WHERE id = ?", (item["id"],))
    for row in tree.subtree(conn, item["id"]):
        if row["trashed_at"] == item["trashed_at"]:
            conn.execute("UPDATE items SET trashed_at = NULL WHERE id = ?", (row["id"],))


def unlink_if_unreferenced(conn: sqlite3.Connection, blobs: Blobs, item_id: str, now: int) -> bool:
    item = conn.execute("SELECT state FROM items WHERE id = ?", (item_id,)).fetchone()
    if item and item["state"] == "doomed" and not has_live_ticket(conn, item_id, now):
        unlink(conn, blobs, item_id, "deleted", now)
        return True
    return False
