<!-- SPDX-License-Identifier: MIT -->
# Changelog

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
  more sentences, on every page and in the app (`web/app/ui/lines.js`). Review: `docs/review/site-v4.md`.
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
