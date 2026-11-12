#!/bin/bash
# SPDX-License-Identifier: MIT
# Arm (or disarm) the launch trigger (deploy/ootle/launch.py) for an instance, as root on the server, from a copy
# of the repository (deploy/, server/mutis/cbor.py, template/):
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/launch-arm.sh --label L --network esmeralda|mainnet \
#     --walletd-port P --account A --wasm template/dist-v2/seal_log.wasm [--dry-run] [--min-public-ut N] [--no-start]
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/launch-arm.sh --label L --disarm
# It checks the wasm against the SHA256SUMS beside it, installs the code (root-owned, read-only to the trigger) in
# /usr/local/lib/mutis-<name>/launch/, writes /etc/mutis-<name>/launch-L.toml, and starts the timer
# mutis-<name>-launch-L.timer: a pass every 30 seconds as drive-<name>, which can reach only its instance's
# walletd. The trigger's state, status.json, evidence.json and launch.log are in /home/drive-<name>/launch-L/.
# Watch it: sudo cat /home/drive-<name>/launch-L/status.json, or journalctl -fu mutis-<name>-launch-L.
# Re-arming keeps the state (a half-done launch resumes); --dry-run arms it with dry runs only.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)
label= network= port= account= wasm= dry= disarm= start=1
min_public=2200000 reveal=3000000 fee_reveal=100000 fee_publish=2000000 fee_log=100000
while [ $# -gt 0 ]; do
  case $1 in
    --label) label=$2; shift ;;
    --network) network=$2; shift ;;
    --walletd-port) port=$2; shift ;;
    --account) account=$2; shift ;;
    --wasm) wasm=$2; shift ;;
    --min-public-ut) min_public=$2; shift ;;
    --reveal-ut) reveal=$2; shift ;;
    --max-fee-publish-ut) fee_publish=$2; shift ;;
    --dry-run) dry=--dry-run ;;
    --disarm) disarm=1 ;;
    --no-start) start= ;;
    *) echo "launch-arm: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done
die() { echo "launch-arm: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
[[ $label =~ ^[a-z][a-z0-9]{1,15}$ ]] || die "--label: 2 to 16 of a-z, 0-9"
eval "$(python3 -I "$repo/deploy/scripts/instance.py" env "${MUTIS_INSTANCE:-}")"
[ -n "$MUTIS_INSTANCE" ] || die "MUTIS_INSTANCE names no instance (the trigger runs as an instance's drive user)"
unit=mutis-$MUTIS_INSTANCE-launch-$label
config=$INST_ETC/launch-$label.toml
state=$INST_DRIVE_HOME/launch-$label
code=$INST_LIB/launch

if [ -n "$disarm" ]; then
  systemctl disable --now "$unit.timer" >/dev/null 2>&1 || true
  systemctl stop "$unit.service" >/dev/null 2>&1 || true
  echo "launch-arm: $unit disarmed; its state stays in $state"
  exit 0
fi

case $network in
  esmeralda) indexers='["https://ootle-indexer-b.tari.com", "https://ootle-indexer-a.tari.com"]' ;;
  mainnet) indexers='["https://indexer-a.ootle.tari.com", "https://indexer-b.ootle.tari.com"]' ;;
  *) die "--network esmeralda|mainnet" ;;
esac
[[ $port =~ ^[0-9]+$ ]] && [ "$port" != 5100 ] || die "--walletd-port: the instance's walletd, never production's 5100"
grep -qx "walletd=$network:$port" "$INST_ETC/instance.conf" || die "$INST_ETC/instance.conf has no walletd=$network:$port"
[[ $account =~ ^[a-z][a-z0-9_-]{0,31}$ ]] || die "--account: a walletd account name"
for n in "$min_public" "$reveal" "$fee_reveal" "$fee_publish" "$fee_log"; do [[ $n =~ ^[0-9]+$ ]] || die "amounts are µT integers"; done
[ -f "$wasm" ] || die "--wasm: no file $wasm"
sums=$(dirname "$wasm")/SHA256SUMS
[ -f "$sums" ] || die "no SHA256SUMS beside $wasm"
digest=$(sha256sum "$wasm" | cut -d' ' -f1)
grep -q "^$digest  $(basename "$wasm")\$" "$sums" || die "$wasm does not match $sums"

