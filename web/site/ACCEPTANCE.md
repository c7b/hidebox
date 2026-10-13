<!-- SPDX-License-Identifier: MIT -->
# Acceptance: web/site and web/shared (spec §16.3)

English-only pass, 2026-10-12: run on the server as `build` (Debian 13, Python 3.13, Node 20.19.2,
Chromium 154) from `/home/build/work/english/tree`, a `git archive` of commit `fd2706f`. The Spanish
pages and their check (`check_translations`) are gone (12-integration §7.8); every other check is the
one the integration pass ran on 2026-10-11:

```
$ python3 -I web/site/tests/run.py
PASS SPDX headers
PASS no HTML/script sinks in JS
PASS markup: CSP-safe, includes, placeholders, JSON-LD
PASS banned words
PASS no typed /config numbers (P-20)
PASS variables and conditions
PASS SEO metadata (M-04)
PASS trademark and mandatory lines (M-05)
PASS partials in sync
PASS privacy inventory covers the schema (M-06)
PASS contrast table (M-03)
PASS static files (M-04)
PASS copy variants set at build time (M11)
PASS /judges quotes the app's words
PASS llms-full.txt matches /how and /security
PASS dates.js in two time zones (M-08)
PASS fonts load, no OTS error
PASS every page, desktop and 360 px
PASS home page budget (M-01)
PASS live numbers and their failure (M-07)
PASS the exit wall (M-02)
PASS the exit wall at 4x CPU on a phone
PASS copy variants from /config
PASS status line phase (M-08)
PASS abuse form: key stripped, never sent without JavaScript
PASS canary reveal (P1)
PASS theme, judge pass
note fonts: Mutis Script 400 loaded, Mutis Script 700 loaded, Mutis Script Code 400 loaded; OTS errors: 0
note budget on /: 35 requests, HTML+CSS+JS 47.0 KB gzip, other 46.4 KB, total 93.4 KB, 2 font files, third-party 0 (with the drop widget's first load)
note API blocked: /pricing hides 18 [data-needs] blocks, shows 0; / shows no live number
note wall scene: 5 stage directions over the scroll; at the end every other locker gone: True, centre opacity 1, closing words opacity 1, last direction opacity 0
note wall frames (quiet, 412x915, 4x CPU): 231 frames, median 17 ms, p95 17 ms
note wall main thread (quiet, 412x915): 1.92 ms of CPU per frame (7.7 ms at 4x); 19 elements restyled per frame (median)
note wall frames (24, 412x915, 4x CPU): 235 frames, median 17 ms, p95 17 ms
note wall main thread (24, 412x915): 1.47 ms of CPU per frame (5.9 ms at 4x); 8 elements restyled per frame (median)
note canary reveal: First line: mutis canary #788. Sealed 2025-10-08T09:00:00Z. If you can read this without t; Test file #789: missed (the verifier restarted).
27 of 27 checks without failures, 222 s
```

`/judges quotes the app's words` now reads `/judges` in each amount-proof mode and requires B6's arrow
sequence to be the app's `upgrade.step.*` labels for that mode; against B6's earlier markup (the
committed `judges.html`) it fails with `pages/judges.html (wallet): payment steps “Waiting → Seen on
chain → Added”, the app shows “Waiting → Seen by our wallet → Exists on chain → Added”`. The screenshots in `shots/` were rendered
again in the integration pass with the app's real widget in the hero (112 files then; 90 since the
Spanish ones were removed, and their footers still show the EN · ES switch the English-only pass took out).

From the site builder's fix pass, with a one-line stand-in for `web/app/drop-widget.js` (before the
app's widget existed):

```
$ python3 -I tools/build.py --out …/full-dist --source 000… 0.0.0 1760000000
build: OK {"content_id": "2cb73f54", "files": 108, ..., "pages": 22, "vendored_checked": 6, "version": "0.0.0"}
$ python3 -I tools/lint.py --only web/site           -> lint: PASS (0 problems)
$ python3 -I tools/check-copy.py --quiet             -> check-copy: PASS (0 problems, ...)
$ python3 -I web/site/tools/variants.py --config direct.toml …/full-dist-direct   # send_mode direct, amount_proof sidecar
variants: {'facts': {'send_mode': 'direct', 'proof': 'proven', 'seallog': 'off', 'kept': 'on', 'snapshots': 'weekly', 'security_drop': 'off'}, 'pages_changed': 10}
  llms-full.txt: 5 lines with "sponsor wallet"; index.html: <li data-when="send_mode=direct">, <li data-when="send_mode=relay" hidden>; app/ untouched
```

