#!/bin/bash
# SPDX-License-Identifier: MIT
# Privilege self-test (spec §15.1 step 9, acceptance D-03 and D-11). Run as root on ultron:
#   sudo bash deploy/scripts/privilege-check.sh
# One line per check: "PASS <name>" or "FAIL <name>". Exit status 1 if any check fails.
# tests/e2e/test_privileges.py runs this over ssh and requires every line to pass.
set -uo pipefail

failures=0
check() {  # check <name> <expected: ok|denied> <command...>
  local name=$1 expected=$2 got
  shift 2
  if "$@" >/dev/null 2>&1; then got=ok; else got=denied; fi
  if [ "$got" = "$expected" ]; then echo "PASS $name"; else echo "FAIL $name (expected $expected, got $got)"; failures=$((failures + 1)); fi
}
as() { local user=$1; shift; runuser -u "$user" -- "$@"; }
listening() { ss -Hltn "sport = :$1" | grep -q .; }

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }

# walletd (auth=none) on 5100 and the L1 wallet's gRPC on 18143: only root, lcam and drive.
for port in 5100 18143; do
  if listening "$port"; then
    for user in mutis build caddy; do check "$user cannot connect to 127.0.0.1:$port" denied as "$user" bash -c "exec 3<>/dev/tcp/127.0.0.1/$port"; done
    check "drive can connect to 127.0.0.1:$port" ok as drive bash -c "exec 3<>/dev/tcp/127.0.0.1/$port"
  else
    echo "SKIP nothing listens on 127.0.0.1:$port"
  fi
done

# mutis-api trusts X-Real-IP from loopback: only caddy, drive (the sidecar's canary), root and lcam
# may connect. While the API is off, a stand-in listener lets the guard itself be tested.
stand_in=
if ! listening 8787; then
  python3 -I -c 'import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 8787))
s.listen(16)
time.sleep(30)' &
  stand_in=$!
  for _ in 1 2 3 4 5 6 7 8 9 10; do listening 8787 && break; sleep 0.2; done
fi
for user in build mutis; do check "$user cannot connect to 127.0.0.1:8787 (the API)" denied as "$user" bash -c "exec 3<>/dev/tcp/127.0.0.1/8787"; done
for user in caddy drive; do check "$user can connect to 127.0.0.1:8787 (the API)" ok as "$user" bash -c "exec 3<>/dev/tcp/127.0.0.1/8787"; done
[ -z "$stand_in" ] || kill "$stand_in" 2>/dev/null

# Caddy's admin API: no TCP port, and a socket only root and caddy can use.
check "nothing listens on Caddy's default admin port 2019" denied listening 2019
check "Caddy's admin socket exists" ok test -S /run/caddy/admin.sock
for user in mutis build drive; do check "$user cannot use Caddy's admin socket" denied as "$user" test -w /run/caddy/admin.sock; done

# Files: who can read what.
check "mutis cannot read /home/drive" denied as mutis ls /home/drive
check "build cannot read /srv/mutis/data" denied as build ls /srv/mutis/data
check "caddy cannot read /srv/mutis/data" denied as caddy ls /srv/mutis/data
check "build cannot read /etc/mutis/secret.key" denied as build cat /etc/mutis/secret.key
check "mutis can read /etc/mutis/secret.key" ok as mutis cat /etc/mutis/secret.key
for user in mutis drive build; do check "$user cannot read the walletd keyring credential" denied as "$user" cat /etc/mutis/credentials/walletd-keyring-pass; done
if [ -d /srv/mutis/app/current/dist ]; then
  check "mutis cannot write the served release" denied as mutis touch /srv/mutis/app/current/dist/.probe
  check "drive cannot write the served release" denied as drive touch /srv/mutis/app/current/dist/.probe
  check "caddy can read the served release" ok as caddy test -r /srv/mutis/app/current/dist/index.html
else
  echo "SKIP no release deployed yet"
fi
check "build cannot read /home/drive/mutis keys" denied as build ls /home/drive/mutis
# The database is shared by mutis (API, cleanup) and drive (chain worker): group-writable, nothing else.
db_modes() { find /srv/mutis/data/db -maxdepth 1 -name 'mutis.sqlite3*' ! -perm 0660 | grep -q .; }
check "the database and its -wal/-shm files are 0660" denied db_modes
check "drive (group mutis) can write the database" ok as drive test -w /srv/mutis/data/db/mutis.sqlite3

# The keyring password is on no command line (walletd gets it through a private config copy).
leaked() { ps -eo args | grep -q -F -f /etc/mutis/credentials/walletd-keyring-pass; }
check "walletd's keyring password is on no process command line" denied leaked

# D-11: no npm toolchain anywhere on the box.
check "npm is not installed" denied command -v npm
check "npx is not installed" denied command -v npx

echo "privilege-check: $([ "$failures" = 0 ] && echo PASS || echo "FAIL ($failures)")"
exit $((failures > 0))
