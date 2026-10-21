<!-- SPDX-License-Identifier: MIT -->
# UX feedback 1: every wait says what is happening, and every result says it worked (2026-10-18)

The owner left a photo at his own drop link from another browser. From Send to the result nothing moved for seven
seconds ("Did it break? Did it work?"). The result was a column of loose lines (Delivered, the chain's name, a bare
transaction id, What the chain sees, Leave another) that did not say what had happened for him. Its link
landed on `/verify/tx` with its record as raw fields: fine for a nerd, no use for anyone else. He asked whether
other corners of the app had never been checked this way. This pass measures every flow on production, then
fixes the waits and the results with one component for each, used the same way everywhere.
The raw evidence (`docs/evidence/2026-10-18/ux-feedback-1/`) was pruned on 2026-10-20; the results it recorded are below.

On the branch `ux/feedback-1`, pushed to `main`. **No deploy, no tag move**: the coordinator deploys.

## The audit

Every flow the brief names, on production (`https://hidebox.app`, `main` at `5677e45`), in headless Chromium on the server
as `build` (`audit.py`). A recorder in each page notes every 120 ms whether what a person reads in the flow changed or
something on it moves; a flow's **longest still** is the longest stretch with neither, from the person's action to the
result (a page load: from navigation). The computer is 1440 x 900; the phone is the e2e's Android profile (412 x 915,
touch, 4x CPU throttling) on DevTools' Slow 4G (562.5 ms, 180,000 B/s down, 84,375 B/s up). The photo is a generated
2000 x 1500 JPEG with a phone's GPS headers (1.1 MB). **After** is this branch's front end on production's API and
chain: `audit.py --candidate` serves the built pages, scripts and styles to the test browser through CDP (production's
headers and CSP kept; nothing deployed). Those files come from the workstation one request at a time and unthrottled, so
an after page load's **total** is not comparable with before; its stills are. Totals with the chain vary with the
relay's random wait (5 to 45 s). Two test drives were made and deleted with Delete my drive; one empty drive of a run
that broke before its key was saved is left to the inactivity rule. Results: `audit/before.json`, `audit/after.json`.

