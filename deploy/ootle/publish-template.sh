#!/bin/bash
# SPDX-License-Identifier: MIT
# Publish the SealLog template and create its log on Esmeralda (spec §11, D-12). Runs on the
# workstation; walletd calls run on the server as drive.
#
# The publish carries the exact bytes of template/dist/seal_log.wasm. walletd's
# transactions.publish_template runs wasm-opt first and stores other bytes, which no source can be
# tied to; so this builds the transaction itself (one PublishTemplate instruction, the binary as the
# transaction's blob, the fee paid from the account) and hands it to transactions.submit_dry_run,
# then transactions.submit, sealed by the `service` account's key, which becomes the template's
# author (its dry run is accepted, 755,531 µT, and the chain's copy is byte-identical). walletd 0.45
# keeps that dry run as a "New" transaction and from then on logs "Error resubmitting new
# transactions: ... Dry run transaction mismatch" every 5 s; harmless (nothing is sent), and the
# wallet's store is left alone (docs/review/fix-log.md).
#
# Gate G5 failed on walletd 0.45: transactions.submit_manifest signs with that same default key
# whatever account the manifest pays from, so the log is created, owned and fed by `service`, as the
# spec's fallback says; the privacy ledger says so.
#   deploy/ootle/publish-template.sh check                  hash check, predicted address, dry run (no funds move)
#   deploy/ootle/publish-template.sh publish                publish; prints the template address, then
#                                                           checks the chain holds dist/seal_log.wasm byte for byte
#   deploy/ootle/publish-template.sh instantiate <template> create the log; prints its component address
# Then put the component in /etc/mutis/mutis.toml (ootle.seallog_component) and, when the server's
# checkpoints should start, features.seallog = true. setup-accounts.md §4 records what was done.
#
# check and publish take --wasm PATH after the command: template/dist-v2/seal_log.wasm, the V2 build that Ootle 0.50
# loads (upgrade-0.50.md §9); the file must match the SHA256SUMS beside it. With none, template/dist/ as before.
# (The same option as lane launch/mainnet's, whose version also takes an instance, a network and an account.)
set -euo pipefail

