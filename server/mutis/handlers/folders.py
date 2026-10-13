# SPDX-License-Identifier: MIT
"""The drive's folders, moves, renames, the Trash and "Delete it after…" (research 16-drive-design §5, §7;
annex 16-drive-architecture §2.1, §2.4). Behind `features.folders`.

A folder is an item without ciphertext whose key wraps its children's keys (`parent_wrap`). The server
checks the shape of the tree (same drive, no cycle, depth, children, the Trash) and never sees a name:
a rename is a new `meta_ct`, a move is a new parent and a new wrap, both made in the browser.
"""
import os
import struct

from .. import codec, db, items, tree
from ..http_util import ApiError, get_b64, get_bool, get_int, invalid, json_response
from .me import item_entry
from .uploads import META_LENGTHS

FOLDERS_PER_HOUR = 600            # per drive
PATCHES_PER_HOUR = 600            # per drive


def check_folder_header(header: bytes) -> None:
    """Format v1 with the folder flag and no chunks; uploads refuse this flag (spec §4.9, annex §2.1)."""
    magic, version, chunk_log2, flags, count, reserved = struct.unpack(">4sBBHII", header[:16])
    if magic != b"MTS1" or version != 1 or chunk_log2 != 22 or flags != tree.FOLDER_FLAGS or count != 0 \
            or reserved != 0:
        raise invalid("header")


def drive_session(ctx):
    ctx.require_feature("folders")
    return ctx.session()


def own_item(conn, item_id: str, identity) -> object:
    """A live item of this drive, or 404 (another drive's item looks like no item at all)."""
    item = conn.execute("SELECT * FROM items WHERE id = ? AND owner_id = ?", (item_id, identity["id"])).fetchone()
    if item is None or item["state"] not in tree.LIVE:
        raise ApiError(404, "not_found", "No such item in this drive.")
    return item


def create(ctx):
    """POST /folders {parent_id|null, header, meta_ct, owner_wrap, parent_wrap?} → 201 {item_id}."""
    identity = drive_session(ctx)
    body = ctx.req.json()
    header = get_b64(body, "header", 32)
    check_folder_header(header)
    meta_ct = get_b64(body, "meta_ct", max_len=2048 + 28)
    if len(meta_ct) not in META_LENGTHS:
        raise invalid("meta_ct")
    owner_wrap = get_b64(body, "owner_wrap", 60)
    conn = ctx.db
    tree.parent_fields(body, conn, identity)
    item_id = codec.new_id()
    with ctx.charged(("mk_folder", identity["id"], FOLDERS_PER_HOUR, 3600, 1)):
        with db.tx(conn):
            parent_id, wrap = tree.parent_fields(body, conn, identity)       # again, inside the transaction
            if parent_id is not None:
                folder = conn.execute("SELECT * FROM items WHERE id = ?", (parent_id,)).fetchone()
                if tree.folder_depth(conn, parent_id) + 1 > tree.MAX_DEPTH:
                    raise ApiError(409, "too_deep", "Folders can't go deeper here.",
                                   details={"max_depth": tree.MAX_DEPTH})
                tree.check_room(conn, folder)
            if tree.drive_items(conn, identity["id"]) >= tree.MAX_ITEMS:
                raise ApiError(413, "too_many", "This drive holds as many items as it can.",
                               details={"max_items": tree.MAX_ITEMS})
            conn.execute("INSERT INTO items(id, owner_id, manage_hash, retention, lane, state, header, meta_ct, "
                         "owner_wrap, chunk_count, size_stored, created_hour, kind, parent_id, parent_wrap) "
                         "VALUES (?, ?, ?, 'kept', 'locker', 'ready', ?, ?, ?, 0, 0, ?, 'folder', ?, ?)",
                         (item_id, identity["id"], codec.sha256(os.urandom(32)), header, meta_ct, owner_wrap,
                          codec.floor_hour(ctx.now), parent_id, wrap))
    return json_response(201, {"item_id": item_id})


