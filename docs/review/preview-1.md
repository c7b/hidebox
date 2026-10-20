<!-- SPDX-License-Identifier: MIT -->
# Preview 1: file previews that can't run what they show (2026-10-19)

The owner's request, security first: previews in the drive (`/drive`) and on paid links (`/p/…`), one shared preview
component (a lightbox) that always has a Download button. What he saw: on a paid link a PNG opened in a preview, an
SVG downloaded at once and `.md` or `.txt` got no preview; in the drive a click on a PNG downloaded it, so he couldn't
tell which picture it was. His hard rule: previews must never become a way in. The decrypted bytes are a stranger's
(anyone can send a file to a drive or sell one on a link), and a script that ran on our origin could read the keys this
browser holds.

## The answer

A file now opens in one lightbox (`web/app/ui/lightbox.js`, `web/app/css/lightbox.css`) from three places: a file's
name in the drive, a file in a folder link's visit (the folder viewer that `/s/` folders, paid folders on `/p/` and
Received's folders share) and a paid single file, which shows itself once Open it decrypts it. What the lightbox shows
is chosen by `web/app/lib/sniff.js` from the decrypted bytes alone; the name and the stored type are never read for
that. Every kind it knows is shown through a sink that can't run anything: an `<img>` for pictures, a canvas of pixels
for SVG, one text node for text. Everything else is download only, and Download is there for every file as soon as
its bytes have arrived. The content security policy did not change.

## The allowlist

| Sniffed from the bytes | Shown as | Why it is safe |
|---|---|---|
| PNG (`89 50 4E 47 0D 0A 1A 0A`) | `<img src=blob:>`, the Blob typed `image/png` | the image decoder is the only parser; an `<img>` runs no script, loads nothing and has no events the file controls; the Blob's type is the sniffed one, so even "Open image in new tab" is an image document |
| JPEG (`FF D8 FF`) | the same, `image/jpeg` | as above |
| GIF (`GIF87a`, `GIF89a`) | the same, `image/gif` | as above; a GIF with a web page after it (the polyglot) is decoded up to its trailer and the page after it is never parsed as HTML |
| WebP (`RIFF` … `WEBPVP8`) | the same, `image/webp` | as above |
| AVIF (an `ftyp` box with `avif` or `avis`, as the major brand or under `mif1`, `msf1`, `miaf`) | the same, `image/avif` | as above; HEIC in the same container is not on the list |
| SVG: the whole file is UTF-8 without NUL bytes, at most 4 MiB, its root element is `<svg>` (after a declaration, comments, processing instructions, a doctype) and it declares no entity | drawn once into a `<canvas>` (below) | what reaches the page is pixels; no SVG document, no `<img>` of it and no address for it exist while it shows |
| Text: valid UTF-8 without NUL bytes that doesn't start with markup | one text node in a `<pre>`, its first 256 KB, then "This shows the first 256 KB. Download it to read the rest." | text nodes are never parsed; Markdown is not turned into HTML or links, so `<script>` and `javascript:` stay characters |
| Nothing (zero bytes) | "This file is empty." | nothing to show; the drive already refuses an empty upload ("That file is empty. There's nothing to lock."), so only another client could store one |
| Anything else | "No preview for this kind of file. Download it to open it." | below |

The order matters and is fixed: the raster signatures first, then the kinds that are never previewed, then the UTF-8
test, then markup, then text. A name can't move a file along it: a PNG named `.svg` is a picture, an SVG named `.png` is
drawn, HTML named `.txt` is download only. A program's name or bytes still bring the viewer's warning line ("This is a
program. Only run it if you expected it.") above whatever shows.

## The SVG decision: a canvas, not an `<img>`

Both ways the owner allowed parse the SVG in the browser's SVG engine in image mode (no script, no external loads, no
interaction): the canvas way has to load it as an image too, so the parser is the same. What differs is what stays
afterwards.

- **`<img src=blob:>` typed `image/svg+xml`** keeps a live SVG document rendering in the page for as long as it shows
  (its CSS, its animations) and keeps a `blob:` address of an active type alive on our origin. "Open image in new tab",
  dragging the picture to the tab strip, "Copy image address" or an extension turn that address into a top-level page
  on hidebox.app, where the SVG's own `<script>` would run; the only guard left then is how the browser hands the
  creator's policy to a `blob:` document. The owner's rule is never to navigate to a blob of an active type, and this
  way leaves the door to the person and to anything in the browser.
