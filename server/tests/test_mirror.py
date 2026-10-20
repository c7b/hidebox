# SPDX-License-Identifier: MIT
"""Gate G3: the UTXO mirror. Parsing is checked against responses recorded from ootle-indexer-b on
2026-10-11 and, for GET /substates in tari_indexer 0.47.0's shape, from both indexers on 2026-10-20
(public chain data, tests/fixtures/), and the worker's cursor logic against the fake indexer."""
import http.server
import json
import os
import threading
import unittest
from pathlib import Path

from harness import Stack
from mutis import chain_worker, codec, db, indexer, mirror
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

    def test_a_malformed_stream_line_is_an_upstream_error(self):
        """security-audit-1: one bad line from one indexer is that indexer's error (the worker keeps the
        others), and no value from it sizes an allocation."""
        sos = '{"sos":{"shard":1,"max_state_version":0,"has_more":false}}'
        nonce = list(range(32))
        poisons = [
            '{"update":{"Unspent":{"tag":1,"public_nonce":"deadbeef"}}}',
            '{"update":{"Unspent":{"tag":1,"public_nonce":50000000}}}',
            '{"update":{"Unspent":{"tag":1,"public_nonce":%s}}}' % json.dumps(nonce[:31]),
            '{"update":{"Unspent":{"tag":true,"public_nonce":%s}}}' % json.dumps(nonce),
            '{"update":{"Unspent":{"tag":-1,"public_nonce":%s}}}' % json.dumps(nonce),
            '{"update":{"Unspent":[]}}',
            '{"eos":{"max_state_version":"1"}}',
            "[]",
            "not json",
        ]
        for poison in poisons:
            with self.subTest(poison=poison[:40]), self.assertRaises(indexer.IndexerError):
                indexer.parse_stream(f"{sos}\n{poison}\n".encode())
        for bad_sos in ('{"sos":{"shard":"1","max_state_version":0,"has_more":false}}',
                        '{"sos":{"shard":1,"max_state_version":0,"has_more":"no"}}', '{"sos":[1]}'):
            with self.subTest(sos=bad_sos), self.assertRaises(indexer.IndexerError):
                indexer.parse_stream(bad_sos.encode())

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

    def test_recorded_substates_of_the_0_47_indexer(self):
        """`state.up.substate` (0.47.0) and `substate` (before) give the same value; a proven down has none."""
        recorded = json.loads((FIXTURES / "indexer-substates-0.47.0.json").read_text())
        live = recorded["live_utxo"]["body"]
        utxo = live["state"]["up"]["substate"]["Utxo"]
        self.assertEqual(indexer.substate_value(live), {"Utxo": utxo})
        self.assertEqual(indexer.substate_value({"verified": True, "substate": {"Utxo": utxo}}), {"Utxo": utxo})
        self.assertEqual(indexer.substate_output(live),
                         ("6892417fe10f69cc21abd98b963160d872e03fe9a8882d9f531e7bb3efde7a06",
                          "2adc08fe942c440039a76272abb9cdec08b0a166aecd841d020a7fe12d69c50b"))
        for name in ("live_utxo_without_proof", "live_utxo_at_version"):
            self.assertIn("Utxo", indexer.substate_value(recorded[name]["body"]), name)
            self.assertFalse(indexer.substate_down(recorded[name]["body"]), name)
        down = recorded["spent_utxo_at_version"]["body"]
        self.assertTrue(indexer.substate_down(down))
        self.assertIsNone(indexer.substate_value(down))
        self.assertEqual(indexer.substate_output(down), (None, None))
        self.assertIn("down_proof", down["proof"])
        self.assertIsNone(indexer.substate_value(recorded["spent_utxo"]["body"]))
        self.assertIn("Component", indexer.substate_value(recorded["seallog_component"]["body"]))
        # An answer with a `state` is read from it alone, never from a `substate` beside it.
        self.assertIsNone(indexer.substate_value({"state": {"down": {}}, "substate": {"Utxo": utxo}}))
        self.assertIsNone(indexer.substate_value({"state": None, "substate": {"Utxo": utxo}}))
        self.assertIsNone(indexer.substate_value({"state": {"up": {"substate": {"Utxo": utxo}}, "down": {}}}))
        for junk in (None, [], "x", {}, {"state": {"up": None}}, {"state": {"up": {"substate": []}}}):
            self.assertIsNone(indexer.substate_value(junk), junk)
        # The mirror reads a committed transaction's outputs the same way (mirror.add_committed).
        out = indexer.parse_fetched([recorded["live_utxo"]["id"].rsplit("_", 1)[1], utxo])
        self.assertEqual((out["nonce"], out["auth"], out["promise"]), (utxo["output"]["output"]["public_nonce"], "key", 0))

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

    def test_a_committed_transactions_outputs_are_read_from_the_indexer(self):
        """mirror.add_committed reads each new output with GET /substates (the fake indexer answers in
        tari_indexer 0.47.0's shape) before the stream lists it; ids that aren't TARI outputs are skipped."""
        self.s.chain.add_output(fake_keys()["address"], 1000, None, promise=10)
        o = self.s.chain.outputs[-1]
        ids = [indexer.utxo_id(o["commitment"]), f"component_{'ab' * 32}", indexer.utxo_id("cd" * 32)]
        self.assertEqual(mirror.add_committed(self.s.conn, self.w.indexers, ids, 7, self.s.now), 1)
        row = self.s.conn.execute("SELECT id, epoch, promise, auth FROM chain_utxos").fetchone()
        self.assertEqual(tuple(row), (ids[0], 7, 10, "key"))
        self.assertEqual(self.w.mirror(self.s.now), 0)            # the stream's copy is the same row

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

    def test_a_hostile_indexer_cant_stop_the_others(self):
        """security-audit-1: an indexer that streams a malformed record, or answers /utxos/fetch with
        garbage, is skipped like one that is down; the other indexers are still mirrored."""
        nonce = json.dumps(list(range(32)))
        answers = {
            "stream": ('{"sos":{"shard":1,"max_state_version":0,"has_more":false}}\n'
                       '{"update":{"Unspent":{"tag":1,"public_nonce":"deadbeef"}}}\n'),
            "fetch": ('{"sos":{"shard":1,"max_state_version":0,"has_more":false}}\n'
                      '{"update":{"Unspent":{"tag":1,"public_nonce":%s}}}\n' % nonce),
        }
        for case, stream in answers.items():
            class Hostile(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    self.rfile.read(int(self.headers.get("Content-Length") or 0))
                    body = (stream if self.path == "/utxos/stream" else "[]").encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                do_GET = do_POST

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hostile)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            with self.subTest(case=case):
                before = self.rows()
                self.w.indexers = Indexers([f"http://127.0.0.1:{server.server_address[1]}", self.s.indexer.url],
                                           rate=1000)
                for _ in range(3):
                    self.s.chain.add_output(fake_keys()["address"], 1000, None)
                self.s.now += 10
                self.assertEqual(self.w.mirror(self.s.now), 3)
                self.assertEqual(self.rows(), before + 3)
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
