#!/bin/bash
# SPDX-License-Identifier: MIT
# Fallback when a release has no binaries yet (upgrade-0.50.md §3b): tari_ootle_walletd built from source
# at the release commit, as `build`, in /home/build/work/ootle-<version>. It builds; it never installs.
#
#   deploy/ootle/build-walletd-src.sh <version> <40-hex release commit> [prepare|build]
#
# `prepare` (as build, in the foreground): the source at that commit (checked, clean), the toolchain its
# rust-toolchain.toml names, the crates (cargo fetch --locked), and the native headers walletd needs
# (openssl-sys, libdbus-sys) from Debian's own packages: `apt-get download` as build, unpacked with
# dpkg-deb -x into a private sysroot, so nothing is installed on the server and no service restarts.
# `build`: cargo build --release --locked of the one binary, -j 1 under nice 15, with the release
# workflow's environment (.github/workflows/build_binaries.yml: TARI_NETWORK=igor). Start it as a
# capped unit so the live services keep the CPU and memory they need (upgrade-0.50.md §3b):
#
#   sudo install -o build -g build -m 0755 build-walletd-src.sh $W/       # W=/home/build/work/ootle-<version>
#   sudo systemd-run --unit=ootle-build --uid=build --gid=build -p MemoryMax=4500M -p MemorySwapMax=0 \
#     -p CPUWeight=10 -p IOWeight=10 -p StandardOutput=append:$W/logs/build.log \
#     -p StandardError=append:$W/logs/build.log $W/build-walletd-src.sh <version> <commit> build
#
# Differences from the release binary: no web UI (the release builds it with pnpm first; the JSON-RPC
# mutis uses is the same), and its bytes are not the release's. Replace it with the release binary once
# one exists.
set -euo pipefail

version=${1:?version}; commit=${2:?release commit}; step=${3:-prepare}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $commit =~ ^[0-9a-f]{40}$ ]] || { echo "bad version or commit" >&2; exit 2; }
[ "$(id -un)" = build ] || { echo "run as build" >&2; exit 2; }
W=/home/build/work/ootle-$version
SR=$W/sysroot
REPO=https://github.com/tari-project/tari-ootle.git
TARGET=x86_64-unknown-linux-gnu

environment() {
  export HOME=/home/build
  export PATH=$W/bin:/home/build/.cargo/bin:/usr/local/bin:/usr/bin:/bin
  export PKG_CONFIG=$W/bin/pkg-config PKG_CONFIG_SYSROOT_DIR=$SR
  export PKG_CONFIG_LIBDIR=$SR/usr/lib/x86_64-linux-gnu/pkgconfig:$SR/usr/share/pkgconfig
  export PKG_CONFIG_ALLOW_SYSTEM_LIBS=1 PKG_CONFIG_ALLOW_SYSTEM_CFLAGS=1
  export OPENSSL_INCLUDE_DIR=$SR/usr/include OPENSSL_LIB_DIR=$SR/usr/lib/x86_64-linux-gnu
  export CPATH=$SR/usr/include:$SR/usr/include/x86_64-linux-gnu LIBRARY_PATH=$SR/usr/lib/x86_64-linux-gnu
  export TARI_NETWORK=igor TARI_TARGET_NETWORK=igor CARGO_HTTP_MULTIPLEXING=false
  export CARGO_TARGET_DIR=$W/target CARGO_BUILD_JOBS=1
}

checked_source() {
  cd "$W/src"
  [ "$(git rev-parse HEAD)" = "$commit" ] || { echo "the source is not at $commit" >&2; exit 1; }
  [ -z "$(git status --porcelain)" ] || { echo "the source tree has changes" >&2; exit 1; }
}

case $step in
prepare)
  mkdir -p "$W/logs" "$W/bin" "$W/debs" "$SR"
  if [ ! -d "$W/src/.git" ]; then
    git init -q "$W/src"
    git -C "$W/src" remote add origin "$REPO"
    git -C "$W/src" fetch -q --depth 1 origin "$commit"
    git -C "$W/src" -c advice.detachedHead=false checkout -q FETCH_HEAD
  fi
  checked_source
  # The headers of the libraries the release binary links (ldd: libssl3, libdbus-1-3), at the versions apt offers
  # (`apt-cache policy`: on 2026-11-05 the installed ones); the binary links the installed libraries.
  (cd "$W/debs" && apt-get download libssl-dev libdbus-1-dev pkgconf-bin libpkgconf3)
  for deb in "$W"/debs/*.deb; do dpkg-deb -x "$deb" "$SR"; done
  sha256sum "$W"/debs/*.deb
  lib=$SR/usr/lib/x86_64-linux-gnu
  for so in libssl.so.3 libcrypto.so.3 libdbus-1.so.3; do ln -sfn "/usr/lib/x86_64-linux-gnu/$so" "$lib/$so"; done
  # dbus-1.pc names libsystemd in Requires.private (static links only); the shared library is the system's.
  printf '%s\n' 'Name: libsystemd' 'Description: stub for pkgconf' 'Version: 257' 'Libs: -lsystemd' > "$lib/pkgconfig/libsystemd.pc"
  printf '%s\n' '#!/bin/sh' "LD_LIBRARY_PATH=$lib exec $SR/usr/bin/pkgconf \"\$@\"" > "$W/bin/pkg-config"
  chmod 755 "$W/bin/pkg-config"
  environment
  rustup show active-toolchain
  nice -n 15 cargo fetch --locked
  pkg-config --cflags --libs dbus-1 openssl
  ;;
build)
  environment
  checked_source
  echo "start $(date -u +%FT%TZ) $(rustc --version)"
  nice -n 15 cargo build --locked --release --target $TARGET --package tari_ootle_walletd --bin tari_ootle_walletd -j 1
  bin=$CARGO_TARGET_DIR/$TARGET/release/tari_ootle_walletd
  "$bin" --version || true
  sha256sum "$bin"
  echo "done $(date -u +%FT%TZ)"
  ;;
*) echo "step is prepare or build" >&2; exit 2 ;;
esac
