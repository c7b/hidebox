#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Make an instance's mainnet burn unattended, once per account, through the running Minotari console wallet.

  sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/l1-burn.py burn --account service --amount-xtm <N> \\
      --start-height <the final MAINNET_START_HEIGHT> [--claim-key <64 hex>] [--dry-run]
  sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/l1-burn.py status

burn asks the wallet service mutis-<name>-l1wallet-mainnet (l1-wallet-mainnet.sh start) over its gRPC on
127.0.0.1 for one CreateBurnTransaction. That is the call the TUI's Burn tab makes: both end in the wallet's
transaction_service.burn_tari with the same arguments (the account's claim public key, no sidechain deployment
key, an empty payment id, default UTXO selection, fee per gram 5), and the wallet process that made the burn
writes its proof, once the burn is mined, as <claim key>-<commitment>.json into its --burn-proof-out directory,
the burn_proofs directory the instance's mainnet walletd claims from (read in tari v6.2.0:
transaction_event_handler.rs, grpc/wallet_grpc_server.rs, ui/components/burn_tab.rs). It sends nothing unless all
of these hold:
  1. burn-guard.py says yes for exactly this account's claim key (account-<name>.json's account_public_key), an
     empty sidechain key and this amount, and the MAINNET_START_HEIGHT it checked is --start-height, the value
     the caller found final; the L1 tip it read is past that height;
  2. the wallet answers as the pinned version (l1-wallet-mainnet.sh), online, and scanned past the start height
     to within a few blocks of that tip;
  3. no burn to this claim key exists: none in this script's journal, none in the wallet's history (every output
     of every outbound transaction, cancelled ones too, is looked up as a burn proof), no proof file for the key in
     the burn_proofs directory; and every outbound transaction in the history is a burn to some claim key;
  4. the amount is more than 0 and at most MAX_XTM, and the wallet's available balance covers it with room for the fee.
The journal, /var/backups/mutis-<name>/l1-burns/<account>.json (root only), records the intent, fsynced, before
the call and the transaction after it. An intent with no transaction to show for it stops every later run for that
account until a person has looked (`status`, then delete the file). Nothing else in the wallet is touched: no
send, no cancel, no service stop; the wallet service keeps running.
Exit 0: done (sent now, or a burn to the key was already there); 2: not yet, nothing sent (try again later);
1: refused or failed, a person looks. The last line printed is RESULT {json}; every run is also appended to
the journal's runs.jsonl. --drill-esmeralda (with --grpc-port, --proofs-dir, --journal-dir, --claim-key,
--walletd-port, --expect-version) runs the same steps against a testnet console wallet, with the claim key
checked against a walletd's accounts in place of burn-guard.py, which is mainnet-only.
Python standard library, curl (HTTP/2) for the gRPC.
"""
import argparse
import contextlib
import datetime
import decimal
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import instance  # noqa: E402

SERVICE = "tari.rpc.Wallet"
UT = 1_000_000                 # µT per XTM
MAX_XTM = 200                  # burn-guard.py's --max-xtm default: burns stay small
FEE_PER_GRAM = 5               # the TUI's Burn tab default (the wallet's fee_per_gram)
FEE_ROOM_UT = 1_000_000        # beyond the amount, the available balance must hold this much for the fee
MAX_BEHIND = 10                # blocks the wallet's scanned height may trail the explorer's tip
ONLINE = 1                     # ConnectivityStatus::Online
OUTBOUND = 2                   # TransactionDirection::Outbound
NOT_FOUND = 5                  # gRPC status NOT_FOUND
STATUS = {0: "completed", 1: "broadcast", 2: "mined_unconfirmed", 3: "imported", 4: "pending", 5: "coinbase",
          6: "mined_confirmed", 7: "rejected", 8: "one_sided_unconfirmed", 9: "one_sided_confirmed", 10: "queued",
          11: "not_found", 12: "coinbase_unconfirmed", 13: "coinbase_confirmed", 14: "coinbase_not_in_block_chain"}
DEAD = {"rejected", "not_found", "coinbase_not_in_block_chain"}


class NotYet(Exception):
    """Nothing was sent; a later run may succeed."""


class Refused(Exception):
    """Nothing more is sent for this account until a person has looked."""


class NotSent(OSError):
    """curl could not connect to the wallet's gRPC port: no byte of the request left this machine."""


