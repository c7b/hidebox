# SPDX-License-Identifier: MIT
# Step 1a, the quick relief: one stealth transfer from `service` to `sponsor` (our own accounts), in the
# shape of deploy/ootle/setup-accounts.md §2. `dry` sends it with "dry_run": true and reads the fee with
# transactions.get; `send` repeats it for real and waits for the result. Run as drive on the server.
# The parameters name only our own accounts; addresses are printed cut.
import json, sys, urllib.request
URL = "http://127.0.0.1:5100/json_rpc"; TARI = "resource_" + "01" * 32
AMOUNT_UT, MAX_FEE_UT = 61_500_000, 30_000
tok = None
def call(m, p):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode()
    r = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    if tok: r.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(r, timeout=200) as res:
        a = json.load(res)
    if "error" in a: raise SystemExit(f"{m}: {a['error'].get('message')}")
    return a["result"]
tok = call("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]
mode = sys.argv[1]
dest = call("accounts.get", {"name_or_address": "sponsor"})["address"]
print("sponsor address", dest[:12] + "…" + dest[-6:])
params = {"owner_account": {"Name": "service"},
          "fee_params": {"input_selection": "PreferConfidential", "pay_fee_with_swap": None},
          "input_selection": "PreferConfidential", "resource_address": TARI,
          "transfers": [{"destination_address": dest, "blinded_output_amount": str(AMOUNT_UT),
                         "revealed_output_amount": "0", "output_memo": {"Message": "mutis sponsor refill"},
                         "pay_to": "StealthPublicKey", "attach_sender_address": False}],
          "max_fee": str(MAX_FEE_UT), "dry_run": mode == "dry"}
res = call("accounts.stealth_transfer", params)
tx = res["transaction_id"]
print("transaction_id", tx, "| dry_run" if mode == "dry" else "")
if mode == "dry":
    t = call("transactions.get", {"transaction_id": tx})
    print("dry run: status", t.get("status"), "final_fee", t.get("final_fee"),
          "| reject", (t.get("result") or {}).get("result", {}).get("Reject") if isinstance(t.get("result"), dict) else None)
else:
    w = call("transactions.wait_result", {"transaction_id": tx, "timeout_secs": 180})
    fin = (w.get("result") or {}).get("result") or {}
    print("wait_result: status", w.get("status"), "final_fee", w.get("final_fee"), "timed_out", w.get("timed_out"),
          "| decision", "Accept" if "Accept" in fin else ("Reject" if "Reject" in fin else list(fin)[:3]))
    if "Accept" in fin:
        ups = [u[0] for u in fin["Accept"].get("up_substates", []) if isinstance(u, list) and u and str(u[0]).startswith("utxo_")]
        print("new outputs", [u[:16] + "…" + u[-8:] for u in ups])
