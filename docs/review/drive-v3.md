<!-- SPDX-License-Identifier: MIT -->
# Drive v3: the drive in the home's v3 look (2026-10-18)

The owner approved the site's v3 look (`/v3`, [home-v3.md](home-v3.md)): the black void, gunmetal, frosted glass, one
lime and the open box as the mark. His order for the app, in his words: "update all the other icons and colors in
/drive to match the same vibe of v3." This pass is the app's half; another session promoted v3 to the home and swapped
the site's mark (`site/promote-v3`), and this branch was built on that branch (its mark commit, `408f08f` after its last
rebase) so the two merge as one.
The raw evidence (`docs/evidence/2026-10-18/drive-v3/`) was pruned on 2026-10-20; the results it recorded are below.

Kept: site v4's rule ([site-v4.md](site-v4.md)): exactly one lime action per view, destructive red, the picked row on
the lime tint. No copy changed; no font, library or install was added; the Lucide sprite stays.

## The mark

The open box replaces the padlock everywhere the drive draws its brand tile: the sidebar (hidebox / My drive), the
start screen (no drive yet), the empty drive's brand moment, and the top bar of the link pages that switch to the
drive's look (the pay page and the folder viewer). It is the promotion's `i-hidebox` symbol in
`web/shared/ui/icons.svg` (one sprite, `currentColor`), so the app and the site draw the same three strokes; no copy
of the mark was added. The favicon and icons are the promotion's files too (`/favicon.svg`, `/favicon-32.png`,
`/apple-touch-icon.png`, the manifest's `icon-192` and `icon-512`, all the open box since its `74cff8d`): `drive.html`,
`app.html` and `view.html` named only the SVG, and now name the 32 px PNG and the touch icon as the home's head does,
so a browser without SVG favicons and a phone's home screen show the open box too. The app pages link no manifest (the
site's starts at `/`). The drive's 404 ("This page isn't here.") and its dialogs show no mark, only Lucide tiles.

**Light theme: the ink tile, not the lime alone.** Lime on white is **1.21:1**, below the 3:1 a graphic needs, so the
lime box sits on the ink tile (`#0A0A0A`) in both themes, as the site header does: lime on ink **16.32:1**, the ink
tile on white **19.80:1**. The white variant (`final-a-open-white-*`) was not needed. In dark the tile is the void on a
gunmetal rail (1.05:1 by itself), so it gets v3's frosted edge (a 9 % hairline, a lit top edge at 18 %), drawn by
`--tile-edge`; the lime box is still 16.32:1 on it.

## Colours: one palette, the site's and v3's

Everything is in the app's token file, `web/shared/ui/tokens.css` (the drive, the pay page and the folder viewer read
it). The site's `web/shared/tokens.css` is untouched: the home reads it (M-01) and its values are already v3's (void
`#0A0A0A`, `#171717` raised, `#666666` / `#A3A3A3` secondary text).

