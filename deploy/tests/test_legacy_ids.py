# SPDX-License-Identifier: MIT
"""deploy/scripts/legacy-ids.py: the frozen set of a deployment's link ids (docs/cutover.md)."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("legacy_ids", ROOT / "deploy" / "scripts" / "legacy-ids.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

SHARE, PAID, DROP, TX, SEAL = "A" * 21 + "w", "b" * 21 + "-", "3w7m8k2v5t", "ab" * 32, "cd" * 32


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="legacy-ids-"))
        self.db = self.tmp / "mutis.sqlite3"
        with sqlite3.connect(self.db) as c:
            c.executescript("CREATE TABLE shares (id TEXT PRIMARY KEY); CREATE TABLE paid_shares (share_id TEXT PRIMARY KEY);"
                            "CREATE TABLE drops (id TEXT PRIMARY KEY); CREATE TABLE jobs (result TEXT);"
                            "CREATE TABLE seal_checkpoints (tx_id TEXT);")
            c.executemany("INSERT INTO shares VALUES (?)", [(SHARE,), (PAID,), ("../../etc/passwd",), ("x/y",)])
            c.execute("INSERT INTO paid_shares VALUES (?)", (PAID,))
            c.executemany("INSERT INTO drops VALUES (?)", [(DROP,), ("ILOU000000",)])
            c.executemany("INSERT INTO jobs VALUES (?)", [(json.dumps({"tx_id": TX}),), ('{"pending_tx": 1}',), ("not json",),
                                                          (json.dumps({"tx_id": "../x"}),), (None,)])
            c.executemany("INSERT INTO seal_checkpoints VALUES (?)", [(SEAL,), (None,)])
        self.out = self.tmp / "legacy"

    def test_every_link_kind_and_nothing_else(self):
        result = legacy.export(self.db, self.out)
        self.assertEqual(result["total"], {"s": 2, "p": 1, "d": 1, "verify/tx": 2})
        files = sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file())
        self.assertEqual(files, sorted([f"s/{SHARE}", f"s/{PAID}", f"p/{PAID}", f"d/{DROP}", f"verify/tx/{TX}",
                                        f"verify/tx/{SEAL}"]))
        self.assertTrue(all(p.stat().st_size == 0 for p in self.out.rglob("*") if p.is_file()))

    def test_export_only_adds(self):
        legacy.export(self.db, self.out)
        with sqlite3.connect(self.db) as c:
            c.execute("DELETE FROM shares WHERE id = ?", (SHARE,))
            c.execute("INSERT INTO shares VALUES (?)", ("C" * 22,))
        again = legacy.export(self.db, self.out)
        self.assertEqual(again["added"]["s"], 1)
        self.assertTrue((self.out / "s" / SHARE).is_file())       # a link that ended since still goes to its deployment

    def test_check_reads_names_only(self):
        legacy.export(self.db, self.out)
        self.assertEqual(legacy.check(self.out, [f"d/{DROP}", f"s/{SHARE}", "d/0000000000", "s/../d/" + DROP, "x/y"]),
                         {f"d/{DROP}": True, f"s/{SHARE}": True, "d/0000000000": False, "s/../d/" + DROP: False, "x/y": False})

    def test_the_database_is_opened_read_only(self):
        self.db.chmod(0o444)
        legacy.export(self.db, self.out)
        self.assertFalse((self.tmp / "mutis.sqlite3-journal").exists())


if __name__ == "__main__":
    unittest.main()
