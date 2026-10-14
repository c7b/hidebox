# SPDX-License-Identifier: MIT
"""A fake Ootle chain and indexer for tests and --dev mode. NOT cryptography.

Outputs carry their plaintext openly (view_pk ‖ value ‖ memo), keys are hashes, and a "commitment"
is a hash of (value, nonce). This keeps the shapes and failure modes of the real indexer API
(gate G3 framing) so the worker, the API proxy and payment verification can be tested offline.
"""
import json
import re
import secrets
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import codec, ootle_addr

TARI_HEX = "01" * 32
FAKE_WASM_SHA256 = codec.sha256(b"mutis fake sidecar").hex()


def fake_pk(sk: bytes) -> bytes:
    return codec.sha256(b"mutis-fake-pk", sk)


def fake_keys() -> dict:
    owner_sk, view_sk = secrets.token_bytes(32), secrets.token_bytes(32)
    owner_pk, view_pk = fake_pk(owner_sk), fake_pk(view_sk)
    return {"owner_sk": owner_sk.hex(), "view_sk": view_sk.hex(), "owner_pk": owner_pk.hex(), "view_pk": view_pk.hex(),
            "address": ootle_addr.encode(ootle_addr.TESTNET_HRP, owner_pk + view_pk)}


def fake_commitment(value: int, nonce: bytes) -> bytes:
    return codec.sha256(b"mutis-fake-commitment", struct.pack(">Q", value), nonce)


def fake_one_time_key(owner_pk: bytes, nonce: bytes) -> bytes:
    """The fake's stand-in for a stealth output's one-time public key (c + k)·G: only the destination's
    owner key derives it from the nonce (`oneTimeKey` in the fake sidecar)."""
    return codec.sha256(b"mutis-fake-otk", owner_pk, nonce)


def seal_output(view_pk: bytes, value: int, memo) -> bytes:
    return view_pk + struct.pack(">Q", value) + json.dumps(memo).encode()


def open_output(view_sk: bytes, commitment: bytes, nonce: bytes, enc: bytes):
    """(value, memo) when `view_sk` owns the output and the value opens the commitment; else None."""
    if len(enc) < 40 or enc[:32] != fake_pk(view_sk):
        return None
    value = struct.unpack(">Q", enc[32:40])[0]
    if fake_commitment(value, nonce) != commitment:
        return None              # the fake's stand-in for unblindOutput's commitment check
    return value, json.loads(enc[40:])


class FakeChain:
    def __init__(self, epoch: int = 12000):
        self.lock = threading.Lock()
        self.epoch = epoch
        self.outputs: list[dict] = []
        self.versions: dict[int, int] = {}
        self.receipts: dict[str, dict] = {}
        self.balances: dict[str, int] = {"sponsor": 8_900_000_000, "service": 20_000_000, "operator": 50_000_000}
        self.addresses = {name: fake_keys()["address"] for name in self.balances}
        self.transfers: list[dict] = []
        self.seal_logs: dict[str, list[int]] = {}      # component → leaf counts appended

    def add_output(self, destination: str, value: int, memo, promise: int = 0, spender: str | None = None,
                   auth: dict | None = None) -> str:
        """An output to `destination`. `spender` (another address) keeps the one-time key for its own owner
        key while the payload still opens with the destination's view key: the R1 forgery a view key can't
        see. `auth` replaces the spend rule outright (another variant than a key)."""
        owner_pk, view_pk, pay_ref = ootle_addr.parse_testnet(destination)
        if spender is not None:
            owner_pk = ootle_addr.parse_testnet(spender)[0]
        if memo is None and pay_ref:
            memo = {"PayRefAndBytes": (bytes([len(pay_ref)]) + pay_ref).hex()}
        nonce = secrets.token_bytes(32)
        commitment = fake_commitment(value, nonce)
        shard = 1 + commitment[0]
        with self.lock:
            self.versions[shard] = self.versions.get(shard, 0) + 1
            self.outputs.append({"commitment": commitment.hex(), "nonce": nonce.hex(),
                                 "enc": seal_output(view_pk, value, memo).hex(), "tag": int.from_bytes(nonce[:4], "big"),
                                 "promise": promise, "shard": shard, "version": self.versions[shard], "spent": False,
                                 "auth": auth or {"Key": fake_one_time_key(owner_pk, nonce).hex()}})
        return f"utxo_{TARI_HEX}_{commitment.hex()}"

    def transfer(self, account: str, destination: str, value: int, memo, max_fee: int, promise: int = 0) -> str:
        with self.lock:
            if self.balances.get(account, 0) < value + max_fee:
                raise ValueError("insufficient funds")
            self.balances[account] -= value + max_fee
        out = self.add_output(destination, value, memo, promise)
        change = self.add_output(self.addresses[account], 0, None)
        tx_id = secrets.token_hex(32)
        self.receipts[tx_id] = {"outcome": "Commit", "epoch": self.epoch,
                                "diff_summary": {"upped": [{"substate_id": out}, {"substate_id": change}],
                                                 "downed": [{"substate_id": f"utxo_{TARI_HEX}_{secrets.token_hex(32)}"}]},
                                "fee_receipt": {"total_fees_paid": max_fee}}
        self.transfers.append({"tx_id": tx_id, "account": account, "destination": destination, "value": value,
                               "memo": memo, "outputs": [out, change]})
        return tx_id

    def manifest_call(self, manifest: str, variables: dict) -> str:
        """A SealLog call. `append_root` follows template 2.0.0: the count must be a multiple of 64 and
        grow, and the append emits a `SealLog.root` event with the checkpoint's index."""
        tx_id = secrets.token_hex(32)
        outcome, events = "Commit", []
        append = re.search(r'append_root\(hex_bytes!\("([0-9a-f]{64})"\), (\d+)u64\)', manifest)
        if append:
            log, root, count = variables["log"], append.group(1), int(append.group(2))
            with self.lock:
                counts = self.seal_logs.setdefault(log, [])
                if count % 64 or count <= (counts[-1] if counts else 0):
                    outcome = "Reject"
                else:
                    counts.append(count)
                    events.append({"topic": "SealLog.root", "substate_id": log, "template_address": "00" * 32,
                                   "payload": {"index": str(len(counts) - 1), "root": root, "leaf_count": str(count),
                                               "epoch": str(self.epoch)}})
        self.receipts[tx_id] = {"outcome": outcome, "epoch": self.epoch, "diff_summary": {"upped": [], "downed": []},
                                "fee_receipt": {"total_fees_paid": 1837}, "events": events}
        return tx_id

    def stream(self, cursors: dict[int, int], limit: int) -> bytes:
        lines = []
        with self.lock:
            for shard in sorted(cursors):
                updates = sorted((o for o in self.outputs if o["shard"] == shard and o["version"] > cursors[shard]),
                                 key=lambda o: o["version"])
                if not updates:
                    continue
                page, more = updates[:limit], len(updates) > limit
                top = page[-1]["version"]
                for i, o in enumerate(page):
                    update = {"Unspent": {"tag": o["tag"], "public_nonce": list(bytes.fromhex(o["nonce"]))}}
                    lines.append({"sos": {"shard": shard, "max_state_version": top, "num_updates": len(page),
                                          "has_more": more} if i == 0 else None,
                                  "update": update, "eos": {"max_state_version": top} if i == len(page) - 1 else None})
        return b"".join(json.dumps(line).encode() + b"\n" for line in lines)

    @staticmethod
    def _output(o: dict) -> dict:
        """The indexer's `{"output": {...}, "auth", "tag"}` shape (gate G3)."""
        return {"output": {"public_nonce": o["nonce"], "encrypted_data": o["enc"],
                           "minimum_value_promise": o["promise"], "viewable_balance": None},
                "auth": o["auth"], "tag": o["tag"]}

    def fetch(self, pairs: list) -> list:
        wanted = {(int(t), n) for t, n in pairs}
        with self.lock:
            return [[o["commitment"], {"output": self._output(o), "is_frozen": False}]
                    for o in self.outputs if (o["tag"], o["nonce"]) in wanted and not o["spent"]]

    def substate(self, substate_id: str) -> dict | None:
        with self.lock:
            for o in self.outputs:
                if substate_id == f"utxo_{TARI_HEX}_{o['commitment']}" and not o["spent"]:
                    return {"version": 0, "verified": True, "proof": {"anchor": {"epoch": self.epoch}},
                            "substate": {"Utxo": {"output": self._output(o), "is_frozen": False}}}
        return None


