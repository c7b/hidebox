# SPDX-License-Identifier: MIT
# Summarise walletd state (read-only RPC) as drive: version, balances, transactions by status,
# the non-Accepted ones, and the sponsor's stealth outputs. Hashes cut to 8 hex digits.
import json, sys, urllib.request, collections
URL = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5100/json_rpc")
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
info = call("wallet.get_info", {})
print("wallet.get_info:", {k: info.get(k) for k in ("network", "version")})
accts = call("accounts.list", {"offset": 0, "limit": 100})["accounts"]
comp = {}
for e in sorted(accts, key=lambda a: a["account"]["name"]):
    n = e["account"]["name"]; comp[n] = e["account"]["component_address"]
    bal = call("accounts.get_balances", {"account": {"Name": n}, "refresh": False})["balances"]
    t = [b for b in bal if b.get("resource_address") == TARI]
    print(f"  {n:11s} " + ("; ".join(f"revealed {b.get('balance')}, confidential {b.get('confidential_balance')} µT" for b in t) or "no balances listed"))
txs = call("transactions.get_all", {"status": None, "component": None})["transactions"]
def tid(t):
    tx = t[0] if isinstance(t, list) else t
    return tx
rows = []
for t in txs:
    if isinstance(t, list):
        tx, fin, status, upd = (t + [None] * 4)[:4]
    else:
        tx, status, upd = t.get("transaction"), t.get("status"), t.get("last_update_time")
    rows.append((tx, status, upd, t))
c = collections.Counter(r[1] for r in rows)
print(f"transactions.get_all: {len(rows)}:", ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
if "-v" in sys.argv and rows: print("  row shape:", type(rows[0][3]).__name__, (list(rows[0][3].keys()) if isinstance(rows[0][3], dict) else len(rows[0][3])))
for tx, status, upd, raw in sorted(rows, key=lambda r: str(r[2])):
    if status not in ("Accepted",):
        i = raw.get("id") if isinstance(raw, dict) else None
        print(f"  {str(i)[:8]}…  {status:10s} {str(upd)[:19]}")
ut = call("stealth_utxos.list", {"resource_address": TARI, "account_address": comp.get("sponsor"), "filter_by_status": None})
us = ut.get("utxos", [])
c2 = collections.Counter((u.get("status"), u.get("is_on_chain")) for u in us)
print(f"sponsor stealth_utxos.list: {len(us)}:", ", ".join(f"{k[0]} (on chain {k[1]}) {v}" for k, v in sorted(c2.items(), key=str)))
for u in us:
    if u.get("status") != "Spent":
        a = u.get("address"); cm = a.get("id", "") if isinstance(a, dict) else str(a)
        print(f"  commitment {cm[:8]}…  {u.get('status')}  is_on_chain {u.get('is_on_chain')}  value {u.get('value')} µT")
if "-v" in sys.argv and us: print("  utxo keys:", sorted(us[0].keys()))
