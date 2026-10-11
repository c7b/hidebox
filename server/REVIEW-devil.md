<!-- SPDX-License-Identifier: MIT -->
# Devil's-advocate review: server/

Reviewer: devil's advocate for the server component, 2026-10-11. I read every module in `server/mutis/**`,
`bin/*`, the README, ACCEPTANCE and NOTES, and checked them against 12-integration, 10-spec §0, §2–§11 and
§14–§16, and 11-brand §7.4, §8.3 and §16. I did not edit anything except this file.

**Verdict: a solid base with four problems a judge could hit.** The stdlib-only rule, the logging
discipline, the atomic burn, input validation, streaming and contract coverage are all real. I reran the
suite on both machines: workstation (Python 3.14) gave `Ran 141 tests … OK (skipped=4)`, and the server as `build`
(Python 3.13.5, server/ only) gave `Ran 134 tests in 19.6s OK (skipped=6)`; the six skips are the opt-in
suites and the cross-vectors, because I didn't copy `web/` across. The four problems below are not covered
by those tests. Each one breaks the judge path or a privacy promise, and I reproduced each with a short
probe on both machines.

How I reproduced things: probes use `tests/harness.py`. On the server they ran in `/home/build/work/review-server/`
as `build`, and every result below matched on both machines.

---

## High

### H1. A job interrupted mid-send stays in `sending` forever, and its destination address is never scrubbed
- **Where:** `chain_worker.py` `execute()` (lines 251–284) and `jobs.claim()`. Nothing anywhere picks up a
  job in the `sending` state.
- **What happens:** `claim` sets `state='sending'`. The tx id is saved only when `wait_result` times out.
  Three things leave the row stuck in `sending` with its `payload`, which holds the destination address:
  a crash or restart during `submit`/`wait_result`, an exception that isn't `WalletdError` or `SidecarError`
  (a `ValueError` from `parse_testnet` in the decoy path, an `AttributeError` on an odd walletd reply), and
  `deploy.sh` restarting `mutis-chain`. `cleanup` deletes only `done`/`failed` jobs. The submitter's page
  polls `"sending"` forever.
- **Evidence (probe_stuck.py; `wait_result` raises once):**
  ```
  two days later: {'state': 'sending', 'has_payload': 1, 'attempts': 1}
  submitter polls: 200 {'kind': 'courier', 'state': 'sending', ... 'result': None, 'error': None}
  ```
- **Why it matters:** two places promise this can't happen. README: "A destination address lives in the
  database only while its send is pending". `/how`: "kept in the job until sent and then scrubbed".
  Judge step 2 ("Delivered") also never completes.
- **Fix:**
  1. Write `result = {"pending_tx": tx_id}` in its own transaction right after `submit()`, before
     `wait_result`.
  2. When the worker starts, requeue each `sending` job:
     - a job with a `pending_tx` waits on that tx again and is never re-sent;
     - a job without one becomes `failed` with error `interrupted`, `payload = NULL` (the UI already offers
       **Try again**).
  3. Wrap `execute` in a catch-all that calls `jobs.fail(...)`.
  4. In `cleanup`, scrub the payload of any job that has been `sending` for more than 15 minutes.
  5. Add a test that kills the worker between `submit` and `wait_result`.

### H2. The second demo-pay challenge in 10 minutes costs 24 bits
- **Where:** `pow.py` `HOURLY`/`difficulty()`. `issue()` counts challenges *issued*, not challenges solved.
- **What happens:** `demo_pay` is limited to 2 per day, so the per-key baseline is `(2/24)/6 ≈ 0.014` per
  10 minutes. One earlier challenge from the same IP key puts it 72× over, which adds +6 bits. `sponsor`
  behaves the same way. `register` and `drop_create` reach 20 bits on the 4th challenge.
- **Evidence (probe_pow.py; same output on the server):**
  ```
  demo_pay [18, 24, 24, 24, 24, 24]
  register [18, 18, 18, 20, 20, 20]
  drop_create [18, 18, 18, 20, 20, 20]
  ```