- **The canvas** (`rasterize()` in `lightbox.js`): an `Image` that never joins the page decodes the SVG, it is drawn
  once into a canvas at the stage's size (up to 8 times its own size, 4096 device pixels at most), and the `blob:`
  address is revoked in `finally`, before the canvas is shown. What remains is a bitmap: no SVG document, no address,
  nothing to open; whatever the browser offers for a canvas is a PNG of its pixels, never a page. An SVG that hasn't
  drawn in 5 seconds or doesn't decode shows "This picture didn't open here. Download it to see it."

Chosen: the canvas. The cost is small and stated: an animated SVG shows its first frame, and a very large or deeply
nested SVG keeps the opener's own tab busy while it draws (the same risk as any image bomb, with nothing exposed).
The `<img>` way is not in the code; the core suite checks that no `<img>` of the SVG is ever in the page and that its
address is revoked once it is drawn, and a mutant that keeps the `<img>` fails it (below).

## Download only, and why

| Kind | Why no preview |
|---|---|
| HTML and anything that starts with markup (every signature a browser itself sniffs as HTML, `<!DOCTYPE HTML`, `<html`, `<script`, `<body`, `<p`, `<!--` and the rest, plus XHTML and other XML), whatever its name | the owner's rule; a page is the one kind whose purpose is to run; shown as text it would be inert, but nobody should mistake its source for the page |
| PDF | a PDF is a document with its own viewer and scripting; it can't be shown as an image |
| Sound and video (ID3, Ogg, FLAC, WAVE, AVI, MP4 and other `ftyp` files, WebM and Matroska) | the owner's rule; container and codec parsers are the largest attack surface a page can reach, and they aren't needed to tell which file is which |
| Fonts (WOFF, WOFF2, OpenType, TrueType, collections) | nothing to see that a name doesn't say; font parsers are another surface |
| Archives, programs | nothing to see; programs carry the warning line |
| Other images (HEIC, BMP, TIFF, ICO) | not on the list; most browsers can't show HEIC anyway |
| Not UTF-8, or NUL bytes (UTF-16 text, any binary) | not text the preview can show as text |
| An SVG over 4 MiB, not wholly UTF-8, or with an internal entity | entities can make a small file grow inside the parser; a big drawing is a download |

Download is `lib/download.js`'s `saveFile`, unchanged: an `application/octet-stream` Blob through a hidden link with
`download` and the sanitized name, so the browser saves it and never renders it. Nothing in the change calls
`window.open`, sets `location` or frames a file.

## The component

