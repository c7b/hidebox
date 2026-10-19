#!/bin/bash
# SPDX-License-Identifier: MIT
# Privilege self-test (spec §15.1 step 9, acceptance D-03 and D-11). Run as root on the server:
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

# walletd (auth=none) on 5100 and the L1 wallet's gRPC on 18143: only root, the operator and drive.
for port in 5100 18143; do
  if listening "$port"; then
    for user in mutis build caddy; do check "$user cannot connect to 127.0.0.1:$port" denied as "$user" bash -c "exec 3<>/dev/tcp/127.0.0.1/$port"; done
    check "drive can connect to 127.0.0.1:$port" ok as drive bash -c "exec 3<>/dev/tcp/127.0.0.1/$port"
  else
    echo "SKIP nothing listens on 127.0.0.1:$port"
  fi
done

# mutis-api trusts X-Real-IP from loopback: only caddy, drive (the sidecar's canary), root and the
# operator may connect. While the API is off, a stand-in listener lets the guard itself be tested.
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

# Uploads are inert (docs/review/upload-safety-1.md): the data directory is mounted noexec, nosuid and nodev,
# so nothing stored there runs, even a file marked executable or one handed to the dynamic loader; only mutis
# can reach into blobs/; and every running service sees / as noexec outside the paths it runs programs from.
data_flags() { local o; o=$(findmnt -n -o OPTIONS --target /srv/mutis/data); [[ ,$o, == *,noexec,* && ,$o, == *,nosuid,* && ,$o, == *,nodev,* ]]; }
check "/srv/mutis/data is mounted noexec,nosuid,nodev" ok data_flags
check "srv-mutis-data.mount is enabled (it comes back at boot)" ok systemctl is-enabled --quiet srv-mutis-data.mount
probe=/srv/mutis/data/.privilege-check-probe-$$
loader=$(ls /lib64/ld-linux-*.so.* /lib/ld-linux-*.so.* 2>/dev/null | head -n 1)
printf '#!/bin/sh\nexit 0\n' > "$probe.sh"
cp /usr/bin/true "$probe.elf"
chown mutis:mutis "$probe.sh" "$probe.elf" && chmod 0700 "$probe.sh" "$probe.elf"
check "control: the same program runs as mutis from /usr/bin" ok as mutis /usr/bin/true
# (test -x can't confirm them: access(X_OK) itself says no on a noexec mount.)
[ "$(stat -c %a "$probe.sh" "$probe.elf" 2>/dev/null)" = $'700\n700' ] ||
  { echo "FAIL could not make the probe files in /srv/mutis/data"; failures=$((failures + 1)); }
check "mutis cannot run a script stored in /srv/mutis/data (mode 0700)" denied as mutis "$probe.sh"
check "mutis cannot run a program stored in /srv/mutis/data (mode 0700)" denied as mutis "$probe.elf"
check "mutis cannot run it through the dynamic loader either" denied as mutis "$loader" "$probe.elf"
rm -f "$probe.sh" "$probe.elf"
check "drive (group mutis) cannot add a file to /srv/mutis/data itself (only to db/)" denied as drive touch /srv/mutis/data/.privilege-check-probe
rm -f /srv/mutis/data/.privilege-check-probe
blob_modes() { find /srv/mutis/data/blobs -mindepth 1 \( -type d -perm /0077 -o -type f ! -perm 0600 \) | grep -q .; }
check "every directory under blobs/ is 0700 and every stored file 0600" denied blob_modes
level=$(find /srv/mutis/data/blobs -mindepth 1 -maxdepth 1 -type d -print -quit)
if [ -n "$level" ]; then
  check "drive (group mutis) cannot add a file inside blobs/" denied as drive touch "$level/.privilege-check-probe"
  rm -f "$level/.privilege-check-probe"
fi
sandbox_noexec() { local pid; pid=$(systemctl show -p MainPID --value "$1"); [ "${pid:-0}" -gt 0 ] && awk '$5 == "/" {print $6}' "/proc/$pid/mountinfo" | grep -q noexec; }
for unit in mutis-api mutis-chain walletd caddy; do
  if systemctl is-active --quiet "$unit"; then check "$unit runs with / noexec in its view (NoExecPaths=/)" ok sandbox_noexec "$unit"; fi
done

# Kernel settings: what /etc/sysctl.d/90-mutis.conf asks for is what the kernel has (provision.sh applies it).
if [ -f /etc/sysctl.d/90-mutis.conf ]; then
  while IFS='=' read -r key want; do
    key=${key// /}; want=${want// /}
    [[ $key =~ ^[a-z] && $key != *'*'* ]] || continue
    check "sysctl $key = $want" ok test "$(sysctl -n "$key" 2>/dev/null)" = "$want"
  done < /etc/sysctl.d/90-mutis.conf
  rp_strict() { local f; for f in /proc/sys/net/ipv4/conf/*/rp_filter; do [ "$(cat "$f")" = 1 ] || return 1; done; }
  check "strict reverse-path filtering on every interface" ok rp_strict
else
  echo "FAIL /etc/sysctl.d/90-mutis.conf is not installed (run provision.sh)"; failures=$((failures + 1))
fi

# SSH: keys only, no root, and no drop-in that would turn passwords back on if another file went away
# (cloud-init writes one). sshd -T is read whole first: grep -q stopping early would fail the pipe.
sshd_config=$(sshd -T 2>/dev/null)
sshd_has() { grep -qix "$1 $2" <<< "$sshd_config"; }
password_line() { grep -rqiE '^[[:space:]]*PasswordAuthentication[[:space:]]+yes' /etc/ssh/sshd_config /etc/ssh/sshd_config.d; }
check "no SSH configuration file asks for passwords" denied password_line
check "SSH refuses passwords" ok sshd_has passwordauthentication no
check "SSH refuses keyboard-interactive logins" ok sshd_has kbdinteractiveauthentication no
check "SSH refuses root" ok sshd_has permitrootlogin no

# The keyring password is on no command line (walletd gets it through a private config copy).
leaked() { ps -eo args | grep -q -F -f /etc/mutis/credentials/walletd-keyring-pass; }
check "walletd's keyring password is on no process command line" denied leaked

# D-11: no npm toolchain anywhere on the box. Debian's nodejs ships corepack, which can fetch pnpm
# or yarn from the registry on first use; nothing calls it, and its shims must not exist.
check "npm is not installed" denied command -v npm
check "npx is not installed" denied command -v npx
check "pnpm is not installed" denied command -v pnpm
check "yarn is not installed" denied command -v yarn
check "pip is not installed" denied command -v pip

echo "privilege-check: $([ "$failures" = 0 ] && echo PASS || echo "FAIL ($failures)")"
exit $((failures > 0))