host=${MUTIS_SSH_HOST:-hidebox}
indexer=https://ootle-indexer-b.tari.com
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
wasm=$repo/template/dist/seal_log.wasm
command=${1:-}
[ $# -gt 0 ] && shift
template_arg=
case $command in instantiate) template_arg=${1:-}; [ $# -gt 0 ] && shift ;; esac
while [ $# -gt 0 ]; do
  case $1 in
    --wasm) [ $# -ge 2 ] || { echo "publish-template: --wasm needs a path" >&2; exit 2; }
            wasm=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift ;;
    *) echo "publish-template: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
control=$(mktemp -d)
# set -e holds in the trap too: without `|| true`, an exit before the first ssh (no master to stop) skipped the rm.
trap 'ssh -o "ControlPath=$control/cm" -O exit "$host" 2>/dev/null || true; rm -rf "$control"' EXIT
remote() { ssh -o ControlMaster=auto -o "ControlPath=$control/cm" -o ControlPersist=5m -o ClearAllForwardings=yes "$host" "$@"; }
rpc() { remote "cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py $*"; }
field() { python3 -I -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
die() { echo "publish-template: $*" >&2; exit 1; }

expected=$(awk '$2 == "seal_log.wasm" {print $1}' "$(dirname "$wasm")/SHA256SUMS")
[ "$(sha256sum "$wasm" | cut -d' ' -f1)" = "$expected" ] || die "$wasm does not match the SHA256SUMS beside it"
account=service
read -r owner author key_id < <(rpc call accounts.list "'{\"offset\":0,\"limit\":100}'" | python3 -I -c '
import json, sys
a = next(e["account"] for e in json.load(sys.stdin)["accounts"] if e["account"]["name"] == sys.argv[1])
print(a["component_address"], a["owner_public_key"], json.dumps(a["owner_key_id"], separators=(",", ":")))' "$account")
[ -n "${key_id:-}" ] || die "walletd has no account named $account"

publish_params() {  # $1 = true for a dry run. An unsigned transaction, sealed by walletd with the account's key.
  python3 -I - "$wasm" "$owner" "$key_id" "$1" "$indexer" <<'PY'
import base64, json, secrets, sys, urllib.request
wasm, owner, key_id, dry, indexer = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4] == "true", sys.argv[5]
MAX_FEE_UT = 3_000_000          # the dry run says what it costs (106,770 bytes: 8 KiB over the allowance)
ESMERALDA = 38                  # the network byte (/api/v1/config network_byte)
req = urllib.request.Request(indexer + "/epoch-manager/stats", headers={"User-Agent": "mutis"})
with urllib.request.urlopen(req, timeout=30) as res:
    epoch = json.load(res)["current_epoch"]
fee = b"\x1a" + MAX_FEE_UT.to_bytes(4, "big")   # CBOR unsigned integer: the argument of pay_fee
transaction = {"V1": {
    "network": ESMERALDA,
    "fee_instructions": [{"CallMethod": {"call": {"Address": owner}, "method": "pay_fee",
                                         "args": [{"Literal": fee.hex()}]}}],
    "instructions": [{"PublishTemplate": {"binary": 0, "metadata_hash": None}}],
    # Ootle 0.48+: the seal signer (the account's key) is the main signer, so it authors the template
    "inputs": [], "min_epoch": None, "max_epoch": epoch + 2, "main_signer": "SealSigner", "dry_run": dry,
    "blobs": [base64.b64encode(open(wasm, "rb").read()).decode()],
    "nonce": str(secrets.randbits(64)),
}}
print(json.dumps({"transaction": transaction, "seal_signer": key_id, "other_signers": [], "lock_ids": [],
                  "detect_inputs": True, "detect_inputs_use_unversioned": True}))
PY
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

dry_run_outcome() {  # the dry run's verdict, fee and template, and whether the chain would hold our bytes
  python3 -I -c 'import hashlib, importlib.util, json, sys
spec = importlib.util.spec_from_file_location("cbor", sys.argv[2])
cbor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cbor)
f = json.load(sys.stdin)["result"]["finalize"]
verdict = next(iter(f["result"]))
ups = f["result"].get("Accept", {}).get("up_substates", [])
for sid, up in ups:
    if sid.startswith("template_"):
        value = up["substate"]
        value = cbor.substate_value(cbor.b64(value)) if isinstance(value, str) else value   # Encoded<…> since 0.48
        same = hashlib.sha256(bytes.fromhex(value["Template"]["binary"])).hexdigest() == sys.argv[1]
        print(verdict, "fee", f["fee_receipt"]["total_fees_paid"], "µT", sid,
              "holding seal_log.wasm byte for byte" if same else "holding OTHER bytes")
        break
else:
    print(verdict, json.dumps(f["result"])[:300])' "$expected" "$repo/server/mutis/cbor.py"
}

wait_for() {  # prints the finalized result of transaction $1
  rpc call transactions.wait_result "'{\"transaction_id\":\"$1\",\"timeout_secs\":240}'"
}

predicted=template_$(python3 -I "$repo/template/wasm_check.py" address "$author" "$wasm")
case $command in
  check)
    echo "seal_log.wasm sha256 ok; $account = $owner, author key $author"
    echo "a publish creates $predicted"
    echo "publish dry run: $(publish_params true | rpc call transactions.submit_dry_run - | dry_run_outcome)"
    ;;
  publish)
    tx=$(publish_params false | rpc call transactions.submit - | field transaction_id)
    echo "tx $tx"
    wait_for "$tx" | python3 -I -c 'import json, sys
r = json.load(sys.stdin)
print("status", r.get("status"), "fee", r.get("final_fee"))'
    python3 -I "$repo/template/wasm_check.py" onchain "$predicted" --wasm "$wasm"   # the chain runs $wasm byte for byte
    ;;
  instantiate)
    template=${template_arg#template_}
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