def result_of(receipt: dict) -> dict:
    """GET /transactions/{id}/result as tari_indexer 0.45 answers it, from a receipt."""
    diff = receipt["diff_summary"]
    accept = {"up_substates": [[u["substate_id"], {}] for u in diff["upped"]],
              "down_substates": [[d["substate_id"], 0] for d in diff["downed"]]}
    return {"result": {"Finalized": {"final_decision": receipt["outcome"], "execution_result": {
        "execute_epoch": receipt["epoch"],
        "finalize": {"result": {"Accept": accept}, "fee_receipt": receipt["fee_receipt"]}}}}}


class _IndexerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    chain: FakeChain

    def log_message(self, *args):
        pass

    def _send(self, status: int, obj=None, raw: bytes | None = None, ctype: str = "application/json") -> None:
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        chain, path = self.server.chain, self.path.split("?")[0]
        if path == "/epoch-manager/stats":
            return self._send(200, {"current_epoch": chain.epoch, "consensus_epoch": chain.epoch})
        if path == "/network":
            return self._send(200, {"network": "esmeralda", "network_byte": 38, "epoch": chain.epoch})
        if path.startswith("/substates/"):
            found = chain.substate(path.removeprefix("/substates/"))
            return self._send(200, found) if found else self._send(404, {"error": "not found"})
        if path.startswith("/transaction-receipts/"):
            receipt = chain.receipts.get(path.removeprefix("/transaction-receipts/"))
            return self._send(200, {"receipt": receipt}) if receipt and self.server.receipts_ready \
                else self._send(404, {"error": "not found"})
        if path.startswith("/transactions/") and path.endswith("/result"):
            receipt = chain.receipts.get(path.split("/")[2])
            return self._send(200, result_of(receipt)) if receipt else self._send(404, {"error": "not found"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        chain = self.server.chain
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/utxos/stream":
            cursors = {int(s): int(v) for s, v in body["shard_state_versions"]}
            return self._send(200, raw=chain.stream(cursors, int(body["per_shard_limit"])),
                              ctype="application/x-ndjson")
        if self.path == "/utxos/fetch":
            return self._send(200, {"utxos": chain.fetch(body["tag_and_nonce_pairs"])})
        if self.path in ("/transactions", "/transactions/dry-run"):
            return self._send(200, {"transaction_id": secrets.token_hex(32)})
        return self._send(404, {"error": "not found"})


class FakeIndexer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, chain: FakeChain):
        self.chain = chain
        self.receipts_ready = True        # False: like a real indexer in the minutes before it files a receipt
        super().__init__(("127.0.0.1", 0), _IndexerHandler)
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"
