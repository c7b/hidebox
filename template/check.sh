#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Checks the SealLog template end to end. Run as user `build` on the server, from anywhere:
#   ./check.sh                   vectors, rustfmt, clippy, tari lint, tests, build; the build must equal dist/
#   ./check.sh --dist            the same checks, then write this build to dist/
#   ./check.sh --costs           print fee, WASM points and state size as the log grows
#   ./check.sh --onchain <addr>  check that a published template holds exactly dist/seal_log.wasm
#                                (needs only python3 and the network; runs anywhere)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
dist=$here/dist

if [[ ${1:-} == --onchain ]]; then
    exec python3 -I "$here/wasm_check.py" onchain "${2:?give the template address}" "${@:3}"
fi

export PATH=/opt/tari/bin:$HOME/.cargo/bin:$PATH
cargo_home=${CARGO_HOME:-$HOME/.cargo}
# rustc writes dependency source paths into panic messages; name them the same on every machine.
export RUSTFLAGS="--remap-path-prefix=$cargo_home=/cargo"

# The ABI section of every SealLog build so far (template_e064f38d…, template_b571909e…).
abi_expected=b4b4134be0d1a58ac7c224de2cf599e6f0d5e8c2ad484476e904bbc6c0dde494
max_bytes=$((110 * 1024))
wasm=target/wasm32-unknown-unknown/release/seal_log.wasm
tested=target/default/wasm32-unknown-unknown/release/seal_log.wasm

step() { printf '\n== %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

cd "$here/seal_log"

if [[ ${1:-} == --costs ]]; then
    log=target/costs.log
    cargo test --locked --test seal_log costs_as_the_log_grows -- --ignored --nocapture >"$log" 2>&1 ||
        { tail -n 20 "$log"; fail "the cost run failed (full output in seal_log/$log)"; }
    grep '^COST' "$log"
    exit
fi

step "test vectors"
python3 -I tests/vectors/gen.py --check

step "rustfmt"
cargo fmt --check

step "clippy"
cargo clippy --locked --all-targets -- -D warnings

step "tari lint"
tari lint --deny-warnings >target/tari-lint.log 2>&1 || { cat target/tari-lint.log; fail "tari lint"; }
tail -n 1 target/tari-lint.log

step "tests"
cargo test --locked

step "build"
tari build >target/tari-build.log 2>&1 || { tail -n 20 target/tari-build.log; fail "tari build"; }
size=$(stat -c %s "$wasm")
abi=$(python3 -I "$here/wasm_check.py" abi "$wasm")
echo "seal_log.wasm  $size bytes  sha256 $(sha "$wasm")"
echo "ABI (tari_tdef) sha256 $abi"
((size <= max_bytes)) || fail "$size bytes is over the $max_bytes-byte budget"
[[ $abi == "$abi_expected" ]] || fail "the ABI differs from the published SealLog builds'"
! grep -qaF "$cargo_home" "$wasm" || fail "the build embeds $cargo_home"
[[ $(sha "$tested") == $(sha "$wasm") ]] || fail "the tests ran different bytes than tari build produced"
echo "ABI unchanged; no build paths inside; the tests ran these exact bytes"

if [[ ${1:-} == --dist ]]; then
    step "dist"
    install -m 0644 "$wasm" "$dist/seal_log.wasm"
    (cd "$dist" && sha256sum seal_log.wasm > SHA256SUMS)
    metadata=$(ls -t target/wasm32-unknown-unknown/release/build/seal_log-*/output | head -n 1)
    cat > "$dist/BUILD-INFO.txt" <<INFO
seal_log $(sed -n 's/^version = "\(.*\)"/\1/p' Cargo.toml | head -n 1), written by template/check.sh --dist
built      $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) as $(whoami)
toolchain  $(rustc -V); $(cargo -V); $(tari --version)
command    RUSTFLAGS="--remap-path-prefix=\$CARGO_HOME=/cargo" tari build
           (release profile in Cargo.toml: opt-level s, lto, codegen-units 1, panic abort, strip)
wasm       seal_log.wasm, $size bytes, sha256 $(sha "$wasm")
abi        tari_tdef sha256 $abi (unchanged since the first SealLog build)
metadata   $(sed -n 's/^cargo::metadata=TEMPLATE_METADATA_HASH=//p' "$metadata") (TEMPLATE_METADATA_HASH; not part of the WASM)
inputs     Cargo.lock $(sha Cargo.lock), Cargo.toml $(sha Cargo.toml), build.rs $(sha build.rs), src/lib.rs $(sha src/lib.rs)

To rebuild: the same toolchain, then template/check.sh (it sets RUSTFLAGS, so the bytes don't
depend on the user, the directory or CARGO_HOME).
Publish these exact bytes with a PublishTemplate instruction. walletd's transactions.publish_template
runs wasm-opt first and stores different bytes. template/check.sh --onchain <template address> says
whether a published template holds this file.
INFO
    cat "$dist/SHA256SUMS"
else
    step "dist"
    cmp "$wasm" "$dist/seal_log.wasm" || fail "this build differs from dist/seal_log.wasm"
    (cd "$dist" && sha256sum --check SHA256SUMS)
fi

printf '\nALL CHECKS PASSED\n'
