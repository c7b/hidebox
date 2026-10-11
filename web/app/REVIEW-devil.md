<!-- SPDX-License-Identifier: MIT -->
# Devil's-advocate reviews of web/app

This file holds two reviews. The **app-ui** review (screens, widget, CSS, i18n) comes first. The
earlier **app-core** review (`lib/`, `sidecar/`, `vendor/`, `tests/`) follows it unchanged. Both
reviewers were told to write to this path, so the second one kept the first.

---

# Devil's-advocate review: app-ui (`web/app`: drop-widget.js, app.html, view.html, ui/, css/, i18n/)

Reviewer: `review-app-ui`, 2026-10-11. I re-ran everything below myself; I didn't take the report's
word for it. I didn't edit any component file. My probes live only on ultron, in
`/home/build/work/review-app-ui/` (`probe.py` reuses the builder's own harness: `run.py`, `flows.py`
and `cdp.py`).

## Verdict

The UI is careful work:
- small modules, no HTML sinks;
- a real Trusted Types posture;
- honest mode-dependent copy;
- an inbox that never tells the server which outputs are yours;
- a 181-check browser suite that I reproduced.

But the suite only walks paths where a locker already exists, or where the dev config happens to
match. In the first 5 minutes, a judge on a fresh device can hit four things:
1. **The home card's Tari action freezes forever on a first visit.**
2. **The program warning can be bypassed with one invisible character.**
3. **Judge step 3 prints the delivery amount 1,000× too large.**
4. **The production payment stepper doesn't match what `/judges` promises.**

All four are cheap to fix. Fix them before the deploy E2E.

## What I ran

| Command (ultron, user `build`, a copy of the tree in `/home/build/work/review-app-ui/mutis`) | Result |
|---|---|
| `python3 -I web/app/ui/tests/run.py` | `UI PASS 181/181`, real 5m31s. The static checks pass, and the budget is `24432 B at load, 40592 B after a drop`. One INFO line reads `after … a photo: 46456 B`. The ten-seconds flow takes `landing 1.1 s, photo to copied link 2.1 s`. |
| `python3 -I probe.py` → `probe-names` | `'invoice.b​at'` and `'run.p\|s1'`: anonymous upload **accepted**; viewer state **`opened`** (no program warning); Save file downloads **`invoice.bat`** / **`run.ps1`** (H2) |
| `probe-card2` | first visit, Change → 7 days: after 90 s the widget still shows `'Opening a free locker in this browser…'`. With a locker already in the browser, card → Send instead works (H1) |
| `probe-card` (sender with an existing locker) | send `delivered`. The card still offers **Copy link** with the **old link, which now answers `revoked`**. The recipient's What the chain saw says **`your locker reads 1000 tTARI`** (H3, M1). The drop page has **no report link in `<main>`**, and its H1 is `'Leave a file for Council.'` (M4). |
| `probe-kept` (locker present) | Only me and Until I delete it apply, and `/locker` lists both kept files. **No test in the suite covers this P1 path** (M6). |
| `tools/build.py --out <scratch>` on the jarvis box | `dist/app/shots/` holds **47 WebP files, 2.9 MB**, served publicly and listed in the hash manifest (M9) |
| `node probe/names.mjs web/app` (`lib/filetype.checkRisky` against `lib/download.sanitizeFileName`) | 5 of 7 names: `risky false`, saved as `.bat .exe .ps1 .htm .vbs` |
| code reading: every file in `ui/`, `css/`, `i18n/en.json`, the shells, `drop-widget.js`; the matching spec/brand sections | findings below |

## High: fix before the deploy E2E and the judge script

### H1. On a first visit, every card action that needs a locker freezes on "Opening a free locker in this browser…"

- **Where:** `ui/widget.js:73-79` (`lockerContext`). The `onStatus` callback calls
  `swap(stage, h('p', … t('locker.opening')))`, which takes **the card out of the page**. The caller
  is the card (`card.js send()` → `send.js sendFromCard`, or `rules.js applyRule` → `adopt`). It
  carries on inside the detached card, so nothing ever appears again.
- **Affected:** the card's single Tari action, **Send it to a Tari address instead** (brand P-6, the
  home page's Tari moment). Also Change → 7 days, 30 days, No limit, more than 10 opens, Only me and
  Until I delete it. They break only when this browser has no locker yet, which is every judge's
  first visit.
- **Evidence:** `probe-card2` (above). The first `probe-card` run timed out after 120 s waiting for
  `send-recipient`, with the stage reading "Opening a free locker in this browser…" and no JS error.
  The suite never clicks `card-send-address` (`grep card-send-address flows.py`: only the static id
  list). The `rules` flow never picks a locker option.
- **Fix:**
  - Only swap the stage when the zone is showing. For example, `lockerContext({ status = true })`
    swaps only if `stage.firstChild === zone.el`. Calls from `renderCard` pass
    `lockerContext: () => lockerContext({ status: false })`. The card already shows "Opening a free
    locker…" in its own slot (`sendFromCard`).
  - Add two flows from a fresh context: card → Send instead → `delivered`, and card → Change → 7 days
    → `data-rule` changes.

### H2. The program warning and the anonymous program refusal can be bypassed by the file name

- **Where:**
  - `ui/view.js:211` `checkRisky(meta.name, head(parts))` and `ui/sealing.js:44`
    `checkRisky(file.name, head)` check the raw name.
  - `saveFile()` → `sanitizeFileName()` (`lib/download.js:9`) then **removes** `\p{Cc}\p{Cf}` and
    `\/:*?"<>|`.
  - So `invoice.b​at` (with U+200B) or `run.p|s1` is "not a program" when checked, but is saved as
    `invoice.bat` / `run.ps1`.
  - Script types have no magic bytes, so nothing else catches them. U+200B is a legal file-name
    character on every OS, so the sender needs no special tools.
- **Why it matters:**
  - P-14 and E-22 are the safety story for an anonymous file service. "Links to them are a favourite
    phishing trick" is our own copy.
  - The anonymous refusal can always be bypassed by a modified client. The viewer's check is the one
    that counts, and it is the one that fails here.
  - The displayed name is also the raw one, so U+202E can make `photo‮gpj.exe` look like
    `photoexe.jpg`.
- **Evidence:** `probe-names` (end to end in Chromium) and `probe/names.mjs`.
- **Fix:**
  - Compute the risk, the notices and the displayed name from **the name that will be saved**:
    `const saved = sanitizeFileName(meta.name)`. Then call `checkRisky(saved, head)` in `view.js
    shown()` and `openedState()`, and do the same in `sealing.js precheck`. Show `saved` in
    `view-filename` and on the card.
  - Ask app-core (NOTES) to make `checkRisky` sanitize internally, so the sidecar and every other
    caller get it too.
  - Add `invoice.b​at` and `run.p|s1` fixtures to the `safety` flow.

### H3. Judge step 3: "What the chain saw" prints µT as tTARI ("your locker reads 1000 tTARI")

- **Where:** `ui/view.js:277`: `t('chain.amount_you', { value: d.value })`. `d.value` is the raw µT
  bigint. Everywhere else, `formatTari()` is used.
