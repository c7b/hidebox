#!/bin/bash
# SPDX-License-Identifier: MIT
# Turn an instance from its staging rehearsal (Esmeralda) into the mainnet deployment, as root on the server:
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/flip-to-mainnet.sh --component component_<hex> [--dry-run]
# then, from the workstation: deploy/scripts/deploy.sh <ref> --instance <name> (the build reads the new config).
# In order: checks the mainnet indexer is live and its walletd runs on the mainnet; stops the instance's API and
# chain worker; keeps a root-only copy of the staging database (backup.py prune-root deletes it after 7 days, like
# every other database copy) and deletes the staging files, keys and database, which were test money and a
# rehearsal; edits the instance's mutis.toml (network mainnet, staging off, the mainnet indexers, the mainnet
# walletd's port, mirror_start_epoch = the mainnet's current epoch, the new SealLog component and
# features.seallog on), keeping the old file in /var/backups/mutis-<name>; validates it with check-config; and
# stops the staging walletd. --dry-run prints the new config and changes nothing. Production is never touched.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
component= dry=
while [ $# -gt 0 ]; do
  case $1 in
    --component) component=$2; shift ;;
    --dry-run) dry=1 ;;
    *) echo "flip-to-mainnet: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done
die() { echo "flip-to-mainnet: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
eval "$(python3 -I "$here/../scripts/instance.py" env "${MUTIS_INSTANCE:-}")"
[ -n "$MUTIS_INSTANCE" ] || die "MUTIS_INSTANCE names no instance; production stays on Esmeralda"
[[ $component =~ ^component_[0-9a-f]{64}$ ]] || die "--component component_<hex>: the log the launch trigger made (its evidence.json)"
port=$(sed -n 's/^walletd=mainnet://p' "$INST_ETC/instance.conf")
staging_port=$(sed -n 's/^walletd=esmeralda://p' "$INST_ETC/instance.conf")
[ -n "$port" ] || die "$INST_ETC/instance.conf names no mainnet walletd"

stats=$(curl -sSf -m 20 -A mutis-flip https://indexer-a.ootle.tari.com/epoch-manager/stats ||
        curl -sSf -m 20 -A mutis-flip https://indexer-b.ootle.tari.com/epoch-manager/stats) || die "no mainnet indexer answers"
epoch=$(printf '%s' "$stats" | python3 -I -c 'import json, sys; s = json.load(sys.stdin)
sys.exit("not live") if not (s.get("current_epoch") and s.get("consensus_epoch") is not None) else print(s["current_epoch"])') ||
  die "the mainnet indexer is not live yet"
info=$(cd /tmp && runuser -u "$INST_DRIVE_USER" -- python3 -I "$here/walletd-rpc.py" --url "http://127.0.0.1:$port/json_rpc" call wallet.get_info) ||
  die "the mainnet walletd on 127.0.0.1:$port doesn't answer"
printf '%s' "$info" | python3 -I -c 'import json, sys; i = json.load(sys.stdin)
sys.exit(0 if i.get("network") == "mainnet" and i.get("network_byte") == 0 else "walletd is not on the mainnet")'

new=$(mktemp)
trap 'rm -f "$new"' EXIT
python3 -I - "$INST_CONFIG" "$new" "$port" "$epoch" "$component" <<'PY'
import re, sys, tomllib
src, dst, port, epoch, component = sys.argv[1:]
text = open(src).read()
cfg = tomllib.loads(text)
if cfg.get("network") == "mainnet":
    sys.exit("flip-to-mainnet: the config already names the mainnet")
edits = [
    (r'^network = "esmeralda"$', 'network = "mainnet"'),
    (r'^staging = true$', 'staging = false'),
    (r'^indexers = \[.*\]$', 'indexers = ["https://indexer-a.ootle.tari.com", "https://indexer-b.ootle.tari.com"]'),
    (r'^walletd_url = ".*"$', f'walletd_url = "http://127.0.0.1:{port}/json_rpc"'),
    (r'^mirror_start_epoch = \d+$', f'mirror_start_epoch = {epoch}'),
    (r'^seallog_component = ".*"$', f'seallog_component = "{component}"'),
    (r'^seallog = (?:true|false)$', 'seallog = true'),        # staging may already run its own log
]
for pattern, line in edits:
    text, n = re.subn(pattern, line, text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"flip-to-mainnet: no line matches {pattern} in {src}")
for f in ("demo_pay", "sponsor", "judge_passes"):
    if re.search(rf"^{f} = true$", text, re.M):
        sys.exit(f"flip-to-mainnet: features.{f} is on; the mainnet has no test money")
open(dst, "w").write(text)
PY
diff -u "$INST_CONFIG" "$new" | sed 's/^/  /' || true
if [ -n "$dry" ]; then
  echo "flip-to-mainnet: dry run; nothing changed"
  exit 0
fi

systemctl stop "$INST_CHAIN_UNIT" "$INST_API_UNIT"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 -o root -g root "$INST_BACKUPS"
cp -p "$INST_CONFIG" "$INST_BACKUPS/mutis.toml.staging.$stamp"
if [ -f "$INST_DATA/db/mutis.sqlite3" ]; then
  python3 -I -c 'import sqlite3, sys; s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' \
    "$INST_DATA/db/mutis.sqlite3" "$INST_BACKUPS/staging-$stamp.sqlite3"
  chmod 0600 "$INST_BACKUPS/staging-$stamp.sqlite3"
fi
find "$INST_DATA/db" "$INST_DATA/blobs" "$INST_DATA/backup" -mindepth 1 -delete
find "$INST_KEYS" -mindepth 1 -maxdepth 1 -name '*.json' -delete           # init-keys makes mainnet ones at deploy
rm -f "$INST_STATUS"/evidence.json "$INST_STATUS"/evidence-archive-*.json "$INST_STATUS"/releases.json "$INST_STATUS"/status.json
install -m 0640 -o root -g "$INST_MUTIS_USER" "$new" "$INST_CONFIG"
runuser -u "$INST_MUTIS_USER" -- env MUTIS_CONFIG="$INST_CONFIG" python3 -I "$INST_APP/current/server/bin/mutis-admin" migrate >/dev/null
runuser -u "$INST_MUTIS_USER" -- env MUTIS_CONFIG="$INST_CONFIG" python3 -I "$INST_APP/current/server/bin/mutis-admin" check-config
[ -n "$staging_port" ] && systemctl disable --now "mutis-$MUTIS_INSTANCE-walletd-esmeralda" >/dev/null 2>&1 || true
echo "flip-to-mainnet: $INST_CONFIG names the mainnet (epoch $epoch, log $component); the staging data is gone"
echo "  (its database: $INST_BACKUPS/staging-$stamp.sqlite3). Now deploy: deploy/scripts/deploy.sh <ref> --instance $MUTIS_INSTANCE"
echo "  then: systemctl start $INST_API_UNIT $INST_CHAIN_UNIT (the deploy restarts them if enabled)"
