# SPDX-License-Identifier: MIT
"""S-07: payment verification (spec §10.5) with the fake sidecar and a fake indexer.

Every case here guards against the 2026-09-29 forged-deposit incident (community.tari.com/t/402):
a wallet checked an amount proof and ignored the result. We credit only a value the sidecar proved
against the commitment AND an indexer shows committed; nothing else moves an invoice to credited.
"""
import unittest

from harness import Stack
from mutis import codec, db, ootle_addr, payments
from mutis.fake_chain import FakeIndexer, fake_keys
from mutis.indexer import IndexerError, Indexers

VERIFIED = (200, b'{"verified": true, "substate": {"Utxo": {}}}')


class Payments(unittest.TestCase):
    def setUp(self):
        self.s = Stack(chain=True)
        self.w = self.s.worker
        self.w.setup()
        with db.tx(self.s.conn):             # today's evidence payment is already done
            db.set_meta(self.s.conn, "evidence_pay_day", codec.day(self.s.now))
        self.locker = self.s.register()

    def tearDown(self):
        self.s.close()

    def ticks(self, n: int = 3) -> None:
        for _ in range(n):
            self.s.now += 10
            self.w.tick()

    def invoice(self) -> dict:
        status, _, inv = self.s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=self.locker["auth"])
        self.assertEqual(status, 201, inv)
        return inv

    def get(self, inv: dict) -> dict:
        return self.s.request("GET", f"/api/v1/invoices/{inv['invoice_id']}", headers=self.locker["auth"])[2]

    def pay(self, address: str, amount: int) -> None:
        self.s.chain.transfer("service", address, amount, None, 30000)

    def test_demo_pay_end_to_end(self):
        """The judge path: demo-pay → sponsor sends → mirror → sidecar proves → indexer confirms → +2 GiB."""
        inv = self.invoice()
        status = self.s.request("POST", f"/api/v1/invoices/{inv['invoice_id']}/demo-pay",
                                {"pow": self.s.solve("demo_pay")}, headers=self.locker["auth"])[0]
        self.assertEqual(status, 202)
        self.ticks()
        got = self.get(inv)
        self.assertEqual(got["status"], "credited")
        self.assertEqual(got["payments"][0]["checks"], {"amount_proven": True, "committed_on_chain": True})
        self.assertEqual(got["credited"]["bytes"], 2 << 30)
        me = self.s.request("GET", "/api/v1/me", headers=self.locker["auth"])[2]
        self.assertEqual((me["plan"], me["quota"]["paid_bytes"]), ("paid", 2 << 30))
        transfer = next(t for t in self.s.chain.transfers if t["destination"] == inv["address"])
        self.assertEqual((transfer["account"], transfer["value"]), ("sponsor", 500000))

    def test_duplicate_utxo_is_credited_once(self):
        """Seeing the same UTXO twice must not credit twice (t/402: deposits were inflated)."""
        inv = self.invoice()
        self.pay(inv["address"], 300000)
        self.ticks()
        row = self.s.conn.execute("SELECT * FROM payments").fetchone()
        again = [{"id": row["utxo_id"], "value_ut": row["value_ut"], "memo": {"Message": inv["invoice_id"]}}]
        self.assertEqual(payments.record_found(self.s.conn, again, True, self.s.now, None), 0)
        self.ticks()
        got = self.get(inv)
        self.assertEqual((got["status"], got["received_ut"], len(got["payments"])), ("seen", "300000", 1))

    def test_outputs_that_are_not_ours_are_ignored(self):
        """The sidecar can't open other people's outputs, so they never become payments (t/402)."""
        self.invoice()
        self.pay(fake_keys()["address"], 900000)
        self.ticks()
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 0)

    def test_unknown_pay_ref_is_unattributed(self):
        """A proven payment with no matching invoice is recorded for a manual refund, never credited (t/402)."""
        address = ootle_addr.with_pay_ref(self.s.receiver["address"], b"inv_aaaaaaaaaaaaaaaaaaaa")
        self.pay(address, 500000)
        self.ticks()
        row = self.s.conn.execute("SELECT status, invoice_id FROM payments").fetchone()
        self.assertEqual(tuple(row), ("unattributed", None))

    def test_indexer_refusals_never_credit(self):
        """404, verified:false and "is down" answers are failures, never credits (t/402)."""
        inv = self.invoice()
        for answer in (lambda sid: None, lambda sid: {"verified": False, "substate": {"Utxo": {}}},
                       lambda sid: {"verified": True, "substate": {"Component": {}}}):
            self.s.chain.substate = answer
            self.pay(inv["address"], 500000)
            self.ticks()
            self.assertNotEqual(self.get(inv)["status"], "credited")
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM payments WHERE status = 'credited'").fetchone()[0],
                         0)

    def test_indexer_failover_after_three_failures(self):
        """After three failed reads on indexer-b the check moves to indexer-a; it still needs verified:true."""
        second = FakeIndexer(self.s.chain)
        self.w.indexers = Indexers([self.s.indexer.url, second.url], rate=1000)
        inv = self.invoice()
        original = self.s.chain.substate
        self.s.chain.substate = lambda sid: None
        self.pay(inv["address"], 500000)
        self.ticks(4)
        self.assertNotEqual(self.get(inv)["status"], "credited")
        self.s.chain.substate = original
        second_calls = []
        self.w.indexers.call_one = lambda pos, m, p: (second_calls.append(pos), Indexers.call_one(self.w.indexers,
                                                                                                    pos, m, p))[1]
        self.ticks()
        self.assertEqual(self.get(inv)["status"], "credited")
        self.assertIn(1, second_calls)
        second.shutdown()
        second.server_close()

    def test_underpaid_then_topped_up(self):
        """Partial payments add up; the invoice is credited only when proven value reaches the price."""
        inv = self.invoice()
        self.pay(inv["address"], 300000)
        self.ticks()
        self.assertEqual((self.get(inv)["status"], self.get(inv)["received_ut"]), ("seen", "300000"))
        self.s.now += 3700
        self.s.run_cleanup()
        self.assertEqual(self.get(inv)["status"], "underpaid")
        self.pay(inv["address"], 200000)
        self.ticks()
        self.assertEqual(self.get(inv)["status"], "credited")

    def test_one_payment_credits_at_most_the_price(self):
        """An oversized payment is recorded with its value, but credits only the invoice price."""
        inv = self.invoice()
        self.pay(inv["address"], 2_000_000)
        self.ticks()
        got = self.get(inv)
        self.assertEqual((got["status"], got["received_ut"], got["payments"][0]["value_ut"]),
                         ("credited", "500000", "2000000"))

    def test_reconcile_mismatch_freezes_credits(self):
        """A credited row the sidecar can't re-prove (a forged insert, E-14) freezes all crediting (t/402)."""
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO payments(utxo_id, value_ut, seen_at, proven, committed, status) "
                                "VALUES (?, 500000, 0, 1, 1, 'credited')", (f"utxo_{'01' * 32}_{'ab' * 32}",))
        self.w.reconcile(self.s.now)
        self.assertEqual(self.s.meta("credit_freeze"), "1")
        inv = self.invoice()
        self.pay(inv["address"], 500000)
        self.ticks()
        self.assertNotEqual(self.get(inv)["status"], "credited")
        with db.tx(self.s.conn):
            self.s.conn.execute("DELETE FROM payments WHERE utxo_id = ?", (f"utxo_{'01' * 32}_{'ab' * 32}",))
            db.del_meta(self.s.conn, "credit_freeze")
        self.ticks()
        self.assertEqual(self.get(inv)["status"], "credited")
        self.w.reconcile(self.s.now)
        self.assertIsNone(self.s.meta("credit_freeze"))

    def credited_invoice(self) -> dict:
        inv = self.invoice()
        self.pay(inv["address"], 500000)
        self.ticks()
        self.assertEqual(self.get(inv)["status"], "credited")
        return inv

    def answer(self, *per_indexer) -> None:
        """Every indexer read from now on gets these answers, one per indexer position."""
        def call_one(position, method, path):
            reply = per_indexer[position]
            if isinstance(reply, Exception):
                raise reply
            return reply[0], reply[1], f"indexer-{position + 1}"
        self.w.indexers.call_one = call_one
        self.w.indexers.upstreams = self.w.indexers.upstreams[:1] * len(per_indexer)

    def test_a_transient_indexer_error_never_freezes_credits(self):
        """Review H3: a 503 or 429 from the indexers' CDN skips the hourly check; the next buyer is credited.

        Freezing on an unknown would stop every pack for a CDN hiccup, so the round is skipped and only
        three unknown hours in a row raise a critical alert (t/402: a real mismatch still freezes)."""
        self.credited_invoice()
        for reply in ((503, b"<html>"), (429, b""), (200, b"not json"), IndexerError(503, "chain_unavailable")):
            self.answer(reply)
            self.w.reconcile(self.s.now)
            self.assertIsNone(self.s.meta("credit_freeze"), reply)
        self.assertEqual(self.s.meta("reconcile_unknown"), "4")
        with self.assertLogs("mutis", "CRITICAL") as logs:          # three unknown hours in a row and more
            self.w.reconcile(self.s.now)
        self.assertEqual(logs.records[0].getMessage(), "event=chain.reconcile_unknown")
        del self.w.indexers.call_one
        self.w.indexers.upstreams = self.w.indexers.upstreams[:1]
        self.credited_invoice()
        self.w.reconcile(self.s.now)
        self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_unknown")), (None, "0"))

    def test_check_outcomes(self):
        """ok needs a verified Utxo; 404 or an unverified answer is missing; the rest is unknown (t/402)."""
        cases = [(VERIFIED, "ok"), ((404, b'{"error": "Substate utxo_x not found"}'), "missing"),
                 ((404, b'{"error": "Input substate utxo_x (v0) is down"}'), "missing"),
                 ((200, b'{"verified": false, "substate": {"Utxo": {}}}'), "missing"),
                 ((200, b'{"verified": true, "substate": {"Component": {}}}'), "missing"),
                 ((502, b""), "unknown"), ((429, b""), "unknown"), ((403, b"error code: 1010"), "unknown"),
                 (IndexerError(503, "chain_unavailable"), "unknown")]
        for reply, outcome in cases:
            self.answer(reply)
            self.assertEqual(payments.committed_on_indexer(self.w.indexers, "utxo_x", 0), outcome, reply)

    def test_a_mismatch_needs_every_indexer_to_agree(self):
        """Missing on one indexer and proven on the other is no mismatch; missing on both freezes (t/402)."""
        self.credited_invoice()
        self.answer((404, b"{}"), VERIFIED)
        self.w.reconcile(self.s.now)
        self.assertIsNone(self.s.meta("credit_freeze"))
        self.answer((404, b"{}"), (503, b""))
        self.w.reconcile(self.s.now)
        self.assertIsNone(self.s.meta("credit_freeze"))
        self.answer((404, b"{}"), (404, b"{}"))
        self.w.reconcile(self.s.now)
        self.assertEqual(self.s.meta("credit_freeze"), "1")

    def test_demo_payments_go_only_to_our_receiver(self):
        """Review M8: the API can write `meta.receiver_address`; the worker pays only the receiver it
        learned from its own key file, so a rewritten row can't send the sponsor's funds elsewhere."""
        stranger = fake_keys()["address"]
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "receiver_address", stranger)
        inv = self.invoice()
        self.assertEqual(ootle_addr.base_address(inv["address"]), ootle_addr.base_address(stranger))
        sent = len(self.s.chain.transfers)
        status = self.s.request("POST", f"/api/v1/invoices/{inv['invoice_id']}/demo-pay",
                                {"pow": self.s.solve("demo_pay")}, headers=self.locker["auth"])[0]
        self.assertEqual(status, 202)
        self.w.run_jobs(self.s.now)
        job = self.s.conn.execute("SELECT state, error, payload FROM jobs WHERE kind = 'demo_pay'").fetchone()
        self.assertEqual(tuple(job), ("failed", "invalid_payload", None))
        self.assertEqual(len(self.s.chain.transfers), sent)

    def test_crafted_mismatch_is_rejected_by_the_sidecar(self):
        """Swapping nonce and encrypted data between outputs claims a value the commitment doesn't hold.

        The fake sidecar models unblindOutput's commitment check; the real sidecar's `selftest` runs the
        crafted case from web/app/tests/vectors/wrap-v2.json in the @chain suite (t/402).
        """
        self.invoice()
        receiver = self.s.receiver["address"]
        self.pay(receiver, 7)
        self.pay(receiver, 900000)
        self.ticks()
        rows = self.s.conn.execute("SELECT id, nonce, enc FROM chain_utxos ORDER BY seq").fetchall()
        small = next(r for r in rows if b'"' not in r["enc"][40:] and int.from_bytes(r["enc"][32:40], "big") == 7)
        large = next(r for r in rows if int.from_bytes(r["enc"][32:40], "big") == 900000)
        crafted = [{"id": small["id"], "nonce": large["nonce"], "enc": large["enc"]}]
        found = self.w._scan(self.s.receiver["view_sk"], crafted)
        self.assertEqual(found, [])


