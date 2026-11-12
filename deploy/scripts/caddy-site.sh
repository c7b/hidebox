#!/bin/bash
# SPDX-License-Identifier: MIT
# The Caddy site of an instance beside production (deploy/scripts/instance.py), as root:
#   MUTIS_INSTANCE=<name> bash caddy-site.sh <release dir> [--check]
# Renders /etc/caddy/mutis.d/<name>.caddy from the release's deploy/caddy/Caddyfile and the instance's
# mutis.toml, then validates the whole live configuration with it inside: production's own /etc/caddy/Caddyfile
# (read, never written) importing a copy of /etc/caddy/mutis.d with the new site in it. Only a configuration that
# validates replaces the old site (kept in /var/backups/mutis-<name>), and Caddy reloads. --check stops after
# the validation. activate-release.sh and rollback.sh call it; nothing else in /etc/caddy changes.
set -euo pipefail

dir=${1:?give the release directory}
check=${2:-}
die() { echo "caddy-site: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
eval "$(python3 -I "$dir/deploy/scripts/instance.py" env "${MUTIS_INSTANCE:-}")"
[ -n "$MUTIS_INSTANCE" ] || die "MUTIS_INSTANCE names no instance; production's site is /etc/caddy/Caddyfile"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
python3 -I "$dir/deploy/scripts/instance.py" caddy "$MUTIS_INSTANCE" "$INST_CONFIG" "$work/site.caddy" >/dev/null
if [ -z "$check" ] && cmp -s "$work/site.caddy" "$INST_CADDY_SITE"; then
  echo "caddy: $INST_CADDY_SITE unchanged"
  exit 0
fi

mkdir "$work/mutis.d"
for f in /etc/caddy/mutis.d/*.caddy; do
  [ -e "$f" ] && [ "$f" != "$INST_CADDY_SITE" ] && cp -p "$f" "$work/mutis.d/"
done
cp "$work/site.caddy" "$work/mutis.d/$(basename "$INST_CADDY_SITE")"
sed "s#^import /etc/caddy/mutis\.d/\*\.caddy\$#import $work/mutis.d/*.caddy#" /etc/caddy/Caddyfile > "$work/Caddyfile"
grep -qF "import $work/mutis.d/*.caddy" "$work/Caddyfile" ||
  die "/etc/caddy/Caddyfile has no 'import /etc/caddy/mutis.d/*.caddy' line to put the site in"
if ! (set -a && . /etc/mutis/caddy.env && caddy validate --config "$work/Caddyfile" --adapter caddyfile) >"$work/validate.log" 2>&1; then
  tail -n 20 "$work/validate.log" >&2
  die "the configuration with the new site does not validate; nothing changed"
fi
echo "caddy: the live configuration validates with $(basename "$INST_CADDY_SITE")"
[ "$check" = --check ] && exit 0

install -d -m 0700 -o root -g root "$INST_BACKUPS"
[ -e "$INST_CADDY_SITE" ] && cp -p "$INST_CADDY_SITE" "$INST_BACKUPS/$(basename "$INST_CADDY_SITE").$(date -u +%Y%m%dT%H%M%SZ)"
install -m 0644 -o root -g root "$work/site.caddy" "$INST_CADDY_SITE.new"
mv -f "$INST_CADDY_SITE.new" "$INST_CADDY_SITE"
systemctl reload caddy
echo "caddy: installed $INST_CADDY_SITE and reloaded"
