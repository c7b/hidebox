#!/bin/bash
# SPDX-License-Identifier: MIT
# The 404 page's art at three widths, AVIF and WebP, with the home's stills' settings (docs/review/home-v3.md): WebP
# with libwebp, quality 84, the picture preset, from RGB, no alpha; AVIF with libaom-av1, a still picture, CRF 24,
# 10-bit 4:2:0, BT.709, full range. Run on the server as build, in a folder holding the owner's PNG as src.png (it is
# not committed); the files land in out/ and go to web/site/media/404/.
set -euo pipefail
mkdir -p out
for W in 480 720 960; do
  H=$((W * 1024 / 1536))
  ffmpeg -v error -y -i src.png -vf "scale=${W}:${H}:flags=lanczos,format=rgb24" -c:v libwebp -quality 84 -preset picture -compression_level 6 out/box-zero-${W}.webp
  ffmpeg -v error -y -i src.png -vf "scale=${W}:${H}:flags=lanczos:out_color_matrix=bt709:out_range=full,format=yuv420p10le" \
    -c:v libaom-av1 -still-picture 1 -crf 24 -b:v 0 -cpu-used 4 \
    -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range pc out/box-zero-${W}.avif
done
ls -l out
