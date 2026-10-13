---
name: bye
description: Give the ghost a secret. Your friend sees it once. Then it's gone.
colors:
  night: "#13183A"
  night-raised: "#1C2250"
  night-sunken: "#0C1030"
  moon: "#EEF0FF"
  moon-dim: "#AEB4DC"
  ceiling: "#F4F5FC"
  ceiling-raised: "#FCFCFF"
  ceiling-sunken: "#E7E9F6"
  ink: "#151A3B"
  ink-dim: "#474D7C"
  phosphor: "#DDFADF"
  phosphor-deep: "#BDEFC3"
  tari: "#813BF5"
  tari-text-light: "#6A2EDB"
  tari-text-dark: "#B79BFF"
  exit-light: "#A3202C"
  exit-dark: "#FF8A8A"
  paper: "#FFF6D6"
  sand: "#E2B13C"
  blush: "#FF9EB9"
typography:
  hero:
    fontFamily: "ui-rounded, SF Pro Rounded, Arial Rounded MT Bold, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "clamp(36px, 5.6vw, 68px)"
    fontWeight: 800
    lineHeight: 1.04
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "ui-rounded, system-ui, sans-serif"
    fontSize: "clamp(28px, 3.6vw, 44px)"
    fontWeight: 800
    lineHeight: 1.1
  say:
    fontFamily: "ui-rounded, system-ui, sans-serif"
    fontSize: "clamp(19px, 1.9vw, 23px)"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "ui-rounded, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "ui-rounded, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.2
  code:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, Noto Sans Mono, monospace"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.45
rounded:
  input: "14px"
  panel: "22px"
  pill: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
  s8: "64px"
  s9: "96px"
components:
  button-primary-light:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ceiling}"
    rounded: "{rounded.pill}"
    padding: "12px 24px"
    height: "48px"
  button-primary-dark:
    backgroundColor: "{colors.phosphor}"
    textColor: "{colors.night}"
    rounded: "{rounded.pill}"
    padding: "12px 24px"
    height: "48px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "10px 18px"
    height: "48px"
  card-light:
    backgroundColor: "{colors.ceiling-raised}"
    rounded: "{rounded.panel}"
    padding: "24px"
  card-dark:
    backgroundColor: "{colors.night-raised}"
    rounded: "{rounded.panel}"
    padding: "24px"
  link-field:
    backgroundColor: "{colors.ceiling-sunken}"
    textColor: "{colors.ink}"
    typography: "{typography.code}"
    rounded: "{rounded.input}"
    padding: "12px 14px"
---

# Design System: bye

> Draft written in Phase 6A (2026-10-13) from the prototype in `research/design/proto/` (outside this repository).
> It replaces the "mutis" screenplay system. Phase 6B moves these values into `web/shared/tokens.css`.

## Overview

**Creative north star: the glow-in-the-dark sticker.** Every child has seen one on a bedroom ceiling:
a pale shape that glows when the lights go off and fades as the night goes on. The ghost is that
sticker. With the lights on, the page is a cool ceiling white with night-ink lines and the ghost is a
white sheet with an ink outline; with the lights off, the page is night indigo and the ghost glows in
phosphor green-white. Fading is the timer, the dashed outline is "gone", and the light switch in the
corner is the theme toggle.

The system is calm and very plain around one lively figure. Pages have one thing to do, set large, in
a rounded system face. The anti-references are the old screenplay look (cream paper, Courier, stage
directions), crypto dashboards (neon on black, glowing edges, charts), and the generic AI landing page
(gradient hero, three feature cards, eyebrow labels).

## Colors

One accent per theme does the work: **ink** in daylight, **phosphor** at night. Tari purple appears
only on things that are Tari (the coin, the chain, the "send to a Tari address" icon, Tari text links).

