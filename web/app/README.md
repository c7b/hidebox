<!-- SPDX-License-Identifier: MIT -->
# mutis app

Every screen of the product: the drop widget on the home page, the viewer (`/s/<id>`, `/t`), the
locker and its key, the dead-drop link and its public page (`/d/<id>`), the inbox, sending to a Tari
address, `/watch`, `/upgrade` and "What the chain sees" (`/verify/tx/<id>`, and `/verify` for SealLog
receipts). Our own ES modules on top of `lib/` (the crypto and protocol library, see
`NOTES-for-integrator.md` and `ACCEPTANCE-core.md`) and the vendored official ootle-wasm. No
third-party code, no build step: the files below are what the browser loads.

## Run the tests (one command)

On the server, as `build`, from a copy of the repository (Debian's Chromium, Node 20 and Python 3.13):

```sh
python3 -I web/app/ui/tests/run.py            # add --shots to rewrite web/app/shots/, --only <id> … for some flows
```

It runs, in order, and exits 1 on any failure:

1. **Static checks:** `tools/lint.py --only web/app` (spec §0.7: no HTML sinks, SPDX headers, CSP-safe
   markup), `tools/check-copy.py` (brand §7.4 banned words, no digits outside `{variables}`), every
   string the UI asks for present in `i18n/en.json` and none unused, the widget's
   string subset in sync (`i18n/subset.py --check`), every `data-testid` of spec §3.4.9 in the sources.
2. **Build:** `tools/build.py` into a fresh directory under `/var/tmp` (disk-backed; the dev
   server sizes lanes and the paid capacity from the disk under its data).
3. **Serve:** `server/bin/mutis-api --dev` on a free port: the real API, Caddy's rewrites and CSP
   headers, fakes for walletd, the indexer and the sidecar. The `upgrade-wallet` flow gets a second
   one in production's payment mode (`amount_proof = "wallet"`) through `ui/tests/devserver.py`,
   which is the same dev server with that one gate changed.
4. **Flows** (`ui/tests/flows.py`) in headless Chromium 154 with phone and desktop emulation, each in
   fresh browser contexts: the anonymous golden path, every viewer state (`expired` from a real
   60-second link), the Change panel (counts, passwords, Delete now, a revoke our server doesn't
   confirm), the card's locker actions on a first visit (Send it to a Tari address instead, 7 days, an
   error that stays in the card), kept files, recipient safety (programs, names that hide one, size
   limits, photo metadata), the locker and its key, dead drops, the inbox, sending to an address,
   `/watch`, kind-4 links, packs paid with demo tTARI in both payment modes, `/verify`'s SealLog
   receipts checked against the template builder's vectors (and a log with an owner refused), the
   testnet line after Nov 11, keyboard-only use with the Accessibility tree checked for unnamed
   controls, no horizontal scroll at 360 px, no third-party request, no CSP or Trusted Types
   violation, no WebAssembly (`--jitless`), dark mode with reduced motion, and the widget's
   payload (A-06).

The dev server's fake chain writes its outputs in the clear, which the official library in the page
can't open. `ui/tests/realize.py` (test-only) intercepts the page's mirror requests and replaces each
fake output addressed to a test locker with a genuine stealth output to the same address, value and
memo, made with the official library in Node. Everything above it, from the trial decryption to the
viewer, is the product code unchanged.

## Files

