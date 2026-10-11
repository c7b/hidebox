# SPDX-License-Identifier: MIT
"""S-11: the courier (spec §4.10, §10.3, §10.4) — memo from PUBLIC_ORIGIN only, blob size, drop address,
jitter, payload scrubbing, budget slices, locker and destination caps, the decoy scheduler, and sends
that never get stuck or go out twice."""
import json
import os
import random
import threading
import unittest

from harness import ORIGIN, Stack
from mutis import budgets, chain_worker, cleanup, codec, db, jobs
from mutis.fake_chain import fake_keys
from mutis.walletd import WalletdError

V = "/api/v1"


def blob(n: int = 125) -> str:
    return codec.b64u(os.urandom(n))


class Courier(unittest.TestCase):
    def setUp(self):
        self.s = Stack(chain=True)
        self.s.worker.setup()
        self.s.quiet_chain()

    def tearDown(self):
        self.s.close()

    def job(self, job_id: str):
        return self.s.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def test_memo_is_built_from_public_origin(self):
        s = self.s
        drop = s.drop()
        raw = os.urandom(125)
        status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                            "blob": codec.b64u(raw), "pow": s.solve("courier"),
                                                            "memo": "https://evil.example/phish"})
        self.assertEqual(status, 202)
        payload = json.loads(self.job(body["job_id"])["payload"])
        self.assertEqual(payload["memo"], f"{ORIGIN}/t#3{codec.b64u(raw)}")
        self.assertEqual(len(payload["memo"].encode()), len(ORIGIN) + 4 + 167)

    def test_blob_must_be_125_bytes(self):
        s = self.s
        drop = s.drop()
        for n in (124, 126):
            status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                                "blob": blob(n), "pow": s.solve("courier")})
            self.assertEqual((status, body["error"]["code"]), (422, "bad_blob"))

    def test_drop_courier_uses_the_drops_address(self):
        s = self.s
        drop = s.drop()
        status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                            "address": fake_keys()["address"], "blob": blob(),
                                                            "pow": s.solve("courier")})
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(self.job(body["job_id"])["payload"])["address"], drop["keys"]["address"])

    def test_jitter_bounds(self):
        s = self.s
        locker = s.register()
        s.graduate(locker)
        seen = []
        for _ in range(15):
            status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                                "kind": 3, "blob": blob()}, headers=locker["auth"])
            self.assertEqual(status, 202, body)
            seen.append(body["not_before"] - s.now)
        self.assertTrue(all(5 <= d <= 45 for d in seen), seen)
        self.assertGreater(len(set(seen)), 3)

    def test_payload_scrubbed_after_done_and_failed(self):
        s = self.s
        drop = s.drop()
        ok = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3, "blob": blob(),
                                                "pow": s.solve("courier")})[2]["job_id"]
        s.now += 46
        s.worker.run_jobs(s.now)
        row = self.job(ok)
        self.assertEqual((row["state"], row["payload"]), ("done", None))
        view = s.request("GET", f"{V}/jobs/{ok}")[2]
        self.assertEqual((view["state"], set(view["result"])), ("done", {"tx_id"}))
        self.assertNotIn("address", json.dumps(view))
        transfer = s.chain.transfers[-1]
        self.assertEqual((transfer["value"], transfer["memo"]["Message"][:len(ORIGIN)]), (1000, ORIGIN))
        bad = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3, "blob": blob(),
                                                 "pow": s.solve("courier")})[2]["job_id"]
        s.walletd_fake.fail_next = 100
        for step in (46, 11, 61):
            s.now += step
            s.worker.run_jobs(s.now)
        row = self.job(bad)
        self.assertEqual((row["state"], row["payload"], row["attempts"]), ("failed", None, 3))
        self.assertEqual(s.request("GET", f"{V}/jobs/{bad}")[2]["error"], "walletd_error")

    def drop_job(self) -> str:
        s = self.s
        s.heartbeat()
        drop = s.drop()
        return s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3, "blob": blob(),
                                                  "pow": s.solve("courier")})[2]["job_id"]

    def test_a_slow_transaction_is_polled_and_never_sent_twice(self):
        s = self.s
        job_id = self.drop_job()
        s.walletd_fake.wait_outcome = "timeout"
        s.now += 46
        s.worker.run_jobs(s.now)
        sent = len(s.chain.transfers)
        row = self.job(job_id)
        self.assertEqual((row["state"], set(json.loads(row["result"]))), ("sending", {"pending_tx"}))
        self.assertEqual(s.request("GET", f"{V}/jobs/{job_id}")[2]["state"], "sending")
        s.walletd_fake.wait_outcome = "commit"
        s.now += 1
        s.worker.run_jobs(s.now)
        self.assertEqual(self.job(job_id)["state"], "done")
        self.assertEqual(len(s.chain.transfers), sent)

    def test_a_transaction_that_never_settles_is_given_up_and_scrubbed(self):
        s = self.s
        job_id = self.drop_job()
        s.walletd_fake.wait_outcome = "timeout"
        s.now += 46
        s.worker.run_jobs(s.now)
        s.now += chain_worker.SEND_TIMEOUT_S
        s.worker.run_jobs(s.now)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["error"], row["payload"]), ("failed", "timeout", None))

    def test_crash_between_submit_and_result(self):
        """Review H1: the worker dies after walletd took the transfer. A restart waits for that same
        transaction; it never sends again, and the destination is scrubbed when the job ends."""
        s = self.s
        job_id = self.drop_job()
        s.now += 46
        crash = threading.Event()

        def die(tx_id, timeout_s):
            crash.set()
            raise SystemExit("worker killed")
        s.worker.walletd.wait_result = die
        with self.assertRaises(SystemExit):
            s.worker.run_jobs(s.now)
        self.assertTrue(crash.is_set())
        sent = len(s.chain.transfers)
        row = self.job(job_id)
        self.assertEqual((row["state"], set(json.loads(row["result"]))), ("sending", {"pending_tx"}))
        s.worker.conn.close()
        s.start_worker()                          # a new process
        s.worker.setup()
        s.worker.recover(s.now)
        s.worker.run_jobs(s.now + 1)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["payload"]), ("done", None))
        self.assertEqual(len(s.chain.transfers), sent)

    def test_crash_before_the_transaction_was_recorded(self):
        """Claimed but not recorded as submitted: walletd may or may not have it. The job fails as
        `interrupted` (the UI offers Try again) instead of risking a second payment."""
        s = self.s
        job_id = self.drop_job()
        s.now += 46
        s.worker.submit = lambda kind, payload: (_ for _ in ()).throw(SystemExit("worker killed"))
        with self.assertRaises(SystemExit):
            s.worker.run_jobs(s.now)
        self.assertEqual(self.job(job_id)["state"], "sending")
        s.worker.conn.close()
        s.start_worker()
        s.worker.recover(s.now)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["error"], row["payload"]), ("failed", "interrupted", None))
        self.assertEqual(s.request("GET", f"{V}/jobs/{job_id}")[2]["error"], "interrupted")

    def test_unexpected_errors_end_the_job(self):
        s = self.s
        job_id = self.drop_job()
        s.now += 46
        s.worker.submit = lambda kind, payload: {}["boom"]
        s.worker.run_jobs(s.now)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["error"], row["payload"]), ("failed", "internal", None))
        job_id = self.drop_job()
        s.now += 46
        s.worker.submit = lambda kind, payload: (_ for _ in ()).throw(WalletdError("walletd_timeout"))
        s.worker.run_jobs(s.now)
        row = self.job(job_id)                    # walletd may have taken it: no second attempt
        self.assertEqual((row["state"], row["error"], row["attempts"]), ("failed", "walletd_timeout", 1))
        job_id = self.drop_job()
        s.now += 46
        del s.worker.submit
        s.worker.walletd.wait_result = lambda tx_id, timeout_s: (_ for _ in ()).throw(WalletdError("walletd_error"))
        s.worker.run_jobs(s.now)
        self.assertEqual(self.job(job_id)["state"], "sending")      # unknown outcome: keep waiting, don't resend
        s.now += chain_worker.SEND_TIMEOUT_S
        s.worker.run_jobs(s.now)
        self.assertEqual(self.job(job_id)["state"], "failed")

    def test_cleanup_scrubs_a_send_left_by_a_dead_worker(self):
        s = self.s
        job_id = self.drop_job()
        s.now += 46
        s.worker.walletd.wait_result = lambda tx_id, timeout_s: (_ for _ in ()).throw(SystemExit("killed"))
        with self.assertRaises(SystemExit):
            s.worker.run_jobs(s.now)
        s.now += cleanup.STALE_SEND_S - 1
        self.assertEqual(s.run_cleanup()["sends_interrupted"], 0)
        s.now += 1
        self.assertEqual(s.run_cleanup()["sends_interrupted"], 1)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["error"], row["payload"]), ("failed", "interrupted", None))
        queued = self.drop_job()                  # due, but no worker comes for it
        due = self.job(queued)["not_before"]
        s.now = due + cleanup.STALE_SEND_S - 1
        self.assertEqual(s.run_cleanup()["sends_interrupted"], 0)
        s.now += 1
        self.assertEqual(s.run_cleanup()["sends_interrupted"], 1)
        self.assertEqual(self.job(queued)["payload"], None)

    def test_claim_order_puts_evidence_and_reserved_first(self):
        s = self.s
        with db.tx(s.conn):
            ids = [jobs.enqueue(s.conn, "courier", slice_, {}, s.now - age, s.now)
                   for slice_, age in (("public", 30), ("reserved", 20), ("evidence", 10))]
        order = [jobs.claim(s.conn, s.cfg["budgets"], 0, s.now)["id"] for _ in range(3)]
        self.assertEqual(order, ids[::-1])

    def test_worker_rejects_foreign_memos(self):
        s = self.s
        with db.tx(s.conn):
            job_id = jobs.enqueue(s.conn, "courier", "public", {"address": fake_keys()["address"],
                                                               "memo": "https://evil.example/t#3" + "A" * 167},
                                  s.now, s.now)
        s.worker.run_jobs(s.now)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["error"], row["payload"]), ("failed", "invalid_payload", None))

    def test_budget_slices(self):
        s = self.s
        fresh, old = s.register(), s.register()
        s.graduate(old)
        address = fake_keys()["address"]
        new_job = s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3, "blob": blob()},
                            headers=fresh["auth"])[2]["job_id"]
        old_job = s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3, "blob": blob()},
                            headers=old["auth"])[2]["job_id"]
        self.assertEqual((self.job(new_job)["slice"], self.job(old_job)["slice"]), ("public", "reserved"))
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "public", 0, s.now)
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3,
                                                            "blob": blob()}, headers=fresh["auth"])
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["kind"]),
                         (429, "budget_exhausted", "courier"))
        self.assertEqual(body["error"]["details"]["resets_at"] % 86400, 0)
        self.assertEqual(s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3,
                                                           "blob": blob()}, headers=old["auth"])[0], 202)
        s.now += 46
        s.worker.run_jobs(s.now)
        self.assertEqual(self.job(new_job)["error"], "budget_exhausted")   # the worker re-checks at claim time
        self.assertEqual(self.job(old_job)["state"], "done")

    def test_lockers_cant_reach_the_evidence_slice(self):
        """Review M3: lockers draining `reserved` leave the canary's and judges' sends untouched."""
        s = self.s
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "reserved", 0, s.now)
        old = s.register()
        s.graduate(old)
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                            "kind": 3, "blob": blob()}, headers=old["auth"])
        self.assertEqual((status, body["error"]["code"]), (429, "budget_exhausted"))
        token = {"X-Mutis-Canary": codec.b64u(s.app.canary_token)}
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": s.robot["address"], "kind": 3,
                                                            "blob": blob(), "evidence": True}, headers=token)
        self.assertEqual((status, self.job(body["job_id"])["slice"]), (202, "evidence"))

    def test_overrides_only_lower_a_budget(self):
        """Review M8: the API can write the database, so an override above the TOML value is ignored."""
        s = self.s
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "public", 10 ** 9, s.now)
        self.assertEqual(budgets.limit(s.conn, s.cfg["budgets"], "courier", "public", s.now), 1500)
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "public", 3, s.now)
        self.assertEqual(budgets.limit(s.conn, s.cfg["budgets"], "courier", "public", s.now), 3)

    def test_refused_senders_dont_use_up_a_destination(self):
        """Review M4: 25 refused tries from a locker with no sends left don't touch the address's 20 a day."""
        s = self.s
        address = fake_keys()["address"]
        spent = s.register()
        with db.tx(s.conn):
            s.conn.execute("UPDATE identities SET sends_day = ?, sends_today = 3 WHERE id = ?",
                           (codec.day(s.now), spent["id"]))
        for _ in range(25):
            status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3,
                                                                "blob": blob()}, headers=spent["auth"])
            self.assertEqual((status, body["error"]["details"]), (429, {"sends_per_day": 3}))
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "public", 0, s.now)
        broke = s.register()
        for _ in range(25):
            self.assertEqual(s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3,
                                                               "blob": blob()}, headers=broke["auth"])[0], 429)
        honest = s.register()
        s.graduate(honest)
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3,
                                                            "blob": blob()}, headers=honest["auth"])
        self.assertEqual(status, 202, body)

    def test_refused_drop_deliveries_dont_use_up_the_drop(self):
        s = self.s
        drop = s.drop()
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "public", 0, s.now)
        for i in range(60):
            ip = f"10.9.{i}.1"
            status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                                "blob": blob(), "pow": s.solve("courier", ip)}, ip=ip)
            self.assertEqual(body["error"]["code"], "budget_exhausted")
        with db.tx(s.conn):
            s.conn.execute("DELETE FROM meta WHERE key = 'budget_overrides'")
        status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                            "blob": blob(), "pow": s.solve("courier", "10.8.0.1")},
                                    ip="10.8.0.1")
        self.assertEqual(status, 202, body)

    def test_locker_and_destination_caps(self):
        s = self.s
        locker = s.register()
        for _ in range(3):
            self.assertEqual(s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                               "kind": 3, "blob": blob()}, headers=locker["auth"])[0],
                             202)
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                            "kind": 3, "blob": blob()}, headers=locker["auth"])
        self.assertEqual((status, body["error"]["details"]["sends_per_day"]), (429, 3))
        address = fake_keys()["address"]
        codes = []
        for i in range(21):
            sender = s.register(ip=f"10.{i}.0.1")
            codes.append(s.request("POST", f"{V}/courier", {"to": "address", "address": address, "kind": 3,
                                                           "blob": blob()}, headers=sender["auth"])[0])
        self.assertEqual(codes.count(202), 20)
        self.assertEqual(codes[-1], 429)

    def test_canary_evidence_courier(self):
        s = self.s
        token = {"X-Mutis-Canary": codec.b64u(s.app.canary_token)}
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": s.robot["address"], "kind": 3,
                                                            "blob": blob(), "evidence": True}, headers=token)
        self.assertEqual(status, 202)
        row = self.job(body["job_id"])
        self.assertEqual((row["evidence"], row["slice"]), (1, "evidence"))
        s.now += 46
        s.worker.run_jobs(s.now)
        self.assertIn("utxo_ids", json.loads(self.job(body["job_id"])["result"]))


