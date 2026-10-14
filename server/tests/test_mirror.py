# SPDX-License-Identifier: MIT
"""Gate G3: the UTXO mirror. Parsing is checked against responses recorded from ootle-indexer-b on
2026-10-11 (public chain data, tests/fixtures/), and the worker's cursor logic against the fake indexer."""
import json
import os
import unittest
from pathlib import Path

from harness import Stack
from mutis import chain_worker, codec, db, indexer
from mutis.fake_chain import FakeChain, FakeIndexer, fake_keys
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
        self.assertEqual(set(parsed[0]), {"commitment", "nonce", "enc", "tag", "promise", "viewable", "auth",
                                          "auth_key"})
        # R1: the one-time key that alone can spend the output is kept for the ownership check.
        self.assertEqual(parsed[0]["auth_key"], "7a3eb2cc0d4e0aa116283bd1c843602f3f2516d281d15ce923a970bac4d64322")
        self.assertIsNone(indexer.one_time_key({"auth": {"Script": "00" * 32}}))
        self.assertIsNone(indexer.one_time_key({"auth": {"Key": "zz" * 32}}))
        substate = {"verified": True, "substate": {"Utxo": {"output": entries[0][1]["output"], "is_frozen": False}}}
        self.assertEqual(indexer.substate_output(substate),
                         (parsed[0]["auth_key"], parsed[0]["nonce"]))
        self.assertEqual(indexer.substate_output({"verified": True, "substate": {"Utxo": {}}}), (None, None))
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
        cursors = db.get_meta_json(self.s.conn, "mirror_cursors")
        self.assertTrue(cursors["indexer-1"])
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

    def test_every_indexer_is_mirrored_with_its_own_cursors(self):
        """A stale indexer (it answers, but its stream stopped advancing) hides nothing another one streams;
        shard versions are cursors into one indexer's state (review L15), so each keeps its own."""
        live = self.s.indexer
        stale = FakeIndexer(FakeChain())
        self.addCleanup(stale.server_close)
        self.addCleanup(stale.shutdown)
        self.w.indexers = Indexers([stale.url, live.url], rate=1000)
        for _ in range(3):
            self.s.chain.add_output(fake_keys()["address"], 1000, None)
        self.assertEqual(self.w.mirror(self.s.now), 3)
        cursors = db.get_meta_json(self.s.conn, "mirror_cursors")
        self.assertEqual(cursors["indexer-1"], {})
        self.assertTrue(cursors["indexer-2"])
        stale.shutdown()
        stale.server_close()
        self.s.chain.add_output(fake_keys()["address"], 1000, None)
        self.s.now += 10
        self.assertEqual(self.w.mirror(self.s.now), 1)            # one indexer down: the other still feeds it
        self.assertEqual(self.w.status["mirror_ok_at"], self.s.now)
        self.assertEqual(self.rows(), 4)
        live.shutdown()
        live.server_close()
        with self.assertRaises(indexer.IndexerError):            # none answers: the mirror is not current
            self.w.mirror(self.s.now + 10)
        self.assertEqual(self.w.status["mirror_ok_at"], self.s.now)

    def test_our_own_outputs_are_mirrored_when_they_commit(self):
        """The indexers stream an output only once the network's consensus epoch reaches it; the outputs of
        a transaction we sent (the delivery and its change) are in the mirror as soon as it commits."""
        s = self.s
        s.worker.setup()
        s.quiet_chain()
        drop = s.drop()
        status, _, body = s.request("POST", "/api/v1/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                               "blob": codec.b64u(os.urandom(125)), "pow": s.solve("courier")})
        self.assertEqual(status, 202, body)
        s.now += 46
        s.worker.run_jobs(s.now)                  # no stream poll in between
        outputs = s.chain.transfers[-1]["outputs"]
        mirrored = {r[0] for r in s.conn.execute("SELECT id FROM chain_utxos")}
        self.assertEqual(len(outputs), 2)
        self.assertTrue(set(outputs) <= mirrored)
        self.assertEqual(self.w.mirror(s.now), 0)  # the stream brings them again later: nothing doubles

    def test_output_spent_before_fetch_is_skipped(self):
        self.s.chain.add_output(fake_keys()["address"], 1, None)
        self.s.chain.add_output(fake_keys()["address"], 2, None)
        self.s.chain.outputs[0]["spent"] = True
        self.assertEqual(self.w.mirror(self.s.now), 1)
        self.assertEqual(self.w.mirror(self.s.now), 0)


if __name__ == "__main__":
    unittest.main()