- **Why it matters:** in the judge script the phone and the computer usually share one Wi-Fi IPv4, which
  is one `ip64`. The app's `solvePow()` fetches a fresh challenge whenever the prefetched one has aged out.
  Any refusal after verification (`rate_limited`, `lane_full`, a 503) also uses up the solution, so the
  next try needs a new challenge. Step 5 then costs 64× an 18-bit solve: about 2 minutes on the A-13
  reference Android. Judge passes (P-12) skip PoW, but most judges won't have one.
- **Fix:**
  1. Put a floor under the baseline: `average = max(HOURLY[purpose] / 6, 3)`.
  2. Count successful `verify()` calls (solutions used) for escalation, not `issue()` calls.
  3. Add a test: two demo-pay challenges back to back both stay at 18 bits, and a real flood from one key
     still escalates.

### H3. One transient indexer error during the hourly reconcile freezes all credits until a human acts
- **Where:** `payments.committed_on_indexer()` treats any `status != 200` as "not committed".
  `reconcile()` then sets `credit_freeze = 1`, and only `mutis-admin unfreeze-credits` clears it.
  `Indexers._request` returns 4xx/5xx statuses instead of raising, so a Cloudflare 429/502/503 lands in
  this path.
- **Evidence (probe_reconcile.py; one fake 503 from `call_one`):**
  ```
  invoice: credited
  credit_freeze after one transient 503 during the hourly reconcile: 1
  next buyer, 5 minutes later: seen
  ```
- **Why it matters:** about 500 reconciles happen between now and Nov 1, and each one makes one indexer
  call per credited payment. Any CDN hiccup in that time stops judge step 5 at "Seen on chain" until the
  owner notices the red health check.
- **Fix:** give the check three outcomes.

  | Outcome | Condition | Action |
  |---|---|---|
  | `ok` | 200 + `verified:true` + `Utxo` | pass |
  | `mismatch` | 404, `verified:false`, a non-Utxo substate or "… is down", confirmed by **both** indexers | freeze |
  | `unknown` | 5xx, 429, timeout, bucket exhaustion | skip this round; raise an alert after 3 unknown hours |

  Freeze only on `mismatch`, and add a test for each outcome.

### H4. "Keep" (`POST /s/{id}/claim`) cancels the sender's exit rule, and the sender is told the link was revoked
- **Where:** `handlers/shares.py` `claim()` (lines 500–532).
- **What happens:**
  - Whoever holds a **Once** link can claim it *without opening it*: `views_used` stays 0.
  - The link becomes `revoked`, and the item becomes `kept` with `expires_at = NULL`.
  - The sender's manage token is rotated, so the sender can no longer see or delete the file.
  - The file never exits, so no exit receipt is ever written.
  - The intended UX ("Keep" after viewing) can't work on the default link: once the Once link is opened it
    has burned, and the claim answers 410.
  - On a 3-view link shared with three people, one recipient can revoke the link for the other two.
- **Evidence (probe_api.py; same output on the server):**
  ```
  claim once link: 200 {'retention': 'kept', 'lane': 'locker'}
  share row: {'views_used': 0, 'state': 'revoked'}
  item row: {'retention': 'kept', 'expires_at': None, 'state': 'ready'}
  sender manage view after claim: 403 forbidden
  sender deletes the file: 403 forbidden
  ```
- **Why it matters:** "Every secret leaves on cue." Kinkajou will try exactly this. The sender's row
  reads "revoked", which is false, and the burn copy says "We've deleted it from our server", which is
  also false for a claimed file.
- **Fix (the conservative choice):**
  1. Make `claim` an *open*: run it inside the same `BEGIN IMMEDIATE` as `_open_in_tx`, use up one view,
     return the open payload, and allow it only on the link's last view, or when the sender marked the
     link keepable at creation (default off).
  2. End the link with its own state/reason, `kept`, so the sender's tombstone says "Kept by the
     recipient".
  3. The old manage token keeps read access to the state.
  4. Until that ships, ship `features.kept = false` for *received* files. "Only me" kept uploads can stay
     on.

