<!-- SPDX-License-Identifier: MIT -->
# Site v2: the design pass and its review (2026-10-16)

Branch `design/site-v2`. Input: `research/17-site-brief.md` (the look, layout and words), `research/17-brand.md`
(the Sea brand colour, type, motion, tokens) and the static mock in `research/design/site-v2/` (jarvis side).
Screenshots of `/`, `/how`, `/judges` and `/made` at 1440 and 390, light and dark (first screen, and the whole
page), plus the field mid-ripple, idle and with reduced motion, are in [`site-v2/`](site-v2/), taken with
headless Chromium 155 on ultron as `build` (`web/site/tests/shots.py --out`, features as live: pay to open
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

## Integration devil (2026-10-16)

The merge and its check against the designer's twelve points, on the real pages. `main` took
`fix/share-stop-pay` (a fast-forward, 4 commits) and then `design/site-v2` (merge `059763e`, no conflicts).
The app's link pages (`app.html`, `view.html`) include the same header partial, so the sticky header is on
them too. How it was checked:

- `devil_site.py` (in `docs/evidence/2026-10-16/site-v2/devil/`) ran with headless Chromium 154 on ultron as
  `build`. The first run used `serve.py` (production CSP, live features) before the deploy. The next two ran
  on production (`32bffc5`, then `410f210`), with 86 checks a run. They cover screenshots of the six pages
  at 390 and 1440 in light and dark; the field (a ripple frame, reduced motion, no JavaScript); and
  measured contrast: the words are hidden and each word box is compared, at its worst, with every
  background pixel under it. They also cover the hero's focus order, no sideways scroll at 360 px, and the
  header with and without a drive in the browser (IndexedDB and the flag).
- The UI flows' screenshots cover the pay page and the row menus (`pay-drive`, `share-stop`, `sell-stop`).
  `http-checks.txt` covers the routes, the 301s, `/es/` and the anchors.

| # | The designer's point | Verdict |
|---|---|---|
| 1 | A hero, and sections that contrast | ok: the hero sits over the field, and the sections alternate between the page and the sunken surface |
| 2 | "What's different from a usual drive?" is there and true | ok: claims C50 to C56, with the hedge line under the table; `check-copy` PASS |
| 3 | "What's tTARI?" is explained, and linked from the first tTARI on /, /how and /judges | **fixed** on `/`: its first tTARI is in the share window's picture, and that tTARI wasn't a link (`faf93da`). ok on `/judges`: the link sits beside the first visible tTARI. ok on `/how`: the box is the first tTARI a reader meets, because the still above it is `aria-hidden` |
| 4 | /how stays the clearest page | ok: five stills, the tTARI box and four cards; 390 px checked whole |
| 5 | Who sees what as 4 boxes | ok: 4 cards on `/` and on `/how`, 2 by 2 at phone width |
| 6 | Make my drive big and centred, Open my drive quiet | ok: the order swaps when a drive exists (screenshot `home-1440-with-drive`) |
| 7 | /judges short, the two tracks as cards | ok: 2,493 px at 1440, two side-by-side track cards |
| 8 | What to check centred and distinct | ok: the heading and the table centre on the viewport (720 of 1440), on their own section |
| 9 | /made out of the nav; "Under the hood" in the footer and on /judges; old anchors still 200 | ok: the nav is How it works and For judges; all 44 ids kept; the 301s land on `/made#locks`, `#limits` and `#check` |
| 10 | A header button on every page; hidden on the home while the hero's button shows; Open my drive when a drive exists | **fixed**. The drive now keeps the flag the builder asked for (`d3bf966`). Link pages in the drive's look (the pay page, the folder view) said "Make your own drive" to a browser that holds a drive; now they say Open my drive (`32bffc5`). The site pages were already ok |
| 11 | Stop sharing and Stop selling in the row menu and the share result, saying where to stop it: "from this file's menu" | ok: screenshots `share-1440-menu-stop`, `share-1440-result-stop` and `sell-stop-*` |
| 12 | Pay from my drive shows its steps within 300 ms | ok: the `pay-drive` flow measures 5 ms; screenshot `pay-drive-sent-390` |

Defects found and fixed, the worst first:

1. **Grey hero words without JavaScript** (`410f210`). Without site.js, the quiet zone under the words is the
   CSS fallback ellipse (46 % by 26 %), which misses them. Over the static grid, the lede measured 4.22:1 at
   390 and the note 4.41:1 at 1440, ten failures across eight widths from 360 to 1920. The second line of
   the headline (large text) measured 2.61:1 at 412 in dark. A wider fallback (80 % by 46 % at 50 % 32 %)
   gives 4.5:1 or more (3:1 or more for large text) at all eight widths, in both themes, with and without
   JavaScript (`nojs-contrast.log`).
2. **Link pages offered a new drive to a browser that already holds one** (`32bffc5`, point 10). These are the
   pay page and the folder view. UI checks now cover both cases.
3. **The drive's flag** (`d3bf966`, the builder's request). `identity.js` sets `mutis.drive` when a drive is
   made, opened or loaded, and clears it on Delete my drive and Lock my drive. `shell.js` paints app pages
   from the same record, including drives made before the flag existed. UI checks: drive-make, and
   drive-open-keyfile (open, then Lock my drive). A-06d went from 113,091 to 113,793 B.
4. **`nav.my_locker` unused** (`7646442`): the old header's button text. The UI's static check failed, at 665 of 666.
5. **The home's first tTARI** (`faf93da`, point 3). It is now a link to the box: the one live element in the
   inert picture.

Rejected, with the reason:

- On `/how`, the tTARI in the share still isn't linked. The still is `aria-hidden`, and the box follows the
  step (the builder's choice, kept).
- Without JavaScript, the home's header button never shows: it waits for site.js's observer. The hero and
  closing buttons are there. Showing the header button without JavaScript would flash it for every other
  visitor before the observer runs.
- Phones hide the top nav below 720 px, as before v2. How it works and For judges are in the footer.
- The lede measures 4.56:1 at 390 in light with the field live. That passes AA without much room. It is the
  brief's grey, so it stays.
- `made-390-light-full.webp` is 0 bytes in `shots/` and here. The page is taller than WebP's limit of
  16,383 px. The devil's PNG covers it, and the problem is in the tool, not the site.
- On production, the first E-J run (the one judge-pass drive the task allowed) failed at step 5. Its Once
  link didn't take the file: `then_delete` never reached the server, the item stayed `kept`, and the phone
  said "The file stays with its owner." Five tries did not reproduce it, and each one applied the setting:
  two probes on production with E-J's steps (four shares), the same E-J code without a pass (PASS on both
  tracks), and the UI flows. The likely cause is a timing race that happens only while the drive's sponsor
  grant arrives (the pass's path); it is not proven. E-J should check the switch is on after the click, as
  the UI flow does, so a rerun with a pass fails at step 3 and says why.

Budgets after the merge and the fixes: A-06 is 40,536 B on a phone (limit 40,960) and 43,503 B on a computer
(limit 43,520). A-06d is 113,793 B (limit 131,072). A-06h: field.js is 3,428 B (limit 6,144), and home.css
grew 2,235 B (limit 3,072). M-01 is 53.4 KB of HTML, CSS and JS (limit 60 KB), with no third-party requests.
