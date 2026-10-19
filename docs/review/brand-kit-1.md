<!-- SPDX-License-Identifier: MIT -->
# The brand kit (2026-10-19)

The owner approved a brand kit: the same open box drawn as one filled outline with soft ends on its side walls, a
wordmark ("hidebox" in outlined letters, "hide" light and "box" bold, a small rhombus over a dotless i), favicons and
app icons. This pass puts it everywhere the old mark and the typed name stood as a logo. Copy, layout and the site's
tokens are unchanged. Branch `brand/kit-1`, rebased on the SEO pass (`13382af`, which ran beside it) and pushed to
`main`; **not deployed** (the integrator deploys). Evidence:
[`docs/evidence/2026-10-19/brand-kit-1/`](../evidence/2026-10-19/brand-kit-1/).

## The commits

| Commit | What |
|---|---|
| The site | The sprite's `i-hidebox` is the kit's mark; a new `i-wordmark`; the header and the comparison's head show the wordmark beside the tile; the favicon and the brand symbol draw the same path; the site's checks; a note in DESIGN.md |
| The drive | `wordmark()` in `behaviors.js`; the sidebar, the start screen and a folder link's top bar |
| The holding page | The kit's lockup in place of the old drawn "bye" |
| Icons and the shared-link card | `render-images.py` draws the icons from SVG; `favicon.ico` at 16, 32 and 48 px; the new maskable icon in the manifest; `og-s.png` |
| The film's end card | The wordmark under the symbol, where the name stood in type |
| README and docs/media | The kit's lockup as the README's heading; both lockups; the README's three pictures and the social card made again |
| The wordmark's outer svg; more checks | The `<svg>` around each `<use>` of the wordmark takes its size from CSS; the static checks cover `/v2`, the maskable icon, the ICO's sizes and the kit's lime |
| The ICO's link | The SEO pass linked `/favicon.ico` from every page as `sizes="192x192"` (the old ICO); it now says `16x16 32x32 48x48` |
| Caddy and the maskable icon | `/icon-maskable-512.png` is kept a day and loadable from any origin, like the other icons |
| The kit's own lime | The owner's call during the pass: the logo in the kit's `#ACFF00`, the kit's icons as shipped |
| This review, the evidence, CHANGELOG, the fix log | |

## Where the mark and the wordmark are now

| Surface | The open box (`i-hidebox`) | The wordmark (`i-wordmark`) | Its name for screen readers |
|---|---|---|---|
| Every site page's header (`/`, `/how`, `/made`, `/judges`, `/fine-print`, the 404, `/v2`, the link and task pages: a link's page, a drop page, `/send`, `/verify`, their errors) | 20 px on the 30 px ink tile | 17 px beside it | the link's label, "hidebox, home" (unchanged) |
| The comparison's head on `/` and `/v2` (computers; phones read each row as a card) | 15 px on the 22 px tile | 12.5 px | an sr-only "hidebox" in the column's header |
| The drive's sidebar (the phone's in its sheet) | 20 px on the 2rem tile | 16 px over "My drive" | an sr-only "hidebox" in the link |
| `/drive` with no drive (the start screen), a folder link's top bar | 20 px on the 2rem tile | 18 px | the same |
| The empty drive | the brand moment's tile | (none) | (decoration) |
| Delivered, Confirmed, Sent (`progress.js`'s done moment) | 44 px on its 72 px tile | (none) | (decoration) |
| The holding page | the lockup, inline | 208 px wide | `role="img"`, "hidebox" |
| Favicons and app icons | the tile, the box in lime | (none) | |
| The shared-link card (`og-s.png`) | 36 px on its 56 px tile | 31.7 px | |
| The film's end card | 160 px tile | 64 px under it | |
| README, social card | the kit's lockup | | `alt="hidebox"` |

Body text still says hidebox in words: the footer's legal line, the pages' sentences, titles and descriptions.
`og.png` keeps the old drawing (below).

## Two limes, the owner's call

The kit draws the box and the rhombus in `#ACFF00`; the site's lime is `--lime-400`, `#BCFE00` (`shared/tokens.css`,
and `#BCFE00` in the drive's `ui/tokens.css`). The brief first asked for one lime, the site's; while the pass ran the
owner asked to keep the kit exactly as handed over. So the logo is the kit's `#ACFF00`, literal, in both themes, and
the site's tokens are untouched: Open your drive, the tints, the selection and every other lime keep `#BCFE00`. Two
near-identical limes, the logo's and the site's (`#ACFF00` is a touch greener; on the ink tile 16.08:1 against
16.32:1).

- **The box** is `currentColor` in the sprite, as the kit's symbol; each tile sets `color: #ACFF00`: `.wm-tile`
  (`site.css`), the comparison's tile icon (`home.css`), `.brand-mark` (`drive.css`, the sidebar, the start screen, a
  folder link, the empty drive) and `.done-box` (`flow.css`). No token is added or changed.