def now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- protobuf, the few shapes this needs --------------------------------------------------------------------------

def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def pb(*fields: tuple) -> bytes:
    """(number, int) as a varint, (number, bytes) length-delimited; empty bytes are left out, as proto3 does."""
    out = bytearray()
    for num, value in fields:
        if isinstance(value, bool) or not isinstance(value, (int, bytes)):
            raise TypeError(f"field {num}: {type(value).__name__}")
        if isinstance(value, int):
            out += varint(num << 3) + varint(value)
        elif value:
            out += varint(num << 3 | 2) + varint(len(value)) + value
    return bytes(out)


def unpb(buf: bytes) -> dict:
    out, i = {}, 0

    def read_varint() -> int:
        nonlocal i
        value = shift = 0
        while True:
            if i >= len(buf):
                raise ValueError("truncated varint")
            b = buf[i]
            i += 1
            value |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return value
    while i < len(buf):
        key = read_varint()
        num, wire = key >> 3, key & 7
        if wire == 0:
            value = read_varint()
        elif wire == 2:
            n = read_varint()
            value, i = buf[i:i + n], i + n
        elif wire in (1, 5):
            n = 8 if wire == 1 else 4
            value, i = int.from_bytes(buf[i:i + n], "little"), i + n
        else:
            raise ValueError(f"wire type {wire}")
        if i > len(buf):
            raise ValueError("truncated field")
        out.setdefault(num, []).append(value)
    return out


def first(d: dict, num: int, default=None):
    return d[num][0] if num in d else default


# --- the wallet's gRPC, over curl (HTTP/2 without TLS, as tonic serves it) -------------------------------------------

class Grpc:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}/{SERVICE}/"

    def call(self, method: str, msg: bytes = b"", timeout: int = 60) -> tuple[int, str, list[bytes]]:
        body = b"\0" + len(msg).to_bytes(4, "big") + msg
        with tempfile.TemporaryDirectory(prefix="l1-burn-") as tmp:
            headers = Path(tmp, "headers")
            res = subprocess.run(["curl", "-sS", "--http2-prior-knowledge", "--max-time", str(timeout),
                                  "-H", "content-type: application/grpc", "-H", "te: trailers",
                                  "--data-binary", "@-", "-D", str(headers), "-o", "-", self.base + method],
                                 input=body, capture_output=True, timeout=timeout + 60)
            text = headers.read_text(errors="replace") if headers.exists() else ""
        if res.returncode != 0:
            why = f"{method}: curl exited {res.returncode}: {res.stderr.decode(errors='replace').strip()[-200:]}"
            raise NotSent(why) if res.returncode == 7 else OSError(why)       # 7: CURLE_COULDNT_CONNECT
        codes = re.findall(r"^grpc-status:\s*(\d+)", text, re.M | re.I)
        if not codes:
            raise OSError(f"{method}: no grpc-status in the answer ({text.strip()[:200]!r})")
        message = re.findall(r"^grpc-message:\s*(.*?)\s*$", text, re.M | re.I)
        frames, data, i = [], res.stdout, 0
        while i < len(data):
            if i + 5 > len(data) or data[i] != 0:
                raise OSError(f"{method}: an unexpected gRPC frame at byte {i}")
            n = int.from_bytes(data[i + 1:i + 5], "big")
            frames.append(data[i + 5:i + 5 + n])
            i += 5 + n
        return int(codes[-1]), urllib.parse.unquote(message[-1]) if message else "", frames

    def unary(self, method: str, msg: bytes = b"", timeout: int = 60) -> dict:
        code, text, frames = self.call(method, msg, timeout)
        if code != 0:
            raise OSError(f"{method}: gRPC status {code}: {text[:200]}")
        if len(frames) != 1:
            raise OSError(f"{method}: {len(frames)} messages in a unary answer")
        return unpb(frames[0])


