# SPDX-License-Identifier: MIT
"""The @chain suite (spec §16.1 S-07, S-13): the worker's clients against real walletd, the public
indexers and the real sidecar. Manual, on the server as `drive` with the deployed config:

    MUTIS_CHAIN=1 MUTIS_CONFIG=/etc/mutis/mutis.toml python3 -I server/tests/chain/test_live_chain.py
    MUTIS_CHAIN_SEND=1 …   also sends 1,000 µT (+0.03 tTARI fee) from `sponsor` to the robot locker

Nothing here is ever pointed at anything but our own wallet and keys (t/397: no attacks on testnet).
"""
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mutis import config, db, indexer, jobs, payments  # noqa: E402
from mutis.chain_worker import Worker  # noqa: E402
from mutis.config import PINNED_WASM_SHA256  # noqa: E402
from mutis.sidecar import Sidecar  # noqa: E402
from mutis.walletd import Walletd  # noqa: E402

LIVE = os.environ.get("MUTIS_CHAIN") == "1"


@unittest.skipUnless(LIVE, "set MUTIS_CHAIN=1 (on the server, as drive)")
class LiveChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = config.load()
        cls.walletd = Walletd(cls.cfg["ootle"]["walletd_url"])
        cls.indexers = indexer.Indexers(cls.cfg["ootle"]["indexers"])
        cls.sidecar = Sidecar(cls.cfg.sidecar_argv(), "http://" + cls.cfg["listen"],
                              cls.cfg["sidecar"]["expected_wasm_sha256"])

    @classmethod
    def tearDownClass(cls):
        cls.sidecar.stop()

    def test_walletd(self):
        info = self.walletd.info()
        self.assertEqual((info["network"], info["network_byte"]), ("esmeralda", 38))
        self.assertGreater(self.walletd.stealth_balance_ut(self.cfg["ootle"]["sponsor_account"]), 200_000_000)

    def test_indexer_framing(self):
        shards, source = self.indexers.stream_utxos({}, 3)
        self.assertRegex(source, r"^indexer-")
        pairs = [p for s in shards for p in s["unspent"]][:5]
        self.assertTrue(pairs)
        fetched = self.indexers.fetch_utxos(pairs)
        self.assertTrue(fetched)
        out = next(iter(fetched.values()))
        self.assertIsInstance(out["promise"], int)                   # what each output reveals is read, not assumed
        self.assertIn(out["viewable"], (0, 1))
        self.assertIsInstance(out["auth"], str)
        status, data, _ = self.indexers.call("GET", f"/substates/{indexer.utxo_id(out['commitment'])}?include_proof=true")
        self.assertEqual(status, 200)
        self.assertIs(json.loads(data)["verified"], True)

    def test_committed_outcomes(self):
        """Review H3 against the real indexers: a live UTXO is `ok` on each, an unknown id is `missing`."""
        shards, _ = self.indexers.stream_utxos({}, 2)
        out = next(iter(self.indexers.fetch_utxos([p for s in shards for p in s["unspent"]][:5]).values()))
        live, absent = indexer.utxo_id(out["commitment"]), indexer.utxo_id(secrets.token_hex(32))
        for position in range(len(self.indexers.upstreams)):
            self.assertEqual(payments.committed_on_indexer(self.indexers, live, position), "ok")
            self.assertEqual(payments.committed_on_indexer(self.indexers, absent, position), "missing")
        self.assertEqual(payments.committed_anywhere(self.indexers, absent), "missing")

    def test_full_mirror_sync(self):
        """Gate G3 end to end: the worker's mirror fills a throwaway database from the live indexers."""
        tmp = tempfile.mkdtemp()
        try:
            cfg = config.from_dict({"data_dir": tmp, "secret_key": "/dev/null",
                                    "ootle": {"indexers": list(self.cfg["ootle"]["indexers"])}})
            db.migrate(cfg.db_path)
            worker = Worker(cfg, bytes(32), None, self.indexers, None)
            started = time.time()
            rows = worker.mirror(int(started))
            self.assertGreater(rows, 0)
            self.assertEqual(worker.mirror(int(time.time())), 0)
            print(json.dumps({"rows": rows, "seconds": round(time.time() - started, 1)}), file=sys.stderr)
        finally:
            shutil.rmtree(tmp)

    def test_real_sidecar(self):
        """G4 on the server side: the pinned wasm, the crafted-mismatch selftest, and 'not ours' scans."""
        self.assertEqual(self.cfg["sidecar"]["expected_wasm_sha256"], PINNED_WASM_SHA256)
        self.assertTrue(self.sidecar.request("selftest")["passed"])
        self.assertEqual(self.sidecar.info["wasm_sha256"], PINNED_WASM_SHA256)
        keys = self.sidecar.request("newKeys")
        shards, _ = self.indexers.stream_utxos({}, 2)
        fetched = self.indexers.fetch_utxos([p for s in shards for p in s["unspent"]][:20])
        rows = [{"id": indexer.utxo_id(o["commitment"]), "nonce": o["nonce"], "enc": o["enc"]} for o in fetched.values()]
        self.assertEqual(self.sidecar.request("scan", view_sk=keys["view_sk"], utxos=rows)["found"], [])

    @unittest.skipUnless(os.environ.get("MUTIS_CHAIN_SEND") == "1", "set MUTIS_CHAIN_SEND=1 to spend 0.031 tTARI")
    def test_relay_send_reaches_the_robot_locker(self):
        robot = json.loads(Path(self.cfg["ootle"]["robot_keys"]).read_text())
        memo = jobs.courier_memo(self.cfg.origin, 3, secrets.token_bytes(125))
        tx_id = self.walletd.stealth_transfer(self.cfg["ootle"]["sponsor_account"], robot["address"],
                                              self.cfg["ootle"]["courier_amount_ut"], memo,
                                              self.cfg["ootle"]["max_fee_transfer_ut"])
        outcome = self.walletd.wait_result(tx_id, 120)
        self.assertTrue(outcome["committed"])
        deadline, found = time.time() + 120, []
        while time.time() < deadline and not found:
            for utxo_id in outcome["utxo_ids"]:
                status, data, _ = self.indexers.call("GET", f"/substates/{utxo_id}")
                if status != 200:
                    continue
                o = json.loads(data)["substate"]["Utxo"]["output"]["output"]
                found += self.sidecar.request("scan", view_sk=robot["view_sk"], utxos=[
                    {"id": utxo_id, "nonce": o["public_nonce"], "enc": o["encrypted_data"]}])["found"]
            time.sleep(5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["value_ut"], str(self.cfg["ootle"]["courier_amount_ut"]))
        self.assertEqual(found[0]["memo"], {"Message": memo})
        print(json.dumps({"tx_id": tx_id, "utxo": found[0]["id"]}), file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