- **The wordmark's letters** are `currentColor` (`--fg`: `#FAFAFA` in dark, `#0A0A0A` in light); the rhombus is
  `#ACFF00` in the sprite itself, so it can't follow the text colour or `--brand-text` (the olive lime-800 in light).
- **Standalone files** (`favicon.svg` and its copy, `shared/brand/symbol.svg`, `docs/media/hidebox-mark.svg`,
  `og/icon*.svg`), the holding page's inline lockup and the shared-link card write `#ACFF00`; `docs/media`'s two
  lockups and the six PNG and ICO icons are the kit's own files.
- **Light mode:** the box stays on its ink tile; the rhombus is lime on white (1.23:1), as the owner chose, and reads
  lighter there; on the comparison's lime tint (`#F4FFE6`, 1.19:1) it is faint (`compare-1440-light.png`). No dark
  green is in any mark, in either theme; the dark greens of light mode (`--lime-600` to `--lime-900`) stay on text and
  borders, as before.
- DESIGN.md's Brand paragraph says the mark is the kit's, in the kit's lime, kept apart from `--lime-400` by the
  owner's call.

## The kit's files, as they ship

| Kit file | Here | Changed |
|---|---|---|
| `snippets/i-hidebox.symbol.svg` | `web/shared/ui/icons.svg#i-hidebox` | the path re-encoded (below) |
| `snippets/wordmark-inline.svg` | `#i-wordmark` in the same sprite | the same; the outer `<svg>` is the page's (below) |
| `favicon.svg` | `web/site/static/favicon.svg` = `web/shared/brand/favicon.svg`; `symbol.svg` (120 px) | the same; named "hidebox" (`role="img"`, a title) as the kit's |
| `hidebox-lockup-{dark,light}.svg` | `docs/media/hidebox-lockup-{dark,light}.svg` | none: the kit's files |
| `favicon-32.png`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | `web/site/static/` | none: the kit's files, byte for byte |
| `hidebox-icon.svg`, `hidebox-wordmark-*.svg`, the lockup PNGs, `PREVIEW.png` | not shipped | the sprite and the SVG lockups cover them |

**The path data.** The kit's paths are absolute commands with three decimals: its favicon is 2,812 bytes, over V-02's
2,048-byte limit for the mark. Every point was rounded to two decimals and written as relative commands, the deltas taken
between rounded points so nothing drifts: the icon's path is 1,415 characters (2,568 in the kit), the wordmark's 2,382
and 96 (3,614 and 156). Every one of the 200, 270 and 12 points is within 0.005 units of the kit's (`kit-check.txt`,
`kit_check.py`), a fortieth of a pixel at 512 px. A space breaks the few runs of four dot-joined numbers that
`tools/lint.py` would read as an IP address.

