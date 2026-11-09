#!/bin/bash
# SPDX-License-Identifier: MIT
# upgrade-0.52.md §3 (upgrade-drill.md §3) for walletd 0.52.0: the new binary on a consistent copy of the
# wallet, with no network, under every directive of deploy/systemd/walletd.service plus PrivateNetwork.
# Read-only additions: the copy's migrations and authored templates before and after, a summary (wsum.py),
# the drill unit's journal. Run as root; writes its outputs beside itself.
set -euo pipefail
T=/var/lib/walletd-drill; NEW=/opt/tari/bin/tari_ootle_walletd-0.52.0-4ee751c
S=$(dirname "$(readlink -f "$0")")
# The copy holds keys: whatever fails below, it is stopped and deleted (every command before rm may fail).
trap 'systemctl stop walletd-drill 2>/dev/null || true; rm -rf "$T"; test -e "$T" && echo "drill copy STILL PRESENT" || echo "drill copy removed: $T no longer exists"' EXIT
rm -rf "$T"; install -d -m 700 -o drive -g drive "$T" "$T/wallet" "$T/share" "$T/share/esmeralda" "$T/share/esmeralda/burn_proofs"
cp -a /home/drive/wallet/esmeralda "$T/wallet/"
python3 -I -c 'import sqlite3, sys; s = sqlite3.connect("file:/home/drive/wallet/esmeralda/data/wallet.sqlite?mode=ro", uri=True); d = sqlite3.connect(sys.argv[1]); s.backup(d)' "$T/wallet/esmeralda/data/wallet.sqlite"
rm -f "$T/wallet/esmeralda/data/wallet.sqlite-wal" "$T/wallet/esmeralda/data/wallet.sqlite-shm"
chown -R drive:drive "$T"
db() { python3 -I -c 'import sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
print("migrations", c.execute("SELECT COUNT(*), MAX(version) FROM __diesel_schema_migrations").fetchone(),
      "| accounts", c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])' "$T/wallet/esmeralda/data/wallet.sqlite"; }
echo "copy before: $(db)"
date -u +"drill start %FT%TZ"
systemd-run --unit=walletd-drill -p User=drive -p Group=drive -p PrivateNetwork=yes -p ProtectHome=tmpfs \
  -p "BindPaths=$T $T/share:/home/drive/.local/share/tari" -p ProtectSystem=strict -p NoNewPrivileges=yes \
  -p LoadCredential=keyring-pass:/etc/mutis/credentials/walletd-keyring-pass -p RuntimeDirectory=walletd-drill \
  -p RuntimeDirectoryMode=0700 -p "InaccessiblePaths=/srv/mutis -/etc/mutis/secret.key -/etc/mutis/mutis.toml -/etc/mutis/caddy.env" \
  -p "NoExecPaths=/tmp /var/tmp /dev/shm $T" -p PrivateTmp=yes -p PrivateDevices=yes -p ProtectProc=invisible \
  -p ProcSubset=pid -p ProtectKernelTunables=yes -p ProtectKernelModules=yes -p ProtectKernelLogs=yes \
  -p ProtectControlGroups=yes -p ProtectClock=yes -p ProtectHostname=yes -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" \
  -p RestrictNamespaces=yes -p RestrictRealtime=yes -p RestrictSUIDSGID=yes -p LockPersonality=yes \
  -p SystemCallArchitectures=native -p SystemCallFilter=@system-service -p "SystemCallFilter=~@privileged" \
  -p SystemCallErrorNumber=EPERM -p CapabilityBoundingSet= -p RemoveIPC=yes -p UMask=0077 -p MemoryMax=2G -p TasksMax=256 \
  --setenv=WALLETD_BASE=$T/wallet --setenv=WALLETD_LISTEN=127.0.0.1:5199 --setenv=WALLETD_BIN=$NEW \
  /usr/local/lib/mutis/run-walletd.sh
sleep 5
PID=$(systemctl show -p MainPID --value walletd-drill)
for i in $(seq 30); do
  nsenter -t "$PID" -n python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py --url http://127.0.0.1:5199/json_rpc \
    call wallet.get_info '{}' >/dev/null 2>&1 && break; sleep 2
done
systemctl is-active walletd-drill
nsenter -t "$PID" -n python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py --url http://127.0.0.1:5199/json_rpc balances > "$S/drill-balances.json"
nsenter -t "$PID" -n python3 -I "$S/wsum.py" http://127.0.0.1:5199/json_rpc || true
python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py balances > "$S/live-balances.json"
echo "copy after: $(db)"
journalctl -u walletd-drill -o short-iso-precise --utc --no-pager > "$S/drill-journal.full" || true
grep -v -i -E 'keyring|password' "$S/drill-journal.full" | cut -c1-330 > "$S/drill-journal.txt" || true
echo "sandbox denials in the drill's journal: $(grep -c -i -E 'EPERM|permission denied|operation not permitted|seccomp|SIGSYS|read-only file system' "$S/drill-journal.full" || true)"
echo "migration lines: $(grep -c -i 'migrat' "$S/drill-journal.full" || true)"
rm -f "$S/drill-journal.full"
if diff <(grep -v '"version"' "$S/drill-balances.json") <(grep -v '"version"' "$S/live-balances.json") > "$S/balances.diff"; then
  echo "drill copy vs live balances (version aside): SAME"; else echo "drill copy vs live balances (version aside): DIFFERENT"; cat "$S/balances.diff"; fi
grep '"version"' "$S/drill-balances.json" "$S/live-balances.json"
