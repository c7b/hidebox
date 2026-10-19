# SPDX-License-Identifier: MIT
"""Pay to open, the chain worker (annex 16-drive-architecture §1.6), on the fake chain only.

The 2026-09-29 forged-deposit incident (community.tari.com/t/402) came from a wallet that checked an
amount proof and ignored the result; R1 and R2 (§1.1) came from treating "our view key opens it" as "it is
ours". So a sale payment counts only when the official `unblindOutput` proved its amount with the seller's
sealed view key AND an indexer commits it; and even then (test_release_gate.py) only test money we built
releases by itself. Each test names the step it pins: found → seen → counted → paid, top-ups, extras,
once-ever UTXOs, the seller's other income never recorded, the grace, bad keys, the scan start, the
round robin, and that the pack credit freeze doesn't stop sales.
"""
import json
from unittest import mock

from paid_fixture import V, PaidCase, watch_blob
from mutis import codec, db, jobs, ootle_addr, sales
from mutis.fake_chain import fake_keys


class SalesWorker(PaidCase):
    def setUp(self):
        super().setUp()
        self.ready_seller()
        self.link = self.sell(self.kept()["item_id"])

    def payments(self, claim: dict) -> list:
        return [tuple(r) for r in self.s.conn.execute("SELECT value_ut, status FROM sale_payments WHERE claim_id = ? "
                                                      "ORDER BY seen_at, value_ut", (claim["claim_id"],))]

    def test_the_watch_key_opens_and_the_seller_is_ready(self):
        self.assertEqual(self.s.conn.execute("SELECT state FROM sellers").fetchone()[0], "ok")
        self.assertEqual(self.s.worker.watch_keys[self.d["id"]], self.sales_keys["view_sk"])
        self.assertTrue(self.s.request("GET", f"{V}/p/{self.link['share_id']}")[2]["seller"]["ready"])

    def test_found_seen_counted_paid(self):
        claim = self.claim(self.link)
        utxo = self.pay(claim)
        self.s.worker.mirror(self.s.now)
        with mock.patch.object(sales, "check_pending"):        # stop after the scan: found, not yet counted
            self.s.worker.verify_sales(self.s.now)
        self.assertEqual(self.row(claim)["status"], "seen")
        got = self.poll(claim)
        self.assertEqual(got["payments"][0]["checks"], {"amount_proven": True, "committed_on_chain": False})
        self.ticks(1)
        row = self.row(claim)
        self.assertEqual((row["status"], row["received_ut"], row["owner_check"], row["demo"]), ("paid", 100000, "pending", 0))
        self.assertEqual(self.s.conn.execute("SELECT status, committed FROM sale_payments WHERE utxo_id = ?",
                                             (utxo,)).fetchone()[:], ("counted", 1))

    def test_underpaid_then_topped_up_within_the_grace(self):
        claim = self.claim(self.link)
        self.pay(claim, 40000)
        self.ticks()
        self.assertEqual((self.row(claim)["status"], self.row(claim)["received_ut"]), ("seen", 40000))
        self.s.now += sales.CLAIM_TTL_S
        self.s.run_cleanup()
        self.assertEqual(self.row(claim)["status"], "underpaid")
        self.pay(claim, 60000)
        self.ticks()
        self.assertEqual((self.row(claim)["status"], self.row(claim)["received_ut"]), ("paid", 100000))

    def test_an_overpayment_counts_in_full_and_a_later_one_is_extra(self):
        claim = self.claim(self.link)
        self.pay(claim, 150000)
        self.ticks()
        self.assertEqual((self.row(claim)["status"], self.row(claim)["received_ut"]), ("paid", 150000))
        other = self.claim(self.link)                          # keeps the seller scanned
        self.pay(claim, 100000)
        self.ticks()
        self.assertEqual(self.payments(claim), [(150000, "counted"), (100000, "extra")])
        self.assertEqual(self.row(claim)["received_ut"], 150000)
        self.assertEqual(self.row(other)["status"], "pending")

    def test_a_utxo_counts_once_ever(self):
        claim = self.claim(self.link)
        self.pay(claim, 40000)
        self.ticks()
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE sellers SET scan_seq = 0")          # scan everything again
        self.ticks()
        self.assertEqual(self.payments(claim), [(40000, "counted")])
        self.assertEqual(self.row(claim)["received_ut"], 40000)

    def test_the_sellers_other_income_and_other_sellers_claims_are_not_recorded(self):
        claim = self.claim(self.link)
        self.s.chain.add_output(self.sales_keys["address"], 70000, {"Message": "thanks for lunch"})
        self.s.chain.add_output(self.sales_keys["address"], 70000, {"Message": "clm_" + "b" * 20})
        other = self.s.register()
        other_keys = fake_keys()
        self.register_seller(other, other_keys)
        self.ticks(1)
        theirs = self.claim(self.sell(self.kept(d=other)["item_id"], d=other))
        self.s.chain.add_output(self.sales_keys["address"], 100000, {"Message": theirs["claim_id"]})   # wrong seller
        self.ticks()
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM sale_payments").fetchone()[0], 0)
        self.assertEqual((self.row(claim)["status"], self.row(theirs)["status"]), ("pending", "pending"))

    def test_a_message_memo_with_the_claim_id_counts_like_a_pay_ref(self):
        claim = self.claim(self.link)
        self.s.chain.add_output(self.sales_keys["address"], 100000, {"Message": claim["claim_id"]})
        self.ticks()
        self.assertEqual(self.row(claim)["status"], "paid")

    def test_a_payment_after_the_grace_is_never_seen(self):
        claim = self.claim(self.link)
        self.s.now += sales.CLAIM_TTL_S + sales.LATE_GRACE_S
        self.s.run_cleanup()
        self.pay(claim)
        self.ticks()
        self.assertEqual((self.row(claim)["status"], self.payments(claim)), ("expired", []))

    def test_a_blob_that_doesnt_hold_the_addresses_view_key_is_bad_key(self):
        stranger = fake_keys()
        for blob in ({"flags": 0x04}, {"ref_address": stranger["address"]}):
            self.register_seller(**blob)
            self.ticks(1)
            self.assertEqual(self.s.conn.execute("SELECT state FROM sellers").fetchone()[0], "bad_key", blob)
            self.assertNotIn(self.d["id"], self.s.worker.watch_keys)
        status, _, _ = self.s.request("PUT", f"{V}/me/sales", {"address": self.sales_keys["address"], "view_sealed":
                                      codec.b64u(watch_blob(self.sales_keys["address"], bytes.fromhex(stranger["view_sk"])))},
                                      headers=self.d["auth"])
        self.assertEqual(status, 204)
        self.ticks(1)
        self.assertEqual(self.s.conn.execute("SELECT state FROM sellers").fetchone()[0], "bad_key")
        self.assertEqual(self.claim(self.link, expect=409)["error"]["code"], "seller_not_ready")

    def test_the_scan_starts_where_the_oldest_waiting_claim_was_made(self):
        for _ in range(3):
            self.s.chain.add_output(fake_keys()["address"], 1, None)
        self.ticks(1)
        head = sales.mirror_head(self.s.conn)
        claim = self.claim(self.link)
        self.assertEqual(self.row(claim)["created_seq"], head)
        seen = []
        real = self.s.worker._scan
        self.s.worker._scan = lambda key, rows: seen.extend(r["seq"] for r in rows) or real(key, rows)
        self.pay(claim)
        self.ticks()
        self.assertEqual(self.row(claim)["status"], "paid")
        self.assertTrue(seen and min(seen) >= head)             # never the rows before the claim
        # The cursor moves past every row it scanned. Not "== the head": a decoy the same tick sends after the
        # scan (random, decoy_mean_gap_s) lands in the mirror later ("==" fails about one run in ten).
        self.assertGreaterEqual(self.s.conn.execute("SELECT scan_seq FROM sellers").fetchone()[0], max(seen))

    def test_sellers_take_turns(self):
        others = []
        for _ in range(2):
            d, keys = self.s.register(), fake_keys()
            self.register_seller(d, keys)
            others.append((d, keys))
        self.ticks(1)
        claims = [self.claim(self.link)] + [self.claim(self.sell(self.kept(d=d)["item_id"], d=d)) for d, _ in others]
        scanned = []
        real = sales.record_sales
        with mock.patch.object(sales, "SELLERS_PER_TICK", 2), \
                mock.patch.object(sales, "record_sales", lambda conn, sid, *a: scanned.append(sid) or real(conn, sid, *a)):
            self.s.worker.verify_sales(self.s.now)
            self.s.now += 10
            self.s.worker.verify_sales(self.s.now)
        self.assertEqual(len(scanned), 4)
        self.assertEqual(len(set(scanned[:2])), 2)
        self.assertNotIn(scanned[2], scanned[:2])               # the one left out goes first next time
        self.assertEqual(len(claims), 3)

    def test_the_pack_credit_freeze_does_not_stop_sales(self):
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "credit_freeze", "1")
        claim = self.claim(self.link)
        self.pay(claim)
        self.ticks()
        self.assertEqual(self.row(claim)["status"], "paid")

    def test_after_a_restart_the_worker_opens_the_sealed_key_again(self):
        claim = self.claim(self.link)
        self.s.worker.watch_keys.clear()
        self.pay(claim)
        self.ticks()
        self.assertEqual(self.row(claim)["status"], "paid")
        self.assertIn(self.d["id"], self.s.worker.watch_keys)

    def test_nothing_runs_with_the_feature_off(self):
        claim = self.claim(self.link)
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "features", {"pay_to_open": False})
        self.pay(claim)
        self.ticks()
        self.assertEqual(self.row(claim)["status"], "pending")


