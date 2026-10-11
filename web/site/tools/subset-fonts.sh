#!/bin/sh
# SPDX-License-Identifier: MIT
# Builds web/shared/fonts/ from Debian's fonts-courier-prime (11-brand §13.3): subset, rename to
# Mutis Script / Mutis Script Code (the OFL requires a new name for a Modified Version), WOFF2.
# Run as `build` on the server with Debian fonttools + woff2 (no pip). Usage: subset-fonts.sh [outdir]
set -eu

SRC=/usr/share/fonts/opentype/courier-prime
OFL=/usr/share/common-licenses/OFL-1.1
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/../../shared/fonts}
# Latin, Latin-1, Latin Extended-A, punctuation, euro (brand §13.3) plus ™ for "Tari™" in headings.
UNICODES=U+0020-007E,U+00A0-00FF,U+0100-017F,U+2010-2027,U+2030-203A,U+20AC,U+2122

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

build() { # <source otf> <family> <style> <output woff2>
  pyftsubset "$SRC/$1" --unicodes="$UNICODES" --layout-features='*' --name-IDs='*' \
    --name-languages='*' --notdef-outline --desubroutinize --output-file="$TMP/subset.otf"
  ttx -q -f -t name -t CFF -t OS/2 -t head -o "$TMP/tables.ttx" "$TMP/subset.otf"
  python3 -I "$HERE/rename-font.py" "$TMP/tables.ttx" "$2" "$3"
  ttx -q -f --no-recalc-timestamp -m "$TMP/subset.otf" -o "$TMP/renamed.otf" "$TMP/tables.ttx"
  woff2_compress "$TMP/renamed.otf" >/dev/null
  mv "$TMP/renamed.woff2" "$OUT/$4"
}

mkdir -p "$OUT"
build "Courier Prime.otf" "Mutis Script" Regular MutisScript-Regular.woff2
build "Courier Prime Bold.otf" "Mutis Script" Bold MutisScript-Bold.woff2
build "Courier Prime Code.otf" "Mutis Script Code" Regular MutisScriptCode-Regular.woff2

{
  printf '%s\n' \
    'Mutis Script and Mutis Script Code are Modified Versions of Courier Prime and Courier Prime Code.' \
    '' \
    'Copyright (c) 2015 Quote-Unquote Apps (http://quoteunquoteapps.com)' \
    'with Reserved Font Name Courier Prime.' \
    'Copyright (c) 2015 Quote-Unquote Apps (http://quoteunquoteapps.com)' \
    'with Reserved Font Name Courier Prime Code.' \
    '' \
    'This Font Software is licensed under the SIL Open Font License, Version 1.1.' \
    ''
  cat "$OFL"
} > "$OUT/OFL.txt"

printf '%s\n' \
  'Mutis Script and Mutis Script Code are Modified Versions of Courier Prime and Courier Prime Code' \
  'by Quote-Unquote Apps (OFL-1.1), renamed as the licence requires. Source: Debian package' \
  "fonts-courier-prime $(dpkg-query -W -f='${Version}' fonts-courier-prime). Changes: subset to Latin," \
  'Latin-1, Latin Extended-A, punctuation, the euro and trademark signs; renamed; converted to WOFF2' \
  'by web/site/tools/subset-fonts.sh. Licence: OFL.txt in this directory.' > "$OUT/NOTICE"

ls -l "$OUT"