def patch(ctx, item_id: str):
    """PATCH /items/{id}: move (`parent_id`, `parent_wrap`), rename (`meta_ct`), Delete it after
    (`expires_at`, a kept file, at most `items.max_delete_after_days` ahead, or null), or the Trash
    (`trashed`, alone). Returns the item as `/me/items` lists it."""
    identity = drive_session(ctx)
    body = ctx.req.json()
    unknown = sorted(set(body) - {"parent_id", "parent_wrap", "meta_ct", "expires_at", "trashed"})
    if unknown:
        raise invalid(unknown[0])
    if not body or ("trashed" in body and len(body) > 1):
        raise invalid("trashed", "Send one change, or `trashed` alone.")
    conn = ctx.db
    with ctx.charged(("item_patch", identity["id"], PATCHES_PER_HOUR, 3600, 1)):
        if "trashed" in body:
            trashed = get_bool(body, "trashed")
            with db.tx(conn):
                item = own_item(conn, item_id, identity)
                if trashed and item["trashed_at"] is None:
                    items.trash(conn, item_id, ctx.now)
                elif not trashed and item["trashed_at"] is not None:
                    items.restore(conn, item, ctx.now)
        else:
            meta_ct = get_b64(body, "meta_ct", max_len=2048 + 28, optional=True)
            if meta_ct is not None and len(meta_ct) not in META_LENGTHS:
                raise invalid("meta_ct")
            expires_given = "expires_at" in body
            expires_at = get_int(body, "expires_at", 0, 1 << 40, optional=True)
            with db.tx(conn):
                item = own_item(conn, item_id, identity)
                if item["trashed_at"] is not None:
                    raise ApiError(409, "trashed", "Bring it back from the Trash first.")
                if "parent_id" in body or "parent_wrap" in body:
                    _move(conn, item, body, identity)
                if meta_ct is not None:            # a rename: new metadata under the same key, a new IV
                    conn.execute("UPDATE items SET meta_ct = ? WHERE id = ?", (meta_ct, item_id))
                if expires_given:
                    _delete_after(conn, item, expires_at, ctx.now)
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return json_response(200, item_entry(conn, row, ctx.now))


def _move(conn, item, body: dict, identity) -> None:
    parent_id = body.get("parent_id")
    if parent_id is None:
        if body.get("parent_wrap") is not None:
            raise invalid("parent_wrap")
        conn.execute("UPDATE items SET parent_id = NULL, parent_wrap = NULL WHERE id = ?", (item["id"],))
        return
    if not isinstance(parent_id, str) or len(parent_id) != 22:
        raise invalid("parent_id")
    wrap = get_b64(body, "parent_wrap", tree.PARENT_WRAP_LEN)
    folder = tree.target_folder(conn, parent_id, identity)
    if tree.within(conn, parent_id, item["id"]):
        raise ApiError(409, "cycle", "A folder can't go inside itself.")
    if tree.folder_depth(conn, parent_id) + tree.height(conn, item) > tree.MAX_DEPTH:
        raise ApiError(409, "too_deep", "Folders can't go deeper here.", details={"max_depth": tree.MAX_DEPTH})
    if item["parent_id"] != parent_id:
        tree.check_room(conn, folder)
    conn.execute("UPDATE items SET parent_id = ?, parent_wrap = ? WHERE id = ?", (parent_id, wrap, item["id"]))


def _delete_after(conn, item, expires_at, now: int) -> None:
    """Delete it after… (16-drive-design §7): a kept file keeps `retention = 'kept'` (so it doesn't leave
    when its links end) and leaves at `expires_at` through cleanup's ordinary expiry, with its exit
    receipt. Its links end then too. Null clears it."""
    if item["kind"] != "file" or item["retention"] != "kept" or item["state"] != "ready":
        raise invalid("expires_at", "Only a kept file can be set to leave.")
    if expires_at is not None:
        if not now < expires_at <= now + items.MAX_DELETE_AFTER_DAYS * 86400 + 60:
            raise invalid("expires_at")
        expires_at = codec.coarse_expiry(expires_at, now)
    conn.execute("UPDATE items SET expires_at = ? WHERE id = ?", (expires_at, item["id"]))
