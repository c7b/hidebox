<!-- SPDX-License-Identifier: MIT -->
# Performance and caching (2026-10-20)

The owner's P6: performance and caching, with no DNS or CDN move during judging. Every asset a page asks for now has
a hash of its content in its name and is kept a year; text is served from Brotli and gzip copies made ahead of time;
the share cards and icons are smaller with the same pixels; `/v2`, its four videos and the screenshots no test makes
any more are gone. Branch `site/perf-1`, rebased on `main` and pushed to it; **not deployed**. Evidence:
[`docs/evidence/2026-10-20/perf-1/`](../evidence/2026-10-20/perf-1/).

## In one table

| | Before (`4d38049`, main before this pass) | After (this branch) |
|---|---|---|
| The home, first visit, 1440 | 156,319 B on the wire, 36 requests | **141,621 B** (−9.4 %), 36 requests |
| The home, repeat visit | 26,194 B, 30 requests reach the network (28 answered 304) | **3,722 B**, 3 requests (the page's 304, `/api/v1/config`, the anti-bot challenge) |
| The home, after a release (nothing changed) | 103,811 B (every stylesheet and script again: a deploy moves every file's time, which is Caddy's ETag) | **9,762 B** |
| `/drive` at 390: first / repeat / after a release | 221,807 / 34,885 / 168,804 B | **198,103 / 3,043 / 5,837 B** |
| Reading pages (`/how`, `/made`, `/judges`, `/fine-print`), repeat visit | 8,809 to 10,238 B, 12 to 14 requests | **738 B**, 1 request (the page's 304) |
| Text on the wire | `encode`'s on-the-fly zstd (Chromium) or gzip | Brotli 11 or gzip -9 made ahead of time |
| Stylesheets, scripts, pictures, fonts, sprites, JSON, wasm | `no-cache` or a day | **a year, `immutable`**, under content-hashed names |
| Picture files served | 12,032,052 B (the /v2 videos and posters 11.2 MB) | 805,120 B |
| M-01, HTML+CSS+JS on `/`, gzip (of 60 KB) | 58.9 KB | **58.1 KB** |
| A-06, the widget after a drop: phone / computer (of 40,960 / 43,520 B) | 40,510 / 43,477 B gzip -9 | **35,552 / 38,235 B** as sent (Brotli); gzip -9 41,263 / 44,240 B |
| A-06d, `/drive` until the table (of 131,072 B) | 126,662 B gzip -9 | **110,822 B** as sent; gzip -9 128,122 B |
| Deleted | | 12,124,781 B: `/v2`, its loops and `clips.js`, 22 dead screenshots, `v2.css`'s loop rules |

## Pictures

Every picture a page shows was already AVIF with a WebP fallback, in a `<picture>` with `srcset` and `sizes`: the
home's five stills and the 404 art (both made by the stills' ffmpeg pipeline, `docs/review/home-v3.md`), and the
drive's start screen, which shows the home's hero. Nothing there was re-encoded: the owner's source PNGs are not in
the repository or on the server, and encoding an AVIF or WebP again from its own output loses detail for no gain.
What this pass changed:

- **The rest are PNG because they have to be:** `favicon-32.png`, `apple-touch-icon.png` (iOS takes only PNG),
  `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (the web manifest's install icons), `og.png` and `og-s.png`
  (link previews: several unfurlers take no AVIF or WebP), and the PNGs inside `favicon.ico`. They are the
  "fallback where needed", and they are now smaller with the same pixels: `web/site/tools/png_shrink.py` decodes every
  pixel and writes the smallest lossless form (RGB when nothing is translucent, a palette for 256 colours or fewer,
  the best PNG filter per row, zlib 9), checks every pixel before it writes, and `render-images.py` runs it on
  everything it renders. ffmpeg on the server, an independent decoder, gives the same RGBA for every file before and
  after (`images/png-pixels.txt`).
- **og.png keeps its look:** 142,970 to 141,178 B, the same pixels (it is a photograph of the home's first screen: a
  palette can't hold it without loss, so the gain is the filters and zlib).
- **The sprites and SVG marks** are text: they go out as Brotli (the Lucide sprite, 31,300 B, is 6,440 B on the wire).
- **Right-sized:** at 1440 (1x) and 390 (3x), scrolled through, every picture's `sizes` picks the smallest candidate
  that covers the device pixels it is drawn at, or the largest there is (`pictures` below).

Every picture file the build serves, in bytes (the plain names; the hashed copies hold the same bytes), and the Brotli copy
a browser gets for the SVGs:

| File | Before | After | After, br |
|---|--:|--:|--:|
| `apple-touch-icon.png` | 5,147 | 2,319 |  |
| `favicon-32.png` | 1,597 | 1,042 |  |
| `favicon.ico` | 5,142 | 3,889 |  |
| `favicon.svg` | 1,697 | 1,697 | 643 |
| `icon-192.png` | 7,072 | 4,276 |  |
| `icon-512.png` | 19,129 | 11,888 |  |
| `icon-maskable-512.png` | 10,572 | 4,722 |  |
| `og-s.png` | 48,468 | 24,901 |  |
| `og.png` | 142,970 | 141,178 |  |
| `shared/brand/favicon.svg` | 1,697 | 1,697 | 643 |
| `shared/brand/symbol.svg` | 1,687 | 1,687 | 634 |
| `shared/icons.svg` | 5,013 | 5,024 | 1,065 |
| `shared/ui/icons.svg` | 31,300 | 31,300 | 6,440 |
| `site/media/404/box-zero-480.avif` | 6,574 | 6,574 |  |
| `site/media/404/box-zero-480.webp` | 9,612 | 9,612 |  |
| `site/media/404/box-zero-720.avif` | 11,088 | 11,088 |  |
| `site/media/404/box-zero-720.webp` | 17,532 | 17,532 |  |
| `site/media/404/box-zero-960.avif` | 16,450 | 16,450 |  |
| `site/media/404/box-zero-960.webp` | 27,982 | 27,982 |  |
| `site/media/motion/hidebox-A-hero.mp4` | 403,555 | deleted |  |
| `site/media/motion/hidebox-A-hero.webm` | 2,375,563 | deleted |  |
| `site/media/motion/hidebox-A-hero_poster.png` | 238,804 | deleted |  |
| `site/media/motion/hidebox-B-sides.mp4` | 143,659 | deleted |  |
| `site/media/motion/hidebox-B-sides.webm` | 886,021 | deleted |  |
| `site/media/motion/hidebox-B-sides_poster.png` | 219,268 | deleted |  |
| `site/media/motion/hidebox-C-encrypt.mp4` | 314,639 | deleted |  |
| `site/media/motion/hidebox-C-encrypt.webm` | 2,564,279 | deleted |  |
| `site/media/motion/hidebox-C-encrypt_poster.png` | 232,188 | deleted |  |
| `site/media/motion/hidebox-D-pay.mp4` | 379,646 | deleted |  |
| `site/media/motion/hidebox-D-pay.webm` | 3,241,933 | deleted |  |
| `site/media/motion/hidebox-D-pay_poster.png` | 181,506 | deleted |  |
| `site/media/v3/different-1536.avif` | 34,113 | 34,113 |  |
| `site/media/v3/different-1536.webp` | 48,274 | 48,274 |  |
| `site/media/v3/different-640.avif` | 6,895 | 6,895 |  |
| `site/media/v3/different-640.webp` | 9,244 | 9,244 |  |
| `site/media/v3/different-960.avif` | 14,985 | 14,985 |  |
| `site/media/v3/different-960.webp` | 19,430 | 19,430 |  |
| `site/media/v3/gem-1024.avif` | 20,176 | 20,176 |  |
| `site/media/v3/gem-1024.webp` | 35,932 | 35,932 |  |
| `site/media/v3/gem-480.avif` | 6,975 | 6,975 |  |
| `site/media/v3/gem-480.webp` | 10,878 | 10,878 |  |
| `site/media/v3/gem-720.avif` | 12,145 | 12,145 |  |
| `site/media/v3/gem-720.webp` | 19,688 | 19,688 |  |
| `site/media/v3/hero-1024.avif` | 25,611 | 25,611 |  |
| `site/media/v3/hero-1024.webp` | 46,530 | 46,530 |  |
| `site/media/v3/hero-480.avif` | 9,209 | 9,209 |  |
| `site/media/v3/hero-480.webp` | 14,838 | 14,838 |  |
| `site/media/v3/hero-720.avif` | 15,311 | 15,311 |  |
| `site/media/v3/hero-720.webp` | 26,558 | 26,558 |  |
| `site/media/v3/who-1024.avif` | 18,514 | 18,514 |  |
| `site/media/v3/who-1024.webp` | 35,070 | 35,070 |  |
| `site/media/v3/who-480.avif` | 6,896 | 6,896 |  |
| `site/media/v3/who-480.webp` | 11,236 | 11,236 |  |
| `site/media/v3/who-720.avif` | 11,442 | 11,442 |  |
| `site/media/v3/who-720.webp` | 20,312 | 20,312 |  |
| **all** | **12,032,052** | **805,120** | |


The candidates Chromium took on the branch, each page scrolled through (`pictures` in `probe-after.json`). The
home's closing names the hero's `srcset` on purpose, so it reuses the hero's bytes; a phone at 3x needs 1,074 px
and gets the largest candidate, or the next one up:

| Page | Picture | Shown (CSS px) | Device px needed | Candidate taken (w) | Its file |
|---|---|--:|--:|--:|--:|
| `/ @1440` | `/site/media/v3/hero-720.avif` | 515 | 515 | 720 | 15,311 |
| `/ @1440` | `/site/media/v3/different-640.avif` | 512 | 512 | 640 | 6,895 |
| `/ @1440` | `/site/media/v3/who-480.avif` | 433 | 433 | 480 | 6,896 |
| `/ @1440` | `/site/media/v3/gem-480.avif` | 465 | 465 | 480 | 6,975 |
| `/ @1440` | `/site/media/v3/hero-720.avif` | 360 | 360 | 720 | 15,311 |
| `/this-page-does-not-exist @1440` | `/site/media/404/box-zero-480.avif` | 480 | 480 | 480 | 6,574 |
| `/drive @1440` | `/site/media/v3/hero-480.avif` | 416 | 416 | 480 | 9,209 |
| `/ @390` | `/site/media/v3/hero-1024.avif` | 358 | 1074 | 1024 | 25,611 |
| `/ @390` | `/site/media/v3/different-1536.avif` | 358 | 1074 | 1536 | 34,113 |
| `/ @390` | `/site/media/v3/who-1024.avif` | 358 | 1074 | 1024 | 18,514 |
| `/ @390` | `/site/media/v3/gem-1024.avif` | 358 | 1074 | 1024 | 20,176 |
| `/ @390` | `/site/media/v3/hero-1024.avif` | 358 | 1074 | 1024 | 25,611 |
| `/this-page-does-not-exist @390` | `/site/media/404/box-zero-960.avif` | 358 | 1074 | 960 | 16,450 |
| `/drive @390` | `/site/media/v3/hero-1024.avif` | 358 | 1074 | 1024 | 25,611 |

## Fingerprinted names

**How.** `tools/build.py` has a new step after placeholders and before SRI, `tools/assets.py`: every file that a page,
stylesheet, script, SVG or the web manifest asks for by a local URL (stylesheets, scripts, pictures, fonts, sprites,
JSON, the wasm) gets a copy named `name.<10 hex>.ext` beside it, the hex being the start of the SHA-256 of its bytes,
and every reference to it in the build is rewritten (a relative reference stays relative, `?query` and `#fragment`
stay). A file's hash covers its bytes after its own references are rewritten, so a change in one module renames
every module that leads to it. Files that ask for each other (four cycles today: `pow.js` and its worker, `card.js`
and three of the widget's modules, `canary.js` and `reveal.js`, and the old sprite, which names itself) share one hash
of their joint content. 170 assets today: 111 scripts, 17 stylesheets, 2 sprites, 30 stills and art (AVIF and WebP), 4
icons, 2 fonts, the 2 i18n JSON files, the word list and the wasm. Only what the pages and the web manifest reach is
copied: a file only an unreached script names (a test module, the old `/vendor/` copy of the shim) keeps its plain name. Nothing in it is specific to a page or a folder, so a new file anyone adds under `web/` is picked up as soon
as something names it in a string; the site suite fails if a script builds a fingerprinted file's address at run
time instead (a template literal with its path, or a string that is the start of its name), as three app modules
did: `core.js` and `scene.js` (the sprites) and `drive-start.js` (the hero still) now name the files in whole
strings, so the build rewrites them.

**Entry points keep their names:** the pages, `/favicon.ico`, `/favicon.svg`, `/apple-touch-icon.png`, `og.png`,
`og-s.png`, the web manifest, `robots.txt`, the sitemap, `llms.txt`, `llms-full.txt` and `.well-known/`. Absolute URLs
(the `og:image` and JSON-LD addresses) are names other products keep, and are left alone. The plain names of the
fingerprinted files stay in the build with the same bytes and their old caching, so anything cached elsewhere or
typed by hand still answers, and a module loaded under its plain name imports the hashed ones (one module graph).

**What the manifest says.** `files` lists both names (same hash); the new `assets` maps each plain name to its hashed
one. The `.gz` and `.br` copies are not in it: they are written after it and decode to a listed file.

**Deterministic.** Two builds of one tree give the same names and the same bytes, `.gz` copies included (the site
suite builds twice and compares; the deploy tests check the names, a cycle, and that a change reaches its importers).

**Caddy** (`deploy/caddy/Caddyfile`): two routes ahead of every other file route match `\.[0-9a-f]{10}\.[a-z0-9]+$`
(the build's own pattern; a source file named like that stops the build): `@hashed_app` (`/app/*`, `/vendor/*`, the
app policy, a worker's script sets its worker's, and `noindex`) and `@hashed` (the site policy). Both send
`Cache-Control: public, max-age=31536000, immutable`. A hashed name no build made is the 404 page, never stored.

**A tab opened before a release** keeps asking for the old names (a module the drive imports later, a picture that
loads lazily). `deploy/scripts/carry-assets.py`, run by `activate-release.sh` before the switch, copies the live
release's own hashed files and their compressed copies into the new release, for one release (only names in the old
release's manifest, never what it carried itself; nothing is overwritten; the new manifest doesn't list them).

