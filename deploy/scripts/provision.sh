#!/bin/bash
# SPDX-License-Identifier: MIT
# Provision the server for mutis, idempotently (spec §15.1). Run with sudo from your own login, from any
# copy of deploy/ (docs/self-host.md walks a new server through it):
#   sudo bash deploy/scripts/provision.sh
# Your login is the operator: with root, the only account besides drive that may reach walletd and the
# API port (MUTIS_OPERATOR=<login> names another one). Re-running is safe. It never overwrites /etc/mutis/mutis.toml or any key, and never moves, deletes
# or re-initialises /home/drive/wallet or /home/drive/l1wallet. The one-time move of walletd from its
# tmux session into walletd.service backs the wallet up first (root-only tar) and stops if the
# balances walletd reports afterwards differ from before.
set -euo pipefail
umask 022

DEPLOY=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WALLET=/home/drive/wallet
BACKUPS=/var/backups/mutis
CREDENTIAL=/etc/mutis/credentials/walletd-keyring-pass
OPERATOR=${MUTIS_OPERATOR:-${SUDO_USER:-}}
PACKAGES=(caddy nodejs chromium fonttools python3-brotli woff2 ffmpeg)

step() { printf '\n== %s\n' "$*"; }
die() { printf 'provision: %s\n' "$*" >&2; exit 1; }
stamp() { date -u +%Y%m%dT%H%M%SZ; }
RUN_STAMP=$(stamp)
CHANGED_UNITS=()

