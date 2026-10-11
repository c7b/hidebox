#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Gate helper: one small stealth transfer from walletd (run as lcam on ultron, stdlib only).

  python3 -I walletd_send.py <account> <destination otl_esm_ address> <amount µT> [memo text]

Prints the transaction id, its status and fee, and the UTXO ids it created. Used only for the G1/G2
gate tests (test sends well under 100 tTARI in total); never changes walletd configuration.
"""
import json
import sys
import urllib.request

URL = "http://127.0.0.1:5100/json_rpc"
TARI = "resource_" + "01" * 32


def call(method, params, token=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=200) as r:
        out = json.load(r)
    if "error" in out:
        raise SystemExit(f"{method}: {out['error']}")
    return out["result"]


def main():
    account, dest, amount = sys.argv[1], sys.argv[2], int(sys.argv[3])
    memo = sys.argv[4] if len(sys.argv) > 4 else None
    if amount > 5_000_000:
        raise SystemExit("refusing: gate sends stay small")
    token = call("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]
    transfer = {"destination_address": dest, "blinded_output_amount": str(amount), "revealed_output_amount": "0",
                "output_memo": {"Message": memo} if memo else None, "pay_to": "StealthPublicKey",
                "attach_sender_address": False}
    req = {"owner_account": {"Name": account},
           "fee_params": {"input_selection": "PreferConfidential", "pay_fee_with_swap": None},
           "input_selection": "PreferConfidential", "resource_address": TARI, "transfers": [transfer],
           "max_fee": "30000", "dry_run": False}
    tx = call("accounts.stealth_transfer", req, token)["transaction_id"]
    res = call("transactions.wait_result", {"transaction_id": tx, "timeout_secs": 180}, token)
    ups = []
    accept = ((res.get("result") or {}).get("result") or {}).get("Accept") or {}
    for sub in accept.get("up_substates", []):
        if sub[0].startswith("utxo_"):
            ups.append(sub[0])
    print(json.dumps({"tx": tx, "status": res.get("status"), "final_fee": res.get("final_fee"),
                      "timed_out": res.get("timed_out"), "utxos": ups}))


if __name__ == "__main__":
    main()