def tx_info(d: dict) -> dict:
    return {"tx_id": first(d, 1, 0), "status": STATUS.get(first(d, 4, 0), str(first(d, 4, 0))),
            "direction": first(d, 5, 0), "amount_ut": first(d, 6, 0), "fee_ut": first(d, 7, 0),
            "cancelled": bool(first(d, 8, 0)), "mined_height": first(d, 13, 0),
            "outputs": [c.hex() for c in d.get(16, [])], "rejected_reason": first(d, 20, b"").decode(errors="replace")}


def history(g: Grpc) -> list[dict]:
    """Every completed transaction, cancelled ones included (GetAllCompletedTransactions pages the whole table)."""
    out, offset = [], 0
    while True:
        page = [tx_info(unpb(t)) for t in g.unary("GetAllCompletedTransactions", pb((1, offset), (2, 50))).get(1, [])]
        out += page
        if len(page) < 50:
            return out
        offset += len(page)
        if offset > 5000:
            raise Refused("the wallet's history holds more than 5,000 transactions: not a burns-only wallet")


def burn_proof(g: Grpc, commitment: str) -> dict | None:
    code, text, frames = g.call("GetBurnClaimProof", pb((1, bytes.fromhex(commitment))))
    if code == NOT_FOUND:
        return None
    if code != 0 or len(frames) != 1:
        raise OSError(f"GetBurnClaimProof {commitment[:16]}…: gRPC status {code}: {text[:200]}")
    d = unpb(frames[0])
    claim = unpb(first(d, 1, b""))
    return {"claim_key": first(claim, 3, b"").hex(), "commitment": commitment, "value_ut": first(d, 5, 0),
            "mined_in_epoch": first(d, 6), "output_proof": 8 in d}


def scan(g: Grpc) -> tuple[list[dict], list[dict]]:
    """The burns in the wallet's history, and the outbound transactions that aren't burns to a claim key."""
    burns, other = [], []
    for t in history(g):
        if t["direction"] != OUTBOUND:
            continue
        found = [p for c in t["outputs"] if len(c) == 64 and (p := burn_proof(g, c))]
        if not found:
            other.append(t)
        for p in found:
            burns.append({**p, **{k: t[k] for k in ("tx_id", "status", "cancelled", "mined_height", "amount_ut",
                                                   "fee_ut", "rejected_reason")}})
    return burns, other


def live(burn: dict) -> bool:
    return not burn["cancelled"] and burn["status"] not in DEAD


# --- the instance ---------------------------------------------------------------------------------------------------

def wallet_settings() -> dict:
    text = (HERE / "l1-wallet-mainnet.sh").read_text()
    version = re.search(r"^VERSION=(\S+)$", text, re.M)
    port = re.search(r"^GRPC_PORT=(\d+)", text, re.M)
    if not version or not port:
        raise SystemExit("l1-burn: l1-wallet-mainnet.sh names no VERSION or GRPC_PORT")
    return {"version": version.group(1), "grpc_port": int(port.group(1))}


def account_key(lay, account: str) -> str:
    path = Path(lay.wallet_dir("mainnet"), f"account-{account}.json")
    key = json.loads(path.read_text())["account_public_key"]
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise Refused(f"{path.name}'s account_public_key is not 64 hex characters")
    return key