### What is cached how

| What | Before | After |
|---|---|---|
| Stylesheets, scripts, the i18n JSON, the sprites, the wasm | `no-cache` (revalidated every visit; Caddy's ETag is the file's time and size, and a deploy rewrites every file, so after a release every one is downloaded again) | the hashed names: `public, max-age=31536000, immutable`; the plain names as before |
| Fonts (`/shared/fonts/`), the stills and the 404 art (`/site/media/`) | `public, max-age=86400` | hashed: a year, immutable; plain: a day |
| `favicon-32.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | a day, loadable from any origin | hashed (the pages and the manifest name these): a year, same origin only (only this site's pages and manifest load them); plain: a day, any origin, for whatever a link preview or a crawler asks for |
| Pages, `/favicon.ico`, `/favicon.svg`, `/apple-touch-icon.png`, `og.png`, `og-s.png`, the manifest, `robots.txt`, the sitemap, `.well-known/` | as now | unchanged (`no-cache`, a day, or an hour); the pages and the manifest now name hashed files |
| The 404 page, the API | `no-store`; the API's own | unchanged |

### Precompressed text

Caddy's `file_server` serves `name.br` or `name.gz` beside a file when the browser accepts that encoding (`precompressed
br gzip`; it looks for the plain file first, sets `Content-Encoding` and `Vary: Accept-Encoding`, and `encode` leaves
the answer alone). Every route that serves text uses it, the 404 page included. `deploy/scripts/precompress.py` writes
the copies for every HTML, CSS, JS, SVG, JSON, web manifest, text, XML and wasm file of 512 B or more (smaller ones
`encode` leaves alone too), only when smaller, compressing identical files once:

- **gzip -9** with Python's zlib, no file name, mtime 0 (the same bytes every build).
- **Brotli, quality 11:** the server has two Brotli encoders that need no install. Debian's `python3-brotli`
  (provision.sh installs it for fontTools' WOFF2) is not the standard library, which the repository's Python must be
  (`tools/lint.py` refuses the import); Node, which provision.sh installs for the sidecar and the tests, has Brotli in
  its built-in `zlib` (no package). `precompress.py` uses `node` when it is on the PATH and decodes each copy again
  before it keeps it. The build runs it on the workstation; `activate-release.sh` runs it again on the server, so a
  build made without Node still gets its `.br` files. Without Node anywhere: gzip only, and Caddy's `encode` as before.

Before, a browser got `encode`'s on-the-fly zstd or gzip at their default levels.

### verify-deploy, D-01 and the other checks

- `tools/verify-deploy.py` still compares every file of the live manifest with a clean build of the commit, and now
  asks for each text file again with `Accept-Encoding: gzip` and `br`, since a browser gets those copies: what each
  answer decodes to must be the file (gzip with Python's zlib; br with Node's when `node` is on the PATH, else counted
  as not decoded). Run against the throwaway stack with a clean build of the branch: 0 differences across 374 files, 288 gzip and
  286 br answers decoded to the build's bytes (`verify-deploy-local.txt`).
- D-01 (`tests/e2e/test_headers.py`, `headers_spec.HASHED`, `HASHED_MISSING`, `PRECOMPRESSED_*`): one asset of each
  kind, looked up in the live manifest's `assets`: 200, its plain name's type, a year and immutable, its folder's
  policy (`noindex` under `/app/`); two made-up hashed names are the 404 page, `no-store`; assets and pages answer br,
  gzip that decodes to the file, or the file, as the browser accepts, each with `Vary`. Its requests no longer carry
  `http.client`'s own `Accept-Encoding: identity` beside the one asked for (Caddy read the first).
- `tests/e2e/test_fonts.py` accepts the fonts' hashed copies (same pinned bytes); the UI flows compare asset
  addresses by their plain names (`plain()`); `deploy/tests` cover the build step, the Caddyfile routes, the
  verify-deploy check and carry-assets.

## Dead content removed

| What | Size | Why it was dead |
|---|--:|---|
| `web/site/pages/v2.html` (`/v2`) | 23,424 B | No page, partial, script, sitemap, `llms*.txt` or the claim registry linked it (searched: the whole repository, the docs, the tests). The review documents that name it are dated records. `/v2` and `/v2/` now answer 301 to `/`, like `/v3` |
| `web/site/js/clips.js` | 3,443 B | `/v2`'s loops only |
| `web/site/media/motion/` (12 files: four loops as WebM and MP4, and their PNG posters; the hero's is the old hero) | 11,181,061 B | `/v2` only |
| `v2.css`: the rules only the loops used (the video and poster crop, the WebKit black stage, the Pause switch) | 2,539 B (810 B gzip on the home) | The home loads `v2.css` for its layout; its stages hold stills (`v3.css`) |
| `web/app/shots/dropflow-*.webp` (18) and `ghost-states-*.webp` (3) | 914,314 B with the next row | Curated screenshots of flows the drive replaced (`no-ghost` replaced `ghost-states`); no flow makes them and nothing names them |
| `web/site/shots/made-390-light-full.webp` | 0 B | Empty: /made at 390 is taller than a WebP can be. `shots.py` now says so instead of writing an empty file |

**Kept on purpose:** the other curated shots (each one is written by a current flow or `shots.py`); the review
folders' screenshots under `docs/review/` and `docs/evidence/` (dated records); `web/app/tests/evidence/run-html.png`
(`ACCEPTANCE-core.md` names it); the Mutis Script fonts in `web/shared/fonts/` (not served; their tools, licence and
the D-01 check that they 404 still refer to them; that is a separate cleanup).

## Proof

`tests/e2e/perf_probe.py` (new) builds a tree onto the production Caddyfile's throwaway stack on the server
(`localstack.py`: Caddy 2.6.2 and `mutis-api --dev`) and loads each page in headless Chromium there, at 1440 (1x) and
390 (3x), each in a fresh profile: the first visit, a repeat visit (a new navigation in the same profile), and a visit
after a release (every file's time moved, as a deploy moves it). Bytes are Chromium's `encodedDataLength`: headers and
body as sent. Before: `--ref 4d38049` (main before this pass when it was measured, its own build and Caddyfile); after: the
branch on that commit (the security audit landed on main after it; the branch is rebased onto it, and the suites below
ran on that). The
stack is plain HTTP on the loopback, where Chromium still offers `br` and `zstd`. JSON: `probe-before.json`,
`probe-after.json`; the tables come from `tables.py`.

| Page | First visit before | after | Requests | Images at load before | after | Repeat visit before | after | Requests to the network before | after | After a release before | after |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/ @1440` | 156,319 | 141,621 | 36 → 36 | 40,584 | 37,520 | 26,194 | 3,722 | 30 (28 × 304) | 3 (1 × 304) | 103,811 | 9,762 |
| `/how @1440` | 142,553 | 131,608 | 18 → 18 | 16,709 | 13,617 | 10,238 | 738 | 14 (14 × 304) | 1 (1 × 304) | 62,271 | 5,225 |
| `/made @1440` | 149,079 | 136,608 | 17 → 17 | 16,709 | 13,617 | 8,809 | 738 | 12 (12 × 304) | 1 (1 × 304) | 67,860 | 17,234 |
| `/judges @1440` | 136,332 | 126,355 | 17 → 17 | 16,709 | 13,617 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 56,050 | 4,969 |
| `/fine-print @1440` | 139,299 | 128,805 | 17 → 17 | 18,830 | 15,577 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 59,017 | 8,735 |
| `/this-page-does-not-exist @1440` | 140,186 | 127,483 | 17 → 17 | 24,117 | 21,039 | 15,594 | 2,995 | 12 (11 × 304) | 1 (0 × 304) | 52,496 | 2,995 |
| `/drive @1440` | 205,404 | 181,700 | 41 → 41 | 26,752 | 23,674 | 34,885 | 3,043 | 37 (36 × 304) | 2 (1 × 304) | 168,804 | 5,837 |
| `/ @390` | 158,890 | 144,178 | 35 → 35 | 43,155 | 40,077 | 26,194 | 3,722 | 30 (28 × 304) | 3 (1 × 304) | 103,811 | 9,762 |
| `/how @390` | 142,553 | 131,608 | 18 → 18 | 16,709 | 13,617 | 10,238 | 738 | 14 (14 × 304) | 1 (1 × 304) | 62,271 | 5,225 |
| `/made @390` | 149,079 | 136,608 | 17 → 17 | 16,709 | 13,617 | 8,809 | 738 | 12 (12 × 304) | 1 (1 × 304) | 67,860 | 17,234 |
| `/judges @390` | 136,332 | 126,355 | 17 → 17 | 16,709 | 13,617 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 56,050 | 4,969 |
| `/fine-print @390` | 139,299 | 128,805 | 17 → 17 | 18,830 | 15,577 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 59,017 | 8,735 |
| `/this-page-does-not-exist @390` | 150,063 | 137,360 | 17 → 17 | 33,994 | 30,916 | 15,594 | 2,995 | 12 (11 × 304) | 1 (0 × 304) | 52,496 | 2,995 |
| `/drive @390` | 221,807 | 198,103 | 41 → 41 | 43,155 | 40,077 | 34,885 | 3,043 | 37 (36 × 304) | 2 (1 × 304) | 168,804 | 5,837 |

