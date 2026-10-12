# SPDX-License-Identifier: MIT
"""The hourly canary and the daily evidence payment (spec §8.4), through the worker and the fakes:
seal → evidence delivery → mirror → the robot locker's keys open it → the link opens once → (P1) reveal."""
import json
import unittest

from harness import Stack
from mutis import codec, db
from mutis.walletd import Walletd


class Canary(unittest.TestCase):
    def setUp(self):
        self.s = Stack(chain=True)
        self.w = self.s.worker
        self.w.setup()
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "evidence_pay_day", codec.day(self.s.now))

    def tearDown(self):
        self.s.close()

    def tick(self, seconds: int = 10, times: int = 1) -> None:
        for _ in range(times):
            self.s.now += seconds
            self.w.tick()

    def test_canary_round_trip_and_reveal(self):
        s = self.s
        self.w.tick()
        log = db.get_meta_json(s.conn, "canary_log")
        self.assertEqual([e["n"] for e in log], [1])
        entry = log[0]
        self.assertEqual(s.request("GET", "/api/v1/canary")[0], 404)       # not delivered yet
        self.tick(10, 6)
        log = db.get_meta_json(s.conn, "canary_log")
        self.assertTrue(log[0]["delivery_tx"])
        self.assertTrue(log[0]["verified"])
        status, _, canary = s.request("GET", "/api/v1/canary")
        self.assertEqual((status, canary["n"], canary["delivery_tx"]), (200, 1, log[0]["delivery_tx"]))
        job = s.conn.execute("SELECT evidence, slice, result FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
        self.assertEqual((job["evidence"], job["slice"]), (1, "evidence"))
        self.assertEqual(len(json.loads(job["result"])["utxo_ids"]), 2)
        views = s.conn.execute("SELECT views_used FROM shares WHERE id = ?", (entry["share_id"],)).fetchone()[0]
        self.assertEqual(views, 1)                                           # opened once by the health check
        self.assertTrue(db.get_meta_json(s.conn, "chain_status")["canary"]["opened"])
        transfer = next(t for t in s.chain.transfers if t["destination"] == s.robot["address"])
        self.assertRegex(transfer["memo"]["Message"], r"^https://test\.mutis\.invalid/t#3[A-Za-z0-9_-]{167}$")
        self.assertEqual(s.request("GET", "/api/v1/stats/wall")[2]["canary"]["size_stored"], 4112)

        s.now += 25 * 3600
        s.run_cleanup()                    # its link expired; a canary stays for 48 h so it can be revealed
        self.assertEqual(s.conn.execute("SELECT state FROM items WHERE id = ?", (entry["item_id"],)).fetchone()[0],
                         "ready")
        self.w.tick()
        revealed = s.request("GET", "/api/v1/canary")[2]["revealed"]
        self.assertEqual([r["n"] for r in revealed], [1])
        self.assertEqual(set(revealed[0]), {"n", "sealed_at", "raw", "fk", "header", "meta_ct", "size_stored"})
        self.assertEqual(len(codec.unb64u(revealed[0]["fk"])), 32)
        status, _, raw = s.request("GET", revealed[0]["raw"])
        self.assertEqual((status, len(raw)), (200, 4112))
        s.now += 24 * 3600
        s.run_cleanup()
        self.assertEqual(s.conn.execute("SELECT state FROM items WHERE id = ?", (entry["item_id"],)).fetchone()[0],
                         "deleted")

    def test_a_key_the_restarted_verifier_lost_is_published_as_missed(self):
        """App-core review L8: the sidecar keeps canary keys in memory; after a restart that hour shows as
        missed, never skipped, and the worker doesn't ask again."""
        s = self.s
        self.w.tick()
        self.tick(10, 6)
        self.w.sidecar.stop()                 # the next request starts a fresh sidecar that knows no canary
        s.now += 25 * 3600
        self.w.tick()
        revealed = s.request("GET", "/api/v1/canary")[2]["revealed"]
        sealed_at = db.get_meta_json(s.conn, "canary_log")[0]["sealed_at"]
        self.assertEqual(revealed, [{"n": 1, "sealed_at": sealed_at, "missed": True}])
        calls = []
        self.w.sidecar.request = lambda cmd, **fields: calls.append(cmd) or {}
        self.w.last.pop("reveal")
        self.w._reveal_canaries(s.now)
        self.assertNotIn("reveal", calls)

    def test_status_says_whether_the_verifier_answers(self):
        """Before the first canary is in the mirror there is nothing to scan; the status (the healthcheck's
        chain_worker check) still says whether the verifier runs."""
        s = self.s
        self.w.write_status(s.now)
        status = db.get_meta_json(s.conn, "chain_status")
        self.assertEqual((status["sidecar_ok"], status["sidecar"]["version"]), (True, "fake"))
        self.w.sidecar.stop()
        self.w.sidecar.argv = [str(s.tmp / "no-such-sidecar")]
        self.w.write_status(s.now)
        self.assertFalse(db.get_meta_json(s.conn, "chain_status")["sidecar_ok"])

    def test_status_says_when_walletd_stops_answering(self):
        """The healthcheck reads walletd's state from the status, so a walletd that doesn't answer must be
        written down at the next status, not left as the last good one until the status goes stale."""
        s = self.s
        self.w.write_status(s.now)
        self.assertTrue(db.get_meta_json(s.conn, "chain_status")["walletd_ok"])
        self.w.walletd = Walletd("http://127.0.0.1:9/json_rpc")
        s.now += 20
        self.w.write_status(s.now)
        status = db.get_meta_json(s.conn, "chain_status")
        self.assertEqual((status["walletd_ok"], status["updated_at"]), (False, s.now))

    def test_hourly_cadence(self):
        self.w.tick()
        self.tick(600, 5)
        self.assertEqual(len(db.get_meta_json(self.s.conn, "canary_log")), 1)
        self.tick(600, 2)
        self.assertEqual(len(db.get_meta_json(self.s.conn, "canary_log")), 2)

    def test_daily_evidence_payment(self):
        s = self.s
        with db.tx(s.conn):
            db.del_meta(s.conn, "evidence_pay_day")
            db.set_meta(s.conn, "canary_log", [{"n": 1, "sealed_at": s.now + 10 ** 6, "delivery_tx": "x",
                                                "verified": True, "fk": None}])
        self.tick(10, 3)
        inv = s.conn.execute("SELECT * FROM invoices").fetchone()
        self.assertEqual((inv["identity_id"], inv["status"]), (None, "credited"))
        job = s.conn.execute("SELECT * FROM jobs WHERE kind = 'demo_pay'").fetchone()
        self.assertEqual((job["evidence"], job["slice"], job["state"]), (1, "evidence", "done"))
        self.assertIn("utxo_ids", json.loads(job["result"]))
        self.tick(10, 3)
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)    # once a day


if __name__ == "__main__":
    unittest.main()
