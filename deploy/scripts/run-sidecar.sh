#!/bin/sh
# SPDX-License-Identifier: MIT
# The verifier sidecar of the live release (web/app/sidecar), as mutis-chain starts it: the config's
# sidecar.command. Node's permission model checks the script's real path, so --allow-fs-read must
# name the release's own directory; given the `current` symlink, Node refuses the sidecar its own
# files. Paths are absolute: the chain worker starts this with MUTIS_API (and MUTIS_NETWORK) and nothing else.
# An instance beside production names its own release's sidecar: sidecar.command = [this script, its path].
dir=$(/usr/bin/readlink -f "${1:-/srv/mutis/app/current/sidecar}") || exit 1
exec /usr/bin/node --experimental-permission --allow-fs-read="$dir" --disallow-code-generation-from-strings \
  "$dir/sidecar.mjs"
