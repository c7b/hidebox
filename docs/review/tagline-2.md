<!-- SPDX-License-Identifier: MIT -->
# The tagline, second pass (2026-10-21)

The owner found that the line under the headline didn't say what hidebox is. His words, as given:

| | Before | After |
|---|---|---|
| Headline | Your private cloud storage. | Your private cloud storage. (unchanged) |
| Second line | Files lock in your browser first. | Store, send, and sell files privately. |
| Third line | (none) | Built on Tari™. No KYC. No email. |

Branch `copy/tagline-2`, rebased on `main` and pushed to it; **not deployed**. Evidence:
[`docs/evidence/2026-10-21/tagline-2/`](../evidence/2026-10-21/tagline-2/).

## Where the tagline changed

| Place | Now |
|---|---|
| The home's hero (`pages/index.html`) | The h1 is the headline with "Store, send, and sell files privately." in its grey `.h1-2`; then `<p class="hero-line">` with the third line; then Open your drive |
| The home's description | Opens with the tagline, then the lock as a fact: "Store, send, and sell files privately. Built on Tari. No KYC. No email. Files lock in your browser first. You pick how each file opens." (135 characters of 155) |
| Open Graph and Twitter descriptions | On `/`, on the app page (`app.html`) and on `/drive`: the two tagline lines. With `og:title` ("Your private cloud storage.") a link preview reads as the hero's three lines |
| The app page's description | The three lines |
| JSON-LD (`SoftwareApplication.description`) | The three lines |
| The web manifest's description | The three lines |
| The share card (`og.png`) and its alt text | Below |
| The repository's social card (`docs/media/social-preview.png`) | Below |
| The README | Its title line is the headline and the second line, the third line under it; the home's picture (`docs/media/home.webp`) taken again, its alt text the three lines |
| The film's end card (`tools/film.py`) | `TAGLINE` is the headline and the second line; `TAGLINE_3`, the third line, sits under it smaller and in the dimmer grey, then the testnet line (`END_Y`). The film was not rendered; `endcard.png` in the evidence is its end card alone |
| `DESIGN.md` | The Say It Once Rule names the tagline; the home's layout describes the three lines; `hero-dim` in the colours |
| The holding page (`deploy/holding/`) | Never carried the tagline; unchanged |

