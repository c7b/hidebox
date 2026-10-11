# SPDX-License-Identifier: MIT
"""Gate G3: the UTXO mirror. Parsing is checked against responses recorded from ootle-indexer-b on
2026-10-11 (public chain data, tests/fixtures/), and the worker's cursor logic against the fake indexer."""
import json
import unittest
from pathlib import Path

from harness import Stack
from mutis import chain_worker, db, indexer
from mutis.fake_chain import FakeIndexer, fake_keys
from mutis.indexer import Indexers

FIXTURES = Path(__file__).parent / "fixtures"


class Framing(unittest.TestCase):
    def test_recorded_stream(self):
        shards = indexer.parse_stream((FIXTURES / "indexer-stream.ndjson").read_bytes())
        self.assertEqual([s["shard"] for s in shards], [1, 2])
        self.assertEqual(shards[0]["version"], 577)
        self.assertFalse(shards[0]["has_more"])
        self.assertEqual(len(shards[0]["unspent"]), 3)          # the 4th update of shard 1 is a Spent
        tag, nonce = shards[0]["unspent"][0]
        self.assertEqual((tag, nonce), (2503219696, "cc033ba8281d281753c9efb355ac4f3f4f5b6c3a5f44330075224db8dce47d14"))

    def test_recorded_fetch(self):
        entries = json.loads((FIXTURES / "indexer-fetch.json").read_text())["utxos"]
        parsed = [indexer.parse_fetched(e) for e in entries]
        self.assertTrue(all(parsed))
        self.assertEqual(set(parsed[0]), {"commitment", "nonce", "enc", "tag", "promise", "viewable", "auth"})
        # Real outputs differ in what they reveal: the first one recorded publishes a 1,000 tTARI lower bound.
        self.assertEqual([(p["promise"], p["viewable"], p["auth"]) for p in parsed],
                         [(1_000_000_000, 0, "key"), (0, 0, "key"), (0, 0, "key")])
        self.assertEqual(indexer.utxo_id(parsed[0]["commitment"]),
                         f"utxo_{'01' * 32}_{parsed[0]['commitment']}")
        self.assertIsNone(indexer.parse_fetched(["zz", {}]))
        self.assertIsNone(indexer.parse_fetched([parsed[0]["commitment"], {"output": {"output": {}}}]))

    def test_source_names(self):
        self.assertEqual(indexer.source_name("https://ootle-indexer-b.tari.com", 0), "indexer-b")
        self.assertEqual(indexer.source_name("http://127.0.0.1:9", 1), "indexer-2")


class Mirror(unittest.TestCase):
    def setUp(self):
        self.s = Stack(chain=True)
        self.w = self.s.worker
        self.limit = chain_worker.STREAM_LIMIT
        chain_worker.STREAM_LIMIT = 2

    def tearDown(self):
        chain_worker.STREAM_LIMIT = self.limit
        self.s.close()

    def rows(self) -> int:
        return self.s.conn.execute("SELECT COUNT(*) FROM chain_utxos").fetchone()[0]

    def test_cursors_paging_and_idempotence(self):
        for _ in range(7):
            self.s.chain.add_output(fake_keys()["address"], 1000, {"Message": "x"})
        self.assertEqual(self.w.mirror(self.s.now), 7)
        cursors = db.get_meta_json(self.s.conn, "mirror_cursor")
        self.assertTrue(cursors)
        self.assertEqual(self.w.mirror(self.s.now), 0)
        self.s.chain.add_output(fake_keys()["address"], 5, None)
        self.assertEqual(self.w.mirror(self.s.now), 1)
        self.assertEqual(self.rows(), 8)
        epochs = {r[0] for r in self.s.conn.execute("SELECT epoch FROM chain_utxos")}
        self.assertEqual(epochs, {self.s.chain.epoch})
        mirrored = {r[0] for r in self.s.conn.execute("SELECT id FROM chain_utxos")}
        self.assertEqual(mirrored, {f"utxo_{'01' * 32}_{o['commitment']}" for o in self.s.chain.outputs})

    def test_mirror_records_what_each_output_reveals(self):
        self.s.chain.add_output(fake_keys()["address"], 9000, None, promise=8000)
        self.w.mirror(self.s.now)
        row = self.s.conn.execute("SELECT promise, viewable, auth FROM chain_utxos").fetchone()
        self.assertEqual(tuple(row), (8000, 0, "key"))

    def test_a_switch_of_indexer_restarts_the_cursors(self):
        """Review L15: shard versions are cursors into one indexer's state; another indexer starts from 0."""
        first, second = self.s.indexer, FakeIndexer(self.s.chain)
        self.addCleanup(second.server_close)
        self.addCleanup(second.shutdown)
        self.w.indexers = Indexers([first.url, second.url], rate=1000)
        for _ in range(3):
            self.s.chain.add_output(fake_keys()["address"], 1000, None)
        self.w.mirror(self.s.now)
        self.assertEqual(db.get_meta(self.s.conn, "mirror_source"), "indexer-1")
        asked = []
        stream = self.w.indexers.stream_utxos
        self.w.indexers.stream_utxos = lambda cursors, *a: (asked.append(dict(cursors)), stream(cursors, *a))[1]
        first.shutdown()
        first.server_close()
        self.s.chain.add_output(fake_keys()["address"], 1000, None)
        self.assertEqual(self.w.mirror(self.s.now), 1)
        self.assertEqual(db.get_meta(self.s.conn, "mirror_source"), "indexer-2")
        self.assertTrue(asked[0])                                 # the old cursors went to the new indexer once
        self.assertEqual(asked[1], {})                            # then it started over from zero
        self.assertEqual(self.rows(), 4)

    def test_output_spent_before_fetch_is_skipped(self):
        self.s.chain.add_output(fake_keys()["address"], 1, None)
        self.s.chain.add_output(fake_keys()["address"], 2, None)
        self.s.chain.outputs[0]["spent"] = True
        self.assertEqual(self.w.mirror(self.s.now), 1)
        self.assertEqual(self.w.mirror(self.s.now), 0)


if __name__ == "__main__":
    unittest.main()
