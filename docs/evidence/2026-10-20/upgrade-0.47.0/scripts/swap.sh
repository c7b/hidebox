#!/bin/bash
# SPDX-License-Identifier: MIT
# Upgrade drill §4: the live walletd to 0.47.0. Backups (root 0600) in /var/backups/mutis.
set -euo pipefail
S=$(dirname "$(readlink -f "$0")")
TS=$(date -u +%Y%m%dT%H%M%SZ); B=/var/backups/mutis; RPC=/srv/mutis/app/current/deploy/ootle/walletd-rpc.py
NEW=/opt/tari/bin/tari_ootle_walletd-0.47.0-9dabb2a; LIVE=/opt/tari/bin/tari_ootle_walletd
echo "TS=$TS"
umask 077
# Never leave walletd down: whatever fails below, it is started again with the binary at its path.
trap 'systemctl is-active --quiet walletd || { systemctl start walletd || true; echo "trap: walletd $(systemctl is-active walletd || true)"; }' EXIT
python3 -I "$RPC" balances > "$B/balances-$TS-before-0.47.0.json"
python3 -I "$S/wsum.py" > "$S/live-before.txt" 2>&1 || true
systemctl stop walletd
echo "stopped: $(systemctl is-active walletd || true) at $(date -u +%T)"
tar -C /home/drive -cf "$B/wallet-$TS-pre-upgrade.tar" wallet
ls -l "$B/wallet-$TS-pre-upgrade.tar"; sha256sum "$B/wallet-$TS-pre-upgrade.tar"; tar -tf "$B/wallet-$TS-pre-upgrade.tar" | wc -l
cp -a "$LIVE" "$B/tari_ootle_walletd.$TS"
sha256sum "$B/tari_ootle_walletd.$TS"
install -m 0755 -o root -g root "$NEW" "$LIVE"
sha256sum "$LIVE"; "$LIVE" --version
systemctl start walletd
echo "started: $(systemctl is-active walletd) at $(date -u +%T)"
sleep 20
python3 -I "$RPC" balances > "$B/balances-$TS-after-0.47.0.json"
diff "$B/balances-$TS-before-0.47.0.json" "$B/balances-$TS-after-0.47.0.json" || true
python3 -I "$S/wsum.py" > "$S/live-after.txt" 2>&1 || true
ls -l "$B" | grep "$TS"