- **Look (impeccable and design-taste-frontend, DESIGN.md's v3; no question could reach the owner in this run, so the
  direction is his brief's words and DESIGN.md's):** the stage is v3's black void (a radial from
  gunmetal `#17191C` to `#0A0A0A`) in both themes, as the start screen's still sits on v3's dark stage in light mode: a
  picture is judged on neutral black. Two floating capsules carry the chrome in the drive's frosted glass (a light from
  above on opaque gunmetal 850, the 8.5 % hairline lit at its top edge; no blur under words): the file's tile, name and
  size on the left, Download (the view's one lime) and Close on the right. A picture sits on a quiet check so a
  transparent one still shows its shape. A text file is a page laid on the void: white in light, the drive's gunmetal
  glass in dark, in the system monospace at 13 px, wrapping. The note for anything else is a glass card with the
  file's tile and two lines. Geist throughout; one sentence a line in every note.
- **Keyboard:** Esc closes; focus is trapped inside (the shared `openModal`) and goes back to the file's own control,
  found again by its id or name if the list was drawn again meanwhile; the arrow keys, Previous file and Next file move
  through the files listed beside it (a drive view as shown, search included; a folder's files), wrapping at the ends;
  Enter on a name opens it. The name is the dialog's label and is read out when the file changes.
- **Phones:** the capsules fill the width (the tile goes below 400 px), the pager sits under the stage, a sideways
  swipe on the stage moves to the next file (the stage starts no browser pan; a text file still scrolls), every
  control is 44 px; nothing scrolls sideways at 390.
- **States:** opening (the shared wait: a turning dot, "Opening…", and the 4 px bar that fills as the file arrives),
  shown, a read that failed (the caller's own alert: the drive's error, the folder visit's "This visit ended"), a
  picture that didn't decode, empty, no preview.
- **Lazy:** `lightbox.js`, `lightbox.css` and `sniff.js` load the first time a file opens (4,269, 3,138 and 3,163
  bytes compressed). Nothing in the drive's first screen imports them; the first screen carries only the six new
  strings.
- **Copy:** six strings, each a short sentence or two, no number written out (`{size}` is `formatBytes` of the cap);
  Download and Close reuse the drive's words. `tools/check-copy.py` passes; no claim marker is touched.

## Where it opens

| Place | Before | Now |
|---|---|---|
| The drive, a file's name | downloaded the file at once | opens it in the lightbox; the row menu's Download is unchanged |
| A folder link's visit (`/s/`), a paid folder on `/p/`, a folder in Received (`ui/folder-view.js`) | its own dialog, choosing by the stored type through `lib/preview.js`, nothing for SVG, Markdown or anything named as active | the lightbox, with the folder's files for the arrows |
| A paid single file on `/p/` | a row with Save, no preview | the lightbox opens as soon as Open it decrypts the file; the row's name opens it again |

## Hostile fixtures and what happened

`web/app/tests/fixtures/preview/make_fixtures.py` builds them (Python stdlib). Every script in them would set the
global canary `top.__pwned`, write `__pwned` to `localStorage` and ask for `/__canary/<which>`. The core suite renders
each one through the real lightbox in headless Chromium under the app's CSP and Trusted Types (`preview.test.js`); the UI
suite stores them in a real drive and opens them in the drive, in a folder link's visit and on a paid link, on a computer
and a phone (`flows_preview.py`). Both runners fail on any CSP or Trusted Types violation; the UI flows also fail on any
console error, page exception, top-level navigation or `window.open`.

| Fixture | The bytes | Shown as | Result (core; drive, folder link, paid link) |
|---|---|---|---|
| `script.svg`: `<script>`, `onload`, a `javascript:` link, a `foreignObject` with `<img onerror>`, an `<image>` asking for `/__canary/svg-image` | SVG | canvas | drawn; canary untouched, nothing stored, no request, no navigation, no violation |
| `svg-named.png`: the same SVG | SVG | canvas | the bytes win over the name; drawn, nothing ran; the paid-link case on a computer and a phone |
| `png-named.svg`: a real PNG | PNG | `<img>` of an `image/png` Blob | the bytes win over the name |
| `notes.md`: `<script>`, `<img onerror>`, a `javascript:` link, an autolink to one | text | one text node | the markup and links read as characters; nothing ran |
| `page.txt`: a whole HTML page | markup | download only | the bytes win over the name; nothing parsed |
| `polyglot.htm`: a valid GIF89a, then an HTML page | GIF | `<img>` of an `image/gif` Blob | shows the GIF; the page after it never parsed |
| `big.txt`: 300 KB of text | text | the first 256 KB and the note | exactly 262,144 characters, then the note |
| `empty.txt`: zero bytes | empty | "This file is empty." (core) | the drive refuses it before upload, so it never reaches a drive or a link |
| `utf16.txt` | NUL bytes | download only | |
| `tiny.pdf` | PDF | download only | |

Download saved the same bytes for every file the flows tried (`big.txt`, `polyglot.htm`, `page.txt`, `svg-named.png`
in the drive, the SVG in a folder visit and on a paid link, on both devices), always as `application/octet-stream`.

**Mutants** (`docs/evidence/2026-10-19/preview-1/suites/mutants.txt`): three deliberate breaks, each run through the
core suite in Chromium: text rendered as HTML (what a Markdown renderer that emits markup does), the SVG kept as an
`<img>` of its `blob:` address, and the name deciding (`.txt` and `.md` shown as text whatever the bytes). Each one
fails the suite (`TESTS FAIL 148/150` each): text as HTML is refused by Trusted Types before anything is parsed
(`This document requires 'TrustedHTML' assignment`) and fails the one-text-node check; the `<img>` of the SVG fails
"a canvas, no live SVG" and "the SVG's URL was revoked once drawn"; the name deciding shows `page.txt` as text where
its bytes say markup. The second lightbox test fails after each because the first left its lightbox open.

## Budgets

| Budget | Before (`main`) | After |
|---|---|---|
| A-06d, `/drive` until the table renders (of 131,072 B) | 125,365 B, 38 files (`72f3871`, the first base); 125,523 B (`bfd72c8`, today's `main`) | 125,485 B (+120 B: the six strings and `drive-list.js`'s open action); 125,645 B rebased (+122 B) |
| The files of A-06d this change touches | `en.json` 20,649 B, `drive-list.js` 6,066 B | 20,751 B (+102, the six strings), 6,084 B (+18) |
| On first open (not in any first screen) | | `lightbox.js` 4,269 B, `lightbox.css` 3,138 B, `sniff.js` 3,163 B |
| A-06 (the home's widget) | no file of the widget's path changed | unchanged: phone 25,013 / 40,510 B, computer 43,477 B, after a photo 45,548 B |

## Suites

On the server as `build`, from copies of the branch (`docs/evidence/2026-10-19/preview-1/suites/`). The branch was
rebased twice onto a moving `main` (the 404 page, upload safety, the steadier pay page); `da05e87` and `e4dd45d` are
the ids the runs had before the rebase, and the rebased tree is the one pushed.

| Suite | Full run (`da05e87`) | The review's fixes (`e4dd45d`) |
|---|---|---|
| `tools/lint.py` | PASS (0 problems) | PASS (0 problems) |
| `tools/check-copy.py` | PASS (0 problems) | PASS (0 problems) |
| `tools/build.py --origin https://hidebox.app` | OK, 216 files, 7 pages, 6 vendored files checked | (the UI suite builds its own tree) |
| App core, `web/app/tests/run_all.py` | ALL PASS (9 steps): lint 1008/1008, vectors 97/97, Node 150/150, Chromium with the app CSP 150/150, jitless 87/87, sidecar 18/18, both benchmarks, contract 12/12 | Chromium 150/150, jitless 87/87 (the two runs the fixes touch) |
| App UI, `web/app/ui/tests/run.py` | **940/940** (the three `preview-*` flows new, `drive-upload-files` and `folder-viewer` changed) | 243/243: `budget`, `drive-budget`, the three `preview-*`, `drive-upload-files`, `folder-viewer`, `folder-zip`, `received-folder`, `pay-page-states` |
| Mutants of the preview | | 3 of 3 fail the core suite |
| E2E on production, E-29 with `--candidate` | PASS (53 s) | |

**After the rebase** onto `main`'s new pay page (`paypage.js` had changed under this branch's edits; git merged them
cleanly): the core suite in Chromium 150/150, and the UI scenarios that touch the pay page, the folder viewer and the
budgets: `budget`, `drive-budget`, `preview-drive` (twice), `preview-folder`, `preview-pay`, `pay-page-states`,
`pay-progress`, `pay-steady`, `drive-upload-files`, `folder-viewer`: 172/172 and 75/75 twice (`suites/rebased/`).
The first try failed one check, and it was a real one: run without the screenshots' pauses, the phone's tap on Next
right after a swipe never became a click. The test's swipe had no time between its moves, so it ended as a fast fling,
and the next touch only stopped the fling. Two changes: the stage now takes a swipe as its own (`touch-action:
pinch-zoom`, the text page keeps its vertical scroll), so the browser starts no pan there, and the flow swipes like a
person (about 30 ms between moves, a short hold before lifting).

The impeccable detector over `lightbox.js` and `lightbox.css` leaves five advisories, all the alpha blacks of the
stage's shadows (`rgb(0 0 0 / …)`), which DESIGN.md's palette doesn't list; the off-scale size and radius it found
first were put on the scale.

## End to end on production

`tests/e2e/run.py` gained `--candidate DIST` (`tests/e2e/candidate.py`): the browser gets every page and static file of
the origin from a local build, with the live response's headers (its CSP included), while `/api/` stays live. E-29 (pay
to open a folder with test money: a drive sells a folder of three, a phone with no drive pays, the page says Paid, one file
opens, a reload keeps the claim, a second stranger gets 402) ran on `https://hidebox.app` with this branch's front end:
PASS in 53 s, 371 files from the candidate; `minutes.txt` opened on the phone in the preview as text, with Download, and
Esc put focus back on its name (`docs/evidence/2026-10-19/preview-1/e2e/`). One drive, one paid folder and one
test-money payment; the scenario takes the link down at the end. E-29 now expects the preview, so against a
deployment without it the scenario fails until this is deployed.

## Independent review

A code critic read the change against the brief (criteria 1 to 9 above): PASS_WITH_NITS, no blocking issue, "no way
for decrypted bytes to become a live document, script or navigation". Its nits, all fixed in the commit after the review: a late error
could replace the next file's view; a failed load of the module had no message; "MZ team notes" sniffed as a program
(the signature now needs a binary header); a double click could open two lightboxes or close the one it opened;
`candidate.py` served pages without the inside-the-build check its files had. Noted and left: the SVG drawing time
(above), and that decrypts of files skipped with the arrows run to the end before they are dropped.

## Left, and open

- `/s/` single-file links and Received's single files still preview through `lib/preview.js`: the earlier allowlist by
  stored type (pictures, video, sound, text; never SVG, HTML or PDF). It has no active-content path, but it trusts the
  stored type. Moving them to the lightbox is the next step; they were outside this change.
- The live pages `/made` and `/fine-print` don't mention previews yet; the threat model's "Previews" section is the
  record.
- Video and sound are download only by the owner's rule, even where `lib/preview.js` plays them on `/s/`.