| Path | What |
|---|---|
| `drop-widget.js` | the home page's entry: mounts the widget into `#mutis-drop` (spec §3.4.4) with its first dictionary and stylesheet |
| `app.html`, `view.html` | the shells Caddy rewrites app routes and links to (`ui/app.js`, `ui/view-page.js`) |
| `ui/widget.js`, `zone.js`, `sealing.js`, `card.js`, `rules.js`, `noise.js`, `recent.js` | the drop widget: zone, sealing progress (the ¡ mark), the locked card with its noise strip, the Change panel, recent drops |
| `ui/scene.js` | the head of every app screen: the ghost in the pose of its rule (cloned from the page's `#ghost-tpl`), the screen's line and the ghost's sentence; Tari™ words in Tari purple |
| `ui/lightbox.js`, `css/lightbox.css`, `lib/sniff.js` | the file preview (docs/review/preview-1.md): one lightbox for a drive file's name, a folder visit's files, a paid file, a single-file link (`/s/`, `/t`) and a single file in Received, each shown as soon as it opens; the kind comes from the decrypted bytes (`sniff.js`: png, jpeg, gif, webp, avif in an `<img>`; SVG drawn into a canvas; UTF-8 text as text nodes; the rest download only), Download always there; loaded the first time a file opens |
| `ui/view.js` | the viewer and the gone page: every state of spec §12.3.2 on the ghost, the goodbye receipt (on chain or pending), the opened file in the preview (ui/lightbox.js), the program warning, `/t` deliveries |
| `ui/known.js` | "What the server knows", the glass box |
| `ui/locker.js`, `keyflow.js`, `locker-ctx.js` | `/locker` (first screen: its three things by name; a drop link asks nothing first), the key (save, restore one tap away, the one-time prompt with Later), opening a locker only when something needs it |
| `ui/droppage.js`, `inbox.js`, `send.js`, `watch.js`, `upgrade.js`, `verify.js` | the other app pages |
| `drive.html`, `ui/drive.js` | the drive (16-drive-design §2): `/drive`, `/drive/folders/<id>`, `/drive/shared`, `/drive/activity`, `/drive/trash`, `/drive/storage`, `/drive/received`, `/drive/earnings` (where pay to open is on), one page that moves between them; `?make` makes a drive at once, `?open` opens the key dialog |
| `ui/behaviors.js`, `css/drive.css`, `/shared/ui/` | the shadcn/ui new-york port (DESIGN.md): Radix behaviour in plain DOM (dialogs, sheets, menus, select, tabs, tooltips, toasts, switches), the tokens, components and Lucide sprite, the drive's compositions; Geist in `/shared/fonts/geist`, pinned in `tools/build.py` |
| `ui/drive-shell.js`, `drive-parts.js`, `drive-start.js`, `drive-list.js`, `drive-menu.js`, `drive-upload.js`, `drive-storage.js`, `drive-account.js`, `activity.js`, `drive-known.js`, `drive-received.js`, `drive-earnings.js`; `lib/feed.js` | the shell; rule badges and frames; Make or Open my drive; My drive, folders, Shared, Trash; Move, Rename, Delete it after…, trash; uploads (files, the folder picker, dropped folders); Storage and Get more space; Settings and the key; Activity (what happens together as one row, by day, Show more, the chips, the CSV; its data in `lib/feed.js`); What our server knows; Received (interim); Earnings (the total, each paid link's take, the payments, where the money is) |
| `lib/drive.js`, `folder.js`, `entries.js`, `api-drive.js` | the drive's index opened with the vault key, rules from links; folders as a key tree (`childWrapKey`); the folder walkers; the folder API |
| `ui/share-dialog.js`, `folder-view.js`, `drive-received.js`; `lib/links.js`, `folder-open.js`, `zip.js`, `purchases.js` | 16-drive-design §3, §5, §6: the share dialog (rules, secret word, Delete it from my drive after, Send by Tari, the result, Links); a folder link's visit (in the drive's look on `/s/<id>`, and in Received) with Download all as a stored ZIP; Received (Tari arrivals, the drop link, purchases, Save to my drive); the flows in `ui/tests/flows_share.py` run on a dev server with `features.folders` on |
| `lib/pay.js`, `ui/paypage.js`, `ui/sales.js` | 16-drive-design §4: pay to open. The seller's sales keys, `PUT /me/sales`, the split-key pay link and its teaser; the buyer page on `/p/<id>#5…` (claims kept in `localStorage` `mutis.claims`, test money, Pay from my drive, Another Ootle wallet, the steps, the paid open); the owner check (`checkSales`, R1) and the Payments on Earnings; flows in `ui/tests/flows_pay.py` (the pay routes faked by `PayFake` until the server lane's step 14) |
| `ui/core.js`, `marks.js`, `errors.js`, `shell.js`, `more.js` | shared pieces: icons, durations, toasts; amounts, addresses, safety codes; every error code's copy; page start-up; loading the rest of the strings and styles |
| `css/widget.css`, `css/parts.css`, `css/app.css` | what a first drop needs; the components beyond it; app pages. Shared tokens only; `md-` for the widget, `a-` for app pages and shared components |
| `i18n/en.json` | the copy deck (11-brand §8–§14 with 12-integration's terms); every number is a `{variable}` from `/config` or computed |
| `i18n/widget-en.json`, `subset.py` | the strings a first drop needs, generated from the full dictionary |
| `ui/tests/` | `run.py` (the command above), `flows.py`, `flows_drive.py` (the drive), `flows_preview.py` (the preview with the hostile fixtures of `tests/fixtures/preview`), `cdp.py` (DevTools over a pipe), `realize.py`, `devserver.py` (the dev server in another payment mode), `drivefake.py` (the server lane's folder API in front of the dev server until it has `features.folders`) |
| `shots/` | curated screenshots (WebP) from `run.py --shots`; test evidence, not served (NOTES-ui.md asks deploy to skip it) |
| `ACCEPTANCE.md`, `NOTES-ui.md` | acceptance evidence; requests to other builders and decisions |

## How the pieces fit

- **Lazy by design.** The home page loads the zone and the proof-of-work prefetch; the sealing code
  loads as soon as the visitor reaches for the zone; the card loads with the first link; the Change
  panel, the glass box, errors and the send step load (with the rest of the strings and `parts.css`)
  the first time they are shown. ootle-wasm loads only when a locker is opened.
- **No HTML from strings.** Every node comes from `lib/dom.js`'s `h()`; dynamic CSS values only
  through custom properties; the one script-URL sink (the PoW Worker) goes through the `mutis-url`
  Trusted Types policy in `lib/dom.js`.
- **Copy follows what happened.** The send result names the mode that send actually used; the pay
  stepper names the checks of this deployment's `amount_proof`; receipts appear only when
  `features.seallog` is on.