---

## Medium

### M1. SealLog `leaf_index` shows exact live upload volume, contradicting "volume can't be read"
- `/seallog/proof/{item_id}` returns `leaf_index` as soon as an upload completes, even while the proof is
  still `pending`. `/s/{id}/exit` does the same for exits.
- **Evidence (probe_seal.py):** two probe uploads read `leaf_index` 0 and 8, so exactly 7 uploads happened
  in between. Each probe costs one 16-bit PoW.
- This contradicts spec §11.3 and the `/security` sentence "a rough upper bound … in steps of 64".
- **Fix:**
  1. Store new leaves with `idx = NULL`.
  2. At `make_checkpoint`, give the batch of real leaves plus pad leaves indices in a random permutation.
  3. Return `leaf_index` only together with a committed proof.

### M2. The recipient can't verify an exit receipt, and receipts say "pending" even when SealLog is off
- **No `item_id`:** `/s/{id}/exit` returns `leaf_hash` without `item_id`. App-core's
  `seallog.exitLeaf(itemId16, unixSeconds)` needs the item id, and the viewer never receives it (`peek`
  and `open` omit it). The browser can only check that *some* leaf is in the tree, which says nothing about
  this file. Fix: return `item_id` in `/s/{id}/exit` (it grants nothing on its own) and have `/verify`
  recompute the leaf.
- **SealLog off:** with `features.seallog = false` or an empty `seallog_component` (the deploy default),
  `next_checkpoint_eta = max(now, 0 + 21600)` evaluates to *now*. Every receipt then says "pending,
  next checkpoint now", forever. Fix: while SealLog is off, answer 503 `feature_disabled` (or
  `{"seal_log":"off"}`) so the UI hides C7.

### M3. Lockers older than a day can drain the reserved slice that judge passes and the canary depend on
- `slice_for()` sends three kinds of work to `reserved`: lockers created before today, evidence jobs and
  judge passes.
- 25 lockers registered yesterday (18-bit PoW each) × 20 relay sends drain `courier:reserved` (500).
  After that, judge passes and the hourly canary get `budget_exhausted`.
- **Fix:** add a third slice, `evidence`, for canary, evidence payments and judge passes that lockers can
  never reach. Or cap each locker's draw from the reserved slice.

### M4. A failed relay send still counts against the destination's 20-a-day limit
- In `handlers/courier.py` `send()`, `cour_dest` is charged before `_count_send` and `budget_check`, and
  `_per_drop_today` is charged before `budget_check`. Neither is refunded when a later check refuses.
- **Evidence (probe_api.py):** a probation locker with no sends left makes 25 attempts. A graduated, honest
  sender to the same address then gets `429 rate_limited, retry_after 4320`. The attacker keeps the limit
  saturated with one request every 72 minutes.
- A drop's address is public through `GET /drops/{id}`, so any drop owner can be targeted.
- **Fix:** run the per-locker and budget checks first, charge the destination counter last, and refund it
  on any later refusal. `uploads.create` already uses this pattern.

### M5. The worker's heartbeat stops during long sends, so the API reports the chain as down
- The heartbeat is written only at the top of `tick()`. `run_jobs` blocks on `wait_result` (up to 120 s
  per job, 5 jobs per tick), and each indexer call can take 10 s plus a fallback.
- A tick longer than 60 s makes the API answer `503 chain_unavailable` for courier and invoices, and sets
  `/stats.chain_ok = false`, even though walletd is fine.
- The queue is plain FIFO by `not_before`, so a burst of public-slice drop couriers delays judge and
  reserved jobs.
- **Fix:**
  1. Write the heartbeat from its own thread.
  2. Don't block on sends: submit, store `pending_tx`, and poll results in later ticks.
  3. Claim in order `ORDER BY (slice = 'reserved') DESC, not_before`.

