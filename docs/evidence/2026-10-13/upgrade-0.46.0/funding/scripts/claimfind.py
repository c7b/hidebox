# SPDX-License-Identifier: MIT
# Read-only, as drive: find walletd's claim transaction for the sponsor burn (the transactions whose body
# mentions a ClaimBurn instruction, newest first) and the sponsor's stealth outputs after it.
import json, urllib.request
URL = "http://127.0.0.1:5100/json_rpc"; TARI = "resource_" + "01" * 32
tok = None
def call(m, p):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode()
    r = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    if tok: r.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(r, timeout=120) as res:
        a = json.load(res)
    if "error" in a: raise SystemExit(f"{m}: {a['error'].get('message')}")
    return a["result"]
tok = call("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]
txs = call("transactions.get_all", {"status": None, "component": None})["transactions"]
claims = [t for t in txs if "ClaimBurn" in json.dumps(t.get("transaction"))]
for t in sorted(claims, key=lambda t: str(t.get("last_update_time")))[-3:]:
    print("claim", t.get("id"), t.get("status"), str(t.get("last_update_time"))[:19], "final_fee", t.get("final_fee"))