**The rasters** are the kit's own files. `render-images.py` still draws them from SVG, so a later change to the mark
can be rendered: on a copy of this tree its output matches the kit's files in the same lime, the box covering the same
area within 0.4 % and its centre within 0.15 px; per pixel they differ by 0.05 to 0.36 % on average at 180 to 512 px,
and by 2 % at 32 px, where antialiasing is most of the picture. Like the kit's, `icon-192.png` and `icon-512.png` are
the rounded tile with transparent corners, `apple-touch-icon.png` is full bleed (iOS rounds it), and the maskable icon
draws the box at 70 % inside the 80 % safe zone (`og/icon-maskable.svg`'s offset matched to the kit's to the pixel).

## Sizes chosen

- **The header:** the kit's 17 px beside the 30 px tile. Its lockups (README, social card) set the name larger, about
  70 % of the tile; the header keeps the kit's stated 17/30. The wordmark is 74 px wide; at 390 px the header still
  fits the tile, the name, GitHub, Lights and Open your drive (`home-390-*.webp`), and under 380 px the GitHub link
  steps aside as before.
- **Elsewhere, 17/30 of the tile:** the comparison (12.5 px at 22 px), the drive's start screen and a folder link
  (18 px at 2rem), the shared-link card (31.7 px at 56 px). In the drive's sidebar the name sits over "My drive", so it
  is 16 px with 2 px under it: both lines fit inside the tile's 2rem (the first try at 18 px left the two lines
  touching; `drive-mark-*`).
- **The film's end card:** the wordmark 64 px tall under the 160 px tile, where the name stood in 72 px type.

## og.png

`og.png` is kept byte for byte, as the owner asked (the hero still). Its source, `og/og.html`, is
kept too, so `render-images.py` draws the same card. **Its brand row still shows the old three-stroke box (in
`#BCFE00`) and the name typed in Geist** at the top left. A candidate with the kit's box and wordmark in that row, in the
kit's lime, the rest unchanged, is `og-candidate.png` (146,845 bytes, under the 150 KB limit; `shots_brand.py` draws it
from `og.html` with only those elements swapped). Adopting it means the same swap in `og/og.html` (as `og-s.html` and
its `.viewer .tile.mark` rule in `og.css` have it) and running `render-images.py og.png`.

## Icons, the build and Caddy

- **`render-images.py`** draws every icon from SVG at its own size (an SVG without width and height fills the page):
  `favicon.svg` as `favicon-32.png`, `icon-192.png`, `icon-512.png` and, at 16, 32 and 48 px, the three PNG entries of
  `favicon.ico`; `og/icon.svg` as `apple-touch-icon.png`; `og/icon-maskable.svg` as `icon-maskable-512.png`. Named files
  render alone; the shipped icons are the kit's and only `og-s.png` was rendered for the release. `og/icon.html` is
  gone.
- **The manifest** lists `{"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}`
  after the two icons; only the icon entries changed.
- **The pages** link `/favicon.ico` first among their icons (the SEO pass added the link as `sizes="192x192"`, true of
  the old ICO, which held the 192 px icon). As the owner asked, it now says what the kit's file holds,
  `sizes="16x16 32x32 48x48"`, on every page that carries it: the five site pages and the 404, and the app's
  `app.html`, `view.html` and `drive.html`; the static files check holds every page to it. The holding build serves
  only `favicon.svg` and keeps its one link.
- **Text responses** (`/robots.txt`, `/llms.txt`, `/sitemap.xml`, `/status.json`) have no `<link>`, so the browser asks for
  `/favicon.ico`: Caddy answers it at the root for every route (`icons-served.json`), and its three entries are the
  kit's tile, the same drawing as `/favicon.svg` and `favicon-32.png` that the pages name, in the same lime
  (`ico-vs-svg.png`: each entry beside `favicon.svg` drawn by Chromium at that size; per pixel they differ by 1.2 to
  4 % on average, the kit's rasteriser smoothing a little more than Chromium's, at 48, 32 and 16 px).