# install_kept <mode> <source> <target>: install a file, first copying the one it replaces (if different) to
# /var/backups/mutis/<name>.<UTC time>, so every change this script makes on a server can be undone by hand.
install_kept() {
  local mode=$1 src=$2 dst=$3
  if [ -e "$dst" ] && cmp -s "$src" "$dst"; then chown root:root "$dst"; chmod "$mode" "$dst"; return 0; fi
  if [ -e "$dst" ]; then
    local name
    name=$(basename "$dst")
    case $dst in */*.d/*) name="$(basename "$(dirname "$dst")")-$name" ;; esac
    install -d -m 0700 -o root -g root "$BACKUPS"
    cp -p "$dst" "$BACKUPS/$name.$RUN_STAMP"
    echo "  kept the previous $dst as $BACKUPS/$name.$RUN_STAMP"
  fi
  install -m "$mode" -o root -g root "$src" "$dst"
  case $dst in
    /etc/systemd/system/*.service.d/*) CHANGED_UNITS+=("$(basename "$(dirname "$dst")" .d)") ;;
    /etc/systemd/system/*) CHANGED_UNITS+=("$(basename "$dst")") ;;
  esac
}

[ "$(id -u)" = 0 ] || die "run as root"
[ -n "$OPERATOR" ] && [ "$OPERATOR" != root ] && getent passwd "$OPERATOR" >/dev/null ||
  die "run it with sudo from your own login, or set MUTIS_OPERATOR=<login>"

check_packages() {
  step "Debian packages (installed by the owner; this script installs nothing)"
  local missing=() p
  for p in "${PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || missing+=("$p")
  done
  [ ${#missing[@]} -eq 0 ] || die "missing packages: ${missing[*]} (apt-get install --no-install-recommends, after owner approval)"
  if command -v npm >/dev/null || command -v npx >/dev/null; then die "npm/npx must not be installed"; fi
  echo "ok: ${PACKAGES[*]} present; npm and npx absent"
}

users_and_dirs() {
  step "users and directories (spec §8.1)"
  getent passwd mutis >/dev/null ||
    useradd --system --user-group --home-dir /srv/mutis --no-create-home --shell /usr/sbin/nologin mutis
  # drive runs walletd, the chain worker and the sidecar; build runs the tests and compiles, and
  # holds no secret. Both are ordinary accounts with a home and no password (sudo -u, runuser).
  local user
  for user in drive build; do
    getent passwd "$user" >/dev/null || useradd --user-group --create-home --shell /bin/bash "$user"
  done
  chmod 0700 /home/drive /home/build
  id -nG drive | tr ' ' '\n' | grep -qx mutis || usermod -aG mutis drive
  install -d -m 0755 -o root -g root /srv/mutis /srv/mutis/app /srv/mutis/app/releases
  # Group mutis (drive: the chain worker and the evidence collector) may write the database's directory, never
  # the data directory itself, where health.json and the mount's root live.
  install -d -m 2750 -o mutis -g mutis /srv/mutis/data
  install -d -m 2770 -o mutis -g mutis /srv/mutis/data/db
  install -d -m 0700 -o mutis -g mutis /srv/mutis/data/blobs /srv/mutis/data/backup
  # Only mutis may list, add or rename anything under blobs/: every level 0700 (setgid kept), every file 0600.
  find /srv/mutis/data/blobs -mindepth 1 -type d -perm /0077 -exec chmod go-rwx {} +
  find /srv/mutis/data/blobs -type f ! -perm 0600 -exec chmod 0600 {} +
  install -d -m 2775 -o mutis -g mutis /srv/mutis/status
  install -d -m 0700 -o drive -g drive /home/drive/mutis "$WALLET" "$WALLET/backup"
  install -d -m 0750 -o root -g mutis /etc/mutis
  install -d -m 0700 -o root -g root /etc/mutis/credentials "$BACKUPS"
  install -d -m 0755 -o root -g root /usr/local/lib/mutis /etc/caddy/mutis.d
  echo "ok: users mutis, drive, build; operator $OPERATOR; tree under /srv/mutis"
}

config_and_secrets() {
  step "configuration and secrets (generated here; nothing comes from another machine)"
  if [ ! -f /etc/mutis/mutis.toml ]; then
    install -m 0640 -o root -g mutis "$DEPLOY/config/mutis.toml.example" /etc/mutis/mutis.toml
    echo "installed /etc/mutis/mutis.toml from the example"
  fi
  chown root:mutis /etc/mutis/mutis.toml && chmod 0640 /etc/mutis/mutis.toml
  if [ ! -f /etc/mutis/secret.key ]; then
    (umask 077 && head -c 32 /dev/urandom > /etc/mutis/secret.key.new)
    chown root:mutis /etc/mutis/secret.key.new && chmod 0640 /etc/mutis/secret.key.new
    mv /etc/mutis/secret.key.new /etc/mutis/secret.key
    echo "generated /etc/mutis/secret.key"
  fi
  if [ ! -f "$CREDENTIAL" ] && [ -f "$WALLET/.keyring-pass" ]; then
    install -m 0600 -o root -g root "$WALLET/.keyring-pass" "$CREDENTIAL"
    echo "copied walletd's keyring password into $CREDENTIAL (root only)"
  fi
  local host
  host=$(python3 -I -c 'import sys, tomllib, urllib.parse
print(urllib.parse.urlsplit(tomllib.load(open(sys.argv[1], "rb"))["public_origin"]).hostname)' /etc/mutis/mutis.toml)
  printf 'MUTIS_HOST=%s\n' "$host" > /etc/mutis/caddy.env.new
  chmod 0640 /etc/mutis/caddy.env.new && chown root:mutis /etc/mutis/caddy.env.new
  mv /etc/mutis/caddy.env.new /etc/mutis/caddy.env
  echo "ok: MUTIS_HOST=$host"
}

install_files() {
  step "scripts, units and logging configuration"
  install -m 0755 -o root -g root "$DEPLOY/ootle/run-walletd.sh" /usr/local/lib/mutis/run-walletd.sh
  install -m 0755 -o root -g root "$DEPLOY/scripts/backup.py" /usr/local/lib/mutis/backup.py
  install -m 0755 -o root -g root "$DEPLOY/scripts/run-sidecar.sh" /usr/local/lib/mutis/run-sidecar.sh
  install -m 0755 -o root -g root "$DEPLOY/scripts/mutis-admin" /usr/local/sbin/mutis-admin
  install -m 0640 -o root -g mutis "$DEPLOY/ootle/walletd-log4rs.yml" /etc/mutis/walletd-log4rs.yml
  local unit
  for unit in "$DEPLOY"/systemd/*.service "$DEPLOY"/systemd/*.timer "$DEPLOY"/systemd/*.mount; do
    install_kept 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
  done
  install -d -m 0755 /etc/systemd/system/caddy.service.d /etc/systemd/journald.conf.d
  install_kept 0644 "$DEPLOY/systemd/caddy.service.d/mutis.conf" /etc/systemd/system/caddy.service.d/mutis.conf
  if ! cmp -s "$DEPLOY/journald/mutis.conf" /etc/systemd/journald.conf.d/mutis.conf; then
    install_kept 0644 "$DEPLOY/journald/mutis.conf" /etc/systemd/journald.conf.d/mutis.conf
    systemctl restart systemd-journald
  fi
  systemctl daemon-reload
  echo "ok"
}

data_mount() {
  step "the data directory: noexec, nosuid, nodev (srv-mutis-data.mount)"
  systemctl enable --now srv-mutis-data.mount >/dev/null 2>&1 || die "srv-mutis-data.mount did not start (journalctl -u srv-mutis-data.mount)"
  local opts
  opts=$(findmnt -n -o OPTIONS --target /srv/mutis/data)
  for flag in noexec nosuid nodev; do
    [[ ,$opts, == *,$flag,* ]] || die "/srv/mutis/data is mounted without $flag ($opts)"
  done
  echo "ok: $(findmnt -n -o TARGET,OPTIONS --target /srv/mutis/data)"
}

status_mount() {
  step "the status directory: nosymfollow, noexec, nosuid, nodev (srv-mutis-status.mount)"
  systemctl enable --now srv-mutis-status.mount >/dev/null 2>&1 || die "srv-mutis-status.mount did not start (journalctl -u srv-mutis-status.mount)"
  local opts
  opts=$(findmnt -n -o OPTIONS --target /srv/mutis/status)
  for flag in nosymfollow noexec nosuid nodev; do
    [[ ,$opts, == *,$flag,* ]] || die "/srv/mutis/status is mounted without $flag ($opts)"
  done
  echo "ok: $(findmnt -n -o TARGET,OPTIONS --target /srv/mutis/status)"
}

kernel_settings() {
  step "kernel settings (/etc/sysctl.d/90-mutis.conf)"
  local target=/etc/sysctl.d/90-mutis.conf
  if ! cmp -s "$DEPLOY/sysctl/90-mutis.conf" "$target"; then
    local keys
    keys=$(grep -E '^[a-z]' "$DEPLOY/sysctl/90-mutis.conf" | cut -d= -f1 | tr -d ' ' | grep -v '\*' | sort -u)
    (umask 077 && install -d -m 0700 "$BACKUPS" && sysctl $keys > "$BACKUPS/sysctl-before.$RUN_STAMP.txt" 2>&1 || true)
    echo "  the values before: $BACKUPS/sysctl-before.$RUN_STAMP.txt"
    install_kept 0644 "$DEPLOY/sysctl/90-mutis.conf" "$target"
  fi
  /usr/lib/systemd/systemd-sysctl "$target" || die "systemd-sysctl $target failed"
  echo "ok: $(grep -cE '^[a-z]' "$target") settings applied"
}

restart_notice() {
  local unit active=()
  for unit in "${CHANGED_UNITS[@]}"; do
    case $unit in caddy.service) ;; *.service) systemctl is-active --quiet "$unit" && active+=("${unit%.service}") ;; esac
  done
  [ ${#active[@]} -eq 0 ] ||
    echo "notice: these running units have a new definition; restart them to apply it: ${active[*]}"
}

firewall() {
  step "ufw: web ports open, logging off, loopback ports guarded by owner"
  ufw status | grep -q '^Status: active' ||
    die "ufw is inactive: allow your SSH port first (ufw limit 22/tcp), then ufw enable, and run this again"
  ufw allow 80/tcp comment 'mutis http' >/dev/null
  ufw allow 443/tcp comment 'mutis https' >/dev/null
  ufw logging off >/dev/null
  local f guard changed=0 op drive
  # Owner-match guards on loopback, before ufw's loopback ACCEPT: the listed uids connect, everyone
  # else gets a TCP reset. 5100: walletd runs with --authentication none, so whoever reaches it could
  # spend. 18143: an L1 console wallet's gRPC (if one runs), no authentication either. 8787: mutis-api
  # trusts X-Real-IP from loopback; only Caddy (which sets it), the chain worker's sidecar (drive, the
  # canary), root and the operator may connect, so `build`, which runs third-party build scripts when
  # it compiles, can't forge client addresses past the per-IP limits.
  op=$(id -u "$OPERATOR")
  drive=$(id -u drive)
  local guards=("5100 0 $op $drive" "18143 0 $op $drive" "8787 0 $op $drive $(id -u caddy)")
  for f in /etc/ufw/before.rules /etc/ufw/before6.rules; do
    grep -qE -- '^-A ufw6?-before-output -o lo -j ACCEPT$' "$f" || die "$f has no loopback ACCEPT line to guard"
    for guard in "${guards[@]}"; do
      if ! grep -q -- "--dport ${guard%% *} -j REJECT" "$f"; then
        [ -e "$f.bak-mutis" ] || cp -p "$f" "$f.bak-mutis"
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
        changed=1
      fi
    done
  done
  [ "$changed" = 0 ] || ufw reload >/dev/null
  ufw status | grep -E '^(80|443|22)/tcp ' | sed 's/^/  /'
}

caddy_site() {
  step "Caddy"
  [ -e /etc/caddy/Caddyfile.debian ] || cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.debian
  (set -a && . /etc/mutis/caddy.env && caddy validate --config "$DEPLOY/caddy/Caddyfile" --adapter caddyfile >/dev/null 2>&1) ||
    die "caddy validate failed: run it by hand to see why"
  install_kept 0644 "$DEPLOY/caddy/Caddyfile" /etc/caddy/Caddyfile
  systemctl enable caddy >/dev/null 2>&1
  if [ -S /run/caddy/admin.sock ] && [[ " ${CHANGED_UNITS[*]} " != *" caddy.service "* ]]; then
    systemctl reload caddy
  else
    # The first switch from the TCP admin port to the socket, or a new sandbox in the drop-in.
    systemctl restart caddy
  fi
  sleep 1
  systemctl is-active --quiet caddy ||
    die "caddy is not running (journalctl -u caddy); the files it replaced are in $BACKUPS (*.$RUN_STAMP)"
  echo "ok: $(systemctl is-active caddy)"
}

walletd_balances() {  # stdin, so drive needs no access to this copy of deploy/
  runuser -u drive -- python3 -I - balances < "$DEPLOY/ootle/walletd-rpc.py"
}

walletd_listening() {
  local i
  for i in $(seq 1 90); do
    if (exec 3<>/dev/tcp/127.0.0.1/5100) 2>/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

walletd_service() {
  step "walletd as a systemd unit"
  if [ ! -f "$CREDENTIAL" ]; then
    echo "skipped: walletd isn't set up (no $WALLET/.keyring-pass; docs/self-host.md step 4); chain features stay off"
    return
  fi
  if systemctl is-active --quiet walletd; then
    systemctl enable walletd >/dev/null 2>&1
    echo "ok: walletd.service already active"
    return
  fi
  local ts before after
  ts=$(stamp)
  if runuser -u drive -- tmux has-session -t walletd 2>/dev/null; then
    (umask 077
     walletd_balances > "$BACKUPS/balances-$ts-before.json"
     tar -C /home/drive -cf "$BACKUPS/wallet-$ts-live.tar" wallet)
    echo "backed up $WALLET (live) to $BACKUPS/wallet-$ts-live.tar"
    runuser -u drive -- tmux send-keys -t walletd C-c
    for _ in $(seq 1 60); do
      pgrep -u drive -f "tari_ootle_walletd .*--base-path $WALLET " >/dev/null || break
      sleep 1
    done
    if pgrep -u drive -f "tari_ootle_walletd .*--base-path $WALLET " >/dev/null; then
      runuser -u drive -- tmux kill-session -t walletd || true
      sleep 5
    fi
    pgrep -u drive -f "tari_ootle_walletd .*--base-path $WALLET " >/dev/null && die "the tmux walletd did not stop"
    runuser -u drive -- tmux kill-session -t walletd 2>/dev/null || true
    (umask 077 && tar -C /home/drive -cf "$BACKUPS/wallet-$ts-cold.tar" wallet)
    echo "stopped the tmux walletd; cold backup at $BACKUPS/wallet-$ts-cold.tar"
  fi
  systemctl enable --now walletd >/dev/null 2>&1
  if ! walletd_listening; then
    systemctl disable --now walletd >/dev/null 2>&1
    if [ -f "$BACKUPS/balances-$ts-before.json" ]; then   # this run stopped the tmux walletd
      runuser -u drive -- tmux new-session -d -s walletd "$WALLET/run-walletd.sh"
      die "walletd.service did not come up (journalctl -u walletd); the tmux session is running again"
    fi
    die "walletd.service did not come up (journalctl -u walletd)"
  fi
  if [ -f "$BACKUPS/balances-$ts-before.json" ]; then
    (umask 077 && walletd_balances > "$BACKUPS/balances-$ts-after.json")
    before=$(sha256sum < "$BACKUPS/balances-$ts-before.json")
    after=$(sha256sum < "$BACKUPS/balances-$ts-after.json")
    [ "$before" = "$after" ] || die "balances differ after the move: compare $BACKUPS/balances-$ts-{before,after}.json"
    echo "ok: walletd.service active; every account balance unchanged"
  else
    echo "ok: walletd.service active"
  fi
}

timers() {
  step "timers that don't need the API: wallet backups always, database backups once a database exists"
  systemctl enable --now mutis-backup-wallet.timer >/dev/null 2>&1
  if [ -f /srv/mutis/data/db/mutis.sqlite3 ]; then
    systemctl enable --now mutis-backup.timer >/dev/null 2>&1
  fi
  systemctl list-timers 'mutis-*' --no-pager | sed -n '1,4p' | sed 's/^/  /'
}

keys() {
  step "receiver and robot-locker keys"
  local sidecar
  sidecar=$(readlink -f /srv/mutis/app/current/sidecar || true)   # Node's permission model wants the real path
  if [ -n "$sidecar" ] && [ -f "$sidecar/sidecar.mjs" ]; then
    runuser -u drive -- bash -s -- "$sidecar" < "$DEPLOY/scripts/init-keys.sh"
  else
    echo "skipped: no release deployed yet (deploy.sh runs this step after the first release)"
  fi
}

check_packages
users_and_dirs
config_and_secrets
install_files
data_mount
status_mount
kernel_settings
firewall
caddy_site
walletd_service
timers
keys
restart_notice
step "privilege self-test (spec §15.1 step 9)"
bash "$DEPLOY/scripts/privilege-check.sh"
