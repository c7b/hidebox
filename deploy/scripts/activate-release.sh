#!/bin/bash
# SPDX-License-Identifier: MIT
# Activate an uploaded release on the server (spec §15.5 steps 3–6), as root. deploy.sh calls it with the
# release unpacked in /srv/mutis/app/releases/<id>.new:
#   bash activate-release.sh <release-id>
# Before the switch: file ownership, the sidecar's pinned-wasm handshake, a database backup and the
# migration. The switch is one rename of the `current` symlink. After it, anything that fails rolls
# back to the previous release. A release id that is already live is left alone when it serves the
# same files, and refused when it doesn't (ids are <sha>-c<content id>, see deploy.sh).
# MUTIS_INSTANCE=<name> activates it for an instance beside production instead (deploy/scripts/instance.py:
# its own tree, users, units and Caddy site; production's Caddyfile and units are never touched then).
set -euo pipefail

id=$1
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
eval "$(python3 -I "$here/instance.py" env "${MUTIS_INSTANCE:-}")"
export MUTIS_INSTANCE
app=$INST_APP
releases=$app/releases
new=$releases/$id.new
dir=$releases/$id
pinned=072f77c11de0ab34e0cae1cc9ffc3f732995fbed3ffb03ddfdb7027b1164c3ae   # spec §3.3 step 7

