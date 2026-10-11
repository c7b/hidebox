#!/bin/bash
# SPDX-License-Identifier: MIT
# Switch `current` back to an earlier release and restart what is enabled (spec §15.5 step 6), as root:
#   sudo bash /srv/mutis/app/current/deploy/scripts/rollback.sh            the release before this one
#   sudo bash …/rollback.sh <release-id>                                   a given release
#   sudo bash …/rollback.sh --from-failed <release-id>                     used by deploy after a failure
# Database migrations only move forward; a release older than the schema refuses to start
# (mutis-api checks), and the healthcheck turns red. See deploy/README.md, "Rolling back".
set -euo pipefail

app=/srv/mutis/app
die() { echo "rollback: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"

current=$(readlink "$app/current" 2>/dev/null | sed 's,^releases/,,') || die "no current release"
failed=
target=
case ${1:-} in
  --from-failed) failed=$2 ;;
  "") ;;
  *) target=$1 ;;
esac
if [ -z "$target" ]; then
  skip=${failed:-$current}
  target=$(awk '{print $2}' "$app/history" | grep -vx -e "$skip" -e "$current" | tail -n 1 || true)
fi
[ -n "$target" ] || die "no earlier release to go back to"
[ -d "$app/releases/$target" ] || die "release $target is not on disk"

ln -sfn "releases/$target" "$app/current.tmp"
mv -T "$app/current.tmp" "$app/current"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$target" >> "$app/history"
echo "rollback: current → releases/$target (was $current)"

for unit in mutis-api mutis-chain; do
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then systemctl restart "$unit"; fi
done
if ! cmp -s "$app/releases/$target/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile; then
  install -m 0644 "$app/releases/$target/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload caddy
fi
