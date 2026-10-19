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

    def restart(self) -> None:
        """mutis-chain restarts (a deploy): a new worker and a new sidecar process that knows no canary key."""
        self.w.sidecar.stop()
        self.w.conn.close()
        self.w = self.s.start_worker()
        self.w.setup()

    def wrapped_key(self, share_id: str):
        return self.s.conn.execute("SELECT wrapped_key FROM shares WHERE id = ?", (share_id,)).fetchone()[0]

    def test_a_restart_loses_no_key(self):
        """owner-5: the sidecar keeps canary keys in memory, so a restart used to publish every hour younger than a
        day as missed. Now the key comes back from the Ootle: the delivery, sealed to our test drive, holds the
        link's secret, which opens the copy of the link's wrapped key the log kept after the link expired."""
        s = self.s
        self.w.tick()
        self.tick(10, 6)
        entry = db.get_meta_json(s.conn, "canary_log")[0]
        self.assertTrue(entry["verified"])
        self.assertEqual(codec.unb64u(entry["wrap"]), self.wrapped_key(entry["share_id"]))
        fk = self.w.sidecar.request("reveal", n=1)["fk"]          # what the sidecar sealed, before it forgets
        self.restart()
        s.now += 25 * 3600
        s.run_cleanup()
        self.assertIsNone(self.wrapped_key(entry["share_id"]))   # the link expired and lost its wrapped key
        self.w.tick()
        revealed = s.request("GET", "/api/v1/canary")[2]["revealed"]
        self.assertEqual([(r["n"], r.get("fk"), r.get("missed")) for r in revealed], [(1, fk, None)])
        self.assertIsNone(db.get_meta_json(s.conn, "canary_log")[0]["wrap"])    # the copy leaves with the reveal

    def test_a_canary_sealed_before_the_log_kept_copies_gets_one_while_its_link_lives(self):
        """The deploy that brings the copies: canaries already sealed get theirs at the new worker's first tick,
        while their links are active, so that restart loses none of them either."""
        s = self.s
        self.w.tick()
        self.tick(10, 6)
        log = db.get_meta_json(s.conn, "canary_log")
        del log[0]["wrap"]
        with db.tx(s.conn):
            db.set_meta(s.conn, "canary_log", log)
        fk = self.w.sidecar.request("reveal", n=1)["fk"]
        self.restart()
        self.w.tick()
        entry = db.get_meta_json(s.conn, "canary_log")[0]
        self.assertEqual(codec.unb64u(entry["wrap"]), self.wrapped_key(entry["share_id"]))
        s.now += 25 * 3600
        s.run_cleanup()
        self.w.tick()
        self.assertEqual(s.request("GET", "/api/v1/canary")[2]["revealed"][0]["fk"], fk)

    def test_a_key_neither_the_verifier_nor_the_chain_gives_back_is_published_as_missed(self):
        """App-core review L8: an hour whose key can't be had shows as missed, never skipped, and the worker
        doesn't ask again. Here one canary has no copy of its wrapped key (its link ended before the log kept
        copies) and the other a copy that isn't its link's: the delivery's secret doesn't open it."""
        s = self.s
        self.w.tick()
        self.tick(10, 6)
        self.tick(3600)
        self.tick(10, 6)
        log = db.get_meta_json(s.conn, "canary_log")
        self.assertEqual([(e["n"], e["verified"]) for e in log], [(1, True), (2, True)])
        log[0]["wrap"] = codec.b64u(bytes(60))
        del log[1]["wrap"]
        with db.tx(s.conn):
            db.set_meta(s.conn, "canary_log", log)
        s.now += 26 * 3600
        s.run_cleanup()
        self.restart()
        self.w.tick()
        revealed = s.request("GET", "/api/v1/canary")[2]["revealed"]
        self.assertEqual(revealed, [{"n": e["n"], "sealed_at": e["sealed_at"], "missed": True} for e in reversed(log)])
        calls = []
        self.w.sidecar.request = lambda cmd, **fields: calls.append(cmd) or {}
        self.w.last.pop("reveal")
        self.w._reveal_canaries(s.now)
        self.assertEqual(calls, [])

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
