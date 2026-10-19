<!-- SPDX-License-Identifier: MIT -->
# Site v4: the owner's four changes (2026-10-17)

On `main` from `224cb1b` (production was the tag at `17f6c5b`). Input: the owner's four notes, with the
coordinator's decisions; `research/17-brand.md` (now version 3, kept outside this repository) and DESIGN.md carry the rules.
Screenshots and the scripts that took them: [`docs/evidence/2026-10-17/site-v4/`](../evidence/2026-10-17/site-v4/),
headless Chromium on the server as `build`.

## What the owner asked, and what shipped

| # | The owner said | What shipped |
|---|---|---|
| 1 | "inside /drive as well add the accent color, it's kind of all hard to see what to do when." | The drive had no hierarchy of actions: its one filled button per view was ink, and a drive with files had none (New was a white button). Now the shadcn default variant is the view's one primary, in Tari's lime with the ink label and a lime-700 edge on light pages, the home's Open your drive style (`web/shared/ui/components.css`, `--brand-*` in the drive's `ui/tokens.css`). Every other action names its variant and stays neutral; destructive stays red. The states and their one lime: below. |
| 2 | One competitor column in the comparison | hidebox beside **A popular cloud drive**: On their servers; Your files and their key; The company can read them; Not usually. A link works until you turn it off.; No; No; Reset it with your email. A two-column table on computers (880 px, the question 26 %, hidebox 42 %); on phones each row is a card, hidebox's answer on the tint, the popular drive's below it (the `data-label` captions stay). The compare note stays. |
| 3 | Is "drive" the right word? ("Your private cloud storage. Privacy is not an option, it's the default.") | The headline is **Your private cloud storage.** with **Privacy isn't an option. It's the default.** in grey below it (the h1 / `.h1-2` structure and its arrival kept). "Drive" stays the product noun everywhere else (My drive, Open your drive, /drive). The meta description, `og:title`, `og:description`, the JSON-LD description (home and `app.html`), the share card `og.png` (re-rendered: the headline in two lines at 64 px), its alt text on every page, the README's first line and the film's caption and end card follow it. |
| 4 | "in all the text you are not adding correct enters" | Every paragraph, lede, intro, note, step, card, table cell, dialog and empty state with two or more sentences starts each sentence on its own line, on every page (including /made and /fine-print) and in the app. Below: how, and what stays one line. |

## 1. The drive: one lime per state

| State | The one lime | Neutral beside it |
|---|---|---|
| No drive yet (`/drive`) | Make my drive | Open my drive (outline) |
| Open my drive (dialog) | Open | Cancel |
| The empty drive | Upload a folder (computer) or Upload files (phone) | Upload files / New folder (outline), New (white), Save key file (outline, C17-k) |
| A drive or folder with files | **New** (the rail's, and the phone's floating New) | Get more space, Upgrade, a folder's Share (outline) |
| One file picked | **Share** in the bar (new; it opens the share dialog for that file) | Move, Download, Move to trash (ghost); New turns white |
| Several picked | none (Share shares one file) | the bar's ghost actions |
| Share dialog | Next, then Make link (or Make pay link, or Send), then Copy link (computer) / Share (phone) | Back, Cancel, Done, Stop sharing |
| New folder, Rename, Move, a note | Make folder / Rename / Move here / Save note | Cancel |
| Delete it after | none: **Set it** is red now (a delete, never lime) | Keep it, Cancel |
| Move to trash, Delete, Delete my drive | none (red) | Cancel |
| Save my key; Settings | Save key file | Done, Show view key, Delete my drive (red) |
| Storage | Get it on the first pack (or Renew it); in the invoice, Pay with test money | the other packs, Pay from my drive (outline) |
| Received | Make my drop link, then Copy link; an opened item's Save to my drive | Open, Save (outline) |
| Pay page | Pay with test money (or Pay from my drive without test money), then Open it | Another Ootle wallet, See it in my drive, Make your own drive (outline) |
| Folder viewer | Open it, then Download all (or Save to my drive); a preview's Save | Save on each row (outline), Make your own drive |
| An unknown drive page | My drive | |

Decisions: **New** carries the lime only while My drive or a folder lists something and nothing is picked
(`drive-shell.js` `setNew`, reset by every render, set by `renderMine` and the selection), so the empty drive's
Upload a folder is never beside a second lime. **Picked rows** sit on the lime tint (`--brand-subtle`: `#F4FFE6`,
dark `#161D0B`; ink on it 19.13:1, `#FAFAFA` on the dark one 16.56:1, their meta lines in ink at 72 %).
**Focus rings stay neutral**: lime on white is 1.21:1, and a ring has to read on every button, the red ones
included (17-brand.md keeps lime off rings). The lime keeps its inset edge next to the ring when focused.
**The single-file link page** (`/s/`, the legacy `a-btn` look) keeps its ink Open it: the site header's lime Open
your drive is already on that page, and two limes would break the rule. **The site's pictures** of the drive (the
home's share window, /how's stills) stay ink: they are inert drawings, and a second lime on the home would
compete with Open your drive. Measured: label on the fill 16.32:1, on the hover 14.04:1; the edge 4.65:1 on
white and 4.45:1 on the rail's `#FAFAFA`; the fill on the dark page 16.32:1.