- **Evidence:**
  - `probe-card`: `Amount hidden on chain your locker reads 1000 tTARI`.
  - The builder's own screenshot `shots/inbox-390-opened.webp` shows the same.
  - The courier amount is `"1000"` µT = 0.001 tTARI.
- **Why it matters:** this is the panel that sells "amount: hidden" to the Kinkajou judge, and right
  under it the amount we can read is wrong by 10⁶/10³.
- **Fix:** `{ value: formatTari(d.value) }`. Add an assertion on `view-chain-saw` text in the
  `deaddrop` flow.

### H4. In production, the payment stepper doesn't say what `/judges` says it will

- **Production mode:** `deploy/config/mutis.toml.example` runs `amount_proof = "wallet"` (server
  default too: `server/mutis/config.py:25`). The app then shows **Waiting → Seen by our wallet →
  Exists on chain → Added** (`ui/upgrade.js steps('wallet')`, spec §12.3.3).
- **What `/judges` promises:** step B6 (`web/site/pages/judges.html:80`) promises **Waiting → Seen on
  chain → Added** in that mode (`data-when="proof=proven"` hides only "Amount proven"). The Council
  guide says "anything else is a bug".
- **Why no test catches it:**
  - The UI suite only runs the dev config (`amount_proof = "sidecar"`).
  - The site's check "/judges quotes the app's words" (`web/site/tests/static_checks.py:500`)
    matches each phrase against *any* app string, so "Seen on chain" passes even though the app
    never shows it in wallet mode.
- **Fix (one source of truth):**
  - Let the site print the wallet variant with the app's exact strings (`upgrade.step.seen_wallet`,
    `upgrade.step.exists`). Make its check pick the app's step list per mode.
  - Add an `upgrade-wallet` flow: start the dev server with `amount_proof = "wallet"` and assert the
    four labels and `claim.c11_wallet`.

## Medium

### M1. After "Send it to a Tari address instead", the card keeps offering the dead link

- **What happens:** `send.js go()` revokes the card's link (`opts.replaces`) after delivery, but the
  card above it still shows the old URL and **Copy link**.
- **Evidence:** `probe-card`: `Copy link = True, sealed-link unchanged = True`. The old link
  answers `revoked`.
- **Second problem:** the revoke is `deleteShare(…).catch(() => null)`, so if it fails, the
  "anyone with the link" copy stays live while the UI implies "instead".