| Token | Light before → after | Dark before → after |
|---|---|---|
| `--background` | `#FFFFFF` | `#0A0A0A` (the void; unchanged) |
| `--sidebar` | `#FAFAFA` (the site's `--bg-alt`) | `#171717` → **`#101113`** gunmetal 900 |
| `--card` | `#FFFFFF` | `#171717` → **`#131417`** gunmetal 850, under the glass |
| `--popover` | `#FFFFFF` | `#171717` → **`#17191C`** gunmetal 800 (v3's stage colour) |
| `--muted`, `--secondary`, `--accent`, `--sidebar-accent` | `#F5F5F5` | `#262626` → **`#1F2226`** gunmetal 700 |
| `--muted-foreground` | `#737373` → **`#666666`** (the site's `--fg-2`) | `#A1A1A1` (unchanged) |
| `--tari` / `--tari-soft` | `#7008E7` / 9 % (unchanged) | `#C4B4FF` / 18 % → **`#A684FF`** / 12 % (the site's `--pay-text`) |
| `--warning` | `#BB4D00` → **`#B24500`** | unchanged |
| `--sidebar-border` | `#E5E5E5` | 10 % → 8 % white |

The gunmetal ramp is one cool hue (OKLCH 258.4, v3's stage `#17191C` and `#2B2F35` measured), chroma rising with
lightness, so the panels read as the stills' metal rather than as blue. `#2B2F35` is the light top of the start
screen's card. DESIGN.md's front matter carries the new values.

New tokens, light then dark: `--glass` (none / a white light from above, 5 % to 1.5 %), `--glass-edge` and
`--glass-top` (the border / 8.5 % and 16 % white), `--tile-edge` (none / a 9 % hairline and an 18 % top edge),
`--chip` (secondary / a 7 % white wash), `--tile-fill` (muted / a 6 % white wash), `--stage`, `--stage-blend` and
`--stage-shadow` (v3's gunmetal card under a still, `lighten` / none).

## Glass, tiles, badges, icons

- **Frosted glass, dark only** (`components.css`, `drive.css`): cards, the file table (computers; the phone's list has
  no box), folder cards (hovered too), dialogs and sheets (now on `--card`), menus, toasts, alerts, the Tari address
  row, the white New buttons. It is made after v2.css's recipe, the one the home's cards use: an opaque gunmetal base, so no backdrop blur sits
  under text and contrast never depends on what is behind (the values are this drive's: 5 % to 1.5 % over gunmetal, an
  8.5 % edge with a 16 % top; v2.css has 6 % to 2.2 % over the void, 9 % and 17 %). With more contrast asked for, the glass goes flat.
- **The header** is the one blur: it is sticky and the list passes under it (`backdrop-filter: blur(14px)`), solid
  with reduced transparency.
- **Icon tiles** (folder icons, the share dialog's choice tiles, empty states, dialog media, the activity timeline)
  are small frosted tiles in dark: a 6 % wash and the lit edge. Tari's tiles keep their violet wash.
- **Badges** read as the home's slice: the rule chips (Once, A few times, Until, Secret word, Public link) are a 7 %
  white wash in dark (on glass the old `#262626` fill was the card's own colour); Private, Not selling, Getting ready,
  Link ended and Leaves stay outline, as the slice's Private and Locked; Pay to open and Sent by Tari are the site's
  violet on its violet wash. Violet appears only on
  Tari things (the drive-v3 scenario reads the text colour of every visible element of a drive with files).
- **Icons**: the Lucide sprite stays, 2 px strokes at 16 px and 12 px in badges, the same as v3's; the only icon that
  read as old was the padlock as a brand, now the open box. The lock stays where it means locked: Private, Not
  selling, the pay page's "What's inside stays locked until you pay.", Save note (it locks the note), the activity
  line "Locked and uploaded", a link page's locked file card.

## The start screen

`/drive` with no drive yet now shows the home's hero still, the open box with the files rising out of it, beside the
words on a computer and under them on a phone, the same `web/site/media/v3/hero-*` files (AVIF first, then WebP, three
widths; no new image). In dark it sits on the void with its floor faded out, as on `/v3`; in light it sits on v3's
gunmetal card through `lighten`. It is decoration (`aria-hidden`); Make my drive stays the one lime, inside the first
screen at 1440 × 900 and 390 × 844.

## The link and task pages

`app.html` and `view.html` (a Once or word link, `/send`, `/watch`, `/verify`, a drop page) keep the site's tokens and
header (the header's mark is the promotion's). Their raised surfaces (the file card, the dialogs, the receipts, the
plans) take the same glass in dark (`look.css`, a lit top edge over the hairline the dark shadow already draws), and
their `theme-color` moves from the ghost's indigo (`#F4F5FC` / `#13183A`) to `#FFFFFF` / `#0A0A0A`. Two surfaces
`app.css` keeps flat on purpose stay flat (the second choice row on /locker, the free plan on /upgrade). One thing the
screenshots showed and site v4's rule asks for: the link page's rule ("It opens one time. When you open it, the link
ends.") and its scan note sat in a `<span>`, where `lines.js` does not split, so their two sentences shared a line; they
now break (`view.js`, `lines()`; the text a screen reader or a test reads is the same).

## Contrast

Measured with the sRGB formula (WCAG 2.x) on the composited colours (the glass's lightest point, at the top of a
card); an independent recomputation from the OKLCH tokens agreed within 0.05. Every text pair the drive draws is 4.5:1
or more. Three were below it before this pass and are fixed here: a red badge's white label on the dark theme's light
red (2.89:1, now ink, 6.85:1), the highlighted Move to trash in a light menu (red on its red wash 4.01:1, red on the
grey highlight 4.38:1; now a deeper red, `--destructive-text`, on the red wash in both states, 5.06:1) and the light warning on its wash
(4.37:1, now 4.87:1). A destructive alert's text uses the same deeper red in light (6.02:1).

| Light | | Dark | |
|---|---|---|---|
| ink on white / rail / muted | 19.80 / 18.97 / 18.16 | `#FAFAFA` on void / rail / card | 18.97 / 18.10 / 17.65 |
| `#666666` on white / rail / muted | 5.74 / 5.50 / 5.27 | `#A1A1A1` on void / glass top / popover top | 7.66 / 6.31 / 6.01 |
| `#666666` on the picked row / Tari wash | 5.55 / 4.88 | `#A1A1A1` on a chip on glass | 5.11 |
| ink on a chip (`#F5F5F5`) | 18.16 | `#FAFAFA` on a chip on glass | 12.66 |
| Tari `#7008E7` on white / its wash | 7.30 / 6.20 | Tari `#A684FF` on void / glass / popover, on its wash | 6.67 / 5.53 / 5.28 |
| destructive on white | 4.77 | destructive `#FF6467` on glass / popover | 5.64 / 5.37 |
| success on white / its wash | 5.36 / 4.67 | success / warning on glass | 10.70 / 11.26 |
| warning on white / its wash | 5.61 / 4.87 (4.37 before) | the picked row's meta | 9.03 |
| lime label on the fill | 16.32 | lime on the void | 16.32 |

## Budgets

| | Before | After |
|---|---|---|
| A-06d, /drive until the table renders (of 131,072 B) | 116,965 B, 37 files (`b749cdd`); 117,471 B with the promotion (its `i-hidebox` symbol and the drive's mark, promote-v3.md) | **119,760 B**, 37 files (+2,289 B over the promotion: the token file's gunmetal, glass, chip and red-text tokens, the components' glass, the drive's v3 section) |
| The modulepreload list in `drive.html` | 23 modules | unchanged: no static import was added or removed (`view.js` gained `lines`, from a module it already imported) |
| Fonts on /drive | one, the 18 KB Latin Geist | unchanged |
| M-01, the home (of 60 KB) | 58.5 KB | not touched by this pass (no file the home loads changed); 58.4 KB with the promotion in the tree |
| The start screen's picture | none | the hero still the home already serves (no new file): 9,209 B (480 px AVIF) on a computer at 1×, the 1024 px AVIF (25,611 B) on a 3× phone; outside A-06d's files and not loaded once a drive exists |

## Tests

| Suite (the server, as `build`) | Result |
|---|---|
| Lint, check-copy | PASS, PASS |
| App core (`run_all.py`) | ALL PASS (9 steps) |
| Server, deploy | 331 OK (5 skipped), 83 OK |
| Site (`web/site/tests/run.py`) | 42/42 on the tree with the promotion (M-01 58.4 KB, the promotion's; on its first mark commit alone, V-02 failed two checks that its later commits rewrite) |
| UI (`web/app/ui/tests/run.py`) | **751/751**: the 732 before, unchanged, plus the new `drive-v3` scenario's 19 checks (twice: on `b203c86` and on the promotion's earlier head, with the same code of this pass) |

No expectation changed. `drive-primary` (one lime a view, the picked row's `#F4FFE6`, the white New's ring) passes as it
was. The new `drive-v3` scenario (`web/app/ui/tests/flows_share.py`) checks the start screen's open box (from its AVIF,
`aria-hidden`, on v3's gunmetal card through `lighten` in light, on the void in dark, inside the first screen, nothing
sideways), the void and the gunmetal rail, the file table and the key reminder as glass with a lit top edge in dark and
plain in light, v3's chip on a rule badge, the mark's frosted ink tile in dark and its lime box on ink in light, the
frosted header, `#666666` secondary text in light, and that no visible text outside a Tari thing is violet. Computed
colours given in OKLCH come back as `oklch()`, so the scenario reads them through a canvas pixel.

**An independent review** (the code-critic agent, over the diff) first failed it on three points, all fixed: the
evidence README used a word check-copy bans; the link pages' new glass also lifted two surfaces `app.css` keeps flat on
purpose (the second choice row on /locker, the free plan on /upgrade); the two-column start layout also caught the
one-child "Opening your drive" and error screens on computers. Its nits were taken (hover keeps the glass, the ring's
border wins on a focused and hovered card, the probe's canvas made once, the docs' wording) and so were the three
contrast risks it found outside the diff (a red badge, a highlighted Move to trash, a destructive alert's text). Its
second pass: PASS with nits; the last one it raised (a focused and hovered card's border) is fixed too.

## Screenshots

Pruned on 2026-10-20: each drive state before (`8351f18`) and after this branch at 1440 and 390, light and dark,
from the start screen to the share dialog and the pay link. The brand kit's evidence
(`docs/evidence/2026-10-19/brand-kit-1/after/`) has the drive after its restyle.

## Release

`main` had the promotion live (`d0f08ed`, the tag moved there by the coordinator). This branch was rebased on it (two
document conflicts, DESIGN.md and the fix log, both sides kept), the gate above ran on the code that ships, and this
session deployed **`6e20248`** with `deploy/scripts/deploy.sh` (release `6e20248d…-cd00dd644`, 203 files; server 328
OK (6 skipped), deploy tests, lint and check-copy on the server; smoke PASS; the manifest `c48f2cb9…` notarized through
SealLog in tx `a1290c29…73a6`), then pushed `main` (`d0f08ed..6e20248`). **The tag `spooky-secrets-2026-10` was not
moved**; it stays at `d0f08ed` for the coordinator to decide.

| Check | Result |
|---|---|
| verify-deploy (`deploy/verify-6e20248.log`) | 0 differences across 203 files; SealLog's template on chain byte for byte |
| D-01 (`deploy/d01-6e20248.log`) | test_headers PASS |
| Live probe (`deploy/live-probe-6e20248.log`, `live_probe.py`) | 23/23: /drive names the open box's PNG, SVG and touch icon; the app's tokens and stylesheet are this pass's; at 1440 and 390, light and dark, the start screen shows the open box from its AVIF (480 px at 1×, 1024 px on a 3× phone), one lime (Make my drive) inside the first screen, the gunmetal card in light and the void in dark, nothing sideways, no CSP or Trusted Types violation |
| The app's E2E batch (`e2e/batch.log`, `e2e/rerun.log`) | E-01, E-08, E-18, E-20, E-26, E-27, E-03 PASS. **E-28** failed once and passed on its rerun: its second Move landed on Rename (`e2e/E-28-failure-run1.png`), a tap at the menu item's centre measured while the menu still slides in (150 ms), the race the UI suite avoids by clicking through the DOM. **E-19 failed twice, outside this pass:** on the Android profile (412 × 915, 4× CPU throttling) the tap on the home's Or write one does not open the text box (`e2e/E-19-failure-412.png`); the 390 × 844 run of the same flow and the 360 px sweep pass. No file the home loads changed in this pass (the drop widget, the home's stylesheets and scripts, the site tokens); it is the v3 home's, reported to the coordinator. No judge pass was used |

## Not done, and open

- **Real devices.** Every browser here was headless Chromium on the server: Safari's `backdrop-filter` on the header,
  `:has()` on the start screen (Safari 15.4 and later; an older Safari stacks the picture under the words, as a phone
  does) and `mix-blend-mode` on the light card were not seen on an iPhone.
- **The site's own pages** (the home, /how, /made, /judges, /fine-print, 404) are the promotion's: their header carries
  the open box from its partial; this pass touched none of their files.
- **E-19 on the Android profile** fails at the home's Or write one (above); the home is the promotion's.
- **`--sidebar-primary`** in dark is still shadcn's blue in the token file; nothing reads it since the mark's tile is
  ink (DESIGN.md says so), so it was left as shadcn wrote it.
