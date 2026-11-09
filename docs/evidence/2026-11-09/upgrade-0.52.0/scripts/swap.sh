#!/bin/bash
# SPDX-License-Identifier: MIT
# upgrade-0.52.md §5: the live walletd to 0.52.0, as root. Backups (root 0600) in /var/backups/mutis; the exit
# trap starts walletd again whatever fails. Outputs beside this script.
set -euo pipefail
S=$(dirname "$(readlink -f "$0")")
NEW=/opt/tari/bin/tari_ootle_walletd-0.52.0-4ee751c                 # §3: the release binary, four sources
TS=$(date -u +%Y%m%dT%H%M%SZ); B=/var/backups/mutis; LIVE=/opt/tari/bin/tari_ootle_walletd
RPC="sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py"
umask 077; cd /tmp
echo "TS=$TS"
trap 'systemctl is-active --quiet walletd || { systemctl start walletd || true; echo "trap: walletd $(systemctl is-active walletd || true)"; }' EXIT
$RPC balances > "$B/balances-$TS-before-0.52.0.json"
python3 -I "$S/wsum.py" > "$S/live-before.txt" 2>&1 || true
systemctl stop walletd
echo "stopped: $(systemctl is-active walletd || true) at $(date -u +%T.%N | cut -c1-12)"
tar -C /home/drive -cf "$B/wallet-$TS-pre-0.52.0.tar" wallet .local/share/tari
ls -l "$B/wallet-$TS-pre-0.52.0.tar"; sha256sum "$B/wallet-$TS-pre-0.52.0.tar"
echo "entries: $(tar -tf "$B/wallet-$TS-pre-0.52.0.tar" | wc -l); wallet.sqlite: $(tar -tf "$B/wallet-$TS-pre-0.52.0.tar" | grep -c wallet.sqlite)"
cp -a "$LIVE" "$B/tari_ootle_walletd.$TS"                  # = tari_ootle_walletd-0.50.1-0b3f364, for a rollback
sha256sum "$B/tari_ootle_walletd.$TS"
install -m 0755 -o root -g root "$NEW" "$LIVE"
sha256sum "$LIVE" "$NEW"; "$LIVE" --version
systemctl start walletd
echo "started: $(systemctl is-active walletd) at $(date -u +%T.%N | cut -c1-12)"
for i in $(seq 60); do $RPC call wallet.get_info '{}' >/dev/null 2>&1 && break; sleep 2; done   # 0.52 adds no migration
echo "RPC answering at $(date -u +%T)"
$RPC balances > "$B/balances-$TS-after-0.52.0.json"
diff <(grep -v '"version"' "$B/balances-$TS-before-0.52.0.json") <(grep -v '"version"' "$B/balances-$TS-after-0.52.0.json") \
  && echo "balances unchanged" || echo "BALANCES DIFFER: compare the two files before going on"
grep '"version"' "$B/balances-$TS-before-0.52.0.json" "$B/balances-$TS-after-0.52.0.json"
python3 -I "$S/wsum.py" > "$S/live-after.txt" 2>&1 || true
python3 -I -c 'import sqlite3; c = sqlite3.connect("file:/home/drive/wallet/esmeralda/data/wallet.sqlite?mode=ro", uri=True); print("live store: migrations", c.execute("SELECT COUNT(*), MAX(version) FROM __diesel_schema_migrations").fetchone(), "| accounts", c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])'
ls -l "$B" | grep "$TS"
echo "TS=$TS"
