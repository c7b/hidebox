# SPDX-License-Identifier: MIT
"""Schema 2 (migrations/002): a deployed schema-1 database migrates to exactly the schema a fresh
install gets, and keeps its rows the way the review fixes need them."""
import re
import shutil
import sqlite3
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

    def test_connections_zero_deleted_bytes(self):
        """Review L7: a scrubbed wrapped key must not linger in free pages, whatever the SQLite build."""
        conn = db.connect(self.tmp / "x.sqlite3")
        try:
            self.assertEqual(conn.execute("PRAGMA secure_delete").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
