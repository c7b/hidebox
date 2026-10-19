#!/bin/bash
# SPDX-License-Identifier: MIT
# Activate an uploaded release on the server (spec §15.5 steps 3–6), as root. deploy.sh calls it with the
# release unpacked in /srv/mutis/app/releases/<id>.new:
#   bash activate-release.sh <release-id>
# Before the switch: file ownership, the sidecar's pinned-wasm handshake, a database backup and the
# migration. The switch is one rename of the `current` symlink. After it, anything that fails rolls
# back to the previous release. A release id that is already live is left alone when it serves the
# same files, and refused when it doesn't (ids are <sha>-c<content id>, see deploy.sh).
set -euo pipefail

id=$1
app=/srv/mutis/app
releases=$app/releases
new=$releases/$id.new
dir=$releases/$id
pinned=2856d86b688959fc6620ac8cf2cb4629ee554c94bd81a6baaa2a71a7e7a393f2   # spec §3.3 step 7

die() { echo "activate: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"
[[ $id =~ ^([0-9a-f]{40}-c[0-9a-f]{8}|[0-9a-f]{12}-dirty-[0-9]{14})$ ]] || die "bad release id: $id"
[ -d "$new" ] || die "nothing unpacked at $new"
# umask 007: the database and its -wal/-shm files are shared with group mutis (the chain worker runs as drive).
as_mutis() { (umask 007 && runuser -u mutis -- env MUTIS_CONFIG=/etc/mutis/mutis.toml "$@"); }

chown -R root:root "$new"
chmod -R u+rwX,go+rX,go-w "$new"

if [ -f "$new/sidecar/sidecar.mjs" ]; then
  hello=$(printf '{"id":1,"cmd":"hello"}\n' | runuser -u drive -- env -i MUTIS_API=http://127.0.0.1:8787 \
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
  chain_was=$(systemctl is-active mutis-chain 2>/dev/null || true)
  if [ "${MUTIS_KEEP_CHAIN:-0}" = 1 ] && [ "$chain_was" = active ]; then
    as_mutis python3 -I "$dir/server/bin/mutis-admin" migrate --check ||
      die "a migration is pending; deploy without MUTIS_KEEP_CHAIN so the chain worker stops for it"
    chain_was=kept
  fi
  [ "$chain_was" = active ] && systemctl stop mutis-chain
  if ! as_mutis python3 -I "$dir/server/bin/mutis-admin" migrate; then   # backs the database up first
    [ "$chain_was" = active ] && systemctl start mutis-chain
    die "mutis-admin migrate failed; the previous release stays live"
  fi
  find /srv/mutis/data/backup -maxdepth 1 -name 'pre-migrate-*' ! -perm 0600 -exec chmod 0600 {} +
fi

ln -sfn "releases/$id" "$app/current.tmp"
mv -T "$app/current.tmp" "$app/current"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$id" >> "$app/history"
echo "switched current → releases/$id"

trap 'echo "activate: failed after the switch; rolling back" >&2; bash "$dir/deploy/scripts/rollback.sh" --from-failed "$id"' ERR

# MUTIS_KEEP_CHAIN=1 leaves the chain worker running on the release it started with (its in-memory
# canary keys survive); the next deploy without it, or a migration above, brings it onto the new code.
for unit in mutis-api mutis-chain; do
  if [ "$unit" = mutis-chain ] && [ "${chain_was:-}" = kept ]; then
    echo "kept mutis-chain running on its current release (MUTIS_KEEP_CHAIN=1)"
    continue
  fi
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    systemctl restart "$unit"
    echo "restarted $unit"
  fi
done

if ! cmp -s "$dir/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile; then
  (set -a && . /etc/mutis/caddy.env && caddy validate --config "$dir/deploy/caddy/Caddyfile" --adapter caddyfile >/dev/null 2>&1)
  install -d -m 0700 /var/backups/mutis
  cp -p /etc/caddy/Caddyfile "/var/backups/mutis/Caddyfile.$(date -u +%Y%m%dT%H%M%SZ)"
  install -m 0644 "$dir/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload caddy
  echo "Caddyfile changed: validated and reloaded"
fi

# One installed copy of backup.py, used by both backup units, refreshed with every release.
cmp -s "$dir/deploy/scripts/backup.py" /usr/local/lib/mutis/backup.py ||
  install -m 0755 -o root -g root "$dir/deploy/scripts/backup.py" /usr/local/lib/mutis/backup.py

for unit in "$dir"/deploy/systemd/*.service "$dir"/deploy/systemd/*.timer "$dir"/deploy/systemd/*.mount; do
  cmp -s "$unit" "/etc/systemd/system/$(basename "$unit")" ||
    echo "notice: $(basename "$unit") differs from the installed unit; run deploy/scripts/provision.sh"
done
cmp -s "$dir/deploy/systemd/caddy.service.d/mutis.conf" /etc/systemd/system/caddy.service.d/mutis.conf ||
  echo "notice: caddy.service.d/mutis.conf differs from the installed drop-in; run deploy/scripts/provision.sh"

if [ -f "$dir/sidecar/sidecar.mjs" ]; then
  runuser -u drive -- bash -s -- "$dir/sidecar" < "$dir/deploy/scripts/init-keys.sh"
fi

trap - ERR
previous=$(awk '{print $2}' "$app/history" | grep -vx "$id" | tail -n 1 || true)
mapfile -t old < <(ls -1t "$releases" | grep -vx -e "$id" -e "${previous:-none}" | grep -v '\.new$' | tail -n +4)
for name in "${old[@]}"; do rm -rf "${releases:?}/$name"; done
echo "releases kept: $(ls -1 "$releases" | wc -l)"