| Flow | Profile | Before: longest still (total), what stood still | After: longest still (total) |
|---|---|---|---|
| **Drop page: pick → Delivered** | computer | **20.5 s** (21.0 s): "Sending it by Tari…" | **0.24 s** (25.3 s) |
| **Drop page: pick → Delivered** | phone | **31.5 s** (48.6 s): "Sending it by Tari…" | **0.77 s** (59.6 s) |
| Drop page opening (Tari's library) | phone | 4.6 s (10.6 s): "…" | 0.89 s: the ring, then "Checking the drop…" with its clock |
| /verify/tx right after a delivery | computer / phone | 0.59 s / 3.6 s ("…") | 0.21 s / 0.84 s |
| /verify/tx, the release's notarization | phone | 4.0 s (6.8 s): "…" | 0.88 s |
| **Home quick share, the photo** | phone | **13.8 s** (19.6 s): "Locking it up." while the one chunk uploads | **2.8 s** (20.8 s): the first moment after the pick, before the busy line appears (open, below) |
| Home quick share | computer | 0.27 s (0.52 s) | 0.56 s (1.34 s) |
| Folder link on a phone: the page, then the list | phone | 3.9 s (9.3 s) "…"; 0.64 s "Opening it." | 0.92 s; 0.30 s |
| Pay to open, the first sale | computer | the pay page: "This link isn't ready to sell yet. … Try again in a few minutes." and it never asked again (a person had to reload) | the page asks again every 10 s under "Waiting for the owner's drive" with its clock (not met again on production: the second drive's seller was ready at once) |
| Pay with test money → Open it | computer | 0.24 s (9.6 s, the steps already turned) | 0.25 s (25.9 s) |
| Make my drive; Make my drop link | computer | 0.28 s (1.1 s); 0.20 s (0.4 s) | 0.15 s; 0.12 s |
| Upload a photo; a folder of three | computer | 0.13 s; 0.22 s | 0.32 s; 0.23 s |
| Share: Make link; Copy link | computer | 0.22 s; 0.15 s | 0.17 s; 0.13 s |
| The link page: Open it | computer | 0.17 s (0.3 s) | 0.20 s |
| Save key file (passphrase); Open my drive with it | computer; phone | 0.24 s; 0.25 s (3.7 s) | 0.20 s; 0.23 s (3.8 s) |
| Received, Activity, the owner's sale in Received | computer | 0.15 s, 0.14 s, 0.20 s | 0.48 s, 0.48 s, 0.79 s (the after page loads, see above) |
| Delete my drive | computer | 0.26 s (3.4 s) | 0.72 s (3.9 s) |

Where nothing stood still for long on a computer, the reason is production's speed from the server itself (no network),
not the screen: the same flows on the phone profile stretch every wait. **What paints.** The screencast of the
computer's drop shows it best: before, Chromium painted **9 frames in 21.4 s**, none between 1.3 s and 21.2 s; after,
**760 frames in 26.1 s** (`film-production/`).

What each flow showed during its waits, and whether failure said what to do:

- **The drop page** (the owner's complaint): a mono "Sending it by Tari…" in a grey box for the whole relay wait and
  the chain, then the result; a failed delivery said what to do ("Try again") but showed nothing of where it had got
  to. The result: loose lines (Delivered., Only that drive can open it., the photo's chip, a check and "On the
  Ootle", the transaction id cut to its first and last eight characters in mono, "What the chain sees →", Leave another), each centred on its own.
- **/verify/tx**: "Reading it from the indexer…" (static, up to 30 s of retries for a new transaction), then the
  record's fields; no summary.
- **The home's quick share**: "Locking it up." with the percent only once a chunk had landed: a one-chunk photo on a
  phone stood still for 13.8 s, then jumped to 100 percent.
- **The pay page** of a first sale: the dead end above.
- **The link and task pages, the drive**: "…" (the task pages) or nothing (the drive) while their scripts load; on the
  phone profile 4 to 4.6 s.
- **Waits that only a slow phone shows** (none over 300 ms on the computer, so not in the table): Save key file
  greyed out its button while PBKDF2 (600,000 rounds) and Tari's library ran; Open my drive did the same while a
  locked key file opened; Make my drop link said "Making it…" with nothing turning; the drive's dialogs (Move,
  Rename, Trash, Delete it after, New folder, Save note) greyed out their button; an upload row sat at 10 % while its
  one chunk travelled. Already moving and kept: Make my drive, the share dialog's Make link, the pay page's steps,
  Received's scan, Delete my drive.
- **Done moments** before: the drop page's loose lines; /send's and Send by Tari's bare tx; elsewhere a toast
  (Copied) or the new state itself, which is enough and was kept.


## What each fixed state shows now

**(a) The drop page while it sends** (`web/app/ui/droppage.js`). One card under the page's intro, in place of the
picker, holds the run: **Locking it in your browser** → **Uploading** → **Waiting for the Tari chain** →
**Delivered**, each lit when its phase starts (`sealItem`'s `encrypting`, `pow`, `uploading`, `finishing`, then the
courier job), with its clock after two seconds and its line underneath: "Taking out where the photo was made…"
while the photo loses its location; "Getting ready to upload" with the bar filling during the proof of work; the
file's size while it uploads; "Sending it by Tari…" while the delivery's proof of work runs; "Our relay sends it in
about 23 seconds." counting down while the bar fills toward the relay's moment; "The chain usually takes a few
seconds." while the chain takes it, and "This one takes longer, up to a minute or two." after 40 seconds of that.
The photo's chip (with Keep the photo as it was) and Stop stay on the card until the upload is done. `lib/seal.js`
now says `uploading` (at 0) when the first chunk leaves, so "Uploading" lights while a one-chunk photo is still in
the air; before, the last word was the proof of work's. The page's first check, which loads Tari's library (the
longest wait on a phone), is the same dot and clock ("Checking the drop…") instead of a still line of mono text.

**Failure** says what failed and what still stands: the step that failed turns red with a cross, the steps before it
stay checked, the bar turns red, and under it "The delivery didn't go through. Your file is stored. Try again." (or,
when the relay could not confirm, "…It may still arrive, so wait a few minutes…") with **Try again**, which retries
only the delivery (the file and its link are kept). A failure before the file is stored returns to the picker with
the error, as before.

**(b) Delivered.** The last check lands, and 0.45 s later the card becomes the done moment: the open box rises, the
photo's glyph drops into it, the check lands; **Delivered.**; "Your photo is in their drive. Only that drive can open
it." (one sentence a line; "Your note…" or "Your file…" for the others); "The Tari chain recorded the delivery." with a
violet shield; the **Receipt** pill (the id's first and last eight characters) to `/verify/tx`; the photo's chip; **Leave another**; then the
stay-unnamed note under a hairline. Everything sits on one axis inside one card (`ux-drop` measures each part's centre
within 2 px of the card's), the heading takes focus, and the page scrolls back to the card if it had been scrolled
past.

**(c) `/verify/tx`** (`web/app/ui/verify.js`). While the indexers are asked, the same dot and clock ("Reading it from
the indexer…"; after six seconds: "A new transaction takes a few seconds to reach the indexers."; the page retries for
about 30 seconds as before). Then, first: the open box with the check landing, **Confirmed.**, "The Tari chain
committed it in epoch 12000, a tick of its clock." Two cards beside each other on a computer, stacked on a phone:
**What this proves** ("The Tari chain accepted this transaction, and it is final." / "Anyone can check it on Tari's
own indexer.") and **What stays hidden**: C36's registered sentence ("The chain shows a payment with a hidden amount and a hidden owner. The fee is public.", one
sentence a line), shown only when every output of this transaction is a Pedersen commitment
with a one-time key (a SealLog checkpoint or any other shape gets **What anyone can see** with the existing "Anyone can
see the fee, and that it happened." instead). Then **Details** (the transaction id, status, epoch,
fee, every output's commitment, amount, owner and memo, the inputs, the indexer that answered and the raw JSON:
every field of before) and **Check it yourself** (the button that asks Tari's indexer, its explanation, the answer):
both open on a computer (768 px and wider) and closed on a phone. A status other than Commit lands a red cross and
**Not confirmed.** with "The Tari chain says {status}."

**(d) The other waits, on the same vocabulary.**

- `/send` and **Send by Tari** in the share dialog: the same steps (Locking the key to their address, Queued, Sending
  on the Ootle, Sent) with the relay's countdown and the chain's line, and the done moment (**Sent**, where it shows
  up, the Tari chain's line, the Receipt, the line about who sent it) in place of the bare tx. `/send`'s failed step
  is now marked (before, a failure reset every step to "to do").
- **The drive's upload rows**: a row whose chunk is on its way, or which is being completed, sweeps (`data-busy`,
  `up-sweep`); before, a one-chunk file's bar sat at 10 % until it was done.
- **Save key file** (the drive's Settings and the first-run key modal): the button turns and says "Locking the key
  file…" while the passphrase's PBKDF2 (600,000 rounds) and Tari's library run; before, it only greyed out.
- **Open my drive**: the dialog's Open turns and says "Opening your drive…" while a locked key file opens.
- **The pay page of a first sale**: "This link isn't ready to sell yet." now says "This page asks again by itself, so
  you can wait here." over "Waiting for the owner's drive" with its clock, and asks every 10 seconds; Pay with test money
  appears when the owner's drive is ready. Before, it said to try again in a few minutes and never did.
- **The link page**: "Checking the link…" and a folder's "Opening it." are the dot and clock; the busy tile while a
  file opens turns (it was a still loader glyph).
- **The home's quick share**: a short bar moves under "Locking it up." (it stood still for 13.9 s on the Slow 4G
  phone while a one-chunk photo uploaded). Paid for inside the widget's A-06 budget (below).
- **Before the scripts run**: the turning ring on the link and task pages and the drive (above).
- Kept as they were, because they already moved: Make my drive (spinner and words), the share dialog's Make link
  (spinner in the button), the pay page's steps (spinners; they now wear `flow.css`), Received (spinner while it scans
  and opens), Delete my drive (count, progress bar, each file into the can).

## Two components, one vocabulary

Both live in `web/app/ui/progress.js` (190 lines, no library) and `web/app/css/flow.css`, which the link and task
pages (`app.html`, `view.html`, in both of its looks) and the drive (`drive.html`) load. Colours name the drive's
token first and the site's second (`var(--success, var(--ok-text))`), so one file reads right in both worlds.

- **`steps(list)`**: the run's real steps in people's words. Each is lit as it happens: a turning dot on the step in
  progress, a green check once done, a red cross where it failed (the steps before it stay checked). The step in
  progress shows the time it has taken once past two seconds (a step that ends sooner shows none, it would only
  flash). One line under it can change while it waits (a function is asked again every second: a countdown, a hint
  that comes after a while). Under the list, a 4 px bar fills when the step knows how far it got (the first chunk's
  encryption, the proof of work, the chunks that reached our server, our relay's countdown) and sweeps when it
  can't (one chunk on its way, the chain). Its markup is the drive's existing `ol.steps` (the pay page's and the
  share dialog's), so the pay page wears the same look without a change to its code; the drive's `.steps` rules
  moved from `drive.css` into `flow.css`.
- **`waiting(text)`**: the same dot and clock on one line, for a wait with one step (the drop page's first check,
  reading a transaction, asking Tari's indexer, the link page's check and a folder's opening).
- **`relayWait(run, not_before)`**: the words under a delivery's chain step. `POST /courier` already answers
  `not_before`, the moment our relay picked to send (5 to 45 seconds out in production's `jitter_s`): the step counts
  down to it ("Our relay sends it in about 23 seconds.") while the bar fills toward it; when the job turns `sending`,
  "The chain usually takes a few seconds." with the sweep; after 40 seconds of that, "This one takes longer, up to a
  minute or two." A browser clock more than a minute off the server's gets the words without the count. The drop
  page, `/send` and Send by Tari use it.
- **`done({...})`**: the moment a run worked, on one axis. The open box (the mark, lime on its ink tile) rises out of a
  38° tilt; what went (a photo, a note, a file glyph) drops into it; a green check lands on its corner (a red cross,
  `tone: 'bad'`, for a transaction the chain refused). Then the title, the line in people's words, the Tari chain's
  line in plain words with a violet shield, the transaction as a violet **Receipt** pill ("Receipt", the id's first and last eight characters, an arrow;
  Tari's colour because it is a Tari receipt), anything beside it (a photo's chip), the next action, a closing note.
  It runs once, about 1.1 s (the box 0.5 s, the file 0.7 s from 0.2 s, the check from 0.76 s, the words from 0.55 s),
  and never loops. The heading takes focus, so a screen reader starts there.
- **Before the scripts run**: the link and task pages showed "…" and the drive a blank screen while their modules
  loaded (4.3 s on the Slow 4G phone for `/verify/tx`). `flow.css` turns both into a turning ring, with no script.

**Motion.** Transform and opacity, plus the 3 px widget bar's `translate`. With reduced motion the site's and the
drive's global rules stop every animation: the sweep becomes a still bar at 30 %, the box and its check are
there at once, the file does not fly, and in the steps and the one-line waits the clock and the words still move once a
second, so those never look frozen. Two places have no clock: the home widget's bar and the drive's upload rows stand
still with reduced motion until the chunk lands (open, below).
One lime per view is kept: the done moment's only buttons are outline (Leave another), and the lime in it is the
mark's, which is not a button (`ux-drop` counts the visible lime buttons and links: only the header's Open your
drive). Lime stays off status, as DESIGN.md says: the check is the done green.

## Copy and claims

New strings (en.json): the drop page's steps (`drop.step.*`: "Locking it in your browser", "Uploading", "Waiting for
the Tari chain", "Delivered"), its notes (`drop.note.pow` "Getting ready to upload", `relay.*` above), the done
line (`drop.done_say.photo|file|note`: "Your photo is in their drive."), `drop.done_chain` ("The Tari chain recorded
the delivery."), `drop.receipt` ("Receipt"), `drive.key.locking` ("Locking the key file…"), and /verify/tx's summary
(`chain.confirmed` "Confirmed.", `chain.when` "The Tari chain committed it in epoch {epoch}, a tick of its clock.",
`chain.proves` "The Tari chain accepted this transaction, and it is final. Anyone can check it on Tari's own
indexer.", `chain.hidden_h` "What stays hidden", `chain.public_h` "What anyone can see", `chain.details` "Details",
`chain.check_h` "Check it yourself", `chain.loading_new`), and `relay.soon` ("Our relay sends it soon.", when the
browser's clock is too far off the server's to count down). Three strings went, since nothing shows them any more: `onchain` ("On the Ootle"), `send.tx`, `tari.tx`.
Each sentence on its own line (`lines.js` splits the done line; the step notes are one sentence each).

**No new privacy claim.** Two of the brief's sample lines would have been. Its second sentence of the human line carries
C25's marker and is none of C25's registered sentences on its own, so the done line keeps the existing "Only that
drive can open it." (it was already on this screen); "Amount and names stay hidden." is in no claim. The chain line says only what
the job's `done` state means (the chain committed the delivery), and what stays hidden is said where it can be read
from the transaction itself: /verify/tx shows C36's registered sentence (`buy.shows`, the pay page's own string, word
for word) only when every output of that transaction is a Pedersen commitment owned by a one-time key, the fields the
record under Details shows; otherwise it says only the existing "Anyone can see the fee, and that it happened." It is
said once on that page (the copy pass's Say It Once rule). "Locking it in your browser" is a step's label, the short
form of C32 (always true), never its sentence. The copy pass's rules hold for the new states: buttons start with a
verb (Leave another, Try again), a failure says what to do, no "Oops". check-copy passes against the registry as it is
on `main` (`5677e45`); the registry was not touched.

## Budgets

Measured by the UI suite on the server (gzip -9 of each file, as the checks count them), against `main` at `5677e45`.

| | Before (`main`, the copy pass's suites) | After (this branch on `main`) |
|---|---|---|
| A-06, the home widget: phone at load / after a drop (of 40,960 B) | 25,001 / 40,536 B | 25,013 / 40,510 B |
| A-06, computer with the code to scan (of 43,520 B) | 43,503 B | **43,477 B** (widget.css +12, seal.js +4, sealing.js −42: its stale ghost comment paid for the sweep; the home card's send step loads `flow.css` itself, so `more.js` is unchanged) |
| A-06d, /drive until the table renders (of 131,072 B) | 118,465 B | **123,329 B**, 38 files: `flow.css` (the steps moved out of `drive.css`, plus the done moment, the bar and the boot ring), the new strings in `en.json`, `turning()` in `drive-parts.js` |
| M-01, the home (of 60 KB) | 58.3 KB | 58.3 KB |
| Fonts, images | | none added; the icons are the Lucide sprite's (`check`, `x`, `loader-circle`, `hidebox`, `file-image`, `file-text`, `file`, `receipt-text`, `shield-check`, `circle-check`, `lock`, `eye`, `chevron-right`, `arrow-right`) |

`progress.js` (about 2.5 KB gzip) is not in either budget's first load: the drop page, /verify/tx, /send, the link page
and the share dialog import it when they show.

## Tests

On the server as `build`, the branch's final tree on `main` at `5677e45` (`suites/`):

| Suite | Result |
|---|---|
| Lint, check-copy | PASS, PASS |
| App core (`run_all.py`) | ALL PASS (9 steps) |
| Deploy | 84 OK |
| Server | 331 run: one error, `test_admin`'s forged payment test, which fails on `main` the same way since 2026-10-19 (above); 331 OK on the same code the day before |
| Site | 42/42 |
| UI | **804/804**: the 751 checks before, `drive-primary` (32) and `drive-v3` (19) among them, plus the new **`ux-drop`** (33: the four steps in order and their words, the clock past two seconds, the sweep and the turning dot while a chunk is held, the size once it leaves, the relay's countdown filling the bar, the chain's line, a forced failure that marks the step and says the file is stored, Try again to Delivered, the heading focused, the done line, the Receipt link to `/verify/tx/<id>`, one lime on the page, every part of the moment on one axis within 2 px, the moment at rest after 1.2 s, the slow indexer line, Confirmed with its epoch, C36's sentence only when the outputs show it, what it proves, Details and the check open on a computer, every field still there), **`ux-drop-phone`** (11: reduced motion shows the moment at once and still, it starts in view, nothing sideways, the folds closed on a phone and opening), **`ux-drive-waits`** (6: the upload row's sweep while its chunk is held and its end; Save key file's turning button and its return) and **`ux-widget`** (3: the busy bar moving). `deaddrop` waits for the indexer check's own line (it waited for a class the check no longer draws) |

`drive-delete-account` failed in two of four full runs of this branch and passed in the others; three runs of it
alone on `main` and on this branch failed once each (`suites/flake-drive-delete-account.txt`), so it is the existing
race, not this pass. A review by the code-critic agent (independent, over the diff) failed the first version on five
points, all fixed: an upload row lost its sweep and its Uploading as soon as the next chunk encrypted; the home card's
send step had no `flow.css`; the folder viewer's way back to the link page's look turned `flow.css` off; a wait that
left the page within a second kept its clock running; the evidence README used a word check-copy refuses. Its nits
were taken (a done step no longer replays its check, each run tells a screen reader its step, a relay time the
browser can't trust says "soon", a stale selector and an orphaned comment).

## Screenshots

Pruned on 2026-10-20: every wait and result state (uploading, the relay's countdown, the chain's line, the failed step,
delivered, /verify loading and confirmed, Send by Tari) at 1440 and 390 in both themes, and the sending → delivered
moment frame by frame. The UI suite's `flows_ux.py` checks the waits and their results.

## Server signals that do not exist (nothing in `server/` changed)

- **A time for a transaction.** `/api/v1/chain/tx/{id}/view` returns the epoch, not a time, and the mirror keeps no
  timestamp (the fix log's first pass, item 8). /verify/tx therefore explains the epoch in one phrase instead of showing
  a time. A time would need the indexer's epoch-to-time (or the block header's timestamp) in that view.
- **Progress inside one chunk.** Uploads and downloads move in 4 MB chunks over `fetch`, which reports no bytes
  sent, so a phone photo (one chunk) has no percent until it lands. The bar sweeps instead of inventing a number.
  Byte progress would need XHR uploads in `lib/api.js` (inside the widget's A-06 budget), not a server change.
- **The relay's wait.** Already there: `not_before` on `POST /courier` and `GET /jobs/{id}` (used as is).

## Not done, and open

- **The quick share's first moment on a phone.** 2.8 s still remain between the pick and the busy line on the
  throttled phone (the sealing code and the photo's first read); the widget's A-06 budget (43,477 of 43,520 B on the
  computer measure) leaves no room for an earlier placeholder without moving code out of the first load. The same
  2.6 s were there before, hidden behind the 13.8 s.
- **Reduced motion on two surfaces.** The widget's bar and the drive's upload rows have no clock, so with reduced motion
  they stand still until the chunk lands (their words say "Locking it up." / "Uploading").
- **Byte progress** (above): one chunk is one step, so a phone photo has no percent.
- **A time for a transaction** (above).
- **The seller-not-ready wait on production** was met before (a first sale) and not again after: the second drive's
  seller was ready at once. The UI suite does not reach that state either; the code path is `checkReady()` in
  `ui/paypage.js`.
- **Real devices.** Every browser here is headless Chromium on the server (Safari's `:has()`, `backdrop-filter` and its
  reduced-motion handling unseen).
- **Two server tests outside this pass** (no file under `server/` changed): `test_sales_worker`'s
  `test_test_money_pays_marks_the_claim_and_releases_it` fails about one run in three (it reads the last transfer,
  which can be a decoy's), and since 2026-10-19 `test_admin`'s `test_e2e_forged_payment_is_never_credited` fails every
  time, on `main` too (`KeyError: 'status'`: the invoice it reads back now comes without a status; not diagnosed
  here, since the same code passed on 2026-10-18). The UI suite's `drive-delete-account` fails about
  one run in three on `main` as on this branch (three runs each: the click on Delete lands while the Settings dialog
  is still moving).
