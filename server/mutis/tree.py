# SPDX-License-Identifier: MIT
"""Folders as a key tree (research 16-drive-architecture §2.1).

A folder is an `items` row with `kind = 'folder'` and no ciphertext. Every item inside one carries
`parent_id` and `parent_wrap` (its own file key wrapped under the folder's key), so one folder key opens
the whole subtree by walking down and nothing opens upward. The server sees the tree's shape (which
items share a folder, how deep, how many), never a name, a type or a real size.
"""
from . import quota
from .http_util import ApiError, get_b64, invalid

MAX_DEPTH = 16                    # folders inside folders, counting the drive's root as depth 0
MAX_CHILDREN = 1000               # items directly inside one folder
MAX_TREE = 1000                   # items one folder link returns (413 `too_many` beyond)
MAX_ITEMS = 10_000                # items (files and folders) in one drive
MAX_UPLOAD_FILES = 500            # files in one folder upload (checked by the browser)
ZIP_MAX_BYTES = 2 * quota.GiB     # "Download all" in the browser: store-only zip, no ZIP64
ZIP_MAX_BYTES_PHONE = 500 * quota.MiB
PARENT_WRAP_LEN = 60              # iv ‖ AES-GCM(childWrapKey, fk) with its tag
FOLDER_FLAGS = 0x0001             # header flags of a folder (chunk_count 0)


def config_block() -> dict:
    return {"max_depth": MAX_DEPTH, "max_children": MAX_CHILDREN, "max_tree": MAX_TREE, "max_items": MAX_ITEMS,
            "max_upload_files": MAX_UPLOAD_FILES, "zip_max_bytes": ZIP_MAX_BYTES,
            "zip_max_bytes_phone": ZIP_MAX_BYTES_PHONE}


LIVE = ("uploading", "ready")     # items still in a drive (doomed ones are on their way out)


def parent_chain(conn, item_id: str) -> list:
    """The folders above an item, nearest first, as rows (walks at most MAX_DEPTH + 1 steps)."""
    chain, row = [], conn.execute("SELECT parent_id FROM items WHERE id = ?", (item_id,)).fetchone()
    while row is not None and row["parent_id"] is not None and len(chain) <= MAX_DEPTH:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (row["parent_id"],)).fetchone()
        if row is not None:
            chain.append(row)
    return chain


def within(conn, item_id: str, ancestor_id: str) -> bool:
    """True when `ancestor_id` is the item itself or a folder above it (a cycle check and a tree ticket's
    membership test, both at request time)."""
    return item_id == ancestor_id or any(r["id"] == ancestor_id for r in parent_chain(conn, item_id))


def folder_depth(conn, folder_id: str) -> int:
    """How many folders, this one included, lie between the drive's root and this folder's contents."""
    return 1 + len(parent_chain(conn, folder_id))


def subtree(conn, root_id: str, states: tuple = LIVE, limit: int = MAX_ITEMS + 1) -> list:
    """The root and everything below it in `states`, breadth first, each row with its level `lvl`."""
    marks = ",".join("?" * len(states))
    return conn.execute(
        f"WITH RECURSIVE t(id, lvl) AS (SELECT ?, 0 UNION ALL SELECT i.id, t.lvl + 1 FROM items i JOIN t "
        f"ON i.parent_id = t.id WHERE t.lvl < ? AND i.state IN ({marks})) "
        f"SELECT items.*, t.lvl FROM t JOIN items ON items.id = t.id ORDER BY t.lvl, items.id LIMIT ?",
        (root_id, MAX_DEPTH + 1, *states, limit)).fetchall()


def height(conn, item) -> int:
    """Folder levels an item brings along when it moves: 0 for a file, 1 + its deepest folder below."""
    if item["kind"] != "folder":
        return 0
    return 1 + max((r["lvl"] for r in subtree(conn, item["id"]) if r["kind"] == "folder"), default=0)


def children(conn, folder_id: str) -> int:
    marks = ",".join("?" * len(LIVE))
    return conn.execute(f"SELECT COUNT(*) FROM items WHERE parent_id = ? AND state IN ({marks})",
                        (folder_id, *LIVE)).fetchone()[0]


def drive_items(conn, owner_id: str) -> int:
    marks = ",".join("?" * len(LIVE))
    return conn.execute(f"SELECT COUNT(*) FROM items WHERE owner_id = ? AND state IN ({marks})",
                        (owner_id, *LIVE)).fetchone()[0]


# --- checks for what goes into a folder (handlers/folders.py, handlers/uploads.py) -------------------

def target_folder(conn, folder_id, identity):
    """The folder something goes into: this drive's own, ready, outside the Trash."""
    folder = conn.execute("SELECT * FROM items WHERE id = ?", (folder_id,)).fetchone()
    if folder is None or folder["owner_id"] != identity["id"] or folder["state"] != "ready":
        raise ApiError(403, "forbidden", "That folder isn't in this drive.", details={"field": "parent_id"})
    if folder["kind"] != "folder":
        raise invalid("parent_id", "That item isn't a folder.")
    if folder["trashed_at"] is not None:
        raise ApiError(409, "trashed", "That folder is in the Trash.")
    return folder


def check_room(conn, folder, adding: int = 1) -> None:
    if children(conn, folder["id"]) + adding > MAX_CHILDREN:
        raise ApiError(409, "folder_full", "This folder holds as many items as it can.",
                       details={"max_children": MAX_CHILDREN})


def parent_fields(body: dict, conn, identity) -> tuple[str | None, bytes | None]:
    """(`parent_id`, `parent_wrap`) for a new item: both or neither. Raises before any write."""
    parent_id = body.get("parent_id")
    if parent_id is None:
        if body.get("parent_wrap") is not None:
            raise invalid("parent_wrap")
        return None, None
    if not isinstance(parent_id, str) or len(parent_id) != 22:
        raise invalid("parent_id")
    wrap = get_b64(body, "parent_wrap", PARENT_WRAP_LEN)
    target_folder(conn, parent_id, identity)
    return parent_id, wrap
