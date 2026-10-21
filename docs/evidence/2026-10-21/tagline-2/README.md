<!-- SPDX-License-Identifier: MIT -->
# The tagline, second pass (2026-10-21)

What and why: [`docs/review/tagline-2.md`](../../../review/tagline-2.md). Branch `copy/tagline-2`, pushed to `main`;
not deployed by this session. Everything below ran on the server as `build`, from a copy of the tree.

| What | Where |
|---|---|
| The hero, before and after | `before/` (`main` at `4f71353`) and `after/` (this branch): `hero-<width>-<theme>.webp`, the first screen of `/` at 1440 × 900 and 390 × 844 (pictured at 1.5×), dark and light, from `shots_tagline.py` |
| The hero's lines, measured | `before/hero-metrics.json`, `after/hero-metrics.json`: each line's text, size, weight, colour, contrast on the page, line count and box, and where Open your drive ends, at 360 to 1440 px in both themes |
| The share card | `og.png`, a copy of `web/site/static/og.png` as `render-images.py og.png` drew it from `og/og.html` (146,584 B, 1200 × 630) |
| The repository's social card | `social-preview.png`, a copy of `docs/media/social-preview.png` as `shots_brand.py --readme` drew it from `../../2026-10-19/brand-kit-1/social-preview.html` (219,529 B, 1280 × 640) |
| The README's home picture | `docs/media/home.webp`, the same run of `shots_brand.py --readme` (it makes `drive.webp` and `share.webp` too; they don't show the hero and were not replaced). Its last step, `og_candidate`, now stops: `og/og.html` carries the kit's marks itself, so there is no typed name left to swap |
| The film's end card | `endcard.png`, from `../../2026-10-19/brand-kit-1/endcard.py` (the end card's filters on blank inputs; the film was not recorded) |
| Suites | `suites/`: lint, check-copy, the build (stamped with the base commit: the copy has no `.git`), `check-seo.py --dist` on that build, the deploy tests and the site suite with its browser checks, all on the final tree |
