<!-- SPDX-License-Identifier: MIT -->
# Home v2: the home with the product loops, at /v2 (2026-10-17)

The owner, in his words: "put a home page v2 on a new link, with all the videos in transparent mode. When you place
them, check that they work with the text, the content and the section they sit in. Better yet: check which sections
the page actually has, and build the style from the mega.io reference." No confirmations were possible (the owner was
away); every decision below was made from the brief, the page and the clips, and is recorded here.

**Live:** <https://srv2052606.hstgr.cloud/v2> (also `/v2/`). The home at `/` is unchanged byte for byte; `/v2` is in no
menu, header, footer, sitemap or JSON-LD graph, carries `<meta name="robots" content="noindex">` and Caddy adds
`X-Robots-Tag: noindex`. Evidence: [`docs/evidence/2026-10-17/home-v2/`](../evidence/2026-10-17/home-v2/).

## What the page actually has, and where each loop went

The home has seven parts. The five places below (four loops, the hero's used twice) are the owner's proposal, which
held up once each clip was watched frame by frame (contact sheets of every tenth frame, made with ffmpeg on ultron)
and set beside its section's words:

| Section (as the home has it) | Loop | What the loop shows | Why it fits, and how it sits |
|---|---|---|---|
| Hero: "Your private cloud storage. / Privacy isn't an option. / It's the default." | A (`hidebox-A-hero`) | A gunmetal box, five glass file tiles floating over it, a lime padlock that opens and closes | The drive itself, as the object the headline names. Computer: the words on the left, the box on the right at 5:4, its transparent edge bleeding 24 px past the column in dark mode. Phone: the words, Open your drive and the note first (the button stays in the first screen at 390 × 844), the loop under them, the slice of a drive after it |
| Just share one thing | none | | The live drop widget is the real thing; a loop beside it would be a picture next to the product |
| Share it your way | none | | Its picture is already the share window drawn from the drive's parts; two pictures side by side would fight |
| What's different from a usual drive? | C (`hidebox-C-encrypt`) | A clear file tile slides into a frosted pane with a padlock; the pane lights lime as the file goes in, then the file comes back | The intro's first line, "Your files lock here, in your browser.", happening. Computer: the loop on the left at 4:3, the question and the intro on the right, the comparison full width below (it was 880 px; now the content width, the question 26 %, hidebox 42 %). Phone: the question, the intro, the loop, the table's cards |
| Who sees what | B (the owner's `hidebox-B-vault`, served as `hidebox-B-sides`) | A frosted box: from outside, the files inside are only shapes | What "Our server" sees: a padded size and an hour, never the name or what's inside. Computer: the four sides in two columns on the left, the box on the right at 1:1, held in view (sticky) while the cards pass. Phone: the intro, the box, the four cards |
| Tari does the private parts. (with What's tTARI?) | D (`hidebox-D-pay`) | A frosted padlock tile turning beside a lime coin, over a steel pedestal | The section's first row, "Pay to open: they pay your Tari address, then it opens." (pay to open is on in this deployment), and the intro's "The chain shows a payment with a hidden amount and a hidden owner. The fee is public." Computer: the coin on the left at 1:1, held in view while the words, the three rows and What's tTARI? pass on the right. Phone: the heading, the loop, the rows, the box |
| Make your drive. (the closing) | A again | The same box | The last ask is the first picture again: the drive you are about to make, centred over "Make your drive." and Open your drive, smaller (440 px), so the button stays the end of the page. The same file as the hero's, so the browser can reuse its bytes |

Nothing was moved from the proposal; the two sections left without a loop are the ones whose picture is already the
product. The reading order is the page's in every width: each loop is `aria-hidden`, has no words, and sits in the
DOM after its section's heading (CSS grid areas put it left or right on a computer).

**Does each one work with its words?** Checked in the screenshots at 1440 and 390 in both themes: no loop sits
under a word; the hero's lime padlock is smaller and lower than the lime button, so the button stays the page's one
action; the loops' lime (the padlock, the lit pane, the coin) only appears on their dark stage, where it reads at
full strength; the closing's padlock sits above the heading and the button below it, and never beside the button.
Each frame is cropped to its object with `object-fit` (A 5:4, C 4:3, B and D 1:1 on a computer, 4:3 on a phone)
and its top 5 %, sides 7 % and floor (from 82 to 86 % down) fade out with a CSS mask, so no frame edge or floor
reflection ends in a line.

## Design decisions

Read as: a preview of the same landing page for judges and strangers, in mega.io's product-page treatment (the
owner's reference: its homepage puts a looping product video beside each section's words on generous dark space,
in alternating feature blocks; we read its markup on 2026-10-17). The brand stays: the words, Geist, the lime as the
one action, the badges, the slice of a drive, the header and footer, the reveals of `motion.js`.

- **Dark first.** `v2.html` opens with `<html data-theme="dark">`, so it is dark until the visitor presses the light
  switch; a choice already stored on this device (the site's `mutis.theme`) still wins, and the switch works as on
  every page. One `theme-color`, the page's `#0A0A0A`.
- **One continuous dark space.** In dark mode the second surface of the alternating sections is the page colour
  too (`--v2-alt`), so the page reads as one night with the sections' hairlines and rulers as seams. Section padding
  grows to 72 px on a phone and 120 px from 1024 px (the home: 64 and 96).
- **The stage.** Each loop sits on a `.stage`: in dark mode no box at all, only a soft pool of light behind the
  object (`rgb(255 255 255 / .065)`, a radial falloff), the "soft studio light"; in light mode a dark card,
  gunmetal to ink (`#2B2F35` to `#17191C` to `#0A0A0A`, a radial gradient lit from above), with a 1 px light inner edge
  and a soft drop shadow, radius 14 px like every card. That card is what keeps the WebM's floor smudges and D's
  rough pedestal matte off a white page.
- **Glass-lit cards in dark mode.** The slice of a drive, the share window, the three of Who sees what's four sides
  that are not "You" (that one keeps its lime tint), the Tari rows and What's tTARI? are lit like mega.io's frosted
  panels: a white gradient from 6 % to 2 % over the page colour, a white 9 % hairline and a brighter top edge (17 %),
  the edge that catches the light. They are opaque and carry no `backdrop-filter`: nothing sits behind them but the
  page, so a blur would show nothing, and a blur near a playing loop costs a phone every frame. (A first version had
  the blur and an inset highlight; in headless Chromium the inset highlight beside the slice's large shadow drew
  stray rectangles over the slice while a loop played, so the highlight became the top border.) Light mode keeps the
  drive's plain cards; under `prefers-contrast: more` they are solid with the control border.
- **The hero.** The headline's first sentence at `clamp(34px, 10vw, 68px)`; its second line ("Privacy isn't an
  option. / It's the default.") stays inside the `<h1>`, in grey, at half that size: two large lines and two small
  ones, and the button's top sits at 474 px on a 1440 × 900 screen (380 px on a 390 × 844 phone, 369 px on a 360 × 740
  one). The lede is 18 px on a computer so its second sentence holds one line beside the box. The box arrives with the
  home's `pop` keyframe (from 95 % and an 8 px blur, 700 ms) as the words rise.
- **What left v2:** the two fields (the grid behind the hero and the pixels behind the closing). The loops are this
  page's motion, and a field moving under a moving object competes with it. The home keeps both.
- **Layout families:** the hero (words left, object right), the widget and the share window (as on the home), What's
  different (object left, words right, then a full-width table), Who sees what (cards left, a held object right),
  Tari (a held object left, words and rows right), the closing (centred). No eyebrow, no em dash, one radius scale
  (8 / 10 / 14 / full, the home's), one accent.
- **Pause motion.** The loops run for as long as the page is open, longer than five seconds, so WCAG 2.2.2 asks for a
  way to stop them. A 36 px round switch (44 px on touch) sits in the hero loop's lower corner, glass on the dark stage
  (`rgb(10 10 10 / .55)`, a white hairline, a 12 px blur over the loop, solid under `prefers-reduced-transparency`),
  named "Pause motion" with `aria-pressed`, Lucide's pause and play icons (inline, unmodified paths: the shared sprite
  has neither, and it is a file the home serves). Pressed, every loop on the page stops, no other loop is fetched, and
  the choice is kept on this device (`mutis.loops`); pressed again, the loops in view play. It is hidden with reduced
  motion, where nothing moves. The one new label on the page; it carries no claim.
- **A departure on purpose.** DESIGN.md's "Don't add gradients, glows, glass panels" holds for the home and the app;
  v2's lit cards, light pools and gunmetal stages are the owner's mega.io reference and live only in `v2.css`, under
  `body.v2`.

## How the loops load and play

Every loop is one element, as the brief set it out:

```html
<video data-clip muted autoplay loop playsinline preload="none" disablepictureinpicture disableremoteplayback
       width="832" height="480" data-poster="/site/media/motion/hidebox-C-encrypt_poster.png">
  <source data-src="/site/media/motion/hidebox-C-encrypt.webm" type='video/webm; codecs="vp9"'>
  <source data-src="/site/media/motion/hidebox-C-encrypt.mp4" type="video/mp4">
</video>
<noscript><img class="still" src="/site/media/motion/hidebox-C-encrypt_poster.png" alt="" width="832" height="480" loading="lazy"></noscript>
```

The hero's is the same with `preload="metadata"` and a real `poster` (preloaded with `fetchpriority="high"`), and no
`<noscript>` (its poster is already there). `web/site/js/clips.js` (1,533 bytes gzip, `/v2` only) does the rest:

- **Nothing below the fold is fetched at load.** The sources wait in `data-src` and the posters in `data-poster`, so a
  `<video>` with `autoplay` has nothing to load. An `IntersectionObserver` (40 % of a screen of margin) gives a loop
  its poster and, when motion is allowed, its sources, then calls `load()`; `autoplay` starts it.
- **It plays only while on screen.** A second observer plays it while a fifth of it or more is visible and pauses it
  below that; a loop that starts while still off screen is paused at once, and every loop pauses while the tab is
  hidden. A refused `play()` (a phone's low-power mode) leaves the poster.
- **Reduced motion:** `html.motion` (set by `theme.js` when `prefers-reduced-motion` is not `reduce`) is absent, so
  a loop only ever gets its poster, as it comes near; nothing is fetched but posters and nothing plays.
- **Safari and every browser on iOS (WebKit):** they play VP9 WebM but drop its alpha, which would put a black box
  over the page. So we did both things the brief allowed: `clips.js` detects WebKit (`AppleWebKit` without
  `Chrome`, `Chromium`, `Edg` or `OPR`; Chrome and Firefox on iOS say `CriOS` and `FxiOS`, and are WebKit too),
  removes the WebM source so it plays the 140 to 400 KB MP4 made on black (remuxed with `-movflags +faststart`,
  the video stream unchanged, so Safari can start it from the first bytes), and marks the stage `.is-opaque`: in
  light mode the stage's card turns the MP4's own black (`#000`), and in dark mode the stage has no card and no
  light pool, so the MP4's black frame fades into the `#0A0A0A` page through the same edge mask. Either way the
  difference from the alpha version is a slightly darker object surround, not a box.
- **Without JavaScript:** the hero shows its poster; the other loops show their poster through the lazy `<noscript>`
  image.
- **Paused by the visitor:** like reduced motion from then on (posters only), until the switch is pressed again.
- **Trusted Types:** the page runs under the app policy (`require-trusted-types-for 'script'`). `source.src`,
  `video.poster` and `load()` are not Trusted Types sinks, so `clips.js` needs no policy.

## Where it lives and how it ships

- **The page:** `web/site/pages/v2.html`, built by `tools/build.py` like every page (`pages/v2.html` →
  `dist/v2/index.html`). It was made from `index.html`'s own blocks, so its words are the home's in the home's order;
  the site suite now checks that (V-01, below), and only the `<title>` differs ("hidebox: your private cloud storage",
  since titles must be unique). It has no JSON-LD, its canonical and `og:url` are `/v2`, and `build.py`'s sitemap
  already leaves out any page with `noindex`. Stylesheets: the home's five plus `/site/css/v2.css` (3,139 bytes
  gzip); scripts: `theme.js`, `site.js`, `clips.js`. No file the home serves changed.
- **The media:** `web/site/media/motion/`, the owner's twelve files (`/home/lcam/hidebox-motion/`): four WebMs (0.9
  to 3.2 MB) and four posters (180 to 240 KB) as he made them, four MP4s (140 to 400 KB) remuxed with `ffmpeg -c copy
  -movflags +faststart` on ultron (the index moved to the front; the video stream's MD5 is the same before and after,
  and so is each file's size), 11,181,061 bytes in all. B is served as `hidebox-B-sides` (the owner's file name has a
  word the copy check bans, and it would sit in a public URL). The keyframes are not used (the posters are the first
  frames at the clips' own size, and the stills would have been the largest files). The pipeline has no way to serve static files from outside the release: Caddy's only outside root is
  `/srv/mutis/status`, for the timers' JSON, and anything served from there would escape the manifest and
  `verify-deploy`. So the files are committed like every other served file: `build.py` now serves `.webm` and `.mp4`
  and copies `web/site/media/` to `dist/site/media/`, the manifest lists them and `verify-deploy` downloads and hashes
  them. This is about 11 MB in the public repository, once.
- **Caddy:** `/v2`, `/v2/` and `/v2/index.html` get the app policy (the page mounts the drop widget, and that policy's
  `media-src 'self'` is what lets video play; the site policy has none), `X-Robots-Tag: noindex` and the usual
  revalidation; `/site/media/*` keeps the site policy and `Cache-Control: public, max-age=86400` (a day, like the
  font: the names carry no version, so never `immutable`), so the closing reuses the hero's bytes. Caddy's file
  server answers byte ranges and Debian's MIME table gives `video/webm` and `video/mp4`. `tests/e2e/headers_spec.py`
  lists both routes and the media's headers; `test_headers.py` (D-01) asks the live site; `deploy/tests/test_config.py`
  checks the Caddyfile says the same.
- **Not in the judged surface:** no link to `/v2` from any page, partial or static file (checked), `robots.txt` and
  `llms*.txt` unchanged, the sitemap unchanged.

## V-01: v2's own budget, and the tests

`/v2` is a preview, outside M-01 (the home's 60 KB of HTML, CSS and JS) and A-06 (the widget's bytes), which stay
the home's and did not move. It gets its own row, V-01, checked by the site suite:

| V-01 | Limit | Now |
|---|---|---|
| Each loop's WebM / MP4 / poster | 3,500,000 / 512,000 / 256,000 B | at most 3,241,933 / 403,555 / 238,804 B |
| `web/site/media/` in all | 12,582,912 B | 11,181,061 B (12 files) |
| `v2.css` / `clips.js`, gzip -9 | 4,096 / 2,048 B | 3,139 / 1,533 B |
| At load, a computer or an Android phone (no scrolling) | 3 MiB, and only the hero's WebM and poster among the media | 2,852,889 B on a computer, 2,852,117 B on an Android phone (the test server; production below) |
| At load, an iPhone (WebKit) | 1 MiB, the MP4, never a WebM | 906,460 B |
| After scrolling through every loop (the test server caches nothing, so the closing fetches the hero's file again) | 14 MiB | 12,794,588 B on a computer, 3,021,849 B on an iPhone; with reduced motion 468,320 B at load and 1,341,002 B after scrolling (posters only) |

- `web/site/tests/static_checks.py` `check_v2` (the files' half): `/v2` is noindex and has no JSON-LD; no page, partial
  or static text links it; its visible words equal the home's but for the title, and so do its links, buttons, copy
  variants (`data-when`, `hidden`), test ids and labels (the Pause motion switch aside); the switch is there; every
  `<video data-clip>` is muted, autoplay, loop, playsinline, with its sources in `data-src` (the WebM with
  `codecs="vp9"` first, then the MP4), the
  first with `preload="metadata"` and its poster, the others `preload="none"`, `data-poster` and a lazy `<noscript>`
  still; every file they name exists; no other page, stylesheet or script names the media folder; the budget rows
  above. Each of those was checked against a broken copy of the page (noindex removed, a word changed, a `preload`, a
  `src`, the lazy still, a CTA's link, a variant's `hidden`, a label, the switch), and each failed it.
- `web/site/tests/browser_checks.py` `check_v2` (the loading half, headless Chromium): dark first; at load only the
  hero's WebM and poster among the media, and the hero plays; scrolling down half a screen at a time, no loop plays
  off screen and every loop wholly on screen plays; after scrolling, all four loops and posters were asked for; the
  bytes; no console error or CSP violation; reduced motion: no WebM or MP4 asked for, every loop paused at 0 s on its
  poster and the switch hidden; an iPhone's Safari: the MP4, no WebM, and in light mode the stage's card the MP4's
  black; light mode: every stage has its dark card; Pause motion: pressed, every loop stops and scrolling fetches no
  more, a reload keeps it paused and fetches no loop, pressed again the hero plays. A copy of `clips.js` that loaded
  everything at once and never paused failed it at once (every loop asked for at load, the load budget passed, loops
  playing off screen). `/v2` also joins the
  every-page check (no error, no CSP violation, no sideways scroll at 1440, 390 and 360, one `<h1>`).
- `web/site/tests/serve.py` serves `/v2` under the app policy, the media with their types and in byte ranges.
- `deploy/tests/test_build.py`: `pages/v2.html` builds to `v2/index.html`, the loops reach `dist/site/media/` byte for
  byte and the manifest, a `.mov` stays out, and the sitemap has no `/v2`. `deploy/tests/test_config.py`: the
  Caddyfile's routes as above, ahead of the catch-all.

## The skills

**design-taste-frontend.** Read as a preview redesign that keeps the brand (preserve), Persuade mode, dials
variance 7, motion 5, density 4. Pre-flight items that mattered here: the hero fits the first screen with its button
(474 px at 1440 × 900, 380 px at 390 × 844); one accent, locked (the lime of Open your drive; the loops' own lime
stays inside their dark stages); no eyebrows, no em dash in visible text, no scroll cue; one theme for the whole page
(dark first, light by the switch, never a section in the other theme); no layout family three times in a row; the
loops are motivated (each shows what its section says) and honour reduced motion, and they stop on request.

**impeccable.** `impeccable context` loaded PRODUCT.md and DESIGN.md (no surface brief); the run was a refinement
with an owner-pinned reference, so the incumbent words, type and colours stay and the reference sets the treatment.
`impeccable detect --json` over `v2.html`, `v2.css` and `clips.js` gave 23 findings: the kinds site-v2.md, site-v3.md
and site-v4.md already explain (icon tiles above the four sides' and the tTARI box's headings, a section's border
flush with its first child, the violet badge text, Geist as the face, a flat ratio between 16 px body and the 17 px
card titles, the hero's `clamp(34px, …, 68px)`, which is the home's own, and its second line at half of it), and new
ones that are intended: the
stage's gunmetal `#2B2F35` and the black `#000` under WebKit's MP4 (v2's own, documented above) and a stage's video
flush against it (the point of a stage). One was fixed: it read the headline's second line, then `.5em`, as 8 px
text (it resolves the em against an unstyled heading); the size is now written as `clamp(17px, 5vw, 34px)`, the
same values in the browser, which the detector then lists as off the ramp like the hero's. The impeccable interview could not run (the owner was away and said to
proceed), so every decision came from the brief, the clips and the page, as recorded here.

## Release

Commit `8fa0925` on `main` (from `da8f943`), deployed with `deploy/scripts/deploy.sh 8fa0925`: release
`8fa092522902ceaa22cc26c068f233392f05a3d8-cd224129f`, 177 files (162 before; the 15 new ones are v2's), the Caddyfile
validated and reloaded, smoke PASS, the manifest `74d9d0bc69bc…` notarized through SealLog in tx
`a7a1e1a35bb206a88ceda904d63820ff5f6d97bd9ae61009b77a028368e09f5a`. **The tag `spooky-secrets-2026-10` was not moved**:
the judged surface is unchanged, so it stays at `0e05f27`.

| Check | Result |
|---|---|
| Suites before the release (ultron, as build) | lint PASS, check-copy PASS, server 331 OK (5 skipped), deploy 81 OK, app core ALL PASS (9 steps), UI 723/723, site 37/37 (V-01's static and browser checks are the two new ones). The deploy gate: server 328 OK (6 skipped), deploy OK, lint, copy |
| verify-deploy against the release (`8fa0925`) | 0 differences across 177 files; SealLog's template on chain byte for byte |
| verify-deploy against the tag (`0e05f27`) | 18 differences, each expected: the commit; the 15 new files; `made/index.html` and `llms-full.txt`, where the only changed lines name the commit a visitor should verify (/made prints the deployed commit, so a judge following it gets 0) |
| The home | `/` is byte for byte the tag's build (the same SHA-256, `c0608fb7…`); the sitemap lists the same five pages; no page, sitemap, robots or llms file mentions `/v2` |
| D-01 (`test_headers.py`) | PASS on production, `/v2` and `/v2/` included (the app policy, `X-Robots-Tag: noindex`), and the loops' type, ranges and cache |
| Live probe (production, headless Chromium, cache off) | at load: a computer 2,712,418 B and an Android phone 2,712,369 B (the hero's WebM and poster only), an iPhone 739,779 B (the MP4), reduced motion 331,777 B (the poster only); after scrolling through: 12,419,232 B on a computer with the cache off (the closing fetches the hero's file again), 10,043,206 B with the cache on (it doesn't), 2,615,821 B on an iPhone, 965,789 B with reduced motion; no loop played off screen; no console error |

Evidence: [`docs/evidence/2026-10-17/home-v2/`](../evidence/2026-10-17/home-v2/).

## Screenshots

All from production, headless Chromium on ultron as `build` (`docs/evidence/2026-10-17/home-v2/shots_v2.py`). The
best four:

- `v2-1440-dark.webp`: the hero, dark first, the drive beside the words.
- `v2-1440-light-who.webp`: Who sees what in light mode, the four sides beside the box on its dark stage.
- `v2-1440-dark-tari.webp`: Tari does the private parts, the coin held beside the rows and What's tTARI?.
- `v2-390-dark-full-1.webp`: the phone, the words and the button first, each loop under its section's intro.

Also: both themes' whole pages at 1440 and 390, each loop's section at 1440 in both themes, the iPhone's MP4 in both
themes, reduced motion, and two frames of the hero a second apart.

## Not done, and open

- **Real devices.** Every browser here was headless Chromium on ultron (software GL), with an iPhone's user agent for
  the WebKit path. Safari's handling of the MP4, the edge mask over it and the Pause motion switch on a real iPhone
  were not seen.
- **No E2E batch and no film** this pass: the app, the API and the home are as released at `0e05f27`.
- **The judges' tag** stays at `0e05f27`; if v2 is ever to become the home, that is a new release and a new tag.
- **Weight.** After a full scroll a computer has fetched about 10 MB (the WebMs are 0.9 to 3.2 MB each). Re-encoding
  them smaller (shorter GOPs, a lower bitrate, or 640 px wide) would cut that; the owner's files were shipped as made.
