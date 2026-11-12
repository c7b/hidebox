<!-- SPDX-License-Identifier: MIT -->
# Changelog

<!-- mainnet 1 -->
## 2026-11-12: hidebox on the Ootle mainnet, a second instance

Production stays on Esmeralda, unchanged. A second, independent instance runs beside it on the same server, at
its own host, first as a staging rehearsal on Esmeralda and from launch day on the Ootle mainnet with real TARI.

- **SealLog on the mainnet**, 2026-11-12 18:28:36 UTC, epoch 38542: `template_494d34a5f55bcef614655c9f8b7fdcb672f1d086467fc96816c0a93a4a5c8472`, published by the launch trigger with `template/dist-v2/` byte for byte (transaction `dbb5173483176a9cadbc82bec4b981d44dd178eb8dfa750febe1e1462bc74dca`), and its log `component_45efaa40c370fa98b86ad59bd395694a241313d741f81ed30bc772b88ef84690` (no owner, upgrade rule Locked, only the service key appends). The receipt, with the raw indexer answers: `docs/evidence/2026-11-12/mainnet-launch/`. The same day mainnet.hidebox.app moved from its staging rehearsal to the mainnet.
- **The network is a config choice**: `network = "esmeralda" | "mainnet"` and `staging` in mutis.toml
  (`server/mutis/network.py`: the network byte, the address prefix, the coin, the indexers). On the mainnet the
  server refuses to start with demo payments, sponsor grants or judge passes on, and forces them off over any
  override; addresses, the sidecar and walletd are checked against the network; `/config` says which.
- **An instance beside production** (`deploy/scripts/instance.py`): its own config, tree, users, walletds,
  units, ports and Caddy site, rendered from production's units and Caddyfile, validated inside the live Caddy
  configuration before it is installed; `provision-instance.sh`, `deploy.sh --instance`, `mutis-admin-NAME`,
  backups, health and evidence per instance. Production's paths are the defaults everywhere.
- **The launch kit** (`deploy/ootle/`): the mainnet walletd's accounts and a root-only seed backup
  (`mainnet-walletd.sh`), the burn guard (`burn-guard.py`, `mainnet-start-height.json`, `burn-mainnet.md`),
  the mainnet L1 wallet (`l1-wallet-mainnet.sh`), the unattended launch trigger (`launch.py`,
  `launch-arm.sh`), the flip from staging (`flip-to-mainnet.sh`) and the launch-hour runbook
  (`mainnet-launch.md`).
- **verify-deploy checks an instance too**: it rebuilds with the instance's own `staging` and `testnet_origin` from
  `/config`, so a staging or mainnet deployment compares equal to its tag.
<!-- /mainnet 1 -->

<!-- withdraw -->
## Draft (November MVP): withdrawing earnings

- **Withdraw**, in Earnings, behind `features.withdraw` (off by default): the drive sends what people paid to its
  pay links to any Ootle address the owner types. It is built and signed in the browser from the drive's own sales
  keys (`stealthDhSecret`, as Pay from my drive spends), so our server never holds a key that can move it and never
  learns where it goes. The confirm step shows what arrives, the network fee (0.03, taken from the amount
  withdrawn), what leaves the earnings, and the address with its first and last 6 characters set apart. The receipt
  links What the chain sees.
