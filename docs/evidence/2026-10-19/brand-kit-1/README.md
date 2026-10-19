<!-- SPDX-License-Identifier: MIT -->
# The brand kit (2026-10-19 UTC)

What and why: [`docs/review/brand-kit-1.md`](../../../review/brand-kit-1.md). Prepared on the branch `brand/kit-1`,
rebased on the SEO pass and pushed to `main`; not deployed by this session.

| What | Where |
|---|---|
| Screenshots | `after/` (this branch's final tree) and `before/` (`main` at `9bfee2c`), from `shots_brand.py` on the server as `build`: `<surface>-<width>-<theme>.webp` at 1440 and 390, dark and light; close-ups of each lockup at 4× (`header-*`, `compare-1440-*`, `drive-mark-*`, `drive-start-mark-*`, `folder-mark-*`, PNG) |
| The README's pictures and the social card | made by `shots_brand.py --readme` into `docs/media/` (`home.webp`, `drive.webp`, `share.webp`, `social-preview.png`; the card's template is `social-preview.html` here) |
| `og.png` with the kit's marks | `og-candidate.png` (`shots_brand.py`'s `og_candidate`); `og.png` itself is unchanged |
| The film's end card | `endcard.png`, from `endcard.py` (film.py's own end-card filters on blank inputs; the film was not recorded) |
| Against the kit | `kit-check.txt`, from `kit_check.py KIT_DIR` (the kit is kept outside this repository): every point of the sprite's, the favicon's and the brand symbol's paths within 0.005 units of the kit's, the lockups the kit's own; the PNG icons are the kit's files (0 % difference) |
| The ICO against the SVG | `ico-vs-svg.png`: each of `favicon.ico`'s entries (16, 32 and 48 px, left) beside `favicon.svg` drawn by Chromium at that size (right) |
| Caddy and the icons | `icons-served.json`, from `icons_served.py` (the production Caddyfile on the throwaway local stack of `tests/e2e/localstack.py`): status, type, caching and bytes of every icon, the manifest, both cards and the sprite |
| Suites | `suites/`: `suites/`: lint PASS, check-copy PASS, build OK (206 files), core ALL PASS (9 steps), deploy 89 OK, server 331 OK (5 skipped), site 42/42, UI 804/804; `headers-local.log` (D-01 on the throwaway stack: PASS, 77 checks), `check-seo-dist.log` (PASS) |
