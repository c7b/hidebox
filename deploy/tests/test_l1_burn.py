# SPDX-License-Identifier: MIT
"""deploy/ootle/l1-burn.py against a fake console wallet: one burn per claim key, never two, and nothing sent
unless every check holds (the history, the journal, the guard, the funds). No network, no wallet."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("l1_burn", ROOT / "deploy" / "ootle" / "l1-burn.py")
l1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l1)

KEY = "a1" * 32
OTHER = "b2" * 32
START = 390_000
XTM = 1_000_000


class FakeWallet:
    """The gRPC answers of a burns-only console wallet, as protobuf, through Grpc.call."""

    def __init__(self):
        self.version, self.scanned, self.online = "6.2.0", START + 100, True
        self.available, self.incoming = 1000 * XTM, 0
        self.txs, self.proofs, self.calls, self.burn_answer = [], {}, [], None
        self.next = 1

    def add_burn(self, key, amount_xtm, status=1, cancelled=False):
        commitment = f"{self.next:064x}"
        self.next += 1
        self.txs.append({"tx_id": 1000 + self.next, "status": status, "direction": 2, "amount": amount_xtm * XTM,
                         "cancelled": cancelled, "outputs": [commitment, f"{self.next + 500:064x}"]})
        self.proofs[commitment] = key
        return self.txs[-1]

    @staticmethod
    def tx_msg(t):
        return l1.pb((1, t["tx_id"]), (4, t["status"]), (5, t["direction"]), (6, t["amount"]), (7, 740),
                     (8, int(t["cancelled"])), *[(16, bytes.fromhex(c)) for c in t["outputs"]])

    def call(self, method, msg=b"", timeout=60):
        self.calls.append(method)
        req = l1.unpb(msg)
        ok = lambda body: (0, "", [body])  # noqa: E731
        if method == "GetVersion":
            return ok(l1.pb((1, self.version.encode())))
        if method == "GetState":
            return ok(l1.pb((1, self.scanned), (2, l1.pb((1, self.available))),
                            (3, l1.pb((1, l1.ONLINE if self.online else 3), (3, 1)))))
        if method == "GetBalance":
            return ok(l1.pb((1, self.available), (2, self.incoming)))
        if method == "GetAllCompletedTransactions":
            offset, limit = l1.first(req, 1, 0), l1.first(req, 2, 0)
            return ok(l1.pb(*[(1, self.tx_msg(t)) for t in self.txs[offset:offset + limit]]))
        if method == "GetTransactionInfo":
            return ok(l1.pb(*[(1, self.tx_msg(t)) for t in self.txs if t["tx_id"] in req.get(1, [])]))
        if method == "GetBurnClaimProof":
            c = l1.first(req, 1).hex()
            if c not in self.proofs:
                return l1.NOT_FOUND, "No burn claim proof found", []
            return ok(l1.pb((1, l1.pb((1, bytes.fromhex(c)), (3, bytes.fromhex(self.proofs[c])))), (5, 1)))
        if method == "CreateBurnTransaction":
            assert set(req) == {1, 2, 4}, f"fields {sorted(req)}: payment id and sidechain key must stay empty"
            if self.burn_answer:
                return self.burn_answer
            key, amount = l1.first(req, 4).hex(), l1.first(req, 1)
            t = self.add_burn(key, amount // XTM)
            t["status"] = 0
            self.available -= amount + 740
            return ok(l1.pb((1, t["tx_id"]), (2, 1), (4, bytes.fromhex(t["outputs"][0])), (6, bytes.fromhex(key))))
        raise AssertionError(method)


class L1BurnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["MUTIS_INSTANCE"] = "testinst"
        self.wallet = FakeWallet()
        self.guard_tip = START + 105
        patches = {"account_key": lambda lay, account: {"service": KEY, "sponsor": OTHER}[account]}
        for name, fn in patches.items():
            old = getattr(l1, name)
            setattr(l1, name, fn)
            self.addCleanup(setattr, l1, name, old)
        old_call, old_guard = l1.Grpc.call, l1.Burn.guard
        l1.Grpc.call = lambda g, method, msg=b"", timeout=60: self.wallet.call(method, msg, timeout)
        l1.Burn.guard = lambda b, key, amount_ut: self.guard_tip
        self.addCleanup(setattr, l1.Grpc, "call", old_call)
        self.addCleanup(setattr, l1.Burn, "guard", old_guard)

    def burn(self, account="service", amount="100", dry=False):
        args = argparse.Namespace(account=account, amount_xtm=amount, start_height=START, claim_key=None, dry_run=dry,
                                  drill_esmeralda=False, walletd_port=None, expect_version=None, grpc_port=None,
                                  proofs_dir=f"{self.tmp.name}/proofs", journal_dir=f"{self.tmp.name}/journal")
        with contextlib.redirect_stdout(io.StringIO()):
            return l1.Burn(args).run()

    def journal(self, account="service"):
        return json.loads(Path(self.tmp.name, "journal", f"{account}.json").read_text())

    def test_the_request_is_the_tui_burn(self):
        self.assertEqual(l1.pb((1, 100 * XTM), (2, l1.FEE_PER_GRAM), (4, bytes.fromhex(KEY))).hex(),
                         "0880c2d72f1005" + "2220" + KEY)

    def test_burns_once_then_finds_it(self):
        r = self.burn()
        self.assertEqual(r["outcome"], "sent")
        self.assertEqual(self.wallet.calls.count("CreateBurnTransaction"), 1)
        j = self.journal()
        self.assertEqual((j["state"], j["tx_id"], j["claim_key"], j["problems"]), ("sent", r["tx_id"], KEY, []))
        self.assertTrue(r["proof_file"].endswith(f"/proofs/{KEY}-{r['commitment']}.json"))
        again = self.burn()
        self.assertEqual((again["outcome"], again["tx_id"]), ("already", r["tx_id"]))
        Path(self.tmp.name, "journal", "service.json").unlink()        # the journal lost: the history still knows
        self.assertEqual(self.burn()["outcome"], "already")
        self.assertEqual(self.wallet.calls.count("CreateBurnTransaction"), 1)

    def test_a_burn_made_in_the_tui_counts(self):
        self.wallet.add_burn(KEY, 100)
        r = self.burn()
        self.assertEqual(r["outcome"], "already")
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)
        self.assertEqual(self.journal()["state"], "sent")

    def test_an_intent_without_a_burn_stops_everything(self):
        Path(self.tmp.name, "journal").mkdir()
        Path(self.tmp.name, "journal", "service.json").write_text(json.dumps(
            {"state": "intent", "claim_key": KEY, "amount_ut": 100 * XTM, "intent_at": "x"}))
        with self.assertRaises(l1.Refused):
            self.burn()
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)

    def test_an_intent_with_its_burn_is_recovered(self):
        t = self.wallet.add_burn(KEY, 100)
        Path(self.tmp.name, "journal").mkdir()
        Path(self.tmp.name, "journal", "service.json").write_text(json.dumps(
            {"state": "intent", "claim_key": KEY, "amount_ut": 100 * XTM, "intent_at": "x"}))
        r = self.burn()
        self.assertEqual((r["outcome"], r["tx_id"]), ("already", t["tx_id"]))
        self.assertEqual(self.journal()["state"], "sent")
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)

    def test_other_outbound_or_dead_burns_refuse(self):
        self.wallet.txs.append({"tx_id": 7, "status": 1, "direction": 2, "amount": 5 * XTM, "cancelled": False,
                                "outputs": ["ab" * 32]})
        with self.assertRaises(l1.Refused):
            self.burn()
        self.wallet.txs.clear()
        self.wallet.add_burn(KEY, 100, status=7)                        # rejected
        with self.assertRaises(l1.Refused):
            self.burn()
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)

    def test_a_burn_to_the_other_key_is_fine(self):
        self.wallet.add_burn(OTHER, 150)
        self.assertEqual(self.burn()["outcome"], "sent")

    def test_a_proof_file_without_history_refuses(self):
        Path(self.tmp.name, "proofs", "claimed").mkdir(parents=True)
        Path(self.tmp.name, "proofs", "claimed", f"{KEY}-{'00' * 32}.json").write_text("{}")
        with self.assertRaises(l1.Refused):
            self.burn()

    def test_funds(self):
        self.wallet.available, self.wallet.incoming = 10 * XTM, 900 * XTM   # the change of the first burn
        with self.assertRaises(l1.NotYet):
            self.burn(account="sponsor", amount="150")
        self.wallet.incoming = 0
        with self.assertRaises(l1.Refused):
            self.burn(account="sponsor", amount="150")
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)
        self.assertFalse(Path(self.tmp.name, "journal", "sponsor.json").exists())

    def test_amounts_and_the_wallet(self):
        for bad in ("0", "-1", "201", "0.0000001", "x"):
            with self.assertRaises(l1.Refused, msg=bad):
                self.burn(amount=bad)
        self.wallet.version = "6.1.0"
        with self.assertRaises(l1.Refused):
            self.burn()
        self.wallet.version, self.wallet.online = "6.2.0", False
        with self.assertRaises(l1.NotYet):
            self.burn()
        self.wallet.online, self.wallet.scanned = True, START - 1
        with self.assertRaises(l1.NotYet):
            self.burn()
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)

    def test_the_drill_never_points_at_the_mainnet_wallet(self):
        args = argparse.Namespace(account="service", amount_xtm="5", start_height=0, claim_key=KEY, dry_run=False,
                                  drill_esmeralda=True, walletd_port=5102, expect_version="6.1.0",
                                  grpc_port=l1.wallet_settings()["grpc_port"], proofs_dir=f"{self.tmp.name}/proofs",
                                  journal_dir=f"{self.tmp.name}/journal")
        with self.assertRaises(l1.Refused), contextlib.redirect_stdout(io.StringIO()):
            l1.Burn(args).run()
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)

    def test_dry_run_sends_nothing(self):
        r = self.burn(dry=True)
        self.assertEqual(r["outcome"], "dry_run")
        self.assertEqual(r["request_hex"], "0880c2d72f1005" + "2220" + KEY)
        self.assertNotIn("CreateBurnTransaction", self.wallet.calls)
        self.assertFalse(Path(self.tmp.name, "journal", "service.json").exists())

    def test_a_refused_burn_leaves_a_retryable_journal(self):
        self.wallet.burn_answer = (0, "", [l1.pb((2, 0), (3, b"Insufficient funds"))])
        with self.assertRaises(l1.Refused):
            self.burn()
        self.assertEqual(self.journal()["state"], "failed")
        self.wallet.burn_answer = None
        self.assertEqual(self.burn()["outcome"], "sent")

    def test_a_refused_connection_sends_nothing_and_may_retry(self):
        def refused(method, msg=b"", timeout=60):
            if method == "CreateBurnTransaction":
                raise l1.NotSent("CreateBurnTransaction: curl exited 7: Failed to connect")
            return FakeWallet.call(self.wallet, method, msg, timeout)
        self.wallet.call = refused
        with self.assertRaises(l1.NotYet):
            self.burn()
        self.assertEqual(self.journal()["state"], "failed")
        self.wallet.call = lambda *a, **k: FakeWallet.call(self.wallet, *a, **k)
        self.assertEqual(self.burn()["outcome"], "sent")

    def test_an_unknown_outcome_keeps_the_intent(self):
        def boom(method, msg=b"", timeout=60):
            if method == "CreateBurnTransaction":
                raise TimeoutError("curl timed out")
            return FakeWallet.call(self.wallet, method, msg, timeout)
        self.wallet.call = boom
        with self.assertRaises(l1.Refused):
            self.burn()
        self.assertEqual(self.journal()["state"], "intent")
        self.wallet.call = lambda *a, **k: FakeWallet.call(self.wallet, *a, **k)
        with self.assertRaises(l1.Refused):                             # and the next run won't send either
            self.burn()


class GuardOutputTest(unittest.TestCase):
    """What burn-guard.py prints decides; its exact lines are parsed, never guessed."""

    def setUp(self):
        os.environ["MUTIS_INSTANCE"] = "testinst"
        self.args = argparse.Namespace(start_height=START, drill_esmeralda=False, expect_version=None, grpc_port=None,
                                       proofs_dir="/nonexistent", journal_dir="/nonexistent")
        self.old = l1.subprocess.run
        self.addCleanup(setattr, l1.subprocess, "run", self.old)

    def guard(self, out, rc=0):
        l1.subprocess.run = lambda *a, **k: argparse.Namespace(returncode=rc, stdout=out, stderr="")
        with contextlib.redirect_stdout(io.StringIO()):
            return l1.Burn(self.args).guard(KEY, 100 * XTM)

    def test_yes(self):
        out = (f"ok  MAINNET_START_HEIGHT {START:,} (Ootle 0.53.1, v0.53.1: x)\nok  L1 mainnet tip {START + 7:,} (explorer)\n"
               "ok  claim key = account service (walletd holds it)\nok  sidechain key empty (the Ootle)\nok  amount 100 XTM\n"
               "\nburn-guard: yes. In the mainnet console wallet, exactly this")
        self.assertEqual(self.guard(out), START + 7)
        with self.assertRaises(l1.Refused):            # another start height than the one the caller found final
            self.guard(out.replace(f"{START:,}", f"{START + 1:,}", 1))
        with self.assertRaises(l1.NotYet):             # the tip at the height, not past it
            self.guard(out.replace(f"tip {START + 7:,}", f"tip {START:,}"))

    def test_no(self):
        with self.assertRaises(l1.NotYet):
            self.guard(f"NO  the L1 tip 1 is below MAINNET_START_HEIGHT {START:,}: a burn now would be lost\n"
                       "burn-guard: refused. Burn nothing.", rc=1)
        with self.assertRaises(l1.NotYet):             # two reads that may work next time
            self.guard("NO  could not read the L1 tip from x (timeout)\nNO  could not read y at v1 (timeout)\n"
                       "burn-guard: refused. Burn nothing.", rc=1)
        with self.assertRaises(l1.Refused):
            self.guard("NO  the claim key is none of this instance's mainnet accounts\nburn-guard: refused.", rc=1)
        with self.assertRaises(l1.Refused):            # a transient read beside a real no is still a no
            self.guard("NO  could not read the L1 tip from x (timeout)\nNO  the sidechain key must be empty\n"
                       "burn-guard: refused.", rc=1)


if __name__ == "__main__":
    unittest.main()
