---
name: shushbox
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
  muted-foreground: "oklch(0.556 0 0)"
  accent: "oklch(0.97 0 0)"
  destructive: "oklch(0.577 0.245 27.325)"
  border: "oklch(0.922 0 0)"
  input: "oklch(0.922 0 0)"
  ring: "oklch(0.708 0 0)"
  sidebar: "oklch(0.985 0 0)"
  sidebar-primary: "oklch(0.205 0 0)"
  tari: "oklch(0.491 0.27 292.581)"
  success: "oklch(0.508 0.118 165.612)"
  warning: "oklch(0.555 0.163 48.998)"
  chart-1: "oklch(0.646 0.222 41.116)"
  chart-2: "oklch(0.6 0.118 184.704)"
  chart-3: "oklch(0.398 0.07 227.392)"
  chart-4: "oklch(0.828 0.189 84.429)"
  background-dark: "oklch(0.145 0 0)"
  foreground-dark: "oklch(0.985 0 0)"
  card-dark: "oklch(0.205 0 0)"
  primary-dark: "oklch(0.922 0 0)"
  primary-foreground-dark: "oklch(0.205 0 0)"
  muted-dark: "oklch(0.269 0 0)"
  muted-foreground-dark: "oklch(0.708 0 0)"
  destructive-dark: "oklch(0.704 0.191 22.216)"
  border-dark: "oklch(1 0 0 / 10%)"
  input-dark: "oklch(1 0 0 / 15%)"
  sidebar-dark: "oklch(0.205 0 0)"
  sidebar-primary-dark: "oklch(0.488 0.243 264.376)"
  tari-dark: "oklch(0.811 0.111 293.571)"
  success-dark: "oklch(0.845 0.143 164.978)"
  warning-dark: "oklch(0.879 0.169 91.605)"
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
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
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

# Design System: shushbox

> Written in Phase 6A, second run (2026-10-13), from the built prototype in `research/design/drive/`
> (jarvis side): `ui/tokens.css`, `ui/components.css`, `ui/behaviors.js`, `app.css`. It replaces the
> "bye" ghost system. Phase 6B moves these files into `web/shared/` and `web/app/ui/`. The tokens are
> shadcn/ui's, copied exactly; the frontmatter is normative. The sidecar with shadows, motion and
> breakpoints lives beside the prototype (`research/design/drive/.impeccable/design.json`), because this
> workflow may write only PRODUCT.md and DESIGN.md in the repository.

## Overview

**Creative north star: a drive you already know how to use, where every file wears its rule.** The
layout is Google Drive's (sidebar with New, My drive, Received, Shared, Recent, Starred, Trash and a
storage meter; a header with search; folder cards; a file table with a menu on each row). The atoms are
shadcn/ui's "new-york" components, ported to plain CSS and about four hundred lines of our own
JavaScript, so the product reads as a careful modern app and not as a vibe-coded page. The one signature
is the **rule badge**: a small named pill with a Lucide icon (Once, 3 opens, Until Oct 14, Secret word,
Pay 0.5 tTARI, Sent by Tari, Public link, Private, Link ended) on every file row, folder card, share
step, activity sheet and on the home page's slice of a drive.

The mood is calm, bright and exact: neutral greys, near-black ink, one violet that only ever means
Tari. Anti-references: the retired ghost (mascot, indigo night, phosphor), crypto dashboards (neon on
black, glowing edges), and generic landing pages (gradient hero, three equal feature cards, eyebrows).

## Colors

Restrained: shadcn's neutral scale carries the whole interface; colour appears only where it means
something.

### Primary
- **Ink** (`primary`): primary buttons, the checked radio card ring, the active switch, the progress
  fill, the brand square. In dark mode it flips to near-white (`primary-dark`) with dark text.

