#!/bin/sh
# SPDX-License-Identifier: MIT
# Builds web/shared/fonts/geist/Geist-Latin.woff2, the home's Geist (17-site-brief §1.2: a Latin subset of
# 30 KB or less, so the home's hero is set in the brand's face): the vendored, pinned Geist-Variable.woff2
# with its weight axis cut to 400-700 (the weights the home uses) and its characters to Basic Latin,
# Latin-1, general punctuation, the euro, ™ and arrows. A Modified Version under the SIL OFL 1.1 (Geist
# declares no Reserved Font Name; OFL.txt sits beside it). Deterministic: the timestamp is fixed.
# Run as `build` on the server with Debian's fonttools (no pip). Usage: subset-geist.sh [outdir]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/../../shared/fonts/geist/Geist-Variable.woff2
OUT=${1:-$HERE/../../shared/fonts/geist}
UNICODES=U+0020-007E,U+00A0-00FF,U+2010-2027,U+2030-203A,U+20AC,U+2122,U+2190-2193
export SOURCE_DATE_EPOCH=1760572800   # 2025-10-16, so the head table's dates never change the bytes
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fonttools varLib.instancer "$SRC" wght=400:700 -o "$TMP/axis.ttf" -q
pyftsubset "$TMP/axis.ttf" --unicodes="$UNICODES" --layout-features='kern,liga,calt,ccmp,locl,mark,mkmk,tnum' \
  --flavor=woff2 --output-file="$OUT/Geist-Latin.woff2"
echo "$(wc -c < "$OUT/Geist-Latin.woff2") bytes, sha256 $(sha256sum "$OUT/Geist-Latin.woff2" | cut -d' ' -f1)"
