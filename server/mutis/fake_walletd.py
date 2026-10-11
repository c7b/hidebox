# SPDX-License-Identifier: MIT
"""A fake tari_ootle_walletd JSON-RPC endpoint over FakeChain, for tests and --dev mode.

It answers the calls mutis makes with the shapes walletd 0.45.0 returns (03-ootle-integration §4.4).
`fail_next` makes the next N calls fail, to exercise retries.
"""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ootle_addr
from .fake_chain import TARI_HEX, FakeChain


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        server: FakeWalletd = self.server
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        with server.lock:
            server.calls.append(req["method"])
            failing = server.fail_next > 0
            server.fail_next -= failing
        try:
            if failing:
                raise ValueError("injected failure")
            result = server.dispatch(req["method"], req.get("params") or {})
            reply = {"jsonrpc": "2.0", "id": req["id"], "result": result}
        except (KeyError, ValueError) as e:
            reply = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -1, "message": type(e).__name__}}
        body = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeWalletd(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, chain: FakeChain):
        self.chain = chain
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.fail_next = 0
        self.wait_outcome = "commit"          # or "timeout" / "reject"
        self.components = {name: "component_" + secrets.token_hex(32) for name in chain.balances}
        super().__init__(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/json_rpc"

    def _name(self, account) -> str:
        name = account["Name"] if isinstance(account, dict) else account
        if name not in self.chain.balances:
            raise KeyError(name)
        return name

    def dispatch(self, method: str, p: dict):
        chain = self.chain
        if method == "auth.request":
            return {"token": "eyJ" + secrets.token_hex(16)}
        if method == "wallet.get_info":
            return {"network": "esmeralda", "network_byte": 38, "version": "0.45.0"}
        if method == "accounts.get":
            name = self._name(p["name_or_address"])
            return {"account": {"name": name, "component_address": self.components[name]},
                    "address": chain.addresses[name]}
        if method == "accounts.get_balances":
            name = self._name(p["account"])
            return {"balances": [{"resource_address": "resource_" + TARI_HEX, "balance": "0",
                                  "confidential_balance": str(chain.balances[name])}]}
        if method == "accounts.stealth_transfer":
            t = p["transfers"][0]
            memo = t.get("output_memo")
            tx_id = chain.transfer(self._name(p["owner_account"]), t["destination_address"],
                                   int(t["blinded_output_amount"]), memo, int(p["max_fee"]))
            return {"transaction_id": tx_id}
        if method == "transactions.submit_manifest":
            return {"transaction_id": chain.manifest_call()}
        if method == "transactions.wait_result":
            receipt = chain.receipts[p["transaction_id"]]
            if self.wait_outcome == "timeout":
                return {"transaction_id": p["transaction_id"], "result": None, "timed_out": True}
            if self.wait_outcome == "reject":
                return {"transaction_id": p["transaction_id"], "timed_out": False,
                        "result": {"result": {"Reject": "fake rejection"}}}
            ups = [[u["substate_id"], {}] for u in receipt["diff_summary"]["upped"]]
            return {"transaction_id": p["transaction_id"], "timed_out": False, "status": "Accepted",
                    "result": {"result": {"Accept": {"up_substates": ups}}}, "final_fee": "30000"}
        if method == "stealth_utxos.list":
            return {"utxos": self.received(p["account_address"])}
        raise KeyError(method)

    def received(self, component: str) -> list[dict]:
        """What walletd's list would show for an account: outputs paid to its address, decrypted."""
        name = next(n for n, c in self.components.items() if c == component)
        base = ootle_addr.parse_testnet(self.chain.addresses[name])[:2]
        out = []
        for t in self.chain.transfers:
            if ootle_addr.parse_testnet(t["destination"])[:2] == base:
                commitment = t["outputs"][0].rsplit("_", 1)[1]
                memo = t["memo"]
                if memo is None:
                    ref = ootle_addr.parse_testnet(t["destination"])[2]
                    memo = {"PayRefAndBytes": (bytes([len(ref)]) + ref).hex()} if ref else None
                out.append({"address": {"id": commitment, "resource_address": "resource_" + TARI_HEX},
                            "value": str(t["value"]), "status": "Unspent", "memo": memo, "is_on_chain": True,
                            "is_burnt": False, "is_frozen": False, "sender_address": None})
        return out