### Primary
- **Night Ink** (#151A3B): text, outlines and the primary button with the lights on.
- **Phosphor** (#DDFADF): the ghost's body, the primary button and the focus ring with the lights off.

### Secondary
- **Tari Purple** (#813BF5; text #6A2EDB on light, #B79BFF on dark): Tari-only elements.

### Neutral
- **Ceiling** (#F4F5FC), **Ceiling Raised** (#FCFCFF), **Ceiling Sunken** (#E7E9F6): light grounds.
- **Night** (#13183A), **Night Raised** (#1C2250), **Night Sunken** (#0C1030): dark grounds.
- **Moon** (#EEF0FF) and **Moon Dim** (#AEB4DC): text on night; **Ink Dim** (#474D7C): secondary text
  on ceiling. All pairs measure 6.6:1 or more.
- **Paper** (#FFF6D6), **Sand** (#E2B13C), **Blush** (#FF9EB9): the ghost's props (notes, the
  hourglass sand and the key, the cheeks). Never used for text or controls.

### Named Rules
**The One Glow Rule.** Only the ghost glows (`drop-shadow(0 0 22px rgb(189 239 195 / .38))`, dark
theme only). No glowing buttons, borders or text.
**The Tari Is Purple Rule.** Purple means Tari. Nothing else may be purple.
**The QR Is Always Ink On White Rule.** The QR code keeps dark modules on #FFFFFF in both themes so
every camera reads it.

## Typography

System faces only: no web fonts, by rule. `ui-rounded` gives SF Pro Rounded on Apple devices; other
platforms fall back to their system sans. The wordmark is drawn, not set: round strokes of the same
weight as the ghost's outline.

### Hierarchy
- **Hero** (800, clamp 36 to 68px, 1.04): one per page; the ghost's line ("Give me a secret.").
- **Headline** (800, clamp 28 to 44px, 1.1): section heads and the "how it works" captions.
- **Say** (650, clamp 19 to 23px, 1.35): the ghost's sentence under the figure; at most 12 words.
- **Body** (400, 18px, 1.55, max 66ch): reading pages.
- **Label** (650, 17px): buttons, chips.
- **Code** (500, 15px, monospace): the link and addresses only, never as decoration.

### Named Rules
**The One Breath Rule.** Home, product and "how it works" copy reads at Flesch-Kincaid grade 4 or
lower, measured by `research/design/copy/fk.py`; "how it was made" at grade 8 or lower.
**The No Digits Rule.** Numbers in copy are `{variables}` from `/config`.

## Layout

Phones first. One centered column for every task screen: the figure, then its sentence, then the one
action. The home page has nothing below its first screen except the footer. The result splits into two
columns at 900px and up (the ghost with the rule on the left, the link card with the QR code on the
right). "How it works" pins a stage (the top 46% of a phone, the right seven twelfths of a desktop)
and scrolls captions past it. Reading pages keep a 66ch measure. Gutters 16 / 28 / 40px; content max
1120px.

## Elevation & Depth

Mostly flat. One soft shadow for the things you act on (the link card, judge tracks, reading tiles):
`0 1px 0 rgb(21 26 59 / .06), 0 18px 40px -24px rgb(21 26 59 / .45)` with the lights on, a hairline
plus a deep drop with the lights off. The drop overlay is a scrim, not a surface.

## Shapes

Round, like the ghost. Buttons and chips are full pills; panels 22px; inputs 14px. Outlines are 2 to
2.5px with round joins everywhere (ghost, icons, wordmark), so drawn things and UI share one line.

## Components

### The figure (signature component)
- **What it is:** the ghost inside a button. Before a drop, one tap opens the file picker; the whole
  window is its drop target. After a drop, one tap on it cycles the rule (Once, Secret word, A few
  times), and the three names sit under it as a radio group.
- **States:** ready, catch, busy, once, word, while, peek, courier, bag, keep, gone, oops. Each is a
  set of parts (eyes, mouth, two hands, props) shown by `data-state`; the hands move with a short
  spring (`cubic-bezier(.3, 1.3, .6, 1)`), the only overshoot in the system.
- **Size:** min(64vw, 270px) on phones, min(28vw, 340px) on desktop; 128 to 250px on the result.

### Buttons
- **Shape:** pill (999px), 48px tall.
- **Primary:** Night Ink on light, Phosphor on dark; one per screen.
- **Quiet:** transparent with a 1.5px line; for the secondary action ("Send it to a Tari address
  instead").
- **Text links:** underlined, 1.5px, offset .2em.
- **Press:** scale .97; hover darkens the fill. No glow, no gradient.

### Chips (the rule switch)
- **Style:** a sunken pill track holding three pills; the chosen one takes the primary fill.

### Cards
- **Corner:** 22px. **Background:** raised ground. **Shadow:** see Elevation. **Padding:** 24px.
  Never nested.

### Inputs
- **Style:** 2px line, 14px radius, raised ground. **Focus:** a 3px ring in the focus color, 2px
  offset.

### The drop overlay
- A scrim over the whole window, a dashed phosphor border inset 14px, and one line: "Let go
  anywhere." The ghost rises above it with its mouth open.

### Motion
- **Durations:** 120ms (press, hover), 200ms (state change), 340ms (reveal), under 1s for the whole
  drop: the note flies into the ghost (420ms), the ghost gulps (380ms), the card unrolls (340ms).
- **Easing:** `cubic-bezier(.22, 1, .36, 1)` everywhere; the spring only for the ghost's hands.
- **Reduced motion:** every animation becomes a cut; the float stops; "how it works" shows each scene
  as a still.

## Do's and Don'ts

- **Do** let the default be right: the link is made and copied before anyone is asked anything.
- **Do** put new choices behind the ghost (at most three names) or behind "More rules".
- **Do** keep every privacy sentence in the claim registry, with its condition.
- **Don't** add a menu to the header; the header holds the name and the light switch.
- **Don't** use eyebrow labels, section numbers, gradient text or glowing borders.
- **Don't** draw a second character, mascot or emoji; the ghost is the only figure.
- **Don't** use purple for anything that isn't Tari.
- **Don't** load a font, an icon set or any script from anywhere else.