- **The build** copies `web/site/static/` whole: 206 files (205 before: the maskable icon is new; `og/` is not served).
- **Caddy** (the production Caddyfile on the throwaway local stack, `icons_served.py`, `icons-served.json`): every icon,
  the manifest, both cards and the sprite answer 200 with the built bytes; `.ico` as `image/vnd.microsoft.icon`, PNGs as
  `image/png`, SVGs as `image/svg+xml` and the manifest as `application/manifest+json` (those two gzip-compressed). The
  cards and icons are kept a day (`public, max-age=86400`, the SEO pass's `@cards`); the new maskable icon joins that
  set here, and `test_config` holds every icon the manifest lists to it. The manifest and the sprite revalidate
  (`no-cache`). D-01 (`test_headers.py --local`): PASS, 77 checks, `/icon-maskable-512.png` among them. The SEO
  pass's `check-seo.py --dist` on a build of this branch: PASS (13 passed, 3 skipped).

## The README and the repository's pictures

There is no `docs/review/repo-marketing` in the repository; the README's pictures came from the UI suite's tools, run by hand, and
the social card from a template that wasn't kept. `shots_brand.py --readme` now makes all four from a local build, the
way they were: `home.webp` (`/` at 1440 × 900, dark), `drive.webp` (960 × 600, dark: notes.txt shared Once, agenda.txt
Private), `share.webp` (960 × 600, light: the share window's result, its QR blurred) and `social-preview.png`
(1280 × 640, from `social-preview.html` beside the script: the kit's lockup, the home's headline and line, the address,
the hero's still, the field's grid). Sizes: 39,562, 19,858, 23,350 and 219,446 bytes (41,462, 17,336, 26,156 and
254,596 before).

The README's heading is the kit's lockup in a `<picture>`: the light lockup (ink letters), and the dark one under
GitHub's dark theme, `alt="hidebox"`. The README had no `<picture>` before; a single dark lockup would have white
letters on GitHub's white page. `docs/media/hidebox-mark.svg` is the kit's tile; nothing links it now, and it stays for
anyone who used its address. GitHub's social card is set by hand in the repository's settings: the owner uploads the new
`social-preview.png`.

## The checks, changed

| Check | Before | After |
|---|---|---|
| V-02 static (`check_home_stills`) | the favicon, its copy and `symbol.svg` hold the three stroke paths and `#BCFE00`; the sprite's `i-hidebox` clean and drawing them; the header's tile draws `#i-hidebox` | every SVG the pages draw from (both sprites, the favicon and its copy, `symbol.svg`) parses as XML; the three files draw the sprite's exact `i-hidebox` path in the kit's `#ACFF00` on the ink tile, at most 2,048 B; `i-hidebox` has no stroke or `fill="none"`; `i-wordmark` is clean with exactly two fills, `currentColor` and `#ACFF00`; each tile's rule (`.wm-tile`, the comparison's, `.brand-mark`, `.done-box`) draws the box `#ACFF00`; the header's link keeps "{{BRAND}}, home" and holds the wordmark, hidden; the comparison's head on `/` and `/v2` holds it with the name in an sr-only span; the home's icons are `/favicon.ico`, `/favicon-32.png`, `/favicon.svg` |
| Static files (`check_static`, M-04) | the manifest's icons exist; the PNG icons' sizes; `favicon.ico` is an ICO | also: the manifest lists `/icon-maskable-512.png` with purpose maskable, which is 512 × 512; `favicon.ico` holds exactly 16, 32 and 48 px, and every page's link to it says so |
| Deploy (`test_config`) | the Caddyfile's `@cards` equals `headers_spec.CARDS` | also: every icon the manifest lists is in that set |
| V-02 browser (`check_home_stills`) | the header's and the comparison's tiles draw `#i-hidebox` in `rgb(188, 254, 0)` on `rgb(10, 10, 10)` in both themes | the tiles in `rgb(172, 255, 0)` (the kit's lime), no stroke on either; the wordmark beside each from `#i-wordmark`, `aria-hidden`, 17 px and 12.5 px, in `rgb(250, 250, 250)` dark and `rgb(10, 10, 10)` light, the names "hidebox, home" and "hidebox" |

The XML rule came from this pass's first screenshots: a `--` in the sprite's comment made the whole sprite unreadable
and no icon showed on any page, and no check noticed. Sixteen broken copies were each caught by the new static
rules: that comment, a stroke on the box, a dark-green rhombus, the rhombus in the site's lime, the favicon's path
drifting from the sprite's, the site's lime in `symbol.svg`, the header's tile and Delivered's tile on the site's token,
the header drawing another symbol, its wordmark not hidden, its link without a label, the comparison's column without
its name in words on `/` and on `/v2`, the manifest without the maskable purpose, an ICO with one entry, a page's ICO
link still saying 192 px. With the maskable icon out of Caddy's `@cards` and `CARDS`, `test_config` fails. The UI
suite's one change: its drive look check (`drive-v3`) expects the tile's box in `rgb(172, 255, 0)`. The Impeccable detector over the changed files found nothing on a changed line of product
code (25 findings, all on lines that were already there, or the social card's template, which keeps the old card's
grid, Geist and 64 px headline).

An independent review of the branch (the code-critic agent: lint, check-copy, the static site suite, the deploy tests,
a build, its own 27 mutants of the static rules, the ICO's entries, the maskable icon's safe zone, a sweep for private
names) returned FAIL on three small points, all fixed: the end card's wordmark came out at 77 % of its size, because
librsvg had no ratio for a standalone SVG with only a viewBox (it now has a width and height; `endcard.png` drawn again),
a comment in `film.py` that told history, and three numbers in this review taken by another gzip method. Of its nits,
the outer `viewBox` around each `<use>` of the wordmark (it shifted the letters half a unit) is gone and the static
checks now cover `/v2`, the maskable icon, the ICO and `#ACFF00`; the drive's wordmark has no check of its own in the UI
suite (the screenshots and the drive's code show it). The rebase on the SEO pass and the switch to the kit's lime came
after that review; the suites, D-01 and the screenshots below are from the final tree.

## Budgets

Before is `main` at `13382af` (the SEO pass, as its own final runs measured it:
`docs/evidence/2026-10-19/seo-1/suites/`); after is this branch's final tree (`suites/`), both on the server as `build`.
On `main` before the SEO pass (`9bfee2c`) the same checks gave M-01 58.3 KB and 133.2 KB, V-02 257,769 / 243,852 B at
load, and the rest as in the before column.

| Budget | Limit | Before | After |
|---|---|---|---|
| M-01: HTML+CSS+JS on `/`, gzip | 60 KB | 58.4 KB | 58.6 KB |
| M-01: everything at load | 400 KB | 160.1 KB | 145.2 KB (moves from run to run with the lazy stills; the sprite adds 4 KB, as the test server compresses nothing) |
| A-06: the widget on a phone, at load / after a drop | 40,960 B | 25,013 / 40,510 B | 25,013 / 40,510 B |
| A-06: a computer with the code to scan | 43,520 B | 43,477 B | 43,477 B |
| A-06: a phone after a photo | 49,152 B | 45,548 B | 45,548 B |
| A-06d: `/drive` until its table renders | 131,072 B | 123,202 B | 125,365 B (the sprite, 1,704 B more; `wordmark()` and the drive's CSS) |
| A-06h: `home.css`, gzip -9 | 1,770 + 3,328 B | 4,114 B | 4,169 B |
| A-06h: the home's stylesheets | 8,704 B | 8,256 B | 8,311 B |
| V-02: the mark (`favicon.svg`, `symbol.svg`) | 2,048 B | 461 / 463 B | 1,697 / 1,687 B |
| V-02: `media/v3/`, `v3.css` | 524,288 / 2,048 B | 480,262 / 970 B | unchanged |
| V-02: `/` at load, 1440 / 390 | 512 KiB | 252,027 / 245,233 B | 303,244 / 253,102 B (it varies with what arrives before the count: 257,829 and 268,633 B at 1440 in two earlier runs of this branch; the page and its stills are as before) |
| `og.png` / `og-s.png` | 150 KB each | 142,970 / 50,018 B | 142,970 / 48,468 B |
| The icons (no budget): `favicon-32.png`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | | 717 / 2,206 / 2,215 / 2,184 / 5,761 B / (none) | the kit's: 1,597 / 5,142 / 5,147 / 7,072 / 19,129 / 10,572 B |

The sprite (`shared/ui/icons.svg`) grows from 27,258 to 31,300 bytes (5,946 to 7,650 gzip -9): the filled box and
the wordmark. It is not HTML, CSS or JS, so M-01's 60 KB doesn't count it, which is why the header draws the wordmark
from the sprite and not inline: inline, the kit's snippet is 1,782 bytes gzip (1,214 re-encoded) in every page's HTML,
with M-01 at 58.3 of 60 KB, and a parallel pass is adding to the home's head. A-06d counts the sprite.

## Suites

On the server as `build`, on this branch's final tree (`suites/`, `3fdf09f` and the docs; the README pictures'
commit after it changes no code):

| Suite | Result |
|---|---|
| lint | PASS (0 problems) |
| check-copy | PASS (0 problems) |
| `tools/build.py` | OK: 206 files, 7 pages, 6 vendored files checked |
| app core (`web/app/tests/run_all.py`) | ALL PASS (9 steps) |
| deploy | 89 tests OK (86 before: the SEO pass's three) |
| server | 331 tests OK (5 skipped) |
| site (`web/site/tests/run.py`) | 42/42 |
| UI (`web/app/ui/tests/run.py`) | 804/804 |
| D-01, `tests/e2e/test_headers.py --local` (the production Caddyfile on the throwaway stack) | PASS, 77 checks |
| `tools/check-seo.py --dist` on a build of this branch | PASS (13 passed, 3 skipped) |

One earlier run of the site suite (before the rebase) failed one check that asks GitHub, as a stranger, whether
private vulnerability reporting is on for the repository: it answered no for a while and yes again in the next run.
It is outside this pass; the final run passed it.

## Screenshots

`shots_brand.py` (the UI suite's own tools on the server as `build`: the build, the dev server and its fake chain,
headless Chromium), the same script on `main`'s tree for `before/`:

- `after/` and `before/`: `<surface>-<width>-<theme>.webp` at 1440 × 900 and 390 × 844 (pictured at 1.5×), dark and
  light: `home`, `judges`, `drive` (1440) and `drive-sheet` (390, the sidebar in its sheet), `drive-start`, `delivered`,
  `folder`, `holding`; after only: `missing` (the 404), `link-missing` (a link that doesn't exist), `drive-empty`.
  Close-ups at 4×, PNG: `header-*` (the header's lockup), `compare-1440-*`, `drive-mark-*`, `drive-start-mark-*`,
  `folder-mark-*`.
- `/how`, `/made`, `/fine-print` and `/v2` were shot and looked at too (the same header); they are left out to keep the
  folder small.
- `endcard.png`: the film's end card from `endcard.py`, which runs film.py's own end-card filters on blank inputs.
- `og-candidate.png`: above.

The best four: `header-1440-light.png` against `before/header-1440-light.png`, `drive-mark-1440-dark.png`,
`delivered-390-light.webp`, `home-390-dark.webp`.

## Open, for the integrator

- **Deploy** from `main` (the integrator's), then verify-deploy and D-01; the film needs rendering again for its end card.
- **GitHub's social card:** upload `docs/media/social-preview.png` in the repository's settings (the owner).
- **`og.png`:** the owner's call between keeping it and `og-candidate.png` (above).
- **The holding page's words** still speak of the ghost ("Show it once. Then bye.", "The ghost opens on this page
  soon.") and its theme colours are the old indigo: only its mark changed here.
- **The rhombus in light mode** is faint on white and fainter on the comparison's lime tint; that is the owner's rule
  (lime in both themes). If it ever should read better there, a 1 px ink edge or a slightly larger rhombus on light
  pages are the options; neither is done.
- **Real devices** were not seen (headless Chromium only): the SVG favicon and the maskable icon on a phone's home screen.