What a repeat visit still asks the network for, after:

- `/ @1440`: / (304), /api/v1/config (200), /api/v1/pow (403)
- `/how @1440`: /how (304)
- `/made @1440`: /made (304)
- `/judges @1440`: /judges (304)
- `/fine-print @1440`: /fine-print (304)
- `/this-page-does-not-exist @1440`: /this-page-does-not-exist (404)
- `/drive @1440`: /api/v1/config (200), /drive (304)
- `/ @390`: / (304), /api/v1/config (200), /api/v1/pow (403)
- `/how @390`: /how (304)
- `/made @390`: /made (304)
- `/judges @390`: /judges (304)
- `/fine-print @390`: /fine-print (304)
- `/this-page-does-not-exist @390`: /this-page-does-not-exist (404)
- `/drive @390`: /api/v1/config (200), /drive (304)

`--check` (the after run: PASS) fails on any same-origin file a page asks for that is neither fingerprinted nor an
entry point, a hashed answer that isn't `public, max-age=31536000, immutable`, a text answer of 512 B or more that
arrives uncompressed, or a repeat visit that asks the network for a hashed file.

### The budgets

| Budget (limit) | Before (`4d38049`) | After (the branch) |
|---|---|---|
| M-01: HTML+CSS+JS on `/`, gzip (60 KB) | 58.9 KB | 58.1 KB (`v2.css` lost the loops' rules; the site suite measures the sources, without hashes) |
| M-01: everything at load (400 KB) | 145.4 KB, 38 requests | 143.5 KB, 38 requests |
| A-06: the widget on a phone, at load / after a drop (40,960 B) | 25,013 / 40,510 B gzip -9 | 21,714 / 35,552 B as sent (gzip -9: 41,263 B) |
| A-06: on a computer, with the code to scan (43,520 B) | 43,477 B gzip -9 | 38,235 B as sent (gzip -9: 44,240 B) |
| A-06: a phone after a photo (49,152 B) | 45,548 B gzip -9 | 40,002 B as sent |
| A-06d: `/drive` until the table renders (131,072 B) | 126,662 B gzip -9, 38 files | 110,822 B as sent (gzip -9: 128,122 B), 38 files |
| V-02: `/` at load, 1440 / 390 (512 KiB) | 303,763 / 253,621 B (272,231 B at 1440 in the two earlier base runs: a lazy still arrives before the count or not) | 268,485 / 251,128 B (292,894 and 299,826 B at 1440 in two earlier branch runs, the same variance) |
| V-02: after scrolling through, 1440 / 390 (1 MiB) | 318,090 / 275,071 B | 282,812 / 272,578 B |
| V-02: `media/v3`, `v3.css` gzip (512 KiB, 2,048 B) | 480,262 B, 970 B | 480,262 B, 960 B |

**A-06 and A-06d now count what the server sends.** The budgets measured gzip -9 of each file because Caddy compressed
on the fly. It now sends each file's Brotli copy (quality 11) to every browser that takes br (Chromium, Firefox and
Safari all do), so the scenarios count that copy, and print gzip -9 of the same files beside it. Measured the old way,
the fingerprints cost 763 B on the computer's widget path: each import names a hash, and a hash doesn't compress.
That alone would have put the QR waiver 720 B over its ceiling (it had 43 B of room) and the phone's first drop 303 B
over 40 KB (`suites/first-run-ui-budget.txt`, the first full run). What a visitor downloads went down 12 % instead.
The sources the authors write are unchanged by this, and M-01 (the site suite, on the sources) still measures gzip.

