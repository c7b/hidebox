<!-- SPDX-License-Identifier: MIT -->
# Home v3: /v2 with stills and the open box, at /v3 (2026-10-18)

The owner's notes on /v2, as the coordinator passed them on: the padlock in a square isn't recognizable and he wants a
more useful, memorable mark; "What's different from a usual drive?" (clip C) says nothing, he doesn't get the
concept; "Who sees what" (clip B) is fine but can improve; "Tari does the private parts" (clip D) is wrong, a generic
coin with nothing of Tari. His hard limit: the Tari brand kit is not a redesign. hidebox keeps its look (gunmetal,
frosted glass, one lime, the black void, Geist, the current words); Tari shows only as a detail (the gem). New stills
and a new logo were generated for this (`~/hidebox-motion/v3/out/`, not in this repository), and he swapped
several of them while v3 was being built; each swap is recorded below. No confirmations were possible; every other
decision was made from the brief, the stills and the page.

**Live:** <https://srv2052606.hstgr.cloud/v3> (also `/v3/`). The home at `/` and `/v2` are unchanged; `/v3` is in no
menu, header, footer, sitemap or JSON-LD graph, carries `<meta name="robots" content="noindex">` and Caddy adds
`X-Robots-Tag: noindex`. Evidence: [`docs/evidence/2026-10-18/home-v3/`](../evidence/2026-10-18/home-v3/).

## What /v3 is

`/v2`'s page, word for word and link for link (the site suite checks it, V-02 below), with a still in place of every
loop. There is no video on `/v3` at all: the hero and the closing were going to keep clip A, then the owner sent a
still for them too, so `clips.js`, the Pause motion switch (nothing moves, so WCAG 2.2.2 no longer applies) and the
hero poster's preload left the page. It loads v2's stylesheet and `v3.css` (1,365 bytes gzip) over it, so layout, cards,
rhythm and tokens are v2's.

## Each section's picture

Every candidate was opened at full size and at the size it is shown (358 px wide for a phone), and set beside its
section's words.

