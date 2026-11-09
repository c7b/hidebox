# SPDX-License-Identifier: MIT
# Summarise walletd (read-only JSON-RPC, as root on the loopback port): version, validator set, every account's
# TARI balances from walletd's own store, and the Pending transactions. Hashes cut to 8 hex digits.
# Usage: python3 -I wsum.py [http://127.0.0.1:<port>/json_rpc]
import json
import sys
import urllib.request

URL = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5100/json_rpc")
TARI = "resource_" + "01" * 32
token = None


def call(method, params):
    req = urllib.request.Request(URL, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=120) as res:
        answer = json.load(res)
    if "error" in answer:
        raise RuntimeError(f"{method}: {answer['error'].get('message')}")
    return answer["result"]


token = call("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]
info = call("wallet.get_info", {})
print("wallet.get_info:", {k: info.get(k) for k in ("network", "version")})
try:
    vs = call("validator_set.get_status", {})
    t = vs.get("trusted") or {}
    print("validator_set.get_status: indexer_trust", vs.get("indexer_trust"), "| trusted epoch", t.get("epoch"),
          "anchor epoch", t.get("anchor_epoch"), "| walk_failing_since", t.get("walk_failing_since"))
except RuntimeError as e:
    print("validator_set.get_status:", e)
for entry in sorted(call("accounts.list", {"offset": 0, "limit": 100})["accounts"], key=lambda a: a["account"]["name"]):
    name = entry["account"]["name"]
    tari = [b for b in call("accounts.get_balances", {"account": {"Name": name}, "refresh": False})["balances"]
            if b.get("resource_address") == TARI]
    print(f"  {name:11s} " + ("; ".join(f"revealed {b.get('balance')}, confidential {b.get('confidential_balance')} µT"
                                        for b in tari) or "no TARI balance listed"))
try:
    pending = call("transactions.list", {"status": "Pending", "account": None})
    rows = pending.get("transactions", pending) if isinstance(pending, dict) else pending
    print(f"transactions.list Pending: {len(rows)}")
except RuntimeError as e:
    print("transactions.list:", e)