### Secondary
- **Tari Violet** (`tari`, from shadcn's own "violet" theme; `tari-dark` on dark): only for things that
  are Tari: the Pay to open and Sent by Tari badges, the Tari choices in the share dialog, tTARI
  amounts, chain receipts and the "What the chain shows" note.

### Tertiary
- **Done green** (`success`, shadcn "emerald"): link ready, paid and checked, delivered, upload done.
- **Soon amber** (`warning`, shadcn "amber"): space nearly full, starred files.
- **Destructive red** (`destructive`): Move to trash, Delete my drive, failed sends.
- **Chart 1 to 4**: the storage breakdown bar only (Photos, Videos, Music, Papers).

### Neutral
- `background`, `card`, `popover` (white / near-black), `muted` and `accent` (hover and quiet fills),
  `muted-foreground` (secondary text), `border` and `input` (hairlines), `ring` (focus), `sidebar` (the
  slightly tinted rail).

### Named Rules
**The Violet Means Tari Rule.** If it is not a Tari payment, address, amount or receipt, it is not
violet. Nothing decorative is ever violet.
**The Colour Is A Word Rule.** Green, amber and red appear only next to the word they qualify (Paid,
Full, Delete); never as decoration, dots or backgrounds of whole sections.
**The QR Is Ink On White Rule.** QR codes stay dark on white in both themes so every camera reads them.

## Typography

One family: **Geist** (Vercel, SIL OFL 1.1), vendored as one variable woff2 (69,760 bytes, SHA-256
`2ffebe993e969069a9789d15164b7715d42491b5835516c5e3b935d5f81b05f1`, checked against Vercel's repository) and served first-party, with the system
sans as fallback. Addresses, links and keys use the system monospace. Product UI uses a fixed rem scale.

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
**The One Breath Rule.** Product strings read at Flesch-Kincaid grade 5 or lower (measured with
`research/design/copy/fk.py`); How it was made at grade 8 or lower.
**The No Digits Rule.** Numbers in copy are `{variables}` from `/api/v1/config`.

## Layout

- **App shell (drive, received, storage):** a 16rem sidebar (fixed, collapsible with Ctrl/Cmd + B) and
  an inset main area with a 3.5rem header (sidebar toggle, search that opens the command palette, Get
  more space, theme, help). Page padding 1rem on phones, 1.5rem from 768px.
- **Phones:** the sidebar becomes an 18rem sheet from the left; the file table becomes a list (icon,
  name, then the rule badge and its state on a second line); a floating New button sits bottom right;
  dialogs fill the width minus 1rem gutters with stacked footers (primary on top); the QR code is
  hidden and Share becomes the primary action.
- **Folder cards** flow in an auto-fill grid (min 15rem). **Reading pages** keep a 44rem column.
- **Home:** a two-column hero from 1024px (copy left, a slice of a drive right), then the quick-share
  band, the rules grouped the way the share dialog asks, the Tari rows and the footer.

## Elevation & Depth

Flat, with shadcn's four shadows: `xs` on outline buttons and inputs, `sm` on cards and the active tab,
`md` on menus, `lg` on dialogs, sheets, the upload panel and the hero's drive slice. Overlays dim the
page with black at 50%. Nothing glows.

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
- Height 2.25rem with a mouse, **2.75rem on touch** (project rule, the one deliberate size change).
- Focus: border in `ring` plus a 3px ring at 50%. Press: a half-pixel drop. Disabled: 50% opacity.

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
  `accent` and turns medium weight; Received carries a count badge. Breadcrumbs inside folders.
  Command palette on Ctrl/Cmd + K (files, folders, places).

### The share dialog (signature component)
- One question per step, at most three choices, each a radio card (icon tile, title, one-line
  description, radio on the right): **Who can open it?** (Anyone with the link / Someone who pays you /
  One Tari address) then, for links, **How many times can it open?** (Once / A few times with a count
  select / No limit) then **Until when?** (Until a time / Until I stop it). "Ask for a secret word" is a
  switch on the last link step. Pay to open asks the price (three named amounts) and whether buyers see
  names first; Send by Tari asks the address and shows the safety code. The result shows the rule
  sentence, the link with Copy, the QR on computers, and the key note.
- A file that already has a link opens on two tabs: New link and Links (state, Copy, Stop this link).

### Rows, menus and sheets
- Every row and folder ends in a kebab menu: Share, Copy a once link, See activity, Download, Rename,
  Move, Add to starred, Move to trash (destructive, last, after a separator).
- See activity opens a right sheet with a timeline (opened, paid, delivered, ended, the chain receipt)
  and links to What our server knows and Check it on chain.
- Toasts follow Sonner: bottom right (full width on phones), 4 seconds, an Undo action where it applies.

## Do's and Don'ts

### Do:
- **Do** show every file's rule as a badge with its icon and its state (opens left, ends, paid,
  delivered) in words.
- **Do** keep each share decision to one question and at most three named choices.
- **Do** keep violet for Tari, green for done, amber for soon, red for destructive, and nothing else.
- **Do** build every overlay with the shared behaviours (focus trap, Escape, outside click where
  allowed, focus return) and every icon from the Lucide sprite.

### Don't:
- **Don't** bring back a mascot or any illustration beyond Lucide line icons in empty states.
- **Don't** add gradients, glows, glass panels or coloured section backgrounds.
- **Don't** use an eyebrow or kicker label above a heading; the heading speaks alone.
- **Don't** put an em dash or en dash in visible text; empty table cells stay empty (with a hidden
  "None" for screen readers).
- **Don't** load a font, script, icon or style from anyone else's server.