install -d -m 0755 -o root -g root "$code" "$code/$label"
install -m 0755 -o root -g root "$here/launch.py" "$code/launch.py"
install -m 0644 -o root -g root "$repo/server/mutis/cbor.py" "$code/cbor.py"
install -m 0644 -o root -g root "$repo/template/wasm_check.py" "$code/wasm_check.py"
install -m 0644 -o root -g root "$wasm" "$code/$label/seal_log.wasm"
install -d -m 0700 -o "$INST_DRIVE_USER" -g "$INST_DRIVE_USER" "$state"
cat > "$config.new" <<TOML
# SPDX-License-Identifier: MIT
# The launch trigger "$label" of instance $MUTIS_INSTANCE (deploy/ootle/launch.py), written by launch-arm.sh $(date -u +%Y-%m-%dT%H:%M:%SZ).
label = "$label"
network = "$network"
walletd_url = "http://127.0.0.1:$port/json_rpc"
account = "$account"
indexers = $indexers
wasm = "$code/$label/seal_log.wasm"
wasm_sha256 = "$digest"
state_dir = "$state"
# µT. pay_fee locks its max_fee from the public vault, so min_public_ut covers both fees' ceilings.
min_public_ut = $min_public
reveal_ut = $reveal
max_fee_reveal_ut = $fee_reveal
max_fee_publish_ut = $fee_publish
max_fee_log_ut = $fee_log
dry_run = $([ -n "$dry" ] && echo true || echo false)
TOML
install -m 0640 -o root -g "$INST_MUTIS_USER" "$config.new" "$config" && rm -f "$config.new"

cat > "/etc/systemd/system/$unit.service" <<UNIT
# SPDX-License-Identifier: MIT
# The launch trigger "$label" of mutis-$MUTIS_INSTANCE (deploy/ootle/launch.py; armed by deploy/ootle/launch-arm.sh).
[Unit]
Description=mutis-$MUTIS_INSTANCE launch trigger $label: publish SealLog on $network as soon as it can
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$INST_DRIVE_USER
Group=$INST_DRIVE_USER
SupplementaryGroups=$INST_MUTIS_USER
ExecStart=/usr/bin/python3 -I $code/launch.py run --config $config $dry
SyslogIdentifier=$unit
TimeoutStartSec=900

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$state
NoExecPaths=/tmp /var/tmp /dev/shm $state
InaccessiblePaths=-/srv/mutis -/etc/mutis -$INST_DATA -$INST_ETC/secret.key
PrivateTmp=yes
PrivateDevices=yes
ProtectProc=invisible
ProcSubset=pid
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=
RemoveIPC=yes
UMask=0077
MemoryMax=256M
UNIT
cat > "/etc/systemd/system/$unit.timer" <<UNIT
# SPDX-License-Identifier: MIT
[Unit]
Description=mutis-$MUTIS_INSTANCE launch trigger $label, every 30 seconds until it is done

[Timer]
OnBootSec=60
OnActiveSec=5
OnUnitActiveSec=30
AccuracySec=1s

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemd-analyze verify "/etc/systemd/system/$unit.service" "/etc/systemd/system/$unit.timer" >/dev/null
echo "launch-arm: $unit armed: $network, walletd 127.0.0.1:$port, account $account, wasm sha256 $digest${dry:+ (dry runs only)}"
if [ -n "$start" ]; then
  systemctl enable --now "$unit.timer" >/dev/null 2>&1
  systemctl start "$unit.service" || true
  cat "$state/status.json" 2>/dev/null || true
fi
