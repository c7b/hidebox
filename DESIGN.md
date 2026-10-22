---
name: hidebox
description: Your private drive. Locked here. Shared your way.
colors:
  background: "oklch(1 0 0)"
  foreground: "oklch(0.145 0 0)"
  card: "oklch(1 0 0)"
  popover: "oklch(1 0 0)"
  primary: "oklch(0.205 0 0)"
  primary-foreground: "oklch(0.985 0 0)"
  secondary: "oklch(0.97 0 0)"
  muted: "oklch(0.97 0 0)"
  muted-foreground: "oklch(0.51 0 0)"       # drive v3: the site's --fg-2 #666666 (shadcn's #737373 was 4.35:1 on muted)
  accent: "oklch(0.97 0 0)"
  destructive: "oklch(0.577 0.245 27.325)"
  border: "oklch(0.922 0 0)"
  input: "oklch(0.922 0 0)"
  ring: "oklch(0.708 0 0)"
  sidebar: "oklch(0.985 0 0)"
  sidebar-primary: "oklch(0.205 0 0)"
  tari: "oklch(0.491 0.27 292.581)"
  success: "oklch(0.508 0.118 165.612)"
  warning: "oklch(0.53 0.163 48.998)"        # drive v3: a step darker, 4.8:1 on its own wash
  chart-1: "oklch(0.646 0.222 41.116)"
  chart-2: "oklch(0.6 0.118 184.704)"
  chart-3: "oklch(0.398 0.07 227.392)"
  chart-4: "oklch(0.828 0.189 84.429)"
  background-dark: "oklch(0.145 0 0)"
  foreground-dark: "oklch(0.985 0 0)"
  card-dark: "oklch(0.192 0.0055 258.4)"   # drive v3: gunmetal 850 #131417 under the glass
  popover-dark: "oklch(0.212 0.0067 258.4)"  # gunmetal 800 #17191C, v3's stage
  primary-dark: "oklch(0.922 0 0)"
  primary-foreground-dark: "oklch(0.205 0 0)"
  muted-dark: "oklch(0.25 0.0088 258.4)"   # gunmetal 700 #1F2226 (secondary and accent too)
  muted-foreground-dark: "oklch(0.708 0 0)"
  destructive-dark: "oklch(0.704 0.191 22.216)"
  border-dark: "oklch(1 0 0 / 10%)"
  input-dark: "oklch(1 0 0 / 15%)"
  sidebar-dark: "oklch(0.178 0.0045 258.4)" # gunmetal 900 #101113, the panel beside the void
  sidebar-primary-dark: "oklch(0.488 0.243 264.376)"   # shadcn's value; the brand tile does NOT use it (pinned to primary)
  tari-dark: "oklch(0.699 0.176 294.1)"     # drive v3: the site's pay-text #A684FF, on a 12% violet wash
  gunmetal-600: "#2B2F35"                   # v3's stage light; the start screen's card in light mode (radial to #0A0A0A)
  chip-dark: "rgb(255 255 255 / 0.07)"      # a rule badge's fill in dark (light: secondary)
  success-dark: "oklch(0.845 0.143 164.978)"
  warning-dark: "oklch(0.879 0.169 91.605)"
  brand: "oklch(0.918 0.235 126.3)"         # Lime 400 = Tari's green #BCFE00, the Open your drive fill, both themes (site v3, research/17-brand.md v2)
  on-brand: "oklch(0.145 0 0)"              # #0A0A0A, 16.32:1 on the fill
  brand-hover: "oklch(0.871 0.215 126.1)"
  brand-edge: "oklch(0.55 0.14 128.2)"      # light only: the fill's 1 px outline (lime on white is 1.21:1)
  brand-text: "oklch(0.45 0.11 128.1)"
  brand-subtle: "oklch(0.985 0.035 126.5)"
  brand-border: "oklch(0.93 0.131 126.1)"
  brand-tile: "oklch(0.966 0.07 125.9)"
  brand-field: "oklch(0.62 0.16 127.9)"     # the static grid's lines (/judges)
  brand-text-dark: "oklch(0.918 0.235 126.3)"
  brand-subtle-dark: "oklch(0.218 0.034 126.5)"
  brand-border-dark: "oklch(0.381 0.08 126)"
  brand-tile-dark: "oklch(0.3 0.061 126.2)"
  brand-field-dark: "oklch(0.75 0.18 125.9)"
  hero-dim: "#737373"                       # the home hero's third line (tagline-2): dimmer than fg-2, 4.74:1 on white
  hero-dim-dark: "#858585"                  # 5.37:1 on #0A0A0A
