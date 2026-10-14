# SPDX-License-Identifier: MIT
# Read-only walletd snapshot as drive: version, every account's TARI balances (walletd's database, no
# refresh), transactions by status, and each account's stealth outputs grouped by status with their sum.
# Hashes cut to 8 hex digits. No call here sends or changes anything.
import json, sys, urllib.request, collections
URL = "http://127.0.0.1:5100/json_rpc"
TARI = "resource_" + "01" * 32
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
refresh = "--refresh" in sys.argv
info = call("wallet.get_info", {})
print("wallet.get_info:", {k: info.get(k) for k in ("network", "version")}, "| refresh" if refresh else "")
accts = call("accounts.list", {"offset": 0, "limit": 100})["accounts"]
for e in sorted(accts, key=lambda a: a["account"]["name"]):
    n = e["account"]["name"]; comp = e["account"]["component_address"]
    bal = call("accounts.get_balances", {"account": {"Name": n}, "refresh": refresh})["balances"]
    t = [b for b in bal if b.get("resource_address") == TARI]
    print(f"  {n:11s} " + ("; ".join(f"revealed {b.get('balance')}, confidential {b.get('confidential_balance')} µT" for b in t) or "no balances listed"))
    us = call("stealth_utxos.list", {"resource_address": TARI, "account_address": comp, "filter_by_status": None}).get("utxos", [])
    g = collections.defaultdict(lambda: [0, 0])
    for u in us:
        k = (u.get("status"), u.get("is_on_chain")); g[k][0] += 1; g[k][1] += int(u.get("value") or 0)
    print("     stealth outputs:", ", ".join(f"{s} (on chain {o}) {c} = {v} µT" for (s, o), (c, v) in sorted(g.items(), key=str)) or "none")
    if "-v" in sys.argv:
        for u in us:
            if u.get("status") != "Spent":
                a = u.get("address"); cm = a.get("id", "") if isinstance(a, dict) else str(a)
                print(f"       {cm[:8]}…  {u.get('status')}  on_chain {u.get('is_on_chain')}  {u.get('value')} µT")
txs = call("transactions.get_all", {"status": None, "component": None})["transactions"]
c = collections.Counter((t.get("status") if isinstance(t, dict) else t[2]) for t in txs)
print(f"transactions.get_all: {len(txs)}:", ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=str)))