## Suites

On the server as `build`, on the rebased branch (`suites/final/`, `done.txt` holds the exit codes):

| Suite | Result |
|---|---|
| Lint, check-copy, `tools/build.py` | PASS, PASS, OK (170 fingerprinted, 288 `.gz` and 288 `.br` copies, with the server's Node 20) |
| Deploy (`deploy/tests`) | 113 tests OK |
| Site (`web/site/tests/run.py`) | 45/45, with the new `fingerprints` (static and in the browser) and `media` |
| App UI (`web/app/ui/tests/run.py`) | 1115/1115 |
| App core (`web/app/tests/run_all.py`) | ALL PASS (9 steps) |
| D-01, `tests/e2e/test_headers.py --local` | PASS, 106 checks (`test_headers-local.txt`) |
| `tools/check-seo.py --dist` | PASS (`check-seo-dist.txt`) |
| `tools/verify-deploy.py` on the stack | 0 differences (`verify-deploy-local.txt`) |
| `tests/e2e/perf_probe.py --check` | PASS (`probe-after.txt`) |

**Found on the way: two UI scenarios pressed a moving target.** With the drive's modules coming from the browser's
cache, the drive opens its menus and dialogs a few hundred milliseconds sooner, and two scenarios started failing now
and then on the branch, never on main (`suites/ui-races.txt`, with the traces):

- `share-rules`: the row menu slides about 30 px as it opens; the test pressed Share while it still moved, and the
  press landed on Copy a once link below it (a link was made instead of the dialog opening). `row_menu`
  (`flows_drive.py`) now presses once no animation runs on the menu or around it.
- `drive-delete-account`: the settings dialog fills in the drive's Tari address, its code and the safety code above
  Delete my drive once the keys are ready, which pushes the button down about 340 px; the press landed where it had
  been. The scenario now presses after the address is there.

The app is unchanged. The settings dialog's late address is a layout shift it had before (a quick tap can still miss
the button; see Left); the slower module loads on main only kept the test from meeting it. The keyboard flow's check
that the preview takes the focus now waits for it (it looked once, at once, while the preview's module was still
loading).

