<!-- SPDX-License-Identifier: MIT -->
# Acceptance: app-ui (the screens of web/app)

Spec §16.2, the ids this builder owns (A-04…A-09), plus the UI evidence the task asked for. Run on
2026-10-11 on ultron (Debian 13, Chromium 154 headless, Node 20.19.2, Python 3.13) as `build`,
against the real API (`server/bin/mutis-api --dev`, fakes for the chain) serving a fresh
`tools/build.py` output. One command reruns everything:

```
$ python3 -I web/app/ui/tests/run.py --shots
…
UI PASS 220/220
```

The last full run was the English-only pass's (2026-10-12, a `git archive` of commit `fd2706f` in
`/home/build/work/english/tree`; log in `docs/evidence/2026-10-12/english/suites/ui.log`): 20 flows
(the `spanish` flow and the dictionary-parity checks are gone with Spanish); the `states` flow waits
65 s for a real link to expire. The screenshots below are from the fix pass's `--shots` run.

The other §16.2 ids belong to app-core: A-01, A-02, A-10…A-14 in `ACCEPTANCE-core.md`; A-03 (secret
hygiene, E-03) is the deploy builder's E2E, with the library-level evidence in `ACCEPTANCE-core.md`
and the storage checks below.

| Id | Status | Evidence |
|---|---|---|
| A-04 every state of §12.3 reachable, with the §3.4.9 test ids | **PASS** | static check: all 88 ids of §3.4.9 (plus P-6's `card-change`, `card-send-address`, `noise-canvas`, and `card-sent`, `card-close-link`, `dd-report`, `view-keep`, `kept-row`/`kept-save`/`kept-delete` for the flows below) are in the sources; every state reached in a browser, list below, `expired` from a real 60-second link. `key-copy` is not built: brand P-15 (accepted in 12-integration §2) removes the copy button |
| A-05 no CSP or Trusted Types violation; no cross-origin request without the explicit click | **PASS** | every flow ends with "no CSP or Trusted Types violation ([])" (production app CSP, `require-trusted-types-for 'script'`); `layout`: no third-party request on 12 app pages × 3 devices; `deaddrop`: no request to Tari's indexer until "Check it on Tari's indexer" is pressed, then only to `ootle-indexer-b.tari.com` |
| A-06 widget payload ≤ 40 KB compressed; ootle-wasm only where a locker is used; storage contents | **PASS** on a phone for a first drop of text (the ghost's flow, 14-ghost-design §17 steps 5 to 7): 24,860 B at load, 40,309 B after the drop (≤ 40,960; at f7016c4, after step 8's string and style changes), and the QR encoder never loads. **WAIVED** on a computer: the result shows the link as a code to scan, so `ui/qr.js` loads (fine pointers only, after the link exists): 43,276 B after a text drop, asserted against `QR_CEILING` = 43,520 B (the step 0 decision, 14 §16 finding 18). **WAIVED** for a file or photo: it also loads `lib/filetype.js` and, for a photo, `lib/exif.js` (recipient safety P-14 and metadata removal §4.13), 45,347 B after a photo on a phone, asserted against a stated 48 KB ceiling. What made room: no view transition, the noise strip and the glass box behind More rules, the secret word, More rules and the send step in `ui/card-more.js` (loaded with their first tap), the old card and progress CSS removed, a trimmed first dictionary | `budget` (gzip -9 of every `/app/` and `/vendor/` file the page requested): `PASS budget: phone: widget payload compressed: 24860 B at load, 40309 B after a drop (≤ 40 KB), no code encoder`, `PASS budget: computer: 43276 B after a drop with the code to scan (≤ 43520 B, the QR waiver)`, `PASS budget: phone, after a photo: 45347 B (≤ 49152 B; …)`; no `ootle_wasm` request on `/` before a locker action or after an anonymous drop; `home-text`: localStorage holds only `mutis.recent`, without the key or the text; `locker`: no key material in localStorage, IndexedDB stores exactly `identity` and `inbox` |
| A-07 keyboard-only flows; accessible names from the CDP Accessibility tree | **PASS** | `keyboard`: drop → copy link; open a link; make a drop link (and the key modal: focus inside, Escape closes); leave a file in a drop; send to an address; buy a pack; watch with a view key. The Accessibility tree has no unnamed button, link, textbox, checkbox or radio on home, card, `/locker`, the drop page, `/send`, `/upgrade`, `/watch` |
| A-08 lint clean (§0.7) | **PASS** | `tools/lint.py --only web/app`: `lint: PASS (0 problems)`; `tools/check-copy.py`: `PASS (0 problems)` (brand §7.4 banned words, no digit outside `{variables}` in either dictionary); no `innerHTML` & co. anywhere: every node comes from `lib/dom.js`'s `h()` |
| A-09 without WebAssembly, anonymous drop and open work; locker features say `needs_wasm` | **PASS** | `nowasm` (Chromium `--js-flags=--jitless`): a text drop opens; `/locker`, `/d/…`, `/inbox`, `/watch` show `[data-code="needs_wasm"]` (the drop page with the Tor Browser / Lockdown Mode wording of app-core's note M8) |

## The golden paths (task list)

| Path | Flow | Result (trimmed) |
|---|---|---|
| Anonymous drop → open → burned | `home-text` | link `…/s/<22>#1<43>`; text to link 0.4 s at 390×844; Copy link fills the clipboard; B: `ready` → `Opens once` → `opened`, exact text, the key left the address bar; reload and a second browser: "This secret already made its exit." |
| First visit on a phone to a copied link | `ten-seconds` | 412×915 Android emulation, touch, 4× CPU throttle: landing 1.1 s, photo to copied link 2.4 s in all (< 10 s, no human pauses) |
| Exit rules | `rules` | 3 opens on **the same link** (PATCH); B, C, D save the file; the fourth sees `burned`; link + password: new `#2` link, old link `revoked`, wrong tries say "3 tries left before a pause of 1 minute", the right one opens; password-only opens without a key part; a revoke our server doesn't confirm (`DELETE` answering 500): an error in the panel, the same link on the card, no "no longer works" toast, the old link still opens; Delete now → `revoked` |
| The card's locker actions on a first visit | `card-fresh` | in browsers that never had a locker: Send it to a Tari address instead → the locker opens in place → `Sent`; the old link's revoke answering 500 keeps the link on the card (it still opens) with Close the link; then `card-sent` ("Sent to otl_esm_1…… instead. The link no longer works…"), no Copy link, the old link `revoked`; Change → 7 days → the same link, 7.00 days; `/auth/register` answering 429: `error-banner[data-code=rate_limited]` inside the card, the link and Copy link still there |
| Kept files (P1) | `kept`, `deaddrop` | Only me → kept, no link; Until I delete it → a new link that stays, the anonymous copy's link ended; `/locker` lists both by name; Save returns the same SHA-256; Delete leaves one after a reload; Keep a copy in my locker from the inbox lists the photo |
| Recipient safety | `safety` | anonymous `.exe` refused before any upload; `invoice.b\u200Bat` and `run.p\|s1` refused as `.bat` / `.ps1`, nothing uploaded; 26 MiB refused with the free-locker offer; with the locker opened in place the program is locked; the viewer shows `program-warning` with Save anyway and no preview; files a modified client stored as `invoice.b\u200Bat`, `run.p\|s1`, `photo\u202Egpj.exe` get the program warning named `invoice.bat`, `run.ps1`, `photogpj.exe`, and Save anyway offers `photogpj.exe`; a GPS photo shows "Location and camera data removed" and opens with a preview |
| Locker and key | `locker` | made silently from Make my drop link; the key modal asks once; with the passphrase box ticked an empty passphrase stops the download; the key file is locked (`Locked key:`, no plain code); 12-emoji safety code, `otl_esm_1…` address, banner until saved, probation, quota; restored in a clean browser from the file and passphrase: same code and address |
| Dead drop create → submit → inbox | `deaddrop` | the stranger's page shows the owner's 12 emoji and the label in a `<bdi>` inside quotes, says the link's maker wrote it, and has Report this drop (`/abuse#link=<drop URL>`); a program is refused before upload; photo → Delivered with a tx id; What the chain sees: no amount shown, fee public; the owner's inbox finds it through the mirror (see the note below) and opens the photo with What the chain saw: hidden on chain, "your locker reads 0.001 tTARI" (the courier amount from `/config`) |
| Send to an address | `send`, `kind4` | the recipient's safety code on the send screen; relay send: Sent, tx id, the relay sentence of C8; the recipient's inbox opens it; L1, mainnet and invalid addresses explained before any request; kind 4: the memo is a `/t#4…` link and a browser without a locker opens it with the view key alone |
| Watch with a view key | `send` | `/watch#mine` and another browser with the exported view key: ≥ 1 delivery, `data-readable = 0`; a view key of another address is refused (`address_mismatch`) |
| Upgrade pack with fakes | `upgrade`, `upgrade-wallet` | sidecar mode (the dev default): s30 → invoice address → Pay with demo tTARI → stepper `waiting, seen, proven, added` all done; quota +2 GiB. Production's mode (`amount_proof = "wallet"`, a second dev server through `ui/tests/devserver.py`): the stepper reads Waiting → Seen by our wallet → Exists on chain → Added, the claim is C11's wallet variant, and every step is reached after a demo payment. With the clock on Nov 12 the testnet line says the Ootle mainnet is live, like the footer |
| SealLog receipts (P1) | `receipts` | a real drop keeps the ciphertext hash this tab computed (equal to our server's); on `/verify`, against the template builder's 2.0.0 state and proofs: the stored and exit proofs verify at the log's checkpoint #1, a hash the file never had doesn't, the log's one writer key is named, and the research component (it has an owner) is refused |

The dev server's fake chain writes outputs in the clear, which the official library in the page
can't open; `ui/tests/realize.py` (test-only) swaps each fake output addressed to a test locker for a
genuine stealth output to the same address, value and memo made with the official ootle-wasm in Node.
Trial decryption, unwrapping and opening are the product code, unchanged. Real-chain runs are the
deploy builder's `@chain` E2E.

## Every state, reached in a browser

- **Widget:** `idle`, `composing`, `sealing` (`seal-progress` names its phase; pictured at
  `encrypting` on a slowed uplink), `sealed` (the card), `error` (`program`, `too_large` banners);
  events `mutis:state` `composing → sealing → sealed`; the Change panel, the glass box, recent drops
  with their states; the card's own error, its sent state and its kept state.
- **Viewer:** `loading`, `incomplete`, `password` (wrong, tries left), `ready`, `opening`, `opened`
  (text, image), `program-warning`, `burned`, `expired`, `revoked`, `removed`, `not-found`,
  `wrong-key`, `locked`, `integrity-error` (one flipped bit, nothing shown), `needs-locker` (and the
  view-key form). `expired` comes from a real link set to 60 seconds (`/config` patched with the
  `e2e_expiry_s` field a test deployment sends, NOTES-ui §1); `removed` and `locked` are the server's
  answers replayed, and `integrity-error` a replayed answer with one bit flipped (`states`).
- **Drop page:** `loading`, `ready`, `sealing`, `sending`, `delivered`, `closed`, `not-found`, `error`
  (`needs_wasm`).
- **Inbox:** `inbox-scan` with `data-checked`, items `data-source="drop"` and `"send"`, `inbox-empty`.
- **Send:** `send-status` `sealing → waiting → sending → delivered`.
- **Upgrade:** `invoice-status` `pending → credited`; `pay-step` × 4.
- **Verify tx:** `tx-root`, `tx-output[data-amount="hidden"]`, `tx-fee`.
- **Verify receipts** (`receipts`): with `/config` turned to SealLog on and the template builder's
  2.0.0 component state and proofs as the answers, `/verify` reads "Stored: included at checkpoint #1
  (epoch 12128)" and "Exit: included at checkpoint #1" for a file whose hash this device kept (the
  log's own number, not the 9 the answer carried), "doesn't match" for a hash the file never had,
  names the log's one writer key, and refuses the research component on Esmeralda (it has an
  owner). The device's kept hash equals our server's for a real drop.

## Layout and themes

- No horizontal scroll at 360 px on `/`, `/locker`, `/inbox`, `/send`, `/watch`, `/upgrade`,
  `/verify`, `/t`, `/verify/tx/…`, `/s/…`, `/d/…` (`layout`, at 360, 390 and 1440).
- Dark theme with reduced motion: stage background `rgb(14, 13, 11)`; the card and viewer work
  (`dark`).
- English only since 2026-10-12 (the owner's decision; 12-integration §7.8): the `spanish` flow,
  the Spanish dictionaries and the `es-*` screenshots are gone. The site's own check of the phrases
  `/judges` quotes passes against `en.json` (`web/site/tests/run.py`: "/judges quotes the app's
  words: PASS").

## Screenshots

`web/app/shots/`, 48 WebP files, 3.3 MB, from `run.py --shots`: phones at 390×844 and 412×915,
desktop at 1440×900, dark mode with reduced motion (`*-dark-*`). Full-page phone
shots are taken at 1.5× and show the sticky bottom bar where the capture caught it.

| Screen | Files |
|---|---|
| Home widget | `home-390-idle`, `home-1440-idle`, `home-1440-sealing`, `home-390-sealed`, `home-1440-sealed-file`, `home-390-sealed-photo`, `home-390-change`, `home-1440-change`, `home-1440-password`, `home-390-known`, `home-1440-program`, `home-1440-card-error`, `home-390-sent-instead`, `home-1440-dark-sealed` |
| Viewer | `view-412-ready`, `view-412-opened-text`, `view-390-opened-photo`, `view-390-password-wrong`, `view-412-burned`, `view-1440-burned`, `view-1440-expired`, `view-1440-incomplete`, `view-1440-integrity`, `view-390-locked`, `view-1440-program`, `view-1440-known`, `view-390-needs-locker`, `view-390-dark-opened` |
| Locker and key | `locker-390-empty`, `locker-390-key-modal`, `locker-390-full`, `locker-1440-restored`, `locker-1440-kept`, `locker-390-dark-empty` |
| Dead drop, inbox, send, watch | `drop-1440-ready`, `drop-1440-delivered`, `inbox-390`, `inbox-390-opened`, `inbox-1440-empty`, `send-412-recipient`, `send-412-sent`, `watch-1440-mine`, `watch-390-viewkey`, `watch-1440-needs-wasm` |
| Upgrade, chain | `upgrade-390-plans`, `upgrade-390-credited`, `upgrade-390-credited-wallet`, `verify-1440-tx` |

## Not covered here

- Real iPhone and Android sessions (12-integration §1: headless emulation for now; the owner checks
  real devices after delivery).
- `/verify` against live SealLog receipts: the dev server runs with `features.seallog = false`, so
  `receipts` answers the chain and proof requests with the template builder's vectors (above); the
  live log is checked once the integrator turns SealLog on.
- Direct-mode sends and browser-signed pack payments: production runs `send_mode = "relay"` until
  E-J passes (app-core's note); the UI picks its copy from the mode each send actually used.
- Cross-directory items this component can't close (NOTES-ui §1): `/judges` B6 in wallet mode
  (site), the `/abuse` prefill (site), not serving `web/app/shots` (deploy); `/config.seal_log`
  `template` and `writer` (server, `NOTES-for-integrator.md` §4).
