#!/bin/bash
# SPDX-License-Identifier: MIT
# Caddy from Caddy's own Debian repository, at one pinned version (security pass, 2026-11-21), as root:
#   bash caddy-upstream.sh status            the installed version against the pin (exit 0 equal, 3 not)
#   bash caddy-upstream.sh setup             the repository's key, source and pin (deploy/apt/), idempotent
#   bash caddy-upstream.sh validate FILE...  each Caddyfile against the pinned binary, before it is installed
#                                            (unpacked from the pinned .deb into a scratch directory)
#   bash caddy-upstream.sh install           install the pinned caddy, restart Caddy, check it runs
# Debian's caddy 2.6.2 is built with Go 1.24.4, whose HTTP/2 server any client can crash (CVE-2026-97032), and
# trixie won't rebuild it. The key is the file in deploy/apt/, checked here by its SHA-256 and its fingerprint:
# nothing is fetched to trust. The pin (deploy/apt/caddy-upstream.pref) lets only `caddy` come from that
# repository, at CADDY_VERSION; unattended upgrades never move it. provision.sh runs setup, validate and install
# (in that order, with its Caddyfile installed between the last two); deploy/README.md "Caddy" has the one-time
# switch of a server whose live sites still use Caddy 2.6's syntax.
set -euo pipefail

CADDY_VERSION=2.11.9
KEY_SHA256=783dfee04b19e851a928cd87b34710213ebbe7628f98d9f34595ab83be578c00
KEY_FPR=65760C51EDEA2017CEA2CA15155B6D79CA56EA34
DEPLOY=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.asc
SOURCES=/etc/apt/sources.list.d/caddy-stable.sources
PREF=/etc/apt/preferences.d/caddy-upstream

die() { echo "caddy-upstream: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"

installed() { dpkg-query -W -f='${Version}' caddy 2>/dev/null || true; }

key_fingerprint() {   # the v4 fingerprint of the first public-key packet of an armored key (python3, no gpg here)
  python3 -I - "$1" <<'PY'
import base64, hashlib, sys
lines = open(sys.argv[1]).read().splitlines()
body = "".join(l for l in lines[lines.index("") + 1:] if l and not l.startswith(("=", "-----")))
d = base64.b64decode(body)
if d[0] & 0x40:   # new-format packet header
    n = d[1]
    ln, off = (n, 2) if n < 192 else (((n - 192) << 8) + d[2] + 192, 3) if n < 224 else (int.from_bytes(d[2:6], "big"), 6)
else:
    size = (1, 2, 4)[d[0] & 3]
    ln, off = int.from_bytes(d[1:1 + size], "big"), 1 + size
packet = d[off:off + ln]
print(hashlib.sha1(b"\x99" + len(packet).to_bytes(2, "big") + packet).hexdigest().upper())
PY
}

setup() {
  local key=$DEPLOY/apt/caddy-stable-archive-keyring.asc changed=0
  [ "$(sha256sum < "$key" | cut -d' ' -f1)" = "$KEY_SHA256" ] || die "$key is not the pinned key (SHA-256)"
  [ "$(key_fingerprint "$key")" = "$KEY_FPR" ] || die "$key does not have the pinned fingerprint $KEY_FPR"
  local src dst
  for pair in "$key:$KEYRING" "$DEPLOY/apt/caddy-stable.sources:$SOURCES" "$DEPLOY/apt/caddy-upstream.pref:$PREF"; do
    src=${pair%%:*} dst=${pair#*:}
    cmp -s "$src" "$dst" && continue
    install -m 0644 -o root -g root "$src" "$dst"
    changed=1
  done
  local offered   # read whole, then matched: grep -q under pipefail would cut apt-cache off (SIGPIPE) and fail
  offered=$(apt-cache madison caddy 2>/dev/null || true)
  if [ "$changed" = 1 ] || ! grep -q " $CADDY_VERSION .*cloudsmith" <<<"$offered"; then
    apt-get update -qq -o Dpkg::Use-Pty=0 >/dev/null
    offered=$(apt-cache madison caddy 2>/dev/null || true)
  fi
  grep -q " $CADDY_VERSION .*cloudsmith" <<<"$offered" ||
    die "caddy $CADDY_VERSION isn't offered by Caddy's repository (apt-cache policy caddy)"
  echo "caddy-upstream: repository, key ($KEY_FPR) and pin to $CADDY_VERSION in place; installed: $(installed)"
}

validate() {
  [ $# -gt 0 ] || die "validate: name at least one Caddyfile"
  local work
  work=$(mktemp -d)
  trap 'rm -rf "$work"' RETURN
  (cd "$work" && apt-get download -qq "caddy=$CADDY_VERSION" >/dev/null) || die "could not download caddy $CADDY_VERSION"
  dpkg-deb -x "$work"/caddy_*.deb "$work/root"
  local bin=$work/root/usr/bin/caddy f
  [[ $("$bin" version) == "v$CADDY_VERSION "* ]] || die "the downloaded binary is not v$CADDY_VERSION"
  for f in "$@"; do
    if ! (set -a && . /etc/mutis/caddy.env && "$bin" validate --config "$f" --adapter caddyfile) >"$work/log" 2>&1; then
      tail -n 15 "$work/log" >&2
      die "$f does not validate with caddy $CADDY_VERSION; nothing was installed"
    fi
    echo "caddy-upstream: $f validates with caddy $CADDY_VERSION"
  done
}

install_pinned() {
  if [ "$(installed)" != "$CADDY_VERSION" ]; then
    # The live Caddyfile is ours (installed by provision.sh): keep it, never the package's example.
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends --allow-downgrades \
      -o Dpkg::Options::=--force-confold -o Dpkg::Use-Pty=0 "caddy=$CADDY_VERSION" >/dev/null
  fi
  [ "$(installed)" = "$CADDY_VERSION" ] || die "caddy $CADDY_VERSION did not install (apt-cache policy caddy)"
  systemctl daemon-reload
  systemctl restart caddy
  sleep 2
  systemctl is-active --quiet caddy || die "caddy is not running on $CADDY_VERSION (journalctl -u caddy)"
  echo "caddy-upstream: caddy $(caddy version | cut -d' ' -f1) running"
}

case ${1:-} in
  status) v=$(installed); echo "caddy: installed ${v:-none}, pinned $CADDY_VERSION"; [ "$v" = "$CADDY_VERSION" ] || exit 3 ;;
  setup) setup ;;
  validate) shift; validate "$@" ;;
  install) install_pinned ;;
  *) die "usage: caddy-upstream.sh status | setup | validate FILE... | install" ;;
esac