The UI scenario `drive-primary` (web/app/ui/tests/flows_share.py) walks the states above on a computer and a
phone, light and dark, and checks that exactly one visible button is lime in each (inside the open dialog when
there is one), that two picked files show none, that Delete it after is red, that the picked row is tinted, and
that every paragraph on screen starts each sentence on a new line with no `<br>` straight inside a flex or grid
box.

## 4. One sentence a line: how

- **Site pages and partials:** a `<br>` after each sentence's end, the space kept before it (`upload. <br>You`), so
  `textContent`, search, screen readers and check-copy read the same words (check-copy normalises whitespace;
  every registered claim still matches word for word). The `<br>` costs fewer bytes than a span per sentence and
  needs no CSS. Where a sentence starts inside a tag (a `<strong>` lead-in, a `data-when` variant, a link) the
  break sits beside the tag; inside a variant that may be hidden it sits inside the variant, so a hidden one
  leaves no empty line. Reading pages: the table cells balance (`main td { text-wrap: balance }`) so a sentence's
  last word doesn't sit alone; the home's comparison hangs each sentence after its mark (`text-indent`).
- **The app:** `web/app/ui/lines.js` wraps `lib/dom.js`'s `h()` and splits the string children of `<p>`, `<dd>`,
  alert titles, choice and item descriptions at each sentence's end (same rule: the space stays, a `<br>`
  follows); the drive's modules get it through `behaviors.js`, the link and task pages (`view.js`, `send.js`,
  `rules.js`, …) import it. Five places that set a two-sentence text later use `replaceChildren(...lines())`.
- **The home's drop widget** stays on `lib/dom.js` (A-06): its two card sentences ("…in the next 24 hours. / Then
  it's gone.") and the code's caption carry a newline under `white-space: pre-line`; two stale ghost comments
  left `widget.css`, so A-06 did not move.