typography:
  display:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "3rem"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.025em"
  heading:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.333
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.43
  reading:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.75
  label:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1
  caption:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.333
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, Liberation Mono, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.43
rounded:
  xs: "0.125rem"
  sm: "0.375rem"
  md: "0.5rem"
  lg: "0.625rem"
  xl: "0.875rem"
  full: "9999px"
spacing:
  "1": "0.25rem"
  "2": "0.5rem"
  "3": "0.75rem"
  "4": "1rem"
  "6": "1.5rem"
  "8": "2rem"
  "12": "3rem"
  "24": "6rem"
components:
  button-primary:                           # site v4: each view's one primary is the lime (Ink before)
    backgroundColor: "{colors.brand}"
    textColor: "{colors.on-brand}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
    height: "2.25rem"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
    height: "2.25rem"
  button-ghost-hover:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "oklch(1 0 0)"
    rounded: "{rounded.md}"
    height: "2.25rem"
  badge-rule:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.foreground}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "0.125rem 0.5rem"
  badge-tari:
    backgroundColor: "oklch(0.491 0.27 292.581 / 0.09)"
    textColor: "{colors.tari}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "0.125rem 0.5rem"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
    padding: "1.5rem"
  input:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "0.25rem 0.75rem"
    height: "2.25rem"
  sidebar:
    backgroundColor: "{colors.sidebar}"
    width: "16rem"
  sidebar-item-active:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "2rem"
  dialog:
    backgroundColor: "{colors.background}"
    rounded: "{rounded.lg}"
    padding: "1.5rem"
    width: "32rem"
  menu:
    backgroundColor: "{colors.popover}"
    rounded: "{rounded.md}"
    padding: "0.25rem"
---

# Design System: hidebox

> Written in Phase 6A, second run (2026-10-13), from the built prototype in `research/design/drive/`
> (kept outside this repository): `ui/tokens.css`, `ui/components.css`, `ui/behaviors.js`, `app.css`; updated the same day by the
> fix pass after the critique (`research/16-drive-design.md` §8, §14). It replaces the
> "bye" ghost system. Phase 6B moves these files into `web/shared/` and `web/app/ui/`. The tokens are
> shadcn/ui's, copied exactly; the frontmatter is normative. The sidecar with shadows, motion and
> breakpoints lives beside the prototype (`research/design/drive/.impeccable/design.json`), because this
> workflow may write only PRODUCT.md and DESIGN.md in the repository.

## Overview

**Creative north star: a drive you already know how to use, where every file wears its rule.** The
layout is Google Drive's (sidebar with New, My drive, Received, Shared, Earnings where pay to open is on, Activity,
Trash and a storage meter; a header with search and Upgrade; folder cards; a file table with a menu on each row). The atoms are
shadcn/ui's "new-york" components, ported to plain CSS and about four hundred lines of our own
JavaScript, so the product reads as a careful modern app and not as a vibe-coded page. The one signature
is the **rule badge**: a small named pill with a Lucide icon (Once, 3 opens, Until Oct 14, Secret word,
Pay 0.1 tTARI, Sent by Tari, Public link, Private, Link ended, Getting ready) on every file row, folder card,
share step, activity sheet and on the home page's slice of a drive, with a second outline badge when a file
is set to leave ("Leaves Oct 20").

The mood is calm, bright and exact: neutral greys, near-black ink, one violet that only ever means
Tari. **Drive v3** (docs/review/drive-v3.md, the owner's "match the same vibe of v3"): in dark the drive is the home's
v3 world, the black void (`#0A0A0A`) with gunmetal panels (one cool ramp at OKLCH hue 258, from v3's stage `#17191C` to
`#2B2F35`) and frosted glass on every raised surface; in light it is the site's light (white, the `#FAFAFA` rail,
`#666666` secondary text). The mark is the open box, lime on its ink tile in both themes, with the wordmark beside it. Anti-references: the retired ghost (mascot, indigo night, phosphor), crypto dashboards (neon on
black, glowing edges), and generic landing pages (gradient hero, three equal feature cards, eyebrows).

## Colors