| Section | Shown | Alternates | Why |
|---|---|---|---|
| Hero: "Your private cloud storage. / Privacy isn't an option. / It's the default." | `hero/hero-v3-03-final.png` (the owner's pick) | `hero-v3-01.png`, `hero-v3-02-final.png` | **The owner's decision**, applied as given: the open box of the new mark, the lid hovering high, five coloured file tiles (a picture, a document, a video, a text, a song) rising in an arc in the box's light. My first read had been 02-final, for two reasons that stay as notes: its box has the mark's notched walls, so the hero and the header would show one object, and its small lime padlock on the front seam says "Privacy isn't an option. It's the default." in the picture; 03 has no lock, its box is a plain open cube, and the coloured beams under the tiles can read as the files leaving the box rather than living in it. 01 has neither the lock nor the notched walls. |
| Make your drive. (the closing) | the hero's still again | | The last ask is the first picture again, smaller (360 px), over "Make your drive." and Open your drive, as on /v2. It names the hero's files, `srcset` and `sizes`, so the browser shows it from the hero's bytes |
| What's different from a usual drive? | `C-different/C-03.png` (**swapped** from the recommended `C-01-final.png`) | `C-01-final`, `C-01`, `C-02` | The intro turns on one word: "Your files lock here, in your browser." In C-01-final the file's clasp is a plain lime tab with no keyhole; at a phone's width it reads as a tag, not a lock, and the scrambled tile lost the file's folded corner, so it reads as a dark card, not the same file. That is the "says nothing" the owner described. C-03 puts a lime lock with a keyhole on the file inside the browser frame, and the same lock on the noise that leaves, the file's shape kept, then a server: the table's first two rows (Where your files get locked, What the server gets) as one picture. One pixel edit: C-03's server had a lime power light, and lime on the server says the opposite of "never the key" (lime is yours, DESIGN.md), so the derivative greys that light and its reflection in a 64 × 220 px patch; every pixel outside the patch is byte for byte the PNG's (checked by hash) |
| Who sees what / Four sides of every file | `B-who/B-03-color.png` (the owner's swap, "less gray, closer to the hero's colours") | `B-03-final` (my first placement, the recommended one), `B-01`, `B-02`, `B-03` | One file in an opened box, each face showing a different amount: the clear front (You), a small window with a blue glimpse (the person you share with), the frosted lid, lit in the hero's colours (our server: a shape, a size), and a large lime Tari gem on the left panel (the chain). The four cards are next to it, in the same order of nearness. Notes, not blockers: the file is violet, the colour DESIGN.md keeps for Tari things (here it is your file), and the lime gem is now the brightest thing in the section; both live inside the picture, on its dark stage, and do not touch the page's own colour rules |
| Tari does the private parts. | `D-tari/D-03-color.png` (the owner's swap from the recommended `D-01-final.png`) | `D-01-final`, `D-01`, `D-02`, `D-03` | Replaces the coin. Tari's real gem in hidebox gunmetal, the hero's colours glowing in its cuts and a lime edge at its foot; a blue file with its key goes in on the left and a violet locked tile comes out on the right, on one frosted rail: the section's Send by Tari row, and its intro's hidden amount and owner, in one picture. The same note on violet as in B |

The two sections /v2 left without a loop (Just share one thing, Share it your way) stay without a picture: their
picture is the product itself.

**Lime on the dark stage.** The stills' lime (the locks in C, the gem in B, the gem's edge in D, the box's edge in the
hero) only ever sits on the stills' own near-black, in both themes: B's gem measured `#AABA1E` on its panel `#1E1B1C`,
7.94:1, and the light card under it never reaches the panel's brightness, so `lighten` leaves both as they are. None of it is beside a button: the closing's lime Open your
drive sits under the picture, never beside it, and the hero's button is in the other column.

## The mark

The owner first named the folded "h" (`final-b-fold-*`), then switched to **the open box** (`final-a-open-*`): a
diamond lid hovering over an open box, three stroked paths. The SVGs were read before use: each is one `<rect>` and
three `<path>`s with a stroke, 417 to 452 bytes, no raster, no script, no font, no filter, no link. Its geometry is
kept exactly; two things changed:

- **One lime.** The files draw it in `#C9EB00`; the site's lime is `#BCFE00` (lime-400, Open your drive's fill), so
  the mark uses `#BCFE00`. Two limes a few centimetres apart in the header would look like a mistake.
- **Where it is.** Only on `/v3`: the header's tile and the comparison's hidebox tile (one mark per page, not the old
  padlock beside the new box), as a CSS background in `v3.css` (a data URI of the same three paths: the header is the
  shared partial every page uses, which stays as it is), and the favicon: `media/v3/hidebox-mark.svg` (439 bytes: the
  SPDX line, a 6-unit rounded ink tile, the three paths) and `media/v3/favicon-32.png` (1,312 bytes, rendered from that
  SVG by headless Chromium on the server, for browsers without SVG favicons). The production favicon, `/favicon.svg`, the
  apple touch icon, the manifest's icons and every other page keep the padlock.

**Contrast.** The tile stays ink (`#0A0A0A`) in both themes, with the lime box on it: lime on ink is **16.32:1**. On
the light header the ink tile against white is **19.80:1**; on the dark header the tile is the header's own colour and
the box against it is the same 16.32:1. The lime box straight on the white header would be **1.21:1**, which is why
the tile stays ink on light pages rather than the light-mode tile flipping. So the lime mark passes in both themes and
the white variant (`final-a-open-white-*`, black on white) was not needed. The Codex sources are kept in the evidence
folder (`logo/`).

## How a still sits on the page

- **Dark mode:** no card. Every still is opaque on the page's own ink, `#0A0A0A`, so its frame disappears into the
  page; only the floor's reflection fades out at the foot (a CSS mask from 82 to 90 % down). Two stills came on a
  different black (the hero on `#000000`, B on `#060606`); their derivatives lift the blacks to `#0A0A0A` (a linear
  levels map, 0 → 10 and 255 → 255), checked at the corners of every derivative.
- **Light mode:** v2's gunmetal card (a radial gradient from `#2B2F35` to `#0A0A0A`, the 1 px light edge, the soft
  shadow, radius 14 px), and the still drawn on it with `mix-blend-mode: lighten`: the picture's ink takes the card's
  light, and nothing brighter than the card changes. The stills look lit by the same studio light as v2's loops, with
  no dark rectangle inside the card.
- **Ratios:** each still is cropped once, in the file, to its object (no `object-fit` crop in the browser): the hero 1:1
  (1024 × 1024 from the middle of 1536 × 1024), C 16:9 (1536 × 864), B 1:1, D 4:3 (1024 × 768). Each `<img>` carries its
  `width` and `height`, so nothing shifts as it loads.
