# SPDX-License-Identifier: MIT
"""Schema migrations: a deployed schema-1 database migrates (002, 003, 004) to exactly the schema a fresh
install gets, and keeps its rows the way the review fixes and the drive need them."""
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from harness import START
from mutis import db

FIXTURE = Path(__file__).with_name("fixtures") / "schema-v1.sql"


def normalized_schema(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
    finally:
        conn.close()
    out = {}
    for kind, name, sql in rows:
        text = re.sub(r"\s+", " ", sql)
        text = re.sub(r"\s*([(),])\s*", r"\1", text)
        out[(kind, name)] = text.replace('"', "")      # ALTER TABLE … RENAME quotes the new name
    return out


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-schema-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def v1_database(self) -> Path:
        path = self.tmp / "v1.sqlite3"
        conn = db.connect(path)
        with db.tx(conn):
            for statement in db._statements(FIXTURE.read_text()):
                conn.execute(statement)
            db.set_meta(conn, "schema_version", "1")
            for job_id, kind in (("courier-job", "courier"), ("seal-job", "seal")):
                conn.execute("INSERT INTO jobs(id, kind, slice, payload, state, not_before, created_at, updated_at) "
                             "VALUES (?, ?, 'reserved', '{}', 'queued', ?, ?, ?)", (job_id, kind, START, START, START))
            for idx in range(70):
                conn.execute("INSERT INTO seal_leaves(idx, kind, leaf_hash) VALUES (?, 'stored', ?)",
                             (idx, bytes([idx]) * 32))
            conn.execute("INSERT INTO seal_checkpoints(tree_size, root, created_at, state, tx_id, epoch) "
                         "VALUES (64, x'00', ?, 'committed', 'tx-a', 12000)", (START,))
            conn.execute("INSERT INTO seal_checkpoints(tree_size, root, created_at, state, job_id) "
                         "VALUES (128, x'01', ?, 'pending', 'seal-job')", (START,))
            conn.execute("INSERT INTO judge_passes(code_hash, uses_left, created_at) VALUES (x'aa', 5, ?)", (START,))
            conn.execute("INSERT INTO chain_utxos(id, nonce, enc, first_seen) VALUES ('utxo_x', x'00', x'00', ?)",
                         (START,))
        conn.close()
        return path

    def test_migrated_schema_equals_a_fresh_one(self):
        old = self.v1_database()
        self.assertEqual(db.migrate(old), db.SCHEMA_VERSION)
        fresh = self.tmp / "fresh.sqlite3"
        self.assertEqual(db.migrate(fresh), db.SCHEMA_VERSION)
        self.assertEqual(normalized_schema(old), normalized_schema(fresh))

    def test_a_new_database_is_group_writable(self):
        """Under the services' umask 007, the database and its -wal/-shm files are 0660 (group mutis)."""
        old = os.umask(0o007)
        try:
            path = self.tmp / "new.sqlite3"
            db.migrate(path)
            conn = db.connect(path)
            conn.execute("SELECT COUNT(*) FROM meta").fetchone()
            modes = {p.name: stat.S_IMODE(p.stat().st_mode) for p in self.tmp.glob("new.sqlite3*")}
            conn.close()
        finally:
            os.umask(old)
        self.assertEqual(modes, {"new.sqlite3": 0o660, "new.sqlite3-wal": 0o660, "new.sqlite3-shm": 0o660})

    def test_rows_after_migration(self):
        path = self.v1_database()
        db.migrate(path)
        conn = db.connect(path)
        try:
            self.assertEqual([r[0] for r in conn.execute("SELECT kind FROM jobs")], ["courier"])   # no seal jobs
            placed = conn.execute("SELECT COUNT(*) FROM seal_leaves WHERE idx IS NOT NULL").fetchone()[0]
            waiting = conn.execute("SELECT COUNT(*) FROM seal_leaves WHERE idx IS NULL").fetchone()[0]
            self.assertEqual((placed, waiting), (64, 6))      # only the committed checkpoint's leaves keep an index
            states = [r[0] for r in conn.execute("SELECT state FROM seal_checkpoints ORDER BY idx")]
            self.assertEqual(states, ["committed", "failed"])
            self.assertEqual(conn.execute("SELECT uses_left, pow_skips_left FROM judge_passes").fetchone()[:], (5, 100))
            self.assertEqual(conn.execute("SELECT promise, viewable, auth FROM chain_utxos").fetchone()[:],
                             (None, None, None))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO jobs(id, kind, slice, state, not_before, created_at, updated_at) "
                             "VALUES ('x', 'seal', 'evidence', 'queued', 0, 0, 0)")
            conn.execute("INSERT INTO jobs(id, kind, slice, state, not_before, created_at, updated_at) "
                         "VALUES ('y', 'courier', 'evidence', 'queued', 0, 0, 0)")
        finally:
            conn.close()

    def v3_database(self) -> Path:
        """The deployed schema 3 with data in it: the v1 fixture through migrations 002 and 003 only."""
        path = self.v1_database()
        only = self.tmp / "to-v3"
        only.mkdir()
        for file in sorted(db.MIGRATIONS.glob("00[23]_*.sql")):
            (only / file.name).write_text(file.read_text())
        self.assertEqual(db.migrate(path, only), 3)
        conn = db.connect(path)
        with db.tx(conn):
            conn.execute("INSERT INTO identities(id, auth_verifier, created_day, last_seen_day, used_bytes) "
                         "VALUES ('drive-a', x'01', '2026-10-01', '2026-10-13', 2048)")
            conn.execute("INSERT INTO items(id, owner_id, manage_hash, retention, lane, state, header, meta_ct, "
                         "owner_wrap, chunk_count, size_stored, created_hour) VALUES ('item-a', 'drive-a', x'02', "
                         "'kept', 'locker', 'ready', x'03', x'04', x'05', 1, 2048, ?)", (START,))
            conn.execute("INSERT INTO shares(id, item_id, mode, wrapped_key, access_hash, max_views, created_hour) "
                         "VALUES ('share-a', 'item-a', 'link', x'06', x'07', 3, ?)", (START,))
            conn.execute("INSERT INTO tickets(token_hash, share_id, item_id, expires_at, max_bytes) "
                         "VALUES (x'08', 'share-a', 'item-a', ?, 6144)", (START + 1800,))
        conn.close()
        return path

    def test_upgrade_from_v3_with_data(self):
        """Migration 004 (16-drive-design §15 step 1) is additive: every row of a schema-3 database keeps
        working as a file at the drive's root, outside the Trash, with an item ticket; the new tables start
        empty and the foreign keys hold."""
        path = self.v3_database()
        self.assertEqual(db.migrate(path), 5)               # 004, then 005 (the owner's check of sales)
        conn = db.connect(path)
        try:
            item = conn.execute("SELECT kind, parent_id, parent_wrap, trashed_at, items.state, used_bytes FROM items "
                                "JOIN identities ON identities.id = items.owner_id").fetchone()
            self.assertEqual(tuple(item), ("file", None, None, None, "ready", 2048))
            self.assertEqual(conn.execute("SELECT scope FROM tickets").fetchone()[0], "item")
            self.assertEqual(conn.execute("SELECT state, max_views FROM shares").fetchone()[:], ("active", 3))
            for table in ("share_opens", "sellers", "paid_shares", "claims", "sale_payments"):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE items SET kind = 'link' WHERE id = 'item-a'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE tickets SET scope = 'drive'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO claims(id, share_id, token_hash, address, price_ut, status, owner_check, "
                             "created_at, created_seq, expires_at) VALUES ('clm_x', 'share-a', x'09', 'a', 1, "
                             "'pending', 'maybe', 0, 0, 0)")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO sale_payments(utxo_id, value_ut, seen_at, status, owner_ok) "
                             "VALUES ('utxo_y', 1, 0, 'counted', 2)")
            conn.execute("INSERT INTO share_opens(share_id, hour, n) VALUES ('share-a', ?, 2)", (START,))
            conn.execute("DELETE FROM shares WHERE id = 'share-a'")       # the tombstone purge cascades
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM share_opens").fetchone()[0], 0)
        finally:
            conn.close()

    def test_connections_zero_deleted_bytes(self):
        """Review L7: a scrubbed wrapped key must not linger in free pages, whatever the SQLite build."""
        conn = db.connect(self.tmp / "x.sqlite3")
        try:
            self.assertEqual(conn.execute("PRAGMA secure_delete").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