class Heartbeat(unittest.TestCase):
    """Review M5: a long step must not make the API report the chain as down; a stuck loop must."""

    def test_beats_while_the_loop_moves_and_stops_when_it_stalls(self):
        s = Stack(chain=True)
        stop = threading.Event()
        every = chain_worker.HEARTBEAT_EVERY_S
        chain_worker.HEARTBEAT_EVERY_S = 0.02
        try:
            with db.tx(s.conn):
                db.del_meta(s.conn, "chain_heartbeat")
            beat = threading.Thread(target=s.worker._heartbeat, args=(stop,))
            beat.start()
            s.now += 500                          # a step has been running for minutes, but the loop is alive
            for _ in range(200):
                if s.meta("chain_heartbeat") == str(s.now):
                    break
                stop.wait(0.01)
            self.assertEqual(s.meta("chain_heartbeat"), str(s.now))
            drop = s.drop()
            status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                                "blob": blob(), "pow": s.solve("courier")})
            self.assertEqual(status, 202, body)                       # not 503 chain_unavailable
            s.worker.alive_at -= chain_worker.STALL_S + 1
            stop.wait(0.1)
            stalled_at = s.meta("chain_heartbeat")
            s.now += 500
            stop.wait(0.1)
            self.assertEqual(s.meta("chain_heartbeat"), stalled_at)
        finally:
            stop.set()
            chain_worker.HEARTBEAT_EVERY_S = every
            beat.join()
            s.close()


