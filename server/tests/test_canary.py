# SPDX-License-Identifier: MIT
"""The hourly canary and the daily evidence payment (spec §8.4), through the worker and the fakes:
seal → evidence delivery → mirror → the robot locker's keys open it → the link opens once → (P1) reveal."""
import json
import unittest

from harness import Stack
from mutis import codec, db


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
