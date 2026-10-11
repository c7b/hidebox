#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch the stealth outputs of finalized Esmeralda transactions from the public indexer (stdlib).

  python3 -I fetch_outputs.py <tx_id> [...] > esmeralda-outputs.json

Writes {tx_id: {"max_epoch": n, "outputs": [{"id", "nonce", "enc"}]}} from each transaction's stealth
statement, so the vectors keep working after the outputs are spent or the testnet is reset.
"""
import json
import sys
import urllib.request

INDEXER = "https://ootle-indexer-b.tari.com"
RESOURCE = "01" * 32


def get(path):
    req = urllib.request.Request(f"{INDEXER}/{path}", headers={"User-Agent": "mutis-vectors/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    out = {}
    for tx in sys.argv[1:]:
        record = get(f"transactions/{tx}")["transaction"]
        body = record["transaction"]["V1"]["body"]["transaction"]
        if (record.get("summary") or {}).get("outcome") != "Commit":
            assert get(f"transactions/{tx}/result")["result"]["Finalized"]["final_decision"] == "Commit", tx
        outputs = []
        for ins in body["fee_instructions"] + body["instructions"]:
            st = ins.get("StealthTransfer", {}).get("statement")
            for o in (st or {}).get("outputs_statement", {}).get("outputs", []):
                o = o["output"]
                outputs.append({"id": f"utxo_{RESOURCE}_{o['commitment']}", "nonce": o["sender_public_nonce"],
                                "enc": o["encrypted_data"]})
        out[tx] = {"max_epoch": body["max_epoch"], "outputs": outputs}
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
