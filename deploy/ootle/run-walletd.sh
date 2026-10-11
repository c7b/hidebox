#!/bin/bash
# SPDX-License-Identifier: MIT
# Starts the official Ootle wallet daemon (Esmeralda testnet) for walletd.service, as `drive`.
#
# walletd needs its keyring password on every start. Passed as --override-keyring-password it would
# sit in the process list where every local user can read it, so systemd hands it to this script as a
# credential (LoadCredential, from a root-only file) and the script gives it to walletd through a
# private copy of walletd's config file in $RUNTIME_DIRECTORY (0700, tmpfs, removed on stop). Only
# bash builtins touch the password, so it never appears in any command line either.
#
# auth=none: any local process that reaches 127.0.0.1:5100 could spend, so the port is limited to
# uids 0, 1000 and 1002 by owner-match rules in /etc/ufw/before.rules and before6.rules.
#
# WALLETD_BASE, WALLETD_LISTEN and WALLETD_BIN exist for the upgrade drill, which runs a new binary
# against a copy of the data directory (deploy/ootle/upgrade-drill.md).
set -euo pipefail

base=${WALLETD_BASE:-/home/drive/wallet}
listen=${WALLETD_LISTEN:-127.0.0.1:5100}
bin=${WALLETD_BIN:-/opt/tari/bin/tari_ootle_walletd}
log_config=${WALLETD_LOG_CONFIG:-/etc/mutis/walletd-log4rs.yml}
source_config="$base/esmeralda/config/config.toml"
runtime_config="$RUNTIME_DIRECTORY/config.toml"
section='[esmeralda.ootle_wallet_daemon]'

pass=$(<"$CREDENTIALS_DIRECTORY/keyring-pass")
pass=${pass%$'\n'}
if [[ ! $pass =~ ^[A-Za-z0-9+/=_.-]{16,128}$ ]]; then
  echo "walletd: the keyring password credential has an unexpected format" >&2
  exit 1
fi

# walletd 0.45 reads this setting as bytes (a TOML array of integers), not as a string.
bytes=()
for ((i = 0; i < ${#pass}; i++)); do
  printf -v code '%d' "'${pass:i:1}"
  bytes+=("$code")
done
unset pass
umask 077
inserted=0
while IFS= read -r line || [[ -n $line ]]; do
  printf '%s\n' "$line"
  if [[ $line == "$section" ]]; then
    (IFS=,; printf 'override_keyring_password = [%s]\n' "${bytes[*]}")
    inserted=1
  fi
done < "$source_config" > "$runtime_config"
unset bytes
if (( ! inserted )); then
  echo "walletd: $source_config has no $section table" >&2
  exit 1
fi

cd "$base"
exec "$bin" --network esme --base-path "$base" --config "$runtime_config" --log-config "$log_config" \
  --listen-on "$listen" --authentication none run
