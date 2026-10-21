# SPDX-License-Identifier: MIT
"""R1 (research 16-drive-architecture §1.1, §4.4, §9): a pack payment counts only if our receiver can spend it.

Like the 2026-09-29 forged-deposit incident (community.tari.com/t/402), this is a check that looked done
and wasn't: the sidecar proves an output's amount and memo with our receiver's VIEW key, and an indexer
proves it exists, but nothing proved the output is ours to spend. A payer can build an output that opens
with our view key while its one-time key is the payer's own (createStealthOutputWitness takes the owner
and view public keys separately), get a pack and keep the money; spending it back later would make the
hourly reconcile find a credited output gone twice and freeze every pack credit until a human acts.

The fix compares the one-time key the indexer shows (`auth.Key`) with the one our owner key derives from
the output's nonce (`stealthDhSecret` in the sidecar's `oneTimeKey`). These tests run on the fake chain
only: the bug-hunt rule keeps forged outputs off the public testnet. The real library's half is the
sidecar's offline KAT (web/app/sidecar/selftest.json `not_ours`, run by `selftest`).
"""
import unittest

from harness import Stack
from mutis import codec, db, payments
from mutis.fake_chain import fake_keys
from mutis.sidecar import SidecarError


class ReceiverOwnership(unittest.TestCase):
    def setUp(self):
        self.s = Stack(chain=True)
        self.w = self.s.worker
        self.w.setup()
        with db.tx(self.s.conn):             # today's evidence payment is already done
            db.set_meta(self.s.conn, "evidence_pay_day", codec.day(self.s.now))
        self.locker = self.s.register()
        self.payer = fake_keys()             # someone paying "us" with an output they keep

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

    def paid_bytes(self) -> int:
        return self.s.request("GET", "/api/v1/me", headers=self.locker["auth"])[2]["quota"]["paid_bytes"]

    def payment(self, utxo_id: str):
        return self.s.conn.execute("SELECT * FROM payments WHERE utxo_id = ?", (utxo_id,)).fetchone()

    def test_an_output_our_view_key_opens_but_we_cant_spend_is_rejected(self):
        """The forgery: amount proven with our view key, committed on chain, memo naming the invoice, and
        still not ours. It is recorded once as `rejected` and never credits the pack (E-14, server part)."""
        inv = self.invoice()
        with self.assertLogs("mutis", "WARNING") as logs:
            forged = self.s.chain.add_output(inv["address"], 500000, None, spender=self.payer["address"])
            self.ticks()
        self.assertIn("event=chain.payment_not_ours", [r.getMessage() for r in logs.records])
        row = self.payment(forged)
        self.assertEqual((row["status"], row["proven"], row["value_ut"]), ("rejected", 1, 500000))
        self.assertNotEqual(self.get(inv)["status"], "credited")
        self.assertEqual(self.paid_bytes(), 0)
        self.ticks()                                       # a rejected output is never looked at again
        self.assertEqual(self.payment(forged)["status"], "rejected")

    def test_a_genuine_payment_after_a_forgery_still_credits(self):
        inv = self.invoice()
        self.s.chain.add_output(inv["address"], 500000, None, spender=self.payer["address"])
        self.ticks()
        self.s.chain.transfer("service", inv["address"], 500000, None, 30000)
        self.ticks()
        got = self.get(inv)
        self.assertEqual((got["status"], got["received_ut"]), ("credited", "500000"))
        self.assertEqual(self.paid_bytes(), 256 << 20)
        statuses = sorted(r[0] for r in self.s.conn.execute("SELECT status FROM payments"))
        self.assertEqual(statuses, ["credited", "rejected"])

    def test_a_spend_rule_that_is_not_a_key_is_rejected(self):
        """An output locked by another rule than a one-time key can't be spent by our owner key either."""
        inv = self.invoice()
        other = self.s.chain.add_output(inv["address"], 500000, None, auth={"Script": "00" * 32})
        self.ticks()
        self.assertEqual(self.payment(other)["status"], "rejected")
        self.assertNotEqual(self.get(inv)["status"], "credited")

    def test_the_reconcile_ignores_rejected_outputs(self):
        """The forger spends their output back: the hourly reconcile only re-proves credited outputs, so it
        finds nothing missing and credits stay open for everyone."""
        genuine = self.invoice()
        self.s.chain.transfer("service", genuine["address"], 500000, None, 30000)
        buyer, self.locker = self.locker, self.s.register()   # the forger's own drive
        forged_inv = self.invoice()
        self.locker = buyer
        forged = self.s.chain.add_output(forged_inv["address"], 500000, None, spender=self.payer["address"])
        self.ticks()
        self.assertEqual(self.get(genuine)["status"], "credited")
        with self.s.chain.lock:                            # the payer spends the output they kept
            next(o for o in self.s.chain.outputs if forged.endswith(o["commitment"]))["spent"] = True
        for _ in range(2):
            self.assertEqual(payments.reconcile(
                self.s.conn, lambda rows: {f["id"]: f["value_ut"] for f in self.w._scan(self.s.receiver["view_sk"],
                                                                                        rows)},
                lambda uid: payments.committed_anywhere(self.w.indexers, uid), self.s.now), "ok")
        self.assertIsNone(self.s.meta("credit_freeze"))

    def test_a_sidecar_that_cant_answer_holds_the_payment(self):
        """No answer about ownership is never a credit: the payment waits, then credits once the sidecar
        answers again."""
        inv = self.invoice()
        self.s.chain.transfer("service", inv["address"], 500000, None, 30000)
        real = self.w.sidecar.request

        def broken(cmd, **fields):
            if cmd == "oneTimeKey":
                raise SidecarError("timeout")
            return real(cmd, **fields)
        self.w.sidecar.request = broken
        self.ticks()
        row = self.s.conn.execute("SELECT status FROM payments").fetchone()
        self.assertEqual((row["status"], self.get(inv)["status"]), ("pending_check", "seen"))
        self.w.sidecar.request = real
        self.ticks()
        self.assertEqual(self.get(inv)["status"], "credited")

    def test_the_check_reads_the_key_and_nonce_the_indexer_shows(self):
        """`owns` gets the substate's own nonce and one-time key; the verdicts map to credit, reject, wait."""
        inv = self.invoice()
        self.s.chain.transfer("service", inv["address"], 500000, None, 30000)
        self.ticks(1)                                      # mirrored and recorded; checked below by hand
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE payments SET status = 'pending_check'")
            self.s.conn.execute("UPDATE invoices SET status = 'seen', received_ut = 0")
        row = self.s.conn.execute("SELECT utxo_id FROM payments").fetchone()
        output = next(o for o in self.s.chain.outputs if row["utxo_id"].endswith(o["commitment"]))
        asked = []

        def owns(answer):
            return lambda nonce, key: (asked.append((nonce, key)), answer)[1]
        self.assertEqual(payments.check_pending(self.s.conn, self.w.indexers, {}, self.s.now, owns(None)), 0)
        self.assertEqual(asked, [(output["nonce"], output["auth"]["Key"])])
        self.assertEqual(self.payment(row["utxo_id"])["status"], "pending_check")
        self.assertEqual(payments.check_pending(self.s.conn, self.w.indexers, {}, self.s.now, owns(True)), 1)
        self.assertEqual(self.payment(row["utxo_id"])["status"], "credited")
        self.assertTrue(self.w._ours(output["nonce"], output["auth"]["Key"]))
        self.assertFalse(self.w._ours(output["nonce"], "00" * 32))
        self.assertFalse(self.w._ours(output["nonce"], None))


if __name__ == "__main__":
    unittest.main()
