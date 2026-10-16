<!-- SPDX-License-Identifier: MIT -->
# Site v2: the design pass and its review (2026-10-16)

Branch `design/site-v2`. Input: `research/17-site-brief.md` (the look, layout and words), `research/17-brand.md`
(the Sea brand colour, type, motion, tokens) and the static mock in `research/design/site-v2/` (outside this repository).
Screenshots of `/`, `/how`, `/judges` and `/made` at 1440 and 390, light and dark (first screen, and the whole
page), plus the field mid-ripple, idle and with reduced motion, are in [`site-v2/`](site-v2/), taken with
headless Chromium 155 on the server as `build` (`web/site/tests/shots.py --out`, features as live: pay to open
and the sponsor on).

## What the two skills flagged, and what changed

**design-taste-frontend.** Design read: the landing and judges pages of a private drive, for strangers and
contest judges, in a calm, exact shadcn-neutral language with one sea accent and one quiet effect. Dials
4 / 3 / 4 (variance, motion, density): the brief pins a centred hero, so variance stays low; motion is one
field. Pre-flight results:

| Flag | Decision |
|---|---|
| Hero top padding over 96 px (the mock had 128 px at desktop) | Changed: 96 px from 1024 px, so the first screen ends on the drive slice at 1440 × 900 |
| A small line under the hero buttons ("No email, no password...") | Kept: the brief lists it, and it is a registered claim |
| Centred hero (anti-centre bias) | Kept: the brief chose it (§0 #1) |
| Div-built product pictures | Kept: they are the product's own parts at 1:1 (17-brand.md, Imagery), the "real component preview" the skill allows |
| Hairline grid as decoration | Kept: the field and the ruler are the brand's one effect and its seams, on the same 48 px unit |
| Four equal cards | Kept with variation: the You card on the brand tint, the chain card's violet tile |
| Em dashes, eyebrows, section numbers, dots, scroll cues, duplicate CTA intents | None; one label per intent (Make my drive, Open my drive) |
| Two image+text splits in a row (Just share one thing, Share it your way) | Within the cap of two; the comparison breaks the run |

**impeccable.** `impeccable context` loaded PRODUCT.md and DESIGN.md; the craft floor was read before the
edits; `impeccable detect --json` ran once over the changed pages, partials, stylesheets and modules (46
findings):

| Finding (count) | Decision |
|---|---|
| design-system-color (11) | Changed: DESIGN.md now carries Sea (`brand`, `brand-*`, light and dark) beside Ink, with The Sea Is Yours Rule; the rest were `#000` in masks and `inherit` the detector couldn't resolve |
| icon-tile-stack (10) | False: the tiles sit beside their titles (the detector's own advice), as the screenshots show |
| cramped-padding (9) | False: it couldn't resolve `var(--sec-pad)`; sections pad 64 or 96 px and `.wrap` gives the gutter |
| design-system-font-size (5), flat-type-hierarchy (4) | DESIGN.md now names the site scale of 17-brand.md; the real steps are 68, 36, 18 and 16 px |
| overused-font: Geist (3) | Kept: Geist is the product's one family (DESIGN.md) |
| repeated-container-text: Pay with test money (1) | Kept: two different payments in track two (the pay link, then more space); the third is the other copy variant |
| nested-cards on /how (1) | Kept: the brief keeps /how's five stills (a stage holding a card) |
| side-tab on `.sec::before` (1) | False: that 5 px strip is the ruler's ticks, not a coloured border |
| bounce-easing `--ease-spring` (1) | Not ours: the old ghost's curve in tokens.css; nothing on the site uses it |

The craft floor's "system display face" rule (and the brief's §1.2 test) moved the home to Geist: a Latin
subset of the pinned file, 18,112 bytes for weights 400 to 700 (the brief said 500 to 700; body text is 400),
rebuilt byte for byte by `web/site/tools/subset-geist.sh` and pinned in `tools/build.py`.

## Other changes found on the way

- The quiet zone (12 % lines under words) is measured from the headline, the lede, the buttons and the note
  at every width, so grey text keeps its measured contrast; on phones that is most of the hero.
- The mock's grid and ruler were offset half a cell; both now put a line through the page centre.
- `/made` held an older copy of Who sees what, The locks and Where Tari comes in (duplicate ids `who`, `locks`,
  `tari`, `record`, `payments`, and words no longer true) since 9708112. The older copies went; the old exit
  record's SealLog detail moved into Receipts on the Tari chain. Every anchor still resolves.

## Where the build differs from the brief

- The grid's reveal and the first ripple are one motion: the static grid is the first paint, so the field
  wakes from Make my drive 300 ms after its first frame instead of drawing the grid again from nothing.
- Drive detection: the drive app doesn't set `localStorage['mutis.drive']` yet (web/app is another lane's), so
  `site.js` counts the drive's key record in IndexedDB (never reading it, never creating the database) and
  keeps that flag; `theme.js` paints from it. The app setting and clearing it would make the first paint right
  after Delete my drive too.
- /judges step 2 keeps its live first-day limit as words in brackets, not a tooltip.
- /how: the first tTARI on that page is inside the inert share-window picture, so it isn't a link; the
  What's tTARI? box follows the Tari step.
- The home's word budget check rises from 400 to 800 words (689 measured); the fold stays at 120 (68).

## Numbers

| Check | Before | After |
|---|---|---|
| A-06, phone, at load / after a drop | 25,001 / 40,536 B (of 40,960) | 25,001 / 40,536 B |
| A-06, computer with the code to scan | 43,503 B (of 43,520) | 43,503 B |
| A-06d, /drive until its table renders | 112,941 B (of 131,072) | 113,091 B (theme.js's drive flag +80, two icons +70) |
| A-06h, field.js gzip -9 | n/a | 3,428 B (of 6,144) |
| A-06h, home.css gzip -9 | 1,770 B | 3,916 B (+2,146 of 3,072) |
| M-01, HTML+CSS+JS on / (gzip) | 47.0 KB (last ACCEPTANCE.md run) | 53.3 KB (of 60) |
| Flesch-Kincaid grade, home / judges (fk.py) | n/a | 2.3 / 2.6 (at most 5) |