- **Stay one line:** headings (the hero's second line is two sentences, broken; other headings are one sentence),
  the status pill on /made (a pill), toasts, labels and buttons.
- **The comparison's intro** no longer repeats the hero: "Your files lock here, in your browser. / A usual drive
  locks them on its own servers, with its own key." The first sentence is registered under C32 (with a marker);
  the second is C50's own registered sentence. "Files lock in this browser before upload." now appears twice on
  the home: the hero and the table's first cell.

The audit (`shots_v4.py`) measures it in the browser: for each block with two or more sentences, the next
sentence must start below the period; a sentence whose last word sits alone on its line is an orphan.
Over the six pages at 1280 and 390 (light), as served by the test server:

| | Blocks of two or more sentences | With a sentence not on its own line | With a one-word last line |
|---|---|---|---|
| Before (`224cb1b`) | 472 | 436 | 69 |
| After | 470 | 2 | 5 |

The two left are the status pill on /made (kept one line, at both widths). The one-word last lines left: the
judge pass hint, measured inside the closed "Have a judge pass?" disclosure (both widths); one long paragraph on
/made ("Our own test transactions…", both widths); one narrow inventory cell on /fine-print at 1280. Production
passes the same check on the home at both widths (the live probe).

## The skills

**design-taste-frontend.** Read as a refinement (preserve) of the site and the drive: Operate mode for /drive
(the one-lime rule is a hierarchy fix, not decoration), Persuade for the home. Pre-flight items that moved:
one accent, locked (the lime now also marks the drive's next step, still one per view); CTA contrast 16.32:1;
no em dashes; the hero now has three lines on a computer (the two sentences of its second line break), the
button still above the fold at 1280 × 800 and 390 × 844.

**impeccable.** `impeccable context` loaded PRODUCT.md and DESIGN.md; refinement keeps the identity. `impeccable
detect --json` over the changed stylesheets, the home and the new modules: 28 findings, all of kinds unchanged
from v2 and v3 and false for the same reasons (site-v2.md, site-v3.md): cramped-padding (6), design-system-color
(5: `#000` in masks, shadow alphas, the violet badge), design-system-font-size (5), icon-tile-stack (5),
design-system-radius (3), overused-font (3), flat-type-hierarchy (1). None on the new lime rules: the lime is in
DESIGN.md's colours.

## Kept as they were, on purpose

- "Drive" in the page title (`hidebox: your private drive`), the drive app's own title and description
  (`drive.html`), the web app manifest and DESIGN.md's front matter: the product's noun and the brand tagline
  ("Locked here. Shared your way.") stay there; "cloud storage" is the headline's category word only.
- The C52 registry entry keeps the markers and sentences of the retired file-sending column, so the checker
  stays as strict as it was.

## Review and tests

An independent review (the code-critic agent, over the diff) found one blocker, fixed before the release: the
white New and floating New lost their focus ring (a box-shadow on the variant rule outranked `:focus-visible`;
the rail's New had never had one). Both now show it, and `drive-primary` checks it. Its nits, also fixed: the
Move warning's text sits in one grid item; `lines.js` splits without a lookbehind (older Safari).

| Suite (the server, as build) | Result |
|---|---|
| Lint, check-copy | PASS, PASS (0 problems) |
| App core (`run_all.py`) | ALL PASS (9 steps) |
| UI (`web/app/ui/tests/run.py`) | 723/723 (691 before; `drive-primary` adds 32 checks) |
| Site (`web/site/tests/run.py`) | 35/35 (run 1 failed M-05: the footer's mandatory trademark line is two sentences, now read without the breaks) |
| Deploy gate | server 328 tests OK (6 skipped), deploy tests OK, lint, check-copy |

Release `0e05f27d01da2e9b9f56bd78e5b40bfb6f8fa1b5` (release id `…-c41ca02e6`, manifest `a8f29841…` notarized
through SealLog in tx `072495e2…c5df`), tag `spooky-secrets-2026-10` moved from `17f6c5b` and pushed with `main`.
verify-deploy: 0 differences across 162 files, SealLog's template byte for byte; D-01 PASS; the live probe 18/18;
the non-chain batch 13/13 (E-04 passed); `/status.json` green. The film was rendered again on the release.

## Numbers

| Check | Before (v3, `17f6c5b` / `224cb1b`) | After |
|---|---|---|
| M-01, HTML+CSS+JS on / (gzip, of 60 KB) | 57.9 KB | 57.9 KB (+40 B: `index.html` −9 B with one column fewer, the footer +8 B, `home.css` +41 B, `widget.css` −3 B, `widget-en.json` +3 B) |
| A-06, phone, at load / after a drop (of 40,960) | 25,001 / 40,536 B | 25,001 / 40,536 B |
| A-06, computer with the code to scan (of 43,520) | 43,503 B | 43,503 B (two stale ghost comments left `widget.css` to pay for `pre-line`) |
| A-06d, /drive until its table renders (of 131,072) | 113,793 B, 36 files | 115,586 B, 37 files (`lines.js` is the new one) |
| A-06h, home.css gzip -9 (of 1,770 + 3,072) | 4,684 B (+2,914) | 4,733 B (+2,963): the growth row stays at 3,072 B, no raise |
| A-06h, field.js / motion.js / pixel.js | 3,463 / 3,149 / 3,640 B | unchanged |
| Home words at 390 / 1440 (of 800; fold of 120) | 667 / 686; fold 63 / 68 | 644 / 660; fold 66 / 70 |


## Screenshots

In [`docs/evidence/2026-10-17/site-v4/`](../evidence/2026-10-17/site-v4/), `before-` from `224cb1b` and `after-` from
the release, headless Chromium on the server as `build`:

- `site/`: every page at 1280 and 390 (`{tag}-{page}-{width}.webp`, the first screen, and `-full` after scrolling
  through; the home also dark), the home's hero, comparison and closing on their own (`-hero`, `-compare`,
  `-closing`), and `audit-before.json` / `audit-after.json`. /made's and /fine-print's whole pages are left out
  (about 4 MB); their first screens are in.
- `app/before/`, `app/after/`: the drive's states from the UI flows (`--shots`): `v4-drive-390-start`,
  `v4-drive-1440-empty`, `v4-drive-1440-files`, `v4-drive-1440-picked`, `v4-share-1440-who`, `-opens`, `-result`,
  `v4-key-1440`, `v4-drive-1440-files-dark`, `v4-drive-390-files` (before: only the first four, the old drive has
  no Share in the bar), and the curated flows' pay page (`pay-wait-1440`, `pay-open-1440`, `pay-check-390`),
  folder viewer (`folder-390-ready`, `folder-390-open`), share dialog, storage and upload shots.

The best four: `app/after/v4-drive-1440-files.webp` (New is the lime), `app/after/v4-drive-1440-picked.webp`
(Share in the bar, the tinted row), `app/after/pay-wait-1440.webp` (the pay page's one lime) and
`site/after-home-1280-compare.webp` (the two-column comparison); on a phone, `site/after-home-390-compare.webp`.