class Decoys(unittest.TestCase):
    @staticmethod
    def day_of_events(seed: int) -> int:
        gaps = chain_worker.decoy_gaps(random.Random(seed), 900)
        t, events = next(gaps), 0
        while t <= 86400:
            events += 1
            t += next(gaps)
        return events

    def test_mean_gap_over_a_simulated_day(self):
        """S-11 as written: one simulated day (fixed seed) has a mean gap within 20 % of 900 s."""
        self.assertLess(abs(86400 / self.day_of_events(0) - 900) / 900, 0.20)

    def test_mean_gap_over_a_simulated_month(self):
        """A Poisson day varies by about ±10 % (1 σ); thirty days must land within 5 % of the mean."""
        events = sum(self.day_of_events(seed) for seed in range(30))
        self.assertLess(abs(30 * 86400 / events - 900) / 900, 0.05)

    def test_decoy_send_looks_like_a_delivery(self):
        s = Stack(chain=True)
        try:
            s.worker.setup()
            s.quiet_chain()
            s.worker.enqueue_decoy(s.now)
            s.worker.run_jobs(s.now)
            decoy = s.chain.transfers[-1]
            memo = decoy["memo"]["Message"]
            self.assertTrue(jobs.memo_regex([ORIGIN]).match(memo))
            self.assertEqual((decoy["account"], decoy["value"]), ("sponsor", 1000))
            self.assertEqual(len(memo), len(ORIGIN) + 4 + 167)
            self.assertIn(memo[-1], "AEIMQUYcgkosw048")              # 125 bytes end on 4 bits, as a real blob does
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