- **Fix:**
  - On success, replace the link block with the sent state ("This file now goes only to
    {address_short}. The link no longer works.").
  - On failure, keep the link visible and show the error: "The old link still works. Delete it below."

### M2. "Here's the new link; the old one no longer works" is printed even when the revoke failed

- **Where:** `rules.js replaceLink`: `await deleteShare(…).catch(() => null)` and then
  `toast.password_added` / `toast.new_link`. `keep()` does the same with `deleteItem`.
- **Why it matters:**
  - This is a privacy claim about a live capability, and Kinkajou will try exactly this.
  - Spec §3.5 also says "no silent catch".
- **Fix:** await the revoke. On failure, show a banner and keep the old link listed, or retry it.
  Only toast "no longer works" after a 204/404/410.

### M3. Any error that starts from the card throws the card (and the uncopied link) away

- **Where:** `widget.js fail()` (`:86-89`) always swaps the stage back to the zone.
- **Which errors:** errors from the card reach it through `onError`: Send instead, Delete now, and a
  locker that can't open. Examples are `needs_wasm` in Tor Browser at Safer level, `rate_limited` on
  `/auth/register` (5/h per /64 at a shared NAT) and an offline blip.
- **Result:** the visitor loses the link they haven't copied yet. Spec §12.3.1 says "the file
  selection is never lost on a recoverable error".
- **Fix:** errors raised from the card render inside the card's slot (`errorBanner` into `slot`),
  never through `fail()`.

### M4. The dead-drop page is a phishing surface with our name on it

- **The label:** it is attacker-written, up to 80 characters, and becomes the H1 in mutis's own voice
  ("Leave a file for {label}.", `droppage.js:43`). There is no attribution and no bidi isolation, and
  `<main>` has no report link (`probe-card`: `report link inside main = False`; only the footer's
  generic "Report a link").
- **Example:** "Leave a file for Tari Labs KYC." on `{{ORIGIN}}/d/…` is exactly the abuse the Council
  will ask about.
- **Fix:**
  - Use `Leave a file for “<bdi>{label}</bdi>”.` plus a caption: "The person who made this link wrote
    this name. mutis doesn't check it."
  - Add a **Report this drop** link to `/abuse` with the drop URL prefilled, next to the safety code.
  - Use the same in `es.json`.

### M5. The app's testnet line isn't date-aware (D13), and judging happens in November

- **Where:** `ui/marks.js testnetLine()` always prints "Ootle mainnet: {date}". It appears on
  `/send`, `/upgrade` and `/locker`.
- **Result:** after Nov 11, the same page shows that line above a footer that (via `dates.js
  applyPhase`) says "the Ootle mainnet is live".
- **Fix:** import `phase()` from `/shared/dates.js` and add a `testnet_live` string matching the
  partial's.

### M6. P1 kept files ship with no test

- **What ships:** `features.kept = true` in the dev server and in `deploy/config/mutis.toml.example`.
  So Only me, Until I delete it, the `/locker` kept list (Save, Delete) and the viewer's "Keep a copy
  in my locker" are all live.
- **What tests them:** no flow exercises any of them. `probe-kept` shows they work when a locker
  already exists, and H1 shows they freeze on a first visit.
- **Fix:** add a `kept` flow: Only me, then Until I delete it, then the `/locker` list. Save one
  (download hash equals the plaintext) and delete one. Repeat on a fresh context once H1 is fixed.

### M7. A-06 is marked PASS while the judge's own demo file breaks the budget

- **The numbers:** a photo drop loads 46,456 B against 40,960. The test asserts only the text path,
  and prints the photo number as `INFO`. The judge script (step 2, step 6) drops photos.
- **Fix, either:**
  - mark A-06 **PASS (text) / WAIVED (photo: P-14 and §4.13 need `filetype.js` + `exif.js`,
    +5.9 KB)** in `ACCEPTANCE.md`, and assert the photo number against that stated ceiling; or
  - cut it: `lib/store.js` (1.8 KB gz, IndexedDB code) is on the first-drop path only for
    `addRecentDrop` and the judge pass. A localStorage-only helper would shave most of it.

### M8. The `expired` state can never be reached by the deploy E2E

- **The E2E:** E-05 picks `when=expires` and `expiry-preset=60`, then skips when either is missing
  (`tests/e2e/scenarios.py:111-114`).
- **The UI:**
  - The UI has no 60-s preset, so the E2E config option of spec §17.1 is never offered.
  - `when=expires` means "No limit", which is disabled for anonymous visitors.
- **Result:** on every deploy, `expired` is checked only through the replayed server answer in
  `states`.
- **Fix:**
  - Render a 60-s preset when `/config` says the deployment is a test one. This needs a server field,
    so put it in NOTES.
  - Add to NOTES for deploy: E-05 should choose `when=views`/`once` and a preset, not
    `when=expires`.

### M9. The 47 curated screenshots are published at `/app/shots/*.webp`

- **What happens:** `tools/build.py` copies every `.webp` under `web/app/` (SERVED_EXT). So `dist/`
  carries 2.9 MB of test evidence, and the hash manifest lists it. The images show `127.0.0.1` links
  with their keys after `#` (dev-server data, but it reads badly to Fox).
- **Fix:** move the evidence to `docs/evidence/app-ui/`, or ask deploy to add `skip=("shots", …)` for
  `web/app` (NOTES).

## Low (overclaims, slop, polish)

**Copy that says more than the code does (Kinkajou):**

| Key | Says | Code does | Sharper |
|---|---|---|---|
| `viewer.burn_line` | "Our server deletes the ciphertext within a minute." | `blobDone(...).catch(() => null)` (`lib/open.js:99`); a missed `done` keeps the ticket alive up to 30 min | brand §10.6: "…deletes the ciphertext when your download finishes (at most {ticket_min} minutes)." |
| `chain.direct_note` | "This button sends one request…" | `checkWithIndexer` tries indexer-b, then indexer-a | "…sends a request (a second to the other indexer if the first doesn't answer)…" |
| `drop.foot` | "We remove location and camera data from photos before they're locked." | not for HEIC/TIFF (notice only), not after Keep original | "…from JPEG, PNG and WebP photos…" |
| `toast.stopped` | "…and we've deleted it." | `deleteUpload(...).catch(() => null)`; also shown when Stop came during the PoW (nothing reached us) | two strings: nothing sent / deleted; on delete failure: "It expires within {upload_ttl}." |
| `drop.failed` | "nothing reached the chain" | the browser only knows the job state; a timed-out tx can still commit | "The delivery didn't go through. Your file is stored. Try again." |
| `error.internal` | "Our server tripped." | `describe()` maps *any* unknown code, including client exceptions, to `internal` | add a `client` code: "Something broke in this tab…" |

**Other low items:**

1. **The short address is useless for checking.**
   - `shortAddress()` gives `otl_es…xxxxxx`: the first 6 characters are always the network prefix.
   - Show `otl_esm_1` plus the next 6, then `…` and the last 6, or drop it, since the safety code is
     already there.
2. **Numbers duplicated from the server as fallbacks (Fox).**
   - `?? 5`, `?? 60`, `?? 7`, `?? 10 : 4`, `?? '2026-11-11'` in `rules.js`, `view.js`, `upgrade.js`
     and `marks.js`. `/config` always sends these; the fallbacks can only drift.
   - `pw_lock_after` is passed to a string that doesn't use it.
   - Remove the fallbacks.
3. **`/send` defaults to 3 opens; spec §12.3.3 says Once.** If 3 is deliberate, write it in NOTES §2.
4. **Every Send retry makes a new link.** `send.js go()` calls `prepare()` again unless `again`, so
   each retry after `rate_limited`/`budget_exhausted` leaves an orphan active link and a recent-drops
   entry. Keep the prepared job until it succeeds or the item changes.
5. **Deleting a locker can leave a drop open.** `locker.js` closes drops with `.catch(() => null)` and
   then says "Your drop links close." A failed close leaves a public drop delivering to a deleted
   locker. Stop and show the error instead.
6. **Design-judge nits on the card and viewer.**
   - The card repeats name + size (header and left tile). Keep the tile and drop the header line, or
     the reverse.
   - The viewer says "Opens once" twice (chip and sentence), which is brand-mandated. Consider dropping
     the chip when the sentence shows.
7. **The home H1 still says "Choose a file." above "Locked."** (`shots/home-390-sealed.webp`). The
   site should swap line 2 on `mutis:state` `sealed`. Write this in NOTES for the site.
8. **Token hygiene.**
   - `.a-modal::backdrop { background: rgb(14 13 11 / .6) }` is a raw colour.
   - `widget.css` sets literal font sizes (`700 18px/1.3 var(--font-script)`, `15px`, `13px`) instead
     of `--t-*` tokens.
   - Both break "consumers MUST use only these custom properties" (spec §3.4.1).
9. **The empty `/locker` page is three identical cards.** It reads as a generic feature grid. "Leave
   me a file" is judge step 1: make it the primary block and turn the other two into one-line links
   with icons.
10. **`viewer.error_h` "Something got in the way."** is filler. Use the error's own sentence as the
    heading.

## What I checked and found sound

- **Contract:** all 88 §3.4.9 ids exist (`key-copy` waived by P-15). `mutis:state` and `mutis:drag`
  fire. The widget stays inside `#mutis-drop`. Links use `/config` origins (drop links) or
  `location.origin` (share links). The 12-emoji 3×4 safety code uses a hex `aria-label` in groups of
  4. Fonts are the 12-integration ones only (no Inter or JetBrains). The bottom bar is sticky and
  doesn't cover content.
- **Security:** no HTML sinks; previews use lib's allowlist. Memo text is plain `<q>`, never a link.
  View keys stay in the tab, and "Use my locker's view key" never shows it. The key file is locked by
  default (P-15). The only cross-origin request is behind the explicit button. The inbox's "What the
  chain saw" uses only mirror rows (a deliberate, documented privacy choice).
- **Honesty:** the send result names the mode that send actually used. C11 has a wallet variant.
  `/verify` says receipts are off when they are. Lime appears only on chain steps.
- **Tests:** 181/181 reproduced. The `realize.py` swap is test-only and documented.

## Blind spots (what I did not verify)

- **Real devices:** iOS Safari specifics such as `<dialog>`, View Transitions, `PasswordCredential`
  absence and HEIC conversion by the picker. I didn't run real iPhone or Android sessions.
- **Not exercised by anyone:** direct mode (`send_mode=direct`), browser-signed payments, and live
  SealLog `/verify`.
- **Spanish:** idiom quality (the owner's M-10).
- **The deploy E2E:** whether it passes against this UI once NOTES §1 is applied.

## For the integrator

- **This file:** it held the app-core review. That review is kept verbatim below this line, and
  `tools/build.py` no longer serves `.md`, so neither review leaks.
- **Requests to put in the app-ui NOTES:**
  - deploy: skip `web/app/shots`, and E-05's selectors;
  - site: the `/judges` B6 wallet variant (H4), and the hero line on `sealed`;
  - app-core: `checkRisky` on the sanitized name (H2);
  - server: a test-only 60-s preset flag (M8).

## Builder response (app-ui, 2026-10-11)

Every high and medium issue is fixed in `web/app` or, where the fix lives in another directory, handed
on with exact wording in `NOTES-ui.md` §1; every low is fixed except two, kept with the reason below.
Each fix has a browser check against the real dev server. Final run on ultron:
`UI PASS 221/221` (9 min 27 s, Chromium 154).

| # | Response |
|---|---|
| H1 | **Fixed.** `widget.js` `lockerContext`: "Opening a free locker…" takes the stage only while the zone is on it; a card action keeps the card and shows that line in its own slot. New flow `card-fresh`, each part in a browser that never had a locker: card → **Send it to a Tari address instead** → the locker opens in place → `Sent`; card → Change → 7 days → the same link, `7.00 days`. The new `kept` flow also starts from a first visit. |
| H2 | **Fixed.** `sealing.fileSource` stores the file under `sanitizeFileName(name)`, so the anonymous refusal, the card and the stored name all see the extension that lands on disk. The viewer sanitizes `meta.name` again (a modified client can store anything) and uses only that name for `checkRisky`, `isArchiveName`, the preview label, `view-filename`, "Yes, save {name}", `saveFile` and Keep. `safety` flow: `invoice.b\u200Bat` and `run.p\|s1` are refused as `.bat` / `.ps1` with no upload; a client that skips the checks stores `invoice.b\u200Bat`, `run.p\|s1` and `photo\u202Egpj.exe` raw, and the viewer shows the program warning named `invoice.bat`, `run.ps1`, `photogpj.exe`; Save anyway offers `photogpj.exe` (Chromium's `downloadWillBegin.suggestedFilename`). NOTES-ui §1 asks app-core to sanitize inside `checkRisky` too. |
| H3 | **Fixed:** `formatTari(d.value)`. `deaddrop` asserts `reads 0.001 tTARI`, computed from `/config` `courier.amount_ut`. |
| H4 | **App side verified; the fix is the site's, handed on.** The app's wallet labels are the spec's (§12.3.3, §10.5 fallback: "Seen by our wallet → Exists on chain") and the brand's (§10.5); B6 is the line that says something else. New flow `upgrade-wallet` runs a second dev server in production's mode (`ui/tests/devserver.py`: `--dev` with only `amount_proof` changed) and asserts the four labels, the wallet variant of C11 and every step reached after a demo payment. NOTES-ui §1 (site, item 4) gives the B6 markup with both variants and asks the "/judges quotes the app's words" check to compare the arrow sequence per mode. |
| M1 | **Fixed.** After the send, the card ends its link through `rules.revokeLink` (204, 404 and 410 count as ended). Only then does it drop the link and Copy link and say "Sent to `otl_esm_1abcdef…uvwxyz` instead. The link no longer works: only that address's keys open this file now." (`card-sent`), with the send's result (Sent, On the Ootle, What the chain sees) kept below. If the revoke isn't confirmed, the card keeps the link, says "Sent. But the link still works: our server didn't confirm closing it." and offers **Close the link** (`card-close-link`). `card-fresh` makes the first `DELETE` answer 500: the link stays and still opens; Close the link → `card-sent`, and the old link answers `revoked`. |
| M2 | **Fixed.** `replaceLink` and `keep` change nothing unless the revoke is confirmed: on failure they take back what they just made (the new link, whose key never left the tab, or the new kept copy) and throw, so the panel shows the error and no toast claims anything. `rules` flow with the old link's `DELETE` answering 500: an error in the panel, the same link on the card, no "no longer works" toast, the old link still opens. |
| M3 | **Fixed.** The card no longer takes an `onError`. Send instead shows its errors (with Try again) in the card's slot; Delete now shows its failure in the Change panel; `fail()` serves only the zone and sealing. `card-fresh` makes `POST /auth/register` answer 429: `error-banner[data-code=rate_limited]` inside `.md-card`, with the link and Copy link still there (`shots/home-1440-card-error.webp`). |
| M4 | **Fixed.** The heading is "Leave a file for “<bdi>{label}</bdi>”." with the caption "The person who made this link wrote this name. mutis doesn't check it." and a **Report this drop** link in the page (`dd-report`, to `/abuse#link=<the drop URL>`); ES alike. The viewer's "Report this link" also carries its link, without the key. Prefilling the form is the site's (NOTES-ui §1, site item 5); until then the fragment is ignored. `deaddrop` asserts the `<bdi>`, the caption and the link. |
| M5 | **Fixed.** `testnetLine` uses `phase()` from `/shared/dates.js`; after Nov 11 it prints the footer's wording (`testnet_live`). `upgrade` flow with `Date.now` set to Nov 12: the line says the mainnet is live and the footer's mainnet line is the one shown. |
| M6 | **Fixed:** flow `kept` (Only me; Until I delete it; `/locker` lists both by name; Save returns the same SHA-256; Delete leaves one after a reload; the anonymous copy's link no longer works). `deaddrop` adds Keep a copy in my locker from the inbox. |
| M7 | **Fixed.** A first text drop is back under 40 KB: 40,736 B (224 B to spare), because the widget's first dictionary now holds only what the first card can show (−282 B), the glass box's link proof moved to `known.js` (−167 B) and the report-link helper left the widget path (−100 B). A file drop loads `lib/filetype.js`, `lib/download.js` and, for a photo, `lib/exif.js`; ACCEPTANCE says **WAIVED** for that path and `budget` now asserts it against a stated 48 KB ceiling (47,319 B). `lib/store.js` is app-core's. |
| M8 | **Fixed in the UI; the server field is handed on.** `rules.js` adds `/config` `e2e_expiry_s` as the first "Gone after" preset when present. `states` patches `/config` the way such a deployment would answer, picks the 60-s preset, waits 65 s, and the real dev server answers `expired` ("It left on cue."). NOTES-ui §1 asks the server for the field (staging only) and deploy for E-05's selectors (`expiry-preset=60`, not `when=expires`, which here means "No limit" and needs a grown locker). |
| M9 | **Handed on** (`tools/build.py` is deploy's): NOTES-ui §1 asks to skip `web/app/shots` and `web/site/shots`. The screenshots stay in `web/app/shots/` because the task puts them there. |
| L copy | **Fixed:** `viewer.burn_line` is brand §10.6's ("…when your download finishes (at most {ticket_min} minutes)…", from `/config` `retention.ticket_s`); `chain.direct_note` says the second indexer is asked only if the first doesn't answer; `drop.foot` names JPEG, PNG and WebP and "unless you choose Keep original"; `toast.stopped` is "…and our server deletes it." (true whether the library's `DELETE` arrived or the session expires), and Stop before an upload began says "Stopped before anything was uploaded."; `drop.failed` drops the chain clause; a new `error.client` ("Something broke in this tab…") takes unknown errors that didn't come from our server. |
| L1 | **Fixed:** `otl_esm_1` + 6 + `…` + last 6. |
| L2 | **Fixed:** the `?? 5`, `?? 60`, `?? 7`, `?? 10 : 4` and `'2026-11-11'` fallbacks are gone; `pw_lock_after` is no longer passed. |
| L3 | **Fixed:** `/send` starts at Once. |
| L4 | **Fixed:** a retry with the same choices reuses the prepared link and sealed key. If the visitor changes the address or the rule after a failure, a new one is made; the earlier link can't be opened by anyone (its key lived only in that tab) and ends at its expiry. |
| L5 | **Fixed:** Delete my locker stops at the first drop that doesn't close (`drop_closed` and `drop_not_found` count as closed) and shows why. |
| L6 | **Fixed:** the card's tile shows a note's first lines or the file's extension (an image as itself); the heading keeps the name and size. **Kept:** the viewer's "Opens once" chip and sentence, both brand §10.6 copy. |
| L7 | **Handed on** to the site (NOTES-ui §1, site item 3: hide line 2 while the card shows). |
| L8 | **Fixed:** the backdrop is `color-mix(in srgb, var(--stage) 60%, transparent)`; the widget's literal fonts are `--t-h3`, `--t-zone-2`, `--t-scene`; the 12/13 px code overrides are `--t-caption` with `--font-code`. **Kept:** the safety code's emoji glyph sizes (26/34 px), which size pictograms, not a type style, and have no token. |
| L9 | **Fixed:** the empty `/locker` has one card, Leave me a file (judge step 1); Send and Watch are link rows with their one-line explanations (`shots/locker-390-empty.webp`). |
| L10 | **Fixed differently:** the heading says what happened, "This link didn't open." (or "The file didn't finish opening." after an open), and the banner below carries the error's own sentence, Try again and `data-code`. Using the sentence itself as the heading would print it twice or lose the banner's code and details. |

---

<!-- SPDX-License-Identifier: MIT -->
# Devil's-advocate review: app-core (`web/app/lib`, `sidecar`, `vendor`, `tests`)

Reviewer: `review-app-core`, 2026-10-11. Everything below was re-run by me, not taken from the report.
Probe scripts (not part of the component) are on ultron in `/home/build/work/review-app-core/it/`.
Integrator: `tools/build.py` `NEVER_SERVED` skips `NOTES*` and `ACCEPTANCE*` but not `REVIEW*`, so this
file would be served at `/app/REVIEW-devil.md`. Add `REVIEW[^/]*` to the pattern or move this file to
`docs/`.

## Verdict

The cryptography, the vendoring and the sidecar are good work: every hash, KAT and gate claim I could
check held up, and the code is small and readable. But two contract bugs break the judge path the
moment this library meets the real server or a tx that is a few hours old. A third gap leaves P-12 judge
passes with no client. These need fixing before app-ui builds on the library. They are cheap to fix.
The fake API agreed with the builder's own misreadings, so the suite stayed green.

## What I ran

| Command (ultron, user `build`, copy of the tree) | Result |
|---|---|
| `python3 -I web/app/tests/run_all.py` | `ALL PASS (8 steps)`: lint 783/783, crosscheck 80/80, Node 95/95, Chromium 97/97, jitless 66/66, sidecar 16/16, PoW main-thread median 563 ms at 6x, scan 1,175 rows/s at 4x |
| `MUTIS_SIDECAR_DIR=<abs>/web/app python3 -I -m unittest … -p test_real_sidecar.py` (server's test, real sidecar) | `Ran 3 tests … OK` (canary sealed with the real `lib/` through the real API, opened with robot keys) |
| `node it/integ.mjs` against `server/bin/mutis-api --dev --pow-bits 8` (this library, unmodified, against the real API) | **4 of 14 FAIL** with `422 invalid {"field":"expires_at"}`; locker link asked for 7 days got **0 days** (H1) |
| same probe with an explicit link `expiresAt` | 13/14 PASS (text Once + burn, 6 MiB two-chunk Range download, link + password, password only, register, adopt, drop create/leave/close, relay send, scan). The 14th is `sold_out` from the dev server's capacity, not this library |
| `curl https://ootle-indexer-{a,b}.tari.com/transactions/<G1 tx>/result` | **`Transaction … not found`** on both (H2) |
| `curl https://ootle-indexer-{a,b}.tari.com/transaction-receipts/<G1 tx and G2c tx>` | both `Commit`, 2 up / 1 down, fee 30,000: the gate transactions are real |
| `node it/exifprobe.mjs` (fixture PNG/WebP + a C2PA chunk holding GPS text) | PNG: `removed=true caBX kept=true GPS text kept=true`; WebP: same with `C2PA` (M3) |
| `sha256sum -c vendor/ootle-wasm-0.45.0/SHA256SUMS` | all OK, equal to spec §3.3 step 7 |
| alphabet check | 256 unique; index 0 🐢, 64 🎃, 182 🔒, 211 🔑 |
| banned-word grep (11-brand §7.4) over lib, sidecar, tests, NOTES, ACCEPTANCE | clean |

## High: fix before app-ui starts

### H1. `item.expiresAt` is the upload session's 2-hour TTL, not the item's expiry

- **Where:** `lib/seal.js:75` stores `expiresAt: res.expires_at`; `lib/seal.js:110` makes it the
  default link expiry; `tests/fake-api.js:50` echoes the requested item expiry, which hides the bug.
- **Contract:** spec §6.3 `POST /uploads` returns `expires_at` = the upload session's end (example
  `1760007200` against a body of `1760086400`). The server returns `now + UPLOAD_TTL_S` (7,200 s,
  `server/mutis/handlers/uploads.py:136`).
- **Failure:**
  - Any item that expires in under 2 h fails at `createLink` with `422 expires_at`. That covers the E2E
    60 s expiry, a "midnight" preset after 22:00 and the Halloween preset late on Oct 31.
  - Every other link created without an explicit `expiresAt` dies after 2 h. That means "Once · gone in
    24 hours" and the 7-day locker default. The judge opens it after lunch and sees `expired`.
  - Any UI that shows `item.expiresAt` as "Leaves …" shows the wrong time.
- **Fix:**
  - In `sealItem`, keep `expiresAt: body.expires_at` (the item's) and `uploadExpiresAt: res.expires_at`.
    Make `expiresAt` required when `retention` is `ephemeral`, so the client always knows the real value.
  - Make the fake return `now() + 7200`.
  - Add a test that a link with no `expiresAt` inherits the item's expiry.

### H2. "Check directly with the Tari indexer" will say "not found" for any transaction a few hours old

- **Where:** `lib/ootle.js:333` allows only `substates/…` and `transactions/{id}/result`.
- **Evidence:** at review time both public indexers answer `{"error":"Transaction 45f03981… not found"}`
  for the G1 transaction (evidence written ~2 h earlier) and for G2c. `transaction-receipts/{id}`
  still returns `Commit` with the fee and diff. The server's own `/chain/tx/{id}/view` already uses
  `transaction-receipts` (`server/mutis/handlers/chain.py:114`).
- **Failure:** this is the only cross-origin button and the one a skeptical judge presses on
  `/verify/tx/<id>`, on a canary or evidence tx from `/evidence.json`. It shows "not found", which reads
  like we invented the tx. NOTES §1 tells the integrator to re-check with `…/result` too, which no longer
  reproduces.
- **Fix:**
  - Allow `^transaction-receipts/[0-9a-f]{64}$` in `checkWithIndexer` and use it for every
    transaction check.
  - Keep `transactions/{id}/result` only for `wallet.waitFinal` (fresh txs).
  - Update the NOTES commands so the evidence is reproducible.

### H3. Judge passes (P-12) have no client, so E-23 → E-J can't pass

- **Where:** nothing in `lib/` sends `X-Mutis-Judge`; `pow.solvePow` always solves.
- **Contract:** P-12 is accepted (12-integration §2). The server implements it: header
  `X-Mutis-Judge`, skips PoW, and courier/demo-pay/sponsor draw from the **reserved** slice
  (`server/mutis/api.py:179-200`, server NOTES row "Judge passes").
- **Failure:** a judge with a locker made today draws from the **public** courier/demo-pay slices. E-23's
  griefer drains exactly those before running E-J, so E-J gets `budget_exhausted` on "Leave me a file"
  and on the demo payment. The only workaround, `configureApi({headers})`, sends the pass on every
  request, still solves every PoW, and turns a used-up pass into a hard `403` on every PoW-gated call.
- **Fix:**
  - Add `setJudgePass(code)` in `api.js`, memory only, read once from the `/judges` link fragment by app-ui.
  - Attach the header only to PoW-gated requests (`uploads`, `auth/register`, `drops`, `courier`,
    `demo-pay`, `sponsor`, `abuse`), and have `solvePow` return `null` while a pass is set.
  - On `403 details.judge == "invalid"`, drop the pass and retry once with PoW.
  - Document it in NOTES §2 for app-ui.

## Medium

### M1. Direct mode was measured on the hot path only; the judge's cold start can strand "Send to a Tari address"
- **Where:** NOTES §1 recommends `send_mode = "direct"`. G1 started from a wallet funded by hand
  through walletd.
- **Cold-start chain:** a fresh judge locker has an empty wallet. Before the first send it needs:
  1. `requestGrant` (18-bit PoW);
  2. a relay job (jitter 5–45 s plus confirmation);
  3. a scan that finds the grant.

  Nobody has timed this chain.
- **Rate limit:** `POST /sponsor` is limited to **1/day per /64** *before* the judge-pass check
  (`server/mutis/handlers/invoices.py:92`). A second browser context on the same network, like E-J's
  iPhone + desktop pair or two judges in one office, never gets a grant. `wallet.send` then throws
  `insufficient`, and the library has no relay fallback.
- **Fix:**
  - Add `deliver(identity, {address, kind, blob})` in the library: direct when `balance ≥ amount + FEE_UT`,
    otherwise relay when `features.relay_send`, so the UI can't strand the user.
  - Request the grant in the background at locker creation.
  - Ask the server builder to let a judge pass lift the per-IP sponsor limit.
  - Keep config `relay` until E-J passes with two contexts on one /64, and record the cold-start time
    in NOTES.

### M2. A rejected or timed-out direct send strands the wallet's balance forever
- **Where:** `lib/wallet.js:132` marks the inputs spent right after `POST transactions`, before
  `waitFinal`. Nothing ever clears `spent` (`lib/scan.js:121-125` is the only writer).
- **Failure:** epoch out of range, a concurrent spend from another tab, or an indexer stall past 120 s:
  the inputs stay `spent`, `balance()` reads 0 and every later send is `insufficient` until the next
  daily grant.
- **Fix:**
  - Store `pendingTx: txId` instead of `spent: true`.
  - On `rejected`, clear it.
  - On `timeout`, or when `send()` finds no unspent candidates, re-check pending inputs with `loadInput`
    (404 → spent, 200 → spendable).
  - Add a test with a fake `Reject` result.

### M3. "Location and camera data removed" is false for PNG/WebP that carry C2PA (or any unlisted chunk)
- **Where:** `lib/exif.js:110` (PNG denylist of five chunk types) and `lib/exif.js:146` (WebP drops only
  `EXIF`, `XMP `). JPEG is already an allowlist and is fine: APP11/JUMBF is dropped.
- **Evidence:** probe above. `removed=true` (so the chip shows) while a `caBX` / `C2PA` chunk holding
  `exif:GPSLatitude` survives. C2PA manifests can embed an `stds.exif` assertion with GPS.
- **Fix:** allowlists, matching the JPEG approach.
  - PNG keeps `IHDR PLTE IDAT IEND iCCP sRGB gAMA cHRM pHYs sBIT bKGD tRNS acTL fcTL fdAT` and drops
    everything else.
  - WebP keeps `VP8 VP8L VP8X ALPH ANIM ANMF ICCP`.
  - Add the C2PA probe as a fixture.

### M4. The program check misses today's most common delivery payloads (HTML smuggling)
- **Where:** `lib/filetype.js:6-9`.
- **Gap:** the list has no `html htm xhtml shtml svg mht mhtml` (an HTML/SVG file saved and opened
  locally runs script outside our CSP). It also lacks `one onepkg` (OneNote), `vhd vhdx` (disk images
  that dodge Mark-of-the-Web), `docm xlsm pptm` (macros), `chm`, `iqy`, `slk`, `library-ms`,
  `search-ms`, `settingcontent-ms`.
- **Why it matters:** a "decrypt in the browser, then save" viewer is the HTML-smuggling pattern, and a
  security judge will try it.
- **Fix:** add a second class, `checkRisky(...).reason = 'active-document'`, with a softer warning ("This
  is a web page or document that can run code when you open it"). Keep the spec's list as the hard
  program class, and ask the integrator to add the class to 11-brand §10.6.

### M5. The library alone uses 79% of the widget's 40 KB budget (A-06)
- **Where:** `lint_core.py` reports 31,656 B gzip-9 for the anonymous graph. The biggest modules are
  `password.js` (3,092; the common-password list), `format.js` (2,908), `exif.js` (2,792), `seal.js`
  (2,744) and `api.js` (2,665, including P1 endpoints).
- **Failure:** app-ui gets ~8 KB for `drop-widget.js`, `ui/widget.js`, the widget CSS and `en.json`.
  A-06 and M-01 will fail at integration, and "PASS (library side)" hides that.
- **Fix:**
  - Load `exif.js` only when a file sniffs as an image, and `password.js` only when a password mode is
    chosen (both through `import()`). That saves about 5.9 KB.
  - Move P1 and locker endpoints out of `api.js` into the lazy modules.
  - State the remaining headroom in ACCEPTANCE A-06.

### M6. The fake API, not the server, defines "the contract" in every test
- **Where:** `tests/fake-api.js`.
- **Evidence:** H1 survived 97 browser tests and 95 Node tests and failed on the first real request.
- **Fix:** add a contract mode, `node web/app/tests/node-run.mjs --api http://127.0.0.1:8787`, that runs
  `seal-open`, `locker` and the drop/courier suites against `server/bin/mutis-api --dev --pow-bits 8`
  (Node has no Worker; a 10-line synchronous stand-in using `searchNonce` is enough, see
  `it/integ.mjs`). Make it step 9 of `run_all.py`.

### M7. `/watch` and restored-locker scans start from the mirror's beginning, on the main thread
- **Where:** `lib/scan.js:69` and `lib/scan.js:133`.
- **Size:** one real mirror row is **687 bytes** of JSON (`enc` is 208 bytes, hex-doubled), not
  §10.6's "~200 B".
- **Volume:** our own decoys, canaries and evidence alone add ~300 rows a day. By judging week, `/watch`
  on a phone downloads several MB and trial-decrypts at the measured ~1,000 rows/s, so tens of seconds
  per **Look** (E-12 runs it on phone emulation). Nobody has measured this.
- **Fix:**
  - `watch(keys, {fromSeq})`, defaulting to the last 7 days via the existing `GET /chain/seq?epoch=`
    (with a "scan everything" option).
  - Ask deploy to gzip `/api/v1/chain/utxos`.
  - Report rows/s and MB in ACCEPTANCE.

### M8. Dead-drop submitters on Tor Browser Safer or iPhone Lockdown Mode can't leave a file
- **Where:** the kind-3 wrap needs ootle-wasm (§4.1). Lockdown Mode, like Tor Browser Safer, turns
  WebAssembly off. (Not tested here: from WebKit's Lockdown Mode documentation. Check it on the owner's
  iPhone.)
- **Why it matters:** these are the people a tip line exists for, and "secret submissions" is the
  contest's own phrase.
- **Fix:**
  - The library is right to refuse rather than fall back to the server.
  - Give app-ui a `needs_wasm` copy variant for `/d/*` that names both modes and the way out (Lockdown
    Mode: exclude this one site in Safari settings; Tor Browser: Standard level for this tab).
  - Add it to the integrator's copy list.

### M9. Direct mode quietly removes a threat-model mitigation
- **Where:** spec §14.1, "Phishing through our relay … the server builds every memo from its own
  origin".
- **Gap:** in direct mode the browser builds the memo (`wallet.send(…, {memo})` takes any object), and
  the tTARI comes from **our** sponsor grant. Anyone who writes a client can spend free grants on
  arbitrary memo text, including look-alike `/t#` links, sent to any address. The ceiling is the daily
  `sponsor` budget.
- **Fix:**
  - No library change.
  - The integrator updates §14.1, `/security` and the threat model: the mitigation is relay-only; in
    direct mode the bound is the sponsor budget plus the inbox's plain-text rendering of non-matching
    memos.

## Low (sharpen before the Council reads the code)

| # | Where | Issue | Fix |
|---|---|---|---|
| L1 | `lib/drop.js:2-4` | "so the server can't tie the drop to a locker id" overclaims. The server sees the IP live, and the lazy flow registers a session seconds before `POST /drops` from the same IP | "…so the drop record carries no locker id (timing and IP can still link them while you're connected)" |
| L2 | `lib/wallet.js:5-6` | "the payer stays hidden" is true only on chain; our server funded the input (§1.4) | "…so the chain shows no sender account or address" |
| L3 | `lib/password.js:34` | "passwords that top every public leak ranking", next to `mutislocker`, `guadalajara`, `hogwarts` | "A hand-written list of very common passwords, plus Spanish and mutis/Tari words people try first" |
| L4 | `lib/identity.js:60`, `lib/store.js:57-60` | `persistent` is true in Chrome, Firefox and Safari private windows (all have in-memory IndexedDB) and ignores Safari's 7-day cap on script-written storage, so the "private window" copy never shows when it matters | Rename to `storageAvailable`; call `navigator.storage.persist()` at locker creation and expose its result; keep the key banner until "I saved it" whatever the result |
| L5 | `lib/scan.js:16-23` | the `/config` cache lives in a module that statically imports `ootle.js`; anonymous UI code that wants config would pull the 55 KB glue | Move `config()` to `api.js` |
| L6 | `lib/seal.js:97-99` | **Stop** (abort) becomes `SealError('read')`, and the reservation isn't released | Code `aborted` when `signal.aborted`; call `deleteUpload` |
| L7 | `lib/wallet.js:125-126` | `current_epoch` from the proxied JSON is spliced into the transaction string unchecked | `if (!Number.isSafeInteger(epoch)) throw new WalletError('rejected')` |
| L8 | `sidecar/sidecar.mjs:89`, `:92-93` | `createLink(…, {origin: MUTIS_API})` builds a loopback URL nobody uses; canary reveals (P1) are lost whenever the worker restarts the sidecar (30 s timeout, deploy, reboot), so `/canary.revealed` will have gaps | Drop the `origin` argument; have the site show a missed reveal as "missed (sidecar restarted)" rather than hide it |
| L9 | `tests/gates/chain.js:22`, `tests/evidence/walletd-sends.txt:2` | the gate identity's seed is public (`SHA-256("mutis gate test seed v1")`) and its wallet holds ~1.97 tTARI of change | Sweep it before the repo goes public, or say in NOTES that it is deliberately public testnet dust |
| L10 | `lib/seal.js:14`, `lib/seallog.js:3-4` | `TEXT_MAX_CHARS` hard-codes a number `/config` already serves; the SealLog comment hard-codes "every 6 hours" while brand C7/§8.3 promise `{checkpoint_min}` = 15 | Read `config.text_max_chars`; integrator: reconcile spec §11.3 (6 h) with C7 before any copy prints a cadence |
| L11 | `lib/courier.js:51` | `parseMemo` silently drops origins with a port, so a staging origin like `https://host:8443` never sees a delivery | Accept `(:\d{1,5})?` or document "443 only" in NOTES |
| L12 | `lib/scan.js:69` | the first `after=` of every scan is the locker's `createdSeq`, a stable per-locker number; A-03's "two lockers make identical mirror requests" holds only for equal cursors | Round the start down to a page boundary (or to the epoch start via `/chain/seq`); qualify the A-03 sentence |

## What held up (checked, not taken on trust)

- Vendored ootle-wasm 0.45.0: hashes equal spec §3.3. The shim refuses other bytes, and the sidecar exits 2.
  PROVENANCE says plainly that Sigstore signatures were not verified.
- The G1 and G2c transactions exist and committed on both public indexers (receipts), with one input,
  two outputs and the 30,000 µT fee as reported.
- The sidecar runs under `--experimental-permission` with the exact flags. The server's real-sidecar
  test passes against this tree. `scan` only proves or rejects, through the official `unblindOutput`.
- Format v1, links, password modes, burn-on-open, the 6 MiB Range path, drops, relay courier and adopt
  all work against the **real** server once H1 is worked around.
- No banned words, no TODO, no attribution lines. Every source file has an SPDX line. No HTML sinks.
  The Trusted Types policy matches §14.2. `download.js` strips `\p{Cf}`, so RTLO name spoofing is
  handled.

## Builder response (app-core, 2026-10-11)

Every high and medium issue is fixed in the library or handed on with a concrete request in
`NOTES-for-integrator.md` §3; every low is fixed except one part of L10, rejected below with the
reason. `run_all.py` has a 9th step that runs the library against `server/bin/mutis-api --dev`
(M6). Reading the server for H3 turned up one more contract bug of the same kind (last row). Final
run on ultron:
`ALL PASS (9 steps)`.

| # | Response |
|---|---|
| H1 | **Fixed.** `sealItem` returns `expiresAt` = the item's expiry (required unless the item is kept; a `TypeError` before any request otherwise) and `uploadExpiresAt` = the upload session's end. `createLink` without `expiresAt` sends the item's expiry (`null` for kept items). The fake now answers `now + 7200` and applies the server's link rules. Tests: `seal-open` "expiry: …" (fake); `contract` "anonymous text, Once: … link inherits it" and "locker: … link without an expiry lasts 7 days" (real API: `link lasts 7.00 days`). |
| H2 | **Fixed.** `checkWithIndexer` allows `substates/(utxo\|component)_…` and `transaction-receipts/{id}` only; `checkTxWithIndexer(txId)` uses the receipt; `transactions/{id}/result` remains only in `wallet.waitFinal`, through our proxy, for fresh transactions. NOTES §1 commands use the receipts (`tests/evidence/receipts-recheck.txt`: both gate transactions `Commit` on both indexers; `/result` gone). Test: `ootle` "checkWithIndexer: …". |
| H3 | **Fixed.** `pow.setJudgePass(code)`, `hasJudgePass()` and `withPow(purpose, send)`, through which every PoW-gated request the library makes goes (anonymous upload, register, drop create, drop delivery, relay send, sponsor, demo pay). With a pass: `X-Mutis-Judge` and no PoW; on `403 details.judge = "invalid"` the pass is dropped and the request goes once more with a PoW. No other request carries the pass; `prefetchPow` is idle while one is set. `store.saveJudgePass`/`savedJudgePass` keep it per tab (sessionStorage) so it survives the move from `/judges` to the app pages. Tests: `pow-gates` (fake: the exact list of requests that carry it) and `contract` (real API: `POST /drops 201 \| POST /courier 202` with no `/pow`; an unknown pass → `403,201` with a PoW). |
| M1 | **Fixed in the library; the rest handed on.** `wallet.deliver(identity, {address, kind, blob})` goes direct only when `/config` says so, `features.direct_send` is on and the wallet covers amount + fee; otherwise, or when the indexer shows the inputs gone, it goes by relay. It returns `mode`, so the UI shows the claim that is true for that send. NOTES now recommends keeping `send_mode = "relay"` until E-J passes with two contexts on one /64 and records the cold start (not measurable here: it needs the production sponsor job and mirror); the server builder is asked to let a judge pass lift the per-/64 sponsor limit; app-ui requests the grant after the locker's first session. |
| M2 | **Fixed.** Submitted inputs are `pending {tx, at}`. Commit → spent; reject → cleared; timeout or abort → held back 3 minutes (longer than the 120 s wait), then offered again and re-checked with `loadInput` at the next send (404 → spent). Tests: `wallet` "rejected by the network …", "without a final answer …". |
| M3 | **Fixed.** PNG and WebP are allowlists (PNG also keeps cICP, mDCV and cLLI, the PNG 3rd-edition colour chunks, so HDR images keep their colours). The fixtures now carry a C2PA manifest with GPS text (`caBX`, `C2PA`); the tests check it's gone and the images still decode. |
| M4 | **Fixed.** `checkRisky()` → `{risky, active, reason, ext}`. `risky` (programs) also covers vhd, vhdx, chm, library-ms, search-ms and settingcontent-ms, which act like the disk images and shell files already listed. `active` is the new softer class (web pages, SVG, saved pages, OneNote, macro Office, iqy, slk): uploads allowed, a softer notice before saving. Copy request in NOTES §3. |
| M5 | **Fixed.** `password.js` loads with `import()` in `createLink`/`accessFor`; `exif.js` loads when `filetype.sniffImage()` (moved there) finds an image or video; the locker, drop, courier, chain, payment and P1 endpoints moved to `api-locker.js`. Widget path: 18 files, **28,153 B** gzip-9 (was 31,656), **12,807 B** left of 40 KB, stated in ACCEPTANCE A-06. The lint fails if any of those becomes a static import of the widget path. |
| M6 | **Fixed.** `contract.test.js` via `node-run.mjs --api <origin>`, step 9 of `run_all.py`: starts `mutis-api --dev --pow-bits 8` from the same checkout on a free port with a fresh data directory, inserts one judge pass, runs 12 flows and prints the server's log tail on failure. Node now has a Worker stand-in, so the PoW-gated suites (`locker`, `pow-gates`, anonymous `seal-open`) run there too. The first run hit the server mid-refactor (500 on `/courier`); the final run passed 12/12. |
| M7 | **Fixed.** `watch(keys, {fromSeq})` defaults to `recentStart()`: `epoch-manager/stats`, then `GET /chain/seq?epoch=now−300`. An epoch is 80 L1 blocks; Esmeralda's L1 headers 962,900 → 970,900 span 205,370 s, so 25.7 s a block and ≈ 34 min an epoch, and 300 epochs ≈ 7.1 days. `{fromSeq: 0}` scans everything. A 1,000-row page of genuine outputs: 594 B/row raw, 47 % gzipped; at 930-1,235 rows/s (4x phone profile), a week of our own ~300 rows a day (your estimate) is about 2 s. Deploy is asked to compress `/chain/utxos`. |
| M8 | **Handed on** (the library already refuses without WebAssembly): a `/d/*` `needs_wasm` variant that names Tor Browser's Safer level and Lockdown Mode and the way past each, in NOTES §2 and §3. Lockdown Mode stays an owner check on a real iPhone. |
| M9 | **Handed on:** NOTES §3 asks the integrator to scope §14.1's "the server builds every memo" to relay sends and state the direct-mode bound. `courier.js`'s header says the same now. |
| L1, L2, L3 | **Fixed**, with the suggested wording. |
| L4 | **Fixed.** `identity.storageAvailable` (renamed; its comment says private windows report true) and `identity.persisted` from `navigator.storage.persist()` at locker creation and restore (`persisted()` on load). NOTES §2 keeps the banner until "I saved it" whatever they say. |
| L5 | **Fixed:** `config()` lives in `api.js` (cached per page; `configureApi` resets it). |
| L6 | **Fixed:** Stop → `DELETE /uploads/{id}`, then `SealError('aborted')` with no resume. Tested on the fake and on the real API (204, then the upload is gone). |
| L7 | **Fixed:** `Number.isSafeInteger(epoch)` before the splice; tested with an injected `12000,"min_epoch":1`. |
| L8 | **Fixed:** the canary passes no origin and `createLink` returns `url: null` without one. A missed `reveal` after a restart → NOTES §3 (server and site: show it as missed). |
| L9 | **Kept, deliberately:** the gate seed is public so anyone can re-run the G2c check; its ~1.97 tTARI is testnet value only. Stated in NOTES §1. |
| L10 | Comment **fixed** (`seallog.js` no longer states a cadence; reconciling §11.3 with C7 is in NOTES §3). **Rejected:** reading `text_max_chars` from `/config` at seal time. The server's value is the code constant `quota.TEXT_MAX_CHARS` (spec §9.4), not runtime configuration, so fetching it would add a request and a failure point to every text seal for a number that can't change without a code change on both sides. `contract.test.js` checks that the two are equal, so drift fails the build. |
| L11 | **Fixed:** allowed origins may carry a port; tested. |
| L12 | **Fixed:** every walk starts on a 64-row grid, so lockers whose cursors fall in the same 64-row block make identical requests (tested with lockers born at rows 3 and 5); ACCEPTANCE A-03 says exactly that. |
| `NEVER_SERVED` | **Handed on** to deploy (NOTES §3): `tools/` isn't mine. |
| New | **Found while reading the server for H3, fixed:** on a password-only link, after 3 wrong tries the server wants a PoW with every try (`428 pow_required`, purpose `password`), and the library could not send one, so the right password could never open the link from that network. `peek`/`openItem` now solve it at the server's difficulty and retry once; a `428` with `retryAfter` ("wait first") is passed to the UI. Tested on the fake and on the real API (a 60 s wait, then a PoW, then it opens). |