- **Rules, the same in the browser and on our server**: at least 0.06; change smaller than the fee goes along
  instead of staying as dust; at most 8 payments per withdrawal; only settled money (counted, and test money or
  checked by the owner's drive, the same rule as Earnings), so a payment still being counted is never spent away from
  its buyer; one at a time (the button, the library and our server each refuse a second). An address on another
  network, with a broken checksum or with a payment reference is refused before anything is built.
- **Server**: migration 009 (`sale_payments.withdraw_tx`, `withdraw_at`, `withdrawn`; `sales_change`),
  `GET /me/sales/outputs`, `POST /me/withdrawals` (checked, marked, relayed), `POST /me/withdrawals/{tx}` (the
  drive's report of the outcome), `/config`'s `withdraw` rules. Docs: `docs/withdraw.md`, the threat model.
- Tests: `server/tests/test_withdraw.py`, `web/app/tests/withdraw.test.js`, `web/app/ui/tests/flows_withdraw.py`.
<!-- /withdraw -->

<!-- shop -->
## Draft (November MVP): a drive's shop

- **My shop**, behind `features.shop` (off by default, so production is unaffected): a drive turns on a public page at
  `/shop/<id>` with a name and a bio its owner writes, and lists some of its pay links on it, each with a title and a
  line the owner types (never the file's name), file or folder, its padded size and its price. **Buy and open** is the
  pay link's own page, unchanged; Earnings are unchanged. Take a listing off, edit its words, or turn the shop off (its
  page answers 404, the pay links keep selling); a paused pay link hides its listing, and one that ends removes it.
- **The split key holds for listed links.** The shop's link is `/shop/<id>#6<shop key>`; our server keeps the key only
  wrapped under the drive's key and each listing's `sA` only sealed with it (`link_ct`, bound to its link), so it holds
  one half of each listed link and opens none. Whoever holds the shop's whole link holds every listed `sA`; the
  listing dialog says what that means (docs/shop.md, "Threat-model delta").
- **Server**: migration 008 (`shops`, `shop_listings`, `abuse_reports.shop_id`), `GET/PUT/DELETE /me/shop`,
  `PUT/DELETE /me/shop/listings/{id}`, `GET /shop/{id}` (cached a minute), `/config`'s `shop` limits (50 listings, field
  lengths), rate limits per drive and per network; **Report this shop** through the existing report form and
  `mutis-admin takedown shop`. Caddy serves `/shop/` from `shop.html`, `view.html`'s twin with its own card
  (`og-shop.png`); `/shop/` is noindex and disallowed in `robots.txt`.
- Tests: `server/tests/test_shop.py`, `web/app/tests/shop.test.js`, `web/app/ui/tests/flows_shop.py`.
<!-- /shop -->

<!-- security 2026-11-09 mainnet -->
## Unreleased (launch/mainnet): the security pass on the mainnet instance

The pass below, and what it found only here (`docs/review/fix-log.md`, findings 12 to 15):

- **Withdrawals**: an output commitment is 32 bytes before anything is made from it. Written as a number, it made the
  API allocate that many bytes: one small request from any drive took it past its memory limit. Every request is now
  counted before its envelope is read.
- **Money not yet withdrawn outlives its link's note**: a pay link that still holds settled money its drive hasn't
  withdrawn keeps its note, and its file's, past the 30 days, until that money is withdrawn. Before, the money left
  Earnings with the note and the relay refused to withdraw it.
- **A walletd or a sidecar on another network** is said in the journal with its own event; the refusal used to raise
  from the logger.
- **No daily evidence payment on the mainnet**: it is test money, and the worker no longer queues it there.
<!-- /security 2026-11-09 mainnet -->

<!-- security 2026-11-09 mainnet web -->
## Unreleased (launch/mainnet): the browser's security pass on the mainnet instance

The browser's pass below, and what it found only here (`docs/review/fix-log.md`, "The browser on the mainnet instance"):

- **A page's network is its build's.** The app's pages name it in their HTML; a page without that has no network
  until `/config` names one, and nothing that touches Tari runs meanwhile. Before, one failed first request left a
  mainnet page on Esmeralda's byte, where the owner's check reads every real payment as not its own.
- **Withdraw**: the confirm step sets apart six characters after `otl_1`, as it says; a withdrawal that never said
  how it ended is settled from what the indexer shows (unspent, or proven spent), never from a 404.
- **The key file** calls a mainnet address "Ootle mainnet"; `/verify` links Esmeralda's indexer page only on
  Esmeralda.
- **The shop's link and its Buy links** are built on the page's own origin, like every other link.
- **The sidecar's self-test** passes on the mainnet: its known answer for "is this output ours to spend" was made on
  Esmeralda and is now derived with Esmeralda's byte, and a fresh output is checked on the network the sidecar runs on.
<!-- /security 2026-11-09 mainnet web -->

<!-- security 2026-11-09 -->
## 2026-11-09: a security pass on the server and the deployment

An audit of the API, the chain worker, the deploy scripts and the end-to-end tools. Nothing it found lets anyone
read another person's file or key, or spend the wallet. What it found were ways to keep others from buying,
downloading or making a drive, a way to make a file's own receipt fail, and three places where root trusted a name a
lower user could have put there. Each is fixed with a test; `docs/review/fix-log.md` has the table.

- **Download the stored bytes** is charged the bytes of its Range (it was the whole file, whatever was asked for), a
  network takes a file's stored bytes 3 times a day (6 per /48), and all of it stays within half the file's daily
  egress, so opens keep the other half.
- **Claims on a pay link**: one network makes 2 an hour on one link (3 per /48), so it can't hold all 20 of a link's
  waiting claims without paying.
- **New drives**: the deployment's daily cap is charged after the proof of work and given back when no drive is made.
- **Uploads**: an upload isn't completed while one of its chunks is still arriving (`409 upload_busy`), and one
  request at a time writes one chunk, so stored bytes can't differ from the hash sealed for them.
- **Ids**: every id pattern ends in `\Z`; a trailing newline no longer passes.
- **Reports**: a paid link's own address (`/p/<id>`) can be reported.
- **Root on the server**: `privilege-check.sh` has `mutis` make its probes, `activate-release.sh` tightens its
  migration backups as `mutis`, and E2E scenario E-31 runs its search from the command line, not from a file in the
  build user's directory.
- **verify-deploy** prints a tag's refused build as a difference instead of a traceback; `e2e-artifacts/` is ignored.
<!-- /security 2026-11-09 -->

<!-- security 2026-11-09 web -->
## 2026-11-09: the same security pass, in the browser

The audit's other half: the app, the site and the library they share. Nothing it found lets a sender or a link holder
run code on the site, read another person's keys or skip a link's rule. What it found is the browser acting on a
missing answer, or on an answer of our API, where money and keys are concerned. Each is fixed with a test;
`docs/review/fix-log.md` has the table.

- **The owner's check of a payment** says "the payer kept control" only on evidence: the output shown with another
  key, or proven spent. An indexer that hadn't caught up answered 404, and that alone ended a buyer's claim for good.
- **Pay from my drive** signs the price the page shows, or nothing. If the answer to its submit is lost, the page says
  the drive may have paid, offers no second payment for three minutes, and follows the claim if the first one lands.
- **Links are built on the page's own origin**, whatever `/config` answers, and a lint keeps it that way.
- **A hidebox link carries a mark of its drive's address** after its `#`; its page refuses any other address before a
  file can be chosen. Links made before open as they did.
- **A link's kind decides its mode**: a link with a word is never opened as "word only", whatever our server answers.
- **Lock my drive and Forget this browser** also clear the recent list and the drive's id where two helpers kept it.
- **Photos**: a JPEG's thumbnails in APP0 go with the rest, and the drive says when a photo or video went up as it was.
- **File names**: spaces of every kind are trimmed from a name's ends, so they can't hide a program's extension.
- **Uploads**: a file that changed between two tries starts a new upload with a new key; a complete that finds a chunk
  still arriving (`409 upload_busy`) is asked again instead of failing.
- **Reports**: the form takes a paid link, the buyer page has Report this link, and a paid program says so beside Save.
- **Download all** refuses a name too long for a ZIP instead of writing an archive nothing opens, and a file can't
  take the name of the folder beside it.
<!-- /security 2026-11-09 web -->

<!-- ootle 0.52 -->
## 2026-11-09: Ootle 0.52.0 on Esmeralda

Esmeralda moved to Ootle 0.51.0 and then 0.52.0 on 2026-11-09, without a reset and with no activation epoch:
validators, indexers and wallets upgrade together. hidebox kept working through the move on walletd 0.50.1; what
0.52 would have broken is a burn claim by an older wallet, which is how hidebox gets test money from L1. This
release changes only what the upgrade needed. Every earlier tag stays where it was; this release has its own tag.

- **walletd 0.52.0**: the release binary (tag v0.52.0, commit `4ee751c`), checked against four sources and
  rehearsed on a copy of the wallet first; live since 18:16 UTC. The calls mutis makes, the command line and the
  wallet's store are unchanged (no migration).
- **The official libraries, 0.52.0**: `ootle-wasm` and `ootle-wasm-bor` 0.52.0, from the npm tarballs that tag
  published (provenance in each folder). Only their `.wasm` changed: they refuse a few malformed inputs earlier
  (non-canonical keys, the same input twice). The API, the glue and the layouts the browser builds and reads did not.
- **SealLog stays as published**: templates on `tari_template_lib` 0.38 keep working on 0.52, and the log kept
  committing checkpoints through the move, at the same cost (about 6,000 µT each).
- **The runbook**: `deploy/ootle/upgrade-0.52.md`, with what 0.51 and 0.52 change for hidebox and how to tell that
  a fleet has moved (`/info` on an indexer); the run's evidence in `docs/evidence/2026-11-09/upgrade-0.52.0/`.
<!-- /ootle 0.52 -->

<!-- testnet line -->
## 2026-11-09: the testnet line after the mainnet's launch

From 2026-11-11 the footer and the money screens would have said that hidebox "stays on the testnet until our code
is reviewed". The mainnet beta at mainnet.hidebox.app makes that untrue, so the line now reads: "The Ootle mainnet
is live; hidebox runs there as a beta, with real TARI." Nothing else changes. This release has its own tag.
<!-- /testnet line -->

<!-- ootle 0.50 -->
## 2026-11-07: Ootle 0.50.0 on Esmeralda

Esmeralda moved to Ootle 0.50.0 on 2026-11-07, without a reset, ahead of protocol V1 at epoch 12951. This
release changes only what the upgrade needed. The tags `spooky-secrets-2026-10` and
`spooky-secrets-2026-10-reset` stay where they were; this release has its own tag.

- **walletd 0.50.0**: the release binary (tag v0.50.0, commit `d3252ef`), checked against four sources and
  rehearsed on a copy of the wallet first; live since 03:34 UTC. The calls mutis makes are unchanged.
- **walletd 0.50.1** (2026-11-08 01:22 UTC, before epoch 12951): the release binary (tag v0.50.1, commit
  `0b3f364`), which the Esmeralda indexers already ran. It changes the engine and validator storage only, and
  `tari_template_lib` stays 0.38.0, so SealLog stays as published. `ootle-wasm` stays 0.50.0: 0.50.1 changes
  nothing the browser runs (same glue and API).
- **The official libraries, 0.50.0**: `ootle-wasm` and `ootle-wasm-bor` 0.50.0, from the npm tarballs that tag
  published (provenance in each folder). Only their `.wasm` changed; the API, the glue and the layouts the
  browser builds and reads did not.
- **SealLog, published again**: Ootle 0.50 no longer loads a template whose definition is in the V1 layout
  (tari-ootle #3398), and the 0.37 build was. The same source, rebuilt against `tari_template_lib` 0.38 (V2
  definitions) as seal_log 2.1.0 (`template/dist-v2/`), runs as
  `template_7441d16299220d821b3b0d091f59d82d4898bac2a21a1df7db606d4c8e5c869f`, with a new log,
  `component_f8820af05feaf4e327e59b3210fe2566e864f5b6631f5e41d6e63d28dd384fbe`: no owner, upgrade rule `Locked`,
  only the `service` key appends. Its first checkpoint holds the whole tree, so every receipt checks against
  it. The previous log (`component_6a3eae19…bd65`) is listed as retired in `/evidence.json`, and
  `verify-deploy` holds every log but that one to the V2 build.
<!-- /ootle 0.50 -->

<!-- reset 0.49 -->
## 2026-11-02: the Esmeralda reset, Ootle 0.49.2

Esmeralda was reset on 2026-11-02 with Ootle 0.48.0 and 0.49.x. The organizers asked every entry to
republish its templates and change nothing else, so this release changes only what the new network needs.
The contest tag `spooky-secrets-2026-10` stays where it was; this release has its own tag.

- **The official libraries, 0.49.2**: `ootle-wasm` 0.49.2 replaces 0.46.0, and `ootle-wasm-bor` 0.49.2, the
  official decoder for the values indexers now serve as base64 CBOR, joins it (both from tag v0.49.2, commit
  `aa7b0c8`, the walletd 0.49.2 the server runs; provenance in each folder). Keys and addresses derive as
  before: a drive keeps its `otl_esm_…` address.
- **What the new network changed, and where**: a stealth output's one-time key now takes the address's view
  key (`stealthDhSecret(network, k, v, R)`) in the browser wallet, the sales check and the sidecar; memos
  read `DestinationTagAndBytes` (the old `PayRefAndBytes` layout under a new name); a transaction names its
  `main_signer` (`"SealSigner"`) instead of `is_seal_signer_authorized`; indexer values are `Encoded<…>`,
  read in the browser with the official decoder and on the server with `server/mutis/cbor.py` (the strict
  reader the proxy already used for envelopes, now also reading indexer values), held to the official
  decoder on real Esmeralda answers (`server/tests/test_cbor.py`).
- **SealLog**: the same template, rebuilt against `tari_template_lib` 0.37 under 0.49's authorization model,
  with its upgrade rule `Locked` written out: nobody, us included, can swap the code under the log. The
  browser's receipt check now also requires `Locked`. It is published again, by the reset wallet's new
  `service` key, so the template and log addresses are new.
- **What the reset left behind**: the transaction view ("What the chain sees") reads the indexers' encoded
  receipts and results; the hourly payment reconcile checks only payments from `ootle.mirror_start_epoch` on,
  so the outputs credited on the old chain, gone with it, don't freeze credits.
- **The wallet**: walletd 0.49.2, reset (`tari_ootle_walletd reset --confirm`); because its seed lived in
  the database the reset sets aside, it came back with a new seed, so the accounts have new keys. The
  receiver and robot keys are separate files and didn't change.
<!-- /reset 0.49 -->

<!-- viral 1 -->
## 2026-10-22: a line after the value, a card per kind of link, two numbers a day

- **After the value, one quiet line**: under an opened secret (`/s/`, `/t`), an opened shared folder, a bought file
  once it opens (`/p/`) and a delivered drop (`/d/`), "Want your own? Private drive. No email. No KYC." with one outline
  button, **Make your own secret** (to `/?from=share#share`) or, on `/p/`, **Sell your own files** (to
  `/drive?make&from=share`), and a × that hides it for that page view. Never before the value, never in a browser
  that holds a drive, and nothing of the link in it. The link page's foot keeps its Make your own secret, now with
  `?from=share` too; while the line shows, the foot's button steps aside, so the page has one, and the × brings it back.
- **A preview card per kind of link**: a secret ("Someone sent you a secret."), a paid link ("A locked file on
  hidebox.") and a drop link ("Leave a file on hidebox.") each have their own title, description and dark 1200 × 630
  card (`og-s.png`, `og-p.png`, `og-d.png`), the same for every link of a kind. Caddy serves `/p/` from `pay.html` and
  `/d/` from `drop.html`, the twins of `view.html` and `app.html` but for their cards; `tools/check-seo.py` checks each
  card and that no part of a link's address is in it.
- **Two numbers a day (C60)**: a tab that came through one of those buttons says so once, with its next one-off link
  or new drive (`from_share: true`), and the server adds one to that UTC day's `secret_from_share` or
  `drive_from_share` (`daily_counts`, migration 007), kept 400 days; nothing about who. `mutis-admin counts [--days N]`
  prints them; `/fine-print` lists the table.
<!-- /viral 1 -->

<!-- share simple -->
## 2026-10-21: a link page that says less, Copy that stays, the mark in the code

- **The link page (`/s/…`) says less**: "Someone shared something with you.", the opens left and the time in one line
  ("Opens 2 more times, until Oct 22, 8:00 PM. Then it's gone."), "The server can't see inside to scan it, so open only
  what you expected.", **Open it**. Its foot, in every state (opened, ended, not found): **Make your own secret**, an
  outline button to `/#share`, then **What the server knows** and **Report this link**. The ended and not-found lines
  say "the server", never "we".
- **Reached at `/#share`**, the home's share box comes fully under the header, wears a lime ring that breathes three
  times and settles (still, with reduced motion), and **Choose a file** takes the focus.
- **Copy link is always there** after a link is made (home, the share dialog, a pay link, the hidebox link, Settings'
  address): Copied for two seconds, then Copy again; **Share** sends the link alone to the device's share sheet.
- **Every QR code carries the mark** in its centre, at level Q (the encoder now has levels Q and H): the codewords
  under it stay at least two below what each block corrects (4 of 11 on a `/s/` link), or the code goes without it.
  `web/app/ui/tests/qr_logo.py` checks that, and that each code still reads back, without a phone.
<!-- /share simple -->

<!-- drop compact -->
## 2026-10-21: a compact hidebox link page, one name for the 12 emoji

- **The page of a hidebox link (`/d/…`) fits the first screen** at 1440 × 900 and on a 390 px phone: the head in one
  row, then two buttons side by side, **Choose a file** and **Write a secret** (the sprite's file-up and pencil; the
  browser's own file input is never drawn, so no "No file chosen" in any language), "Or drop a file here." with a
  mouse, the limits, then **Whose drive is this?** and the fine print. The home's widget and the old app pages use
  the same two buttons.
- **The 12 emoji are the "drive ID" everywhere**: Settings' "Your drive ID" (its own row: "12 emoji only your drive
  has. It's not a secret: share it, so people can check that a hidebox link or Tari address is yours."), the link's
  page ("Drive ID", "Ask the owner for their drive ID. If all 12 match, it's theirs."), the send step and the share
  dialog ("Their drive ID", "Compare all 12 with them, out loud or on a call."), screen readers ("Drive ID …") and
  `/made`. The key file's "Safety code:" line stays, as the format's vectors pin it.
- **"drop link" is now "hidebox link"** in the app, Received ("…or left at your hidebox link."), `/made`, `/fine-print`
  and SECURITY.md; URLs stay `/d/…`. `tools/check-copy.py` retires "drop link" and "safety code" in copy.
<!-- /drop compact -->

<!-- preview share -->
## 2026-10-21: a preview you can read, share and rename

- **Selected words in a preview stay readable.** A note's or a text file's selection took the page's own colours: white
  words on a white tint in the drive, ink on gunmetal in dark, so they vanished. The preview now sets both colours, in
  both themes, and the reading pages' selection keeps the text colour in dark. **The fine print's What's wrong list
  reads in both themes**: the light switch now sets the browser's colour scheme, and a list's options carry the page's
  colours, never the OS's. **The drive's preview has Share** (the share dialog, over the preview) **and a name you
  rename in place** (the pencil or the name, the same Rename as the menu). Every rename field opens with the name before
  its extension selected, and a new extension asks first ("Change .png to .txt?").
<!-- /preview share -->

<!-- packs small -->
## 2026-10-21: smaller space packs

- **The small pack is 256 MiB and the big one 1 GiB** (were 2 GiB and 5 GiB), each for 30 days at the same
  prices (0.5 and 1 tTARI) and with the same ids (`s30`, `m30`). The Upgrade dialog reads "+256 MB for 30 days"
  and "+1 GB for 30 days"; packs already sold keep their size to their end, renewals included. A paid drive's
  largest file stays 2 GB, and `/made` now says it also has to fit the free share plus the pack. Review:
  `docs/review/packs-small.md`.
<!-- /packs small -->

<!-- tagline 2 -->
## 2026-10-21: a tagline that says what hidebox is

- **The home's hero is three lines and the button.** "Your private cloud storage." with "Store, send, and sell files
  privately." under it in grey, then "Built on Tari™. No KYC. No email." smaller and dimmer, then Open your drive. The
  line under the button and the line about how each file opens left the hero: the drive's start screen, one tap later,
  says "No email, no password. Your key is the account.", and Share it your way shows the rules. The same three lines
  are on the share card (`og.png`, now with the brand kit's mark and wordmark), the repository's social card, the link
  previews, the web manifest, the README and the film's end card. "Files lock in your browser first." stays a fact in
  the README and the home's description. Review: `docs/review/tagline-2.md`.
<!-- /tagline 2 -->

<!-- prune evidence -->
## 2026-10-20: leaner evidence

- **The repository keeps the evidence that backs the product as it is, and drops the rest.** It carried 55 MB of raw
  evidence and screenshots, most of them from passes that later passes replaced. Pruned: the raw evidence of
  2026-10-11 to 2026-10-18 that no live document, test or the contest entry cites (the fix passes, the 2026-10-12 and
  2026-10-13 lanes, home v2, site v4 and every 2026-10-18 design lane), the review screenshots of those designs, the
  site v2 and v4 reviews, and the curated screenshots no document names (26 in `web/app/shots/`, the 29 site v2 shots
  in `web/site/shots/`). `docs/evidence/` went from 34.4 MB to 9.6 MB, `docs/review/` from 12.0 MB to 0.5 MB. The new
  `docs/evidence/README.md` says what each kept folder proves; the kept reviews mark every pruned path and keep the
  result it recorded; commit `8bcd889` still holds every pruned file.
<!-- /prune evidence -->

<!-- perf 1 -->
## 2026-10-20: faster repeat visits, lighter pictures

- **A second visit fetches almost nothing.** Every stylesheet, script, picture, font and sprite now has a hash of its
  content in its name (`site.b6680ac0f9.css`), so browsers keep it for a year and never ask again; a new release
  changes the names of what changed, and the pages, which are always checked, point to them. Coming back to the home
  page used to send 30 requests (28 of them answered "not modified"); now it sends 3 (the page and two calls to our
  API). After a release it used to download about 100 KB again even when nothing had changed; now about 10 KB.
- **Smaller downloads.** Text (pages, styles, scripts, the wasm) is served from copies compressed ahead of time with
  Brotli and gzip instead of on the fly: 7 to 12 % less on a first visit, page by page. The share cards and app icons
  shrank without changing a pixel (og-s.png by half, the icons by 44 %).
- **Removed:** the `/v2` preview with its four videos (11.2 MB in the repository), which no page linked; `/v2` now
  goes to the home page. Old screenshots no test makes any more went too.
- Nothing moved to another host or CDN. Review: `docs/review/perf-1.md`.
<!-- /perf 1 -->

<!-- security-audit-1 -->
## 2026-10-20: security audit 1

A full audit of the repository and the deployment, unit by unit, with an independent check of every finding
(`docs/review/security-audit-1.md`). Nine findings, each fixed with a regression test:

- **The status directory follows no links.** Caddy serves `/status.json`, `/evidence.json` and `/releases.json` from
  a directory two service users can write, and it followed a symlink planted there, so a compromised chain worker
  could have published Caddy's own TLS key. The directory is now mounted `nosymfollow` (live on the server). The
  status writers (the health check, the evidence collector and root's notarize step) create their files under
  random names, so a planted link can't redirect their writes either.
- **One bad indexer can't stop the mirror.** A malformed record from one indexer stopped mirroring from all of them,
  every tick; every field is now checked and a bad answer counts against that indexer alone.
- **Paid space stays within its cap.** An invoice that gave its bytes back (swapped or expired) and was paid later
  credited anyway; it now credits only if its slice has room again.
- **Smaller fixes:**
  - Abuse reports reach the operator's terminal escaped.
  - Racing downloads of a file's stored bytes can't pass its daily egress cap.
  - A closed or taken-down drop gets no delivery still waiting in the queue.
  - verify-deploy refuses build values from the deployment that could add markup.
  - Lock my drive and Forget this browser now erase the drive's links, secret words, purchases and claims too.
  - A chunked request no longer leaves a second answer on Caddy's connection to the API.
<!-- /security-audit-1 -->
<!-- drive earnings activity -->
## 2026-10-19: Earnings, and Activity at scale

- **Earnings** (in the drive's sidebar wherever pay to open is on) answers "where's my money?": what people paid to
  open your pay links in all (test money from our demo wallet told apart, the testnet line under it), each paid
  link's take with its last payment, its opens and the transaction we know, and the payments with your drive's
  check, which move here from Received. **Where the money is:** your sales address, with Copy. The money is in
  payments to that address on the Esmeralda testnet, and only your drive's key can spend it; Tari's wallets can't use
  that key yet and the drive can't send it on, so the page says "Not yet" rather than offer a way out that doesn't
  work. `GET /me/sales` adds the total and each link's take over every payment.
- **Activity scales:** what happens together (the same kind, in the same folder, in the same hour) is one row,
  "Locked and uploaded 20 files to hidebox-brand", that opens to its files; rows sit under their day with its count;
  the newest 25 first, then Show more; chips for uploads, links, opens and payments; search filters it; payments show
  up; Download the list saves the whole log as a CSV file made in your browser. Folders read "Folder created" (they
  read "Locked and uploaded"). Review: `docs/review/drive-earnings-activity.md`.
<!-- /drive earnings activity -->

<!-- ootle-0.47 -->
## 2026-10-20: Ootle v0.47.0 (docs/evidence/2026-10-20/upgrade-0.47.0/)

- **What broke.** Esmeralda's indexers moved to tari-ootle v0.47.0 at 05:12 UTC, and `GET /substates/{id}`
  now answers `{"state": {"up": {"substate": …}}}` where it answered `{"substate": …}`. walletd 0.46.0 couldn't
  read it, so every SealLog checkpoint and release notarization failed from 05:21 (its stealth sends, the
  decoys and canary deliveries, kept committing). Our own code read every output as missing: the hourly
  reconcile froze pack credits at 05:38 (the outputs were all there), browsers couldn't read their own
  wallet's outputs before a send (`send_mode = "direct"`), and /verify couldn't read the SealLog log.
- **walletd 0.47.0** (`tari_ootle_walletd-0.47.0-9dabb2a-linux-x86_64`, SHA-256 `919579e6…ba52`, four sources
  agree, the tag's signature verified) runs since 07:19 UTC, after the drill on a copy of the wallet under the
  whole production sandbox: two additive store migrations, the same balances before and after, no sandbox
  directive loosened, no config change (its indexer list is still `indexer_api_url`, both indexers). It
  verifies what the indexer serves against the validator sets it trusts (anchored on first use at epoch 12506).
  The 0.46.0 binary and a pre-upgrade tar of the wallet are kept for a rollback. Checkpoints commit again (#790
  on), and the release deployed during the outage is notarized.
- **The code** reads both shapes (the dev server's fake chain answers like 0.47.0 now), and a spent output the
  indexer proves (`state.down`) is never a credit. An indexer answer in a shape we don't know counts as the
  indexer's problem (`unknown`: the reconcile skips the round and alerts after three hours) instead of a
  missing output, so a format change can no longer freeze credits. After a walletd restart the chain worker's
  cached token is refused (401); it now gets a new one and repeats the call once, where it used to fail every
  call for up to four minutes. Fixtures and test vectors hold real answers from both indexers (a live output,
  a spent output's down proof, the live SealLog log). ootle-wasm stays at 0.46.0: the sidecar never reads an
  indexer answer, and its suites pass. Deployed as `e6d5f7c`: `verify-deploy` finds 0 differences (the
  SealLog template check included), and E-13 (a pack paid from the browser's own wallet), E-25 and E-29 pass
  on production.
- **Credits.** No payment, invoice or claim was made during the outage, so nothing was credited late and no
  claim expired because of it; credits were unfrozen once every credited output read `ok` on both indexers.
- The upgrade drill tries a new walletd under the unit's own sandbox (a deploy test keeps the two lists the
  same), and its exit trap can no longer end before it deletes the copy.
<!-- /ootle-0.47 -->

<!-- preview 1 -->
## 2026-10-19: file previews

- **Click a file to see it.** In the drive a file's name now opens a preview (it downloaded at once before), and so
  does a file in a folder link's visit and a paid file once Open it decrypts it. One preview for all three: the
  file's name and size, Download (always there, in lime), Close; Esc closes it and focus goes back to the file;
  the arrow keys, Previous and Next, or a swipe on a phone move through the files listed beside it. It sits on v3's
  black void in both themes, with the drive's frosted glass, and loads the first time a file opens: the drive's first
  screen carries only its six new strings (120 bytes compressed).
- **What it shows comes from the bytes, never the name.** PNG, JPEG, GIF, WebP and AVIF show as pictures; an SVG is
  drawn into a canvas, so only its pixels reach the page; UTF-8 text (`.txt`, `.md`, anything else that is text)
  shows as plain text, its first 256 KB, with a note for the rest. HTML, PDF, sound, video, fonts and everything
  else are download only. A file named `.svg` that is a PNG shows as a PNG; an SVG named `.png` is still drawn, not run.
- **Tested with hostile files:** an SVG with scripts, Markdown with scripts and `javascript:` links, HTML named
  `.txt`, a GIF with a web page after it, a 300 KB text file, an empty file. Nothing runs, nothing is fetched, no page
  navigates, in the core suite and in the drive, a folder link and a paid link in the UI suite. The end-to-end runner
  can serve a local build's front end against the live site (`--candidate`); pay to open a folder (E-29) passed that
  way on production. Review: `docs/review/preview-1.md`; the threat model has a new section, "Previews".
- **Then the last two places:** a single-file link (`/s/`, `/t`) and a single file in Received open in the same preview,
  chosen from the bytes alone; the old preview by stored type is gone, so sound and video are download only there too.
  `/made` says it under The locks.
<!-- /preview 1 -->

<!-- owner-5 -->
## 2026-10-19: owner 5

- **Canary keys survive a restart.** The verifier kept each hourly test file's key in memory, so a deploy published
  a day of test files as missed. The chain worker now keeps a copy of each canary link's wrapped key until its key
  is due, and gets a key the verifier lost back from the delivery that is already on the Ootle, sealed to our test
  drive. /made#check lists test files missed in a row as one line ("23 test files missed (#150 to #172): the
  verifier restarted."), and its status line no longer says every check is working while one missed in the last
  24 hours.
- **/verify/tx**: what it proves and what stays hidden each read as one line, and "Tari's own indexer" opens the
  transaction on Tari's indexer page in a new tab.
- **The pay page** no longer flickers: it redraws only when something changes (it used to redraw itself and rebuild
  the payment address's QR code every 3 seconds), and a drive in this browser gets its line held while it is
  checked. After Pay with test money the steps show from the click and move while the payment is on its way (the
  step in progress turning, its time, what it waits on: our demo wallet sending it, then the chain), where the page
  used to sit on "Waiting for your payment" until everything appeared at once.
- **The mainnet line** reads "Ootle mainnet launches Nov 11, 2026": a launch date, checked against Tari's own
  announcements. Review: `docs/review/owner-5.md`.
<!-- /owner-5 -->

<!-- site 404 -->
## 2026-10-19: the 404 page

- **A new 404 page:** the owner's picture above the words, "4", the open box as the "0", "4", with the lid hovering
  and a lime "?" rising out of the box. On the void in dark mode, on an ink card in light mode. The words are new:
  "We can't see inside your files. Or, apparently, this page." and "Maybe the address has a typo, or the link
  expired. Ask whoever sent it for a fresh one." One button, Go home; Open my drive left the page. Still a 404, still
  noindex, and the page itself is never cached.
- **The picture** is AVIF and WebP at three widths (6.6 KB for a computer's screen), under `/site/media/` like the
  home's stills. No new script on other pages.
- **Three easter eggs**, for whoever looks: a line that shows only when you select the page, a comment in the source,
  and a note in the browser's console with a ghost by Donovan Baker (asciiart.eu). Review: `docs/review/site-404.md`.
<!-- /site 404 -->

<!-- upload safety 1 -->
## 2026-10-19: uploads are inert

- **Nothing anyone uploads can run on the server.** The server never decodes, unpacks, sniffs or runs a stored
  file, and a test now keeps decoders and process launchers out of the API. The data directory is mounted
  `noexec,nosuid,nodev` (`srv-mutis-data.mount`), so the kernel refuses to execute anything stored there, even for
  root; nothing a service can write is executable in its own view either, and each directory level under `blobs/`
  is `0700` whatever the umask (one level was `2770`, though no other user could reach it).
- **Stored bytes reach a browser only as a download.** Every API answer carries a sandboxed content security policy
  on top of `application/octet-stream`, `attachment` and `nosniff`; `tests/e2e/test_stored_bytes.py` checks it in
  Chromium.
- **The server:** Caddy now runs in the same systemd sandbox as the API, with only the right to bind ports 80 and
  443 (exposure 8.8 to 1.5); every mutis unit gained the API's hardening; walletd can't see the visitors' data;
  kernel settings in `/etc/sysctl.d/90-mutis.conf`; SSH takes keys only even if a file goes away; `provision.sh`
  keeps a copy of every file it replaces and the privilege check grew from 34 checks to 85. Review:
  `docs/review/upload-safety-1.md`; the threat model has a new section, "Uploads are inert".
<!-- /upload safety 1 -->

<!-- brand kit 1 -->
## 2026-10-19: the brand kit

- **The open box is the kit's:** one filled outline with soft ends on the side walls, in place of three strokes. It is
  the tile in every header, the comparison's hidebox column, the drive's brand tile and empty drive, Delivered and the
  other done moments, the favicon and the app icons. On the ink tile in both themes, in the kit's own lime, `#ACFF00`
  (the owner's call; the site's lime, `#BCFE00`, stays everywhere else).
- **The name is a wordmark:** "hidebox" in the kit's outlined letters ("hide" light, "box" bold, a lime rhombus over
  the i) beside the tile in the site's header, the drive's sidebar, its start screen, a folder link's top bar, the
  comparison's head, the shared-link card, the holding page and the film's end card. Its letters take the text colour;
  the rhombus stays lime in both themes. Screen readers still hear "hidebox". Body text still says hidebox in words.
- **Icons:** the favicons and app icons are the kit's own files, `favicon.ico` holds 16, 32 and 48 px
  (each page's link to it now says so), and the manifest gains a maskable icon (`icon-maskable-512.png`). `og.png` is
  unchanged. The README opens on the kit's lockup, with new pictures of the home, the drive and the share window, and
  a new social card. Review: `docs/review/brand-kit-1.md`.
<!-- /brand kit 1 -->

<!-- seo pass 1 -->
## 2026-10-19: the SEO pass

- **Search results and link previews**: every page's title says what it is for and ends with the name, every
  description is its own, and each page carries the full Open Graph and Twitter card (the share card, its size and
  alt text), a canonical on hidebox.app, robots that allow a large image preview and every icon. The home describes
  the app in JSON-LD (free, any browser, no rating), the other pages their place under the home, and the home's
  pictures say what they show. Shared links, drop links and the drive preview with a card that names no file.
- **Caddy** keeps the share cards and icons a day and lets other products show them; `robots.txt` and the sitemap
  (now with each page's date) carry their types; the API and the drive's files are never indexed. The bots that draw
  a pasted link's card may now read a shared link's page, so those links get their card too. No analytics, no
  tracker, no outside service, and the content security policy is unchanged. The share cards keep their names; the
  brand pass will draw them again. `tools/check-seo.py` checks all of it from outside. Review:
  `docs/review/seo-1.md`.
<!-- /seo pass 1 -->

<!-- history rewrite -->
## 2026-10-19: the history rewrite

- **The repository's history no longer names the operator's machines, login or home paths.** The launch-hygiene
  pass had taken them out of the tree; this pass runs the same substitutions over every commit (`git filter-repo`),
  so the past reads "the server", "the workstation", "operator", `<repo>` and `$TMPDIR` where it named them.
  Every commit id changed; the tree of the release did not. Ids quoted in earlier entries, reviews and evidence logs
  are from the previous history. Review: `docs/review/launch-hygiene.md`.
<!-- /history rewrite -->

<!-- copy pass 1 -->
## 2026-10-18: the copy pass

- **The home's headline** is "Your private cloud storage." with "Files lock in your browser first." under it, in
  place of "Privacy isn't an option. It's the default." The share card, the drive page's description, the README's
  title and the film's end card say the same.
- **Each key statement is said once a page**, in its best place (DESIGN.md, the Say It Once rule): the home no longer
  repeats the lock, the chain record, the chain's hidden amount, "No email, no password" or the testnet line, and
  /how, /judges and the README follow the same rule. The docs had a humanizer pass and name Tari™ on first mention.
- **The drive's words:** errors say what to do and lose "Oops", buttons start with a verb, an empty search says how
  to clear it, and "room" is "space" everywhere. The live site is <https://hidebox.app>. Review:
  `docs/review/copy-1.md`.
<!-- /copy pass 1 -->

<!-- twelfth pass, the v3 design is the home -->
## 2026-10-18: the twelfth pass (the v3 design becomes the home)

- **The home is the v3 design**, as the owner approved it: dark first, the words beside the open box with the files
  rising out of it, a still beside What's different from a usual drive?, Who sees what and Tari does the private
  parts, and the open box again over the closing. The words, buttons, links and the anonymous widget are the home's
  as they were; the light switch still turns the lights on. The moving grid behind the hero and the pixel field behind
  the closing are gone with it (two scripts fewer).
- **One mark:** the open box, lime on ink, is the tile in every page's header, the comparison's hidebox column, the
  drive's brand tile and empty drive, the favicon (`/favicon.svg`, and a 32 px PNG), the app icons and both share
  cards; the share card (`og.png`) is the home's first screen with its still.
- **`/v3` answers 301 to `/`**; `/v2` (the loops) stays where it was, noindex and linked from nowhere. Review:
  `docs/review/promote-v3.md`.
<!-- /twelfth pass, the v3 design is the home -->

<!-- under the hood as docs -->
## 2026-10-18: Under the hood reads as docs

- **`/made`, shorter and easier to scan**, at the owner's request: the page sits on the second surface with each part
  a card, a sticky contents on the left from 1024px (four groups that fold, the part being read on the lime tint) and a
  breadcrumb under the header that names it; on phones the contents are a closed On this page. Long detail (the
  cryptography, the threat table, every party fact by fact, how free space and paid space work, how SealLog and
  payment checks work, the ways to check us, the logs, how it was built) waits in accordions, and What we can't hide
  is eleven numbered rows that open. At 1280 × 800 on the test server, scrolled through so the live parts have loaded: 14,609 px
  before, 9,163 after (its defaults; 16,144 and 9,949 with every feature on).
- No word, claim or anchor is gone: `/made#locks`, `#limits`, `#check`, `#who`, `#disclosure` and the rest still land,
  and a link into a closed accordion opens it. Without JavaScript the contents are plain links. `llms-full.txt` follows.
<!-- /under the hood as docs -->

<!-- repository front page -->
## 2026-10-18: the README, shorter (docs only)

- **The README** is now a short tour: the mark and the one-line pitch, the home and two screens of the drive,
  Try it in 2 minutes, one diagram of who sees what (`docs/media/how-it-works.svg`), the exit rules, what the
  server never sees, Run it yourself, the architecture in five lines, status and roadmap.
- **Nothing was dropped:** the long parts moved to `docs/` (`tari.md`, `privacy.md`, `verify.md`, the repository
  table in `architecture.md`), with an index at `docs/README.md`. New: `CONTRIBUTING.md`, and
  `docs/media/social-preview.png` for the repository's social card. `SECURITY.md`, `NOTICE`, `docs/api.md`,
  `docs/self-host.md` and `docs/threat-model.md` use the name hidebox. No code, page or deployment changed.
<!-- /repository front page -->

<!-- eleventh pass, home v3 -->
## 2026-10-18: the eleventh pass (home v3, a preview at /v3)

- **The home with stills**, at `/v3` only: `/v2`'s page, words, buttons and widget, with a picture in place of every
  loop. The hero and the closing show the open box with the files rising out of it; What's different from a usual
  drive? shows a file locked in the browser, leaving still locked, and the server; Who sees what shows one file's four
  sides; Tari does the private parts shows the file and its key going through Tari's gem and coming out locked. No
  video on the page: it weighs about a quarter of a megabyte after a full scroll.
- **The open box** is the mark in `/v3`'s header and its favicon, lime on ink. The home, the sitemap, the JSON-LD
  and every other page are as they were. Its own budget (V-02) is checked by the site suite. Review:
  `docs/review/home-v3.md`.
<!-- /eleventh pass, home v3 -->

<!-- tenth pass, home v2 -->
## 2026-10-17: the tenth pass (home v2, a preview at /v2)

- **The home with the product loops**, at `/v2` only: the same words, buttons and widget as the home, dark first, in
  the treatment of mega.io's product pages. Four short loops (a VP9 WebM with alpha each, an H.264 MP4 for Safari,
  a still poster) sit beside the hero, What's different from a usual drive?, Who sees what and Tari does the
  private parts, and over the closing. Each is asked for only as it comes near and plays only while on screen;
  with reduced motion only its still shows.
- `/v2` is noindex and linked from nowhere: the home, the sitemap, the JSON-LD and every other page are as they
  were. Its own budget (V-01) is checked by the site suite. Review: `docs/review/home-v2.md`.
<!-- /tenth pass, home v2 -->

<!-- ninth pass, site v4 -->
## 2026-10-17: the ninth pass (site v4: the owner's four changes)

- **The drive shows what to do next:** the one primary of each view is Tari's lime under the ink label, the
  home's Open your drive style (Upload a folder on the empty drive, New once there are files, Share when one file
  is picked, the share dialog's Next, Make link and Copy link, Make my drive, Save key file, each dialog's
  confirm, Get space, the pay page's Pay with test money and Open it, the folder viewer's open). Everything else
  stays neutral, destructive stays red (Delete it after too), picked rows sit on the lime tint.
- **The comparison** sets hidebox beside one column, "A popular cloud drive", on computers and phones.
- **The headline:** "Your private cloud storage. Privacy isn't an option. It's the default." "Drive" stays the
  product's noun everywhere else. The meta, Open Graph and JSON-LD descriptions, the share card (`og.png`) and
  the film follow it.
- **One sentence a line** in every paragraph, lede, step, card, table cell, dialog and empty state with two or
  more sentences, on every page and in the app (`web/app/ui/lines.js`). Review: docs/review/site-v4.md (pruned on 2026-10-20).
<!-- /ninth pass, site v4 -->

<!-- eighth pass, site v3 -->
## 2026-10-17: the eighth pass (site v3: the owner's six changes)

- **One action:** Open your drive in the header (always on, never stepping aside), the hero and the closing; it
  makes a drive in a browser without one (`/drive?make`) and opens the one this browser has. /judges and /how
  use the new label; the drive app keeps its own words.
- **Tari's lime** (`#BCFE00`, the owner's copy of the Tari brand kit) replaces Sea as the action colour: a
  `#0A0A0A` label at 16.32:1, a lime-700 edge on light pages, olive brand text on light, lime text on dark.
- **Motion** (`web/site/js/motion.js`, after the load event): the template's kinds of motion on the home, /how
  and /judges (reveals as things scroll in, word blur-in, the hero's arrival, a progress line on /how) and the
  hero picture's decode from hex noise. Reduced motion and no JavaScript show everything at once.
- **Pixel field** (`web/site/js/pixel.js`): a WebGL2 port of PixelBlast's idea in the lime, behind the home's
  closing. A-06h covers both modules. Review: `docs/review/site-v3.md`.
<!-- /eighth pass, site v3 -->

<!-- sixth pass, anti-griefing -->
## 2026-10-14: the sixth pass (anti-griefing: the space)

- **Packs:** a judges' slice (30 %) of the paid cap that public buyers can't take, with judges spilling into
  the public slice; open invoices hold their bytes until they expire; one pack per drive, renewable with the
  same pack in its last 3 days (days stack, bytes don't); the big pack is 5 GiB for 1 tTARI.
- **Sales brakes:** 1 pack a UTC day per /64 or IPv4 address (2 with a judge pass), in memory; 3 public packs
  a day for the deployment and 10 with judge passes, counted from the invoices. 429 `packs_limited`.
- **Free-space brakes**, a UTC day per network, in memory: 5 new drives per /64 (20 per /48), 2 GiB of uploads
  to free drives per /64 (6 GiB per /48; 8 GiB with a judge pass). 429 `drives_limited`, `uploads_limited`.
- **Visible and stoppable:** `/status.json` amber on `packs.public_80` and `packs.ceiling`; `/api/v1/stats`
  `packs_sold_public`, `packs_cap_public`; `mutis-admin feature packs off` (Storage says "Space packs are
  paused."), `mutis-admin packs`. Schema 6 (`invoices.judge`, `identities.paid_pack`, `paid_judge`).
- **Docs:** the threat model's "Griefing the space", the runbook's "If someone games the packs", claims
  C48 and C49. Evidence: `docs/evidence/2026-10-14/anti-grief/`.
<!-- /sixth pass, anti-griefing -->

<!-- fifth pass, release -->
## 2026-10-14: the fifth pass (the devil's judge run on the drive) and the release

- **No ghost anywhere:** the link and task pages (`/s/`, `/t`, `/p/`, `/send`, `/watch`, `/verify`, `/d/`)
  draw a Lucide tile instead, in Geist with shadcn buttons; the ghost's partials and `ghost.css` are gone and
  the site checks fail if a page shows it again.
- **C42 for kept files:** a link that ends on a file its owner keeps says "The file stays with its owner",
  with no chain line (`GET /s/{id}/exit` answers `receipt: "none"`).
- **Track two, step 5:** Received → Payments refreshes while the drive is open and lists each payment with its
  file, Test money, Checked and the tx (`GET /me/sales` `paid`), on any device.
- **Track one, step 5:** Activity shows Opened before It left your drive (gone rows carry `opens`).
- **Mediums:** previews and app strings say drive (never locker); the key file is `hidebox-key-…`; the pay
  page on phones; Trash names at 390; "In a shared folder"; day one's space line; test money capped per
  selling drive; Make my drive counts down and retries, and a judge pass lifts its network limit; C11's short
  form; `mutis.sh` out of `memo_origins`. Every verdict: `docs/review/fix-log.md`, "Fifth pass".
- **Film:** `tools/film.py` records §10's two tracks.
- **Repository:** renamed `c7b/mutis` → `c7b/hidebox` (GitHub redirects the old URL); `repo_url`, the
  README, `SECURITY.md`, the self-host guide and the advisory check follow.
- **Later fixes in the pass:** Received names each payment's file (it didn't load the drive's index); a folder's
  menu no longer reads "null" where a file's entries go; Activity orders an hour's events from last to first;
  `/judges` step 4 quotes "This link has ended.".
- **Released:** tag `spooky-secrets-2026-10` on `c73c7b4`, live as `c73c7b415ecd…-cbb8c1e8a`; verify-deploy 0
  differences; E-J and the non-chain batch green on it; E-30 and E-13 wait for the evidence slice's next day.
  Evidence: `docs/evidence/2026-10-14/release/`.
<!-- /fifth pass, release -->

<!-- integration, pass 2 -->
## 2026-10-14: pay to open in production with test money (research 16-drive-design §15 step 17, milestone M2)

- **Merged** lane S (step 14, the server: sales address, paid links, `/p` routes, claims, the open gate,
  `verify_sales`, the release gate; migration 005), lane A1 (step 11's reading pages, cards, README) and lane
  A2 (steps 15 and 16, the client: the seller's dialog, the buyer page, the owner check) without conflicts;
  every suite green on the merged tree (server 306, site 29, UI 628, app 9 steps, deploy).
- **E2E** (step 17): new E-29 (a drive sells a folder; a phone with no drive pays with test money; three
  names, one opens; a second stranger gets 402) and E-30 (a second drive pays from its own wallet, waits for
  the owner's check, opens); E-J's track two follows §10 when `features.pay_to_open` is on (a pay link, test
  money, Received, What the chain sees). The dev stack can't stand in for E-29: its fake keys aren't curve
  points, so the browser can't seal to its watch address (tests/e2e/README.md).
- **What the chain sees for test money:** the claim's poll carries `tx_id` once our demo wallet has sent it
  (the finished job keeps the claim's ref; its payload is scrubbed), and the buyer page links it.
  `/judges` track two steps 5 and 6 and `/made#pay` say where the tx is.
- **Home:** the widget's result is one column inside the card, so the code to scan no longer covers the
  words at 1440.
- **Production:** `features.pay_to_open = true`.
<!-- /integration, pass 2 -->

<!-- lane app1, round 3 -->
## 2026-10-14: the reading pages, the cards and the README in the drive's clothes (16-drive-design §10, §11)

- **How it works**: five stills of the real interface (make your drive, drop your files, share it your way,
  Tari does the private parts, see what happened), drawn inert from the drive's parts so they follow the
  theme; who sees what; no mascot, no animation (`js/how.js` is gone).
- **How it was made** in the §11 outline: the short version, your key is the account, the locks, folders and
  their keys, `#pay` (the §4 trust sentence, its limits, the next step; switched-off wording while
  `features.pay_to_open` is off), Send by Tari, `#who` (C40, C41, C35), space and when files go (C45, C46, C47,
  Delete it after), receipts on the Tari chain (C42; none for a link that ends on a kept file), the Tari map,
  check us, what we can't hide (C5-snap, C6, C20), how it was built and tested (the R1 fix, on a fake chain).
  Every old anchor still lands. The trust sentence is registered as C33-t.
- **For judges**: the two six-step tracks of §10 (track two is pay to open when it is on, else Send by Tari and
  Get more space) and a What to check table, claim by claim; the judge pass field stays.
- **The fine print and 404** in drive words (the deletion terms carry C45 to C47).
- **Geist** sets the reading pages (the pinned file); the home keeps the system faces (A-06).
- **OG cards, app icons and favicon** redrawn: the brand tile and a slice of a drive with its rule badges;
  `render-images.py` hands each card Geist and the brand. **llms.txt** describes the drive; **robots.txt** keeps
  `/drive` and `/p/` out. **README**: the first screen (title, one paragraph, Try it, the Tari table).
- **Drive polish**: the header's actions sit at the right edge; a finished upload row drops its full bar; the
  search field reads as a field.
<!-- /lane app1, round 3 -->

<!-- integration, pass 1 -->
## 2026-10-13: the drive replaces the locker (research 16-drive-design §15 steps 11 to 13, milestone M1)

- **Merged** lanes S (steps 1, 2, 4, 6), A1 (3, 5, 7, 9) and A2 (8, 10) without conflicts; every suite green
  on the merged tree (server 257, site 29, UI 637, app 9 steps, deploy).
- **Home** (§11): "Your private drive." with Make my drive (`/drive?make`) and Open my drive (`/drive?open`)
  beside an inert slice of a drive with its rule badges; **Just share one thing** keeps the anonymous widget
  (its ids and A-06 unchanged; no Geist or drive code on `/`); Share it your way; Tari does the private
  parts (the pay rows only when `features.pay_to_open` is on). The widget takes a scanned `/#to=` address
  without the old figure, so the drive's address code still opens a send on a phone.
- **The name** is hidebox (`BRAND` in tools/build.py and web/app/lib/i18n.js); the internal codename stays.
- **The site and the older app pages** read the drive's neutral palette through `/shared/tokens.css`
  (no growth in the widget's bytes); the header is the name, three pages and the light switch.
- **Routes** (§12): `/locker` → `/drive`, `/inbox` → `/drive/received`, `/upgrade` → `/drive/storage#more`
  (301, in the Caddyfile and `tests/e2e/headers_spec.py`); `/send`, `/watch`, `/verify`, `/d/*`, `/s/*`
  and `/t` unchanged.
- **/judges** follows the drive: six steps on a computer and a phone, then four for the Tari part.
- **E2E** (step 12): E-08 moved to the drive; new E-26 (a folder and its restore), E-27 (a folder link,
  Once, zip), E-28 (move into and out of a shared folder; 403 mid-visit), E-31 (opens per hour; no IP,
  user agent or name in the database or backups); E-03, E-18, E-19, E-22, E-24 updated; the chain
  scenarios and E-J read Received, Settings and Storage.
- **Copy** (step 13): `tools/check-copy.py` knows C32 to C47 and bans the two retired sentences.
<!-- /integration, pass 1 -->

<!-- lane S, step 14 -->
## 2026-10-14: pay to open, the server (research 16-drive-design §4, §15 step 14), behind `features.pay_to_open`

- **Sales address:** `PUT /me/sales` registers the drive's sales address and its view key sealed (kind 3,
  flag `0x08`, bound to the address) to the payment checker; the chain worker opens it in memory only
  (new sidecar op `openWatchKey`, with an offline round trip in `selftest`) and marks the seller `ok` or
  `bad_key`. `GET /me/sales` lists paid claims waiting for the drive's ownership check.
- **Paid links:** `mode: "pay"` on a drive's kept file or folder (a price from `/config`, our half of the
  key, an encrypted preview); one per item; `PATCH /s/{id} {paused}`; `manage` and `/me/items` show counts
  and earnings, never who paid.
- **Buyers:** `GET /p/{id}` (never the seller's address), `POST /p/{id}/claims` (PoW purpose `claim`, code
  9; caps per link and in all), `GET /p/{id}/claims/{cid}` with `X-Mutis-Claim`, and test money for a claim
  (`…/demo-pay`; the worker re-checks claim, seller, address and amount for `clm_` references).
- **The open gate:** a paid link opens, peeks and serves its bytes only with a released claim with opens
  left in its window (402 `payment_required`, 403 `bad_claim`, 410 `claim_used`); each open spends one.
- **verify_sales:** sellers with a waiting claim, 50 a tick, scanned from the claim's mirror position;
  only outputs that pay one of that seller's claims are recorded; counted once an indexer commits them;
  short payments, top-ups within the grace, extras. The pack credit freeze doesn't stop sales.
- **The release gate:** test money our demo wallet built for the whole price releases at `paid`; any
  other payment waits at `owner_check = 'pending'` until `POST /me/sales/claims/{cid}/confirm` from the
  owner's drive, one call per output (`{utxo_id, spendable}`; migration 005 adds `sale_payments.owner_ok`):
  every counted output spendable releases, one that isn't voids. Ending a link erases `server_half` and
  voids waiting claims.
- **Docs:** api.md (routes, `X-Mutis-Claim`, fragment kind 5, a "Pay to open" paragraph), threat-model.md
  (five rows and a "Pay to open" paragraph), architecture.md (who sees what, the life of a file, the Tari
  parts). Tests on the fake chain only: `test_paid_shares.py`, `test_sales_worker.py`, `test_release_gate.py`.
<!-- /lane S, step 14 -->

<!-- lane S -->
## 2026-10-13: the drive's server, steps 1, 2, 4 and 6 (research 16-drive-design §15)

- Schema 4 (`migrations/004_drive.sql`, additive): folders, the Trash, folder tickets, opens per hour and
  the pay-to-open tables. `/config` publishes the drive's numbers (`folders`, `items`, `send`,
  `pay_to_open`, `retention.trash_days`, `links_per_item`); `features.folders` and
  `features.pay_to_open` are off until the drive's routes ship.
- R1, a bug in production, fixed: a pack payment now counts only if its one-time key is the one our
  receiver's owner key derives (`oneTimeKey` in the sidecar). Before, an output that opened with our view
  key credited a pack even when the payer kept the key to spend it. Tested on the fake chain and with an
  offline known-answer pair made with the real library; never with forged outputs on the testnet.
- Folders (`POST /folders`), moves, renames, the Trash (30 days; links end when an item goes in) and
  Delete it after (`PATCH /items/{id}`); deleting a folder deletes what it holds, each file with its exit
  receipt; `/me/items` lists one folder, the Trash, and what left the drive in the last 30 days; the
  lapse of extra space deletes trashed files first.
- Folder links open the whole folder as one visit with a folder ticket that serves only files still
  inside; `then_delete` makes a file leave with its link; every open is counted per link per UTC hour
  (never who opened it), shown to the owner.
<!-- /lane S -->

<!-- lane app1 -->
## 2026-10-13: the drive's app, steps 3, 5, 7 and 9 (research 16-drive-design §15)

- The shadcn/ui (new-york) port in `web/shared/ui/` (tokens, components, the Lucide sprite) and
  `web/app/ui/behaviors.js`, with Geist self-hosted (`web/shared/fonts/geist/`, OFL) and pinned by its
  hash; the font test now asks for Geist only on `/drive`.
- `/drive` (`app/drive.html`): the shell (sidebar, search in this browser, Upgrade, theme), Make my drive
  (the key at once, the Ootle keys made only when something needs them) and Open my drive (key file or
  pasted key), folders with breadcrumbs, the storage meter with Get more space (today's packs and invoice,
  restyled), and the empty drive with its Tari address.
- Uploads of files and folders (the picker and dropped folders, every batch read), Move (with "This
  shares it too."), Rename, the Trash with Undo and Bring back, and Delete it after… with its Leaves badge.
- Activity per file and for the whole drive (opens per hour, links made and ended, files that left with
  their exit receipt from `/seallog/proof/{id}?kind=exit`), and What our server knows. Folders, the Trash
  and Delete it after stay behind `features.folders`.
<!-- /lane app1 -->

<!-- lane app2 -->
## 2026-10-14: pay to open, the client, steps 15 and 16 (research 16-drive-design §4, §15), behind `features.pay_to_open`

- Sell: the share dialog's "Someone who pays you" (when /config offers it and the item has no paid link
  yet): a price chip from `pay_to_open.prices_ut`, "Show the name before they pay" (on), the sales view
  key notice the first time a drive sells (C35), then Make pay link. The browser derives the drive's
  sales keys, seals the sales view key to our payment checker once per drive (`PUT /me/sales`), splits
  the link's key (`sA` after the `#` as fragment kind 5, `sB` to our server, `s = HKDF(sA ‖ sB)`), seals
  the teaser with a key from `sA`, and shows `/p/<id>#5…` with C34 and its boundary. Rows say Getting
  ready, then Pay {price} tTARI with "{n} paid"; the Links tab has Stop selling and Sell again.
- The buyer page `/p/<id>` (view.html; Caddy, the dev server and robots.txt route it): the teaser
  (folder or file, the name if allowed, the count, a size bucket), the price and the public fee, what you
  get (C39), no take-backs (C37), one primary Pay with test money; Pay from my drive only when a drive
  in this browser has the money (its wallet pays the claim address, memo = the claim id); Another Ootle
  wallet shows the address made for the claim only after the claim exists. The steps follow the claim
  (waiting, seen with its amount checked, on the chain, the owner's drive check for any payment our
  demo wallet didn't build, C38, ready to open); the claim's token stays in this browser, so a reload
  resumes; unlocked: Open it (both headers), "{n} opens left until {date}", a folder's visit.
- The owner check (R1, the release gate): each time a selling drive opens, it walks the chain mirror
  with its sales view key, compares each sales output's one-time key on the indexer with the one its
  sales owner key derives (`oneTimeKey`, as the sidecar does), and confirms the claim (or voids it:
  "The payer kept control of this payment") with `POST /me/sales/claims/{cid}/confirm`. Received lists
  the payments with their check.
- Tests: UI flows share-pay, pay-page-states, owner-check (the pay routes faked in the annex's shapes in
  front of the dev server until the server lane's step 14 merges); lib KATs `pay.test.js` with
  `vectors/pay-v1.json`, checked again by `crosscheck.py`.

## 2026-10-13: the drive's sharing, the folder viewer and Received, steps 8 and 10 (research 16-drive-design §15)

- The share dialog on files and folders: one question per step. Anyone with the link: Once, A few times
  or No limit, a defaulted "It ends" (Tomorrow, In a week, When I stop it from a drive's second day), a
  secret word, and on files "Delete it from my drive after" (`then_delete`). One Tari address: the
  address, its safety code, "They use another Ootle wallet" (kind 4) and who sends it (relay or this
  browser, C8). The result says the rule in one sentence, with Copy, a code to scan on computers and
  Share on phones. A file with links opens on New link and Links (Copy again from the browser that made
  it, Stop this link). The row menu's Copy a once link is one tap. Rows wear Sent by Tari for links this
  browser sent.
- A folder link opens in the drive's look as one visit with a countdown: names opened in the browser,
  breadcrumbs, a preview, Save one, and Download all as a ZIP built in the browser (`lib/zip.js`, stored,
  CRC-32, checked with Python's `zipfile`) up to `folders.zip_max_bytes` (on phones
  `folders.zip_max_bytes_phone`), else one by one.
- Received: what came by Tari ("By Tari, sender hidden") or to the drop link, found by this browser's
  scan; open it here and Save to my drive (locked again as the drive's own); the drop link with Copy;
  purchases kept on this device; when the chain can't be reached, it says so and keeps what it found.
<!-- /lane app2 -->

## 2026-10-13: Ootle v0.46.0 (docs/evidence/2026-10-13/upgrade-0.46.0/, pruned on 2026-10-20)

- walletd 0.46.0 (`tari_ootle_walletd-0.46.0-cc8a83b-linux-x86_64`, SHA-256 `26d4c269…6e05`) runs on
  the server since 18:14 UTC, after Esmeralda's indexers moved to v0.46.0 at about 10:30 and walletd
  0.45.0 could no longer read a transaction result (docs/evidence/2026-10-13/incident-walletd/, pruned on 2026-10-20). The
  store took one additive migration; balances are unchanged; the 0.45.0 binary and a pre-upgrade tar
  are kept for a rollback. Checkpoints commit again (#159 on), and #141 to #158, which reached the log
  while walletd couldn't tell, are recorded committed after a check against the log's state on both
  indexers. The three releases missing from `/releases.json` are notarized.
- Not fixed: the sponsor's whole balance (8,851.452 tTARI) is the change of a send whose result the
  network stopped serving before the upgrade, so walletd keeps it locked and every sponsor send
  (grants, courier canaries, decoys, the evidence payment) still fails with "Available: 0". walletd
  0.46.0 has no way to settle or rescan it; the owner decides the remedy (the evidence README).
- ootle-wasm 0.46.0 vendored for the browser and the sidecar (integrity and provenance checked; only
  the `.wasm` differs from 0.45.0, the JavaScript and types are the same files) with the core, sidecar,
  server, deploy, site and UI suites passing; production still serves 0.45.0 until the chain scenarios
  can run (they need a sponsor that can spend). The live gates G1 and G2c pass on the V2 chain with
  both libraries.
- Self-hosting guide, architecture and the upgrade drill name walletd 0.46.0; the drill says to
  upgrade before pending results age out (about one or two epochs).

## 2026-10-13: the repository is public (docs/review/fix-log.md, "The public step, done")

- `c7b/mutis` is public, recreated from the rewritten history: the commits from before the rewrite
  are not served there. It passed a secrets gate first (every commit and blob as GitHub serves it, and
  the server's secrets checked on the server); description, homepage, topics and private
  vulnerability reporting are set.
- `security.txt` lists GitHub's private advisory form as the second contact, after the dead drop; the
  site suite checks, signed out, that the form answers and that private reporting is on.
- Deployed as `6fa84fd`. A stranger's clone runs `verify-deploy` (0 differences) and the server suite,
  and every link on the live site answers 200, the GitHub links included.

## 2026-10-13: the function review's fixes (docs/review/fix-log.md, "The function review")

- Packs: `mutis-admin release-pack -- <locker id>` ends a pack; E-13 and E-J end theirs, and the 11
  test packs that had filled the paid-space cap (so `/upgrade` said sold out to everyone) were ended.
- Sponsor grants: asked for whenever the browser wallet is short of the next spend, at most once a
  UTC day per locker (once more after a judge pass is saved); a refusal is said on the send line, and
  `/upgrade` in direct mode offers the demo payment when the wallet is short.
- `/watch` treats an invalid view key as a key error; the expired page names its UTC day; a replaced
  link no longer says its file was deleted; the scan bench no longer starves the test driver.
- `/judges` B3, B5, B6 and B7, `/pricing`, the architecture, the threat model and the self-hosting
  guide (walletd 0.45.0's asset and SHA-256) corrected; expiry rounding stated exactly everywhere.
- The repository stays private: GitHub still serves the commits from before the history rewrite.

## 2026-10-12: English only, and the architecture leftovers (docs/review/fix-log.md, "Third pass")

- Spanish removed by the owner's decision: the site and the app are English only. The `/es/` pages,
  the Spanish partials, dictionaries, exit-wall words and Open Graph card, the hreflang links, the
  EN · ES switch and the translation offer are gone, and any path under `/es/` answers 404. All of
  it is restorable from the git history (the commits before `ba883ab`).
- App: one dictionary (`i18n/en.json`) with en-US formats; no stored language and no language
  script before first paint.
- Self-hosting: `provision.sh` now creates the `drive` and `build` accounts, takes the operator from
  the sudo login instead of a fixed account, adds every loopback guard (walletd's included) and skips
  walletd until it is set up; `docs/self-host.md` walks a new server through every step, walletd's
  first start included, and was followed from a clean clone (dry where it would touch a server).
- Docs: what an API restart forgets (the in-memory rate limits and daily per-network caps, keyed by a
  day key that is never written) and what it keeps (the daily budgets, in SQLite), in
  `docs/architecture.md` and `deploy/README.md`; test counts in the READMEs match this pass's runs.
- Operations: the walletd journal's resubmit error every 5 s is one stored dry run of the 2026-10-11
  template publish (harmless; `publish-template.sh` says so). E-20 waits for the live region instead of
  reading it the moment the link shows.
- Released as `abc5d71…-cc6fca59c` (verify-deploy: 0 differences across 129 files); E-J in direct mode
  and every scenario without chain transactions pass against production (`docs/evidence/2026-10-12/english/`).

## 2026-10-12: second pass, after the security, anti-slop, SEO and docs reviews (docs/review/fix-log.md, "Second pass")

- History: an evidence log named the operator's own machine; the addresses were redacted and every
  commit rewritten so no blob carries them, and the lint now refuses any public address but the
  server's own. Key-shaped files are ignored by name wherever they land.
- Server: a submit goes out on the indexer client's own send lane, so a flood of reads from one
  network can't stall a browser's direct send; chain reads are limited per /48 as well as per /64,
  and an unknown transaction id (up to four upstream calls) has a small budget of its own. A
  proof-of-work challenge is bound to the network it was issued to and a solution can't trail the
  escalation by more than two bits, so a stockpile can't skip it. A link made without an expiry takes
  its file's own (an anonymous file's default was refused as too far away).
- Web server: pages and files answer 405 to any method but GET and HEAD; the privilege check wants no
  pnpm, yarn or pip either (Debian's nodejs ships corepack).
- App: the file's modification time stays out of the sealed metadata (for a photo it is close to the
  moment it was taken); numbers and dates format for Mexico and the US; an unknown app path shows the
  404 scene and a closed or unknown drop offers a way out; link previews for the viewer (the locked-file
  card) and the app pages; "recent links", "open count", and Spanish verbs and gender where they drifted.
- Site: the reference tables on `/how` and `/security` stack on phones instead of clipping; the home
  page's title, description, JSON-LD and `llms.txt` lead with Tari (and `llms.txt` keeps only the
  lines true for this deployment); a Spanish Open Graph card; `favicon.ico`; "locked to your locker"
  (not "sealed"), "checkpoint" in Spanish too, the measured "a minute or two" everywhere; the status
  page says what needs attention, in words, and only when a check isn't green; the pricing rules are
  headings; the abuse form's category starts unchosen; every FAQ answer has a stable id; the language
  offer follows the skip link; `robots.txt` lets crawlers read the public config and numbers, and a
  drop page carries its own noindex.
- Docs: `SECURITY.md`, `docs/architecture.md` (parts, users, trust boundaries, who sees what, the life
  of a file, the Tari parts), README's "How it's built".
- Payments: the hourly reconcile no longer freezes every pack on one round. A mismatch holds credits
  and is checked again five minutes later; a second one in a row freezes them as before. The
  indexers serve outputs unverified for about half a minute at some epoch changes, and one such
  round had frozen production for three hours. A 404 that isn't the indexer's own JSON answer
  counts as "unknown".
- App: the locker's IndexedDB records load with the locker (`lib/idb.js`), so a first drop stays
  inside the widget's 40 KB budget.

## 2026-10-12: fix pass after the judge-run and claims reviews (docs/review/fix-log.md)

- Direct sends: the send screen says, before Send, whether this send goes from the browser's wallet or
  through our relay, and refreshes while you wait; the wallet is scanned before each decision, so a
  grant that has landed is found. Two sponsor grants a day per /64 (a phone and a computer on one
  network). The site's direct-mode sentences carry the condition (grant first, relay until then).
- `/judges` and `/pricing` name the button each send mode shows; `/judges` B1 has the computer open its
  locker early; a judge pass can be handed out as `/judges#pass=…` and is kept on the device for a week.
- Expiries at least an hour away are stored rounded up to the hour (an exact one gave the arrival second
  away); the ended-link body no longer carries the open count; copy on the link path, logs, SRI and
  invoice addresses made literally true; README describes both send modes.
- App: receipts on `/verify` say when the file was locked and where it went; inbox rows show when a
  delivery was found and whether it has made its exit; the header offers "My locker" once one exists;
  payment steps show the check in ink and lime only when the chain confirmed; app pages are one centred
  column on wide screens; the home page's indexer link follows the indexer that holds the receipt.
- The submit proxy (`POST /chain/ix/transactions`) takes a locker session and relays only a transaction
  shaped like the app's own send, read back from its BOR envelope (one stealth transfer paying its own
  fee of at most the courier fee, one output plus change, up to four inputs, no other instruction,
  12 KB at most): it is no relay for other Esmeralda transactions.
- The web server answers a request body declared over 5 MB with a 413 in the API's error shape (the
  app names the limit instead of "our server tripped"), and any other Host name with a 421 that
  carries the security headers, on both ports.
- Root's go-live and pre-migrate database copies under `/var/backups/mutis` are deleted at the
  published 7 days by the backup unit's first step; wallet tars, balance snapshots and config copies
  are never touched.
- Copy made literally true: the FAQ says the program rule lives in the app (our server can't see file
  types); the snapshot sentence says our host can keep weekly snapshots, that we haven't switched them
  off and haven't yet confirmed the retention in its panel.
- E2E: the harness keeps a judge pass where the app now reads it (`localStorage`, a week, as a
  `/judges#pass=` link saves it); E-13 in direct mode takes a one-use pass, as E-J does, so its
  buyer's locker gets the sponsor grant it pays from after the test network's two grants a day
  are spent.

## spooky-secrets-2026-10 (2026-10-11): first public release

Live at <https://srv2052606.hstgr.cloud> on the Esmeralda testnet.

- Files and text locked in the browser (AES-256-GCM, Padmé padding, 4 MB chunks), shared by link with
  the key after the `#`: once, a number of opens, an expiry, link + password or password only.
- Lockers made in the browser (no email): dead-drop links that deliver a file's key to the locker
  inside a stealth payment, sending to any Tari address, an inbox that scans the chain in the browser,
  a view-key page that sees deliveries and opens no file, packs paid in tTARI and credited after the
  official Tari library proves the amount.
- SealLog 2.0.0, published from this repository's exact bytes, with a checkpoint every 15 minutes:
  inclusion proofs for every stored file and every exit, checked by `/verify` against the component's
  state on the Ootle; each release's manifest hash notarized through it.
- An hourly canary sealed by our own code and delivered on chain, its key published a day later;
  `/evidence.json` lists our own test transactions; `/status` shows the health checks.
- Site in English and Spanish, the judges' guide at `/judges`, the threat model at `/security`.
- Go-live fixes: a fresh database is created group-writable for the API and the chain worker; the
  health check asks the verifier whether it runs; the UTXO mirror reads every indexer (one stopped
  advancing its stream while still answering).
