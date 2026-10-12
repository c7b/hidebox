<!-- SPDX-License-Identifier: MIT -->
# Fix pass after the judge-run and claims reviews (2026-10-11/12)

Two devil's-advocate passes ran against the live site on 2026-10-11: a judge run (the Council guide on
emulated phone and desktop) and a claims and security pass (headers, TLS, limits, every privacy
sentence against the shipped code and config). This log takes each finding, says whether it held up
against the code, what changed, and where the evidence is. Times are CST (UTC−6). Nothing here is a
secret: no owner key, no judge pass, no transaction id of a test send.

The reviews' own blind spots stand: every browser ran on ultron itself (no real network latency),
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
| 22 | `/how` and `/privacy` promise every database copy is deleted after 7 days, but root's `/var/backups/mutis/pre-golive-…/` holds database copies (rehearsal and test data, no real visitors) outside the pruned folder (low, claims) | **Confirmed.** Ten `.sqlite3` copies plus `-wal`/`-shm` from 2026-10-11; all younger than 7 days, so nothing was deleted now. | `backup.py prune-root`, run as root as the first step of `mutis-backup.service` (systemd's `+` prefix on one `ExecStartPre`), deletes files named like a mutis database (`.sqlite3`, `-wal`, `-shm`, `.part`) under `/var/backups/mutis` at the published age; wallet tars, balance snapshots and config copies never go, whatever their age (test). The unit is installed on ultron (`install` + `daemon-reload`); the runbook's table says so. | `deploy/scripts/backup.py`, `deploy/systemd/mutis-backup.service`, `deploy/tests/test_ops.py::test_roots_database_copies_go_at_the_same_age_and_nothing_else`, `test_config.py::test_root_runs_only_the_backup_prune`, `deploy/README.md` |
| 23 | Caddy: an unknown Host gets a bare 200 without the security headers; port 80 answers a 308 to the reflected Host (low, claims) | **Confirmed.** | A `(misdirected)` snippet (security headers, site CSP, `no-store`, 421) imported by `https://` and `http://` catch-all blocks after the site; the local stack rewrites them onto its ports; D-01 checks a made-up Host on both ports (421, the headers, nothing reflected); deploy test; `caddy validate` passed on ultron before the deploy (activate-release validates every changed Caddyfile before reloading). | `deploy/caddy/Caddyfile`, `tests/e2e/localstack.py`, `tests/e2e/test_headers.py`, `deploy/tests/test_config.py` |
| 24 | A 6 MB `PUT …/chunks/0` answers 502 with an empty body (Caddy's 5 MB `request_body` fails mid-read inside the buffering proxy) instead of a 413 in the API's JSON shape, so the app shows a server-down error (low, claims) | **Confirmed.** The app's chunks are 4 MiB + 16 B, so only a hand-made client met it; the app would still have said "Our server tripped". | A declared `Content-Length` over 5 MB answers 413 in `http_util.ApiError`'s shape (`too_large`, `max_bytes`) before a byte is read; the app's `describe()` maps a server-side `too_large` (through a `SealError` too) to `error.too_large_request`, which names the limit, EN and ES; D-01 sends a 6 MB chunk; the app-ui `safety` flow answers a chunk with that 413 and reads the banner. | `deploy/caddy/Caddyfile`, `web/app/ui/errors.js`, `web/app/i18n/*.json`, `tests/e2e/test_headers.py`, `web/app/ui/tests/flows.py`, `deploy/tests/test_config.py` |
| 25 | `hosting.snapshots = "weekly"` and "keeps them for a few weeks" were never checked against the Hostinger panel (low, owner) | **Confirmed** (an unverified claim). | The sentence on `/how`, `/privacy`, `/faq`, `llms-full.txt` and the app's claim `c5snap` now says, in both languages: our host (Hostinger) can take weekly snapshots of the whole server; we haven't switched them off, and we haven't yet confirmed in its panel how long it keeps them. Open item 5: the owner checks the panel; the config and the copy follow. | `web/site/pages/{how,privacy,faq}.html` (+ES), `web/site/static/llms-full.txt`, `web/app/i18n/*.json` |
| 26 | `/judges` links the forum root instead of a thread (low, owner) | **Confirmed, left as is.** | Nothing until the owner posts the thread (open item 2). | — |

Items 20–26 were handled in the continuation of this pass (the claims review's list had reached the
first pass truncated after item 19).

## Suites run after the changes

On ultron as `build` with the server's Python 3.13, Node 20 and Chromium 154, from a tarball of the
tree that became commit `7c9e627` (logs in `docs/evidence/2026-10-11/fix-pass/suites/`):

| Suite | Result |
|---|---|
| server (`python3 -I -m unittest discover -s server/tests`) | 197 tests OK, 4 skipped (the deploy gate's run as `build`: OK, 5 skipped) |
| site (`web/site/tests/run.py`, static and browser checks) | 28 of 28 (a first run failed the judge-pass check, item 6's hash-change fix) |
| app-ui (`web/app/ui/tests/run.py`) | 229 of 229 (a first run failed once: the new 413 case had counted as an upload for a later check; moved to its own actor) |
| app-core (`web/app/tests/run_all.py`) | ALL PASS, 9 steps (lint 824/824, cross-check 80/80, KATs 118/118 under Node and in Chromium, jitless 75/75, sidecar 16/16, PoW and scan benches, contract 12/12 against `mutis-api --dev`; the two contract expiries now expect the hour rounding of item 16) |
| deploy tests (`deploy/tests`, locally) | 65 OK |
| `tools/lint.py` · `tools/check-copy.py --config <live /config>` | PASS · PASS (3 phrases to read, as before) |
| D-01 on the throwaway stack (`test_headers.py --local ultron`, the real Caddy 2.6.2) | PASS, 413 shape and 421 on both ports included |

Deployed as release `7c9e6279927e4ed3bc12558cfaec27bb280056ff-c9a2957d0` at 22:11 (`deploy.sh HEAD`: gates,
build, activation, smoke PASS, manifest notarized in tx `f64332b5…09a2`); `verify-deploy` 0 differences
across 143 files; `/status.json` overall green; D-01 against production PASS (certificate 89 days
left). The changed `mutis-backup.service` was installed by hand (`install` + `daemon-reload`, the
notice activation prints); `backup.py prune-root` run once as root deleted nothing (every copy is
younger than 7 days). The production E2E and judge runs are under "Evidence" below.

## Evidence: the production E2E and judge runs (`docs/evidence/2026-10-11/fix-pass/e2e/`)

Every scenario ran against release `7c9e627…-c9a2957d0` with `run.py --chain --final`, in batches:
every browser runs on ultron, so all actors share one /64, and the API allows five new lockers and
five new drops per network an hour (tests/e2e/README.md). `e2e_expiry_s = 60` was in the config for
the first batch only (E-05) and removed, `mutis-api` restarted, before the second; `/config` carries
no `e2e_expiry_s` now.

| Run | Scenarios | Result | Where |
|---|---|---|---|
| batch1, 22:21 | E-01, E-02, E-04, E-05, E-06, E-07, E-08, E-11, E-13, E-14, E-15, E-16, E-17, E-18, E-19, E-20, E-21, E-22, E-24, E-25, E-03 | 20 of 21 PASS; E-13 FAIL (below) | `batch1.log`, `reports/batch1-*.json`, `shots/batch1-*` |
| batch2a, 23:28 | E-09, E-10, E-13 | E-09 (23 s) and E-10 (52 s) PASS; E-13 FAIL (below) | `batch2a.log`, `reports/batch2a-*.json` |
| batch2b, 23:40 | E-13 | PASS, 30 s: the browser wallet received its grant, Waiting → Seen → Amount proven → Added, paid by the browser, quota +2 GiB | `batch2b.log`, `reports/batch2b-*.json` |
| batch2c, 23:41 | E-12 | PASS, 30 s | `batch2c.log`, `reports/batch2c-*.json` |
| batch2d, 23:53 | E-J, direct mode | FAIL at B1: the computer's locker was refused with "Easy. You can do that again in 10:49" (429 `rate_limited`): E-J's phone had been the fifth new locker of that hour on ultron's /64, the limit working as published | `batch2d.log`, `reports/batch2d-*.json` |
| batch2e, 00:17 | E-J, direct mode | PASS, 1.5 min (track A 5 s, track B 84 s; B1 4 s, B2 27 s, B3 14 s, B4 13 s, B5 2 s, B6 22 s, B7 1 s); cold start 60 s (the grant spendable within 3:15); B3 and B6 built and submitted by the browser; B7 lists the exit receipt from A3 | `batch2e.log`, `reports/batch2e-*.json`, `shots/batch2e-*` |

So every scenario of §17.2 and E-J in direct mode passed on the new code, each at least once after
its last change.

**E-13 failed twice, both times in the test, not the product.** (1) In batch1 the buyer's fresh locker
got no sponsor grant: the two grants a day per /64 (item 2) had gone to earlier lockers of the same
run, so "Pay 0.5 tTARI from this browser" answered "This browser's testnet wallet doesn't have enough
tTARI for that" and the invoice stayed at Waiting until it expired unpaid an hour later (the failure
screenshot; nothing was credited, as it should be). (2) E-13 was given a one-use judge pass in direct
mode, as E-J has, and still got no grant: item 6 moved the pass from `sessionStorage` to
`localStorage` (`{code, until}`, a week, as a `/judges#pass=` link saves it) and the harness still
wrote the old key, so the app never sent `X-Mutis-Judge`; E-J's direct run would have failed the same
way. The harness now writes what `store.saveJudgePass` writes, and E-13 waits for the grant to be
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