`suites/before/`: the site suite (44/44) and the UI budgets (18/18) on `4d38049`, for the numbers above.

## Left

- **Deploy.** Nothing here is live. The first release with fingerprints has nothing to carry (the live release has no
  hashed names); `activate-release.sh` makes the `.br` copies on the server if the workstation had no Node. After it:
  `tests/e2e/test_headers.py` (D-01) and `tools/verify-deploy.py https://hidebox.app <commit>` against the live site.
- **A-06 is now counted as sent** (the Brotli copy), with gzip -9 printed beside it. The fingerprints in the widget's
  import names add 763 B to the old gzip -9 measure (a hash doesn't compress), which alone would have put the
  computer's QR waiver 720 B over its ceiling (it had 43 B of room). What a visitor gets went down instead. If the
  owner wants the gzip -9 measure kept, the way back is to fingerprint only what pages name directly, which leaves
  every imported module to revalidate on each visit.
- **Bigger wins need the owner's PNGs:** the hero is drawn 520 px wide on a computer and takes its 720 px candidate
  (15,311 B); a 560 px one would be about 11 KB. The source PNGs are not in the repository or on the server, and
  encoding the published AVIF again would lose detail.
- **A rollback** serves the previous release, which doesn't have the newer release's hashed names: a tab opened on the
  newer one would miss a lazily loaded module until it reloads (carry-assets only looks back).
- **The drive's settings dialog grows** when the Tari address, its code and the safety code arrive, moving Delete my
  drive down about 340 px; keeping the address's room from the start would end that layout shift (the app's).
- **Seen, not this pass's:** `tools/build.py --with-tests` (staging builds that serve `web/app/tests`) stops with a
  `UnicodeDecodeError` on main as well as here (the previews' UTF-16 fixture, read as UTF-8 by the placeholder step).
- **Not removed:** the Mutis Script fonts in `web/shared/fonts/` (not served, but their tools, licence notes and a D-01
  check still name them) and the screenshots in `docs/review/*/` that no review names by file (they are records).