class WalletFallback(unittest.TestCase):
    """G4 fallback: walletd's `service` account receives; labels say "Seen by our wallet", never "proven"."""

    def test_wallet_mode_credit(self):
        s = Stack({"gates": {"amount_proof": "wallet"}}, chain=True)
        try:
            s.worker.setup()
            locker = s.register()
            inv = s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=locker["auth"])[2]
            self.assertEqual(ootle_addr.base_address(inv["address"]),
                             ootle_addr.base_address(s.chain.addresses["service"]))
            s.chain.transfer("sponsor", inv["address"], 500000, None, 30000)
            for _ in range(3):
                s.now += 10
                s.worker.tick()
            got = s.request("GET", f"/api/v1/invoices/{inv['invoice_id']}", headers=locker["auth"])[2]
            self.assertEqual(got["status"], "credited")
            self.assertEqual(got["payments"][0]["checks"], {"amount_proven": False, "committed_on_chain": True})
            s.worker.reconcile(s.now)
            self.assertIsNone(s.meta("credit_freeze"))
        finally:
            s.close()


class PayRef(unittest.TestCase):
    def test_memo_forms(self):
        ref = "inv_abcdefghijklmnopqrst"
        self.assertEqual(payments.pay_ref({"PayRefAndBytes": (bytes([len(ref)]) + ref.encode() + b"tail").hex()}), ref)
        self.assertEqual(payments.pay_ref({"Message": ref}), ref)
        self.assertIsNone(payments.pay_ref({"Message": ref + " "}))
        self.assertIsNone(payments.pay_ref({"PayRefAndBytes": "ff00"}))
        self.assertIsNone(payments.pay_ref(None))
        self.assertIsNone(payments.pay_ref({"Bytes": codec.b64u(b"x")}))


if __name__ == "__main__":
    unittest.main()
