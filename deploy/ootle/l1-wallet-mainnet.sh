#!/bin/bash
# SPDX-License-Identifier: MIT
# The Minotari (L1) console wallet for an instance's mainnet burns, as root on the server:
#   sudo bash deploy/ootle/l1-wallet-mainnet.sh install                     the official mainnet build, checksum-checked
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/l1-wallet-mainnet.sh create   first start: the seed, backed up root-only
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/l1-wallet-mainnet.sh start    the wallet as a service (non-interactive)
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/l1-wallet-mainnet.sh address  its receive address (base58 and emoji)
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/l1-wallet-mainnet.sh tui      stop the service, open the TUI here (burns)
# install fetches tari_suite-$VERSION-mainnet (the L1 releases are built per network; the testnet wallet in
# /opt/tari/l1 is the Esmeralda build) and accepts it only when the zip's SHA-256 is the pinned one below and the
# release's .sha256 file, its sha256-unsigned.txt and GitHub's asset digest all say the same.
# The wallet runs as drive-<name> with its own data directory (/home/drive-<name>/l1wallet-mainnet). Its password
# is handled like walletd's keyring password: a random one in /etc/mutis-<name>/credentials/l1wallet-mainnet-pass
# (root, 0600), handed over as a systemd credential and only ever in the wallet process's environment. create runs
# the first start in that sandbox, which makes the wallet and writes its seed words once; they go to
# /var/backups/mutis-<name>/l1wallet-mainnet-seed-words.txt (root, 0400), beside walletd's, and the copy the wallet
# wrote is overwritten and removed. Burn proofs go straight into the directory the instance's mainnet walletd claims
# from (~/.local/share/tari/mainnet/burn_proofs). In non-interactive mode the wallet only stays up with its gRPC
# server on, so the service listens on 127.0.0.1:$GRPC_PORT, which an owner-match guard in ufw (as for walletd)
# leaves to drive-<name>, root and the operator. Nothing here burns or sends: deploy/ootle/l1-burn.py makes the burns
# through that gRPC once deploy/ootle/burn-guard.py says yes (the TUI, `tui`, is the by-hand fallback).
set -euo pipefail

