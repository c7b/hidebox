# SPDX-License-Identifier: MIT
"""The launch trigger (deploy/ootle/launch.py) against a fake walletd and a fake indexer: it waits for the network
and the funds, reveals, publishes our exact bytes once, creates the log, writes the evidence, survives a crash
between submit and result, halts after a failed transaction, and a dry run never submits anything."""
import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("launch", ROOT / "deploy" / "ootle" / "launch.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)

KEY = "ab" * 32
ACCOUNT = "component_" + "cd" * 32
LOG = "component_" + "ef" * 32
TARI = "resource_" + "01" * 32


class Chain:
    def __init__(self, wasm: bytes):
        self.wasm, self.live, self.public, self.stealth = wasm, False, 0, 0
        self.templates, self.components, self.txs, self.calls = {}, {}, {}, []
        self.fail_next = None
        self.lock = threading.Lock()

    def template_id(self) -> str:
        return "template_" + launch.wasm_check.template_address(KEY, self.wasm)

    def walletd(self, method: str, p: dict):
        self.calls.append(method)
        if method == "auth.request":
            return {"token": "t"}
        if method == "wallet.get_info":
            return {"network": "esmeralda", "network_byte": 38, "version": "0.50.0"}
        if method == "accounts.list":
            return {"accounts": [{"account": {"name": "rehearsal", "component_address": ACCOUNT, "owner_public_key": KEY,
                                              "owner_key_id": {"Derived": {"index": 2, "key_branch": "account"}}}}]}
        if method == "accounts.get":
            return {"address": "otl_esm_1self"}
        if method == "accounts.get_balances":
            return {"balances": [{"resource_address": TARI, "balance": str(self.public),
                                  "confidential_balance": str(self.stealth)}]}
        if method == "substates.get":
            return {"substate": {"Component": self.components[p["substate_id"]]["Component"]}}
        if method == "burn_proofs.list":
            return {"burn_proofs": []}
        if method == "accounts.stealth_transfer":
            assert p["transfers"][0]["destination_address"] == "otl_esm_1self"
            if p["dry_run"]:
                return {"transaction_id": "d" * 64, "dry_run_result": {"finalize": {"result": {"Accept": {}}}}}
            amount = int(p["transfers"][0]["revealed_output_amount"])
            self.stealth -= amount
            self.public += amount
            return self.tx("reveal")
        if method == "transactions.submit_dry_run":
            v1 = p["transaction"]["V1"]
            assert v1["network"] == 38 and v1["dry_run"] and v1["main_signer"] == "SealSigner"
            binary = __import__("base64").b64decode(v1["blobs"][0])
            ups = [[self.template_id(), {"substate": {"Template": {"binary": binary.hex()}}}]]
            return {"transaction_id": "e" * 64, "required_fees": 800000,
                    "result": {"finalize": {"result": {"Accept": {"up_substates": ups}},
                                            "fee_receipt": {"total_fees_paid": 800000}}}}
        if method == "transactions.submit":
            assert not p["transaction"]["V1"]["dry_run"]
            self.public -= 842_994                           # the publish's fee, from the public vault
            self.templates[self.template_id()] = {"Template": {"template_name": "SealLog", "author": KEY,
                                                               "binary": self.wasm.hex(), "at_epoch": 12951}}
            return self.tx("publish")
        if method == "transactions.submit_manifest":
            assert p["seal_signer_key_id"] == {"Derived": {"index": 2, "key_branch": "account"}}
            assert self.template_id().removeprefix("template_") in p["manifest"]
            if p["dry_run"]:
                return {"transaction_id": "f" * 64, "result": {"finalize": {"result": {"Accept": {}}}}}
            self.components[LOG] = {"Component": {"header": {
                "template_address": self.template_id().removeprefix("template_"), "owner_rule": "None",
                "upgrade_rule": "Locked", "access_rules": {"default": "DenyAll", "method_access": {"append_root": {
                    "Restricted": {"Require": {"Require": {"NonFungibleAddress": {
                        "resource_address": "resource_01" + "0" * 62, "id": {"U256": KEY}}}}}}}}}}}
            return self.tx("log", created=LOG)
        if method == "transactions.wait_result":
            tx = self.txs[p["transaction_id"]]
            status = self.fail_next or "Accepted"
            self.fail_next = None
            return {"transaction_id": p["transaction_id"], "status": status, "final_fee": 1234, "timed_out": False,
                    "result": {"created": tx.get("created")}}
        raise AssertionError(f"unexpected walletd call {method}")

    def tx(self, kind: str, **extra) -> dict:
        tx = hashlib.sha256(f"{kind}{len(self.txs)}".encode()).hexdigest()
        self.txs[tx] = {"kind": kind, **extra}
        return {"transaction_id": tx}

    def indexer(self, path: str):
        if path == "/epoch-manager/stats":
            return 200, ({"current_epoch": 12951, "consensus_epoch": 12951, "current_block_height": 1036100} if self.live
                         else {"current_epoch": 0, "consensus_epoch": None, "current_block_height": 0})
        if path.startswith("/substates/"):
            sid = path.split("/")[2]
            value = self.templates.get(sid) or self.components.get(sid)
            return (200, {"state": {"up": {"substate": value}}, "verified": True}) if value else (404, {})
        if path.startswith("/transactions/") and path.endswith("/result"):
            return 200, {"result": {"Finalized": {"final_decision": "Commit", "finalized_time": "2026-11-11 11:11:12.0"}}}
        return 404, {}


def serve(handler_fn):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(*handler_fn("GET", self.path, None))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.reply(*handler_fn("POST", self.path, body))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-launch-"))
        self.wasm = (ROOT / "template" / "dist" / "seal_log.wasm").read_bytes()
        self.chain = Chain(self.wasm)

        def walletd(method, path, body):
            with self.chain.lock:
                return 200, {"jsonrpc": "2.0", "id": body["id"], "result": self.chain.walletd(body["method"], body["params"])}
        self.wd = serve(walletd)
        self.ix = serve(lambda method, path, body: self.chain.indexer(path))
        (self.tmp / "seal_log.wasm").write_bytes(self.wasm)
        self.cfg = {"network": "esmeralda", "walletd_url": f"http://127.0.0.1:{self.wd.server_address[1]}/json_rpc",
                    "account": "rehearsal", "indexers": [f"http://127.0.0.1:{self.ix.server_address[1]}"],
                    "wasm": str(self.tmp / "seal_log.wasm"), "wasm_sha256": hashlib.sha256(self.wasm).hexdigest(),
                    "state_dir": str(self.tmp / "state"), "min_public_ut": 2_200_000, "reveal_ut": 3_000_000,
                    "max_fee_reveal_ut": 100_000, "max_fee_publish_ut": 2_000_000, "max_fee_log_ut": 100_000,
                    "label": "test"}
        (self.tmp / "state").mkdir()
        launch.WAIT_RESULT_S = 1

    def tearDown(self):
        for s in (self.wd, self.ix):
            s.shutdown()
            s.server_close()

    def run_pass(self, dry=False) -> dict:
        code = launch.Run(self.cfg, dry).run()
        status = json.loads((self.tmp / "state" / "status.json").read_text())
        status["exit"] = code
        return status

    def submits(self):
        return [c for c in self.chain.calls if c in ("transactions.submit", "accounts.stealth_transfer",
                                                    "transactions.submit_manifest")]

    def test_waits_reveals_publishes_once_and_writes_the_evidence(self):
        self.assertEqual(self.run_pass()["message"].split(" (")[0], "the esmeralda indexer is not live yet")
        self.chain.live = True
        self.assertIn("not enough TARI yet", self.run_pass()["message"])
        self.chain.stealth = 5_000_000                       # walletd claimed a burn: a stealth output
        self.assertIn("revealing 3000000", self.run_pass()["message"])
        status = self.run_pass()                             # the reveal is final: on to the publish and the log
        self.assertEqual((status["state"], status["exit"]), ("done", 0), status)
        evidence = json.loads((self.tmp / "state" / "evidence.json").read_text())
        self.assertEqual(evidence["template"]["address"], self.chain.template_id())
        self.assertEqual(evidence["template"]["author_public_key"], KEY)
        self.assertEqual(evidence["template"]["wasm_sha256"], hashlib.sha256(self.wasm).hexdigest())
        self.assertEqual(evidence["template"]["publish"]["finalized_time"], "2026-11-11 11:11:12.0")
        self.assertEqual(evidence["template"]["at_epoch"], 12951)
        self.assertEqual(evidence["log"]["component"], LOG)
        self.assertEqual(evidence["log"]["header"]["upgrade_rule"], "Locked")
        self.assertEqual(self.chain.calls.count("transactions.submit"), 1)
        before = len(self.chain.calls)
        self.assertEqual(self.run_pass()["state"], "done")   # every later pass does nothing
        self.assertEqual(len(self.chain.calls), before)

    def test_a_crash_after_submit_waits_on_the_same_transaction(self):
        self.chain.live, self.chain.public = True, 5_000_000
        real_wait = launch.Run.wait_tx

        def crash(self, tx, what):
            raise KeyboardInterrupt
        launch.Run.wait_tx = crash
        try:
            with self.assertRaises(KeyboardInterrupt):
                launch.Run(self.cfg, False).run()
        finally:
            launch.Run.wait_tx = real_wait
        state = json.loads((self.tmp / "state" / "state.json").read_text())
        self.assertIn("publish_tx", state)
        self.assertEqual(self.run_pass()["state"], "done")
        self.assertEqual(self.chain.calls.count("transactions.submit"), 1)

    def test_the_publish_fee_doesnt_stop_the_next_pass(self):
        """Live rehearsal 2026-11-06: the publish's fee took the public vault under min_public_ut; the next pass must
        wait on the publish and create the log, not wait for funds the publish no longer needs."""
        self.chain.live, self.chain.public = True, 2_300_000
        real_wait = launch.Run.wait_tx

        def crash(self, tx, what):
            raise KeyboardInterrupt
        launch.Run.wait_tx = crash
        try:
            with self.assertRaises(KeyboardInterrupt):
                launch.Run(self.cfg, False).run()
        finally:
            launch.Run.wait_tx = real_wait
        self.assertLess(self.chain.public, self.cfg["min_public_ut"])
        self.assertEqual(self.run_pass()["state"], "done")
        self.assertEqual(self.chain.calls.count("transactions.submit"), 1)

    def test_installed_beside_its_helpers_it_reads_encoded_values(self):
        self.assertIs(launch.wasm_check.decoder(), launch.cbor)

    def test_a_template_already_on_chain_is_not_published_again(self):
        self.chain.live, self.chain.public = True, 5_000_000
        self.chain.templates[self.chain.template_id()] = {"Template": {"template_name": "SealLog", "author": KEY,
                                                                       "binary": self.wasm.hex(), "at_epoch": 1}}
        self.assertEqual(self.run_pass()["state"], "done")
        self.assertNotIn("transactions.submit", self.chain.calls)

    def test_a_failed_publish_halts_until_a_person_unhalts(self):
        self.chain.live, self.chain.public = True, 5_000_000
        self.chain.fail_next = "OnlyFeeAccepted"
        status = self.run_pass()
        self.assertEqual((status["state"], status["exit"]), ("attention", 1))
        self.assertIn("halted", status["message"])
        before = self.submits()
        self.assertEqual(self.run_pass()["step"], "halted")
        self.assertEqual(self.submits(), before)

    def test_a_dry_run_submits_nothing(self):
        self.chain.live, self.chain.stealth = True, 5_000_000
        status = self.run_pass(dry=True)
        self.assertIn("dry run: would reveal", status["message"])
        self.chain.public, self.chain.stealth = 5_000_000, 0
        status = self.run_pass(dry=True)
        self.assertIn("dry run: the publish is accepted", status["message"])
        self.assertNotIn("transactions.submit", self.chain.calls)
        self.assertEqual([c for c in self.chain.calls if c == "accounts.stealth_transfer"], ["accounts.stealth_transfer"])

    def test_wrong_network_and_wrong_bytes(self):
        self.chain.live = True
        bad = dict(self.cfg, network="mainnet")
        self.assertEqual(launch.Run(bad, False).run(), 1)
        self.assertIn("not mainnet", json.loads((self.tmp / "state" / "status.json").read_text())["message"])
        with self.assertRaises(launch.Fail):
            launch.Run(dict(self.cfg, wasm_sha256="00" * 32), False)

    def test_the_log_header_must_be_locked_and_ownerless(self):
        good = {"owner_rule": "None", "upgrade_rule": "Locked", "access_rules": {"default": "DenyAll", "method_access": {
            "append_root": {"Restricted": {"Require": {"Require": {"NonFungibleAddress": {
                "resource_address": "resource_01" + "0" * 62, "id": {"U256": KEY}}}}}}}}}
        self.assertEqual(launch.log_header_problems(good, KEY), [])
        for change in ({"owner_rule": {"OwnedBySigner": None}}, {"upgrade_rule": "OwnerOnly"}, {"upgrade_rule": None},
                       {"access_rules": {"default": "AllowAll", "method_access": good["access_rules"]["method_access"]}}):
            self.assertTrue(launch.log_header_problems({**good, **change}, KEY), change)
        self.assertTrue(launch.log_header_problems(good, "cd" * 32))      # another key's badge
        self.assertTrue(launch.log_header_problems({}, KEY))

    def test_decision(self):
        self.assertEqual(launch.decision({"status": "Accepted", "timed_out": False}), "Commit")
        self.assertIsNone(launch.decision({"status": "Pending", "timed_out": False}))
        self.assertIsNone(launch.decision({"status": "Accepted", "timed_out": True}))
        self.assertEqual(launch.decision({"status": "Rejected", "timed_out": False}), "Rejected")


if __name__ == "__main__":
    unittest.main()


class BurnGuardTest(unittest.TestCase):
    """deploy/ootle/burn-guard.py: the start height is final only from a pinned final entry that the source
    confirms, for the walletd version installed; a placeholder never is."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("burn_guard", ROOT / "deploy" / "ootle" / "burn-guard.py")
        self.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.guard)
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-guard-"))
        self.walletd = self.tmp / "walletd"
        self.walletd.write_text("#!/bin/sh\necho tari_ootle_walletd 0.50.1\n")
        self.walletd.chmod(0o755)

    def pins(self, **pin):
        doc = json.loads((ROOT / "deploy" / "ootle" / "mainnet-start-height.json").read_text())
        doc["pins"] = [{"ootle_version": "0.50.1", "source_ref": "v0.50.1", "start_height": 381_900, "final": True,
                        "why": "test", **pin}]
        path = self.tmp / "pins.json"
        path.write_text(json.dumps(doc))
        return path

    def height(self, source: str, **pin):
        self.guard.fetch = lambda url: source.encode()
        problems = []
        return self.guard.start_height(self.pins(**pin), self.walletd, problems), problems

    def test_the_shipped_pins_are_final_only_at_the_launch_height(self):
        doc = json.loads((ROOT / "deploy" / "ootle" / "mainnet-start-height.json").read_text())
        self.assertEqual({p["start_height"] for p in doc["pins"] if p["final"]}, {380_400})   # MainNet launched on it
        self.assertFalse(next(p for p in doc["pins"] if p["ootle_version"] == "0.50.0")["final"])

    def test_final_when_pinned_and_confirmed(self):
        value, problems = self.height("pub const MAINNET_START_HEIGHT: u64 = 381_900;")
        self.assertEqual((value, problems), (381_900, []))

    def test_refusals(self):
        self.assertIsNone(self.height("pub const MAINNET_START_HEIGHT: u64 = 381_901;")[0])          # source differs
        self.assertIsNone(self.height("pub const MAINNET_START_HEIGHT: u64 = 381_900;", final=False)[0])
        self.assertEqual(self.height("pub const MAINNET_START_HEIGHT: u64 = 380_400;", start_height=380_400)[0], 380_400)
        self.assertIsNone(self.height("", ootle_version="0.50.0")[0])                                 # other version
        self.walletd.write_text("#!/bin/sh\nexit 1\n")
        value, problems = self.height("pub const MAINNET_START_HEIGHT: u64 = 381_900;")
        self.assertIsNone(value)
        self.assertIn("no mainnet walletd", problems[0])
