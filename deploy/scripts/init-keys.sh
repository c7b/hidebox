#!/bin/bash
# SPDX-License-Identifier: MIT
# Create the receiver and robot-locker keys (spec §10.2, §8.1) with the verifier sidecar's `newKeys`,
# as `drive`, when they don't exist yet:
#   sudo -u drive bash deploy/scripts/init-keys.sh [sidecar_dir]
# An instance beside production runs it as its own drive-<name>, with MUTIS_KEYS (its key directory) and
# MUTIS_NETWORK (its config's network: the keys' addresses are that network's).
# Existing key files are never overwritten (invoice addresses and canary deliveries derive from
# them). The keys are generated inside the sidecar on this machine and only ever written to
# /home/drive/mutis/<name>.json (0600); no key passes through a command line.
set -euo pipefail

dir=${1:-/srv/mutis/app/current/sidecar}
keys=${MUTIS_KEYS:-/home/drive/mutis}
network=${MUTIS_NETWORK:-esmeralda}
case $network in esmeralda) prefix=otl_esm_1 ;; mainnet) prefix=otl_1 ;; *) echo "init-keys: unknown network $network" >&2; exit 1 ;; esac
pinned=29087e5618c4f5e1c94f31f42a00ccf0f33fc634ddece6f79f1cc37557c85725   # spec §3.3 step 7

case $(id -un) in drive|drive-*) ;; *) echo "init-keys: run as drive" >&2; exit 1 ;; esac
missing=()
for name in receiver robot; do [ -e "$keys/$name.json" ] || missing+=("$name"); done
if [ ${#missing[@]} -eq 0 ]; then
  echo "init-keys: receiver.json and robot.json exist; nothing to do"
  exit 0
fi

coproc sidecar {
  exec env -i MUTIS_API=http://127.0.0.1:8787 MUTIS_NETWORK="$network" /usr/bin/node --experimental-permission \
    --allow-fs-read="$dir" --disallow-code-generation-from-strings "$dir/sidecar.mjs" 2>/dev/null
}
ask() {  # one JSON request per line in, one per line out (spec §3.4.6)
  printf '%s\n' "$1" >&"${sidecar[1]}"
  IFS= read -r -t 60 reply <&"${sidecar[0]}"
}

ask '{"id":1,"cmd":"hello"}'
printf '%s' "$reply" | python3 -I -c '
import json, sys
hello = json.load(sys.stdin)
if not hello.get("ok") or hello.get("wasm_sha256") != sys.argv[1]:
    sys.exit("init-keys: the sidecar does not run the pinned ootle-wasm build")' "$pinned"

umask 077
id=2
for name in "${missing[@]}"; do
  ask "{\"id\":$id,\"cmd\":\"newKeys\"}"
  printf '%s' "$reply" | python3 -I -c '
import json, os, re, sys
keys = json.load(sys.stdin)
hexkey = re.compile(r"[0-9a-f]{64}")
fields = ("owner_sk", "view_sk", "owner_pk", "view_pk")
if not keys.get("ok") or not all(hexkey.fullmatch(keys.get(f, "")) for f in fields) \
        or not keys.get("address", "").startswith(sys.argv[2]):
    sys.exit("init-keys: unexpected newKeys answer")
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({k: keys[k] for k in (*fields, "address")}, f)
    f.write("\n")' "$keys/$name.json" "$prefix"
  echo "init-keys: wrote $keys/$name.json"
  id=$((id + 1))
done