VERSION=6.2.0
COMMIT=1fe8cff
ZIP_SHA256=19201c22b1f93eba4269adc8a02d6e8885f139eaf27e9fb9c2eaf645db2d5a66
GRPC_PORT=18153           # not 18143, the testnet L1 wallet's
OPERATOR=${MUTIS_OPERATOR:-${SUDO_USER:-}}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
die() { echo "l1-wallet-mainnet: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
target=/opt/tari/l1-mainnet-$VERSION

instance() {
  eval "$(python3 -I "$here/../scripts/instance.py" env "${MUTIS_INSTANCE:-}")"
  [ -n "$MUTIS_INSTANCE" ] || die "MUTIS_INSTANCE names no instance"
  [ -x "$target/minotari_console_wallet" ] || die "run install first"
  dir=$INST_DRIVE_HOME/l1wallet-mainnet
  proofs=$INST_DRIVE_HOME/.local/share/tari/mainnet/burn_proofs
  cred=$INST_ETC/credentials/l1wallet-mainnet-pass
  unit=mutis-$MUTIS_INSTANCE-l1wallet-mainnet
  run=$INST_LIB/run-l1wallet-mainnet.sh
}

prepare() {
  install -d -m 0700 -o "$INST_DRIVE_USER" -g "$INST_DRIVE_USER" "$dir" "$INST_DRIVE_HOME/.local/share/tari/mainnet" "$proofs"
  if [ ! -f "$cred" ]; then
    [ -d "$dir/mainnet" ] && die "$dir already holds a wallet but $cred is missing: restore the password, don't make one"
    (umask 077 && head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' > "$cred.new" && mv "$cred.new" "$cred")
    echo "l1-wallet-mainnet: generated $cred (root only; the wallet gets it as a systemd credential)"
  fi
  rm -f "$dir/.pass" "$dir/run-l1wallet.sh"                    # the first layout kept them in the wallet's home
  cat > "$run.new" <<RUN
#!/bin/bash
# The official Minotari (L1) console wallet, Tari MAINNET $VERSION, for instance $MUTIS_INSTANCE's burns only
# (deploy/ootle/l1-wallet-mainnet.sh). The password arrives as the systemd credential wallet-pass and lives only in
# this process's environment. Arguments pass through (--non-interactive-mode for the service; none for the TUI).
set -euo pipefail
pass=\$(<"\$CREDENTIALS_DIRECTORY/wallet-pass")
export MINOTARI_WALLET_PASSWORD=\${pass%\$'\\n'}
unset pass
cd "$dir"
exec $target/minotari_console_wallet --network mainnet -b "$dir" --burn-proof-out "$proofs" "\$@"
RUN
  install -m 0755 -o root -g root "$run.new" "$run" && rm -f "$run.new"
  cat > "/etc/systemd/system/$unit.service" <<UNIT
# SPDX-License-Identifier: MIT
# The Minotari mainnet console wallet of mutis-$MUTIS_INSTANCE, non-interactive (deploy/ootle/l1-wallet-mainnet.sh).
# It only follows the chain: XTM sent to it arrives while it runs. Burns are made in its TUI (l1-wallet-mainnet.sh tui).
[Unit]
Description=Minotari mainnet console wallet for mutis-$MUTIS_INSTANCE (burns only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$INST_DRIVE_USER
Group=$INST_DRIVE_USER
LoadCredential=wallet-pass:$cred
ExecStart=$run --non-interactive-mode --grpc-enabled --grpc-address /ip4/127.0.0.1/tcp/$GRPC_PORT
Restart=on-failure
RestartSec=30
TimeoutStopSec=60
KillSignal=SIGINT
SyslogIdentifier=$unit

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=tmpfs
BindPaths=$dir $INST_DRIVE_HOME/.local/share/tari
InaccessiblePaths=-/srv/mutis -$INST_SRV -/etc/mutis -$INST_ETC/secret.key -$INST_CONFIG
NoExecPaths=/tmp /var/tmp /dev/shm $dir $INST_DRIVE_HOME/.local/share/tari
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
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=
RemoveIPC=yes
UMask=0077
MemoryMax=1G
TasksMax=256

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
}

guard() {  # the owner-match guard on 127.0.0.1:$GRPC_PORT (provision.sh's rule shape), before ufw's loopback ACCEPT
  local f changed=0 op
  [ -n "$OPERATOR" ] && [ "$OPERATOR" != root ] || die "run it with sudo from your own login, or set MUTIS_OPERATOR"
  op=$(id -u "$OPERATOR")
  for f in /etc/ufw/before.rules /etc/ufw/before6.rules; do
    grep -q -- "--dport $GRPC_PORT -j REJECT" "$f" && continue
    grep -qE -- '^-A ufw6?-before-output -o lo -j ACCEPT$' "$f" || die "$f has no loopback ACCEPT line to guard"
    [ -e "$f.bak-mutis-$MUTIS_INSTANCE-l1" ] || cp -p "$f" "$f.bak-mutis-$MUTIS_INSTANCE-l1"
    python3 -I - "$f" "$GRPC_PORT" 0 "$op" "$(id -u "$INST_DRIVE_USER")" <<'PY'
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
  done
  [ "$changed" = 0 ] || { ufw reload >/dev/null; echo "l1-wallet-mainnet: guarded 127.0.0.1:$GRPC_PORT in ufw"; }
}

oneoff() {  # the wallet in the service's sandbox, with its credential, attached to this terminal or pipe
  local mode=$1
  shift
  systemd-run --quiet --wait --collect --service-type=exec "$mode" \
    --uid="$INST_DRIVE_USER" --gid="$INST_DRIVE_USER" -p LoadCredential="wallet-pass:$cred" \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=tmpfs \
    -p BindPaths="$dir $INST_DRIVE_HOME/.local/share/tari" -p PrivateTmp=yes -p UMask=0077 \
    -p InaccessiblePaths="-/srv/mutis -$INST_SRV -/etc/mutis -$INST_ETC/secret.key -$INST_CONFIG" \
    "$run" "$@"
}

case ${1:-} in
  install)
    if [ -x "$target/minotari_console_wallet" ]; then
      echo "l1-wallet-mainnet: $target/minotari_console_wallet is there ($("$target/minotari_console_wallet" --version 2>/dev/null | head -n 1))"
      exit 0
    fi
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    zip=tari_suite-$VERSION-mainnet-$COMMIT-linux-x86_64.zip
    url=https://github.com/tari-project/tari/releases/download/v$VERSION
    curl -sSfL -o "$work/$zip" "$url/$zip"
    curl -sSfL -o "$work/$zip.sha256" "$url/$zip.sha256"
    curl -sSfL -o "$work/unsigned.txt" "$url/tari_suite-$VERSION.sha256-unsigned.txt"
    digest=$(curl -sSfL "https://api.github.com/repos/tari-project/tari/releases/tags/v$VERSION" |
      python3 -I -c 'import json, sys; print(next(a["digest"] for a in json.load(sys.stdin)["assets"] if a["name"] == sys.argv[1]))' "$zip")
    got=$(sha256sum "$work/$zip" | cut -d' ' -f1)
    [ "$got" = "$ZIP_SHA256" ] || die "$zip has sha256 $got, not the pinned $ZIP_SHA256"
    grep -q "^$ZIP_SHA256  $zip\$" "$work/$zip.sha256" || die "$zip.sha256 disagrees"
    grep -q "^$ZIP_SHA256  $zip\$" "$work/unsigned.txt" || die "sha256-unsigned.txt disagrees"
    [ "$digest" = "sha256:$ZIP_SHA256" ] || die "GitHub's asset digest disagrees ($digest)"
    install -d -m 0755 -o root -g root "$target"
    python3 -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("minotari_console_wallet", sys.argv[2])' \
      "$work/$zip" "$work/x"
    install -m 0755 -o root -g root "$work/x/minotari_console_wallet" "$target/minotari_console_wallet"
    echo "l1-wallet-mainnet: installed $target/minotari_console_wallet ($("$target/minotari_console_wallet" --version 2>/dev/null | head -n 1))"
    ;;
  prepare)
    instance
    prepare
    echo "l1-wallet-mainnet: ready: $run, $unit.service; next: create"
    ;;
  create)
    instance
    prepare
    words=$INST_BACKUPS/l1wallet-mainnet-seed-words.txt
    [ -e "$dir/mainnet" ] && [ -s "$words" ] && { echo "l1-wallet-mainnet: the wallet exists and its seed is backed up"; exit 0; }
    [ -e "$dir/mainnet" ] && die "$dir/mainnet exists but $words doesn't: back the seed up by hand from the TUI"
    systemctl is-active --quiet "$unit" && die "stop $unit first"
    seedfile=$dir/.seed-words-once.txt
    oneoff --pipe --non-interactive-mode --seed-words-file-name "$seedfile" --command get-balance --command-mode-auto-exit \
      > "$INST_BACKUPS/l1wallet-mainnet-first-start.log" 2>&1 || true
    chmod 0600 "$INST_BACKUPS/l1wallet-mainnet-first-start.log"
    [ -s "$seedfile" ] || die "the first start wrote no seed words (see $INST_BACKUPS/l1wallet-mainnet-first-start.log)"
    install -d -m 0700 -o root -g root "$INST_BACKUPS"
    (umask 077 && grep -oE '[a-z]+( [a-z]+){11,}' "$seedfile" | head -n 1 > "$words.new")
    [ "$(wc -w < "$words.new")" -ge 12 ] || { rm -f "$words.new"; die "the seed file holds no line of words"; }
    chmod 0400 "$words.new" && mv "$words.new" "$words"
    shred -u "$seedfile" 2>/dev/null || rm -f "$seedfile"
    echo "l1-wallet-mainnet: wallet created; its seed words are in $words (root, 0400): $(wc -w < "$words") words"
    ;;
  start)
    instance
    [ -e "$dir/mainnet" ] || die "no wallet yet: run create"
    guard
    systemctl enable --now "$unit" >/dev/null 2>&1
    sleep 5
    systemctl is-active "$unit"
    ;;
  address)
    # The wallet prints its address only in the TUI: draw it in a pseudo-terminal for half a minute, read the
    # base58 address off the screen, check its DammSum and network byte, and show its emoji form too.
    instance
    was=$(systemctl is-active "$unit" 2>/dev/null || true)
    [ "$was" = active ] && systemctl stop "$unit"
    python3 -I "$here/l1-address.py" -- systemd-run --quiet --wait --collect --pty --uid="$INST_DRIVE_USER" \
      --gid="$INST_DRIVE_USER" -p LoadCredential="wallet-pass:$cred" -p ProtectHome=tmpfs \
      -p BindPaths="$dir $INST_DRIVE_HOME/.local/share/tari" -p PrivateTmp=yes "$run" || true
    [ "$was" = active ] && systemctl start "$unit"
    ;;
  tui)
    instance
    was=$(systemctl is-active "$unit" 2>/dev/null || true)
    [ "$was" = active ] && systemctl stop "$unit"
    oneoff --pty || true
    [ "$was" = active ] && systemctl start "$unit"
    ;;
  *) die "usage: l1-wallet-mainnet.sh install | prepare | create | start | address | tui" ;;
esac
