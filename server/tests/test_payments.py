# SPDX-License-Identifier: MIT
"""S-07: payment verification (spec §10.5) with the fake sidecar and a fake indexer.

Every case here guards against the 2026-09-29 forged-deposit incident (community.tari.com/t/402):
a wallet checked an amount proof and ignored the result. We credit only a value the sidecar proved
against the commitment AND an indexer shows committed; nothing else moves an invoice to credited.
"""
import json
import unittest
from pathlib import Path

from harness import GiB, Disk, Stack
from mutis import codec, db, ootle_addr, packs, payments, quota
from mutis.chain_worker import RECONCILE_RECHECK_S
from mutis.fake_chain import FakeIndexer, fake_keys
from mutis.indexer import IndexerError, Indexers

VERIFIED = (200, b'{"verified": true, "substate": {"Utxo": {}}}')             # an indexer before 0.47.0
NOT_FOUND = (404, b'{"error": "Substate utxo_x not found"}')
# tari_indexer 0.47.0's answers, recorded from both Esmeralda indexers (fixtures/indexer-substates-0.47.0.json).
RECORDED = json.loads((Path(__file__).parent / "fixtures" / "indexer-substates-0.47.0.json").read_text())


def recorded(name: str) -> tuple[int, bytes]:
    answer = RECORDED[name]
    return answer["status"], json.dumps(answer["body"]).encode()


