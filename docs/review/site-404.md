<!-- SPDX-License-Identifier: MIT -->
# The 404 page (2026-10-19)

The owner approved a new 404 page: his picture of "4", the open box as the "0", "4" (the lid hovers, a lime glass "?"
rises out of the box), new words, one button, and three easter eggs. The status (404) and the robots meta (noindex) are
as they were. Branch `site/404`, rebased on the brand kit and the upload-safety pass and pushed to `main`; **not deployed**. Evidence:
[`docs/evidence/2026-10-19/site-404/`](../evidence/2026-10-19/site-404/).

## What the page is now

| Part | What | Why |
|---|---|---|
| The art | One `<picture class="nf-art">` above the h1, at most 480 px wide, centred, `alt=""` | Decorative: the h1 says it (the owner's call) |
| Dark mode | The art sits on the void with no edge | Its black is `#010101`, so it is drawn through `lighten` on an ink card (`#0A0A0A`) that is the page itself |
| Light mode | The same ink card, rounded (`--r-panel`) | The header tile's rule: the dark stays dark |
| Its foot | Fades into the card over the last 18 % | The floor's reflections otherwise end on a hard line; the home's stills fade at their foot too |
| h1 | "We can't see inside your files." then, on its own grey line, "Or, apparently, this page." | The home's pattern for a two-sentence heading (`.h1-2`) |
| Lede | "Maybe the address has a typo, or the link expired." / "Ask whoever sent it for a fresh one." | One sentence a line, balanced |
| One button | Go home, to `/`, in ink | Open my drive left. The view's one lime is the header's Open your drive (The Lime Is Yours Rule) |
| No float | The optional 4 px float was not added | The site's one repeating motion is /how's stills, under their Pause switch (DESIGN.md, WCAG 2.2.2); a float would need its own |

The head (title "Not found", description, card) is unchanged.

## The picture

Made like the home's stills (`docs/review/home-v3.md`): ffmpeg 7.1.5 on the server as `build`, from the owner's PNG
(1536 x 1024, kept outside this repository). WebP with libwebp (quality 84, the picture preset, from RGB, no alpha);
AVIF with libaom-av1 (a still picture, CRF 24, 10-bit 4:2:0, BT.709, full range); the commands are
`encode_404.sh` in the evidence. No PNG fallback: the site's pictures have none (the `<img>` is a WebP).

| Width | AVIF | WebP |
|---|---|---|
| 480 | 6,574 B | 9,612 B |
| 720 | 11,088 B | 17,532 B |
| 960 | 16,450 B | 27,982 B |

`sizes="(min-width: 512px) 480px, calc(100vw - 32px)"`, `width="960" height="640"` (no layout shift),
`fetchpriority="high"` (it is the first screen). A computer at 1x and a phone at 1x take the 480 AVIF, 6.6 KB.

**Caching (the owner's addition).** The build fingerprints no file name and no route serves anything `immutable`: the
home's stills are under `/site/media/*` with `Cache-Control: public, max-age=86400` (their names carry no version, so
a day, never a year). The art uses that same path, `/site/media/404/`, and D-01 now asks for it (`headers_spec.MEDIA`).
The 404 HTML stays `no-store` (Caddy's `handle_errors`). Nothing is precompressed for any type; AVIF and WebP are
compressed already, and Caddy's `encode` rightly leaves images out. **What a later performance pass should change:**
have `tools/build.py` copy each file under `site/media/` to a content-hashed name (`box-zero-480.<sha256:10>.avif`)
and rewrite the pages' `src` and `srcset` to it (the manifest and `verify-deploy` then pin those names), and give
Caddy one route for hashed names, `public, max-age=31536000, immutable`, ahead of `@media`; the unhashed names would
keep their day for anything that cached them. The home's stills and /v2's loops would gain the most.

## The three easter eggs

1. **A line that shows only when selected**: "for real, this is a 404, we couldn't find the page, stop looking",
   under Go home, in the page's own colour (`--bg`). Selecting the page (Ctrl+A, a drag) paints it in the text colour
   on the reading pages' selection tint (14.6:1 light, 13.4:1 dark). `aria-hidden="true"`, so no screen reader takes
   it for the page's message (the browser check reads the accessibility tree). In forced colours it takes the
   system's page colour. The art and Go home take no selection, so Ctrl+A paints the words alone. It is the one text
   the site means not to show; no contrast check here computes element colours, and the 404 browser check says it is
   exempt on purpose.
2. **A comment in the source**: `<!-- keep looking? man, give up, there is nothing to find -->`, after that line.
   `tools/build.py` keeps comments (it only expands `<!--#include …-->`); the built `404.html` carries it.
3. **The console**: `web/site/js/egg.js`, a module `site.js` imports only on the 404 page (`main.not-found`), after
   the load event, so the CSP stays `script-src 'self'` and no other page fetches it. It prints the ghost exactly, then
   "ghost: Donovan Baker, asciiart.eu" in small type; the same credit is in the code (the artist asks for it). Both
   are `log` lines: the suite counts only `error` and `exception` lines, and its 404 check asks for these two lines,
   word for word and space for space. 755 B (483 B gzip -9).

## Checks changed

- `static_checks.check_not_found` (new): the owner's words, one link (Go home to `/`), the order art, h1, lede, button,
  hidden line, comment; the picture's two sources and three widths, each file's pixels against its descriptor, sizes
  (AVIF 32,000 B, WebP 48,000 B, the folder 128 KiB), every file in `media/404` named; the hidden line's CSS; `egg.js`
  only from `site.js`, at most 1,024 B gzip.
- `browser_checks.check_not_found` (new): at 1440 and 390, dark and light, the page answers 404, the art is shown from
  its AVIF, at most 480 px, centred above the h1, on the ink card through `lighten`; Go home is the one link and in the
  first screen; the hidden line, its selection colour, `aria-hidden` and its absence from the accessibility tree; the
  comment in the served page; the console's two lines; no error, no CSP violation.
- `check_seo` (M-04): an `<img>` with `alt=""` passes on a page search never indexes; every other picture still needs
  alt text. `check_v2`: `media/404` is the third media folder, and the 404 page may name `/site/media/`.
- Nothing pinned the old words: not the claim registry, not a test. The drive's own "This page isn't here." (`notfound.h`
  and `drive.missing.title` in `web/app/i18n/en.json`) is the app's, for its own routes, and stays.
- Mutants (`mutants.txt`): the hidden line visible, the comment gone, Open my drive back, the ghost one space off. The
  static check fails three of them, the browser check all four.

## Suites

On the server as `build` (`suites/`); before is `main` as this pass began (lint, copy and build on the workstation),
after is the branch's last code commit as tested, `1b36296`. Main moved once more (the upload-safety pass); after the
rebase (`924e2f5`) lint, the copy check, the build, the deploy tests (96 OK), the site's file checks, D-01 on the
local stack and the 404 and every-page browser checks passed again:

| Suite | Before (`13382af`) | After (`1b36296`) |
|---|---|---|
| Lint | PASS (0 problems) | PASS (0 problems) |
| Copy check | PASS (0 problems) | PASS (0 problems) |
| `tools/build.py` | OK: 205 files, 7 pages | OK: 213 files (the six pictures, `egg.js`), 7 pages; the built `404.html` keeps the comment |
| Deploy tests | | 89 OK |
| Site (`web/site/tests/run.py`) | 42/42 | **44/44**: the two new 404 checks |
| D-01 `test_headers.py --local` | | PASS: an unknown page is a 404 with the site policy and `no-store`; the art is `image/avif`, in byte ranges, kept a day |
| `check-seo.py --local` | | PASS (15): "an unknown page answers 404, noindex" |

A first full run of the branch (`first-run-site.log`) had one failure, `/made`'s contents marking the part being read
(43/44), while the server's load stood near 8 on two cores; that check alone passed on `main` and then on the branch,
and the final run passed in full. Nothing in this pass touches `/made`.

Budgets, the 404 page at load, uncached, `serve.py` (`budget-404.json`): 138,419 B in 17 requests before (main after
the brand kit), 146,692 B in 19 after at 1440 (the art 6,574 B, `egg.js` 755 B, `pages.css` +2,250 B, `site.js`
+288 B, the page +773 B); 133,277 → 141,550 B at 390. The home's budgets (M-01, A-06h, V-01, V-02) are unchanged apart
from `site.js`'s one line: 95 B more gzip -9 on every page (2,407 → 2,502). `pages.css` is 827 B more on the reading
pages (6,090 → 6,917). M-01 on the home stays under its 60 KB (58.7 KB of HTML, CSS and JS, with the brand kit's
changes). The curated screenshots in `web/site/shots/404-*.webp` are made again by `tests/shots.py`.

## Left

- **Deploy**: the coordinator's. D-01 against production asks for `/site/media/404/box-zero-480.avif`, so it fails
  until this is deployed.
- **The other reading pages' selection in dark mode**: `site.css` gives `::selection` the lime fill's label colour
  (ink) and `pages.css` only changes its background, so selected words on /how, /made, /judges and /fine-print (and
  the 404's header and footer) are ink on the dark tint. The 404's own words keep the text colour (`.not-found
  ::selection`); the site-wide fix is one property on `.reading ::selection` (buttons need theirs kept), for a later
  pass.
- Real devices (Safari's AVIF and `mix-blend-mode`) were not seen; headless Chromium only.
