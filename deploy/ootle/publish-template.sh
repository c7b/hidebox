#!/bin/bash
# SPDX-License-Identifier: MIT
# Publish the SealLog template and create its log on Esmeralda (spec §11, D-12). Runs on the jarvis
# box; walletd calls run on ultron as drive.
#
# Gate G5 failed on walletd 0.45: transactions.submit_manifest signs with the wallet's default key
# (the `service` account) whatever account the manifest pays from, so a log created "from operator"
# is refused (AccessDenied on operator's pay_fee). The log is therefore created, owned and fed by
# `service`, as the spec's fallback says; the privacy ledger must say so.
#   deploy/ootle/publish-template.sh check                  hash check and dry runs (no funds move)
#   deploy/ootle/publish-template.sh publish                publish; prints the template address
#   deploy/ootle/publish-template.sh instantiate <template> create the log; prints its component address
# Then put the component in /etc/mutis/mutis.toml (ootle.seallog_component) and, when the server's
# checkpoints should start, features.seallog = true. setup-accounts.md §4 records what was done.
set -euo pipefail

host=${MUTIS_SSH_HOST:-ultron}
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
wasm=$repo/template/dist/seal_log.wasm
control=$(mktemp -d)
trap 'rm -rf "$control"' EXIT
remote() { ssh -o ControlMaster=auto -o "ControlPath=$control/cm" -o ControlPersist=5m -o ClearAllForwardings=yes "$host" "$@"; }
rpc() { remote "cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py $*"; }
field() { python3 -I -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
die() { echo "publish-template: $*" >&2; exit 1; }

expected=$(awk '$2 == "seal_log.wasm" {print $1}' "$repo/template/dist/SHA256SUMS")
[ "$(sha256sum "$wasm" | cut -d' ' -f1)" = "$expected" ] || die "seal_log.wasm does not match template/dist/SHA256SUMS"
account=service
owner=$(rpc call accounts.list "'{\"offset\":0,\"limit\":100}'" | python3 -I -c '
import json, sys
print(next(a["account"]["component_address"] for a in json.load(sys.stdin)["accounts"] if a["account"]["name"] == sys.argv[1]))' "$account")

publish_params() {  # $1 = true for a dry run
  python3 -I -c 'import base64, json, sys
print(json.dumps({"binary": base64.b64encode(open(sys.argv[1], "rb").read()).decode(), "fee_account": {"Name": sys.argv[3]},
                  "max_fee": "2000000", "detect_inputs": True, "dry_run": sys.argv[2] == "true"}))' "$wasm" "$1" "$account"
}

manifest_params() {  # $1 = template hex, $2 = true for a dry run
  python3 -I -c 'import json, sys
template, owner, dry = sys.argv[1:]
manifest = (f"use template_{template} as SealLog;\n"
            "fn fee_main() { let account = var![\"account\"]; account.pay_fee(1000000); }\n"
            "fn main() { let alloc = new_component_addr!(); SealLog::new(alloc); }\n")
print(json.dumps({"manifest": manifest, "variables": {"account": owner}, "max_fee": "1000000", "dry_run": dry == "true"}))' \
    "$1" "$owner" "$2"
}

wait_for() {  # prints the finalized result of transaction $1
  rpc call transactions.wait_result "'{\"transaction_id\":\"$1\",\"timeout_secs\":240}'"
}

case ${1:-} in
  check)
    echo "seal_log.wasm sha256 ok; $account = $owner"
    tx=$(publish_params true | rpc call transactions.publish_template - | field transaction_id)
    echo "publish dry run: $(rpc call transactions.get "'{\"transaction_id\":\"$tx\"}'" | python3 -I -c '
import json, sys; d = json.load(sys.stdin); print(d["status"], "fee", d["final_fee"])')"
    ;;
  publish)
    tx=$(publish_params false | rpc call transactions.publish_template - | field transaction_id)
    wait_for "$tx" | python3 -I -c 'import json, re, sys
result = json.load(sys.stdin)
print("status", result.get("status"), "fee", result.get("final_fee"))
print("template", sorted(set(re.findall(r"template_[0-9a-f]{64}", json.dumps(result))))[0])'
    echo "tx $tx"
    ;;
  instantiate)
    template=${2#template_}
    [[ $template =~ ^[0-9a-f]{64}$ ]] || die "give the template address"
    manifest_params "$template" true | rpc call transactions.submit_manifest - >/dev/null
    tx=$(manifest_params "$template" false | rpc call transactions.submit_manifest - | field transaction_id)
    wait_for "$tx" | python3 -I -c 'import json, re, sys
result, owner = json.load(sys.stdin), sys.argv[1]
print("status", result.get("status"), "fee", result.get("final_fee"))
print("component", sorted(set(re.findall(r"component_[0-9a-f]{64}", json.dumps(result))) - {owner}))' "$owner"
    echo "tx $tx"
    ;;
  *) die "usage: publish-template.sh check | publish | instantiate <template>" ;;
esac