| Id | Status | Evidence |
|---|---|---|
| **M-01** `/` budget: ≤ 400 KB total, ≤ 60 KB compressed HTML+CSS+JS, ≤ 2 fonts, 0 third-party requests | **PASS** | `check_budget` reads the CDP network log of `/` at 1440×900, now with the app's real drop widget and its `widget.css` (NOTES §6), and gzips (level 9) every HTML, CSS and JS response as served (header and footer expanded, SRI attributes in place): **47.0 KB** compressed, **93.4 KB** in all (47.8 and 94.3 before the English-only pass), **35** requests, **2 font files** (Regular + Bold; Bold preloaded), **0** requests to another origin. The widget's anti-bot challenge (a `POST`) is counted as it arrived. The site's own share was 24.9 KB in the fix pass; the wall, noise, canary and chain-card code load as their sections come near (review M1). Font files: Regular 16,764 B, Bold 17,040 B, Code 16,392 B. |
| **M-02** screenshots at 390×844 and 1440×900 for every section and page, plus reduced motion; no sideways scroll at 360; the wall with `quiet`, 8 and 24 items | **PASS** (yaw ≥ 55° waived) | `shots/`: 90 WebP files, 2.9 MB, from `tests/shots.py` (home sections and the wall in 6 frames at 1440×900, 390×844 and 412×915; dark home at 1440; every page at 1440 and 390; `wall-reduced-1440/390` (the data grid: every real item lit with its rule); `wall-quiet-1440`, `wall-8-1440`; the direct-mode + SealLog variants of "Two locks" and "What we can't hide"). `check_pages`: all 11 pages at 1440 and at 360 on a touch device, `scrollWidth` never above the viewport. `check_wall`: `quiet` keeps the scripted scene; 8 items leave 9 empty lockers; 24 relabel every slot; no locker says or shows whether its file has left; a size-0 box is shallower than size 2, size 2 than size 4; reduced motion lays nothing out for motion and draws data lockers solid; with `/api/v1/canary` blocked the scene still plays and its door is drawn from local bytes; wall data that arrives after the lockers are on screen relabels nothing; the scene plays to its end frame. `check_wall_frames` (12-integration §1): 412×915 Android emulation, 4× CPU: median 17 ms, p95 17–33 ms per frame (indicative: software GL on two shared cores); the main thread spends 1.6–1.9 ms of CPU per frame (6.2–7.6 ms at 4×, budget 16.7; integration-pass run) and restyles 8–19 elements per frame (limit 32). The pre-fix code measured 5.4 ms (30 ms at 4×) and 145 elements per frame with the same probe (`REVIEW-devil.md`, builder response M9). "Side-face words readable at ≥ 55° yaw": **waived**, 11-brand v2 replaced the camera turn with front-facing 2.5-D lockers, so no words sit on side faces. |
| **M-03** every text token pair meets the 11-brand §13.2 table | **PASS** | `check_contrast` parses `../shared/tokens.css` and recomputes WCAG ratios for `--fg`, `--fg-2`, `--pay-text`, `--ok-text`, `--exit-text`, `--line` on `--bg`, `--bg-raised`, `--bg-sunken` in light and dark, the three `--on-*` pairs, and the lit keyhole on a locker. All meet their thresholds (7 / 4.5 / 3). With `prefers-contrast: more`, `--hair` now follows `--fg`, so dark-theme hairlines no longer turn into ink on the stage (review L13). |
| **M-04** SEO checklist for every indexable page; robots, llms.txt, security.txt, sitemap, OG images, favicons, manifest | **PASS** (sitemap: build) | `check_seo`: one `<h1>`, `lang`, title ≤ 60, description ≤ 155, canonical, `og:*`, `twitter:card`, `theme-color`, `<html lang="en">` on every page (one language, so no hreflang); titles unique; JSON-LD on `/` and `/faq`; 404s and `/status` are `noindex`. `check_static`: robots disallows every private path (`/t$`, so `/terms` stays crawlable, review M7), and a simulation of Google's rule matching finds every indexable page allowed and `/t`, `/s/…`, `/d/…`, `/api/…`, `/locker`, `/verify/…` blocked; security.txt has every spec §13.4 field; `og.png` 42,240 B and `og-s.png` 37,251 B ("(Only its key opens it.)", review L12) at 1200×630; icons 192, 512 and 180 px; manifest icons exist; `llms.txt` and `llms-full.txt` present. `sitemap.xml` is generated by `tools/build.py` (deploy); NOTES §1.5 lists its two fixes. |
| **M-05** trademark checklist; mandatory lines on every page | **PASS** | `check_trademark`: no Tari mark in any file name or class name; the first mention of Tari inside each page's `<main>` carries ™; the footer partials hold “Built on the Tari™ Ootle testnet.”, the independence line and the attribution line verbatim, and every page includes a footer; no sentence claims official, partner or endorsed status. No Tari logo, gem or XTM icon anywhere; the ¡-keyhole marks are ink or paper only. The 404's `soon™` joke is gone (review L7). |
| **M-06** legal pages contain every element of spec §13.2 | **PASS** (owner approval pending) | `/terms`: acceptable use, testnet with no warranty, not a backup, limits and how the quota is decided, your key = your locker, deletion, expiry and lapse, removal by id (now "any link, file or drop", what `mutis-admin takedown` can do, review M3), what we can hand over, changes, contact. `/privacy`: summary (third parties named in it: Hostinger, Let's Encrypt, Tari's indexer on demand, review M6), IP handling, **every table of `server/mutis/schema.sql`** (`check_privacy_inventory`), what we publish (every `/stats` field, the wall's two classes and who could recognise a file there), retention with C5 / C5-db (and the wrapped keys of links open at backup time, the write-ahead log) / C5-snap / C6, no cookies, no analytics, third parties, how to delete everything, your browser (C20). `/abuse`: the form ships `hidden` and appears only when `abuse.js` has its handler in place (review H1); `check_abuse` reads the request body (no `#` without the box, `#` with it, a proof of work either way), and with scripts off and with `abuse.js` blocked it types the link with a key and presses Enter like a visitor: the field can't take focus and no request carries `SECRET` or `%23`. The app's report links (`/abuse#link=…`) fill the field through `cleanLink` and leave the address bar at once: a drop link is taken, a link with a key loses it, another origin's link is refused. No scene heading on the legal, security, abuse and status pages; plain error copy (review M16). The full texts are the owner's to approve (Tier 3). |
| **M-07** live numbers only from `/stats`, `/stats/wall`, `/canary`, `/evidence.json`; they disappear on failure | **PASS** | `check_config_numbers` (P-20 (3)): no page or partial types a number `/config` provides. `check_live_numbers`, scrolling down like a visitor: with the fixtures `/` shows "No locker? Files up to 25 MB, gone within 24 hours.", the per-locker live line, the canary ("Here's a file we locked … ago"), the reveal and the chain card; with `*/api/*` and `*/evidence.json` blocked, `/` shows no `[data-needs]` block, no chain card, no canary block, the "between takes" line instead, and the scripted wall; `/pricing` hides all 18 number blocks. Without JavaScript "Try to read it" still offers the download and the curl line (review L9). The data wall reads only `{size, exit}`, as `/stats/wall` now serves (review M15). The chain card shows only when the output carrying the sealed key reads `amount: "hidden"` and `owner: "one-time key"` in the tx view. `/judges` shows "not reported yet" while `/evidence.json` has no `wasm_sha256`, and no decoy count. |
| **M-08** `dates.js`: the status line switches at 2026-11-11T00:00Z; midnight counts to local midnight in two time zones | **PASS** | `tests/dates.test.mjs` under Node 20 with `TZ=Europe/Madrid` and `TZ=America/Mexico_City`: phase flips at `MAINNET` exactly; 23:59:30 → 30 s to midnight; Oct 25 2026 has 25 h in Madrid (DST ends) and 24 h in Mexico City; `applyPhase` with a fixed clock shows exactly one line. `check_phase` does the same in Chromium on `/how`. |
| **M-09** stencil numerals (`stencil-gen.py`) | **WAIVED** | 12-integration §2 makes them optional ("only if the site builder finds a real use"). 11-brand v2 sets locker labels, scene numbers and the `23:59 → 00:00` line in Mutis Script, so there is no use for a second numeral system; nothing in the app contract depends on them. |
| **M-10** (P1) Spanish pages reviewed by the owner; zh-CN proofread | **REMOVED** (2026-10-12) / **WAIVED** (zh-CN) | The owner removed Spanish on 2026-10-12 (12-integration §7.8): the pages, `check_translations` and the `es` screenshots went with it, and `/es/*` answers 404 (`tests/e2e/headers_spec.py`). zh-CN is out of this build (12-integration §1). |

## Also checked

| What | Evidence |
|---|---|
| Fonts: renamed, subset, deterministic, no OTS error (11-brand §13.3, P-18) | unchanged in this pass: sha256 `fedf22be…` Regular, `0c985315…` Bold, `59eab36e…` Code. `check_fonts` loads all three faces in Chromium: `loaded`, 0 `OTS parsing error`. |
| CSP | Every page served with the spec §14.2 header (`/` with the app CSP and Trusted Types, the rest with the content CSP); `check_pages` finds no CSP violation on any page, and the home checks that scroll (wall, chain card, canary, reveal) load every lazily imported module under the app CSP. No inline script (JSON-LD data blocks only), no `style` attribute, no inline handler, no single-brace placeholder (`check_markup`). |
| Copy variants | `check_variants` (runtime): relay mode shows the relay sentences and hides direct and SealLog ones; `--mode direct --seallog` shows the direct and SealLog sentences, and `/`, `/how` and `/security` say that sends link back to our sponsor wallet (review H2); `/judges` B6 shows the app's payment steps for each mode. `check_build_variants` (static): every page's HTML shows the server's defaults; `variants.resolve()` for a direct, proven deployment hides and shows every variant correctly, and the `llms-full.txt` it would write discloses the sponsor-grant linkage and the proven-amount check (review M11). Payment wording follows `proof` everywhere; "not a wallet's word" only when amounts are proven (review M2). |
| No HTML sinks | `check_js_sinks`: no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, string `setTimeout` in `js/` or `../shared/*.js`. Every tx id the site links (chain card, canary, judges) passes the same 64-hex check (review L8). |
| Canary reveal (P1 item 4) | `check_reveal`: yesterday's fixture canary (sealed by `tests/make-canary.mjs` with the app's own `format.js`) opens in the page with its published key: first line `mutis canary #788. Sealed …`. The page offers the newest revealed entry that carries a key, and lists every hour the verifier lost: "Test file #789: missed (the verifier restarted)." |
| Theme, judge pass, hero | `check_interactions`: the hero's line 2 is hidden on the widget's `sealed` state and back on `idle`; Lights off survives a reload; the judge-pass box appears with JavaScript; an invalid pass is refused; `" JUDGE-0123…NPQ "` is saved lower-cased in `sessionStorage['mutis.judge']` through app-core's `store.js` and shown again on the next visit in the tab. |
| Accessibility | One `h1` per page, landmarks, skip link, visible focus ring (base.css), the wall `aria-hidden` with a screen-reader description that changes with the data, the "What we store" ciphertext keeps its text caption (review L2), labels on every form control, `role="status"` regions, tap targets ≥ 44 px on touch, no text under 12 px, no `user-scalable=no`, reduced motion honoured. `user-select: none` appears once, on the decorative `$` prompt of the command samples, so a copied command doesn't start with it (the earlier "no `user-select: none`" was wrong, review L4). A manual screen-reader pass on real devices is the owner's (12-integration §1). |
