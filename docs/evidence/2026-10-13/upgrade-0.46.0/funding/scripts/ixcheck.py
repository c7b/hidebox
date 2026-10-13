# SPDX-License-Identifier: MIT
# Read a transaction's result from both Esmeralda indexers (public read routes, as data) and check that
# each output it created is a live substate on both. Run from the workstation: python3 -I ixcheck.py <tx id>…
import json, sys, urllib.request, urllib.error
IX = ["https://ootle-indexer-a.tari.com", "https://ootle-indexer-b.tari.com"]
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mutis"}), timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
for tx in sys.argv[1:]:
    for ix in IX:
        code, body = get(f"{ix}/transactions/{tx}/result")
        name = ix.split("//")[1].split(".")[0]
        if code != 200 or not isinstance(body, dict):
            print(f"{tx[:8]}… {name}: HTTP {code}"); continue
        res = body.get("result") or {}
        fin = res.get("Finalized") if isinstance(res, dict) else None
        if not fin:
            print(f"{tx[:8]}… {name}: {list(res)[:2] if isinstance(res, dict) else res}"); continue
        dec = fin.get("final_decision")
        exe = (fin.get("execution_result") or {}).get("finalize") or {}
        acc = (exe.get("result") or {}).get("Accept") or {}
        ups = [u[0] for u in acc.get("up_substates", []) if isinstance(u, list) and u and str(u[0]).startswith("utxo_")]
        fee = (exe.get("fee_receipt") or {}).get("total_fees_paid")
        live = []
        for u in ups:
            c2, s = get(f"{ix}/substates/{u}")
            live.append(f"{u[-8:]}:{c2}")
        print(f"{tx[:8]}… {name}: {dec}, fee {fee}, outputs {len(ups)} [{', '.join(live)}]")
