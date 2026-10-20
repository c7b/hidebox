#!/bin/bash
# SPDX-License-Identifier: MIT
# Upgrade drill §3 for walletd 0.47.0: the new binary on a consistent copy of the wallet, with no
# network, under the production unit's sandbox (deploy/systemd/walletd.service) plus PrivateNetwork.
# Read-only additions: the copy's applied migrations before and after, and a summary (wsum.py).
set -euo pipefail
T=/var/lib/walletd-drill; NEW=/opt/tari/bin/tari_ootle_walletd-0.47.0-9dabb2a
S=$(dirname "$(readlink -f "$0")")
# The copy holds keys: whatever fails below, it is stopped and deleted.
trap 'systemctl stop walletd-drill 2>/dev/null; systemctl reset-failed walletd-drill 2>/dev/null; rm -rf "$T"; test -e "$T" && echo "drill copy STILL PRESENT" || echo "drill copy removed: $T no longer exists"' EXIT
rm -rf "$T"; install -d -m 700 -o drive -g drive "$T" "$T/wallet" "$T/share" "$T/share/esmeralda" "$T/share/esmeralda/burn_proofs"
cp -a /home/drive/wallet/esmeralda "$T/wallet/"
python3 -I -c 'import sqlite3, sys; s = sqlite3.connect("file:/home/drive/wallet/esmeralda/data/wallet.sqlite?mode=ro", uri=True); d = sqlite3.connect(sys.argv[1]); s.backup(d)' "$T/wallet/esmeralda/data/wallet.sqlite"
rm -f "$T/wallet/esmeralda/data/wallet.sqlite-wal" "$T/wallet/esmeralda/data/wallet.sqlite-shm"
chown -R drive:drive "$T"
mig() { python3 -I -c 'import sqlite3, sys; print(sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True).execute("SELECT COUNT(*), MAX(version) FROM __diesel_schema_migrations").fetchone())' "$T/wallet/esmeralda/data/wallet.sqlite"; }
echo "copy schema migrations before: $(mig)"
date -u +"drill start %FT%TZ"
systemd-run --unit=walletd-drill -p User=drive -p Group=drive -p PrivateNetwork=yes \
  -p ProtectHome=tmpfs -p "BindPaths=$T $T/share:/home/drive/.local/share/tari" -p ProtectSystem=strict \
  -p NoNewPrivileges=yes -p LoadCredential=keyring-pass:/etc/mutis/credentials/walletd-keyring-pass \
  -p RuntimeDirectory=walletd-drill -p RuntimeDirectoryMode=0700 \
  -p "InaccessiblePaths=/srv/mutis -/etc/mutis/secret.key -/etc/mutis/mutis.toml -/etc/mutis/caddy.env" \
  -p "NoExecPaths=/tmp /var/tmp /dev/shm $T" -p PrivateTmp=yes -p PrivateDevices=yes -p ProtectProc=invisible \
  -p ProcSubset=pid -p ProtectKernelTunables=yes -p ProtectKernelModules=yes -p ProtectKernelLogs=yes \
  -p ProtectControlGroups=yes -p ProtectClock=yes -p ProtectHostname=yes \
  -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" -p RestrictNamespaces=yes -p RestrictRealtime=yes \
  -p RestrictSUIDSGID=yes -p LockPersonality=yes -p SystemCallArchitectures=native \
  -p SystemCallFilter=@system-service -p "SystemCallFilter=~@privileged" -p SystemCallErrorNumber=EPERM \
  -p CapabilityBoundingSet= -p RemoveIPC=yes -p UMask=0077 -p MemoryMax=2G -p TasksMax=256 \
  --setenv=WALLETD_BASE=$T/wallet --setenv=WALLETD_LISTEN=127.0.0.1:5199 --setenv=WALLETD_BIN=$NEW \
  /usr/local/lib/mutis/run-walletd.sh
sleep 15
systemctl is-active walletd-drill
PID=$(systemctl show -p MainPID --value walletd-drill)
nsenter -t "$PID" -n python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py --url http://127.0.0.1:5199/json_rpc balances > "$S/drill-balances.json"
nsenter -t "$PID" -n python3 -I "$S/wsum.py" http://127.0.0.1:5199/json_rpc
python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py balances > "$S/live-balances.json"
echo "copy schema migrations after: $(mig)"
journalctl -u walletd-drill -o short-iso-precise --utc --no-pager | grep -v -i -E 'keyring|password' | cut -c1-330 | head -60 > "$S/drill-journal.txt"
if diff <(grep -v '"version"' "$S/drill-balances.json") <(grep -v '"version"' "$S/live-balances.json") > "$S/balances.diff"; then
  echo "drill copy vs live balances (version aside): SAME"; else echo "drill copy vs live balances (version aside): DIFFERENT"; cat "$S/balances.diff"; fi