class DemoPayForClaims(PaidCase):
    """Test money: our demo wallet pays the seller's claim address. The worker's guard re-checks it all."""

    def setUp(self):
        super().setUp()
        self.ready_seller()
        self.link = self.sell(self.kept()["item_id"])
        self.c = self.claim(self.link)

    def demo(self, claim: dict, expect: int = 202) -> dict:
        status, _, resp = self.s.request("POST", f"{V}/p/{claim['share_id']}/claims/{claim['claim_id']}/demo-pay",
                                         {"pow": self.s.solve("demo_pay")}, headers=claim["hdr"])
        self.assertEqual(status, expect, resp)
        return resp

    def job(self, job_id: str):
        return self.s.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def test_test_money_pays_marks_the_claim_and_releases_it(self):
        job = self.demo(self.c)
        self.ticks()
        self.assertEqual(self.job(job["job_id"])["state"], "done")
        sent = self.s.chain.transfers[-1]
        self.assertEqual((sent["account"], sent["destination"], sent["value"]), ("sponsor", self.c["address"], 100000))
        row = self.row(self.c)
        self.assertEqual((row["status"], row["demo"], row["owner_check"]), ("paid", 1, "none"))
        got = self.poll(self.c)
        self.assertEqual((got["status"], got["views_left"], codec.unb64u(got["server_half"])),
                         ("released", sales.BUYER_VIEWS, self.link["half"]))
        self.assertRegex(got["tx_id"], r"^[0-9a-f]{64}$")      # the buyer can see its tx
        self.open(self.link, self.c)

    def enqueue(self, **payload) -> str:
        base = {"address": self.c["address"], "amount_ut": "100000", "ref": self.c["claim_id"]}
        with db.tx(self.s.conn):
            return jobs.enqueue(self.s.conn, "demo_pay", "public", {**base, **payload}, self.s.now, self.s.now)

    def assert_refused(self, job_id: str) -> None:
        self.ticks(1)
        row = self.job(job_id)
        self.assertEqual((row["state"], row["error"]), ("failed", "invalid_payload"))

    def test_the_worker_refuses_another_address(self):
        thief = fake_keys()["address"]
        self.assert_refused(self.enqueue(address=ootle_addr.with_pay_ref(thief, self.c["claim_id"].encode())))

    def test_the_worker_refuses_more_than_what_is_missing(self):
        self.assert_refused(self.enqueue(amount_ut="100001"))

    def test_the_worker_refuses_a_closed_claim_or_an_unready_seller(self):
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE claims SET status = 'expired'")
        self.assert_refused(self.enqueue())
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE claims SET status = 'pending'")
            self.s.conn.execute("UPDATE sellers SET state = 'bad_key'")
        self.s.worker.watch_keys.clear()
        self.assert_refused(self.enqueue())

    def test_a_claim_reference_never_goes_to_our_receiver_check_and_back(self):
        """`inv_` refs keep the old rule (our receiver only); a `clm_` ref is checked against the claim."""
        receiver = self.s.meta("receiver_address")
        self.assert_refused(self.enqueue(address=ootle_addr.with_pay_ref(receiver, self.c["claim_id"].encode())))

    def test_a_top_up_of_someone_elses_partial_payment_is_not_test_money(self):
        self.pay(self.c, 40000)
        self.ticks()
        job = self.demo(self.c)
        self.assertEqual(json.loads(self.job(job["job_id"])["payload"])["amount_ut"], "60000")
        self.ticks()
        row = self.row(self.c)
        self.assertEqual((row["status"], row["demo"], row["owner_check"]), ("paid", 0, "pending"))
        self.assertNotIn("server_half", self.poll(self.c))


del PaidCase