### M6. `/stats` publishes exact free disk bytes every 60 s
- `disk_free_bytes` and `disk_total_bytes` are exact. Uploads are preallocated with `posix_fallocate`, so
  each upload's `size_stored` shows up as a visible step within a minute.
- That gives anyone upload timing and padded sizes, which undoes the reason for SealLog padding.
- **Fix:** round both values to 0.1 GiB. The copy shows GB anyway.

### M7. "What the chain sees" claims amounts are hidden without checking
- `/chain/tx/{id}/view` (public, any tx id) hard-codes `"amount": "hidden"` and
  `"owner": "one-time key"` for every UTXO it lists.
- **Fix:** read the output first. Say "hidden" only when `minimum_value_promise == 0` and
  `viewable_balance` is null; otherwise show the revealed value or lower bound.

### M8. A compromised API can spend more than the daily budgets
- `seal` jobs aren't in `budgets.KINDS`, so `jobs.claim` runs them with no budget check. Each one can spend
  up to 1 tTARI of the operator's funds and publish *any* root. Anything that can write the database, such
  as the API user, can queue them.
- `demo_pay` validation doesn't check that the address is our receiver. The worker could compare it with
  its own in-memory receiver address, not with `meta`, which the API can also write.
- The D4 promise "A compromised API can at most spend the daily budget slices" is therefore false for
  `seal`.
- **Fix:** the worker submits checkpoints directly from `seal_checkpoint()` and never takes `seal` work
  from the queue. Pin demo-pay's destination to the receiver address.

---

## Low

| # | Where | Issue | Fix |
|---|---|---|---|
| L1 | `handlers/blobs.py` `_ticket` | A non-canonical 43-character ticket returns **500 internal** and logs an error (probe: `GET /blobs/AAA…AB` → 500). S-10 says a malformed id gets 400. | Catch `ValueError` and answer 404; add the case to `test_input_safety`. |
| L2 | `uploads.put_chunk` | On `hash_mismatch` the bad bytes are already written while the old chunk row stays. `complete` then succeeds with a `ct_hash` (and a SealLog stored receipt) that doesn't match the disk. | On mismatch, `DELETE FROM chunks WHERE item_id=? AND idx=?`. |
| L3 | `handlers/stats.py` wall | The docstring says "can never describe one person's file". Eight cheap uploads plus strict newest-first order (`rowid DESC`) defeat k ≥ 8. `opened` reveals when a recipient opened a link (5-minute resolution). | Shuffle the entries, leave out items < 1 h old, delay or drop `opened`, and fix the docstring. |
| L4 | `payments.credit` / `api_status` | Invoice status `proven` is never set (`seen → credited`), so the `exists` branch is dead. | Set `proven` before `credited`, or delete the branch and document that the stepper reads `payments[].checks`. |
| L5 | `auth.use_judge_pass(spend=False)` | A pass skips PoW without limit as long as it never spends a use. A leaked pass bypasses PoW for uploads, registrations and drops. | Add an expiry and a separate cap on PoW skips. |
| L6 | `quota.measure` N | Fake lockers graduate with one request on day 2 (2,000 a day globally), pushing Q down 10 % a day to the floor. | Count lockers that *stored* something on two or more days. |
| L7 | `db.connect` | Scrubbing `wrapped_key` relies on the distro default `secure_delete=1`. It is on in Debian (verified on the server: SQLite 3.46.1 → `(1,)`), but self-hosters may not have it. Separately, the 7 daily DB backups keep wrapped keys of links that were active at backup time. | Add `PRAGMA secure_delete=ON` explicitly with a test. State the backup window in `/privacy` (deploy). |
| L8 | README "privacy promises" table | "Ciphertext is unlinked within a minute of its exit" is false while a download ticket is live (≤ 30 min) and for canaries (48 h). "Ended links lose their wrapped key at once" is false for expiry, which is scrubbed at the next cleanup (≤ 60 s). | Reword to what the code does. |
| L9 | `payments.py` docstring, §1.3 copy | "Independent indexer": with the default order, the mirror *and* the confirmation both come from indexer-b. | Mirror from indexer-a, or drop the word. Note that "two independent indexers" is a banned phrase. |
| L10 | schema | `first_opened_min` (minute) and `items.exit_hour` are stored, but §1.4's "Sees and stores" lists hour/day granularity. | Integrator: update `/how`, `/privacy` and the glass box. |
| L11 | `me.list_items` | The `next` cursor is a global `rowid`, a small volume side channel. | Use an opaque cursor such as `(created_hour, item_id)`. |
| L12 | `seallog.inclusion_proof` | Each proof request recomputes subtree roots (O(n) SHA-256 under the GIL). | Cache the interior nodes of each committed checkpoint. |
| L13 | `jobs.fail` codes | `walletd_unreachable`, `walletd_error`, `timeout`, `rejected`, `invalid_payload`, `budget_exhausted` and `sidecar_error` reach `GET /jobs/{id}` but are not in §6.4. | Document them in `docs/api.md` for the app-ui copy map. |
| L14 | `admin.cmd_e2e_forge_payment` | "Staging only" is enforced only by the help text. | Refuse unless the config marks a staging host. |
| L15 | `Indexers.call` in the mirror | Falling back from b to a reuses b's per-shard cursors. If state versions are per indexer, UTXOs can be skipped. | Record which indexer the cursors came from and reset them on a switch. |
| L16 | `App.memory` | One untyped dict with three key shapes (`pw`, `small48`, `courier_drop`) and no size cap; it grows all day under IPv6 rotation. | Use small named classes with an LRU cap. |
| L17 | `chain_worker.random_memo` | Nit: the last character is uniform over 64 values, while real 125-byte b64u memos end in one of 16. This is harmless today because memos are encrypted to a discarded key. | `origin + "/t#3" + b64u(secrets.token_bytes(125))` makes "same format" literally true. |

