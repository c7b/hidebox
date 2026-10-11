# SPDX-License-Identifier: MIT
"""SealLog storage and exit receipts (spec §11, brand patch P-8): an RFC 9162 Merkle tree of leaf hashes.

On a fixed cadence the chain worker pads the tree to a multiple of 64 leaves and appends the root to
the SealLog component. A new leaf has no index until that checkpoint, which places the batch in a
random order, so a leaf index says only which checkpoint committed it (spec §11.3). The log proves
what we committed to and when, never what we did with it later.
"""
import secrets
import sqlite3
import struct

from . import codec, db

PAD_TO = 64
CHECKPOINT_INTERVAL_S = 6 * 3600


def stored_leaf(item_id: str, ct_hash: bytes) -> bytes:
    return codec.sha256(b"\x00", b"mutis-leaf-v1", codec.unb64u(item_id, 16), ct_hash)


def exit_leaf(item_id: str, exit_hour: int) -> bytes:
    return codec.sha256(b"\x00", b"mutis-exit-v1", codec.unb64u(item_id, 16), struct.pack(">I", exit_hour // 3600))


def pad_leaf() -> bytes:
    return codec.sha256(b"\x00", b"mutis-pad-v1", secrets.token_bytes(32))


def append(conn: sqlite3.Connection, kind: str, leaf_hash: bytes) -> None:
    """Add a leaf (inside the caller's transaction); it gets its index at the next checkpoint."""
    conn.execute("INSERT OR IGNORE INTO seal_leaves(kind, leaf_hash) VALUES (?, ?)", (kind, leaf_hash))


# --- the tree ---------------------------------------------------------------------------------------

def levels(leaves: list[bytes]) -> list[list[bytes]]:
    """Every level of the RFC 9162 §2.1.1 tree, leaves first.

    Pairwise reduction gives the same tree as the recursive definition: the left subtree is always
    the largest power of two, so an odd last node is carried up unchanged.
    """
    tree = [list(leaves)]
    while len(tree[-1]) > 1:
        level = tree[-1]
        up = [codec.sha256(b"\x01", level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            up.append(level[-1])
        tree.append(up)
    return tree


def root(leaves: list[bytes]) -> bytes:
    return levels(leaves)[-1][0] if leaves else codec.sha256(b"")


def inclusion_proof(tree: list[list[bytes]], index: int) -> list[bytes]:
    """Audit path of RFC 9162 §2.1.3.1 for leaf `index`, leaf to root, from `levels()`."""
    if not 0 <= index < len(tree[0]):
        raise IndexError("leaf index out of range")
    path = []
    for level in tree[:-1]:
        sibling = index ^ 1
        if sibling < len(level):          # a carried-up last node has no sibling at this level
            path.append(level[sibling])
        index //= 2
    return path


def verify_inclusion(leaf: bytes, index: int, size: int, path: list[bytes], expected_root: bytes) -> bool:
    """RFC 9162 §2.1.3.2 verification (used by tests and documented for /verify)."""
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = codec.sha256(b"\x01", p, r)
            while not fn & 1 and fn:
                fn >>= 1
                sn >>= 1
        else:
            r = codec.sha256(b"\x01", r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == expected_root


# --- storage ----------------------------------------------------------------------------------------

def leaf_hashes(conn: sqlite3.Connection, size: int) -> list[bytes]:
    return [row[0] for row in conn.execute("SELECT leaf_hash FROM seal_leaves WHERE idx < ? ORDER BY idx", (size,))]


def leaf_index(conn: sqlite3.Connection, leaf_hash: bytes) -> int | None:
    row = conn.execute("SELECT idx FROM seal_leaves WHERE leaf_hash = ?", (leaf_hash,)).fetchone()
    return row[0] if row else None


def make_checkpoint(conn: sqlite3.Connection, now: int, rng=secrets.SystemRandom()) -> dict:
    """Place every new leaf, with pad leaves up to the next multiple of 64, in a random order after the
    leaves already placed, and record a pending checkpoint. Caller holds a transaction.
    Returns {"idx", "tree_size", "root"}."""
    placed = conn.execute("SELECT COUNT(*) FROM seal_leaves WHERE idx IS NOT NULL").fetchone()[0]
    waiting = conn.execute("SELECT COUNT(*) FROM seal_leaves WHERE idx IS NULL").fetchone()[0]
    for _ in range(-(placed + waiting) % PAD_TO):
        append(conn, "pad", pad_leaf())
    batch = [row[0] for row in conn.execute("SELECT rowid FROM seal_leaves WHERE idx IS NULL")]
    rng.shuffle(batch)
    for offset, rowid in enumerate(batch):
        conn.execute("UPDATE seal_leaves SET idx = ? WHERE rowid = ?", (placed + offset, rowid))
    size = placed + len(batch)
    tree_root = root(leaf_hashes(conn, size))
    idx = conn.execute("INSERT INTO seal_checkpoints(tree_size, root, created_at, state) VALUES (?, ?, ?, 'pending') "
                       "RETURNING idx", (size, tree_root, now)).fetchone()[0]
    db.set_meta(conn, "seal_last_at", str(now))
    return {"idx": idx, "tree_size": size, "root": tree_root}


def mark_submitted(conn: sqlite3.Connection, idx: int, tx_id: str, now: int) -> None:
    conn.execute("UPDATE seal_checkpoints SET tx_id = ?, submitted_at = ? WHERE idx = ?", (tx_id, now, idx))


def checkpoint(conn: sqlite3.Connection, idx: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM seal_checkpoints WHERE idx = ?", (idx,)).fetchone()


def submitted(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM seal_checkpoints WHERE state = 'pending' AND tx_id IS NOT NULL").fetchall()


def settle(conn: sqlite3.Connection, idx: int, state: str, epoch: int | None) -> None:
    conn.execute("UPDATE seal_checkpoints SET state = ?, epoch = ? WHERE idx = ? AND state = 'pending'",
                 (state, epoch, idx))


def recover(conn: sqlite3.Connection) -> None:
    """A checkpoint made but never submitted (the worker stopped in between) is failed; the next one
    commits its leaves."""
    conn.execute("UPDATE seal_checkpoints SET state = 'failed' WHERE state = 'pending' AND tx_id IS NULL")


def latest_committed(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM seal_checkpoints WHERE state = 'committed' ORDER BY idx DESC LIMIT 1").fetchone()


def checkpoint_json(row: sqlite3.Row) -> dict:
    return {"index": row["idx"], "tree_size": row["tree_size"], "root": row["root"].hex(), "epoch": row["epoch"],
            "tx_id": row["tx_id"], "created_at": row["created_at"]}


def next_checkpoint_eta(conn: sqlite3.Connection, now: int) -> int:
    last = int(db.get_meta(conn, "seal_last_at", "0"))
    return max(now, last + CHECKPOINT_INTERVAL_S)
