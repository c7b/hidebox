#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""walletd JSON-RPC from the command line, as `drive` (the only user the port guard lets through
besides root and lcam). Python stdlib only; the JWT lives in memory, nothing is written to disk.

  walletd-rpc.py balances [--refresh]          every account and its balances, as JSON
  walletd-rpc.py call METHOD '{json params}'    one call; prints the result ("-" reads the params from
                                                stdin: a template binary is too long for one argument)

`balances` is run before and after any change to how walletd runs (the move to systemd, the upgrade
drill, a reset) to show that no funds moved: without --refresh it reads walletd's own database, with
it walletd asks the indexer. Every `call` used by the playbooks is written out in deploy/ootle/*.md.
"""
import argparse
import json
import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:5100/json_rpc"


class Rpc:
    def __init__(self, url: str):
        self.url = url
        self.token = None
        self.token = self.call("auth.request", {"permissions": ["Admin"], "credentials": "None"})["token"]

    def call(self, method: str, params: dict):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        with urllib.request.urlopen(req, timeout=120) as res:
            answer = json.load(res)
        if "error" in answer:
            raise SystemExit(f"{method}: {answer['error'].get('message', 'error')}")
        return answer["result"]


def snapshot(rpc: Rpc, refresh: bool) -> dict:
    info = rpc.call("wallet.get_info", {})
    accounts = rpc.call("accounts.list", {"offset": 0, "limit": 100})["accounts"]
    out = {"network": info.get("network"), "version": info.get("version"), "accounts": []}
    for entry in sorted(accounts, key=lambda a: a["account"]["name"]):
        name = entry["account"]["name"]
        balances = rpc.call("accounts.get_balances", {"account": {"Name": name}, "refresh": refresh})["balances"]
        out["accounts"].append({
            "name": name,
            "component": entry["account"]["component_address"],
            "balances": sorted(({k: b.get(k) for k in ("resource_address", "balance", "confidential_balance")}
                                for b in balances), key=lambda b: b["resource_address"]),
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="walletd JSON-RPC")
    p.add_argument("--url", default=DEFAULT_URL)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("balances", help="every account with its balances")
    b.add_argument("--refresh", action="store_true", help="ask walletd to re-read balances from the indexer")
    c = sub.add_parser("call", help="one JSON-RPC call")
    c.add_argument("method")
    c.add_argument("params", nargs="?", default="{}", help="JSON, or - to read it from stdin")
    args = p.parse_args()
    rpc = Rpc(args.url)
    if args.command == "balances":
        result = snapshot(rpc, args.refresh)
    else:
        result = rpc.call(args.method, json.loads(sys.stdin.read() if args.params == "-" else args.params))
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
