<!-- SPDX-License-Identifier: MIT -->
# Site v3: the owner's six changes (2026-10-16)

Branch `design/site-v3`. Input: the owner's words, decided, with no devil's-advocate pass this time; the brand
doc they amend (`research/17-brand.md`, now version 2, jarvis side); DESIGN.md. Screenshots of `/`, `/how` and
`/judges` at 1440 and 390, light and dark (the first screen, and the whole page after scrolling through it),
the hero picture caught mid-decode and the pixel field are in [`site-v3/`](site-v3/), taken with headless
Chromium on ultron as `build` by [`site-v3/shots_v3.py`](site-v3/shots_v3.py).

## What the owner asked, and what shipped

| # | The owner said | What shipped |
|---|---|---|
| 1 | "Open my drive or btn in header: put it always there, no need to hide it when scrolling, always on." | The header's button is on at every scroll position on every site page and on the app's link pages (they share the partial). The hide-while-the-hero's-is-in-view code (`site.js`'s observer, `data-cta-out`, its CSS) is gone. |
| 2 | "'Open your Drive' the only CTA." | One label, **Open your drive**, in the header, the hero and the closing; "Make my drive" is gone from the site's links. Each place keeps two links with that label and shows the one that fits before the first paint (theme.js's `data-has-drive`): `/drive?make` makes a drive where there is none, `/drive?open` (header: `/drive`) opens the one this browser has. The drive app's own words stay. /judges step 1 says "tap **Open your drive**", /how's first step is headed "Open your drive"; no registered claim sentence changed. The quick-share widget's ids, its code and A-06 are untouched. |
| 3 | "Take the Tari brand kit's bcfe00 as the action button." | `#BCFE00` is the `--brand-*` fill in both themes under a `#0A0A0A` label (16.32:1), with a 1 px lime-700 edge on light pages (lime on white is 1.21:1; the edge is 4.65:1). Sea is retired; light-page brand text is the olive lime-800 (7.20:1), dark brand text is the lime itself (16.32:1). The fields, the You card and the hidebox column follow the lime. 17-brand.md v2 and DESIGN.md carry the ramp, the pairs and the reasoning; the fine print's "not affiliated with Tari Labs" line is unchanged. |
| 4 | "Any animation as it goes down, let's copy" (rbp-saas-template.vercel.app) | `web/site/js/motion.js` and CSS transitions: the template's kinds of motion on every section of the home, /how and /judges (below). |
| 5 | The drive picture "decodes" on load | Every word in the hero's picture starts as hex noise in the grey and resolves left to right, row after row, its badge and icon fading in as it resolves, in 1.1 s. "Sees" and "Never sees" in Who sees what do the same in 360 ms as their cards arrive. |
| 6 | "Add PixelBlast in some part ... with the green style of the kit." | `web/site/js/pixel.js`, a dependency-free WebGL2 port, behind the home's closing (why: below). |

## The green: what the kit says

The owner's copy of the Tari Brand Kit PDF could not be fetched. Every public source read on 2026-10-16 gives
**`#C9EB00`**, not `#BCFE00`: Tari's own extraction of the kit (`tari-project/community-discourse`,
`branding/STYLE_GUIDE.md`, "Extracted from the Tari Brand Kit on 2026-04-24": Green `#C9EB00`, "Highlights,
success states"), tari.com's theme (`brightGreen[500]: "#C9EB00"`, button hover `#b3d800`, `color: #000` on it,
focus rings `3px solid #c9eb00`) and the 2025-06-05 kit zip (`research/02` §3.3). `#BCFE00` appears nowhere
public. The kit pairs the green with Ink `#040723` and puts black text on it; its one usage note is "Never use
Green text on light. Green works only on dark (Ink) backgrounds", which is why light pages write brand text in
olive. We shipped the owner's `#BCFE00` as decided; `#C9EB00` is a one-line switch (`--lime-400`) that passes
the same checks (`#0A0A0A` on it 14.49:1).

## The template's motion, and what we copied

The template is Next.js with framer-motion (motion v12) and Lenis; its house easing is
`cubic-bezier(.23, 1, .32, 1)`. Read from its page chunks (`98ccb4d597fc3e91.js`, `3b638f2d8380e640.js`) and
the server-rendered initial states:

| The template does | Its numbers | Here |
|---|---|---|
| Hero entrance on load, staggered | `{opacity:0, y:20, filter:"blur(8px)"}` per line, the CTA from `scale:.95` + blur, 0.8 s, `staggerChildren:.15`; the picture `y:40`, 1 s | CSS keyframes under `html.motion`: each line rises 20 px out of an 8 px blur, the button grows from 95 %, the picture rises 40 px; 700 ms, 60 ms apart (our limits) |
| Fade-up as blocks enter the viewport, once | section heads `y:20` 0.6 s; cards `y:40` 0.6 to 0.8 s, `delay:.1*i`; list items `y:20` 0.5 s, `delay:.05*i`; logos opacity only | headings `y:20` + 8 px blur 700 ms; paragraphs `y:20` 600 ms; cards `y:40` 700 ms; pictures `y:40` from 97 % 700 ms; rows `y:12` 500 ms; badges from 90 % + 4 px blur 400 ms; things arriving together 60 ms apart, at most 8 steps |
| Word-by-word blur-in of a large paragraph, tied to scroll | opacity .15 → 1, blur 8 px → 0 per word, scrubbed by scroll position, reverses | one statement a page (the comparison's line on the home, "Each claim, word for word" on /judges), words out of the blur on arrival, at most 60 ms apart; not scrubbed, so no paragraph is ever left half faded |
| Scroll-linked progress line beside "How it works" | a 2 px track filled by `useScroll` from "start 0.3" to "end 0.7" | /how's steps: the same line, scroll-driven CSS (`view-timeline`), no script, where the browser supports it |
| Button micro-interactions | hover scale 1.02, tap .98, the CTA arrow rotates -45° | Open your drive ends in an arrow that turns -45° on hover; press scale .97 (unchanged) |
| Logo marquee, testimonial carousel, pointer parallax on the hero picture, Lenis smooth scroll | | not copied: no logos or quotes here; parallax and scroll hijacking fight the picture's job and reduced motion (the template ignores reduced motion for its framer reveals) |

Rules held: nothing over 700 ms, no stagger over 60 ms an item, no bounce; only opacity, translate, scale and
blur, so no layout shift; only what is below the fold when motion.js runs is hidden first, so nothing on
screen blinks out; nothing is hidden without JavaScript (the classes come from JavaScript; the hero's keyframes
need `html.motion`, which theme.js sets only when scripts run and motion is allowed); with reduced motion
neither module loads and every word is there at once. Every element is left as the page served it (no
stray class or style attribute).

## The decode

`motion.js` lays an aria-hidden layer over the picture with one span per word, at the word's own place and in
its own type (measured with a Range), and scrambles it in hex (`0-9a-f`, in `--fg-2`) at 20 Hz while it
resolves left to right. The real words stay in the DOM, unseen (`opacity: 0`), so screen readers read them the
whole time; as each resolves it crossfades in (160 ms) with its badge or icon, and the layer goes when the last
one has. Head first, then the column names, then the rows 55 ms apart (name, badge, state 40 ms apart); 1.1 s
in all. Until motion.js takes over (`html.mo`), home.css keeps only the picture's words unseen, for 3 s at most;
if the module fails to load they show at once. With reduced motion the module never loads and the picture is
whole from the first paint. A browser check compares the picture's DOM after the decode with a reduced-motion
load: identical.

## Where PixelBlast lives, and why

Behind the home's closing ("Make your drive." and Open your drive). The hero already has the grid; the last ask
of the page gets the second field, so the page opens and closes on the brand and the one action sits between
them. The /judges head was the other candidate; it stays calm and fast for the people who read it closely, with
its static grid. Its parts: value-noise fbm thresholded through an 8 × 8 Bayer matrix (computed with bit
operations, not a table) into 4 px square pixels that drift slowly, in `--brand-px` (lime-600 light, lime-d-fx
dark) where thin and the fill's lime where dense; a blast from Open your drive the first time it is seen
(1.4 s), and a ripple when the pointer meets the button or it takes focus (at most once per 1.5 s). One WebGL2
pass at one fragment per pattern pixel, scaled up crisp (`image-rendering: pixelated`), about 1/16 of a
full-size pass. It draws only while on screen in a visible tab, loads after the load event when the section
comes near, and never with reduced motion; without WebGL2, without JavaScript or after a lost context the CSS
pixels show, kept to the section's padding and the sides of a 640 px column. Words are never over pixels: the
shader clears a box 16 px around the heading, the line and the button (alpha 0, so their contrast is the
page's own: 19.80:1 and 5.74:1 light, 18.97:1 and 7.85:1 dark for the heading and the grey line).

## What the two skills flagged

**design-taste-frontend.** Design read: the landing and judge pages of a private drive, for strangers and contest
judges, calm and exact shadcn-neutral, now with Tari's lime as the one action colour and a motion layer; vanilla
CSS, IntersectionObserver reveals, two small WebGL fields. Dials 4 / 6 / 4 (variance, motion, density): motion
up from 3 because the owner asked for it. Pre-flight: one CTA intent and one label (the old Make/Open pair was
two labels for one intent, now fixed); one accent locked across every section (the lime; violet keeps its Tari
meaning); CTA contrast 16.32:1; no em dashes; no `scroll` listeners (IntersectionObserver and scroll-driven
CSS only); reduced motion honoured everywhere; the centred hero and the HTML product pictures stay (the brief's,
as in v2).

**impeccable.** `impeccable context` loaded PRODUCT.md and DESIGN.md; the animate and colorize references and
the craft floor were read before the edits. Its animate guidance prefers one rehearsed focal sequence to
repeated section reveals; the owner asked for reveals everywhere, so they stay, kept short (12 to 40 px, at
most 700 ms) and once only, and the decode is the one authored moment. Its browser-surface check led to text
selection in the lime. `impeccable detect --json` over the changed pages, partials, stylesheets and modules (41
findings):

| Finding (count) | Decision |
|---|---|
| icon-tile-stack (10), cramped-padding (9), overused-font (4), design-system-font-size (4), flat-type-hierarchy (3) | Unchanged from v2 and false for the same reasons (site-v2.md) |
| design-system-color (6) | `#000` in masks, and the detector's own computed colours; the lime is now in DESIGN.md's frontmatter |
| side-tab (1) | False: `.sec::before` is the ruler on the seam |
| design-system-radius (1) | Changed: the progress line lost its 1 px radius |
| bounce-easing (1) | Pre-existing `--ease-spring` (the retired ghost's hands); the site's motion uses `--ease-out` only |
| nested-cards (1), repeated-container-text (1) | Pre-existing on /how and /judges, unchanged |

## Numbers

| Check | Before (v2, `410f210`) | After |
|---|---|---|
| A-06, phone, at load / after a drop | 25,001 / 40,536 B (of 40,960) | 25,001 / 40,536 B (no `/app/` file changed) |
| A-06, computer with the code to scan | 43,503 B (of 43,520) | 43,503 B |
| A-06d, /drive until its table renders | 113,793 B (of 131,072) | 113,793 B |
| A-06h, field.js / motion.js / pixel.js gzip -9 | 3,428 B / n/a / n/a | 3,463 B (of 6,144) / 3,149 B (of 4,096) / 3,640 B (of 8,192) |
| A-06h, home.css gzip -9 (of 1,770 + 3,072) | 4,005 B (+2,235) | 4,684 B (+2,914): the growth row stays at 3,072 B, no raise needed |
| M-01, HTML+CSS+JS on / (gzip, of 60 KB) | 53.4 KB | 57.9 KB (motion.js is in it; pixel.js loads only near the closing) |
| Home words, at 390 / 1440 (of 800; fold of 120) | 689 at 1440 | 667 / 686; fold 63 / 68 |
| Suites (ultron, as build) | | lint PASS, check-copy PASS, app core 9/9, UI 691/691, site 35/35 |

The word count now runs with reduced motion: with motion on, the words waiting below the fold for their
reveal are invisible to a count that only reads what is on screen, and the budget would have been met by
hiding words rather than by having few.
