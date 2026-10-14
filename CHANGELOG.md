<!-- SPDX-License-Identifier: MIT -->
# Changelog

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

## 2026-10-13: Ootle v0.46.0 (docs/evidence/2026-10-13/upgrade-0.46.0/)

- walletd 0.46.0 (`tari_ootle_walletd-0.46.0-cc8a83b-linux-x86_64`, SHA-256 `26d4c269…6e05`) runs on
  the server since 18:14 UTC, after Esmeralda's indexers moved to v0.46.0 at about 10:30 and walletd
  0.45.0 could no longer read a transaction result (docs/evidence/2026-10-13/incident-walletd/). The
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
