#!/bin/bash
# SPDX-License-Identifier: MIT
# Deploy a git ref to the server (spec §15.5). Runs on your workstation, from the repository:
#   deploy/scripts/deploy.sh <git-ref>             a committed ref, built from `git archive` (clean);
#                                                  release id <sha>-c<content id>
#   deploy/scripts/deploy.sh --working-tree        the working tree as it is (staging; release id
#                                                  <sha12>-dirty-<time>, not verifiable by verify-deploy)
# Options: --holding (serve deploy/holding/ instead of the site), --host <ssh host> (default: the
# MUTIS_SSH_HOST environment variable, else "hidebox"; the SSH alias of the server in ~/.ssh/config).
# MUTIS_KEEP_CHAIN=1 deploys without restarting the chain worker (web-only releases; see activate-release.sh).
#
# Steps: unit tests, lint and copy check on the server as `build` with the server's Python 3.13 → build
# (here) → upload one tarball over one multiplexed SSH connection → on the server, activate-release.sh
# checks the sidecar, backs up and migrates the database, switches the `current` symlink atomically
# and restarts what is enabled → smoke test from here (tests/e2e/smoke.py) → automatic rollback if
# the smoke test fails and this run switched `current` → with SealLog on, the served manifest's hash
# is notarized on the Ootle (brand patch P-9).
#
# The content id is a hash of what the build serves, so the same commit built with another
# public_origin or security_drop_url is another release, never a silent no-op.
set -euo pipefail

host=${MUTIS_SSH_HOST:-hidebox}
ref=
holding=
while [ $# -gt 0 ]; do
  case $1 in
    --working-tree) ref=WORKTREE ;;
    --holding) holding=--holding ;;
    --host) host=$2; shift ;;
    -*) echo "deploy: unknown option $1" >&2; exit 2 ;;
    *) ref=$1 ;;
  esac
  shift
done
[ -n "$ref" ] || { echo "usage: deploy.sh <git-ref> | --working-tree [--holding] [--host H] (host: $host)" >&2; exit 2; }

repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
work=$(mktemp -d "${TMPDIR:-/tmp}/mutis-deploy.XXXXXX")
ssh_opts=(-o ControlMaster=auto -o "ControlPath=$work/cm" -o ControlPersist=10m -o ClearAllForwardings=yes)
trap 'ssh "${ssh_opts[@]}" -O exit "$host" 2>/dev/null; rm -rf "$work"' EXIT
remote() { ssh "${ssh_opts[@]}" "$host" "$@"; }

if [ "$ref" = WORKTREE ]; then
  src=$repo
  sha=$(git -C "$repo" rev-parse HEAD)
  source_args=()
else
  if [ -n "$(git -C "$repo" status --porcelain)" ]; then
    echo "deploy: the working tree has uncommitted changes; commit them, or use --working-tree for staging" >&2
    exit 1
  fi
  sha=$(git -C "$repo" rev-parse --verify "$ref^{commit}")
  src=$work/src
  mkdir "$src"
  git -C "$repo" archive "$sha" | tar -x -C "$src"
  source_args=(--source "$sha" "$(git -C "$repo" describe --tags --always "$sha")" "$(git -C "$repo" log -1 --format=%ct "$sha")")
fi

echo "== checks on $host as build (the server's Python)"
gate=/home/build/work/deploy/gate
tar -C "$src" --exclude=__pycache__ -cf - server tools web deploy tests |
  remote "cd /tmp && sudo -u build -H bash -c 'set -eo pipefail; umask 022; rm -rf $gate; mkdir -p $gate
    tar -x -C $gate; cd $gate
    python3 -I -m unittest discover -s server/tests -q 2>&1 | tail -3
    python3 -I -m unittest discover -s deploy/tests -q 2>&1 | tail -3
    python3 -I tools/lint.py --root .
    python3 -I tools/check-copy.py --root . | tail -1
    cd /tmp && rm -rf $gate'"

echo "== build"
remote "sudo cat /etc/mutis/mutis.toml" > "$work/mutis.toml"
summary=$(python3 -I "$src/tools/build.py" --config "$work/mutis.toml" --web "$src/web" --out "$work/dist" \
  --release "$work/release" ${holding} "${source_args[@]}")
echo "$summary"
content=$(python3 -I -c 'import json, sys; print(json.loads(sys.argv[1].split(" ", 2)[2])["content_id"])' "$summary")
if [ "$ref" = WORKTREE ]; then
  release="${sha:0:12}-dirty-$(date -u +%Y%m%d%H%M%S)"
else
  release="$sha-c$content"
fi

echo "== upload and activate $release"
stage=$work/stage
mkdir -p "$stage"
cp -r "$work/dist" "$stage/dist"
cp -r "$work/release/sidecar" "$stage/sidecar"
cp -r "$src/deploy" "$stage/deploy"
cp -r "$src/server" "$stage/server"
rm -rf "$stage/server/tests"
find "$stage" -name __pycache__ -prune -exec rm -rf {} +
printf '%s\n' "$release" > "$stage/RELEASE"
printf '%s\n' "$sha" > "$stage/server/GIT_SHA"
tar -C "$stage" --owner=0 --group=0 --mode='u+rwX,go+rX,go-w' -cf "$work/release.tar" .
before=$(remote "readlink /srv/mutis/app/current || true")
remote "sudo bash -c 'set -e; d=/srv/mutis/app/releases/$release.new; rm -rf \"\$d\"; mkdir -p \"\$d\"; tar -x -C \"\$d\" --no-same-owner; MUTIS_KEEP_CHAIN=${MUTIS_KEEP_CHAIN:-0} bash \"\$d/deploy/scripts/activate-release.sh\" $release'" < "$work/release.tar"

echo "== smoke test"
origin=$(python3 -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["public_origin"])' "$work/mutis.toml")
smoke_args=(--origin "$origin" --manifest "$work/dist/.well-known/mutis-manifest.json")
[ "$(remote "systemctl is-enabled mutis-api 2>/dev/null || true")" = enabled ] && smoke_args+=(--api)
[ "$(remote "systemctl is-enabled mutis-chain 2>/dev/null || true")" = enabled ] && smoke_args+=(--chain)
if ! python3 -I "$repo/tests/e2e/smoke.py" "${smoke_args[@]}"; then
  if [ "$before" = "releases/$release" ]; then
    echo "== smoke test failed on $release, which was already live: nothing to roll back to from here" >&2
  else
    echo "== smoke test failed: rolling back" >&2
    remote "sudo bash /srv/mutis/app/releases/$release/deploy/scripts/rollback.sh --from-failed $release"
  fi
  exit 1
fi

if ! remote "sudo python3 -I /srv/mutis/app/current/deploy/scripts/notarize-release.py"; then
  echo "== notarization failed; the release stays live. Retry: sudo python3 -I /srv/mutis/app/current/deploy/scripts/notarize-release.py" >&2
fi
echo "== deployed $release to $origin"
