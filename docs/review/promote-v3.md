<!-- SPDX-License-Identifier: MIT -->
# The v3 design becomes the home (2026-10-18)

The owner approved `/v3` (docs/review/home-v3.md) as it is, with one mark, the open box, everywhere the brand tile
appears. This pass makes that page the home, sends `/v3` to it, re-points the home's checks and re-renders the share
cards and icons. **Prepared on the branch `site/promote-v3`; the coordinator deploys it** (this session ran no
`deploy.sh`, touched no production file and moved no tag). Evidence:
[`docs/evidence/2026-10-18/promote-v3/`](../evidence/2026-10-18/promote-v3/).

## The commits

| Commit | What |
|---|---|
| One mark | The previous agent's patch, kept as it was: the open box (`i-hidebox`, three strokes on a 32-unit grid) in the shared sprite; the header's tile on every page and the comparison's hidebox tile on `/`, `/v2` and `/v3` draw it, lime on ink in both themes; the drive's brand tile, its start card, the folder view and the empty drive; `shared/brand/symbol.svg` and `favicon.svg` (and `static/favicon.svg`, the same bytes); the OG and icon templates; the film's end card (`tools/film.py` takes `symbol.svg` as it is) |
| The home is the v3 design | `pages/index.html` is `v3.html`'s body under the home's head (below); `home.css` loses the field, the pixel field and the old layout's two rules; `v2.css` and `v3.css` say they now serve the home; `field.js` and `pixel.js` are deleted and `site.js` no longer loads them |
| `/v3` answers 301 to `/` | `pages/v3.html`, `media/v3/hidebox-mark.svg` and `media/v3/favicon-32.png` leave; the Caddyfile, `headers_spec.py`, the deploy tests and the site's test server |
| The site suite re-pointed | Below, check by check |
| The share cards, icons and favicons | `render-images.py` on the server as build |
| The build serves `favicon.ico` | `.ico` joins `SERVED_EXT`; `deploy/tests/test_build.py` |
| This review, the fix log, the evidence | |

## What `/` serves now

- **The page:** `/v3`'s markup, word for word (the site suite had held `/v3`'s words, links, variants and labels
  equal to the home's, so nothing a reader or a crawler sees as text changed), under the home's head: the title
  `{{BRAND}}: your private drive` (kept: `/v2` holds "your private cloud storage" and titles stay unique, and site-v4
  kept "drive" in the title on purpose), the description, canonical `{{ORIGIN}}/`, `og:url` `/`, both theme-color
  metas (light `#FFFFFF`, dark `#0A0A0A`, as asked; see "Open" below), the JSON-LD graph with its current
  descriptions, no robots meta. `<html lang="en" data-theme="dark">`: dark first, and `theme.js` still applies a
  stored choice over it, so the Lights switch works (checked: pressed, the page turns light; pressed again, dark).
- **The favicons:** `<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">` then
  `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`. `/favicon.svg` keeps its path and is the open box (the
  one-mark patch); the PNG is new, rendered from that SVG by the pipeline (below). `/favicon.ico` (the 192 px icon in
  an ICO), the apple touch icon and the manifest's icons are the open box too. `/favicon.ico` is also served now:
  `render-images.py` always wrote it, but `.ico` was not among `tools/build.py`'s served types, so production answers
  404 for it today (checked); a deploy test holds it, and Caddy types it `image/vnd.microsoft.icon` from the server's MIME
  table.
- **The stylesheets: the chain, not one combined file.** `tokens.css`, `base.css`, `site.css`, `home.css`,
  `widget.css`, `v2.css`, `v3.css`, as `/v3` had them. `/v2` loads `home.css` and `v2.css` too, so folding them into
  one home file would either serve `/v2` the home's stills rules or duplicate v2's layout in two files; the chain keeps
  each byte in one place and each file inside the budget it already had (V-01 for `v2.css`, V-02 for `v3.css`). The
  home's own stylesheets get a combined row in A-06h (below). `home.css` lost the rules only the old home used (the
  hero field's static grid and canvas, the pixel field, `.hero-inner`, `.chain-grid`): `/v2` never used them, so its
  look is unchanged.