---

## Contract notes (no action from the server unless the integrator decides otherwise)

- **Config keys:** the server uses `memo_origins` (spec §15.3); 12-integration §1 says `allowed_memo_origins`.
  `deploy/config/mutis.toml.example` already uses `memo_origins`, and an unknown key stops the service.
  The integrator should correct the 12-integration text.
- **`/config` names:** the class block is `limits.locker` (spec); 11-brand §8.3 says `limits.free`.
  `web/site/js/stats.js` already reads `limits.locker`, and app-ui must too. `amount_proof` is a string
  (12-integration §3), not the spec's boolean, so `docs/api.md` must say so.
- **`features.kept` defaults to `true`** (spec: false). With H4 open, ship `false` for received files.
- **Proxy allowlist:** `epoch-manager/stats` was added by the builder (spec: the integrator adds G1 paths).
  It is not a wildcard, so it is fine, but the integrator should record it.
- **`{checkpoint_min}` is 360:** copy that says "within {checkpoint_min} minutes" should be formatted as
  "6 hours".

## What I did not check

- The `@chain` suite (walletd, real sends): it needs the deployed config and the `drive` user.
- The real-sidecar suite and the 2 GiB S-09 run. I took the builder's evidence for both.
- Behaviour behind the real Caddy 2.6.2: `X-Real-IP`, the body limit, and `Content-Length: 0` on 204s.
- Whether indexer state versions are global or per indexer (L15).
- Worker throughput against real walletd finalization under a burst (M5).
- App-ui use of the API, which isn't built yet.

---

## Builder response (server builder, 2026-10-11)

All four highs and all eight mediums are fixed. Sixteen of the seventeen lows are fixed or handed to
their owner; L14 is rejected below. The storage changes are schema 2 (`mutis/migrations/002_review_fixes.sql`).
`test_schema.py` migrates a copy of the deployed schema 1 and requires the same schema a fresh install
gets. Suite: `Ran 178 tests … OK` on the server (Python 3.13.5, real sidecar) and on the workstation. Each fix and
its test is listed in `NOTES-for-integrator.md` §5.

