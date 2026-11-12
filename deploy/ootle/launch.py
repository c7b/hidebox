#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The launch trigger: publish SealLog and create its log as soon as a network can take them, unattended.

  launch.py run    --config launch.toml [--dry-run]    one pass (the timer runs one every 30 s): do the next steps
  launch.py status --config launch.toml                 print the status file
  launch.py unhalt --config launch.toml                 after a person has looked at a failed transaction

Each pass, in order, and only as far as it can get (a step that can't be done yet leaves the next pass to try):
  1. indexer   an indexer of the network answers with a live epoch (consensus_epoch set, block height > 0)
  2. walletd   our walletd answers, runs on that network, and holds the account
  3. funds     the account's public vault holds min_public_ut (what pay_fee draws on); if not, and its stealth
               balance can cover it, reveal reveal_ut into the public vault with a stealth transfer to itself
               (reset-playbook.md §3; walletd claims burns into stealth outputs by itself)
  4. publish   the template: a transaction built here, one PublishTemplate instruction with seal_log.wasm byte for
               byte as its blob, the fee from the account, sealed by walletd with the account's key, which becomes
               the author (deploy/ootle/publish-template.sh does the same by hand). A dry run first: Accept, and the
               chain would hold our bytes. Then submit, wait, and read the template back from an indexer.
  5. log       SealLog::new from a manifest signed by the same key (it becomes the only writer), owner None and
               upgrade Locked; the header is read back and checked.
  6. evidence  the template and component addresses, both transaction ids, their finalized times and epochs, the
               author key, the wasm's hash and the fees, in evidence.json; then the state is "done" and every later
               pass does nothing.
Idempotent: every transaction id is written to state.json before it is waited on, so a pass after a crash waits on
the same transaction instead of sending another; a template already on chain with our bytes and author is never
published again (its address is a hash of both). status.json says where it is, for a person to watch.

--dry-run (or dry_run = true in the config) goes through every step with dry runs only: nothing is submitted,
nothing is spent, the state never becomes "done". Python standard library only; cbor.py and wasm_check.py are
read from the same directory (deploy/ootle/launch-arm.sh installs them beside this file).
"""
import argparse
import base64
import contextlib
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARI = "resource_" + "01" * 32
NETWORKS = {"esmeralda": 0x26, "mainnet": 0x00}
ADDRESS = re.compile(r"[0-9a-f]{64}")
KEY_BADGES = "resource_01" + "0" * 62
WAIT_RESULT_S = 240


def _load(name: str, *paths: Path):
    for path in paths:
        if path.is_file():
            spec = importlib.util.spec_from_file_location(f"launch_{name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise SystemExit(f"launch: {name}.py not found next to launch.py")


cbor = _load("cbor", HERE / "cbor.py", HERE.parents[1] / "server" / "mutis" / "cbor.py")
wasm_check = _load("wasm_check", HERE / "wasm_check.py", HERE.parents[1] / "template" / "wasm_check.py")
wasm_check.decoder = lambda: cbor      # installed beside this file, wasm_check.py can't find server/mutis/cbor.py


class Wait(Exception):
    """A step can't be done yet; the next pass tries again. The message goes to status.json."""


class Fail(Exception):
    """Something is wrong in a way another pass won't fix by itself; a person must look."""


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- outside world ----------------------------------------------------------------------------------------

def http_json(url: str, body: dict | None = None, timeout: float = 30, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "mutis-launch", "Accept": "application/json",
                                                          **({"Content-Type": "application/json"} if data else {}),
                                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


class Walletd:
    """walletd JSON-RPC (deploy/ootle/walletd-rpc.py's calls); the JWT lives in memory only."""

    def __init__(self, url: str):
        self.url, self.token = url, None

    def call(self, method: str, params: dict, timeout: float = 120):
        if self.token is None and method != "auth.request":
            self.token = self.call("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        answer = http_json(self.url, body, timeout, {"Authorization": "Bearer " + self.token} if self.token else None)
        if "error" in answer:
            raise WalletdError(method, answer["error"].get("message", "error"))
        return answer["result"]


class WalletdError(Exception):
    def __init__(self, method: str, message: str):
        super().__init__(f"{method}: {message}")
        self.message = message


class Run:
    def __init__(self, cfg: dict, dry_run: bool):
        self.cfg, self.dry_run = cfg, dry_run
        self.network = cfg["network"]
        if self.network not in NETWORKS:
            raise SystemExit(f"launch: network must be one of {', '.join(NETWORKS)}")
        self.byte = NETWORKS[self.network]
        self.dir = Path(cfg["state_dir"])
        self.state_path, self.status_path = self.dir / "state.json", self.dir / "status.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.is_file() else {}
        self.walletd = Walletd(cfg["walletd_url"])
        self.indexers = [u.rstrip("/") for u in cfg["indexers"]]
        self.wasm = Path(cfg["wasm"]).read_bytes()
        if hashlib.sha256(self.wasm).hexdigest() != cfg["wasm_sha256"]:
            raise Fail(f"{cfg['wasm']} is not the armed seal_log.wasm (sha256 {cfg['wasm_sha256'][:16]}…)")

    # --- bookkeeping ----------------------------------------------------------------------------------------

    def halt(self, why: str) -> None:
        """A submitted transaction failed (and may have cost its fee): no pass submits anything again until a
        person has looked and run `launch.py unhalt` (the failed transaction id stays in state.json)."""
        self.state["halted"] = {"why": why, "at": now_iso()}
        self.save()
        raise Fail(f"{why}; halted: nothing more is sent until `launch.py unhalt --config …`")

    def save(self) -> None:
        write_json(self.state_path, self.state)

    def status(self, step: str, state: str, message: str, **extra) -> None:
        doc = {"label": self.cfg.get("label", ""), "network": self.network, "step": step, "state": state,
               "message": message, "dry_run": self.dry_run, "updated_at": now_iso(),
               "template": self.state.get("template"), "component": self.state.get("component"), **extra}
        write_json(self.status_path, doc)
        print(f"launch: [{step}] {state}: {message}", flush=True)

    def log(self, event: str, **fields) -> None:
        with open(self.dir / "launch.log", "a") as f:
            f.write(json.dumps({"at": now_iso(), "event": event, "dry_run": self.dry_run, **fields}) + "\n")

    # --- the indexers -----------------------------------------------------------------------------------------

    def indexer_get(self, path: str):
        last = None
        for base in self.indexers:
            try:
                return http_json(f"{base}/{path}", timeout=20)
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = e
        raise Wait(f"no indexer answers {path.split('/')[0]} ({last})")

    def live_epoch(self) -> dict:
        stats = self.indexer_get("epoch-manager/stats")
        live = (isinstance(stats, dict) and int(stats.get("current_epoch") or 0) > 0
                and stats.get("consensus_epoch") is not None and int(stats.get("current_block_height") or 0) > 0)
        if not live:
            raise Wait(f"the {self.network} indexer is not live yet (epoch {stats.get('current_epoch')}, "
                       f"consensus {stats.get('consensus_epoch')})")
        return stats

    def substate(self, address: str) -> dict | None:
        for base in self.indexers:
            try:
                body = http_json(f"{base}/substates/{address}", timeout=30)
            except urllib.error.HTTPError as e:      # 404: not on this indexer (yet)
                e.close()
                continue
            except (urllib.error.URLError, OSError, ValueError):
                continue
            value = wasm_check.substate_value(body)
            if value:
                return {"value": value, "body": body, "indexer": base}
        return None

    def tx_result(self, tx: str) -> dict | None:
        for path in (f"transactions/{tx}/result", f"transaction-receipts/{tx}"):
            for base in self.indexers:
                try:
                    return {"path": path, "body": http_json(f"{base}/{path}", timeout=20), "indexer": base}
                except (urllib.error.URLError, OSError, ValueError):
                    continue
        return None

    # --- the steps ----------------------------------------------------------------------------------------------

    def account(self) -> dict:
        info = self.walletd.call("wallet.get_info", {})
        named = str(info.get("network", "")).lower()
        if named not in (self.network, "esme" if self.network == "esmeralda" else self.network) or \
                ("network_byte" in info and info["network_byte"] != self.byte):
            raise Fail(f"walletd runs on {info.get('network')!r}, not {self.network}")
        accounts = self.walletd.call("accounts.list", {"offset": 0, "limit": 100})["accounts"]
        name = self.cfg["account"]
        found = next((e for e in accounts if e["account"]["name"] == name), None)
        if found is None:
            raise Fail(f"walletd has no account named {name}")
        a = found["account"]
        if not ADDRESS.fullmatch(a.get("owner_public_key", "")):
            raise Fail(f"account {name} has no owner public key")
        self.state.setdefault("author", a["owner_public_key"])
        if self.state["author"] != a["owner_public_key"]:
            raise Fail("the account's key changed since the first pass")
        return {"name": name, "component": a["component_address"], "key": a["owner_public_key"],
                "key_id": a["owner_key_id"], "version": info.get("version")}

    def balances(self, account: dict) -> tuple[int, int]:
        result = self.walletd.call("accounts.get_balances", {"account": {"Name": account["name"]}, "refresh": True})
        public = sum(int(b.get("balance") or 0) for b in result.get("balances", []) if b.get("resource_address") == TARI)
        hidden = sum(int(b.get("confidential_balance") or 0) for b in result.get("balances", [])
                     if b.get("resource_address") == TARI)
        return public, hidden

    def funds(self, account: dict) -> None:
        """What the remaining steps' pay_fee calls lock: both fees' ceilings before the publish, the log's after it."""
        published = self.state.get("publish_tx") or self.state.get("template")
        need = int(self.cfg["max_fee_log_ut"]) if published else int(self.cfg["min_public_ut"])
        reveal = int(self.cfg["reveal_ut"])
        public, hidden = self.balances(account)
        self.state["balances"] = {"public_ut": public, "stealth_ut": hidden, "at": now_iso()}
        if public >= need:
            return
        pending = self.state.get("reveal_tx")
        if pending:
            outcome = self.wait_tx(pending, "reveal")
            if outcome != "Commit":
                self.halt(f"the reveal {pending} ended {outcome}")
            if not self.state.get("reveal_seen") == pending:
                self.state["reveal_seen"] = pending       # one more pass for the vault to show it, then reveal again
                raise Wait(f"revealed {reveal} µT in {pending[:16]}…; waiting for the public vault to show it "
                           f"(public {public} µT, need {need})")
            self.state.setdefault("reveals", []).append(self.state.pop("reveal_tx"))
            if len(self.state["reveals"]) >= 3:
                self.halt(f"three reveals and the public vault still holds {public} µT, under {need}")
        fee = int(self.cfg["max_fee_reveal_ut"])
        if hidden < reveal + fee:
            claims = self.claims()
            raise Wait(f"not enough TARI yet: public {public} µT, stealth {hidden} µT, need {need} public "
                       f"(or {reveal + fee} stealth to reveal){claims}")
        address = self.walletd.call("accounts.get", {"name_or_address": account["name"]})["address"]
        params = {"owner_account": {"Name": account["name"]},
                  "fee_params": {"input_selection": "PreferConfidential", "pay_fee_with_swap": None},
                  "input_selection": "PreferConfidential", "resource_address": TARI,
                  "transfers": [{"destination_address": address, "blinded_output_amount": "0",
                                 "revealed_output_amount": str(reveal), "pay_to": "StealthPublicKey",
                                 "attach_sender_address": False}],
                  "max_fee": str(fee)}
        dry = self.walletd.call("accounts.stealth_transfer", {**params, "dry_run": True})
        self.log("reveal_dry_run", verdict=verdict(dry), result=_brief(dry))
        if verdict(dry) != "Accept":
            raise Fail(f"the reveal's dry run says {verdict(dry)}: {reason(dry)}")
        if self.dry_run:
            raise Wait(f"dry run: would reveal {reveal} µT into {account['name']}'s public vault")
        tx = self.walletd.call("accounts.stealth_transfer", {**params, "dry_run": False})["transaction_id"]
        self.state["reveal_tx"] = tx
        self.save()
        self.log("reveal_submitted", tx=tx, amount_ut=reveal)
        raise Wait(f"revealing {reveal} µT into the public vault: tx {tx}")

    def claims(self) -> str:
        try:
            proofs = self.walletd.call("burn_proofs.list", {"filter_by_public_key": None})
        except (WalletdError, urllib.error.URLError, OSError):
            return ""
        items = proofs.get("burn_proofs", proofs.get("proofs", [])) if isinstance(proofs, dict) else proofs
        return f"; walletd sees {len(items)} burn proof(s) waiting to be claimed" if items else ""

    def publish_transaction(self, account: dict, epoch: int, dry: bool) -> dict:
        fee = int(self.cfg["max_fee_publish_ut"])
        transaction = {"V1": {
            "network": self.byte,
            "fee_instructions": [{"CallMethod": {"call": {"Address": account["component"]}, "method": "pay_fee",
                                                 "args": [{"Literal": (b"\x1a" + fee.to_bytes(4, "big")).hex()}]}}],
            "instructions": [{"PublishTemplate": {"binary": 0, "metadata_hash": None}}],
            # The seal signer (the account's key) is the main signer, so it authors the template.
            "inputs": [], "min_epoch": None, "max_epoch": epoch + 2, "main_signer": "SealSigner", "dry_run": dry,
            "blobs": [base64.b64encode(self.wasm).decode()],
            "nonce": str(secrets.randbits(63)),
        }}
        return {"transaction": transaction, "seal_signer": account["key_id"], "other_signers": [], "lock_ids": [],
                "detect_inputs": True, "detect_inputs_use_unversioned": True}

    def template_onchain(self, address: str) -> dict | None:
        found = self.substate(address)
        template = (found or {}).get("value", {}).get("Template")
        if not isinstance(template, dict):
            return None
        binary = bytes.fromhex(template["binary"])
        if binary != self.wasm or template.get("author") != self.state["author"]:
            raise Fail(f"{address} on chain holds other bytes or another author than ours")
        return {"epoch": template.get("at_epoch"), "name": template.get("template_name"), "indexer": found["indexer"],
                "verified": found["body"].get("verified")}

    def publish(self, account: dict, stats: dict) -> None:
        if self.state.get("template"):
            return
        predicted = "template_" + wasm_check.template_address(self.state["author"], self.wasm)
        self.state["predicted_template"] = predicted
        onchain = self.template_onchain(predicted)
        if onchain:
            self.state["template"] = predicted
            self.state["template_onchain"] = onchain
            self.save()
            self.log("template_found", template=predicted)
            return
        tx = self.state.get("publish_tx")
        if not tx:
            dry = self.walletd.call("transactions.submit_dry_run",
                                    self.publish_transaction(account, int(stats["current_epoch"]), True), timeout=180)
            said, fee, holds = dry_run_template(dry, self.wasm)
            self.log("publish_dry_run", verdict=said, fee_ut=fee, template=holds)
            if said != "Accept":
                raise Fail(f"the publish dry run says {said}: {reason(dry)}")
            if holds != predicted:
                raise Fail(f"the dry run would create {holds}, not the predicted {predicted} with our bytes")
            self.state["publish_dry_run_fee_ut"] = fee
            if self.dry_run:
                raise Wait(f"dry run: the publish is accepted ({fee} µT) and would create {predicted}")
            tx = self.walletd.call("transactions.submit",
                                   self.publish_transaction(account, int(stats["current_epoch"]), False),
                                   timeout=180)["transaction_id"]
            self.state["publish_tx"] = tx
            self.state["publish_submitted_at"] = now_iso()
            self.save()
            self.log("publish_submitted", tx=tx, template=predicted)
            self.status("publish", "working", f"publish submitted: tx {tx}")
        outcome = self.wait_tx(tx, "publish")
        if outcome != "Commit":
            self.halt(f"the publish {tx} ended {outcome}")
        for _ in range(12):
            onchain = self.template_onchain(predicted)
            if onchain:
                break
            time.sleep(5)
        else:
            raise Wait(f"the publish {tx} is final; waiting for an indexer to serve {predicted}")
        self.state.update({"template": predicted, "template_onchain": onchain})
        self.save()
        self.log("template_published", template=predicted, tx=tx)

    def manifest(self, account: dict, dry: bool) -> dict:
        template = self.state["template"].removeprefix("template_")
        fee = int(self.cfg["max_fee_log_ut"])
        text = (f"use template_{template} as SealLog;\n"
                f"fn fee_main() {{ let account = var![\"account\"]; account.pay_fee({fee}); }}\n"
                "fn main() { let alloc = new_component_addr!(); SealLog::new(alloc); }\n")
        # The account's own key seals it, so it pays and becomes the log's only writer (walletd 0.50:
        # seal_signer_key_id; an older walletd signs with its default account, which must then be this one).
        params = {"manifest": text, "variables": {"account": account["component"]}, "max_fee": str(fee), "dry_run": dry}
        if self.state.get("signer_param", True):
            params["seal_signer_key_id"] = account["key_id"]
        return params

    def log_component(self, account: dict) -> None:
        if self.state.get("component"):
            return
        tx = self.state.get("log_tx")
        if not tx:
            try:
                dry = self.walletd.call("transactions.submit_manifest", self.manifest(account, True), timeout=180)
            except WalletdError as e:
                if "seal_signer_key_id" not in e.message and "unknown field" not in e.message:
                    raise
                self.state["signer_param"] = False        # walletd before 0.50: it signs with its default account
                dry = self.walletd.call("transactions.submit_manifest", self.manifest(account, True), timeout=180)
            self.log("log_dry_run", verdict=verdict(dry), result=_brief(dry))
            if verdict(dry) != "Accept":
                raise Fail(f"the SealLog::new dry run says {verdict(dry)}: {reason(dry)}")
            if self.dry_run:
                raise Wait(f"dry run: SealLog::new on {self.state['template']} is ready to send")
            tx = self.walletd.call("transactions.submit_manifest", self.manifest(account, False), timeout=180)["transaction_id"]
            self.state["log_tx"] = tx
            self.state["log_submitted_at"] = now_iso()
            self.save()
            self.log("log_submitted", tx=tx)
            self.status("log", "working", f"SealLog::new submitted: tx {tx}")
        result = self.walletd.call("transactions.wait_result", {"transaction_id": tx, "timeout_secs": WAIT_RESULT_S},
                                   timeout=WAIT_RESULT_S + 30)
        outcome = decision(result)
        if outcome != "Commit":
            if outcome is None:
                raise Wait(f"SealLog::new {tx} not final yet")
            self.halt(f"SealLog::new {tx} ended {outcome}")
        components = sorted(set(re.findall(r"component_[0-9a-f]{64}", json.dumps(result))) - {account["component"]})
        if len(components) != 1:
            raise Fail(f"SealLog::new {tx} created {components}, expected one component")
        self.state["component"] = components[0]
        self.state["log_fee_ut"] = result.get("final_fee")
        self.save()
        self.log("log_created", component=components[0], tx=tx)

    def check_log(self) -> dict:
        found = self.substate(self.state["component"])
        if not found:
            raise Wait(f"waiting for an indexer to serve {self.state['component']}")
        # The indexer's Encoded value gives cbor.py the template address only; walletd decodes the whole header.
        decoded = self.walletd.call("substates.get", {"substate_id": self.state["component"]})
        header = _find(decoded, "header")
        if not isinstance(header, dict):
            raise Wait(f"walletd doesn't show {self.state['component']}'s header yet")
        template = header.get("template_address", "")
        self.state["component_onchain"] = {"template": template, "indexer": found["indexer"],
                                           "verified": found["body"].get("verified")}
        if template and "template_" + template.removeprefix("template_") != self.state["template"]:
            raise Fail(f"{self.state['component']} runs {template}, not {self.state['template']}")
        return header

    def wait_tx(self, tx: str, what: str) -> str | None:
        result = self.walletd.call("transactions.wait_result", {"transaction_id": tx, "timeout_secs": WAIT_RESULT_S},
                                   timeout=WAIT_RESULT_S + 30)
        outcome = decision(result)
        if outcome is None:
            raise Wait(f"the {what} {tx} is not final yet")
        self.state.setdefault("fees_ut", {})[what] = result.get("final_fee")
        return outcome

    def finalized(self, tx: str) -> dict:
        found = self.tx_result(tx)
        if not found:
            return {"tx": tx}
        body = found["body"]
        final = (body.get("result") or {}).get("Finalized") if isinstance(body, dict) else None
        out = {"tx": tx, "indexer": found["indexer"]}
        if isinstance(final, dict):
            out.update({"decision": final.get("final_decision"), "finalized_time": final.get("finalized_time")})
        return out

    def evidence(self) -> None:
        stats = self.live_epoch()
        doc = {
            "what": "SealLog published and its log created by the mutis launch trigger (deploy/ootle/launch.py)",
            "network": self.network, "label": self.cfg.get("label", ""),
            "template": {"address": self.state["template"], "author_public_key": self.state["author"],
                         "wasm_sha256": hashlib.sha256(self.wasm).hexdigest(), "wasm_bytes": len(self.wasm),
                         "publish": self.finalized(self.state["publish_tx"]) if self.state.get("publish_tx") else None,
                         "submitted_at": self.state.get("publish_submitted_at"),
                         "at_epoch": (self.state.get("template_onchain") or {}).get("epoch"),
                         "dry_run_fee_ut": self.state.get("publish_dry_run_fee_ut")},
            "log": {"component": self.state["component"], "create": self.finalized(self.state["log_tx"]),
                    "submitted_at": self.state.get("log_submitted_at"), "fee_ut": self.state.get("log_fee_ut"),
                    "header": self.state.get("component_header")},
            "fees_ut": self.state.get("fees_ut", {}),
            "epoch_at_evidence": stats.get("current_epoch"), "l1_height_at_evidence": stats.get("current_block_height"),
            "written_at": now_iso(),
        }
        write_json(self.dir / "evidence.json", doc)
        self.state["evidence"] = str(self.dir / "evidence.json")

    # --- one pass ----------------------------------------------------------------------------------------------

    def run(self) -> int:
        if self.state.get("halted"):
            self.status("halted", "attention", f"{self.state['halted']['why']} (since {self.state['halted']['at']}); "
                        "look, then `launch.py unhalt --config …`")
            return 1
        if self.state.get("done"):
            self.status("done", "done", f"published {self.state['template']}, log {self.state['component']}")
            return 0
        step = "indexer"
        try:
            stats = self.live_epoch()
            step = "walletd"
            account = self.account()
            step = "funds"
            if not self.state.get("component") and not self.state.get("log_tx") and \
                    not (self.state.get("publish_tx") and not self.state.get("template")):
                self.funds(account)                  # a transaction in flight is waited on below, never re-funded
            step = "publish"
            self.publish(account, stats)
            step = "log"
            self.log_component(account)
            header = self.check_log()
            problems = log_header_problems(header, self.state["author"])
            self.state["component_header"] = {k: header.get(k) for k in ("owner_rule", "upgrade_rule", "template_address",
                                                                       "access_rules")}
            if problems:
                raise Fail(f"the log's header is not what SealLog::new writes: {'; '.join(problems)}")
            step = "evidence"
            self.evidence()
            if not self.dry_run:
                self.state["done"] = now_iso()
            self.save()
            self.status("done", "done", f"published {self.state['template']}, log {self.state['component']}",
                        evidence=self.state["evidence"])
            return 0
        except Wait as e:
            self.save()
            self.status(step, "waiting", str(e))
            return 0
        except (Fail, WalletdError) as e:
            self.save()
            self.status(step, "attention", str(e))
            self.log("attention", step=step, message=str(e))
            return 1
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            self.save()
            self.status(step, "waiting", f"{type(e).__name__}: {e}")
            return 0


def decision(result) -> str | None:
    """"Commit" for an accepted transaction, None while it isn't final, else walletd's status (Rejected,
    InvalidTransaction, OnlyFeeAccepted: the fee was taken and nothing else happened). transactions.wait_result
    answers {transaction_id, result, status, final_fee, timed_out}; status is New, DryRun, Pending, Accepted, …"""
    status = result.get("status") if isinstance(result, dict) else None
    if not isinstance(result, dict) or result.get("timed_out") or status in (None, "New", "Pending"):
        return None
    return "Commit" if status == "Accepted" else str(status)


def _finalize(answer) -> dict:
    """A dry run's FinalizeResult: transactions.submit_dry_run and submit_manifest answer {result: ExecuteResult},
    accounts.stealth_transfer {dry_run_result: ExecuteResult}; an ExecuteResult is {finalize: FinalizeResult, …}."""
    if not isinstance(answer, dict):
        return {}
    execute = answer.get("result") or answer.get("dry_run_result") or {}
    return execute.get("finalize", execute) if isinstance(execute, dict) else {}


def verdict(answer) -> str:
    """Accept, AcceptFeeRejectRest or Reject (FinalizeResult.result), or Unknown."""
    result = _finalize(answer).get("result")
    return next(iter(result)) if isinstance(result, dict) and result else "Unknown"


def reason(answer) -> str:
    result = _finalize(answer).get("result")
    return json.dumps(result)[:300] if result else json.dumps(answer)[:300]


def dry_run_template(answer: dict, wasm: bytes) -> tuple[str, int | None, str | None]:
    """The dry run's verdict, its fee, and the template it would create with exactly `wasm`."""
    final = _finalize(answer)
    fee = (final.get("fee_receipt") or {}).get("total_fees_paid")
    for sid, up in (final.get("result") or {}).get("Accept", {}).get("up_substates", []):
        if sid.startswith("template_"):
            value = up["substate"]
            value = cbor.substate_value(cbor.b64(value)) if isinstance(value, str) else value
            if bytes.fromhex(value["Template"]["binary"]) == wasm:
                return verdict(answer), fee, sid
            return verdict(answer), fee, None
    return verdict(answer), fee, None


def _find(value, key: str):
    if isinstance(value, dict):
        if key in value:
            return value[key]
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            found = _find(item, key)
            if found is not None:
                return found
    return None


def log_header_problems(header: dict, writer: str) -> list[str]:
    """web/app/lib/seallog.js readSealLog's checks, every one required: nobody owns the log, nobody can swap its
    code, every method is denied unless named, and only the author's key badge may append."""
    problems = []
    if header.get("owner_rule") != "None":
        problems.append(f"owner_rule {header.get('owner_rule')!r}")
    if header.get("upgrade_rule") != "Locked":
        problems.append(f"upgrade_rule {header.get('upgrade_rule')!r}")
    rules = header.get("access_rules") if isinstance(header.get("access_rules"), dict) else {}
    if rules.get("default") != "DenyAll":
        problems.append("the default rule is not DenyAll")
    badge = (rules.get("method_access", {}).get("append_root") or {})
    nf = _find(badge, "NonFungibleAddress") or {}
    if not isinstance(nf, dict) or nf.get("resource_address") != KEY_BADGES or (nf.get("id") or {}).get("U256") != writer:
        problems.append("append_root is not restricted to the author's key badge")
    return problems


def _brief(answer) -> dict:
    """What a dry run says, small enough for a log line."""
    if not isinstance(answer, dict):
        return {"answer": str(answer)[:200]}
    out = {k: answer.get(k) for k in ("transaction_id", "required_fees", "fee", "status") if k in answer}
    text = json.dumps(answer)
    for word in ("Accept", "Reject", "AccessDenied", "InsufficientFunds", "Abort"):
        if word in text:
            out.setdefault("mentions", []).append(word)
    return out


def write_json(path: Path, doc) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    required = ("network", "walletd_url", "account", "indexers", "wasm", "wasm_sha256", "state_dir", "min_public_ut",
                "reveal_ut", "max_fee_reveal_ut", "max_fee_publish_ut", "max_fee_log_ut")
    missing = [k for k in required if k not in cfg]
    if missing:
        raise SystemExit(f"launch: {path} is missing {', '.join(missing)}")
    return cfg


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command", choices=("run", "status", "unhalt"))
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true", help="dry runs only: nothing is submitted or spent")
    args = p.parse_args()
    cfg = load_config(args.config)
    state_dir = Path(cfg["state_dir"])
    if args.command == "status":
        status = state_dir / "status.json"
        print(status.read_text() if status.is_file() else "launch: no pass has run yet")
        return 0
    os.umask(0o077)
    state_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "unhalt":
        path = state_dir / "state.json"
        state = json.loads(path.read_text()) if path.is_file() else {}
        halted = state.pop("halted", None)
        for key in ("reveal_tx", "publish_tx", "log_tx"):     # the failed one; the evidence keeps nothing of it
            if halted and key in state and state[key] in halted["why"]:
                state.setdefault("failed", []).append({"tx": state.pop(key), "why": halted["why"]})
        write_json(path, state)
        print(f"launch: unhalted ({halted['why'] if halted else 'it was not halted'})")
        return 0
    with open(state_dir / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("launch: another pass is running", flush=True)
            return 0
        try:
            run = Run(cfg, args.dry_run or bool(cfg.get("dry_run")))
        except Fail as e:
            write_json(state_dir / "status.json", {"step": "arm", "state": "attention", "message": str(e),
                                                   "updated_at": now_iso()})
            print(f"launch: {e}", file=sys.stderr)
            return 1
        with contextlib.suppress(KeyboardInterrupt):
            return run.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
