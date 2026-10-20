<!-- SPDX-License-Identifier: MIT -->
# Owner 5: canary keys that survive a restart, /verify/tx on one line, a steady pay page whose steps move, the mainnet date (2026-10-19)

Four requests from the owner and one addition to the third (3b), fixed on the branch `fix/owner-5` and pushed to `main`. **No deploy, and mutis-chain was
not restarted**: the integrator deploys. Evidence: [`docs/evidence/2026-10-19/owner-5/`](../evidence/2026-10-19/owner-5/).

## 1. The canary list on /made#check

On /made#check, under a headline that said "Every check is working.", the list showed one line per test file:
"Test file #150: missed (the verifier restarted)." through #172 (24 lines, #150 to #173, when this pass read
`/api/v1/canary`).

**Cause.** The verifier sidecar keeps each canary's file key in its own memory (`web/app/sidecar/sidecar.mjs`,
`canaries`), and the chain worker asks it for the key once the canary is a day old (`_reveal_canaries`). The sidecar
restarts whenever mutis-chain restarts (a deploy), and also when a request to it times out or it crashes. Each
restart lost every key not yet published, so every test file younger than a day showed as missed a day later. One
deploy wiped a day.

**(c) The keys now survive a restart, from the delivery that is already on the Ootle.** The promise the page makes
(the /made copy, `docs/api.md`, the threat model): the canary's key "left on the Ootle, sealed to our own test
drive"; "we publish its key a day later"; an hour whose key is lost is listed as missed, never skipped. The delivery
(a kind-3 blob in a stealth output's memo, sealed to the robot drive) carries the link's secret `s`, not the file
key. The file key sits in the link's row, wrapped under `HKDF(s, "share-wrap")`, and the cleanup erases that
wrapped key when the link expires, 24 hours after sealing. The reveal is due at that same moment or later (the
worker reveals once an hour). So the delivery alone can't give the key back, and the worker keeps a copy of the
link's 60-byte wrapped key:

- `seal_canary` stores the wrapped key with the canary's log entry (`canary_log` in the database's meta table).
  Canaries sealed before this change get their copy at the new worker's first tick, while their link is active
  (`_keep_wraps`).
- At the reveal the worker asks the sidecar first, as before. If the sidecar no longer knows the key, the worker
  finds the delivery's outputs in the mirror and scans them with the robot drive's view key. It then asks the
  sidecar's new `recoverCanary` command: the robot drive's keys open the delivery, the share id must be this
  canary's, `s` gives the wrap key, and AES-GCM opens the kept copy under the header's hash. A key that opens is
  the one that file was locked with.
- The copy is dropped at the reveal, whether the key was published or missed. A key that neither path gives back is
  published as missed (`chain.canary_missed`), and the worker never asks again. A sidecar that is down only delays
  the reveal to the next hour.
- `/api/v1/canary` builds its answer field by field and never shows the copy.

**The trade-off.** For about an hour longer than before, the database holds the canary link's wrapped key: until the
reveal (24 to 25 hours after sealing) instead of until the link expires (24 hours). The daily backup can catch it.
The copy is useless without the link's secret, which exists only in the delivery, sealed to our test drive. The
chain worker holds that drive's keys and already opened the delivery every hour for its health check, so nothing
new can read the canary. The worker learns the file key only when it is due to publish it. User links are unchanged.
The other option in the brief (the file key itself encrypted at rest) wasn't needed. It would have meant a key that
lives in a sidecar which can't write files, and a second copy of the secret to look after.

**(a)** Misses in a row are one line: "23 test files missed (#150 to #172): the verifier restarted." A single miss
reads "Test file #173 missed: the verifier restarted." Each run is on its own line (`web/site/js/canary.js`,
`missedLines`). DESIGN.md bans en and em dashes in visible text, so the range is written with "to".

**(b)** The status line never says "Every check is working." while a test file missed its key in the last 24 hours.
`/status.json` comes from the health check, which doesn't count reveals. So the page reads the misses from the same
`/api/v1/canary` that "Try to read one of our files" loads, and counts those whose key was due in the last 24 hours.
All green with misses reads "24 test files missed their key in the last 24 hours. Every other check is working.
Checked …", and the dot turns amber. Amber or red keep their reasons and add the same count.

