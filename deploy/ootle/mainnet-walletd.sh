#!/bin/bash
# SPDX-License-Identifier: MIT
# The mainnet walletd of an instance (deploy/scripts/instance.py), as root on the server, from a copy of deploy/:
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/mainnet-walletd.sh install <tari_ootle_walletd 0.50+ binary> <sha256>
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/mainnet-walletd.sh setup     the accounts, offline; prints their keys
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/mainnet-walletd.sh keys      the keys again (the burn targets)
#   sudo MUTIS_INSTANCE=<name> bash deploy/ootle/mainnet-walletd.sh backup    the seed words and a cold copy, root only
# install copies a checked binary into /usr/local/lib/mutis-<name>/ and points tari_ootle_walletd-mainnet at it.
# setup writes the wallet's config ([mainnet.ootle_wallet_daemon], the preset's two Tari-run indexers) and creates
# `service` (key 0, the default account: it publishes SealLog, owns the log and pays for checkpoints) and
# `sponsor` (key 1: relay sends, decoys, the canary) with walletd's offline create-account, inside the same
# sandbox and with the same keyring password credential as mutis-<name>-walletd-mainnet.service; the daemon must be
# stopped. It creates no funds and sends nothing; the seed is new and only on this server. backup stops nothing it
# didn't start: it refuses while the daemon runs, writes the seed words (walletd seed-words) to
# /var/backups/mutis-<name>/walletd-mainnet-seed-words.txt (root, 0400) and a tar of the wallet directory with
# the keyring password beside it (root, 0600), like the testnet wallet's root-only copies (provision.sh).
# Burn to the `account_public_key` this prints: 64 hex characters, not an otl_ address (burn-guard.py checks).
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
die() { echo "mainnet-walletd: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
eval "$(python3 -I "$here/../scripts/instance.py" env "${MUTIS_INSTANCE:-}")"
[ -n "$MUTIS_INSTANCE" ] || die "MUTIS_INSTANCE names no instance (production's walletd stays on Esmeralda)"
network=mainnet
unit=mutis-$MUTIS_INSTANCE-walletd-$network
base=$INST_DRIVE_HOME/wallet-$network
bin=$INST_LIB/tari_ootle_walletd-$network
port=$(sed -n "s/^walletd=$network://p" "$INST_ETC/instance.conf")
[ -n "$port" ] || die "$INST_ETC/instance.conf names no $network walletd (provision-instance.sh --walletd $network:PORT)"
config=$base/$network/config/config.toml

oneoff() {  # a walletd subcommand in the daemon's sandbox, with its credential; stdout is the command's
  systemctl is-active --quiet "$unit" && die "stop $unit first (the offline commands open its database)"
  systemd-run --quiet --wait --pipe --collect --service-type=exec \
    --uid="$INST_DRIVE_USER" --gid="$INST_DRIVE_USER" \
    -p LoadCredential="keyring-pass:$INST_ETC/credentials/walletd-$network-keyring-pass" \
    -p RuntimeDirectory="$unit-oneoff" -p RuntimeDirectoryMode=0700 -p UMask=0077 \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=tmpfs -p BindPaths="$base" -p PrivateTmp=yes \
    -p PrivateDevices=yes -p InaccessiblePaths="-/srv/mutis -$INST_SRV -/etc/mutis -$INST_ETC/secret.key -$INST_CONFIG" \
    -E WALLETD_NETWORK=$network -E WALLETD_BASE="$base" -E WALLETD_LISTEN="127.0.0.1:$port" \
    -E WALLETD_LOG_CONFIG="$INST_ETC/walletd-log4rs.yml" -E WALLETD_BIN="$bin" \
    "$INST_LIB/run-walletd.sh" "$@"
}

keys() {
  local name
  for name in service sponsor; do
    [ -f "$base/account-$name.json" ] || die "no $base/account-$name.json: run setup"
    python3 -I - "$base/account-$name.json" "$name" <<'PY'
import json, re, sys
a = json.load(open(sys.argv[1]))
key = a["account_public_key"]
assert re.fullmatch(r"[0-9a-f]{64}", key), "unexpected account_public_key"
print(f"{sys.argv[2]:8} burn to (Claim Public Key): {key}")
print(f"{'':8} component {a['component_address']}")
print(f"{'':8} address   {a['address']}")
PY
  done
}

case ${1:-} in
  install)
    src=${2:?give the walletd binary} sum=${3:?give its sha256}
    [ "$(sha256sum "$src" | cut -d' ' -f1)" = "$sum" ] || die "$src does not have sha256 $sum"
    version=$("$src" --version | awk '{print $2}')
    [[ $version =~ ^0\.([5-9][0-9]|[1-9][0-9][0-9])\. ]] || die "walletd $version: the mainnet needs 0.50 or later"
    target=$INST_LIB/tari_ootle_walletd-$version-${sum:0:7}
    install -m 0755 -o root -g root "$src" "$target"
    ln -sfn "$target" "$bin"
    echo "mainnet-walletd: $bin → $target ($("$bin" --version))"
    ;;
  setup)
    [ -x "$bin" ] || die "no walletd at $bin: run install first"
    install -d -m 0700 -o "$INST_DRIVE_USER" -g "$INST_DRIVE_USER" "$base" "$base/$network" "$base/$network/config"
    if [ ! -f "$config" ]; then
      printf '%s\n' "# walletd for instance $MUTIS_INSTANCE on the Ootle mainnet (deploy/ootle/mainnet-walletd.sh); walletd's presets fill the rest." \
        "[$network.ootle_wallet_daemon]" 'indexer_api_url = ["https://indexer-a.ootle.tari.com/", "https://indexer-b.ootle.tari.com/"]' > "$config"
      chown "$INST_DRIVE_USER:$INST_DRIVE_USER" "$config" && chmod 0600 "$config"
    fi
    for spec in service:0 sponsor:1; do
      name=${spec%%:*} index=${spec#*:}
      out=$base/account-$name.json
      if [ -f "$out" ]; then echo "mainnet-walletd: $name exists ($out)"; continue; fi
      extra=()
      [ "$name" = service ] && extra=(--set-active)
      oneoff create-account --name "$name" --key-index "$index" "${extra[@]}" --output "$out" >/dev/null
      chmod 0600 "$out"
      echo "mainnet-walletd: created $name (key index $index)"
    done
    keys
    echo "mainnet-walletd: now run backup, then: systemctl enable --now $unit"
    ;;
  keys) keys ;;
  backup)
    install -d -m 0700 -o root -g root "$INST_BACKUPS"
    words=$INST_BACKUPS/walletd-$network-seed-words.txt
    if [ ! -s "$words" ]; then
      # walletd's log lines share stdout with the words: keep only the line of words.
      (umask 077 && oneoff seed-words | grep -E '^[a-z]+( [a-z]+){11,}$' > "$words.new") || true
      [ "$(grep -c . "$words.new")" = 1 ] && [ "$(wc -w < "$words.new")" -ge 12 ] ||
        { rm -f "$words.new"; die "seed-words gave no single line of words"; }
      chmod 0400 "$words.new" && mv "$words.new" "$words"
      echo "mainnet-walletd: seed words in $words (root, 0400): $(wc -w < "$words") words"
    else
      echo "mainnet-walletd: $words exists"
    fi
    systemctl is-active --quiet "$unit" && die "stop $unit for the cold copy"
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    tarball=$INST_BACKUPS/wallet-$network-$stamp.tar
    (umask 077 && tar -C "$INST_DRIVE_HOME" -cf "$tarball" "wallet-$network" &&
      cp "$INST_ETC/credentials/walletd-$network-keyring-pass" "$INST_BACKUPS/walletd-$network-keyring-pass.$stamp")
    echo "mainnet-walletd: cold copy $tarball and its keyring password beside it (root, 0600)"
    ;;
  *) die "usage: mainnet-walletd.sh install <binary> <sha256> | setup | keys | backup" ;;
esac