def walletd_owner_keys(port: int) -> dict:
    """The accounts a walletd holds, by owner public key (as burn-guard.py asks it)."""
    def rpc(method, params, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json_rpc", data=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)["result"]
    token = rpc("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]
    return {e["account"]["owner_public_key"]: e["account"]["name"]
            for e in rpc("accounts.list", {"offset": 0, "limit": 100}, token)["accounts"]}


def proof_files(proofs: Path, key: str) -> list[str]:
    return sorted(str(p) for p in proofs.rglob(f"{key}-*.json")) if proofs.is_dir() else []


def write_durable(path: Path, doc: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    with open(tmp, "w") as f:
        f.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def to_ut(amount: str) -> int:
    try:
        value = decimal.Decimal(amount) * UT
    except decimal.InvalidOperation:
        raise Refused(f"the amount {amount!r} is not a number of XTM") from None
    if value != value.to_integral_value() or not 0 < value <= MAX_XTM * UT:
        raise Refused(f"the amount must be more than 0 and at most {MAX_XTM} XTM, in whole µT: {amount}")
    return int(value)


# --- burn --------------------------------------------------------------------------------------------------------

class Burn:
    def __init__(self, args):
        self.args = args
        self.drill = args.drill_esmeralda
        self.lay = instance.layout(os.environ.get("MUTIS_INSTANCE"))
        if not self.lay.name:
            raise SystemExit("l1-burn: MUTIS_INSTANCE names no instance (production burns nothing on the mainnet)")
        settings = wallet_settings()
        self.version = args.expect_version or settings["version"]
        self.g = Grpc(args.grpc_port or settings["grpc_port"])
        self.proofs = Path(args.proofs_dir or f"{self.lay.drive_home}/.local/share/tari/mainnet/burn_proofs")
        self.jdir = Path(args.journal_dir or f"{self.lay.backups}/l1-burns")
        self.unit = f"mutis-{self.lay.name}-l1wallet-mainnet"
        self.notes: list[str] = []

    def note(self, line: str) -> None:
        self.notes.append(line)
        print(line, flush=True)

    def journal(self, account: str) -> Path:
        return self.jdir / f"{account}.json"

    def run(self) -> dict:
        a = self.args
        account = a.account
        if self.drill:
            if not a.claim_key or not a.walletd_port or not a.grpc_port or a.grpc_port == wallet_settings()["grpc_port"]:
                raise Refused("--drill-esmeralda needs --claim-key, --walletd-port and a testnet wallet's --grpc-port "
                              "(never the mainnet wallet's)")
            key = a.claim_key.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", key):
                raise Refused("the claim key must be 64 hex characters")
        else:
            key = account_key(self.lay, account)
            if a.claim_key and a.claim_key.strip().lower() != key:
                raise Refused(f"--claim-key is not account-{account}.json's account_public_key")
        amount_ut = to_ut(a.amount_xtm)
        self.note(f"l1-burn: {account}: {amount_ut / UT:g} XTM to claim key {key}")
        self.jdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.jdir, 0o700)
        with open(self.jdir / ".lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise NotYet("another l1-burn run holds the lock") from None
            return self.locked(account, key, amount_ut)

    def locked(self, account: str, key: str, amount_ut: int) -> dict:
        a = self.args
        jpath = self.journal(account)
        j = json.loads(jpath.read_text()) if jpath.is_file() else None
        if j and j.get("claim_key") != key:
            raise Refused(f"{jpath} is for claim key {j.get('claim_key')}, not {key}")
        burns, other = scan(self.g)
        mine = [b for b in burns if b["claim_key"] == key]
        base = {"account": account, "claim_key": key, "amount_ut": amount_ut}
        # 1. a burn to this key that is already there, or an earlier run that didn't finish
        if j and j.get("state") == "sent":
            b = next((b for b in mine if b["tx_id"] == j.get("tx_id")), None)
            if not b:
                raise Refused(f"the journal records tx {j.get('tx_id')} to this key, but the wallet's history has no such burn")
            if not live(b):
                raise Refused(f"the burn tx {b['tx_id']} to this key is {b['status']}{' (cancelled)' if b['cancelled'] else ''}"
                              f" {b['rejected_reason']}: a person checks before anything is burned again")
            return {**base, "outcome": "already", "tx_id": b["tx_id"], "commitment": b["commitment"],
                    "tx_status": b["status"], "mined_height": b["mined_height"],
                    "proof_file": self.proof_path(key, b["commitment"]), "proof_files": proof_files(self.proofs, key)}
        if j and j.get("state") == "intent":
            found = [b for b in mine if live(b) and b["amount_ut"] == j.get("amount_ut")]
            if len(found) == 1:
                b = found[0]
                write_durable(jpath, {**j, "state": "sent", "tx_id": b["tx_id"], "commitment": b["commitment"],
                                      "sent_at": j.get("intent_at"), "recovered_at": now(),
                                      "recovered_from": "the wallet's history (the earlier run stopped after the call)"})
                self.note(f"l1-burn: recovered tx {b['tx_id']} from the history: the earlier run stopped after its call")
                return {**base, "outcome": "already", "tx_id": b["tx_id"], "commitment": b["commitment"],
                        "tx_status": b["status"], "proof_file": self.proof_path(key, b["commitment"])}
            raise Refused(f"an earlier run recorded its intent at {j.get('intent_at')} and the wallet shows "
                          f"{len(mine)} burn(s) to this key: whether its call reached the wallet is unknown. A person "
                          f"checks (`l1-burn.py status`), then deletes {jpath}")
        if other:
            raise Refused("the wallet's history has outbound transaction(s) that are no burn to a claim key: "
                          + ", ".join(f"tx {t['tx_id']} ({t['status']}, {t['amount_ut'] / UT:g} XTM)" for t in other))
        if mine:
            alive = [b for b in mine if live(b)]
            if len(alive) == 1:
                b = alive[0]
                write_durable(jpath, {**base, "state": "sent", "tx_id": b["tx_id"], "commitment": b["commitment"],
                                      "found_at": now(), "amount_ut": b["amount_ut"],
                                      "found_in": "the wallet's history: a burn this script didn't make (the TUI)"})
                self.note(f"l1-burn: a burn to this key is already in the wallet's history (tx {b['tx_id']}, "
                          f"{b['amount_ut'] / UT:g} XTM, {b['status']}): nothing sent")
                return {**base, "outcome": "already", "tx_id": b["tx_id"], "commitment": b["commitment"],
                        "tx_status": b["status"], "amount_ut": b["amount_ut"],
                        "proof_file": self.proof_path(key, b["commitment"])}
            raise Refused("the wallet's history holds burns to this key that are cancelled, rejected or more than one: "
                          + ", ".join(f"tx {b['tx_id']} {b['status']}" for b in mine))
        files = proof_files(self.proofs, key)
        if files:
            raise Refused(f"a proof file for this key exists but the wallet's history has no burn to it: {files}")
        self.note(f"ok  no burn to this key yet ({len(burns)} burn(s) to other keys in the history, no proof file)")
        # 2. the wallet
        version = first(self.g.unary("GetVersion"), 1, b"").decode()
        if version != self.version:
            raise Refused(f"the wallet on the gRPC port says version {version!r}, not the pinned {self.version}")
        state = self.g.unary("GetState")
        scanned = first(state, 1, 0)
        net = unpb(first(state, 3, b""))
        if first(net, 1, 0) != ONLINE:
            raise NotYet(f"the wallet is not online (connectivity {first(net, 1, 0)}, {first(net, 3, 0)} connection(s))")
        if not scanned:
            raise NotYet("the wallet has scanned no block yet")
        # GetState's has_done_initial_validation is only set by a later change to a one-sided transaction (the
        # gRPC debouncer), so it stays false after a restart: the scanned height against the tip is the sync check.
        self.note(f"ok  wallet {version}, online, scanned to {scanned:,}")
        # 3. the guard: this key, an empty sidechain key, this amount, the final start height, the tip past it
        if self.drill:
            held = walletd_owner_keys(a.walletd_port)
            if key not in held:
                raise Refused(f"drill: the walletd on {a.walletd_port} holds no account with this key")
            self.note(f"ok  drill: the claim key is the walletd's account {held[key]} (burn-guard.py is mainnet-only)")
            tip = None
        else:
            tip = self.guard(key, amount_ut)
            if scanned < a.start_height or tip - scanned > MAX_BEHIND:
                raise NotYet(f"the wallet has scanned to {scanned:,}; the tip is {tip:,}, the start height {a.start_height:,}")
        # 4. the funds
        bal = self.g.unary("GetBalance")
        available, incoming = first(bal, 1, 0), first(bal, 2, 0)
        need = amount_ut + FEE_ROOM_UT
        if available < need:
            if available + incoming >= need:
                raise NotYet(f"{available / UT:g} XTM available, {incoming / UT:g} XTM still confirming (the change of "
                             f"an earlier burn); {need / UT:g} XTM needed")
            raise Refused(f"the wallet holds {available / UT:g} XTM available ({incoming / UT:g} incoming); this burn "
                          f"needs {need / UT:g} XTM: send XTM to the wallet (l1-wallet-mainnet.sh address)")
        self.note(f"ok  {available / UT:g} XTM available, {need / UT:g} XTM needed")
        request = pb((1, amount_ut), (2, FEE_PER_GRAM), (4, bytes.fromhex(key)))
        if a.dry_run:
            return {**base, "outcome": "dry_run", "request_hex": request.hex(), "available_ut": available,
                    "scanned_height": scanned, "tip": tip, "proofs_dir": str(self.proofs)}
        # 5. the intent, on disk before the call
        before = sorted({b["tx_id"] for b in burns})
        write_durable(jpath, {**base, "state": "intent", "intent_at": now(), "fee_per_gram": FEE_PER_GRAM,
                              "start_height": None if self.drill else a.start_height, "tip": tip,
                              "outbound_before": before, "request_hex": request.hex()})
        # 6. the call: CreateBurnTransaction {amount, fee_per_gram, claim_public_key}; payment_id and
        #    sidechain_deployment_key stay empty (the Ootle; an empty memo, as the TUI's empty Payment-id field gives)
        try:
            code, text, frames = self.g.call("CreateBurnTransaction", request, timeout=900)
        except NotSent as e:          # the connection itself failed (the service restarting): nothing reached the wallet
            write_durable(jpath, {**base, "state": "failed", "failed_at": now(), "reason": str(e)[:500],
                                  "note": "the connection to the wallet failed before any request was sent; a later run may retry"})
            raise NotYet(f"the wallet's gRPC port refused the connection: {e}") from None
        except Exception as e:
            raise Refused(f"the CreateBurnTransaction call's outcome is unknown ({type(e).__name__}: {e}); {jpath} keeps "
                          "the intent: a person checks `l1-burn.py status` before anything is sent again") from None
        resp = unpb(frames[0]) if code == 0 and len(frames) == 1 else {}
        ok, tx_id = bool(first(resp, 2, 0)), first(resp, 1, 0)
        if code != 0 or not ok or not tx_id:
            why = text if code != 0 else first(resp, 3, b"").decode(errors="replace")
            after, other_now = scan(self.g)
            new = sorted({b["tx_id"] for b in after} - set(before))
            if new or other_now:
                raise Refused(f"the wallet answered {why!r} but its history changed (new burn txs {new}, "
                              f"{len(other_now)} other outbound): a person checks")
            write_durable(jpath, {**base, "state": "failed", "failed_at": now(), "reason": why[:500],
                                  "note": "no transaction was made (the history is unchanged); a later run may retry"})
            raise Refused(f"the wallet made no burn: {why[:300]}")
        commitment = first(resp, 4, b"").hex()
        echoed = first(resp, 6, b"").hex()
        sent = {**base, "state": "sent", "tx_id": tx_id, "commitment": commitment, "sent_at": now(),
                "fee_per_gram": FEE_PER_GRAM, "start_height": None if self.drill else a.start_height,
                "response_claim_key": echoed, "proof_file": self.proof_path(key, commitment)}
        write_durable(jpath, sent)
        self.note(f"l1-burn: sent: tx {tx_id}, commitment {commitment}")
        # 7. what the wallet now holds for it
        problems = []
        if echoed != key:
            problems.append(f"the answer's claim key is {echoed}")
        if len(commitment) != 64:
            problems.append("the answer has no 32-byte commitment")
        info = [tx_info(unpb(t)) for t in self.g.unary("GetTransactionInfo", pb((1, tx_id))).get(1, [])]
        t = info[0] if info else {}
        if t.get("direction") != OUTBOUND or t.get("amount_ut") != amount_ut or commitment not in t.get("outputs", []):
            problems.append(f"GetTransactionInfo: {json.dumps(t)[:300]}")
        p = burn_proof(self.g, commitment) if len(commitment) == 64 else None
        if not p or p["claim_key"] != key:
            problems.append(f"GetBurnClaimProof: {p}")
        sent.update({"verified_at": now(), "tx_status": t.get("status"), "fee_ut": t.get("fee_ut"), "problems": problems})
        write_durable(jpath, sent)
        if problems:
            raise Refused(f"burn tx {tx_id} was made, but: {'; '.join(problems)}")
        self.note(f"ok  tx {tx_id} {t.get('status')}, {amount_ut / UT:g} XTM, fee {t.get('fee_ut', 0) / UT:g} XTM; the "
                  f"wallet holds its burn proof for this key; the proof file follows once it is mined: {sent['proof_file']}")
        return {**base, "outcome": "sent", "tx_id": tx_id, "commitment": commitment, "tx_status": t.get("status"),
                "fee_ut": t.get("fee_ut"), "proof_file": sent["proof_file"], "unit": self.unit_state()}

    def proof_path(self, key: str, commitment: str) -> str:
        return str(self.proofs / f"{key}-{commitment}.json")

    def unit_state(self) -> str:
        if self.drill:
            return "drill"
        return subprocess.run(["systemctl", "is-active", self.unit], capture_output=True, text=True).stdout.strip()

    def guard(self, key: str, amount_ut: int) -> int:
        a = self.args
        cmd = [sys.executable, "-I", str(HERE / "burn-guard.py"), "--claim-key", key, "--sidechain-key", "",
               "--amount-xtm", f"{decimal.Decimal(amount_ut) / UT}", "--max-xtm", str(MAX_XTM)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd="/tmp",
                             env={**os.environ, "MUTIS_INSTANCE": self.lay.name})
        out = res.stdout + res.stderr
        noes = [line for line in out.splitlines() if line.startswith("NO ")]
        if res.returncode != 0 or noes or "burn-guard: yes" not in out:
            if noes and all("below MAINNET_START_HEIGHT" in n or "could not read" in n for n in noes):
                raise NotYet(f"burn-guard.py: {'; '.join(noes)}")       # the tip, or a read that may work next time
            raise Refused(f"burn-guard.py says no: {'; '.join(noes) or out.strip()[-300:]}")
        m = re.search(r"^ok  MAINNET_START_HEIGHT ([0-9,]+) ", out, re.M)
        tip_m = re.search(r"^ok  L1 mainnet tip ([0-9,]+) ", out, re.M)
        start = int(m.group(1).replace(",", "")) if m else None
        tip = int(tip_m.group(1).replace(",", "")) if tip_m else None
        if start != a.start_height:
            raise Refused(f"burn-guard.py checked MAINNET_START_HEIGHT {start}, not the final {a.start_height:,} given")
        if tip is None or tip <= start:
            raise NotYet(f"the L1 tip {tip} is not past MAINNET_START_HEIGHT {start:,}")
        for line in out.splitlines():
            if line.startswith("ok  "):
                self.note(f"guard: {line[4:]}")
        return tip


# --- status ------------------------------------------------------------------------------------------------------

def cmd_status(args) -> dict:
    lay = instance.layout(os.environ.get("MUTIS_INSTANCE"))
    if not lay.name:
        raise SystemExit("l1-burn: MUTIS_INSTANCE names no instance")
    settings = wallet_settings()
    g = Grpc(args.grpc_port or settings["grpc_port"])
    proofs = Path(args.proofs_dir or f"{lay.drive_home}/.local/share/tari/mainnet/burn_proofs")
    jdir = Path(args.journal_dir or f"{lay.backups}/l1-burns")
    state = g.unary("GetState")
    bal = g.unary("GetBalance")
    burns, other = scan(g)
    journals = {p.stem: json.loads(p.read_text()) for p in sorted(jdir.glob("*.json"))} if jdir.is_dir() else {}
    for b in burns:
        b["proof_files"] = [f for f in proof_files(proofs, b["claim_key"]) if b["commitment"] in f]
    return {"outcome": "status", "version": first(g.unary("GetVersion"), 1, b"").decode(),
            "scanned_height": first(state, 1, 0), "validated": bool(first(state, 4, 0)),
            "online": first(unpb(first(state, 3, b"")), 1, 0) == ONLINE,
            "available_ut": first(bal, 1, 0), "incoming_ut": first(bal, 2, 0), "outgoing_ut": first(bal, 3, 0),
            "burns": burns, "other_outbound": other,
            "journal": {k: {f: v.get(f) for f in ("state", "tx_id", "commitment", "amount_ut", "claim_key", "intent_at",
                                                  "sent_at", "problems")} for k, v in journals.items()}}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("burn", "status"):
        s = sub.add_parser(name)
        s.add_argument("--grpc-port", type=int)
        s.add_argument("--proofs-dir")
        s.add_argument("--journal-dir")
        if name == "burn":
            s.add_argument("--account", required=True, choices=("service", "sponsor"))
            s.add_argument("--amount-xtm", required=True)
            s.add_argument("--start-height", type=int, default=0)
            s.add_argument("--claim-key")
            s.add_argument("--dry-run", action="store_true")
            s.add_argument("--drill-esmeralda", action="store_true")
            s.add_argument("--walletd-port", type=int)
            s.add_argument("--expect-version")
    args = p.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("l1-burn: run as root (the gRPC port is guarded; the journal is root's)")
    os.umask(0o077)
    if args.command == "burn" and not args.drill_esmeralda and args.start_height <= 0:
        raise SystemExit("l1-burn: --start-height must be the final MAINNET_START_HEIGHT")
    burn = None
    try:
        if args.command == "status":
            result, rc = cmd_status(args), 0
        else:
            burn = Burn(args)
            result = burn.run()
            rc = 0
    except NotYet as e:
        result, rc = {"outcome": "not_yet", "reason": str(e)}, 2
    except Refused as e:
        result, rc = {"outcome": "refused", "reason": str(e)}, 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        result, rc = {"outcome": "not_yet", "reason": f"{type(e).__name__}: {e}"}, 2
    if args.command == "burn":
        result.setdefault("account", args.account)
        record = {"at": now(), "dry_run": args.dry_run, "drill": args.drill_esmeralda, "rc": rc, **result,
                  "notes": burn.notes if burn else []}
        with contextlib.suppress(OSError):
            jdir = Path(args.journal_dir or f"{instance.layout(os.environ.get('MUTIS_INSTANCE')).backups}/l1-burns")
            jdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            with open(jdir / "runs.jsonl", "a") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
    with contextlib.suppress(BrokenPipeError):
        print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
