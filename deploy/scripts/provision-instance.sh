#!/bin/bash
# SPDX-License-Identifier: MIT
# Provision an instance of mutis beside production on the same server (deploy/scripts/instance.py), idempotently.
# Run with sudo from your own login, from any copy of deploy/, after production's provision.sh:
#   sudo bash deploy/scripts/provision-instance.sh --name NAME --origin https://HOST --api-port PORT \
#     --walletd NETWORK:PORT [--walletd NETWORK:PORT] [--walletd-bin NETWORK:PATH ...] [--testnet-origin https://HOST] [--check]
# e.g. --name mainnet --origin https://mainnet.example.com --api-port 8788 --walletd mainnet:5101
#      --walletd esmeralda:5102 --walletd-bin esmeralda:/opt/tari/bin/tari_ootle_walletd-0.50.1-0b3f364
#
# What it makes, all under the instance's own names (production's files, users, units, ports and Caddyfile are
# never written; its ufw rules gain guard lines for the instance's ports only): users mutis-NAME and drive-NAME,
# /etc/mutis-NAME (mutis.toml from deploy/config/instance.toml.example if missing, a fresh secret.key, one walletd
# keyring password per network under credentials/, instance.conf), /srv/mutis-NAME/{app,data,status} on noexec
# mounts, /home/drive-NAME/{mutis,wallet-NETWORK,wallet-backup,.local/share/tari}, /usr/local/lib/mutis-NAME (the
# run scripts, backup.py, one walletd binary link per network), /usr/local/sbin/mutis-admin-NAME, /var/backups/
# mutis-NAME, the rendered units, and owner-match guards on 127.0.0.1:API-PORT and each walletd port. It enables
# the timers and mounts, never a walletd, the API or the chain worker: deploy.sh --instance NAME starts those
# once a release is live, and deploy/ootle/mainnet-walletd.sh sets a walletd up. --check only says what's missing.
set -euo pipefail
umask 022

DEPLOY=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OPERATOR=${MUTIS_OPERATOR:-${SUDO_USER:-}}
name= origin= api_port= check= testnet_origin=
walletds=() bins=()
while [ $# -gt 0 ]; do
  case $1 in
    --name) name=$2; shift ;;
    --origin) origin=$2; shift ;;
    --api-port) api_port=$2; shift ;;
    --walletd) walletds+=("$2"); shift ;;
    --walletd-bin) bins+=("$2"); shift ;;
    --testnet-origin) testnet_origin=$2; shift ;;
    --check) check=1 ;;
    *) echo "provision-instance: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n== %s\n' "$*"; }