"Files lock in your browser first." is still C32's registered sentence and a fact in explanatory copy: the README
says it at the top of How it works (with the hero's old lede, "You pick how each file opens: once, with a word, or
for Tari."), and the home's description says it after the tagline. `/how`, `/made` and `docs/threat-model.md`
never used that sentence; they keep their own registered words for the same fact. On the home, the comparison's
"In your browser." is its short answer.

## The hero

Three lines and the button, nothing under it. The headline keeps its size. The second line keeps the old line's place
and style: grey (`--fg-2`), half the headline's size, inside the h1, so the page's heading says what the product is.
The third line is new: 500 weight, 15 to 18 px, in `--hero-dim`, a grey one step dimmer than `--fg-2`.

| Line | 390 | 1440 | Contrast, light / dark |
|---|---|---|---|
| Your private cloud storage. | 39 px, 650, two lines | 68 px, 650, two lines | 19.80 / 18.97 |
| Store, send, and sell files privately. | 19.5 px, one line | 34 px, one line | 5.74 / 7.85 (`--fg-2`) |
| Built on Tari™. No KYC. No email. | 15.2 px, one line | 18 px, one line | 4.74 / 5.37 (`--hero-dim`: `#737373` / `#858585`) |

Measured in Chromium (`after/hero-metrics.json`). The second line is longer than the old one: at 34 px it wrapped
beside the still between 960 and about 1170 px (two lines at 1024). From 960 px it is `clamp(27px, 2.9vw, 34px)`, so
it is one line at every width measured: 360, 390, 768, 960, 1024, 1100, 1180, 1280 and 1440 px, in both themes, with
no sideways scroll. With more contrast asked for, the third line takes `--fg-2`. Each line still rises in the hero's
arrival, 60 ms apart (the third takes the old lede's 120 ms slot), and stands still with reduced motion.

Two lines left the hero: the lede ("You pick how each file opens: once, with a word, or for Tari™.") and the note
under the button ("No email, no password. Your key is the account."). The owner asked for three lines, and the note
would have said "No email" twice within a few lines of the third. The drive's start screen, one tap after Open your
drive, says the note word for word (`drive.start.no_email`, which /judges' What to check
table points to); Share it your way and the drive slice right under the hero show how each file opens; the README
keeps the lede. In the Say It Once Rule, `No KYC. No email.` is now statement 7's short answer on the home.

| First screen, 1440 × 900 | Before | After |
|---|---|---|
| Words in the hero | 4 blocks: headline, line, lede, note | 3 lines |
| Open your drive ends at | 523 px (dark) | 545 px (the shorter column centres lower beside the still) |
| At 390 × 844 | 386 px | 347 px |

Screenshots: `after/hero-1440-dark.webp`, `hero-1440-light.webp`, `hero-390-dark.webp`, `hero-390-light.webp`, with the
same four in `before/`.

## The cards

**`og.png`** (1200 × 630, **146,584 B**, under the 150 KB limit; it was 146,845 B): the kit's open box in `#ACFF00` and
the wordmark, then the three lines as the hero sets them (64 px headline; 34 px second line, 600, `#A3A3A3`; 26 px
third line, 500, `#858585`), and the hero's still at 420 px. `og/og.html` now carries the kit's marks itself (the same
symbols as `og-s.html`), so `render-images.py og.png` draws the card that ships; before, `og.png` was the brand pass's
`og-candidate.png`, swapped in by hand. The words' column grew from 600 to 640 px so the second line is one line.
`og-s.png` (a shared link's card) doesn't carry the tagline and was not rendered again; its tile's lime moved from
`.viewer .tile.mark` to `.tile.mark` in `og.css`, the same colour.

**`docs/media/social-preview.png`** (1280 × 640, **219,529 B**): the brand pass's template
(`docs/evidence/2026-10-19/brand-kit-1/social-preview.html`), changed in place: the lockup, the same three lines
(64 / 34 / 26 px), `hidebox.app`, the still. Made with that pass's `shots_brand.py --readme`, which still works for the
README's pictures and this card. Its last step (`og_candidate`) now stops with an error, because `og.html` has no
typed name left to swap: the candidate it drew is what `og.html` draws now.

The cards' alt text, on every page and on the app page and `/drive`: "The {{BRAND}} logo over three lines: Your
private cloud storage. Store, send, and sell files privately. Built on Tari. No KYC. No email. Beside them, an open
box with files rising out of it in its light."

GitHub's social card is set by hand in the repository's settings: upload `docs/media/social-preview.png` there.

## The claims

`tools/claim-registry.json` registers both lines, so `check-copy` fails any other wording of them:

| Id | Sentence | Markers | Condition |
|---|---|---|---|
| C58 | Store, send, and sell files privately. | `sell files privately`, `send, and sell` | Store is the drive, send a link or Send by Tari, sell is pay to open (`features.pay_to_open`, on at hidebox.app), privately is C32 and C1-n |
| C59 | Built on Tari. No KYC. No email. | `no kyc` | We ask for no name, no ID document, no email and no password; we store a random id and a hash of the login key (C29, `handlers/auth.py` register); payments go between Tari addresses |

A deployment with pay to open off would still show "sell" in the hero: the hero has no variant for it, since the owner's
words are fixed and the cards, the README and the manifest can't change per deployment either. hidebox.app has it on.

## Checks

- **New in the site suite:** `check_tagline` (static) holds the hero to the three lines in order with no other
  paragraph, keeps the tagline off every other page and partial (the Say It Once Rule), checks that the previews of
  `/`, the app page and `/drive` quote it, that the home's description opens with it, that the manifest and `og/og.html`
  carry it, and that `--hero-dim` is dimmer than `--fg-2` and at least 4.5:1 on the page, in each of v2.css's three
  blocks that set it (light, the dark switch, the OS's dark). A copy of the second line on `/how` makes it fail, and so
  does a light grey in one dark block alone.
- **Nothing pinned the old tagline:** no test, check-seo expectation or fixture named it. The claim registry kept its
  C32 sentence.
- **Found, not changed:** `check_contrast` (M-03) parses `tokens.css` so that the OS's dark block,
  `:root:not([data-theme="light"])` after a comment, lands in the light table: its light pass has been checking dark
  values. Read correctly, light `--line` on `--bg` is 2.88:1, under the 3:1 it asks for. `check_tagline` uses a parser
  that reads both themes right (`theme_tokens`); `check_contrast` is as it was, for the owner to decide on `--line`.
- **Budgets:** M-01, V-02 and the share cards' 150 KB limit, in the suites below.

## Suites

On the server as `build`, on a copy of the final tree (logs in `suites/` of the evidence):

| Suite | Result |
|---|---|
| `tools/lint.py` | PASS (0 problems) |
| `tools/check-copy.py` | PASS (0 problems; the same 15 lines to read as before, none new) |
| `tools/build.py` (production origin, stamped with the base commit, since the copy has no `.git`) | OK, 374 files, 6 pages |
| `tools/check-seo.py --dist` on that build | PASS (13 passed, 3 skipped: what only Caddy sets); `og.png` 1,200 × 630, 146,584 B |
| `deploy/tests` | OK, 113 tests |
| `web/site/tests/run.py` (static and browser checks) | 46 of 46, `check_tagline` among them |

The budgets, from the site suite's notes: **M-01** on `/`, HTML, CSS and JS 58.3 KB gzip of 60 KB (38 requests, 143.7 KB
in all, 1 font file, 0 third-party); **V-02**, 268,785 B at load at 1440 and 251,428 B at 390, the hero's still first;
the home's stylesheets 7,637 B gzip of 8,704 (`home.css` +2,442 of its 3,328 B allowance); the home's words above the
fold 41 at 1440 and 26 at 390 (of 120); **the share card limit**: `og.png` 146,584 B of 153,600, `og-s.png` unchanged at
24,901 B.
