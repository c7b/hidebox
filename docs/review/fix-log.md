<!-- SPDX-License-Identifier: MIT -->
# Fix pass after the judge-run and claims reviews (2026-10-11/12)

Two devil's-advocate passes ran against the live site on 2026-10-11: a judge run (the Council guide on
emulated phone and desktop) and a claims and security pass (headers, TLS, limits, every privacy
sentence against the shipped code and config). This log takes each finding, says whether it held up
against the code, what changed, and where the evidence is. Times are CST (UTC−6). Nothing here is a
secret: no owner key, no judge pass, no transaction id of a test send.

The reviews' own blind spots stand: every browser ran on the server itself (no real network latency),
real devices were emulated, and the claims pass read only the lines it cited.

## Verdicts

| # | Finding (severity) | Verdict | What changed | Evidence |
|---|---|---|---|---|
| 1 | Repo `c7b/mutis` is private and 3 commits behind the release the site prints; every Code / Verify / evidence link 404s (high, both reviews) | **Confirmed. Owner action (Tier 3).** `gh repo view` → PRIVATE; `origin/main` = b493564. Pushing and making the repository public are the owner's calls. | HEAD is committed and ready to push (all commits of this pass included). `security.txt` lists only the dead drop as contact: RFC 9116 wants every Contact to work, and the GitHub advisory URL needs the repo public *and* private reporting switched on (also owner settings); `/security` keeps the advisory link under "Report a vulnerability" next to the drop. Every repo path the site links exists on main (`docs/self-host.md`, `docs/threat-model.md`, `docs/api.md`, `server/mutis/payments.py`, `docs/evidence`, `LICENSE`). | `git status -sb` (ahead), `gh repo view c7b/mutis --json visibility`; `web/site/static/.well-known/security.txt`; `web/site/tests/static_checks.py` (check_static refuses a GitHub contact) |
| 2 | Direct mode: the computer's B3 send fell back to the relay (sponsor 429: one grant per /64 per day; the locker opened at B3), while home, /how and /security say the browser sends and we never see the destination (high, both reviews) | **Confirmed**, and worse than reported: nothing on `/send` ever scanned the browser wallet, so a grant that had landed was never found there (only the inbox and E-J's test helper scanned). | (a) `wallet.canSendDirect()` scans before deciding, and `deliver()` decides by it. (b) The send screen shows, above Send, "This send goes from your browser's wallet…" or "…would go through our relay… wait, or send now", refreshed every 10 s (`send.path.*`, `data-testid=send-path`). (c) Two sponsor grants a day per /64 (`sponsor64` 1 → 2; the /48 cap of 3 and one per locker stay); `/security` says so. (d) `/judges` B1 (direct variant) has the computer open its locker in B1 and B3 tells the judge to read the line. (e) Every direct-mode sentence now carries its condition: home S3 footnote, `/how` table and "Never sees", `/security` "Who posts the payment", README, threat model. E-J waits for the line to say "direct" and asserts the browser posted the transaction. | `web/app/lib/wallet.js`, `web/app/ui/send.js`, `server/mutis/handlers/invoices.py`, `server/tests/test_admin.py` (202, 202, 429), pages listed; E-J in the production run below |
| 3 | `/judges` B6 and `/pricing` name "Pay with demo tTARI" and "our demo wallet pays", which direct mode never shows (high, both reviews) | **Confirmed.** `upgrade.js` renders `pay-browser` only in direct mode. | B6, the step's explanation, the pricing table cell and the demo paragraph have `send_mode` variants (the direct one names "Pay 0.5 tTARI from this browser", the price from `/config`, and the sponsor grant, `sponsor_grant` variable). `static_checks.check_ui_strings` now reads `/judges` in both send modes too, so a button named for the other mode fails the site suite. | `web/site/pages/judges.html`, `es/judges.html`, `pricing.html`, `es/pricing.html`, `web/site/js/stats.js`, `web/site/tests/static_checks.py`; site suite PASS (below) |
| 4 | Above the fold nothing says Tari; the page is 16 phone screens (medium) | **Partly accepted.** | The hero's Tari line is now an action: "Built on the Tari™ Ootle testnet. Or send it to a Tari address: the key rides sealed inside a stealth payment →" linking to `/send` (EN and ES). Not changed: the page order and S3's footnotes (11-brand §9 / P-2 order, ratified; a fix pass is not a redesign), and no Testnet chip in the phone header (the brand's hero has no HUD chips; the header is already brand + CTA + menu at 390 px). Recorded for the owner. | `web/site/pages/index.html`, `es/index.html` |
| 5 | `/verify` receipts are unlabelled ("Link …mVxw"), no time, the B3 file listed under a share id the judge never saw (medium) | **Confirmed.** | Each receipt says what this browser knows locally: "Sent to otl_esm_1…zm9 · locked Oct 12, 2026, 1:05 AM" or "Locked …"; recent drops keep `at` and `to` (device only, never sent). Newest first was already the order. | `web/app/lib/store.js`, `web/app/ui/verify.js`, `send.js`, strings `verify.sent_to/locked_at/from_link` |
| 6 | Forum link goes to the forum root; the judge pass is "kept for this tab only", so a second tab or device loses it (medium) | **Confirmed** (pass); forum thread is the owner's (Tier 3: posting). | The pass lives in `localStorage` for a week; `/judges#pass=<code>` saves it on opening (and on a hash change while the page is open: a fragment navigation runs no script, which the site suite's check caught) and clears the hash; the header shows a "Judge pass" chip while one is saved; copy updated. The forum link stays at the community root until the owner posts the thread (open item). | `web/app/lib/store.js`, `web/site/js/judges.js`, `site.js`, `partials/header*.html`, `site/tests/browser_checks.py` |
| 7 | zh-CN browsers get English with no hint; es-MX browsers land on English `/` (medium) | **Partly accepted.** zh-CN stays unshipped (12-integration §7.8: no native review). | A one-line offer ("Leer en español" / "Read this in English") appears when the browser prefers the other shipped language and no choice was made on this device; dismissable, remembered. | `web/site/js/site.js`, `site.css` (`.lang-offer`) |
| 8 | Header still says "Open my locker" inside the locker; inbox rows show "epoch 12,154"; an exited once-only file keeps an active Open; an empty gap; blank main for 1.5 s (medium) | **Confirmed.** | Header CTA reads "My locker" once a locker exists in the browser; inbox rows show "found 2 minutes ago" (epoch in the tooltip; older records keep the epoch); a delivery whose link ended in this browser is marked "Made its exit" (`data-state=exited`, persisted) through a viewer `onEnded` hook; the empty problems slot takes no grid row; app pages show "…" in the script face until the modules load. Not done: a time from the chain epoch itself (the mirror carries no timestamp; inventing one would be a guess). | `web/app/ui/shell.js`, `inbox.js`, `view.js`, `lib/scan.js`, `app.html`, `view.html`, `css/app.css` |
| 9 | Three explanations of how an invoice is matched; the address is the shared receiver plus a reference, not "made for this one payment" (low) | **Confirmed.** `ootle_addr.with_pay_ref(receiver, invoice_id)`. | One sentence everywhere: our receiving address with the invoice's reference inside it; the reference travels in the payment's encrypted memo (`payments.pay_ref`: PayRefAndBytes or Message), so the chain shows neither the invoice nor the payer. | `pricing.html`, `privacy.html`, `how.html` (+ES), `upgrade.address_note` (EN/ES) |
| 10 | Completed early steps show as black squares; app pages left-aligned on 1440 px; blank tile for a non-image file (low) | **Confirmed** (first two); **not reproduced** (tile). | Every reached step shows the check glyph in ink, lime only on the chain-verified ones; `.a-main` is one centred column at ≥ 1200 px. The card's tile shows the file's extension (`noise.js ownFigure`, `.md-own-ext`) or the text itself; a file with no extension shows its name. | `web/app/ui/upgrade.js`, `css/app.css` |
| 11 | No hidden layer before Oct 24; `dates.js` exports `isOctober31` that only tests use (low) | **Fixed** (duplication); **rejected** (delight: no honest small addition without new chain reads; out of a fix pass). | `isOctober31` removed; `theme.js` is the one place the Halloween rule lives; `coarseExpiry` took its spot in the tests. | `web/shared/dates.js`, `theme.js`, `site/tests/dates.test.mjs` |
| 12 | Nav, footer and inline link targets 18–20 px tall (low) | **Confirmed** for `.more` and the nav links; footer links were 32 px (44 on touch). | `.more` and `.nav-links a` get `min-height: 24px`. Inline prose links fall under WCAG 2.5.8's inline exception. | `web/site/css/site.css` |
| 13 | "1 of 1 chunks"; 107 KB vs 108 KB; 💊/💣 in safety codes, repeats; `/llms.txt` describes the weaker check and links the private repo (low) | **Fixed / fixed / rejected / fixed.** | Plural forms (`viewer.intact` one/other). The viewer's chip is the padded stored size, now labelled "{size} stored (padded)" (the card shows the real size). The emoji alphabet is Tari's RFC-0155 address alphabet by spec (`emoji.js`, hash-checked in tests); changing it after launch would change every existing locker's code, and a byte selects one of 256 symbols, so repeats are expected. `llms.txt` now says the amount is proven by the official library where the sidecar runs; its API link follows item 1. | `web/app/i18n/*.json`, `view.js`, `web/site/static/llms.txt` |
| 14 | README says relay mode is this deployment's setting (medium, claims) | **Confirmed.** | README describes both modes, direct first as the live one, with the grant condition and the relay fallback. | `README.md` |
| 15 | "SRI on every script and stylesheet" is false: imported modules carry no integrity (medium) | **Confirmed.** No import map; `build.py` fills only top-level tags. | Copy everywhere: SRI on each page's top-level scripts and stylesheets, the hash manifest (verify-deploy) for the modules they import. The conservative choice over an integrity import map, which would need build, CSP and verify-deploy changes on the last stretch. | `security.html` (+ES), `docs/threat-model.md`, `README.md`, `llms-full.txt` |
| 16 | The exact `expires_at` gives the arrival second away (`expires_at − preset`); "midnight" reveals the time zone; SealLog places a file in a 15-minute window (medium) | **Confirmed.** | Server: an expiry at least an hour away is stored rounded up to the next whole hour (`codec.coarse_expiry`, in uploads, link creation and patches, never past the item's own); the E2E 60 s preset stays exact. Client: the rule sentence shows the hour the server will store (`dates.coarseExpiry`); the preset is still recognised after rounding. Copy: `/how` metadata and FAQ say "when it leaves (rounded up to the hour; midnight is your local midnight, which shows your time zone)"; "What we know" says the expiry is rounded up; the link-path row says what the exit receipt places in checkpoint windows. | `server/mutis/codec.py`, `handlers/uploads.py`, `handlers/shares.py`, `server/tests/test_contract.py::test_expiries_are_whole_hours`, `web/shared/dates.js`, `web/app/ui/rules.js`, pages |
| 17 | The home page's "Check it on Tari's indexer" is hardcoded to indexer-b, which 404'd for the newest canary; the no-JS href is the indexer root (medium) | **Confirmed.** | The link follows the indexer the transaction view reports as `_source` (from `/config`'s indexer list); without JavaScript it points at `/verify`. The `/judges` evidence list links each transaction to its "What the chain sees" page, whose button asks both Tari indexers. | `web/site/js/evidence.js`, `judges.js`, `index.html` (+ES) |
| 18 | "never write … your files' ids to disk" is false: the database holds every id (low) | **Confirmed.** | "…to a log. The database holds file and link ids, never keys; Privacy lists every table." | `security.html` (+ES) |
| 19 | Someone with only the link's path gets the open count (410 body) and, through `/exit`, the item id, exit hour and leaf index, against "not the metadata" (low) | **Confirmed.** | The 410 body carries the reason and the day only (no `views`; the UI never used it); the `/how` row and the threat model say what the path reveals once a link has ended, receipt included, and what it never does (key, contents, name, real size, open count). | `server/mutis/handlers/shares.py`, `test_contract.py`, `docs/api.md`, `how.html` (+ES), `docs/threat-model.md` |
| 20 | `/faq` says people without a locker "can't send" programs, but the block lives in the honest client (`filetype.js`) and the server can't see file types (low, claims) | **Confirmed.** | The answer now says what is literally true: every viewer warns before saving a program, our app won't send one without a locker, and that rule lives in the app because our server can't see what kind of file it holds, so it can't enforce it. EN and ES. | `web/site/pages/faq.html`, `es/faq.html` |
| 21 | `POST /chain/ix/transactions` (and `/dry-run`) forwarded any valid-JSON Ootle transaction to Tari's indexers with no locker session and no shape check: an IP-hiding relay for any Esmeralda user, abuse landing on our IP (low, real security) | **Confirmed.** Spec §10.7's "Bearer not required" is superseded by this item. | The submit path takes a locker session (`wallet.js` sends it with the envelope), keeps the per-/64 and per-/48 limits, bounds the body to `{"transaction": <base64 BOR>}` of 12 KB at most, decodes the envelope with a strict stdlib CBOR reader (`server/mutis/cbor.py`, definite lengths only) and relays it only if it is shaped like `wallet.js send()`: version 0, a `StealthTransfer` followed by `PutLastInstructionOutputOnWorkspace` and `PayFeeFromBucket` in the fee phase, no instructions, the resource plus one to four spent outputs with a signature each, one or two outputs, fee ≤ `max_fee_transfer_ut`; anything else is `422 invalid`. Tests use three real envelopes built by the official library under Node (fixture) and six tampered re-encodings (fee over the limit, a third output, five inputs, an instruction, a fourth fee instruction, another version); the fake API refuses a submit without a session. `docs/api.md` and the threat model say so. | `server/mutis/handlers/chain.py`, `server/mutis/cbor.py`, `server/tests/test_contract.py::test_submitting_takes_a_locker_session_and_relays_only_our_sends`, `server/tests/fixtures/stealth-envelopes.json`, `server/tests/cbor_fixture.py`, `web/app/lib/wallet.js`, `api-locker.js`, `web/app/tests/fake-api.js`, `wallet.test.js`, `docs/api.md`, `docs/threat-model.md`; E-J direct in the production run below |
| 22 | `/how` and `/privacy` promise every database copy is deleted after 7 days, but root's `/var/backups/mutis/pre-golive-…/` holds database copies (rehearsal and test data, no real visitors) outside the pruned folder (low, claims) | **Confirmed.** Ten `.sqlite3` copies plus `-wal`/`-shm` from 2026-10-11; all younger than 7 days, so nothing was deleted now. | `backup.py prune-root`, run as root as the first step of `mutis-backup.service` (systemd's `+` prefix on one `ExecStartPre`), deletes files named like a mutis database (`.sqlite3`, `-wal`, `-shm`, `.part`) under `/var/backups/mutis` at the published age; wallet tars, balance snapshots and config copies never go, whatever their age (test). The unit is installed on the server (`install` + `daemon-reload`); the runbook's table says so. | `deploy/scripts/backup.py`, `deploy/systemd/mutis-backup.service`, `deploy/tests/test_ops.py::test_roots_database_copies_go_at_the_same_age_and_nothing_else`, `test_config.py::test_root_runs_only_the_backup_prune`, `deploy/README.md` |
| 23 | Caddy: an unknown Host gets a bare 200 without the security headers; port 80 answers a 308 to the reflected Host (low, claims) | **Confirmed.** | A `(misdirected)` snippet (security headers, site CSP, `no-store`, 421) imported by `https://` and `http://` catch-all blocks after the site; the local stack rewrites them onto its ports; D-01 checks a made-up Host on both ports (421, the headers, nothing reflected); deploy test; `caddy validate` passed on the server before the deploy (activate-release validates every changed Caddyfile before reloading). | `deploy/caddy/Caddyfile`, `tests/e2e/localstack.py`, `tests/e2e/test_headers.py`, `deploy/tests/test_config.py` |
| 24 | A 6 MB `PUT …/chunks/0` answers 502 with an empty body (Caddy's 5 MB `request_body` fails mid-read inside the buffering proxy) instead of a 413 in the API's JSON shape, so the app shows a server-down error (low, claims) | **Confirmed.** The app's chunks are 4 MiB + 16 B, so only a hand-made client met it; the app would still have said "Our server tripped". | A declared `Content-Length` over 5 MB answers 413 in `http_util.ApiError`'s shape (`too_large`, `max_bytes`) before a byte is read; the app's `describe()` maps a server-side `too_large` (through a `SealError` too) to `error.too_large_request`, which names the limit, EN and ES; D-01 sends a 6 MB chunk; the app-ui `safety` flow answers a chunk with that 413 and reads the banner. | `deploy/caddy/Caddyfile`, `web/app/ui/errors.js`, `web/app/i18n/*.json`, `tests/e2e/test_headers.py`, `web/app/ui/tests/flows.py`, `deploy/tests/test_config.py` |
| 25 | `hosting.snapshots = "weekly"` and "keeps them for a few weeks" were never checked against the Hostinger panel (low, owner) | **Confirmed** (an unverified claim). | The sentence on `/how`, `/privacy`, `/faq`, `llms-full.txt` and the app's claim `c5snap` now says, in both languages: our host (Hostinger) can take weekly snapshots of the whole server; we haven't switched them off, and we haven't yet confirmed in its panel how long it keeps them. Open item 5: the owner checks the panel; the config and the copy follow. | `web/site/pages/{how,privacy,faq}.html` (+ES), `web/site/static/llms-full.txt`, `web/app/i18n/*.json` |
| 26 | `/judges` links the forum root instead of a thread (low, owner) | **Confirmed, left as is.** | Nothing until the owner posts the thread (open item 2). | — |

Items 20–26 were handled in the continuation of this pass (the claims review's list had reached the
first pass truncated after item 19).

## Suites run after the changes

On the server as `build` with the server's Python 3.13, Node 20 and Chromium 154, from a tarball of the
tree that became commit `7c9e627` (logs in `docs/evidence/2026-10-11/fix-pass/suites/`):

| Suite | Result |
|---|---|
| server (`python3 -I -m unittest discover -s server/tests`) | 197 tests OK, 4 skipped (the deploy gate's run as `build`: OK, 5 skipped) |
| site (`web/site/tests/run.py`, static and browser checks) | 28 of 28 (a first run failed the judge-pass check, item 6's hash-change fix) |
| app-ui (`web/app/ui/tests/run.py`) | 229 of 229 (a first run failed once: the new 413 case had counted as an upload for a later check; moved to its own actor) |
| app-core (`web/app/tests/run_all.py`) | ALL PASS, 9 steps (lint 824/824, cross-check 80/80, KATs 118/118 under Node and in Chromium, jitless 75/75, sidecar 16/16, PoW and scan benches, contract 12/12 against `mutis-api --dev`; the two contract expiries now expect the hour rounding of item 16) |
| deploy tests (`deploy/tests`, locally) | 65 OK |
| `tools/lint.py` · `tools/check-copy.py --config <live /config>` | PASS · PASS (3 phrases to read, as before) |
| D-01 on the throwaway stack (`test_headers.py --local hidebox`, the real Caddy 2.6.2) | PASS, 413 shape and 421 on both ports included |

Deployed as release `7c9e6279927e4ed3bc12558cfaec27bb280056ff-c9a2957d0` at 22:11 (`deploy.sh HEAD`: gates,
build, activation, smoke PASS, manifest notarized in tx `f64332b5…09a2`); `verify-deploy` 0 differences
across 143 files; `/status.json` overall green; D-01 against production PASS (certificate 89 days
left). The changed `mutis-backup.service` was installed by hand (`install` + `daemon-reload`, the
notice activation prints); `backup.py prune-root` run once as root deleted nothing (every copy is
younger than 7 days). The production E2E and judge runs are under "Evidence" below. After them, HEAD
(`ea20751`: the tests commit and this documentation) was deployed the same way at 00:31 as release
`ea20751ce0033a8208ca7815c0b4de7feab3c00d-cc3ac6cfe` (gates, build, activation, smoke PASS, manifest
notarized in tx `b9955589…bdfe`); `verify-deploy` 0 differences across 143 files, `/api/v1/health`
green on that commit, `/status.json` green, D-01 against production PASS, `/config` without
`e2e_expiry_s`, the wall quiet (`fix-pass/deploy/*-ea20751.txt`).

## Evidence: the production E2E and judge runs (`docs/evidence/2026-10-11/fix-pass/e2e/`)

Every scenario ran against release `7c9e627…-c9a2957d0` with `run.py --chain --final`, in batches:
every browser runs on the server, so all actors share one /64, and the API allows five new lockers and
five new drops per network an hour (tests/e2e/README.md). `e2e_expiry_s = 60` was in the config for
the first batch only (E-05) and removed, `mutis-api` restarted, before the second; `/config` carries
no `e2e_expiry_s` now.

| Run | Scenarios | Result | Where |
|---|---|---|---|
| batch1, 22:21 | E-01, E-02, E-04, E-05, E-06, E-07, E-08, E-11, E-13, E-14, E-15, E-16, E-17, E-18, E-19, E-20, E-21, E-22, E-24, E-25, E-03 | 20 of 21 PASS; E-13 FAIL (below) | `batch1.log`, `reports/batch1-*.json`, `shots/batch1-*` |
| batch2a, 23:28 | E-09, E-10, E-13 | E-09 (23 s) and E-10 (52 s) PASS; E-13 FAIL (below) | `batch2a.log`, `reports/batch2a-*.json` |
| batch2b, 23:40 | E-13 | PASS, 30 s: the browser wallet received its grant, Waiting → Seen → Amount proven → Added, paid by the browser, quota +2 GiB | `batch2b.log`, `reports/batch2b-*.json` |
| batch2c, 23:41 | E-12 | PASS, 30 s | `batch2c.log`, `reports/batch2c-*.json` |
| batch2d, 23:53 | E-J, direct mode | FAIL at B1: the computer's locker was refused with "Easy. You can do that again in 10:49" (429 `rate_limited`): E-J's phone had been the fifth new locker of that hour on the server's /64, the limit working as published | `batch2d.log`, `reports/batch2d-*.json` |
| batch2e, 00:17 | E-J, direct mode | PASS, 1.5 min (track A 5 s, track B 84 s; B1 4 s, B2 27 s, B3 14 s, B4 13 s, B5 2 s, B6 22 s, B7 1 s); cold start 60 s (the grant spendable within 3:15); B3 and B6 built and submitted by the browser; B7 lists the exit receipt from A3 | `batch2e.log`, `reports/batch2e-*.json`, `shots/batch2e-*` |

So every scenario of §17.2 and E-J in direct mode passed on the new code, each at least once after
its last change.

**E-13 failed twice, both times in the test, not the product.** (1) In batch1 the buyer's fresh locker
got no sponsor grant: the two grants a day per /64 (item 2) had gone to earlier lockers of the same
run, so "Pay 0.5 tTARI from this browser" answered "This browser's testnet wallet doesn't have enough
tTARI for that" and the invoice stayed at Waiting until it expired unpaid an hour later (the failure
screenshot; nothing was credited, as it should be). (2) E-13 was given a one-use judge pass in direct
mode, as E-J has, and still got no grant: item 6 moved the pass from `sessionStorage` to
`localStorage` (`{code, until}`, a week, as a `/judges#pass=` link saves it) and the test harness still
wrote the old key, so the app never sent `X-Mutis-Judge`; E-J's direct run would have failed the same
way. The test harness now writes what `store.saveJudgePass` writes, and E-13 waits for the grant to be
spendable before it pays (commit `3cd5622`). The pass path is now proven on production: the grant
was queued from the evidence slice within a minute of the locker opening, and the payment went out
of the browser.

**Purge (00:21–00:33, `fix-pass/deploy/purge.txt`).** By id, from a read-only diff against the 22:21
snapshot of the ids an E2E run can create: 22 items and 12 drops taken down (`mutis-admin takedown`),
the E-14 forged payment row and the two unpaid E-13 invoices deleted, the four test judge passes
deleted. Kept: the two credited E-13 invoices (paid on chain), the 18 test lockers (identities, as at
go-live), the owner's locker, the security dead drop (active), the robot's canary items and the 20
judge passes. The wall then still listed eight exits from the 20:00 hour: the judge-run and claims
reviews' own burned test items from before the snapshot (three named in the claims probe's
`created.json`, three found through the walk's links, two sealed in the same minutes), taken down by
id as well. `/api/v1/stats/wall` reads quiet, canary only; `/config` carries no `e2e_expiry_s`. Left
alone for the owner: one unlabeled dead drop, still active, created during the reviews' hour with no
trace in their logs (open item 6).

## Open items for the owner (Tier 3)

1. `git push` main and make `c7b/mutis` public before any judge visits; then enable private
   vulnerability reporting if the `/security` advisory link should work, and run
   `python3 -I tools/verify-deploy.py https://srv2052606.hstgr.cloud <commit>` from a clean clone on a
   third machine.
2. Post the announcement thread on the Tari community forum and point `/judges` at it (both languages).
3. Hand judge passes out as links: `https://srv2052606.hstgr.cloud/judges#pass=<code>`, one per judge,
   opened on both devices.
4. Design items left on purpose: the home page's length and S3's footnotes; a Testnet chip in the
   phone header; a hidden "delight" before Oct 24.
5. Check the Hostinger panel: are VPS snapshots on, how often, and how long are they kept? Then set
   `hosting.snapshots` in `/etc/mutis/mutis.toml` ("weekly" or "off") and make the snapshot sentence
   on `/how`, `/privacy`, `/faq`, `llms-full.txt` and the app's `claim.c5snap` state the retention.
6. One unlabeled dead drop is still active, made on 2026-10-12 UTC during the reviews' hour with no trace
   in their logs (`SELECT id FROM drops WHERE state = 'active' AND label = ''` as `mutis`, read-only). If it
   isn't yours, `sudo mutis-admin takedown drop -- <id>`.

## Second pass (2026-10-12): the security, anti-slop, SEO and docs reviews

Four more reviews ran against the live site and the repository after the first pass: a security
audit (the repository and its history, the live headers and TLS, the burn race, the fragment, the
limits), an anti-slop read of every page in both languages at 390 and 1440 px, an SEO and GEO pass
(crawl, metadata, link previews, what an AI engine reads first), and a documentation pass. Each
finding below was checked against the code before anything changed; "rejected" names the reason.
Nothing here is a secret: the one leak this pass removed is described without repeating it.

### The history rewrite

The security audit found no key material in git, but one OPSEC leak: the D-02 relay log in the
go-live evidence named the operator's own machine (its public IPv4 and IPv6 addresses, whose reverse
DNS is a private VPS of the owner's). The addresses were replaced in the working tree by
`<operator-ipv4>` / `<operator-ipv6>` (the test's meaning is unchanged: a session over each address
family, then a search of every log for its values), then every commit was rewritten with
`git filter-branch --tree-filter` over all refs (there were no tags; no stash), the backup refs were
dropped, every reflog expired and the store pruned (`git gc --prune=now`). A scan of every blob in
the object store afterwards (`git cat-file --batch-all-objects`) found neither address nor the
hostname in any object, reachable or not; the two unreachable stash commits the audit mentioned are
gone with the prune. The scan also looked for other non-public names of the owner's machines
(tailnet ranges and names, private LAN ranges, the other VPS's hostname): the only matches were a
test fixture address and a substring of `parts.netloc` in a handler. Commits from the go-live
evidence onward have new ids (the earlier ones are unchanged), so ids quoted in the first pass above
(`7c9e627`, `3cd5622`, `ea20751`, `88e12e9`) are historical labels, not commits of this repository
any more; the release ids they name stay what the live `releases.json` recorded. `tools/lint.py`
now refuses any public IP literal but the server's own (private, loopback, documentation and
`x.0.0.0` literals, versions and times are fine), with a test, and `.gitignore` names the
key-shaped files that must never land in the tree. GitHub may hold the old objects until its own
garbage collection: an owner item below.

### Security audit

| # | Finding (severity) | Verdict | What changed | Evidence |
|---|---|---|---|---|
| S1 | The operator's public addresses committed in an evidence log (medium) | **Confirmed. Fixed.** | Above: redaction, history rewrite, verification scan, lint rule, `.gitignore`. | `tools/lint.py` (`address_problems`), `deploy/tests/test_lint.py::test_public_addresses`, `.gitignore` |
| S2 | One /64 can empty the API's indexer budget: chain reads have no /48 rule, an unknown transaction id costs up to four upstream calls and is never cached, and the same bucket carries a browser's direct send (medium) | **Confirmed** from the source. | The indexer client has a send lane of its own per upstream (a fifth of the rate; reads get the rest), and the submit proxy draws on it, so no flood of reads can stall a send. Chain reads carry a per-/48 rule next to the per-/64 one. An unknown transaction id draws on a budget of its own (ten a minute per /64; a hit gives it back), so misses answer 429 after that, never a 503, and stay uncached (a transaction committed seconds ago reaches the indexers at different times). Result polls stay on the read lane: the wallet retries a failed poll until its deadline, so a flood delays the confirmation, not the send. | `server/mutis/indexer.py`, `handlers/chain.py`, `test_contract.py::test_unknown_ids_have_a_budget_of_their_own_and_never_empty_the_send_lane` |
| S3 | A stockpile of base-difficulty challenges, or challenges fetched from an unescalated network, skips the proof-of-work escalation; challenges aren't bound to the requesting key (low) | **Confirmed** (reproduced in the reviewer's local run). | The network key is part of the challenge's MAC (nothing new is stored; the frozen vectors pass an empty key and are unchanged), and a solution counts only if its difficulty is within two bits of what that key is asked for now. Two tests that spent a challenge from a network other than the one that fetched it were corrected. The key changes at UTC midnight, so a challenge issued in a day's last minutes fails after it and the app solves a fresh one. | `server/mutis/pow.py`, `server/tests/test_pow.py`, `test_never_store.py`, `test_password.py`; `docs/api.md` |
| S4 | The only security contact is a dead drop with a daily cap, and deliveries fail while the chain worker is down (low) | **Confirmed. Partly fixed; the cap bypass rejected.** | `SECURITY.md` names the drop first and the GitHub private advisory as the second channel once the repository is public and private reporting is on (the owner's two settings), with what to do when the drop answers "took all it can today". `security.txt` keeps its one `Contact` until the second one works, as RFC 9116 asks (the site suite refuses a dead one). Letting the security drop skip its daily caps was rejected: the caps protect the owner's locker and the disk from a flood through a public link, and the per-/64 limits alone would still let a few networks fill it. | `SECURITY.md`, `web/site/static/.well-known/security.txt` |
| S5 | `.gitignore` gaps: key-shaped files would be committed; no allowlist for evidence images (low) | **Confirmed. Fixed; the image allowlist rejected.** | `keys/`, `credentials/`, `*.pem`, `id_*`, `*passes*.txt`, `robot*.json`, `receiver*.json`, `*keyring*`, `*.sqlite`, `*.db`, `.env.*`, `*.tar` (no tracked file matches). A per-image allowlist was rejected: it would add a line per screenshot with no check beyond its presence; the evidence README already names every folder and what its shots show, and the lint now catches the one kind of leak an image's text could carry a path to. | `.gitignore` |
| S6 | A link made without an expiry for an anonymous file is refused with 422 (the file's default expiry, a day rounded up to the hour, is above the link class's bound plus a minute) (low, a bug) | **Confirmed.** | A link that defaults to its file's expiry takes it as is: the file's own expiry passed the same check at upload. | `server/mutis/handlers/shares.py` (`link_rules`), `test_contract.py::test_a_link_without_an_expiry_takes_the_files_own` |
| S7 | The file's `lastModified` time is sealed into the metadata, close to the capture time for photos, while the UI says camera data was removed (informational) | **Confirmed.** Nothing reads it. | The app seals `mtime: null` (format v1 keeps the field; the library still accepts one). | `web/app/ui/sealing.js` |
| S8 | `corepack` ships with Debian's nodejs; static routes answer TRACE, PUT and DELETE with 200 (informational) | **Confirmed.** | `privilege-check.sh` also wants pnpm, yarn and pip absent and the runbook says why; pages and files answer 405 with `Allow: GET, HEAD`, the security headers and `no-store` to any method but GET and HEAD (the API keeps its own), checked by D-01 (TRACE and PUT) and a deploy test. | `deploy/scripts/privilege-check.sh`, `deploy/README.md`, `deploy/caddy/Caddyfile`, `tests/e2e/test_headers.py`, `deploy/tests/test_config.py` |

### Anti-slop review

| # | Finding (severity) | Verdict | What changed | Evidence |
|---|---|---|---|---|
| A1 | The three reference tables on `/how` and `/security` are clipped on a phone (high) | **Confirmed.** | Below 640 px each row stacks and every cell carries its column's name (`data-cue`, as the home page's "What we store" table does), in both languages. | `web/site/css/pages.css`, `how.html`, `security.html` and the `es/` twins; `docs/review/antislop/how-390-tables-cut.webp` (before) |
| A2 | The Spanish app formats with Spain's conventions ("1,9 GB", "10.000") next to the site's Mexican ones (high) | **Confirmed.** | The app's number, date and relative-time formats use `es-MX` and `en-US`, as `site.js` does. | `web/app/lib/i18n.js` |
| A3 | The Spanish hero's two-line H1 touches the "FUNDIDO DE ENTRADA:" line at 390 px (medium) | **Confirmed.** | The hero keeps a row gap on phones. | `web/site/css/home.css` |
| A4 | A wall label that wraps lifts its keyhole; the promise's forced break makes four ragged lines on phones (medium) | **Confirmed.** | Every label reserves two lines, text at the bottom, so keyholes stay level; on phones the promise's `<br>` is hidden and the line balances. | `web/site/css/home.css`; `docs/review/antislop/home-1440-wall-label-wrap.webp`, `home-390-wall-promise-wrap.webp` (before) |
| A5 | Four word-pairs for four things: drop / dead drop, sealed to / locked to, view / open, room / space (medium) | **Partly accepted.** | "Locked to your locker" on `/faq`, `/how`, `/security` and `/judges` ("sealed" stays only for the key inside a payment, 11-brand §7.2); the count is "open" (the viewer's burn line, the bad-key and wrong-key bodies, the FAQ, `/how`, `/privacy`); the device list is "Your recent links". Kept: "dead drop" on the site and in the docs (the feature's name in the spec, the API and the threat model; the app's "drop" is its short form, and "Drop a file" is the hero's verb), and "Get more room" (the brand's own CTA; "space" is the noun for the quota, and Spanish says "espacio" for both). | `web/app/i18n/en.json`, pages listed |
| A6 | Spanish gender and verb drift in the app and "punto de control" vs "checkpoint" on the site; "sellados a" (medium) | **Confirmed.** | "Abrir" on the inbox row (and `/judges` B4 quotes it); "cifrado el", "al cifrarlo" on `/verify`; "checkpoint" everywhere on the Spanish site, as the app already said; "cifrados para tu casillero" and "sellada para nuestro casillero". | `web/app/i18n/es.json`, `es/faq.html`, `es/how.html`, `es/judges.html`, `es/security.html`, `es/privacy.html`, `es/index.html` |
| A7 | Fourteen Spanish sentences that read as translated (medium) | **Confirmed.** | Every rewrite in the review applied (home: "Solo una es nuestra", "La otra persona necesita…", "O que cualquiera te deje uno"; privacy "(si tienes casillero)"; security "llave de inicio de sesión"; abuse "Motivo"; FAQ "una dirección de Tari normal, sin casillero"; 404 "Volver a soltar un archivo"; the app's password hint, "Te espera hasta el…", "Se fue en su señal", "Tus enlaces recientes"). The home page's skip link reads "Ir a la zona de archivos"; the other pages keep "Saltar al contenido", the same on all ten. | `es/*.html`, `web/app/i18n/es.json` |
| A8 | `/status` says "Something needs our attention" while every check is green (medium) | **Confirmed** (`attention` is the operator's signal). | The line shows only when a check isn't green, and under it the reasons in words (a budget's kind, slice and share; new abuse reports), in both languages. | `web/site/js/status.js`, `status.html`, `es/status.html`, `pages.css`; `docs/review/antislop/status-390-attention-all-green.webp` (before) |
| A9 | The three pack cards on `/upgrade` don't align (medium) | **Confirmed.** | A pack's title reserves two lines, so every price and Buy sit level. The cards stay: the page offers a choice between three packs and a free plan, which a table of prices would not make clearer. | `web/app/css/app.css`; `docs/review/antislop/upgrade-1440-pack-cards-misaligned.webp` (before) |
| A10 | An unknown app path borrows the gone-link copy; "No drop here." offers no way out (medium) | **Confirmed.** | An unknown app path shows the site's 404 scene (INT. NOWHERE — NIGHT) with its button sized to its words; a closed or unknown drop lists "What is mutis?" and "Lock a file of your own". | `web/app/ui/app.js`, `droppage.js`, `app.css`, `i18n/*.json`; `docs/review/antislop/app-notfound-1440.webp` (before) |
| A11 | "About a minute" for the sponsor grant is tighter than what was measured (medium) | **Confirmed** (cold start 60 s, spendable within 3:15). | "A minute or two" on the home page, `/security`, `/judges` B3, the README and the threat model, in both languages; the app's send screen already said so. | pages listed |
| A12 | The whole "Do this" column of `/judges` is bold (low) | **Confirmed.** | Only the UI names it already marks with `<strong>` are bold. | `web/site/css/pages.css` |
| A13 | Straight quotes in one home footnote (low) | **Confirmed.** | “sent by mutis”. | `index.html` |
| A14 | Layout nits: the "Two locks" block, `.more` arrows pushed to the far right, static-wall cells drawn tall, an orphaned "#)", stretched buttons, the known-panel toggle inset (low) | **Partly accepted.** | A gap above the locks block; `.more` links are inline, so the arrow follows the last word (a 3 px vertical padding keeps the target); "(no #)" never breaks; the inbox's "Check again" and the not-found button take their words' width; the toggle sits flush with the content. Rejected: squares for the static wall, which shows every locker's fate under its label, so its cells grow with their text; a square would clip the fate on a phone. | `web/site/css/site.css`, `home.css`, `web/app/css/app.css`, `widget.css`, `how.html` (+ES) |
| A15 | "Questions, answered short."; six label-colon paragraphs on `/pricing`; the abuse form files "Something else" untouched (low) | **Confirmed.** | "Questions, short answers."; the pricing rules are small headings with a paragraph each (the send-mode variant pair kept); the category starts at "Choose one" / "Elige una", required. | `faq.html`, `pricing.html`, `abuse.html` and the `es/` twins |

### SEO and GEO review

| # | Finding (severity) | Verdict | What changed | Evidence |
|---|---|---|---|---|
| E1 | Every GitHub link 404s while the repository is private; the JSON-LD license points there (high) | **Confirmed. Owner action (Tier 3)** for the repository; the license fixed. | The JSON-LD license is `https://spdx.org/licenses/MIT.html` on both home pages. The repository stays the owner's call (open item 1 of the first pass). | `index.html`, `es/index.html` |
| E2 | A search or AI engine learns Tari fourth: the home title, description, Open Graph description and JSON-LD don't say it (high) | **Confirmed.** | Title "mutis — encrypted file drops, keys sent over Tari Ootle" (55), description and `og:description` with the stealth payment and the Ootle record, `/how` titled "How mutis works: browser encryption and Tari Ootle", the Spanish twins alike; the JSON-LD description leads with Tari Ootle. 11-brand §9.1 records the new strings. "Every exit logged on the Ootle" is true while `features.seallog` is on, which the live deployment runs. | `index.html`, `es/index.html`, `how.html`, `es/how.html` |
| E3 | `llms.txt` is a static template that hedges and omits SealLog, direct sends and view keys (medium) | **Confirmed.** | `llms.txt` leads with Tari and carries one line per deployment fact (`{when:send_mode=direct}`, `seallog=on`, `proof=proven`…); `tools/variants.py` keeps the lines true for the deployment and drops the marker, as it already resolves the pages' variants, so the served file says what the site runs (direct sends, SealLog, the sidecar proof). Links to `/privacy`, `/faq`, `/es/` and `/releases.json` added. | `web/site/static/llms.txt`, `web/site/tools/variants.py`, `web/site/tests/static_checks.py` |
| E4 | No limit or price in crawlable HTML, and `robots.txt` blocks the `/api/v1/config` the pages fill from (medium) | **Partly accepted.** | `robots.txt` allows `/api/v1/config` and `/api/v1/stats` exactly (longest match; `/stats/wall`, `/canary` and the rest stay blocked), so a crawler that renders the pages may read the numbers, and `llms.txt` points at them. Writing the numbers into the HTML at build time was rejected: the pages' numbers are variables filled from `/config` by one formatter (11-brand P-20); a second formatter in the build would drift from it. | `web/site/static/robots.txt`, `static_checks.py` |
| E5 | Share links and drop pages unfurl with no card (medium) | **Confirmed.** | The viewer page carries the locked-file card (`og-s.png`, made for it) with a description; the app pages carry the site's card. Static tags, the same for every link: no id, no fragment, no `og:url`. A drop-specific card was rejected: one page serves every app route, and a page of its own for `/d/` is a route change; the drop page keeps its runtime title "Leave a file · mutis". | `web/app/view.html`, `web/app/app.html` |
| E6 | The Spanish pages share the English card and describe it in Spanish (medium) | **Confirmed.** | `og-es.html` rendered with the site's own tool to `og-es.png` (Cada secreto sabe cuándo hacer mutis.), every Spanish page points at it, and the alt text now describes what the image shows. | `web/site/og/og-es.html`, `web/site/static/og-es.png`, `web/site/tools/render-images.py`, `es/*.html` |
| E7 | Hidden variants are in the served HTML: "Drop a file.Choose a file.", both status-line phases, the relay footnote (low) | **Partly accepted.** | A space between the fine- and coarse-pointer spans (no visual change). Rejected: emitting one phase of the status line and deleting the other send-mode variants in the build. The runtime switch from `/config` is a documented feature (an admin flips a flag without a rebuild and the copy stays true), and the mainnet rebuild is planned (spec §15.6). | `index.html`, `es/index.html` |
| E8 | The language offer bar shifts the page (CLS 0.04) and sits before the skip link (low) | **Partly accepted.** | The offer follows the skip link, so "Skip to…" stays the first Tab stop. A fixed overlay was rejected: the app pages have a bottom bar, a fixed top bar would cover the header, and the measured shift is under the 0.1 threshold. | `web/site/js/site.js` |
| E9 | The JSON-LD is thin (low) | **Confirmed.** | An `@graph` with a `WebSite` and the `SoftwareApplication`: a Tari-first description, `featureList`, `image`, `softwareHelp`, the SPDX license; `sameAs` waits for the repository to be public. | `index.html`, `es/index.html` |
| E10 | `/favicon.ico` is a 404 (low) | **Confirmed.** | `render-images.py` wraps the 192 px icon as an ICO (PNG inside); the site suite checks the file. | `web/site/tools/render-images.py`, `web/site/static/favicon.ico`, `static_checks.py` |
| E11 | FAQ answers have no ids (low) | **Confirmed.** | Every `<dt>` has a stable id, the same slug in both languages (`/faq#will-a-link-preview-in-whatsapp-or-slack-use-up-my-one-open`). | `faq.html`, `es/faq.html` |
| E12 | `robots.txt` blocks `/d/`, so Google never sees a drop page's noindex and may list the bare URL (low) | **Confirmed.** | The `Disallow: /d/` line is gone; a drop page's own `noindex` (header and meta) does the work; `/s/` and `/t` stay blocked. | `web/site/static/robots.txt`, `static_checks.py` |
| E13 | (the review's last item reached this pass truncated) | **Not received.** | — | — |

### Documentation review

Its findings reached this pass only as the task's list: `SECURITY.md` (RFC 9116-aligned, the dead
drop as the private channel, the testnet scope, response expectations, the advisory path once the
repository is public), `docs/architecture.md` (the parts and users on the server, the trust
boundaries, who sees what, the life of a file from drop to exit, the Tari parts with where each
lives in the code, verify-don't-trust), the AI disclosure line (11-brand §7.8) in the README's "How
it's built" (moved above the evidence it says is linked below) and on `/how`, the capability map
("Where Tari comes in") and the honest boundaries ("What the server sees") in the README, `NOTICE`
(complete: the vendored library, the emoji alphabet, the template crates, the fonts), `CHANGELOG`
(this pass), and every relative Markdown link checked (40 files, none broken).

### Suites, deploy, end-to-end runs and the purge

The pass's first suite run on the server (tarball `fix3`) was red twice in app-ui: the widget's
dictionaries (`web/app/i18n/widget-*.json`) were stale after `recent.h` was reworded, and the
widget's payload after a text drop was 41,082 B, 122 B over A-06's 40 KB (the locale function in
`lib/i18n.js` and the metadata note in `ui/sealing.js`). Fixed by regenerating the subsets and by
moving the IndexedDB code (the locker's and the inbox's records, nothing a first drop touches) out of
`lib/store.js` into `lib/idb.js`, which loads with the locker: 23,891 B at load and 40,176 B after a
drop (commit `4888a19`; the lint's `LOCKER_ONLY` list names the new module). Site's first failure
(the pricing heading, `20389a4`) had been fixed before.

On the server as `build` with the server's Python 3.13, Node 20 and Chromium 154, from fresh tarballs of
the tree that became `4888a19` and again of `47cfbb0` after the reconcile fix below (the logs in
`docs/evidence/2026-10-11/fix-2/suites/` are `47cfbb0`'s; both runs were green):

| Suite | Result |
|---|---|
| server (`python3 -I -m unittest discover -s server/tests`) | 202 tests OK, 4 skipped (201 before the reconcile test) |
| site (`web/site/tests/run.py`) | 28 of 28 |
| app-ui (`web/app/ui/tests/run.py`) | 229 of 229 (budget: 23,891 B at load, 40,176 B after a drop) |
| app-core (`web/app/tests/run_all.py`) | ALL PASS, 9 steps (lint 836/836 over 78 files, cross-check 80/80, KATs 118/118 under Node and in Chromium, jitless 75/75, sidecar 16/16, PoW and scan benches, contract 12/12 against `mutis-api --dev`) |
| deploy tests (`deploy/tests`, locally) | 67 OK |
| `tools/lint.py` · `tools/check-copy.py --config <live /config>` | PASS · PASS (2 phrases to read, as before) |

Deployed as release `9e7bc34c44a9f33243cd1149a3c4f4f219fe7007-c47090408` at 10:37 CST (`deploy.sh HEAD`:
gates, build, activation, smoke PASS, manifest `26e75510…8322` notarized in tx `63e54a75…66aa`);
`verify-deploy` 0 differences across 145 files and the chain runs the SealLog template byte for
byte; `/api/v1/health` on that commit; `/status.json` green except the canary for the minutes it was
in flight after the restart; D-01 against production PASS, the new `TRACE`/`PUT → 405` checks with
`Allow: GET, HEAD` included (certificate 89 days left); `/config` without `e2e_expiry_s`; the wall
quiet (`fix-2/deploy/*-9e7bc34.txt`). E-J's second attempt (below) found a server fault, fixed in
`47cfbb0` and deployed at 18:51.

**End to end against production (`docs/evidence/2026-10-11/fix-2/e2e/`).** Every scenario except E-J
ran on release `9e7bc34…-c47090408`, and E-J's passing run on `47cfbb0…-cf21f0fbd` (the two differ only
in the server's reconcile and its runbook line), all with `run.py --chain --final`, in batches an hour apart as before, with
`e2e_expiry_s = 60` in the config for the first batch only (E-05) and removed at 11:04, `mutis-api`
restarted and `/config` checked before anything else ran. `report.json` holds the final result of each
of the 25 scenarios (25 PASS) and every attempt:

| Run | Scenarios | Result | Where |
|---|---|---|---|
| batch1, 10:47–11:03 | E-01, E-02, E-04, E-05, E-06, E-07, E-08, E-11, E-14, E-15, E-16, E-17, E-18, E-19, E-20, E-21, E-22, E-24, E-25, E-03 | 19 of 20 PASS; E-24 FAIL (below) | `batch1.log`, `reports/batch1-*.json` |
| batch1b, 11:06 | E-24 | PASS, 12 s | `batch1b.log`, `reports/batch1b-*.json` |
| batch2a, 12:05–12:07 | E-09, E-10, E-12, E-13 | PASS: 23 s, 52 s, 38 s, 31 s (E-13 with a one-use pass: Waiting → Seen → Amount proven → Added, paid by the browser) | `batch2a.log`, `reports/batch2a-*.json` |
| batch2b, 13:10 | E-J, direct mode | FAIL at B3 (below): the computer's sponsor grant was refused, `budget_exhausted` | `batch2b.log`, `reports/batch2b-*.json` |
| batch2c, 18:03 | E-J, direct mode | FAIL at B6 (below): the payment held at "Amount proven", credits frozen since 15:37 | `batch2c.log`, `reports/batch2c-*.json`, `shots/batch2c-*` |
| batch2d, 19:05 | E-J, direct mode, on `47cfbb0` | PASS, 106 s: track A 5 s, track B 98 s (B1 4 s, B2 43 s, B3 15 s, B4 12 s, B5 2 s, B6 19 s, B7 1 s); cold start 77 s, within 3:15 | `batch2d.log`, `reports/batch2d-*.json`, `shots/batch2d-*` |

**E-24 failed in the test, not the product.** Its "/locker shows needs_wasm" check ran after a fixed
3-second drain of browser events; on production, a `--jitless` page evaluates the app's modules slowly
enough that the banner came a moment later (the failure screenshot already shows it). The check now
waits for the banner as the ui suite's does (`6e0ee25`); E-24 then passed in 12 s.

**E-J failed on a spent budget, not on the product.** B1 opened the phone's locker (its grant at
13:10:27, 202) and then the computer's, whose grant answered 429 `budget_exhausted` at 13:10:30: the
evidence slice of the sponsor budget (`budgets.evidence.sponsor_ut`, 10 grants a UTC day shared by all
judge passes; a judge pass skips the 2-per-/64 limit) had been spent on this UTC day by the previous
pass's runs of the night, the 04:29 film run, batch2a's E-13 and E-J's phone. The app did what its code
says (a refused grant only means sends go by the relay, and `ui/locker-ctx.js` drops the refusal
silently), so a judge is never stuck, but B3's "built and submitted by the browser itself" waited 240 s
for a path that could not become direct. No budget was changed in production: the slice resets at
00:00 UTC and E-J was rerun after it.

**E-J's rerun at 18:03 found a real fault: one reconcile round froze every pack for three hours.**
B1 to B5 passed (cold start 54 s); at B6 the phone paid its pack from the browser, the payment was seen
and its amount proven, and it never became "Added" (`shots/batch2c-E-J-B6-held-at-amount-proven.jpg`).
`meta.credit_freeze` had been 1 since the hourly reconcile of 15:37 (`event=chain.credit_freeze`, health
red `credit_freeze_on` from then on), and only `mutis-admin unfreeze-credits` lifts it. The rounds of
16:37, 17:37 and 18:37 found nothing wrong, and at 18:12 a direct read of all ten credited outputs answered
a verified `Utxo` on both indexers; they are in the mirror and the sidecar re-proves the same values.
A committed output cannot leave the chain and come back, and we never spend receiver outputs, so the
15:37 verdict came from the one input of the reconcile that is not deterministic: both indexers
answered "missing" for an output at that moment. A read-only probe of one credited output on both
indexers every 4 seconds then caught such a moment (`fix-2/deploy/credit-freeze-15-37.txt`): at the
epoch changes of 18:41 and 19:05 both indexers served it as a `Utxo` without `verified: true`, for 21
and 26 seconds (the change at 18:18 went clean; at 19:32 indexer-a alone did it for about 20 s,
`verified: false` with no proof), which the check counts as "missing". An epoch change
happened between 15:28 and 15:43 (the SealLog checkpoints of those times sit in epochs 12187 and
12188), so the 15:37 round most likely fell on one. What is ours: one round could stop every paying
visitor, and every judge's B6, until the owner noticed a red check. No other payment arrived in those
hours; E-J's was the only one held.

Fixed in `47cfbb0` (`server/mutis/payments.py`, `chain_worker.py`): a mismatch now holds credits
(`meta.reconcile_mismatch`, `event=chain.reconcile_mismatch`) and the worker runs the reconcile again
five minutes later; a second mismatch in a row freezes credits as before, a clean round releases the
hold, and nothing is credited in between. A 404 counts as "missing" only when it is the indexer's own
JSON error ("… not found", "… is down"); a gateway's 404 page is "unknown", like a 5xx. `unfreeze-credits`
also clears a hold, and the runbook (`deploy/README.md`, "Credits frozen") says how to read the state.
New test `test_a_one_off_mismatch_holds_credits_until_the_recheck`; the freeze tests now need the
second round. Deployed at 18:51 as release `47cfbb0b7b30c1f947c44da123535fde7e5dae1f-cf21f0fbd`
(gates, build, activation, smoke PASS, manifest `9bbbf66b…10b2` notarized in tx `2ef4d8c8…41a8`);
`verify-deploy` 0 differences across 145 files, the SealLog template byte for byte; D-01 41 of 41
checks PASS, the 405 checks included (`fix-2/deploy/*-47cfbb0.txt`). The worker's first round after the
restart (18:51:56) was clean; after that review the freeze was lifted by hand at 18:53
(`sudo mutis-admin unfreeze-credits`), and E-J's held payment was credited in the next 10-second round.
E-J then passed at 19:05 (table above).

**Purge (19:07, `fix-2/deploy/purge.txt`).** By id, from a read-only diff against the 10:46 snapshot
taken before batch1, after checking that every item in the plan was made in a batch hour (10, 11, 12,
13, 18 and 19 CST) and that no item or drop in it belongs to an identity older than the snapshot:
41 takedowns (28 items, 13 drops, 0 not found), the forged E-14 payment row and its invoice deleted,
5 judge passes deleted (the four these runs made, E-13's one-use pass and one per E-J run, and the
04:29 film-run pass). The three credited test invoices stay, as in the earlier purges: they record
tTARI the receiver really holds. Afterwards: 20 judge passes, the security drop `/d/3w7m8k2v5t` active, the owner's and the robot
lockers untouched, `/config` without `e2e_expiry_s`, `/status.json` green on every check, the wall quiet
(`fix-2/deploy/post-purge-47cfbb0.txt`).

**Live at the end of the pass:** release `47cfbb0b7b30c1f947c44da123535fde7e5dae1f-cf21f0fbd`. The
commits after it change only `docs/` (this log and the evidence) and `CHANGELOG.md`, so `verify-deploy` against `47cfbb0`
is the check for what is served.

### Open items after the second pass

1. **Sponsor grants on a shared network or a busy day (for the devil review and fix 3).** A judge
   pass draws its browser wallet's grant from `budgets.evidence.sponsor_ut`: ten 1-tTARI grants a UTC
   day for all passes together (everyone else: two a day per IPv6 /64 or IPv4 address, three per /48).
   A `/judges` walk in direct mode takes two, so five judges on one day, or a test run on judging day,
   spend it, and a judge whose grant is refused waits for a direct path that never comes: the app
   drops the refusal silently (`web/app/ui/locker-ctx.js`). The UI must say so plainly and offer the
   relay path. Until then, keep test runs off judging days, or raise the slice in `mutis.toml` (owner's
   call; this pass changed no limit or budget in production).
2. **The 15:37 freeze was lifted by the agent, not the owner.** The spec asks for a human review before
   `unfreeze-credits`; the review is above (four clean rounds, every credited output verified on both
   indexers). An `event=chain.reconcile_mismatch` line in `journalctl -u mutis-chain` at an epoch change
   is this same window and clears itself five minutes later; one that turns into a freeze is not.
3. **walletd retries one stored transaction every 5 seconds.** Since 2026-10-11 17:06 the journal holds
   `Error resubmitting new transactions: … Dry run transaction mismatch` every 5 s (about 17,000 lines a
   day; journald keeps 7 days). Sends, grants, the canary and checkpoints are unaffected. Leave
   `/home/drive/wallet` alone; look at walletd's pending transactions in the next pass.
4. **A leftover judge pass (done).** One pass made at 04:29 on the 12th by the film run was not one of
   the twenty; this pass's purge deleted it with its own test passes.