die() { echo "activate: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
[[ $id =~ ^([0-9a-f]{40}-c[0-9a-f]{8}|[0-9a-f]{12}-dirty-[0-9]{14})$ ]] || die "bad release id: $id"
[ -d "$new" ] || die "nothing unpacked at $new"
# umask 007: the database and its -wal/-shm files are shared with group mutis (the chain worker runs as drive).
as_mutis() { (umask 007 && runuser -u "$INST_MUTIS_USER" -- env MUTIS_CONFIG="$INST_CONFIG" "$@"); }

# The live release's fingerprinted files go along for one release: a page loaded before the switch still asks for them.
live=$(readlink "$app/current" 2>/dev/null || true)
if [ -n "$live" ] && [ "$live" != "releases/$id" ] && [ -d "$app/$live/dist" ] && [ -f "$new/deploy/scripts/carry-assets.py" ]; then
  python3 -I "$new/deploy/scripts/carry-assets.py" "$app/$live/dist" "$new/dist" || echo "notice: carry-assets failed; pages loaded before the switch may miss a file"
fi
# The text files' .br copies, with the server's Node (provision.sh), where the build had none to make them; the
# .gz copies come with the build. Never in the hash manifest; without them Caddy compresses on the fly as before.
if [ -f "$new/deploy/scripts/precompress.py" ]; then
  python3 -I "$new/deploy/scripts/precompress.py" "$new/dist" || echo "notice: precompress failed; Caddy compresses on the fly"
fi
chown -R root:root "$new"
chmod -R u+rwX,go+rX,go-w "$new"

if [ -f "$new/sidecar/sidecar.mjs" ]; then
  hello=$(printf '{"id":1,"cmd":"hello"}\n' | runuser -u "$INST_DRIVE_USER" -- env -i MUTIS_API=http://127.0.0.1:8787 \
    /usr/bin/node --experimental-permission --allow-fs-read="$new/sidecar" --disallow-code-generation-from-strings \
    "$new/sidecar/sidecar.mjs" 2>/dev/null | head -n 1) || true
  printf '%s' "$hello" | python3 -I -c '
import json, sys
h = json.loads(sys.stdin.read() or "{}")
sys.exit(0 if h.get("ok") and h.get("wasm_sha256") == sys.argv[1] else "activate: the sidecar does not report the pinned ootle-wasm")' "$pinned"
  echo "sidecar: hello ok, pinned ootle-wasm"
fi

same_files() {  # same_files <manifest> <manifest>: the served files and hashes (built_at aside)
  python3 -I -c 'import json, sys; a, b = (json.load(open(p))["files"] for p in sys.argv[1:]); sys.exit(a != b)' "$1" "$2"
}
current=$(readlink "$app/current" 2>/dev/null || true)
if [ "$current" = "releases/$id" ]; then
  if same_files "$dir/dist/.well-known/mutis-manifest.json" "$new/dist/.well-known/mutis-manifest.json"; then
    rm -rf "$new"
    echo "release $id is already live with the same files: nothing to switch"
    exit 0
  fi
  rm -rf "$new"
  die "release $id is live but this upload serves different files; refusing (a build that isn't deterministic?)"
fi
rm -rf "$dir"   # a copy of this id that was rolled back earlier
mv "$new" "$dir"

if [ -x "$dir/server/bin/mutis-admin" ]; then
  as_mutis python3 -I "$dir/server/bin/mutis-admin" check-config >/dev/null || die "mutis-admin check-config failed"
  # The chain worker writes all the time; it waits out the migration (the restarts below start it again).
  # With MUTIS_KEEP_CHAIN=1 it keeps running: refused when a migration is pending.
  chain_was=$(systemctl is-active "$INST_CHAIN_UNIT" 2>/dev/null || true)
  if [ "${MUTIS_KEEP_CHAIN:-0}" = 1 ] && [ "$chain_was" = active ]; then
    as_mutis python3 -I "$dir/server/bin/mutis-admin" migrate --check ||
      die "a migration is pending; deploy without MUTIS_KEEP_CHAIN so the chain worker stops for it"
    chain_was=kept
  fi
  [ "$chain_was" = active ] && systemctl stop "$INST_CHAIN_UNIT"
  if ! as_mutis python3 -I "$dir/server/bin/mutis-admin" migrate; then   # backs the database up first
    [ "$chain_was" = active ] && systemctl start "$INST_CHAIN_UNIT"
    die "mutis-admin migrate failed; the previous release stays live"
  fi
  # As mutis, which made them, and regular files only: root follows no name a service user could have planted there.
  # From /: find returns to the directory it started in, and mutis can't enter the caller's (deploy.sh runs this from
  # a home directory, where find then ends with an error). A backup's mode is not worth a chain worker left stopped,
  # so a failure here is a notice and the activation goes on.
  (cd / && as_mutis find "$INST_DATA/backup" -maxdepth 1 -type f -name 'pre-migrate-*' ! -perm 0600 -exec chmod 0600 {} +) \
    || echo "notice: the pre-migrate backups' mode could not be tightened"
fi

ln -sfn "releases/$id" "$app/current.tmp"
mv -T "$app/current.tmp" "$app/current"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$id" >> "$app/history"
echo "switched current → releases/$id"

trap 'echo "activate: failed after the switch; rolling back" >&2; bash "$dir/deploy/scripts/rollback.sh" --from-failed "$id"' ERR

# MUTIS_KEEP_CHAIN=1 leaves the chain worker running on the release it started with (its in-memory
# canary keys survive); the next deploy without it, or a migration above, brings it onto the new code.
for unit in "$INST_API_UNIT" "$INST_CHAIN_UNIT"; do
  if [ "$unit" = "$INST_CHAIN_UNIT" ] && [ "${chain_was:-}" = kept ]; then
    echo "kept $INST_CHAIN_UNIT running on its current release (MUTIS_KEEP_CHAIN=1)"
    continue
  fi
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    systemctl restart "$unit"
    echo "restarted $unit"
  fi
done

if [ -z "$MUTIS_INSTANCE" ]; then
  if ! cmp -s "$dir/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile; then
    (set -a && . /etc/mutis/caddy.env && caddy validate --config "$dir/deploy/caddy/Caddyfile" --adapter caddyfile >/dev/null 2>&1)
    install -d -m 0700 /var/backups/mutis
    cp -p /etc/caddy/Caddyfile "/var/backups/mutis/Caddyfile.$(date -u +%Y%m%dT%H%M%SZ)"
    install -m 0644 "$dir/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
    systemctl reload caddy
    echo "Caddyfile changed: validated and reloaded"
  fi
else
  # The instance's own site, rendered from this release's Caddyfile and the instance's config, checked inside the
  # whole live configuration (production's Caddyfile and every other mutis.d file) before it replaces the old one.
  bash "$dir/deploy/scripts/caddy-site.sh" "$dir"
fi

# One installed copy of backup.py, used by both backup units, refreshed with every release.
cmp -s "$dir/deploy/scripts/backup.py" "$INST_LIB/backup.py" ||
  install -m 0755 -o root -g root "$dir/deploy/scripts/backup.py" "$INST_LIB/backup.py"

if [ -z "$MUTIS_INSTANCE" ]; then
  for unit in "$dir"/deploy/systemd/*.service "$dir"/deploy/systemd/*.timer "$dir"/deploy/systemd/*.mount; do
    cmp -s "$unit" "/etc/systemd/system/$(basename "$unit")" ||
      echo "notice: $(basename "$unit") differs from the installed unit; run deploy/scripts/provision.sh"
  done
  cmp -s "$dir/deploy/systemd/caddy.service.d/mutis.conf" /etc/systemd/system/caddy.service.d/mutis.conf ||
    echo "notice: caddy.service.d/mutis.conf differs from the installed drop-in; run deploy/scripts/provision.sh"
else
  rendered=$(mktemp -d)
  # shellcheck disable=SC2046
  python3 -I "$dir/deploy/scripts/instance.py" units "$MUTIS_INSTANCE" "$rendered" \
    $(sed -n 's/^walletd=//p' "$INST_ETC/instance.conf" 2>/dev/null | sed 's/^/--walletd /') >/dev/null
  for unit in "$rendered"/*; do
    cmp -s "$unit" "/etc/systemd/system/$(basename "$unit")" ||
      echo "notice: $(basename "$unit") differs from the installed unit; run deploy/scripts/provision-instance.sh"
  done
  rm -rf "$rendered"
fi

if [ -f "$dir/sidecar/sidecar.mjs" ]; then
  network=$(python3 -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("network", "esmeralda"))' "$INST_CONFIG")
  runuser -u "$INST_DRIVE_USER" -- env MUTIS_NETWORK="$network" MUTIS_KEYS="$INST_KEYS" \
    bash -s -- "$dir/sidecar" < "$dir/deploy/scripts/init-keys.sh"
fi

trap - ERR
previous=$(awk '{print $2}' "$app/history" | grep -vx "$id" | tail -n 1 || true)
mapfile -t old < <(ls -1t "$releases" | grep -vx -e "$id" -e "${previous:-none}" | grep -v '\.new$' | tail -n +4)
for name in "${old[@]}"; do rm -rf "${releases:?}/$name"; done
echo "releases kept: $(ls -1 "$releases" | wc -l)"