**(d)** Nothing to code: the integrator won't restart the sidecar until judging ends. The next deploy's restart (the
one that ships this fix) is the last one that can lose keys, and only until this code is live. Even that restart
loses at most the canary whose link expired in the hour before the restart and whose reveal hadn't run yet: the new
worker copies the wrapped key of every canary whose link is still active, and reveals at its first tick. A release
that changes only the front end can keep the old worker running (`MUTIS_KEEP_CHAIN=1`, on `main` from the deploy
pass). This change is not one of those: it changes the chain worker and its sidecar, so its deploy restarts them once.
While this pass ran the server rebooted (not by this pass): mutis-chain started again at 02:33 UTC on 2026-10-20,
still on the old code, so the test files sealed in the day before it will show as missed once their keys are due.

**Proof.**

- `server/tests/test_canary.py`. `test_a_restart_loses_no_key` takes the sealed key from the sidecar, then restarts
  the worker and its sidecar (a new process that knows no canary). It lets the link expire (its wrapped key is
  gone from the row), then checks that `/api/v1/canary` publishes the same key and that the copy is gone.
  `test_a_canary_sealed_before_the_log_kept_copies_gets_one_while_its_link_lives` covers the deploy transition.
  `test_a_key_neither_the_verifier_nor_the_chain_gives_back_is_published_as_missed` gives one canary no copy and
  another a copy that isn't its link's: both are missed, and the worker asks nothing again.
- `server/tests/test_real_sidecar.py`, on the server with the pinned ootle-wasm 0.46.0 and Node 20: the real
  sidecar's `recoverCanary` returns the key it sealed. It refuses another drive's keys (`cannot_open`), another
  link's id (`other_share`), and another header or wrapped key (`cannot_unwrap`) (`suites/sidecar.log`).
- The site suite's canary check: a fixture with #789 to #791 and #787 missed reads "3 test files missed (#789 to
  #791): the verifier restarted." and "Test file #787 missed: the verifier restarted." on two lines. The status line
  reads "4 test files missed their key in the last 24 hours. Every other check is working." with all green, adds
  the count to amber, and reads "Every check is working." when nothing missed.

## 2. /verify/tx: one line each, and a link to Tari's own indexer

**Cause.** The app's `ui/lines.js` puts a `<br>` after every sentence in a paragraph (DESIGN.md, the One Sentence A
Line Rule), so each fact on `/verify/tx` was two lines.

**Fix.** The two facts are built without that break: "The Tari chain accepted this transaction, and it is final.
Anyone can check it on Tari's own indexer." and "The chain shows a payment with a hidden amount and a hidden owner.
The fee is public." DESIGN.md names this as the rule's one exception, the owner's. "Tari's own indexer" links to
`https://indexer.esme.tari.com/transactions/<id>` in a new tab (`rel="noopener"`, `referrerpolicy="no-referrer"`).
A plain link is a navigation, not a fetch, so the CSP's `connect-src` is unchanged. `tools/lint.py` allows that origin
in served code next to the two indexers, as a link target.

**Why that page.** With two real ids, the release notarization of 2026-10-11 (`8c6227fd…` in `/releases.json`) and
the canary delivery of 2026-10-19 (`aae9b98a…` in `/evidence.json`), `indexer-link/probe.py` found:

| What | Old id (2026-10-11) | New id (2026-10-19) |
|---|---|---|
| `ootle-indexer-{a,b}.tari.com/transaction-receipts/<id>` | 200 JSON, CORS `*`, `"outcome": "Commit"` | the same |
| `ootle-indexer-{a,b}.tari.com/transactions/<id>` | 404 (the indexers drop it after a while) | 200 JSON |
| `indexer.esme.tari.com/transactions/<id>` (the indexer's own web page) | Transaction Details, Decision: Commit, the receipt (epoch 12149), the fee | the same, epoch 12491 |

The indexer's JSON opens in a tab as raw text. The indexer's page is for people: it says Commit, the epoch and the
fee, and when validators have dropped the full result it shows the committed receipt and says so. It is Tari's own:
it is on tari.com, and a Tari contributor pointed to it when closing the issue for an official explorer
(github.com/tari-project/tari-ootle/issues/2224, 2026-10-08). An Ootle explorer for Esmeralda exists only as a
community project (explorer.tari.mw, "not affiliated with or endorsed by the Tari Project"), and `explore.tari.com`
shows the base layer only, so neither is linked. Screenshots: `indexer-link/*-page.png`.

**Proof.** The UI suite's `ux-drop` checks the paragraph's words, no `<br>` in either fact, the link's text, its
`href` for that transaction, `target="_blank"` and `noopener`.

## 3. The pay page flickers

**Reproduced** in headless Chromium on the server (the UI suite's dev server and its pay fake), with a recorder in the
page from its first script. It notes layout shifts (`PerformanceObserver`), redraws of the whole page, every QR
code built, frames in which the address showed without its code, and every frame in which a part of the pay card
moved or resized. The scenario is `pay-steady` in `web/app/ui/tests/flows_pay.py`.

**Causes, measured.**

1. **The page redrew all of itself on every poll.** While a claim waits, the page asks about it every 3 seconds. Each
   answer replaced the whole page and built the address's QR code again. The code arrived a moment later (a dynamic
   import), so for a frame the card had no code: the address moved up 25 px and the card shrank 48 px, then grew
   back. In the ten seconds after "Another Ootle wallet" opened, the page redrew itself 6 times and built the code 4
   times, with 5 frames without it. That was the flicker.
2. **A browser with a drive** (production runs in direct mode): the drive check answered after the first screen and
   redrew it, inserting Pay from my drive and pushing everything below it down 108 px.
3. **A late font on phones:** the drive's look uses its own Geist subset, which could swap in after the first screen
   and move the whole card 20 px (seen in one of our runs).

**Fix** (`web/app/ui/paypage.js`, `web/app/css/drive.css`).

- A draw that would show the same thing is skipped: the page compares a plain serialization of its new tree with
  the last one drawn. The address keeps its selection, the status isn't read out again, and nothing is rebuilt.
- The QR code is drawn with its address: the module is loaded before the address first shows, or with the link's
  data when a kept claim has one. A draw puts the same code back through an empty placeholder, so a slot never
  shows without it. The wait's clock and an open folder's panel are kept the same way.
- The link's data, whether a drive is in this browser, and the QR module are fetched together. Then the drive's
  look and the first screen arrive in one step, after the drive's Geist subset has loaded (at most 1.5 s).
- A drive in this browser gets its line from the first screen: "Checking your drive here…", held at the height of
  Pay from my drive and its note (`.pay-drive`). Its answer (the button, or why there is none) takes that line and
  moves nothing below it.

**Proof**, `pay-steady/before.json` (`main` at `13382af`) and `after.json` (this branch), each from one run of the same
scenario:

| Stretch | Before: shift after the card is drawn, redraws, moving frames, QR codes built, frames without the code | After |
|---|---|---|
| A stranger's first screen (computer) | 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0 |
| Another Ootle wallet opens (to 10 s after) | 0.0104, 6, 5, 4, 5 | 0, 2, 2, **1**, **0** (the two are the box opening) |
| While the page polls, address shown (10 s, three polls) | 0.0052, 3, 2, 3, 2 | **0, 0, 0, 0, 0** |
| A reload with the claim kept | 0, 3, 3, 3, 5 | 0, **0, 0**, 1, **0** |
| A phone with a funded drive | 0, 1, 1 (everything below moves) | 0, 1, 1 (only the held line's own answer) |

Pay from my drive and its note fill the held line exactly at 390, 360 and 1440 px (92 of 92 px). The total layout
shift on arrival, 0.046, is the same before and after (under the 0.1 that counts as good). It comes from the link
page's own header and footer giving way to the drive's in the frame the card first shows, before anything in the
card exists. Removing it would mean starting `/p/` in the drive's look from the HTML, in the shared header partial
this pass doesn't touch.

An independent review (the code-critic agent, over the diff) failed the first version of this fix on one point: the QR
module loaded only when a kept claim had an address or Another Ootle wallet made one, so after a payment that spent
nothing (Pay with test money or Pay from my drive refused), the claim's address showed with no code for the rest of
the visit. Now every new claim loads the module before its address can show, and `pay-drive` checks the code after a
refused payment. Its smaller points were taken too: a failed drive lookup can't stop the page, the held drive line
waits 30 s at most, a canary whose file is gone drops its copy, a recovery interrupted by the verifier keeps what the
pass already published, and the sidecar's protocol test covers `recoverCanary`.

## 3b. After paying, the steps move (the owner's addition)

After Pay with test money the screen sat on "Waiting for your payment" for about 7 seconds, then everything appeared
at once. The owner asked for live progress: the step in progress turning, each step ticked as its event arrives (or,
if the events arrive together, the step in progress animated with its time), `aria-live="polite"`, words and the time
instead of motion under reduced motion, with `ui/progress.js` and `flow.css`, the drop page's steps.

**What the API returns over time.** On production with this branch's front end (`pay-progress/production-after.json`,
the audit's timeline, a real payment of test money): the steps showed 0.24 s after the click, while the claim and
the demo payment did their proofs of work ("Getting ready…", 1.9 s). The demo wallet's transaction id came with the
claim's status at 3.8 s. Seen, paid and released came together at 8.6 s, in one answer. They do arrive together: the
payment checker finds the payment with the seller's sales key and confirms it on an indexer in the same step of the
chain worker (`verify_sales`, then `check_pending`), and the next poll releases it (`get_claim`). So the steps tick
when their state arrives, seen and on the chain together, and the step in progress shows what it waits on.

**Fix** (`web/app/ui/paypage.js`, `web/app/ui/progress.js`, `en.json`).

- The pay page draws its steps with `ui/progress.js`, as the drop page does: the dot of the step in progress turns,
  its time counts up from 2 s ("0:04"), a note under it says what it waits on, a bar under the steps sweeps, and done
  steps get their check. The run is kept across the page's draws, so the clock never restarts.
- The notes follow the real events: "Getting ready…" (the proofs of work), "Our demo wallet is sending it…" (the
  demo payment accepted), "Sent. Checking the chain…" (its transaction id arrived), "Checking the chain…" (a payment
  from another wallet, seen).
- Pay with test money shows the steps from the click, as Pay from my drive already did.
- While a payment is on its way the page asks every 1.5 s instead of 3 s (the server allows 60 a minute per network).
- The live region that says each step (`role="status"`) carries `aria-live="polite"`. Under reduced motion the
  site's rule stops every animation: the dot doesn't turn and the bar doesn't sweep. The words, the time and the
  ticks still say where the payment is.
- **The colour.** The owner asked for a lime dot. DESIGN.md's Lime Is Yours rule says lime never goes on status or
  on anything that is a Tari payment, so the dot turns in ink, like the drop page's. Making it lime would take one
  line in `flow.css` and an exception in DESIGN.md, if the owner wants it anyway.

**Proof.**

| | Before | After |
|---|---|---|
| Production, a real payment of test money (the audit's text timeline, `pay-progress/production-*.json`) | steps at 0.88 s, then the same words for **18.2 s** until it opened (19.1 s) | steps at 0.24 s; new words at most **1.9 s** apart (the note, then the clock every second); open at 8.6 s |
| The UI suite's `pay-progress`, with production's timing replayed (transaction at 2.5 s, paid at 7 s) | steps 0.41 s after the click; **9.1 s** with nothing new to read; no time, no note, no live region | steps at 0.04 s; at most **1.6 s** without something new; clock 0:02 to 0:07; the notes in order; a polite live region |
| The same with reduced motion | 9.1 s still | 1.6 s, no animation running in the steps |

The audit's own "longest still" can't show this: it counts a running animation as life, and the old page's small
spinner kept turning, so it measured 0.16 s before. Its text timeline shows what a person read
(`pay-progress/production-before-steps.png` and `-after-steps.png` are the screen during the wait).

## 4. "Ootle mainnet: Nov 11, 2026"

The date came from a note marked inferred, and the owner asked to check it and to make the label say it is the launch
date. Tari's own sources, read on 2026-10-19:

| Source | Date | What it says | Whose |
|---|---|---|---|
| [tari.com/updates/2026-09-01-update-143.html](https://tari.com/updates/2026-09-01-update-143.html) | 2026-09-01 | "The big one: the Ootle (Tari's Layer 2) is confirmed for November 11th." Its schedule: "November 11: Migration Event - Ootle Showcase" | Tari Council |
| [tari.com](https://tari.com/), the banner | live on 2026-10-19 (added by [tari-dot-com#117](https://github.com/tari-project/tari-dot-com/pull/117), merged 2026-09-22, for issue #116 of 2026-09-18: "The Ootle is dropping on November 11th!") | "The Ootle, Tari's Layer 2, launches on November 11th." | Tari's site |
| [community.tari.com/t/323](https://community.tari.com/t/ootle-launch-date-and-launch-contest-rules/323) | 2026-09-01 (edited 2026-09-09) | "The Ootle launches November 11, 2026!" | a Core Contributor, for the Council |
| [community.tari.com/t/397](https://community.tari.com/t/extra-contest-ootle-security-bug-hunt/397) | 2026-10-01 (edited 2026-10-12) | "The Ootle launch is on the horizon. To help refine things ahead of mainnet, … we're holding a security bug hunt!" | the same |

The date is Nov 11, 2026, confirmed. No source says Nov 19 or any other day, and none gives an hour, so the phase
still turns at 00:00 UTC. Tari's X account couldn't be read here (the fetch was refused), and the tari-ootle
releases (to v0.46.1, pre-releases) name no date. The date stays as it is in `web/shared/dates.js` and in
`ootle.mainnet_date`, and each now names its source.

**The label** now says it is the launch date, not a version: "Esmeralda testnet: tTARI is test money, worth nothing.
Ootle mainnet launches Nov 11, 2026." This applies to the footer and its status-line partial, the app's money screens
(the pay page among them, `testnet` in `en.json`) and the film's end card. The claim registry's C19-k holds the new
sentence and its source; /made already said "Ootle mainnet launches …".

## Tests

On the server as the unprivileged user (`suites/`). The first full run was on the branch before the brand kit and
the upload-safety pass landed on `main`; the last run is on the final tree, rebased on them.

| Suite | First tree (`suites/first-tree/`) | Final tree (`suites/final-tree/`) |
|---|---|---|
| Lint, check-copy | PASS, PASS | PASS, PASS |
| Server | 333 run, OK (5 skipped: the opt-in real-sidecar tests, next row) | 343 run, OK (5 skipped, the same) |
| Real sidecar (`MUTIS_SIDECAR_DIR`, Node 20, ootle-wasm 0.46.0) | 4 OK, `recoverCanary` among them | 4 OK |
| Site | 41 of 42: `motion` left one thing hidden on `/` once; it fails one run in three or four alone, on `main` too (`suites/site-motion-on-main.txt`), then passed (42 of 42) on the next tree | 41 of 42: `V-01` (/v2's loops) said a loop played off screen; alone it fails the same way on `main` while the server is loaded (load average 7 to 9 with the UI suite running, `suites/site-v01-under-load.txt`); the canary check (`check_reveal`) passes |
| App core (`run_all.py`) | ALL PASS (9 steps) | ALL PASS (9 steps), run alone; the same suite under load earlier missed its scan-speed floor (1,617 rows/s of 2,000) and a phone scan's time limit |
| Deploy | 89 OK | 96 OK (the upload-safety pass added tests) |
| UI | 812 of 812, `pay-steady` among them | 784 passed and 2 failed when the server rebooted in the middle of the run (it stopped at `ux-drop-phone`): `share-rules` (the share dialog didn't open within 20 s after a reload) and `ux-drop` (the browser closed). Those two and every scenario after them, run again: 135 of 136, `share-rules` again; alone it passes on this tree and on `main` (27 of 27 each, `ui-share-rules-alone*.log`) |

The pay page's later changes ran first in the scenarios that touch them (`suites/pay-and-drop-ui.log`: `pay-page-states`,
`pay-drive`, `pay-steady`, `pay-progress`, `share-pay`, `sell-stop`, `owner-check`, `ux-drop`, `ux-drop-phone`):
178 of 179. The one failure was the test, not the page: `pay-page-states` checked that test money paid the claim right
after the steps showed, which is now at the click, before the demo payment's proof of work; it waits for the payment
now. The final tree's UI run has it.

**End to end on production** (`suites/e2e-E-29.*`): `E-29`, a drive sells a folder of three, a phone with no drive
pays it with test money (a judge pass), opens one file, reloads, and reads the payment on `/verify/tx`: PASS (45.5 s).
It checks production's front end as deployed today; this branch's pages reach production with the integrator's
deploy. The UX audit's two runs (3b) made two more test drives on production, both deleted with Delete my drive;
`E-29`'s seller drive is left to the inactivity rule, its pay link ended (`mutis-admin takedown share`).

## Not done, and open

- The link page's own header and footer still give way to the drive's when `/p/` opens (layout shift 0.046, the same
  before and after; above).
- The status line counts misses in the browser, from `/api/v1/canary`. `/status.json` itself (the health check, in
  `deploy/`, outside this pass) still says green when a reveal was missed.
- The pay steps' dot is ink, not the lime the owner asked for (3b): DESIGN.md's Lime Is Yours rule keeps lime off a
  payment's status. One line in `flow.css` if the owner wants lime anyway.