- **Layout:** /v2's, unchanged: the hero's words left and the picture right (1:1 now, 5:4 before; the square is
  taller than the loop was, so the centred row grew and Open your drive's top moved from 474 to 502 px on a 1440 × 900
  screen, still well inside it; 380 px at 390 × 844 and 369 px at 360 × 740, as on /v2), What's different's
  picture left of the question (the two columns stay even, so "A usual drive locks them on its own servers, with its
  own key." keeps one line at 1440; a wider picture column broke it onto a third line), Who sees what's four cards
  beside the held box, Tari's held picture beside its rows, the closing centred. On a phone each picture comes after
  its section's heading and intro.

## Compression and loading

Encoded with **ffmpeg 7.1.5 on the server** (already installed; nothing was installed anywhere): WebP with libwebp
(quality 84, the picture preset, from RGB so libwebp does its own conversion, no alpha) and **AVIF** with libaom-av1
(a still picture, CRF 24, 10-bit 4:2:0, BT.709, full range). Neither `cwebp` nor `avifenc` exists on the box or on
the server, and the box has no image tool at all. Each still is served at three widths in a `<picture>`: AVIF first, then
WebP, then the `<img>` (a WebP) for anything else.

| Still | Source PNG | AVIF (480 / 720 / 1024, C: 640 / 960 / 1536) | WebP |
|---|---|---|---|
| Hero and closing | 1,006,189 B | 9,209 / 15,311 / 25,611 B | 14,838 / 26,558 / 46,530 B |
| What's different (C) | 949,526 B | 6,895 / 14,985 / 34,113 B | 9,244 / 19,430 / 48,274 B |
| Who sees what (B) | 1,085,530 B | 6,896 / 11,442 / 18,514 B | 11,236 / 20,312 / 35,070 B |
| Tari (D) | 1,158,939 B | 6,975 / 12,145 / 20,176 B | 10,878 / 19,688 / 35,932 B |

4,200,184 bytes of PNG became 480,262 bytes for all 24 files; one visitor downloads one of each: on a 1440 screen
the hero's 720 and the sections' smallest AVIFs, about 36 KB of pictures for the whole page.

- **The hero's still** has `fetchpriority="high"` and no `loading` attribute, so it is fetched with the page.
- **Every other still** is `loading="lazy"` with `sizes` that match its column (C's is `(min-width: 900px) 520px,
  (min-width: 592px) 560px, calc(100vw - 32px)`: two columns, v2's 560 px cap, then the phone's width), so a phone gets
  the 480 or 640 file and a 2× laptop the 1024 or 1536 one.
- **The closing** names the hero's `srcset` and `sizes`, so it picks the same file and the browser shows it from the
  bytes it has; the probe saw the hero's file asked for once, with the cache on or off.
- No JavaScript is involved: the pictures show without it, with reduced motion and in every browser that knows
  `<picture>`.

**The swap point.** The hero's picture is one marked block in `web/site/pages/v3.html`, between `<!-- HERO MEDIA … -->`
and `<!-- /HERO MEDIA -->`, and the closing's between `<!-- CLOSING MEDIA … -->` and `<!-- /CLOSING MEDIA -->`. A new
image goes in as new files under `web/site/media/v3/` and new names in those two blocks (the closing keeps the
hero's `srcset` and `sizes`, which the site suite checks).

## Where it lives and how it ships

- **The page:** `web/site/pages/v3.html`, built by `tools/build.py` like every page (`dist/v3/index.html`), made from
  `v2.html`; only the `<title>` ("Your private cloud storage · hidebox"), the canonical and `og:url`, the favicons,
  the stylesheet list and the pictures differ. `body` carries `home v2 v3`.
- **The files:** `web/site/media/v3/` (26 files, 482,013 bytes: 24 stills, the mark, the PNG favicon), committed like
  /v2's loops so the manifest lists them and `verify-deploy` hashes them. The source PNGs are not committed. `build.py`
  now serves `.avif`.
- **Caddy:** `/v3`, `/v3/` and `/v3/index.html` get the app policy (the drop widget), `X-Robots-Tag: noindex` and the
  usual revalidation; the stills are under `/site/media/*`, kept a day like the loops, as `image/avif` and
  `image/webp` from Caddy's MIME table. `headers_spec.py` lists both routes and three of the stills; `test_headers.py`
  (D-01) asks the live site; `deploy/tests/test_config.py` checks the Caddyfile says the same.
- **Not in the judged surface:** no page, partial, static file, sitemap, robots or llms file links `/v3`.

## V-02: v3's own budget, and the tests

| V-02 | Limit | Now |
|---|---|---|
| Each still's AVIF / WebP | 64,000 / 96,000 B | at most 34,113 / 48,274 B |
| `web/site/media/v3/` in all | 524,288 B | 482,013 B (26 files); V-01's limit for all of `web/site/media/` (12,582,912 B) still holds: 11,663,074 B |
| The mark | 2,048 B, no raster, script, link or data | 439 B |
| `v3.css`, gzip -9 | 2,048 B | 1,365 B |
| At load, a computer or an Android phone | 512 KiB | see the release table |
| After scrolling through | 1 MiB | see the release table |

- `web/site/tests/static_checks.py` `check_v3`: `/v3` is noindex, has no JSON-LD and no page, partial or static text
  links it; its words, links, buttons, copy variants, test ids and labels equal the home's; no `<video>`, `clips.js`,
  loop file or Pause switch; exactly one `<picture>` on each of the five stages, in page order, each an AVIF then a
  WebP `srcset` of three widths with one `sizes`, an `<img class="pic">` with `width`, `height` and empty `alt`; the
  hero's with `fetchpriority="high"`, every other one lazy; each candidate is a file whose real width (read from the
  WebP's VP8 header or the AVIF's `ispe` box) equals its `w` descriptor and whose ratio is the `<img>`'s; the closing
  names the hero's `srcset` and `sizes`; the two favicons exist, the PNG is 32 × 32, the mark and the CSS data URI carry
  no raster, script, style, animation, link or data, and the header's tile does carry the open box; every file in `media/v3/` is used; the budget rows. Each rule was checked against a
  broken copy (noindex removed, a word changed, the hero lazy, a section eager, a wrong descriptor, a wrong ratio, the
  WebP first, a missing file, a video added, a favicon removed, a script in the mark, the closing on other `sizes`),
  and each failed it.
- `web/site/tests/browser_checks.py` `check_v3` (headless Chromium): dark first; no video and no loop file; at load the
  hero's still is shown, from one AVIF, and no section still that sits more than 2,500 px below the screen is asked
  for; after scrolling, each section's still once, every picture decoded from its AVIF, the closing on the hero's
  file; the bytes; the open box in the header's tile; no console error or CSP violation; light mode: every still on
  v2's gunmetal card through `lighten`, dark mode: no card and no blend; reduced motion: the hero's still shows.
  `/v3` also joins the every-page check (no error, no CSP violation, no sideways scroll at 1440, 390 and 360, one
  `<h1>`).
- `V-01` (`check_v2`) changed where /v3's files meet it, and holds what it held: its per-file limits read the loops'
  folder, `media/motion/`; a new rule fails any file under `media/` outside `media/motion/` and `media/v3/` (before,
  the per-file rule caught a stray file anywhere under `media/` as "not a loop"; now that rule and V-02 together
  cover every file, and an independent review's mutants, a stray `.mov` in `media/`, a file in `media/other/` and one
  in `media/v3/sub/`, each fail); its folder total still counts everything under `media/`; and the rule that only
  the previews name `/site/media/` now exempts `v3.html` beside `v2.html`, `v2.css` and `clips.js`.
- `web/site/tests/serve.py` serves `/v3` under the app policy and the stills with their types.
- `deploy/tests/test_build.py`: `pages/v3.html` builds to `v3/index.html`, the AVIF, WebP, SVG and PNG reach
  `dist/site/media/v3/` byte for byte and the manifest, and the sitemap has no `/v3`. `deploy/tests/test_config.py`:
  the Caddyfile's routes as above, ahead of the catch-all.

## The skills

**design-taste-frontend.** Read as a preview redesign that keeps the brand (preserve), Persuade mode, dials variance
7, motion 3 (the page no longer moves but for v2's reveals), density 4. The checks that mattered: the hero still fits
the first screen with its button; one accent (the lime of Open your drive; the stills' lime stays inside their dark
stages); no eyebrows, no em dash in visible text; one theme for the whole page; no picture sits under a word or
beside a button; every picture is a real image, not a drawn diagram; each picture's ratio is reserved before it loads.

**impeccable.** `impeccable context` loaded PRODUCT.md and DESIGN.md; the run was a refinement of /v2, so the words,
type, colours and layout stay and only the pictures and the mark change. `impeccable detect --json` over `v3.html` and
`v3.css` gave 15 findings, all of kinds the earlier reviews explain (icon tiles above the four sides' and the tTARI
box's headings, a section's border flush with its first child, the violet badge text, Geist as the face, the flat
ratio between 16 px body and 17 px card titles) plus one new and intended: `#000` in `v3.css`, which is the mask's
alpha, not a colour anyone sees.

## Release

The release, its checks and the live numbers are added here once it is deployed.

## Screenshots

From production, once it is deployed (`docs/evidence/2026-10-18/home-v3/shots_v3.py`).

## Not done, and open

- **Real devices.** Every browser here was headless Chromium on the server. Safari's AVIF decoding (Safari 16 and later),
  `mix-blend-mode` over the light card and the SVG favicon on a real iPhone were not seen; a Safari before 16 gets the
  WebP.
- **The mark beyond /v3.** The open box is only on this page; the production favicon, the apple touch icon, the
  manifest's icons, the share card and the brand files keep the padlock until the owner says otherwise.
- **The judges' tag** stays at `0e05f27`; if v3 is ever to become the home, that is a new release and a new tag.