LIVE = recorded("live_utxo")
DOWN = recorded("spent_utxo_at_version")


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

    def test_a_late_payment_for_a_lapsed_invoice_credits_only_with_room(self):
        """security-audit-1: an invoice gives its bytes back when it is swapped (or expires); a payment that
        arrives for it later credits only once the slice has room again, so paid space never goes over its
        cap. Public slice here: 7.28 GiB."""
        disk = Disk(total=100 * GiB, avail=36 * GiB)
        self.s.app.statvfs = disk
        a, b = self.s.register(ip="198.18.0.1"), self.s.register(ip="198.18.1.1")

        def buy(drive, pack, ip):
            status, _, inv = self.s.request("POST", "/api/v1/invoices", {"pack": pack}, headers=drive["auth"], ip=ip)
            self.assertIn(status, (200, 201), inv)
            return inv

        late = buy(a, "m30", "198.18.0.1")
        buy(a, "s30", "198.18.0.1")                               # the swap: `late` gives its 5 GiB back
        taken = buy(b, "m30", "198.18.1.1")                       # someone else takes them
        for inv in (late, taken):
            self.pay(inv["address"], int(inv["amount_ut"]))
        self.ticks()
        status = lambda inv: self.s.conn.execute("SELECT status FROM invoices WHERE id = ?",  # noqa: E731
                                                 (inv["invoice_id"],)).fetchone()[0]
        self.assertEqual((status(taken), status(late)), ("credited", "expired"))
        held = self.s.conn.execute("SELECT p.status FROM payments p WHERE p.invoice_id = ?",
                                   (late["invoice_id"],)).fetchone()[0]
        self.assertEqual(held, "pending_check")
        pool = quota.measure(self.s.conn, disk, self.s.cfg.data_dir, self.s.cfg["limits"], self.s.now)
        s = packs.slices(self.s.conn, pool, self.s.cfg["packs"], self.s.now)
        self.assertLessEqual(s.public_active, s.public_cap)
        disk.avail = 80 * GiB                                    # room again: the held payment credits
        self.ticks()
        self.assertEqual(status(late), "credited")

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
        """404, verified:false, "is down" and proven-spent answers are failures, never credits (t/402)."""
        inv = self.invoice()
        spent = RECORDED["spent_utxo_at_version"]["body"]
        live = RECORDED["live_utxo"]["body"]
        for answer in (lambda sid: None, lambda sid: {"verified": False, "substate": {"Utxo": {}}},
                       lambda sid: {"verified": True, "substate": {"Component": {}}},
                       lambda sid: spent, lambda sid: {**live, "verified": False},
                       lambda sid: {**live, "state": {"up": {"substate": {"Component": {}}}}},
                       lambda sid: {**live, "state": {**live["state"], "down": {}}},
                       lambda sid: {"verified": True, "state": None, "substate": live["state"]["up"]["substate"]}):
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
        """A credited row the sidecar can't re-prove (a forged insert, E-14) holds all crediting, and the
        check five minutes later that finds it again freezes it (t/402)."""
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO payments(utxo_id, value_ut, seen_at, proven, committed, status) "
                                "VALUES (?, 500000, 0, 1, 1, 'credited')", (f"utxo_{'01' * 32}_{'ab' * 32}",))
        self.w.reconcile(self.s.now)
        self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_mismatch")), (None, str(self.s.now)))
        self.w.reconcile(self.s.now + RECONCILE_RECHECK_S)
        self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_mismatch")), ("1", None))
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
        self.locker = self.s.register()          # a drive holds one pack at a time: each purchase is a new drive
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
        """ok needs a verified Utxo; the indexer's own 404 or an unverified answer is missing; the rest,
        a gateway's 404 page included, is unknown (t/402)."""
        cases = [(VERIFIED, "ok"), ((404, b'{"error": "Substate utxo_x not found"}'), "missing"),
                 ((404, b'{"error": "Input substate utxo_x (v0) is down"}'), "missing"),
                 ((200, b'{"verified": false, "substate": {"Utxo": {}}}'), "missing"),
                 ((200, b'{"verified": true, "substate": {"Component": {}}}'), "missing"),
                 ((502, b""), "unknown"), ((429, b""), "unknown"), ((403, b"error code: 1010"), "unknown"),
                 ((404, b"<html>404 Not Found</html>"), "unknown"), ((404, b"{}"), "unknown"),
                 (IndexerError(503, "chain_unavailable"), "unknown")]
        for reply, outcome in cases:
            self.answer(reply)
            self.assertEqual(payments.committed_on_indexer(self.w.indexers, "utxo_x", 0), outcome, reply)

    def test_check_outcomes_of_the_0_47_indexer(self):
        """tari_indexer 0.47.0 answers `state.up.substate` for a live output and, for a spent version it can
        prove, `state.down` with a down proof: recorded answers of both indexers. Only a verified live Utxo is
        `ok`; a proven down is `missing`, like the "… is down" 404 (t/402)."""
        live = RECORDED["live_utxo"]["body"]
        cases = [(LIVE, "ok"), (recorded("live_utxo_without_proof"), "ok"), (recorded("live_utxo_at_version"), "ok"),
                 (DOWN, "missing"), (recorded("spent_utxo"), "missing"),
                 ((200, json.dumps({**live, "verified": False}).encode()), "missing"),
                 ((200, json.dumps({k: v for k, v in live.items() if k != "verified"}).encode()), "missing"),
                 ((200, json.dumps({**live, "state": {"up": {"substate": {"Component": {}}}}}).encode()), "missing"),
                 ((200, json.dumps({**live, "state": {**live["state"], "down": {}}}).encode()), "missing"),
                 ((200, json.dumps({**live, "state": {}}).encode()), "unknown"),
                 ((200, json.dumps({**live, "state": "up"}).encode()), "unknown"),
                 ((200, json.dumps({**live, "state": {"up": {"substate": []}}}).encode()), "unknown"),
                 ((200, json.dumps({"verified": True, "value": live["state"]}).encode()), "unknown"),
                 ((200, json.dumps([live]).encode()), "unknown"), ((200, b'"ok"'), "unknown")]
        for reply, outcome in cases:
            self.answer(reply)
            self.assertEqual(payments.committed_on_indexer(self.w.indexers, "utxo_x", 0), outcome, reply[1][:80])
        self.answer(LIVE)
        verdict, seen = payments.utxo_on_indexer(self.w.indexers, RECORDED["live_utxo"]["id"], 0)
        self.assertEqual((verdict, seen), ("ok", {
            "auth_key": "6892417fe10f69cc21abd98b963160d872e03fe9a8882d9f531e7bb3efde7a06",
            "nonce": "2adc08fe942c440039a76272abb9cdec08b0a166aecd841d020a7fe12d69c50b"}))

    def test_the_0_47_answers_never_freeze_credits(self):
        """Every credited output read in the 0.47.0 shape is proven: the hourly check and its recheck stay ok,
        and the next buyer is credited. Reading only the older `substate` field, every output looked gone and
        two rounds froze every pack (t/402: a spent credited output still freezes, below)."""
        self.credited_invoice()
        self.answer(LIVE, LIVE)
        for later in (0, RECONCILE_RECHECK_S):
            with self.assertLogs("mutis", "INFO") as logs:
                self.assertEqual(payments.reconcile(
                    self.s.conn, lambda rows: {f["id"]: f["value_ut"] for f in self.w._scan(
                        self.s.receiver["view_sk"], rows)},
                    lambda uid: payments.committed_anywhere(self.w.indexers, uid), self.s.now + later), "ok")
            self.assertEqual(logs.records[-1].getMessage(), "event=chain.reconcile_ok")
        self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_mismatch")), (None, None))
        del self.w.indexers.call_one
        self.w.indexers.upstreams = self.w.indexers.upstreams[:1]
        self.credited_invoice()

    def test_the_fake_indexer_answers_like_0_47(self):
        """The dev stack's indexer: a live output in `state.up.substate`; a spent one a 404 "… is down", or a
        proven down when its version is named with a proof."""
        self.s.chain.add_output(fake_keys()["address"], 1000, None)
        utxo = f"utxo_{'01' * 32}_{self.s.chain.outputs[-1]['commitment']}"
        indexers = self.w.indexers
        self.assertEqual(payments.utxo_on_indexer(indexers, utxo, 0)[0], "ok")
        status, body, _ = indexers.get_json(f"/substates/{utxo}")
        self.assertEqual((status, sorted(body), sorted(body["state"])), (200, ["proof", "state", "verified", "version"], ["up"]))
        with self.s.chain.lock:
            self.s.chain.outputs[-1]["spent"] = True
        self.assertEqual(payments.utxo_on_indexer(indexers, utxo, 0)[0], "missing")
        self.assertEqual(indexers.get_json(f"/substates/{utxo}?include_proof=true")[:2],
                         (404, {"error": f"Input substate {utxo} (v0) is down"}))
        status, body, _ = indexers.get_json(f"/substates/{utxo}?version=0&include_proof=true")
        self.assertEqual((status, body["state"]), (200, {"down": {}}))

    def test_an_answer_in_a_shape_we_cant_read_never_freezes_credits(self):
        """A 200 whose shape has neither a `state` nor a `substate` we can read (an indexer release that moved
        the value again) says nothing about the output: the round is skipped and counted, never a freeze; an
        output the indexers say is gone still freezes on the second round (t/402)."""
        self.credited_invoice()
        moved = (200, json.dumps({"version": 0, "result": RECORDED["live_utxo"]["body"]["state"], "verified": True}).encode())
        self.answer(moved, moved)
        for later in (0, RECONCILE_RECHECK_S, 2 * RECONCILE_RECHECK_S):
            self.w.reconcile(self.s.now + later)
            self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_mismatch")), (None, None))
        self.assertEqual(self.s.meta("reconcile_unknown"), "3")
        self.answer(moved, NOT_FOUND)
        self.w.reconcile(self.s.now)
        self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_unknown")), (None, "4"))
        self.answer(DOWN, NOT_FOUND)
        self.w.reconcile(self.s.now)
        self.assertEqual((self.s.meta("reconcile_mismatch"), self.s.meta("reconcile_unknown")), (str(self.s.now), "0"))
        self.w.reconcile(self.s.now + RECONCILE_RECHECK_S)
        self.assertEqual(self.s.meta("credit_freeze"), "1")

    def test_a_forged_payment_still_freezes_when_the_indexers_answer_in_the_0_47_shape(self):
        """E-14 with 0.47.0 answers: a credited row for an output both indexers say doesn't exist holds
        credits, and the recheck freezes them (t/402)."""
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO payments(utxo_id, value_ut, seen_at, proven, committed, status) "
                                "VALUES (?, 500000, 0, 1, 1, 'credited')", (f"utxo_{'01' * 32}_{'ab' * 32}",))
        self.w.reconcile(self.s.now)
        self.assertEqual((self.s.meta("credit_freeze"), self.s.meta("reconcile_mismatch")), (None, str(self.s.now)))
        self.w.reconcile(self.s.now + RECONCILE_RECHECK_S)
        self.assertEqual(self.s.meta("credit_freeze"), "1")

    def test_a_proven_spent_credited_output_freezes(self):
        """A credited output both indexers prove spent (`state.down`) is gone, like a 404 "… is down": the
        check and its recheck freeze credits (t/402; our receiver never spends)."""
        self.credited_invoice()
        self.answer(DOWN, DOWN)
        self.w.reconcile(self.s.now)
        self.assertEqual(self.s.meta("reconcile_mismatch"), str(self.s.now))
        self.w.reconcile(self.s.now + RECONCILE_RECHECK_S)
        self.assertEqual(self.s.meta("credit_freeze"), "1")

    def test_a_mismatch_needs_every_indexer_to_agree(self):
        """Missing on one indexer and proven on the other is no mismatch; missing on both, twice in a row,
        freezes (t/402)."""
        self.credited_invoice()
        self.answer(NOT_FOUND, VERIFIED)
        self.w.reconcile(self.s.now)
        self.assertIsNone(self.s.meta("reconcile_mismatch"))
        self.answer(NOT_FOUND, (503, b""))
        self.w.reconcile(self.s.now)
        self.assertIsNone(self.s.meta("reconcile_mismatch"))
        self.answer(NOT_FOUND, NOT_FOUND)
        self.w.reconcile(self.s.now)
        self.assertIsNone(self.s.meta("credit_freeze"))
        self.w.reconcile(self.s.now + RECONCILE_RECHECK_S)
        self.assertEqual(self.s.meta("credit_freeze"), "1")

    def test_a_one_off_mismatch_holds_credits_until_the_recheck(self):
        """One hourly round can find a mismatch no other round finds (it happened once in production), and
        a freeze stops every pack until a human acts. So a mismatch holds credits, the worker checks again five
        minutes later, and a round that finds every credit proven releases the hold (t/402)."""
        self.credited_invoice()
        self.answer(NOT_FOUND, NOT_FOUND)
        with self.assertLogs("mutis", "WARNING") as logs:
            self.w.reconcile(self.s.now)
        self.assertEqual(logs.records[0].getMessage(), "event=chain.reconcile_mismatch")
        del self.w.indexers.call_one
        self.w.indexers.upstreams = self.w.indexers.upstreams[:1]
        self.w.last["reconcile"] = self.s.now
        self.locker = self.s.register()
        inv = self.invoice()
        self.pay(inv["address"], 500000)
        self.ticks()
        self.assertEqual((self.get(inv)["status"], self.s.meta("credit_freeze")), ("seen", None))
        self.s.now = self.w.last["reconcile"] + RECONCILE_RECHECK_S
        self.ticks(2)
        self.assertEqual((self.s.meta("reconcile_mismatch"), self.s.meta("credit_freeze")), (None, None))
        self.assertEqual(self.get(inv)["status"], "credited")

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