| # | Resolution |
|---|---|
| H1 | **Fixed.** The worker writes `{"pending_tx"}` in its own transaction right after `submit`, then waits 5 s. Slower transactions are polled on later ticks and never re-sent; after 15 minutes the job fails `timeout`. At start, `recover()` fails any job claimed but never recorded as `interrupted`, with `payload = NULL`, and keeps waiting on recorded ones. Any other exception from `submit` fails the job `internal`. Cleanup ends any send still open after 30 minutes, for a worker that is down. Also new: a walletd call that times out after sending (`walletd_timeout`) is never retried. Tests kill the worker (`SystemExit`) between submit and `wait_result`, and before the record. |
| H2 | **Fixed as proposed.** Escalation counts solutions spent in `verify()`, not challenges issued, and the baseline has a floor of 3 per 10 minutes. Asking for a challenge also no longer creates a per-key entry. Four back-to-back challenges for demo_pay, register, drop_create and sponsor from one key all stay at base. 5,000 challenge requests stay at 16 bits. A real flood still escalates: 9 solutions give 20 bits, 27 give 22. |
| H3 | **Fixed as proposed.** Each indexer check now has three outcomes: `ok`, `missing` (404 "not found" or "is down", both probed live, or an unverified/non-Utxo 200) and `unknown` (5xx, 429, other statuses, non-JSON, unreachable). Credits still need `ok`. The reconcile freezes only when every indexer says a credited output is gone, or when the sidecar no longer proves its value. `unknown` skips the round and counts `meta.reconcile_unknown`, which is shown in `chain_status`; the log line turns critical after 3 unknown hours. |
| H4 | **Fixed by removing the endpoint.** `POST /s/{id}/claim` is gone, and `/items/{id}/claim` was never served; both answer 404. A recipient keeps a file by opening the link normally and sealing the plaintext again as their own kept file, with the app's existing `sealItem(…, {keepFor})`. The sender's rule, exit, exit receipt and manage token are untouched, and "revoked" is shown only for real revocations. This is simpler than a keepable flag and a `kept` state, and every exit sentence stays literally true. `features.kept` stays on for "Only me" files. App-core's `claimItem`/`keepWrap` are now unused (NOTES, App builders 2). |
| M1 | **Fixed as proposed.** A new leaf has `idx` NULL. `make_checkpoint` adds the pad leaves, shuffles the whole batch with `SystemRandom`, and places it after the leaves already placed. `leaf_index` is returned only with a proof against a committed checkpoint. |
| M2 | **Fixed as proposed.** `/s/{id}/exit` returns `item_id`; the test recomputes the exit leaf from it and checks the proof. While `features.seallog` is off or no component is set, `/s/{id}/exit`, `/seallog/proof` and `/seallog/checkpoints` answer `503 feature_disabled` with `details.feature = "seallog"`. |
| M3 | **Fixed with a third slice.** New `budgets.evidence` (courier 150, demo-pay 10 tTARI, sponsor 10 tTARI a day) is used by the canary, the daily evidence payment and judge passes. Lockers can't reach it. Claims run evidence first, then reserved, then public. |
| M4 | **Fixed as proposed.** All per-locker and budget checks run first. The per-destination and per-drop counters, both now limiter rules, are charged last and refunded if queuing still fails. The judge-pass use is spent in the queuing transaction. Demo-pay, sponsor and upload rate limits are refunded on a later refusal too (`Ctx.charged`). The review's probe now ends with the honest sender's `202`. |
| M5 | **Fixed as proposed.** The heartbeat comes from its own thread every 10 s, for as long as the loop has moved in the last 5 minutes, so a stuck loop still shows as down. Sends no longer block for 120 s (see H1). Claims are ordered by slice. |
| M6 | **Fixed as proposed.** Both disk values are rounded down to 0.1 GiB. |
| M7 | **Fixed.** The mirror now records what each output reveals: `promise` (minimum_value_promise), `viewable` and `auth`. The view uses the mirror, then the indexer, and otherwise says `unknown`. `amount` ∈ `hidden | lower_bound | viewable | unknown`, plus `min_value_ut`; `owner` ∈ `one-time key | spend rule | unknown`. This was a real gap: 2 of 506 live TARI UTXOs publish a lower bound, one of them 1,000 tTARI (in the recorded fixture). |
| M8 | **Fixed as proposed, and one step further.** The worker makes and submits checkpoints itself, so there is no `seal` job kind and the schema refuses one. `seal-now` can't run more often than every 10 minutes, and a failed submission retries after 10 minutes. A demo payment goes only to the receiver address the worker learned from its own key file or walletd. Also, budget overrides in `meta` can now only lower a limit: the API can write `meta`, so an override that raised a limit was the same hole. |
| L1 | **Fixed.** A non-canonical ticket gets `404 not_found`, with no error log. |
| L2 | **Fixed.** On a hash mismatch the chunk row is deleted, so `complete` reports it missing. |
| L3 | **Fixed in part.** The wall is shuffled, holds items back until they are at least an hour old, and the docstring now says what can still be recognised. `opened` is kept: spec §6.3 defines it, and the site draws open doors from it. The remaining leak (someone who knows a file's classes can see it was opened, with up to 5 minutes' delay from the cache) is in NOTES for `/privacy`. |
| L4 | **Fixed by removing the dead branch.** `api_status` is gone. The payments docstring and NOTES say the stepper reads `payments[].checks`; invoices go pending → seen → credited. |
| L5 | **Fixed.** Passes last 30 days and carry `pow_skips_left` (`judge-pass new --pow-skips`, default 100). |
| L6 | **Fixed with a variant.** N counts lockers active on two or more days that hold bytes (`used_bytes > 0`), instead of "stored on two distinct days". This needs no new per-locker column (another stored fact to disclose) and costs a fake locker about the same. |
| L7 | **Fixed.** `PRAGMA secure_delete=ON` is set on every connection, with a test. The README states the remaining exposure: an older page can stay in the WAL until it is reused, and in the 7-day backups. The `/privacy` sentence goes to the integrator (NOTES, Integrator 7). |
| L8 | **Fixed.** README and `cleanup.py` now describe what the code does: the ticket wait (up to 30 minutes), canaries kept 48 h, and expiry scrubbed within a minute. |
| L9 | **Fixed by rewording.** "Independent" became "a Tari indexer (not walletd)". The mirror still prefers indexer-b, so nothing claims two independent indexers. |
| L10 | **Handed to the integrator** (NOTES, Integrator 7). |
| L11 | **Fixed.** The cursor is `"<created_hour>.<item_id>"` of the locker's own last row. |
| L12 | **Fixed.** Proofs come from the cached levels of each committed tree, O(log n) per request. A test checks them against the RFC's recursive PATH and the browser vectors. |
| L13 | **Handed to the integrator** with the full list, including the new `interrupted`, `timeout`, `walletd_timeout` and `internal` (NOTES, Integrator 6). |
| L14 | **Rejected.** There is no separate staging host: the deploy builder's E-14 (`tests/e2e/scenarios_chain.py`) runs this command against the one deployment. A "staging" flag would either break that test or be set on production, which protects nothing. The command needs DB write access as `mutis`, which already allows any write. The row it inserts can never be credited; that is what E-14 checks, and `payments_unconfirmed` shows it after 10 minutes. The help text says what it is for. |
| L15 | **Fixed.** The mirror stores which indexer served its cursors and restarts from zero on a switch (rows are idempotent). |
| L16 | **Fixed.** The password-try and SMALL-lane tables are bounded `Recent` maps (200,000 entries each). The per-drop and per-destination counters moved into the limiter, which already has its own bound. |
| L17 | **Fixed as proposed.** A decoy memo is now `origin + "/t#3" + b64u(token_bytes(125))`. |

Contract notes: `features.kept = true` is right now that no endpoint lets a recipient keep a sender's
file. The other notes (config key names, `limits.locker`, the proxy allowlist, `{checkpoint_min}`) are
already in NOTES for the integrator.