- **Scripts:** `theme.js`, `site.js`, and after the load event `motion.js` (the reveals and the drive slice's decode,
  which `/v3` used too: `body[data-motion]`); the drop widget as before. No WebGL: `field.js` (the hero's grid) and
  `pixel.js` (the closing's pixels) are deleted, since no page used them once the home stopped; `site.js` keeps the
  motion and `/how` loaders only.
- **The Open your drive logic** is the home's: two links share the label, `theme.js` paints `data-has-drive` from
  `localStorage['mutis.drive']` before the first paint and `site.js` keeps the flag true from the drive's own record.
  `v3.html` had the same markup (`.hero .cta-row`, `home-make`, `home-open`), so the header check runs unchanged.

## `/v3` and `/v2`

- **`/v3` and `/v3/` answer 301 to `/`** (`deploy/caddy/Caddyfile`: `@old_preview path /v3 /v3/`, `redir @old_preview "/" 301`,
  with the other folded pages' redirects, which carry the security headers). `headers_spec.REDIRECTS` says the same
  (`test_config.py` compares them; D-01, `test_headers.py`, asks the live site for both and their `Location`), `/v3`
  left `headers_spec.ROUTES`, and the `@preview3` handler is gone. `/v3/index.html` is no route any more (404 through
  the catch-all, like any missing page). `check_redirects` holds that no `pages/v3.html` exists and `/` does. The
  site's test server (`serve.py`) now answers the Caddyfile's 301s from `headers_spec`, so the browser suite sees
  `/v3` land on `/`.
- **The stills stay in `web/site/media/v3/`**: the URLs the page names did not change, so a browser that cached them
  from `/v3` keeps them; `hidebox-mark.svg` and `favicon-32.png` left the folder (the home uses `/favicon.svg` and the
  new `/favicon-32.png`). 24 files, 480,262 B.
- **`/v2` is as it was:** noindex (meta and Caddy header), linked from nowhere, its loops, its words. Its page changed
  in one invisible place (the share card's alt text, since `og.png` changed) and, through the one-mark patch, its
  header and comparison tiles draw the open box like every page. A pixel comparison of `/v2` before and after this
  pass's own commits (the one-mark commit's tree against this branch's, reduced motion so the loops show their
  posters, the same Chromium): at 1440 every byte of the first screen and the whole page is equal; at 390 the first
  screen and the second half are equal and one 400 px band (y 2000 to 2400, the drop widget's) differs, and it differs
  between two runs of the same tree too, so it is run-to-run noise, not a change (`v2-compare.json`, `v2-tiles.txt`).
- **Sitemap and JSON-LD:** the build lists every page without noindex, so `sitemap.xml` names `/` (and `/how`,
  `/made`, `/judges`, `/fine-print`) and never `/v2` (noindex) or `/v3` (no page). The JSON-LD graph is the home's
  (`WebSite` and `SoftwareApplication`, both `{{ORIGIN}}/`). `deploy/tests/test_build.py` now checks that the home's
  stills reach `dist/` byte for byte, that the sitemap lists `/` and that no `v3/` is built.

## The share cards, icons and favicons

Rendered by `web/site/tools/render-images.py` on the server as `build` (headless Chromium, the pinned Geist), as every
earlier pass did. Two changes to the tool: it waits for a card's pictures to decode, and it draws `static/favicon.svg`
at 32 px with its corners clear as `static/favicon-32.png`.

| File | Size | What |
|---|---|---|
| `og.png` | 145,788 B (limit 150 KB) | The home's first screen: dark, the open box tile and the name, "Your private cloud storage." with "Privacy isn't an option. It's the default.", and the hero's still (`media/v3/hero-720.webp`) at 420 px on the right. 520 px looked better but weighed 187 KB, 440 px 154 KB: the still is the card's heaviest part, so it is 420 px (`og.css` says why) |
| `og-s.png` | 50,018 B | The shared-link card, light as before, its tile the open box |
| `icon-512.png`, `icon-192.png`, `apple-touch-icon.png` | 5,761 / 2,184 / 2,215 B | The lime box on ink, full bleed (the OS rounds them) |
| `favicon.ico` | 2,206 B | The 192 px icon in an ICO |
| `favicon-32.png` | 717 B | `favicon.svg` at 32 px: the rounded ink tile, the lime box, transparent corners |

The cards' alt text, on every page and on `app.html`, now says what `og.png` shows: "{{BRAND}}: an open box, files
rising out of it in its light. Your private cloud storage. Privacy isn't an option. It's the default."

## The checks, re-pointed

Expectations changed only where the design change meant them to; each is below. Nothing for another page was loosened.

| Check | Before | After | Why |
|---|---|---|---|
| V-02 static (`check_v3` → `check_home_stills`) | `/v3`: noindex, no JSON-LD, unlinked, its words equal the home's, its favicons `media/v3/*`, the header tile a CSS data URI in `v3.css` | `/`: indexable (no robots meta), dark first, no link to `/v3` anywhere, no video, loop or Pause switch; the five pictures exactly as before (AVIF then WebP, three widths, real pixel widths and ratios, the hero eager with `fetchpriority="high"`, the rest lazy, the closing on the hero's `srcset` and `sizes`); favicons `/favicon-32.png` (32 × 32) then `/favicon.svg`; `favicon.svg` (both copies) and `symbol.svg` the open box in `#BCFE00`, clean (no raster, script, link, style or data), at most 2,048 B; the sprite's `i-hidebox` clean and the header partial's tile drawing it; every file in `media/v3` named by the home; the folder at most 512 KiB, `v3.css` at most 2,048 B | It is the home now; the equal-words rule has nothing to compare (the page is the home), the data-URI tile left with the one-mark patch |
| V-02 browser (`check_v3` → `check_home_stills`) | on `/v3` | the same on `/` (dark first, the hero's AVIF first, sections lazy, each still once, the bytes: 512 KiB at load, 1 MiB scrolled), plus: the header's and the comparison's tiles draw `#i-hidebox` in `rgb(188, 254, 0)` on `rgb(10, 10, 10)` in both themes, and the Lights switch takes a light page back to dark | The tile is the sprite now, not a CSS background |
| A-06h static (`check_field_budget`) | `field.js` ≤ 6,144, `motion.js` ≤ 4,096, `pixel.js` ≤ 8,192, `stills.js` ≤ 2,048 B gzip -9, each only from `site.js`; `home.css` ≤ 1,770 + 3,328 B | `motion.js` and `stills.js` as before; `field.js` and `pixel.js` must not exist and nothing may name them, no page or partial carries `data-field` or `data-pixel`; `home.css` ≤ 1,770 + 3,328 B as before; **new row:** the home links exactly `home.css`, `v2.css`, `v3.css` (in that order) and those three together stay ≤ 8,704 B gzip -9 | The design has no WebGL field (the owner approved v3 as it is). The home's CSS is now three files; the growth row on `home.css` alone would no longer describe what the home loads, so the combined row does: 8,303 B measured, 401 B of room (each file also keeps its own limit) |
| A-06h browser (`check_field` → `check_no_field`) | `field.js` after the load event, ripples, the static grid with reduced motion | at 1440 and 390, after load and a full scroll, `/` asks for neither `field.js` nor `pixel.js` and has no canvas, `[data-field]` or `[data-pixel]`; `/how` and `/judges` ask for neither | Same reason |
| Motion (`check_motion`) | the slice decoding at load; `pixel.js` only near the closing, drawing only on screen | the decode is waited for after scrolling the slice into view (it now sits under the hero's still, below the first screen at 1440 × 900 and 390 × 844); the `pixel.js` parts are gone; everything else as before (motion.js after the load event, no element still hidden after scrolling, the slice's DOM as served, reduced motion, no JavaScript, `/how`, `/judges`, `/made`, `/fine-print`) | The page's layout moved the slice; the decode itself is unchanged |
| Every page (`check_pages`) | `/`, `/how`, `/made`, `/judges`, `/fine-print`, 404, `/v2`, `/v3` | the same without `/v3`, plus `/v3` and `/v3/` land on `/` | `/v3` is a redirect |
| `check_v2` (V-01) | only `/v2` and `/v3` may name `/site/media/` | only `/v2` and the home | The home shows the stills |
| Static files (`check_static`) | og cards, icons, `favicon.ico` | also `favicon-32.png`, 32 × 32 | New file |
| Deploy: `test_config` | `/v3` under the app policy, noindex, `rewrite * /v3/index.html` | no `@preview3`, no `/v3/index.html`, `@old_preview` 301 to `/` for `/v3` and `/v3/`, `/v3` out of `ROUTES`, the stills under `/site/media/` | Same |
| Deploy: `test_build` | a synthetic `v3.html` built to `v3/index.html`, out of the sitemap | the home's stills reach `dist/site/media/v3` byte for byte and the manifest, the sitemap lists `/`, no `v3/` is built | Same |
| D-01 (`headers_spec`) | `/v3`, `/v3/` 200 with the app policy and noindex; `hidebox-mark.svg` among the media | `/v3`, `/v3/` 301 to `/` with the security headers; the two hero files remain the media probes | Same |
| Unchanged, re-run on the new markup | | M-01, the word budget (120 above the fold, 800 in all, Open your drive the first control), the header and the Open-vs-Make logic, fonts, `check_shared_blocks` (the four sides and What's tTARI? equal on `/` and `/how`), internal links, check-copy (every claim verbatim; the hero and the comparison's intro are `/v3`'s, which were the home's), A-06 (UI suite `budget`), A-06d | |

The new static rules were each tried against a broken copy and each failed it: a robots meta on `/`, no
`data-theme="dark"`, a `data-field` in the hero, `field.js` back, the hero lazy, the PNG favicon link removed, the
favicon back to the padlock's colours, a stray still in `media/v3`, a link to `/v3` from `/how`, a fourth stylesheet on
the home, the header tile back to `#i-lock`, a `<video>` on the home, `v3.html` back (that one fails M-04, a duplicate
title, and the redirect rule).

## Budgets, before and after

Before is `main` at `312eea1` (the old home, measured by its own suite's checks on the server, as build); after is this
branch (`suites/site.log`, `suites/ui.log`). The test server compresses nothing and caches nothing.

| Budget | Limit | Before (the old home) | After (the v3 home) |
|---|---|---|---|
| M-01: HTML+CSS+JS on `/`, gzip | 60 KB | 58.9 KB (35 requests) | 58.4 KB (37 requests: two stylesheets more, two scripts fewer) |
| M-01: everything at load | 400 KB | 137.9 KB | 133.3 to 160.0 KB across runs (whether a lazy still near the first screen has arrived when the check counts) |
| A-06: the widget on a phone, at load / after a drop | 40,960 B | 25,001 / 40,536 B | 25,001 / 40,536 B |
| A-06: a computer with the code to scan | 43,520 B | 43,503 B | 43,503 B |
| A-06: a phone after a photo | 49,152 B | 45,574 B | 45,574 B |
| A-06d: `/drive` until its table renders | 131,072 B | (not this pass's) | 117,471 B, 37 files |
| A-06h: `home.css`, gzip -9 | 1,770 + 3,328 B | 4,987 B | 4,128 B (the field's and the pixels' rules left) |
| A-06h: the home's stylesheets (`home.css` + `v2.css` + `v3.css`) | 8,704 B (new) | `home.css` only: 4,987 B | 8,303 B (4,128 + 3,185 + 990) |
| A-06h: `field.js` / `pixel.js` | 6,144 / 8,192 B | 3,752 / 3,864 B | gone |
| A-06h: `motion.js` / `stills.js` | 4,096 / 2,048 B | 3,149 / 1,800 B | 3,149 / 1,800 B |
| V-02: `media/v3/` | 524,288 B | 482,013 B, 26 files (`/v3`) | 480,262 B, 24 files (the mark and its PNG left) |
| V-02: `v3.css`, gzip -9 | 2,048 B | 1,365 B | 990 B (the data-URI tile left with the one-mark patch) |
| V-02: at load, 1440 / 390 | 512 KiB | `/v3`: 282,692 / 275,920 B | `/`: 258,489 / 244,572 B |
| V-02: after scrolling through, 1440 / 390 | 1 MiB | `/v3`: 304,142 / 297,370 B | `/`: 272,816 / 266,022 B |
| Words at 390: above the fold / in all | 120 / 800 | 66 / 650 | 46 / 650 (the hero's still takes the rest of the first screen) |
| Words at 1440 | 120 / 800 | 70 / 666 | 64 / 666 |
| `og.png` | 150 KB | 60,907 B | 145,788 B |

The old home's WebGL field on the server's software GL judged itself slow at 1440 (frames 117 ms apart) and fell back to
its static grid; the v3 home has nothing to fall back from.

## Suites

On the server as `build`, on this branch's final tree (rebased on `312eea1`, with every commit and these docs), logs in
`suites/` (`done.txt`: every suite exit 0):

| Suite | Result |
|---|---|
| lint | PASS (0 problems) |
| check-copy | PASS (0 problems; 15 to read, as before) |
| server | 331 tests OK (5 skipped) |
| deploy | 84 tests OK (83 before; the `favicon.ico` test is new) |
| app core (`run_all.py`) | ALL PASS (9 steps) |
| site (`web/site/tests/run.py`) | **42/42** (`check_no_field` in place of `check_field`, `check_home_stills` in place of `check_v3`; `/made`'s `check_contents` came with `312eea1`) |
| UI (`web/app/ui/tests/run.py`) | **732/732** |

An earlier full run on the same code (before the docs and the `favicon.ico` commit; `first-run-*.log`) met two timing
failures while another session's screenshots and suite shared the box's two CPUs: V-01 once on `/v2` ("stage-c plays
off screen" at one scroll stop; `/v2`'s page and `clips.js` are untouched; the site suite's second run passed 42/42,
`first-run-site2.log`) and the UI's `drive-delete-account` (a 10 s wait for the Delete my drive alert; run alone it
failed once more and then passed twice, as it did on `main`'s tree and on the one-mark commit's; no drive file changed
in this pass). Neither recurred in the final run.

An independent review of the branch (the code-critic agent: lint, check-copy, the static site suite, the deploy tests,
a build, the test server's redirects, its own 15 mutants of the new rules, the logs) returned PASS_WITH_NITS with no
blocking issue. Its nits: the docs and evidence were not yet committed (they are now), the evidence README named a
log that did not exist and an old deploy count (fixed), and `tokens.css` keeps three tokens only the fields used (left,
below). It also noted `serve.py` now answers every `headers_spec` 301, not only `/v3` (deliberate: it mirrors the
Caddyfile).

## Screenshots

`docs/evidence/2026-10-18/promote-v3/shots_promote.py`, headless Chromium on the server as `build`, against this tree
served by `web/site/tests/serve.py` (production's CSP; the API from fixtures, set as the live deployment is: direct
sends, SealLog, pay to open):

- `home-{1440,390}-{dark,light}.webp`: the first screen; `home-{1440,390}-{dark,light}-full*.webp`: the whole page after
  scrolling through it (390's in two parts); `home-*-mark.png`: the header's tile.
- `v2-{1440,390}.webp`, `v2-{1440,390}-full*.webp`: `/v2` with reduced motion; `v2-compare.json`, `v2-tiles.txt`.
- `v3-redirect-1440.webp`, `redirect.json`: `/v3` and `/v3/` answer 301 with `Location: /`; the browser lands on `/`
  (title "hidebox: your private drive").

The best four: `home-1440-dark.webp` (the words beside the open box, the open box in the header's tile),
`home-1440-light.webp` (the still on the gunmetal card, the tile still ink), `home-390-dark.webp` (a phone's first
screen: the words and Open your drive first, the still under them), `home-1440-dark-full.webp` (the whole page).

## Open, and for the coordinator

- **Deploy from this branch's head**, then verify-deploy, D-01 (now asks `/v3` and `/v3/` for a 301 to `/`), the
  non-chain E2E batch, the tag, the film: the commands are in the twelfth pass of the fix log.
- **theme-color:** the home keeps both theme-color metas, as asked; the page is dark first whatever the OS says, so a
  phone in light mode paints its browser bar white over a dark page until the visitor presses Lights. One meta
  (`#0A0A0A`), as `/v3` had, would match the page; a one-line change if wanted.
- **Unused tokens:** `--brand-px`, `--px-alpha` and `--field-quiet` in `shared/tokens.css` only served the two fields
  (its comment on `--brand-px` still names the closing's pixel field); left in place, since the drive shares the file
  and this pass changes no drive byte beyond the mark. Harmless; a cleanup for a later pass.
- **`/favicon.ico`** starts answering 200 after the deploy (it was a 404): worth a glance in D-01's run.
- **M-01** is at 58.4 KB of 60 KB: little room for the home's next addition.
- **Real devices** were not seen (headless Chromium only), as in home-v3.md: Safari's AVIF and `mix-blend-mode` on the
  light card, the SVG favicon on an iPhone.
- The README's picture of the home (`docs/media/home.webp`) already shows this design (it was taken from `/v3`).

## After the release: E-19 and the drop widget's reveal

The drive-v3 session's E2E batch on production (`6e20248`) failed E-19 twice on the Android profile (412 × 915, touch,
4× CPU throttle): the tap on Or write one opened nothing. **Cause:** `motion.js` counted the drop widget's box
(`.quick-body`) among the cards it reveals. On the v3 home the widget sits further down (under the hero's still), so
on a phone it is below the first screen when `motion.js` starts, and it was hidden (`mo-h mo-card`: opacity 0, 40 px
low) until it scrolled in, then rose 40 px over 0.7 s. The E2E test harness scrolls the button to the middle of the screen,
measures its centre and taps at once: when the tap fell inside that rise it landed about 18 px under the 44 px
button. A race with the throttled CPU decides when `motion.js` starts against when the page is ready to tap, which is
why it showed on one profile and not the other; a person tapping the widget as it arrives would miss the same way.
It was there on the old home too, where the widget usually sat in or near the first screen.

**Fix:** the widget is the page's tool, not a picture, so it leaves `motion.js`'s reveal list; it is never hidden or
moved by a reveal. Its heading and line ("Just share one thing", "No drive needed. / It opens once, then the link
ends.") still arrive as before. `check_motion` now holds it: after load, at 1440 and at 390, the widget carries no
`mo-` class, its opacity is 1 and it has no translate. Against the old `motion.js` that check fails at both widths
(`mo-h mo-card mo-in`, opacity 0, `0px 40px`); with the fix it passes. The E2E check is unchanged.

**Reproduced and confirmed** with the test harness's own devices and tap (`e19/tap_probe.py`, nothing sealed): on the
test server, before the fix 4 of 12 taps opened the text box (2 of 6 on each phone), every miss made while the widget
was hidden or rising; after it 12 of 12. Production before the fix: 5 of 6. Record: `e19/tap-probe.txt`.

**Gate and release:** on the server as build (`e19/suites/`): lint PASS, check-copy PASS, server 331 OK (5 skipped), deploy
84 OK, core 9/9, site 42/42 (with the new widget rule), UI 751/751. Deployed as `f3bede7` with `deploy.sh` (the gate,
203 files, smoke PASS, notarized in tx `41056aef…8c25`; `e19/deploy/`); verify-deploy 0 differences across 203 files;
D-01 PASS (66 checks, `/v3` and `/v3/` 301 to `/`, `/favicon.ico` now served as `image/vnd.microsoft.icon`). E2E on
production: E-01 PASS and E-19 PASS (both profiles), then E-19 PASS again (`e19/e2e/`). The tag was not moved: it stays
at `d0f08ed`.