Restrained: shadcn's neutral scale carries the whole interface; colour appears only where it means
something.

### Primary
- **Ink** (`primary`): the checked radio card ring, the active switch and checkbox, the progress fill, the
  brand square (pinned to `primary` in both themes, never shadcn's blue dark `sidebar-primary`). In dark mode it
  flips to near-white (`primary-dark`) with dark text. Until site v4 it also filled the primary buttons; now
  the one filled primary of each view is lime (below). The sidebar New and the phone's floating New are white
  bordered buttons, like Google's, except where they are that view's primary.

### Brand
- **Lime** (`brand`, Tari's green `#BCFE00`, OKLCH hue 126, one computed ramp, `web/shared/tokens.css` `--lime-*`
  and the `--brand-*` roles; research/17-brand.md v2 has the ramp, the reasoning and every measured pair): the
  public pages' one action colour, beside Ink, chosen by the owner for site v3 in place of Sea. It fills
  **Open your drive**, the site's one action (header, hero, closing), under a near-black label (16.32:1), with
  a 1px lime-700 edge on light pages; tints the You card in Who sees what and the hidebox column of the
  comparison. The mark is the brand kit's (docs/review/brand-kit-1.md), in the kit's own lime, `#ACFF00`, a near twin
  of this one, kept apart by the owner's call: the open box on its ink tile (both themes) and, beside the tile in the
  site's and the drive's headers, the wordmark (the kit's outlined name, 17/30 of the tile's height), its letters in the
  text colour and the rhombus over its dotless i `#ACFF00` in both themes, the one lime on white in light mode (part of
  the mark, not text; no dark green ever goes in the mark). Light pages
  never write lime as text: brand text there is the olive lime-800 (7.20:1). **In the drive (site v4)** lime
  fills the one next step of each view, the shadcn default variant (`components.css`, the drive's
  `ui/tokens.css` `--brand-*`): Upload a folder (or Upload files) on the empty drive, New while My drive or a
  folder lists files, Share in the bar once one file is picked, Next, Make link and Copy link in the share
  dialog, Make my drive and Open on the start screen, Save key file, each dialog's confirm, Get space, Pay with
  test money and Open it on the pay page, the folder viewer's open and save; picked rows sit on the lime tint
  (`--brand-subtle`). On Under the hood the part being read sits on that tint in the contents, its words and its group's
  name in brand text, like a picked row: the one link that wears the tint, and never the fill. Everything else names its variant (outline, secondary, ghost); destructive actions,
  Delete it after included, stay red. Lime never goes on links (but for that one, on the tint), focus rings (lime on white is 1.21:1), badges,
  status or anything that is a Tari payment. The single-file link page keeps its ink Open it under the header's
  lime Open your drive, so it still has one lime.

### Secondary
- **Tari Violet** (`tari`, from shadcn's own "violet" theme; `tari-dark` on dark): only for things that
  are Tari: the Pay to open and Sent by Tari badges, the Tari choices in the share dialog, tTARI
  amounts, chain receipts, the "What the chain shows" note, the Tari address row, and the tail of the storage
  bar that is paid space.

### Tertiary
- **Done green** (`success`, shadcn "emerald"): link ready, paid and checked, delivered, upload done.
- **Soon amber** (`warning`, shadcn "amber"): space nearly full, the "This shares it too" warning on Move.
- **Destructive red** (`destructive`): Move to trash, Delete my drive, failed sends.
- **Storage ramp**: the breakdown bar is one neutral ramp (ink at 82, 58, 38 and 22 %); shadcn's chart
  colours are not used anywhere.

### Neutral
- `background`, `card`, `popover` (white / near-black), `muted` and `accent` (hover and quiet fills),
  `muted-foreground` (secondary text), `border` and `input` (hairlines), `ring` (focus), `sidebar` (the
  slightly tinted rail).

### Named Rules
**The Violet Means Tari Rule.** If it is not a Tari payment, address, amount or receipt, it is not
violet. Nothing decorative is ever violet.
**The Colour Is A Word Rule.** Green, amber and red appear only next to the word they qualify (Paid,
Full, Delete); never as decoration, dots or backgrounds of whole sections.
**The QR Is Ink On White Rule.** QR codes stay dark on white in both themes so every camera reads them. The mark sits
in the centre on a white pad (share-simple), at level Q, where every block corrects well past what it covers.
**The Lime Is Yours Rule.** Lime marks your side of hidebox: Open your drive, the open box (the mark), the You card,
the hidebox column, and in the drive the one thing to do next. If it is not yours, it is not lime; one lime a view (the tint of a picked row or of the part being read is not a second lime). Open your drive is always on in the sticky header (site v3:
the owner's call; it no longer steps aside while the page's own is in view).

## Typography

One family: **Geist** (Vercel, SIL OFL 1.1), vendored as one variable woff2 (69,760 bytes, SHA-256
`2ffebe993e969069a9789d15164b7715d42491b5835516c5e3b935d5f81b05f1`, checked against Vercel's repository) and served first-party, with the system
sans as fallback. The home loads `Geist-Latin.woff2` instead, an 18,112-byte subset of that file (weights 400
to 700, Latin-1; SHA-256 `7e1491511dafabbbef951b7f7c96fe6de94a87efe6c2343443cd4167c86b07f3`, rebuilt
byte for byte by `web/site/tools/subset-geist.sh`), pinned the same way. The public pages use the site scale
of research/17-brand.md (hero `clamp(34px, 8.6vw, 68px)`, H2 `clamp(26px, 3vw, 36px)`, say 17 to 20px, UI
label 15px, caption 12px) on top of this one. Addresses, links and keys use the system monospace. Product UI uses a fixed rem scale.

### Hierarchy
- **Display** (600, 3rem on desktop, 2.25rem on phones, 1.1): one per marketing or buyer page.
- **Heading** (600, 1.5rem): page titles in the drive ("My drive", "Received", "Storage") and section
  heads on reading pages.
- **Title** (600, 1.125rem): dialog, sheet and card titles.
- **Body** (400, 0.875rem): everything in the app, tables included; tabular numerals in counts.
- **Reading** (400, 1rem, 1.75): how it works, how it was made, judges; 68ch measure.
- **Label** (500, 0.875rem): buttons, menu items, form labels.
- **Caption** (500, 0.75rem): badges, table heads, meta lines, kbd.

### Named Rules
**The One Sentence A Line Rule (site v4, the owner's).** In any paragraph, lede, intro, note, step, card, table
cell, dialog or empty state with two or more sentences, each sentence starts on its own line: the pages put a
`<br>` after each sentence's end (the space stays, so the text reads the same to search, screen readers and
check-copy); the app's `ui/lines.js` does it for `<p>`, `<dd>` and the alert and choice text it builds; the home's
drop widget breaks its two card sentences with a newline under `white-space: pre-line` (A-06 unchanged).
Headings and the status pill stay one line. Two exceptions, the owner's: `/verify/tx`'s two facts (owner-5: what it
proves, with its link to Tari's own indexer, and what stays hidden) each read as one line, and so does the invitation
after the value (viral-1, `ui/invite.js`): "Want your own? Private drive. No email. No KYC." beside one outline button
(Make your own secret, or Sell your own files on `/p/`) and a ×, muted in a hairline box, only once the secret, folder
or bought file is open or the drop delivered, never in a browser that holds a drive; × hides it for that page view.
**The Say It Once Rule (copy-1, the owner's).** hidebox has a tagline and eight key statements. The tagline (tagline-2,
the owner's words) is "Store, send, and sell files privately." (C58) under the headline "Your private cloud storage.",
then "Built on Tari. No KYC. No email." (C59). The home's hero says it once; no other page shows it. The share cards,
the metas, the manifest, the README and the film's end card carry it as the home's words. Each key statement is said
once per page, in its best place and in its registered words (`tools/claim-registry.json`); anywhere else on that page
it is a short answer (a comparison cell: "In your browser.") or a link to where it is said, never the sentence again:
1. The lock: "Files lock in your browser first." (C32; "Files lock in this browser before upload." in the app). A fact
   for explanatory copy (the README, the home's description), not the tagline.
2. The server: "Our server gets scrambled noise. Never the key." (C1-n)
3. The names: "Search runs in this browser. Our server can't read your file names." (C43)
4. The exit rules: "Each file or folder gets its own rule. You can stop a link any time."
5. Pay to open: "Pay to open: they pay your Tari address, then it opens." and, said once for Send by Tari and Pay to
   open together, "The chain shows a payment with a hidden amount and a hidden owner. The fee is public." (C36)
6. The chain record: "When a file leaves your drive, we write that on the Tari chain, for anyone to check." (C42)
7. The account: "No email, no password. Your key is the account."
8. Losing the key: "Save your key. If this browser forgets it, nobody can let you back in, not even us." (C17-k)

On the home: the tagline in the hero, where "No KYC. No email." is 7's short answer; 1 as the comparison's short answer
("In your browser."); 4 in Share it your way, 2, 3 and 8 in the comparison, 5 and 6 in Tari does the private parts.
The testnet line is the footer's, on every page; no block repeats it. /judges' What to
check table is the one place a page lists the claims, word for word with where each shows; its steps say what the
app shows at that step. Pictures of the app (/how's stills) show the app's own words.
**The One Breath Rule.** Product strings read at Flesch-Kincaid grade 5 or lower (measured with
`research/design/copy/fk.py`); How it was made at grade 8 or lower.
**The No Digits Rule.** Numbers in copy are `{variables}` from `/api/v1/config`.

## Layout

- **App shell (drive, received, storage, activity):** a 16rem sidebar (fixed, collapsible with Ctrl/Cmd + B)
  and an inset main area with a 3.5rem header (sidebar toggle, search that filters the current view in the
  browser, Upgrade, theme, help). Page padding 1rem on phones, 1.5rem from 768px.
- **Phones:** the sidebar becomes an 18rem sheet from the left; folders become a two-column compact grid so
  files show in the first screen; the file table becomes a list (icon, name, then the badges and the state on
  a second line that wraps); a floating New button sits bottom right (white, lime while it is the view's primary)
  and the page pads its end by the button's height; dialogs fill the width minus 1rem gutters with stacked footers (primary on top); the QR
  code is hidden and Share becomes the primary action.
- **Folder cards** flow in an auto-fill grid (min 15rem) on computers. **Reading pages** keep a 44rem column.
- **Under the hood (/made) reads as docs (2026-10-17, the owner's):** the page on the second surface (`--bg-alt`),
  each part a card on it (an icon tile beside its heading, violet only for the Tari parts), the cards inside a part
  turned into wells; a breadcrumb that sticks under the header and names the part being read; from 1024px a sticky
  contents on the left in four groups that fold, the part being read on the lime tint; on phones the same contents
  in a closed On this page. Long detail waits in the accordions and What we can't hide is eleven rows that open;
  every word of the page is still there, for readers without JavaScript too.
- **Empty drive:** the brand moment (the open box's ink tile taking in two Lucide file icons), one primary (Upload a
  folder on computers, Upload files on phones), and the Tari address row with Copy.
- **No drive yet (`/drive`, drive v3):** the words and Make my drive left, the home's hero still (the open box with the
  files rising out of it, `web/site/media/v3/hero-*`) right on a computer and under the words on a phone; on the void in
  dark, on v3's gunmetal card through `lighten` in light.
- **Home (the v3 design since the twelfth pass, docs/review/promote-v3.md; its words from site v4):** dark first.
  The hero's words on the left, three lines and the button (tagline-2: the headline "Your private cloud storage.";
  under it in the h1, in grey, "Store, send, and sell files privately." (`.h1-2`, half the headline's size, balanced if
  it wraps); then "Built on Tari™. No KYC. No email." smaller and dimmer (`.hero-line`, 500, 15 to 18px, `--hero-dim`:
  #737373 on white at 4.74:1, #858585 on the ink at 5.37:1, `--fg-2` with more contrast); the 56px lime Open your drive,
  the site's one action, with nothing under it), and its still on the right: the open box with the files rising out
  of it in its light. Under them the slice of a
  drive hanging 56px into Just share one thing (its words decode from hex noise as it comes into view), then Share it
  your way (the rules grouped, the share window as the picture, tilted, with a line under it), What's different from
  a usual drive? (its still beside the question, hidebox beside one popular cloud drive under them), Who sees what
  (four cards beside the box with four faces), Tari does the private parts with What's tTARI? (beside the gem), the
  closing under the hero's still again, and the footer. Each still is opaque on the page's ink in dark mode and sits
  on a gunmetal card through `lighten` in light mode; AVIF and WebP at three widths, only the hero's fetched first.
  No WebGL field. Sections alternate two surfaces (`--bg`, `--bg-alt`); their parts arrive as they scroll in.

## Elevation & Depth

Flat, with shadcn's four shadows: `xs` on outline buttons and inputs, `sm` on cards and the active tab,
`md` on menus, `lg` on dialogs, sheets, the upload panel and the hero's drive slice. Overlays dim the
page with black at 50%. Nothing glows, but one thing, the owner's (share-simple): reached at `/#share` (the link
page's Make your own secret lands there), the home's share box wears a 1px lime ring and a soft lime light that
breathes three times and settles to a faint ring (still, with reduced motion). **Drive v3, dark only:** cards, the file table, folder cards, dialogs, sheets,
menus, toasts and alerts are frosted glass (a white light from above, 5% to 1.5%, inside an 8.5% hairline whose top
edge is 16%) on an opaque gunmetal base, so no backdrop blur sits under text; icon tiles and the mark's tile are small
frosted tiles (a 6% wash, the same lit edge); the drive's header is the one blur (it is sticky, the list passes under
it), solid with reduced transparency. Light mode stays flat, as v3's light mode does. One picture is drawn in depth (site/share, the owner's): the home's share
window leans back in perspective over a second sheet, takes no pointer, and a line under it says what it shows, so
nobody takes it for a window to use.

## Shapes

One radius scale from `--radius` 0.625rem: inputs, buttons and menu items `md` (0.5rem), dialogs `lg`,
cards and the sidebar inset `xl`, badges and switches `full`. Checkboxes 4px. Strokes are 1px
hairlines; Lucide icons use a 2px stroke at 16px.

## Components

All ported from `https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/ui/`, markup
mirroring shadcn's `data-slot` / `data-variant` / `data-size` / `data-state` attributes; behaviours in
`ui/behaviors.js` emit Radix's ARIA.

### Buttons
- Variants default (ink), outline, secondary, ghost, destructive, link; sizes sm, default, lg and icon.
- Height 2.25rem with a mouse, **2.75rem on touch** (project rule, the one deliberate size change), icon
  buttons included (row menus, folder icons, the dialog close).
- Focus: border in `ring` plus a 3px ring at 50%, on buttons, links, link-buttons and disclosures alike (never
  the browser's outline). Press: a half-pixel drop. Disabled: 50% opacity.

### Chips (if used)
- **Rule badges** are the chip: caption type, full radius, a 12px Lucide icon first. Neutral rules use
  `secondary`; Private and Link ended use `outline`; Tari rules use the soft violet.

### Cards / Containers
- shadcn card (`xl` radius, `sm` shadow, 1.5rem padding on header and content). Never nested. The file
  table sits in a bordered container with row hairlines and a muted hover; selected rows fill `muted`.

### Inputs / Fields
- Label above, 0.5rem gap, hint and error below. 1rem text on phones (no zoom), 0.875rem from 768px.
  Links, addresses and keys are read-only inputs in monospace with a Copy button beside them.

### Navigation
- Sidebar menu buttons (2rem, 2.75rem on touch) with an icon and label; the current page fills
  `accent` and turns medium weight; Received carries a count badge. Breadcrumbs inside folders. No command
  palette and no list/grid toggle (cut; the components stay available).

### The share dialog (signature component)
- One question per step, at most three choices, each a radio card (icon tile, title, one-line
  description, radio on the right): **Who can open it?** (Anyone with the link / Someone who pays you /
  One Tari address) then, for links, **How many times can it open?** (Once / A few times / No limit) with a
  defaulted line **It ends** (Tomorrow / In a week / When I stop it), the switch "Ask for a secret word" and,
  on files, the switch "Delete it from my drive after". Pay to open shows the three prices from `/config` as
  "0.1 tTARI" (no adjectives), the switch "Show the name before they pay" and, the first time, the sealed
  sales-view-key notice; Send by Tari asks the address, shows their drive ID (the 12 emoji), the switch "They use another
  Ootle wallet" and the relay-or-direct line. The result shows the rule sentence, the link with Copy, the QR
  on computers, and the key note (pay links: the split-key sentence and its boundary).
- A file that already has a link opens on two tabs: New link and Links (state, Copy, Stop this link).

### Rows, menus and sheets
- Every row and folder ends in a kebab menu: Share, Copy a once link, See activity, Download, Rename,
  Move, Delete it after…, Move to trash (destructive, last, after a separator).
- See activity opens a right sheet with a timeline (opened, paid, made, uploaded, link ended) and a button
  to **What our server knows**, a second sheet (the glass box). The drive-wide **Activity** view lists the
  same events newest first, including files that left, with their chain receipt and tx. It scales (drive-earnings-activity):
  events of one kind, in one folder, in one hour (the finest time our server keeps) are one row ("Locked and uploaded
  20 files to hidebox-brand", its size and hour) that folds open to its files; rows sit under their day with the
  day's count; the newest 25 rows first, then Show more; outline toggles filter the kinds; Download the list saves
  the whole log as CSV, made in the browser. A folder reads Folder created.
- **Earnings** (where pay to open is on) answers "where's my money?": the total in violet (an amount of tTARI) with
  the part our demo wallet paid as Test money and the testnet line under it, each paid link's take, last payment,
  opens and tx, the payments with the drive's owner check, and Where the money is: the sales address with Copy and
  what moving it out means today. No lime: nothing there is a next step.
- Move into a folder that has a link shows a `warning` alert inside the dialog ("This shares it too.").
- Toasts follow Sonner: bottom right (full width on phones), 4 seconds, an Undo action where it applies.

### Waits and their results (ux-feedback-1)
- **One vocabulary for a wait** (`web/app/ui/progress.js`, `web/app/css/flow.css`, loaded by the link and task pages and
  the drive): the run's real steps in people's words, each lit as it happens (a turning dot, then a green check; a red
  cross where it failed, the steps before it still checked), the time the lit step has taken once past two seconds, one
  line under it that can change while it waits (our relay's countdown, "The chain usually takes a few seconds."), and a
  4px bar that fills when the step knows how far it got (encryption, uploaded chunks, the relay's moment) and sweeps when
  it can't. Nothing that waits stands still; with reduced motion the clock and the words still move. Used by the drop
  page, /send, Send by Tari in the share dialog and the pay page's steps (owner-5: from the click, with what each step
  waits on; the turning dot stays ink, since lime never marks a payment's status). A single wait (reading a
  transaction) is the same dot and clock on one line.
- **One done moment**: the open box (the mark, on its ink tile) rises, the thing that went drops into it, a green check
  lands on its corner; then the line in people's words, the Tari chain's line in plain words and the transaction as a
  violet Receipt pill, then what's next. One axis, on one card. It runs once (about a second), never loops, and with
  reduced motion it is there at once. The drop page's Delivered, /verify/tx's Confirmed (a red cross for a refused one),
  /send's and the share dialog's Sent.
- **Failure says what to retry**: the failed step stays in the list, marked, and the alert under it names what still
  stands ("Your file is stored.") beside Try again.

## Do's and Don'ts

### Do:
- **Do** show every file's rule as a badge with its icon and its state (opens left, ends, paid,
  delivered) in words.
- **Do** keep each share decision to one question and at most three named choices.
- **Do** keep violet for Tari, green for done, amber for soon, red for destructive, and nothing else.
- **Do** build every overlay with the shared behaviours (focus trap, Escape, outside click where
  allowed, focus return) and every icon from the Lucide sprite.

### Don't:
- **Don't** bring back a mascot or any illustration beyond Lucide line icons in empty states (the empty
  drive's tile with two file icons is the one composed moment).
- **Don't** say a link's end goes on the chain: only a file that leaves gets a receipt.
- **Don't** add gradients, glows (but the share box's at `/#share`), glass panels or coloured bands. The home's light lives in its stills (and v2's
  gunmetal card under them in light mode), never under a word; the static grid stays /judges' one field. The drive's exceptions are v3's too, by the owner's
  choice: its frosted glass in dark mode and the gunmetal card under the start screen's still in light mode
  (Elevation & Depth).
- **Don't** hide content for motion's sake: the site's reveals and the hero picture's decode
  (`web/site/js/motion.js`) touch only what is below the fold when they run, never run without JavaScript or
  with reduced motion, stay within 700 ms and 60 ms a step, and leave the DOM as it was served. The one motion that
  repeats is /how's stills replaying what they show (`web/site/js/stills.js`): loops of 4 to 7 s that rest on the
  finished still, only while on screen, with the app's words, under one Pause motion switch; never with reduced motion.
- **Don't** use an eyebrow or kicker label above a heading; the heading speaks alone.
- **Don't** put an em dash or en dash in visible text; empty table cells stay empty (with a hidden
  "None" for screen readers).
- **Don't** load a font, script, icon or style from anyone else's server.
