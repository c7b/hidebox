#!/bin/bash
# SPDX-License-Identifier: MIT
# Dry run of deploy/scripts/provision.sh on a simulated fresh Debian 13 server, following
# docs/self-host.md steps 1-4. Usage: dryrun.sh <repo checkout> <fake root> <dir with Debian's ufw
# before.rules and before6.rules, as the ufw package installs them>
set -u
SRC=$1; R=$2; UFW=$3; S=$(dirname "$(readlink -f "$0")")/stubs
# What Debian and its caddy package leave in place.
rm -rf "$R"; mkdir -p "$R"/etc/ufw "$R"/etc/caddy "$R"/etc/systemd/system "$R"/home "$R"/work
cp "$UFW/before.rules" "$UFW/before6.rules" "$R/etc/ufw/"
echo "# Debian's default" > "$R/etc/caddy/Caddyfile"
printf 'root:0:root\ncaddy:999:caddy\nalice:1000:alice,sudo\n' > "$R/fake-passwd"
: > "$R/actions.log"
cp -r "$SRC/deploy" "$R/work/deploy"
p=$R/work/deploy/scripts/provision.sh
sed -i -e "s#/etc/#$R/etc/#g" -e "s#/srv/mutis#$R/srv/mutis#g" -e "s#/home/#$R/home/#g" \
  -e "s#/var/backups#$R/var/backups#g" -e "s#/usr/local/#$R/usr/local/#g" \
  -e 's#^bash "\$DEPLOY/scripts/privilege-check.sh"$#echo "(dry run: privilege-check.sh is not run)"#' "$p"
mkdir -p "$R/usr/local/sbin"
run() { env -i HOME=/root PATH="$S:/usr/bin:/bin" DRY_ROOT="$R" SUDO_USER=alice "$@" bash "$p"; }
echo "### step 2: the config, public_origin set"
install -d "$R/etc/mutis" && sed 's#^public_origin = .*#public_origin = "https://drive.example.org"#' \
  "$SRC/deploy/config/mutis.toml.example" > "$R/etc/mutis/mutis.toml"
echo "### step 3: provision without walletd"
run; echo "exit $?"
echo "### step 4: walletd initialised as drive, provision again"
printf 'k%.0s' $(seq 40) > "$R/home/drive/wallet/.keyring-pass"
run DRY_WALLETD=active; echo "exit $?"
echo "### refusals: ufw inactive, then no operator"
run DRY_UFW=inactive 2>&1 | grep '^provision:'
env -i HOME=/root PATH="$S:/usr/bin:/bin" DRY_ROOT="$R" bash "$p" 2>&1 | grep '^provision:'
echo "### the guards it left, before ufw's loopback ACCEPT"
grep -E -- '--dport (5100|18143|8787) |-o lo -j ACCEPT$' "$R/etc/ufw/before.rules" "$R/etc/ufw/before6.rules"
echo "### accounts"
cat "$R/fake-passwd"