die() { printf 'provision-instance: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
[ -n "$OPERATOR" ] && [ "$OPERATOR" != root ] && getent passwd "$OPERATOR" >/dev/null ||
  die "run it with sudo from your own login, or set MUTIS_OPERATOR=<login>"
python3 -I "$DEPLOY/scripts/instance.py" check-name "$name"
[[ $origin =~ ^https://[a-z0-9.-]+$ ]] || die "--origin https://host"
[[ $api_port =~ ^[0-9]+$ ]] && [ "$api_port" -gt 1024 ] && [ "$api_port" != 8787 ] || die "--api-port: a free loopback port, not 8787"
[ ${#walletds[@]} -gt 0 ] || die "--walletd NETWORK:PORT at least once"
eval "$(python3 -I "$DEPLOY/scripts/instance.py" env "$name")"
id -u caddy >/dev/null 2>&1 && [ -f /etc/caddy/Caddyfile ] || die "run production's provision.sh first (Caddy, the main Caddyfile)"

if [ -n "$check" ]; then
  step "check (nothing changes)"
  for what in "$INST_ETC" "$INST_CONFIG" "$INST_SRV/app/releases" "$INST_DATA/db" "$INST_DRIVE_HOME" "$INST_LIB" "$INST_ADMIN"; do
    [ -e "$what" ] && echo "ok $what" || echo "MISSING $what"
  done
  for user in "$INST_MUTIS_USER" "$INST_DRIVE_USER"; do getent passwd "$user" >/dev/null && echo "ok user $user" || echo "MISSING user $user"; done
  exit 0
fi

step "users and directories"
getent group "$INST_MUTIS_USER" >/dev/null || groupadd --system "$INST_MUTIS_USER"
getent passwd "$INST_MUTIS_USER" >/dev/null ||
  useradd --system --gid "$INST_MUTIS_USER" --home-dir "$INST_SRV" --no-create-home --shell /usr/sbin/nologin "$INST_MUTIS_USER"
# drive-NAME runs the instance's walletds, chain worker and sidecar, and the L1 console wallet in tmux.
getent passwd "$INST_DRIVE_USER" >/dev/null || useradd --user-group --create-home --shell /bin/bash "$INST_DRIVE_USER"
chmod 0700 "$INST_DRIVE_HOME"
id -nG "$INST_DRIVE_USER" | tr ' ' '\n' | grep -qx "$INST_MUTIS_USER" || usermod -aG "$INST_MUTIS_USER" "$INST_DRIVE_USER"
install -d -m 0755 -o root -g root "$INST_SRV" "$INST_APP" "$INST_APP/releases" "$INST_LIB"
install -d -m 2750 -o "$INST_MUTIS_USER" -g "$INST_MUTIS_USER" "$INST_DATA"
install -d -m 2770 -o "$INST_MUTIS_USER" -g "$INST_MUTIS_USER" "$INST_DATA/db"
install -d -m 0700 -o "$INST_MUTIS_USER" -g "$INST_MUTIS_USER" "$INST_DATA/blobs" "$INST_DATA/backup"
install -d -m 2775 -o "$INST_MUTIS_USER" -g "$INST_MUTIS_USER" "$INST_STATUS"
install -d -m 0700 -o "$INST_DRIVE_USER" -g "$INST_DRIVE_USER" "$INST_KEYS" "$INST_WALLET_BACKUPS" \
  "$INST_DRIVE_HOME/.local" "$INST_DRIVE_HOME/.local/share" "$INST_DRIVE_HOME/.local/share/tari"
install -d -m 0750 -o root -g "$INST_MUTIS_USER" "$INST_ETC"
install -d -m 0700 -o root -g root "$INST_ETC/credentials" "$INST_BACKUPS"
echo "ok: $INST_MUTIS_USER, $INST_DRIVE_USER; $INST_SRV; $INST_ETC"

step "configuration, secrets and walletd keyring passwords (made here)"
: > "$INST_ETC/instance.conf.new"
for spec in "${walletds[@]}"; do
  network=${spec%%:*} port=${spec#*:}
  case $network in esmeralda|mainnet) ;; *) die "--walletd esmeralda|mainnet:PORT, got $spec" ;; esac
  [[ $port =~ ^[0-9]+$ ]] && [ "$port" != 5100 ] || die "walletd port for $network: not production's 5100"
  echo "walletd=$network:$port" >> "$INST_ETC/instance.conf.new"
  install -d -m 0700 -o "$INST_DRIVE_USER" -g "$INST_DRIVE_USER" "$INST_DRIVE_HOME/wallet-$network"
  pass=$INST_ETC/credentials/walletd-$network-keyring-pass
  if [ ! -f "$pass" ]; then
    (umask 077 && head -c 33 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' > "$pass.new" && mv "$pass.new" "$pass")
    echo "generated $pass (root only; walletd gets it as a systemd credential)"
  fi
done
echo "api_port=$api_port" >> "$INST_ETC/instance.conf.new"
echo "origin=$origin" >> "$INST_ETC/instance.conf.new"
chmod 0644 "$INST_ETC/instance.conf.new" && mv "$INST_ETC/instance.conf.new" "$INST_ETC/instance.conf"
if [ ! -f "$INST_CONFIG" ]; then
  staging_port=$(printf '%s\n' "${walletds[@]}" | sed -n 's/^esmeralda://p' | head -n 1)
  [ -n "$staging_port" ] || die "a new instance starts as staging on Esmeralda: give --walletd esmeralda:PORT"
  host=${origin#https://}
  [[ $testnet_origin =~ ^https://[a-z0-9.-]+$ ]] || die "a new instance starts as staging: --testnet-origin https://HOST (the live testnet site)"
  sed -e "s#@NAME@#$name#g" -e "s#@ORIGIN@#$origin#g" -e "s#@API_PORT@#$api_port#g" -e "s#@WALLETD_PORT@#$staging_port#g" \
    -e "s#@TESTNET_ORIGIN@#$testnet_origin#g" \
    "$DEPLOY/config/instance.toml.example" > "$INST_CONFIG.new"
  grep -q '@[A-Z_]*@' "$INST_CONFIG.new" && die "instance.toml.example has a placeholder this script doesn't fill"
  install -m 0640 -o root -g "$INST_MUTIS_USER" "$INST_CONFIG.new" "$INST_CONFIG" && rm -f "$INST_CONFIG.new"
  echo "installed $INST_CONFIG for $host (staging on Esmeralda; deploy/ootle/mainnet-launch.md flips it)"
fi
chown root:"$INST_MUTIS_USER" "$INST_CONFIG" && chmod 0640 "$INST_CONFIG"
if [ ! -f "$INST_ETC/secret.key" ]; then
  (umask 077 && head -c 32 /dev/urandom > "$INST_ETC/secret.key.new")
  chown root:"$INST_MUTIS_USER" "$INST_ETC/secret.key.new" && chmod 0640 "$INST_ETC/secret.key.new"
  mv "$INST_ETC/secret.key.new" "$INST_ETC/secret.key"
  echo "generated $INST_ETC/secret.key"
fi
install -m 0640 -o root -g "$INST_MUTIS_USER" "$DEPLOY/ootle/walletd-log4rs.yml" "$INST_ETC/walletd-log4rs.yml"

step "scripts, walletd binaries and the admin command"
install -m 0755 -o root -g root "$DEPLOY/ootle/run-walletd.sh" "$INST_LIB/run-walletd.sh"
install -m 0755 -o root -g root "$DEPLOY/scripts/backup.py" "$INST_LIB/backup.py"
install -m 0755 -o root -g root "$DEPLOY/scripts/run-sidecar.sh" "$INST_LIB/run-sidecar.sh"
install -m 0755 -o root -g root "$DEPLOY/scripts/mutis-admin" "$INST_ADMIN"
for spec in "${bins[@]}"; do
  network=${spec%%:*} path=${spec#*:}
  [ -x "$path" ] || die "--walletd-bin $spec: not an executable"
  ln -sfn "$path" "$INST_LIB/tari_ootle_walletd-$network"
  echo "walletd for $network: $path ($("$path" --version 2>/dev/null | head -n 1))"
done

step "units (rendered from deploy/systemd by instance.py)"
rendered=$(mktemp -d)
trap 'rm -rf "$rendered"' EXIT
walletd_args=()
for spec in "${walletds[@]}"; do walletd_args+=(--walletd "$spec"); done
python3 -I "$DEPLOY/scripts/instance.py" units "$name" "$rendered" "${walletd_args[@]}" >/dev/null
changed=()
for unit in "$rendered"/*; do
  target=/etc/systemd/system/$(basename "$unit")
  cmp -s "$unit" "$target" && continue
  [ -e "$target" ] && cp -p "$target" "$INST_BACKUPS/$(basename "$unit").$(date -u +%Y%m%dT%H%M%SZ)"
  install -m 0644 -o root -g root "$unit" "$target"
  changed+=("$(basename "$unit")")
done
systemctl daemon-reload
for unit in "$rendered"/*; do
  systemd-analyze verify "/etc/systemd/system/$(basename "$unit")" >/dev/null 2>"$rendered/verify.log" ||
    { cat "$rendered/verify.log" >&2; die "systemd-analyze verify $(basename "$unit") failed"; }
done
echo "ok: ${#changed[@]} unit files new or changed${changed:+: ${changed[*]}}"

step "mounts: data noexec,nosuid,nodev; status also nosymfollow"
for dir in "$INST_DATA" "$INST_STATUS"; do
  mount=$(systemd-escape --path --suffix=mount "$dir")
  systemctl enable --now "$mount" >/dev/null 2>&1 || die "$mount did not start (journalctl -u '$mount')"
  echo "ok: $(findmnt -n -o TARGET,OPTIONS --target "$dir")"
done

step "ufw: owner-match guards for the instance's loopback ports"
op=$(id -u "$OPERATOR") drive=$(id -u "$INST_DRIVE_USER") caddy=$(id -u caddy)
guards=("$api_port 0 $op $drive $caddy")
for spec in "${walletds[@]}"; do guards+=("${spec#*:} 0 $op $drive"); done
reload=0
for f in /etc/ufw/before.rules /etc/ufw/before6.rules; do
  grep -qE -- '^-A ufw6?-before-output -o lo -j ACCEPT$' "$f" || die "$f has no loopback ACCEPT line to guard"
  for guard in "${guards[@]}"; do
    port=${guard%% *}
    if grep -q -- "--dport $port -j REJECT" "$f"; then continue; fi
    [ -e "$f.bak-mutis-$name" ] || cp -p "$f" "$f.bak-mutis-$name"
    # shellcheck disable=SC2086
    python3 -I - "$f" $guard <<'PY'
import re, sys
path, port, *uids = sys.argv[1:]
lines = open(path).read().split("\n")
at = next(i for i, l in enumerate(lines) if re.fullmatch(r"-A ufw6?-before-output -o lo -j ACCEPT", l))
chain = lines[at].split()[1]
guard = [f"-A {chain} -o lo -p tcp --dport {port} -m owner --uid-owner {uid} -j ACCEPT" for uid in uids]
guard.append(f"-A {chain} -o lo -p tcp --dport {port} -j REJECT --reject-with tcp-reset")
open(path, "w").write("\n".join(lines[:at] + guard + lines[at:]))
PY
    reload=1
    echo "  guarded $port in $(basename "$f") (uids ${guard#* })"
  done
done
[ "$reload" = 0 ] || ufw reload >/dev/null
echo "ok"

step "timers (the database backup once a database exists)"
systemctl enable --now "mutis-$name-backup-wallet.timer" "mutis-$name-cleanup.timer" "mutis-$name-health.timer" \
  "mutis-$name-evidence.timer" >/dev/null 2>&1
[ -f "$INST_DATA/db/mutis.sqlite3" ] && systemctl enable --now "mutis-$name-backup.timer" >/dev/null 2>&1
systemctl list-timers "mutis-$name-*" --no-pager | sed 's/^/  /' | head -n 8
echo
echo "next: deploy/scripts/deploy.sh <ref> --instance $name (the first deploy migrates the database and writes the"
echo "Caddy site), then enable the walletd for the config's network: systemctl enable --now mutis-$name-walletd-<network>"
