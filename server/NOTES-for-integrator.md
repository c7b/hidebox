<!-- SPDX-License-Identifier: MIT -->
# NOTES for the integrator (server builder)

Everything below was run on 2026-10-11, on the workstation (Python 3.14) and on the server as `build`
(Python 3.13.5, Node 20.19.2) in `/home/build/work/server`. Nothing ran as `drive`; walletd was read
once, read-only, as `operator` (§1.3). §5 lists what the devil's-advocate fix pass changed (schema 2); §6 and §7
are the integration pass (schema 3), which also updated the rows of §2 and §3 it touched.

## 1. Gate G3: indexer UTXO framing — PASS (mirror via the stream with per-shard cursors)

### 1.1 What the indexers do (tari_indexer 0.45.0, both `ootle-indexer-a` and `-b`)

- `POST /utxos/stream` body `GetUtxoUpdatesRequest {resource_address, shard_state_versions: [[shard,
  version], …], per_shard_limit, from_epoch?, unspent_only?}`. Shards are **1..256**; shard 0 ("global")
  is refused with `400 … Cannot query UTXOs in global shard`. Shards with no TARI UTXOs are simply absent
  from the answer (246 of 256 have some today).
- Framing depends on `Accept`: `application/x-protobuf` by default, **NDJSON** with
  `Accept: application/json`. One line per update:
  `{"sos": {"shard", "max_state_version", "num_updates", "has_more"} | null, "update": {"Unspent": {"tag":
  u32, "public_nonce": [32 numbers]}} | {"Spent": {"id": [32 numbers], "version"}}, "eos":
  {"max_state_version"} | null}`. `sos` opens a shard's section; `max_state_version` is that section's
  cursor (ask again from it; `has_more` says whether to).
- **An `Unspent` update carries no commitment and no encrypted data.** Full outputs come from
  `POST /utxos/fetch {resource_address, tag_and_nonce_pairs: [[tag, nonce_hex], …]}` →
  `{"utxos": [[commitment_hex, {"output": {"output": {"public_nonce", "encrypted_data",
  "minimum_value_promise", "viewable_balance"}, "auth": {"Key"}, "tag"}, "is_frozen"}], …]}` (500 pairs in
  one request worked; we send 100). A pair that was spent meanwhile is just missing from the answer.
- `GET /utxos` needs `?resource_address=…&limit=…` and returns the same `[commitment, output]` pairs with
  no cursor, so the stream is the only incremental source. The SSE fallback was not needed.
- **Not every output hides its amount.** `minimum_value_promise` is a public lower bound. In a live sync
  of 506 TARI UTXOs (the server, 2026-10-11), 2 had `minimum_value_promise > 0`; one recorded in
  `tests/fixtures/indexer-fetch.json` publishes 1,000 tTARI. The mirror now stores `promise`, `viewable`
  and `auth` for each output, and "What the chain sees" says "hidden" only for outputs it read.
- Both a spent UTXO (`{"error": "Input substate … (v0) is down"}`) and an unknown id (`{"error":
  "Substate … not found"}`) answer **HTTP 404** on both indexers (probed 2026-10-11); payments treat
  404 as `missing` and 5xx, 429, other statuses and timeouts as `unknown`.
- UTXO substate id = `utxo_<32×01>_<commitment_hex>`; `GET /substates/{id}?include_proof=true` → `200`,
  `verified: true`, `proof.anchor {epoch, shard_group, height, block_id, state_merkle_root}`.
- `GET /transactions/{id}/result` forgets old transactions (`transaction_retention_epochs: 50`), but
  `GET /transaction-receipts/{tx_id}` keeps every committed receipt (`receipt_retention: null`) with
  `outcome`, `diff_summary.upped/downed`, `fee_receipt.total_fees_paid`, `epoch`: the "What the chain
  sees" view uses it.
- Python's default `User-Agent` is refused by the indexers' CDN (the app builder saw HTTP 403 / 1010);
  every request we make sends `User-Agent: mutis`.

### 1.2 Commands and outputs (trimmed)

```
$ curl -s -X POST https://ootle-indexer-b.tari.com/utxos/stream -H 'Content-Type: application/json' \
    -H 'Accept: application/json' --data '{"resource_address":"resource_0101…01","shard_state_versions":[[1,0],[2,0]],"per_shard_limit":2}'
{"sos":{"shard":1,"max_state_version":229,"num_updates":2,"has_more":true},"update":{"Unspent":{"tag":2503219696,"public_nonce":[204,3,59,…]}},"eos":null}
{"sos":null,"update":{"Unspent":{"tag":2178487565,"public_nonce":[248,61,67,…]}},"eos":{"max_state_version":229}}
{"sos":{"shard":2,"max_state_version":107,"num_updates":2,"has_more":true},"update":{"Spent":{"id":[138,19,…],"version":0}},"eos":null}
…
# all 256 shards from 0, per_shard_limit 1000: 838 lines (490 Unspent, 348 Spent), 246 shards, 178 KB, 0.7 s
$ curl -s -X POST https://ootle-indexer-b.tari.com/utxos/fetch --data '{"resource_address":…,"tag_and_nonce_pairs":[[529182138,"70b626c5…3526"],…]}'
{"utxos":[["72795736dcd171d07fb9c5b1b90ea0461198581893a44b07ad0170aff1621d45",{"output":{"output":{"public_nonce":"70b626c5…","encrypted_data":"92bddd7b…","minimum_value_promise":0,"viewable_balance":null},"auth":{"Key":"ac2d58c6…"},"tag":529182138},"is_frozen":false}],…]}

# the worker's mirror against the live indexers, as build on the server (throwaway database; the same steps
# are the @chain test tests/chain/test_live_chain.py::test_full_mirror_sync)
$ python3.13 -I g3_live_mirror.py
{"rows": 496, "polls": 2, "seconds": 2.8}
(1, 'utxo_010101010101010…', 32, 80, '953419F0', 12132)
(2, 'utxo_010101010101010…', 32, 80, '81D9150D', 12132)
shards with cursors: 246
next poll, new rows: 0
```

Recorded responses (public chain data) are in `tests/fixtures/indexer-stream.ndjson` and
`indexer-fetch.json`; `test_mirror.py` parses them, and checks paging, idempotence and a pair spent
between stream and fetch against the fake indexer.

### 1.3 walletd shapes for the G4 fallback (read-only, as `operator`)

`stealth_utxos.list` items look like `{"address": {"id": "<commitment hex>", "resource_address":
"resource_01…"}, "value": "1500000", "status": "Unspent", "memo": {"PayRefAndBytes": "0a696e76…"},
"is_on_chain": true, "is_burnt": false, "is_frozen": false, "sender_address": null, "auth": …}`;
`accounts.get_balances` → `balances[].confidential_balance` for tTARI. `amount_proof = "wallet"` uses
exactly these (`payments.py`, `chain_worker.verify_payments`), credits only after the indexer check,
and reports `checks.amount_proven: false`. An invoice goes `pending → seen → credited` (the spec's
`proven` step happens inside the crediting transaction), so the UI stepper reads `payments[].checks`.

## 2. Decisions this build made (conservative choices, with the reason)

| Topic | Decision | Why |
|---|---|---|
| Mirror `tag` | stored as 4 bytes big-endian; `GET /chain/utxos` returns 8 hex chars (`"953419f0"`) | the indexer's tag is a u32, the spec's column is a BLOB |
| Mirror `epoch` | the indexer's current epoch when our mirror first saw the output | the stream carries no epoch; good enough for `GET /chain/seq` |
| `GET /chain/seq?epoch=n` | returns the largest seq whose epoch is below `n` (0 if none): pass it as `after` | "where to start scanning from epoch n" |
| Worker status for the healthcheck | in the database, not a file: `meta.chain_heartbeat` (unix s; written every 10 s by its own thread while the loop has moved in the last 5 minutes), `meta.chain_status` (JSON: `walletd_ok`, `sponsor_balance_ut`, `mirror_ok_at`, `mirror_head`, `sidecar_ok`, `sidecar`, `canary {n, sealed_at, delivered, in_mirror, opened}`, `receiver_ready`, `credit_freeze`, `reconcile_unknown` (hourly reconciles in a row with no verdict; alert at 3), `payments_unconfirmed`, `amount_proof`, `updated_at`), `meta.alerts` (`{"budgets": {"courier:public": 50|90, …}}`), `meta.credit_freeze`, `meta.canary_log` | the API, cleanup and health all run as `mutis`, which can read the DB; `mutis-chain` may write only `data/db` and `status/` |
| Canary items | not doomed when their link ends; they live their full 48 h | "Try to read it" needs the hourly blob, and the P1 reveal needs it 24 h later |
| Never-shared items | doomed only after the 2-hour upload window (they never had a link) | a slow phone must not lose its upload between `complete` and creating its link |
| Unread request bodies | drained (≤ 8 MiB) before answering an early error; larger ones close the connection | a browser gets the JSON error instead of a reset |
| Listen backlog | 128 (the `http.server` default of 5 dropped bursts: 50 concurrent opens took 7.6 s, now 0.1 s) | judge-path bursts behind Caddy |
| Judge passes (P-12) | header `X-Mutis-Judge: judge-<24 Crockford chars>` (case-insensitive), valid 30 days from `judge-pass new`; each PoW it stands in for uses one of its `--pow-skips` (default 100); budgeted sends (courier, demo-pay, sponsor) spend one of its `--uses` (default 5) inside the transaction that queues the job (a refused send keeps its use) and draw from the **evidence** slice; a valid pass lifts the per-/64 and per-/48 limits of `POST /sponsor` and demo-pay (the per-locker limits stay); unknown, expired or used up → `403 forbidden` `details.judge = "invalid"` | 5 uses would otherwise run out midway through the judge script; a leaked pass can't skip PoW without limit; two judges on one network both get a grant (app-core review M1) |
| Drop and canary links | the server fixes their rule (3 opens until the drop item's 7-day expiry; 3 opens within 24 h for the canary) and answers the effective values; a client value is not an error | fewer ways for the judge path to fail |
| `first_opened_min` (P-25) | unix **seconds** floored to the minute (like `*_hour`); only in `GET /s/{id}/manage` | the API's time convention |
| SealLog tables | in schema v1 directly (`seal_leaves` with `kind ∈ stored|exit|pad`, `seal_checkpoints`), plus `items.exit_hour` | nothing is deployed yet; pad leaves must live in the tree; the exit leaf is recomputed from the item id and hour, so no table maps leaves to items |
| Checkpoint cadence | config `seal_log.checkpoint_interval_s`, default **900** (15 minutes), refused below 600; `/config.seal_log.checkpoint_interval_s` reports it | ratified by the integrator (12-integration §7.2, the template builder's recommendation); C7 copy reads the variable |
| Password-only PoW | `peek`/`open` accept an optional JSON body `{"pow": {challenge, nonce}}`; `POST /pow` accepts `min_difficulty` (for the 20-bit busy-day rule); waiting shows as `428 pow_required` with `retry_after` | the spec gives the rule but no wire format |
| Unlock | `PATCH /s/{id}` accepts `{"unlock": true}` from the owner | "locks until its owner unlocks or revokes it" |
| "Keep" for a received file (P1) | **no server endpoint.** The recipient opens the link normally (the view is used, the sender's file leaves on its rule and gets its exit receipt), then the browser seals the plaintext again as the recipient's own kept file (`POST /uploads` with `retention: "kept"`). `POST /s/{id}/claim` and `POST /items/{id}/claim` answer 404 | a server-side claim let a recipient cancel a Once link's exit without opening it and showed the sender a false "revoked" (review H4); re-sealing keeps every exit promise literally true and uses only existing endpoints |
| Stored bytes (P1) | `GET /s/{share_id}/stored` with the same headers as `peek`: the ciphertext as stored, `Range` supported, no view used | safe even for the link holder: the wrapped key is released only by `/open` |
| Abuse reports with the key | the fragment is appended to `details` as `[Reporter included the link key: #…]`, `included_key = 1` | the schema has no column for it; the reporter chose to include it |
| E-14 | `mutis-admin e2e-forge-payment <invoice>` inserts a proven-looking `pending_check` row for a UTXO that doesn't exist; it is never credited and `chain_status.payments_unconfirmed` counts it after 10 minutes | the spec asks for a test-only admin command |
| Retention of finished jobs | user jobs (with their tx ids) deleted 1 day after they end; evidence jobs after 30 days | nothing needs a user's tx id after the submitter's page has polled it |
| Sends | claim → `submit` → `result = {"pending_tx"}` written → `wait_result` for 5 s; slower transactions are polled each tick (1 s); after 15 minutes the job fails `timeout`. At start the worker fails jobs claimed but never recorded as submitted (`interrupted`) and keeps waiting on recorded ones; cleanup fails any send open 30 minutes (`interrupted`, for a worker that is down). A rejected transaction may be retried (nothing moved); a walletd call that timed out after sending is not (`walletd_timeout`) | a crash or restart must never leave an address in the database or pay twice (review H1); ticks stay short (review M5) |
| Claim order | evidence slice, then reserved, then public; `not_before` within each | judge and canary sends don't wait behind a burst of public drop deliveries |
| Budget slices | `public`, `reserved` (lockers older than today, decoys) and a new `evidence` slice (canary, daily evidence payment, judge passes): courier 150, demo-pay 10 tTARI, sponsor 10 tTARI a day | lockers can't drain what the canary and judges need (review M3); worst case adds ≈ 25 tTARI/day to §9.5's ≈ 230 |
| Budget overrides | `mutis-admin budget set` can only **lower** a slice for the day; raising one means editing the TOML and restarting | the API user can write the database; a bug there must not raise what the worker spends (spec D4, review M8) |
| SealLog checkpoints | submitted by the worker itself every `checkpoint_interval_s` (`seal-now` at most every 10 minutes; a failed submission, including one the component refuses, retries after 10 minutes and the next checkpoint covers its leaves); every checkpoint adds at least one pad leaf, up to the next multiple of 64; there is no `seal` job kind any more | nothing in the database can make the worker publish a root or spend the operator's funds (review M8); template 2.0.0 refuses a size that doesn't grow, and idle windows must not show |
| SealLog leaf indices | a leaf has no index until the checkpoint that commits it, which places the batch (with its pad leaves) in a random order; proofs return `leaf_index` only with a committed checkpoint | an index must not count uploads (spec §11.3, review M1) |
| SealLog off | `/seallog/proof`, `/seallog/checkpoints` and `/s/{id}/exit` answer `503 feature_disabled` (`details.feature = "seallog"`) unless `features.seallog` is on **and** `ootle.seallog_component` is set | no page may promise a checkpoint that never comes (review M2) |
| Demo payments | the worker sends a `demo_pay` only to the receiver address it learned itself (key file or walletd), never one read from the database | a rewritten `meta.receiver_address` can't redirect the sponsor's funds (review M8) |
| Indexer checks | `ok` / `missing` / `unknown`; credits need `ok`; the hourly reconcile freezes credits only when every indexer says a credited output is gone (or the sidecar no longer proves its value), and skips the round on `unknown` | one CDN 503 must not stop every pack until a human acts (review H3) |
| Mirror cursors | stored with the indexer that served them (`meta.mirror_source`); an answer from the other indexer restarts the cursors from zero | shard versions may be per indexer (review L15). After the schema-2 upgrade the mirror re-syncs once (no source recorded yet), which also fills `promise`/`viewable`/`auth` for live outputs |
| `/stats` disk sizes | rounded down to 0.1 GiB | uploads reserve their full padded size at once, so exact bytes every minute showed each upload's padded size (review M6). `last_sealed_min` (spec §6.3) still tells, to the minute, when the latest upload finished; `/privacy` should say so |
| `/stats/wall` | `{size, exit}` per item only (no `state`, no `ttl`); random order; items appear 1–2 hours after upload (never under an hour); taken-down items are left out | a fresh upload can't be picked out by position (review L3); the wall must not say when a link was opened (site review M15); an E2E run that takes its items down leaves no trace there (12-integration §7.7); whoever knows a file's size class and rule may still recognise it, which `/privacy` should say |
| `/me/items` cursor | `"<created_hour>.<item_id>"` of the last row, newest hour first | the old global `rowid` leaked total volume (review L11) |
| Active lockers N (§9.2) | lockers active on ≥ 2 days **that store something** | lockers made only to be counted don't push the free quota down (review L6); no new column |
| Database | `PRAGMA secure_delete=ON` on every connection | scrubbing a wrapped key must not depend on the distro's build flags (review L7) |
| Address normalisation | addresses we store or send to are canonical lowercase without a pay-ref (`ootle_addr.base_address`) | walletd would otherwise copy an embedded pay-ref into the memo |
| `limits.anon.courier_per_day` (P-3) | = the probation locker's 3 sends a day | every send leaves from a (silently created) locker; anonymous sessions can't relay-send at all |
| `limits.anon.uploads_per_hour` | 30 (small files); `large_uploads_per_hour` = 10 (5–25 MiB) | both limits exist (spec §6.2) |
| SealLog checkpoint numbers | `seal_checkpoints.component` and `chain_index` (schema 3): the component appended to and the `index` of its `SealLog.root` event, read from walletd's `transactions.wait_result` `result.events` (shape checked live on the notarize transaction `c9026517…4329`); the committed epoch also comes from that event. API checkpoint objects: `index` = that chain index (null if the event couldn't be read), plus `component`; `/seallog/checkpoints` `next` is an opaque cursor | the server's own row id also counts failed checkpoints, so "SealLog checkpoint #n" must be the number a reader finds on chain (template NOTES §2) |
| Missed canary reveals | when the sidecar answers `reveal` with `not_found` (it restarted and forgot the key), the hour is marked missed and `GET /canary` lists it in `revealed[]` as `{"n", "sealed_at", "missed": true}` (no `fk`) while its ciphertext is still held; other sidecar errors retry the next hour | never skip an hour (app-core review L8) |
| E2E expiry preset | config `e2e_expiry_s` (default 0 = off); when set, `/config` carries `"e2e_expiry_s": <value>` | spec §17.1's 60 s option, absent in production (app-ui review M8) |
| Requests in flight | at most 32 per /64 (IPv4: per address) and 128 per /48 (IPv4: per /24); over that `429 rate_limited`, `retry_after: 1` | slow downloads from one network can't hold every API thread (deploy review M6); a browser uses about 6 at once |
| `operator_account` | default `"service"` | G5 failed: walletd 0.45 signs SealLog calls with the default key (12-integration §7.3) |
| Process umask | every `bin/*` sets 007; `migrate` copies the database (0600) only when a migration is pending | the database and its `-wal`/`-shm` must stay group-`mutis` only, whoever runs the command |

## 3. Requests

### Integrator (`docs/api.md`, spec patches)

1. Additions to spec §6.3 that this server implements: `GET /s/{id}/stored`, `GET /s/{id}/exit` (P-8:
   `{reason, item_id, exit_hour, leaf_hash, leaf_index, proof | {pending, next_checkpoint_eta}, checkpoint}`,
   `leaf_index` null until committed, `503 feature_disabled` while SealLog is off), `X-Mutis-Judge`,
   `{"unlock": true}` on `PATCH /s/{id}`,
   `min_difficulty` on `POST /pow`, `{"pow"}` bodies on `peek`/`open`, `/config` fields (`send_mode`,
   `amount_proof` as a string, `repo_url`, `security_drop` (null until set), `seal_log`, `retention`, `quota`,
   `password`, `invoices`, `hosting`, `onion`, `limits.demo_pay_per_day`, `limits.anon.{courier_per_day,
   uploads_per_hour, large_uploads_per_hour}`, `ootle.{wasm_version, mainnet_date}`, `e2e_expiry_s` only where
   configured), `/stats.{disk_total_bytes,
   disk_free_bytes, seal_log}`, `GET /canary` `revealed[]` entries carry `header`, `meta_ct`, `size_stored` so
   a visitor can decrypt with `fk` (or are `{n, sealed_at, missed: true}`), checkpoint objects carry the
   chain's `index` and `component`, `/stats/wall` items are `{size, exit}`, `GET /chain/tx/{id}/view` adds
   `substates_created` and per output
   `amount` ∈ `hidden | lower_bound | viewable | unknown` (+ `min_value_ut` when a lower bound is public)
   and `owner` ∈ `one-time key | spend rule | unknown`. **Removed:** `POST /items/{id}/claim` (P1 "Keep"
   is a re-seal in the browser; §2).
2. The `/config` class block is named `limits.locker` (spec §6.3); 11-brand §8.3 calls it `limits.free`.
3. Config key names follow spec §15.3 (`memo_origins`, not 12-integration's `allowed_memo_origins`); a new
   gate `gates.key_bundle` (G2a fallback, default false), `ootle.seallog_component`,
   `seal_log.checkpoint_interval_s` (default 900) and `e2e_expiry_s` (default 0). Unknown keys stop the
   service on purpose.
4. Add the owner's real Tari Universe / L1 address samples to `server/tests/make_vectors.py` (`addr.json`
   `pending` note), then re-run it.
5. `features.kept` defaults to `true` (P1 item 1 is in this build: "Only me" files and the locker list);
   set it off in the TOML if kept files should wait.
6. Job error codes for the §6.4 catalogue and the app-ui copy map (`GET /jobs/{id}` → `error`, review L13):
   `walletd_unreachable` (walletd didn't answer; retried), `walletd_error` (walletd refused; retried),
   `walletd_timeout` (walletd took the call but didn't answer; not retried, it may have gone out),
   `rejected` (the network rejected the transaction; retried), `timeout` (no result in 15 minutes),
   `interrupted` (the worker stopped mid-send), `invalid_payload`, `budget_exhausted`, `sidecar_error`,
   `internal`. Every one leaves the item and link intact; the UI offers **Try again**.
7. `/privacy`, `/how` and the glass box (review L10): `shares.first_opened_min` is the **minute** of the
   first open (owner only, P-25) and `items.exit_hour` the hour of deletion; the daily database backups
   hold the wrapped keys of links that were active at backup time for 7 days; the wall shows a recent
   file's size class and exit rule (never whether it was opened), which someone who knows those may
   recognise. "Two independent indexers" stays banned: the mirror and the payment check both use
   indexer-b first.
8. Spec §9.5 gains the `evidence` slice and "overrides only lower"; spec §10.4 loses the `seal` job kind.

### Deploy builder

1. Release: write `server/GIT_SHA`. Run `mutis-admin migrate` before starting `mutis-api` (it refuses a
   stale schema). **This release is schema 3** (`mutis/migrations/002_review_fixes.sql` and
   `003_seal_chain_index.sql`, tested against a copy of the deployed schema 1); stop `mutis-chain` for the
   migration. `mutis-admin check-config` validates the TOML.
2. `mutis-chain` reaches the API at `http://<listen>` for the canary (the sidecar uploads through it; the
   worker opens the canary link once): keep it on `127.0.0.1:8787`.
3. Sidecar command: `[sidecar] node`, `dir` (→ `node --experimental-permission --allow-fs-read=<dir>
   --disallow-code-generation-from-strings <dir>/sidecar.mjs` with `<dir>` resolved through symlinks, env
   `MUTIS_API` only) or a full `command` list for the Chromium fallback. `expected_wasm_sha256` defaults to
   the pinned 0.45.0 hash.
4. `receiver.json` / `robot.json` = the sidecar's `newKeys` answer as JSON
   (`owner_sk, view_sk, owner_pk, view_pk, address`). The worker reads `view_sk` (receiver) and all three
   for the robot.
5. `amount_proof = "sidecar"` once the real sidecar runs in production (`test_real_sidecar.py` passes on
   the server); until then `"wallet"` makes invoices pay to walletd's `service` address.
6. Healthcheck inputs: §2 "Worker status". Evidence: `SELECT result FROM jobs WHERE evidence = 1 AND
   state = 'done'` → `{"tx_id", "utxo_ids"}` (canary deliveries are `kind = 'courier'`, the daily payment
   `kind = 'demo_pay'`); `meta.canary_delivery_tx`.
7. Caddy: `X-Real-IP {remote_host}` (trusted only from 127.0.0.1); the API sends no `Server` header;
   `request_body max_size 5MB` fits a 4 MiB + 16 chunk.
8. walletd: the worker uses accounts `sponsor`, `service` (G4 fallback) and `ootle.operator_account`
   (SealLog; default `service`, G5) by name.
9. `mutis.toml.example` may list `[budgets.evidence]` (`courier = 150`, `demo_pay_ut = 10000000`,
   `sponsor_ut = 10000000`); the defaults apply without it. `budget set` now only lowers a limit.
10. Healthcheck: `chain_status.reconcile_unknown ≥ 3` is an alert (indexers unreachable for the hourly
    check), separate from `credit_freeze`. `judge-pass new` takes `--pow-skips N` (default 100); a pass
    works for 30 days.
11. Restarting `mutis-chain` during a send is safe now: a recorded transaction is waited on, an unrecorded
    one ends as `interrupted`.

### App builders (core and UI)

1. Sidecar protocol: the server now speaks the app's implementation exactly — `canary_token` as b64u,
   `openDelivery` with `origins` → `{share_id (b64u), access_token}`, `reveal {n}` → `{fk (b64u)}`, `scan`
   memo objects `{"Message"}` / `{"PayRefAndBytes": hex}`. `epoch-manager/stats` is in the proxy allowlist.
2. **"Keep" for a received file has no server endpoint** (review H4): open the link as usual, then seal
   the plaintext again with `sealItem(…, {keepFor: identity})` as a new kept file. Drop `api.claimItem`
   and `keepWrap`; nothing on the server accepts them.
3. `POST /uploads` → `expires_at` is the **upload session's** expiry (2 h), not the file's: don't reuse it as
   a link's default expiry (`seal.createLink` falls back to `item.expiresAt`).
4. Error details the UI can use: `bad_access` on link + password has `details.tries_left`; `423 locked` has
   `details.permanent`; `428` has `details.difficulty` and, while waiting, `retry_after`; `budget_exhausted`
   has `details.kind` and `details.resets_at`; `too_large` has `details.max_bytes` and `details.class`;
   courier `rate_limited` for a locker has `details.sends_per_day`.
5. A job can stay `sending` for a few ticks while its transaction finalizes; `GET /jobs/{id}` error codes
   are listed under Integrator 6. `/s/{id}/exit` and `/seallog/*` answer `503 feature_disabled` while
   SealLog is off (hide C7 then), and `/s/{id}/exit` returns `item_id` so `/verify` recomputes the exit
   leaf with `seallog.exitLeaf(item_id, exit_hour)` before checking the proof.

### Site builder

`/stats` (60 s; `disk_total_bytes`/`disk_free_bytes` in steps of 0.1 GiB), `/stats/wall` (300 s; items
`{size, exit}` only, random order, not newest first; items show 1–2 hours after upload; `quiet: true` and
`lockers: []` below 8), `/canary` (404 until the first delivery is done; `revealed[]` may hold
`{n, sealed_at, missed: true}`) and `/config` follow §6.3 plus the fields in Integrator 1.
The tx view's outputs say `amount: "hidden"` only for outputs that hide it; render the value as given.

## 4. Open risks

- **Esmeralda resets or upgrades**: the mirror cursor must be reset (`DELETE FROM meta WHERE key =
  'mirror_cursor'`) after a reset; the reset playbook should say so.
- **CDN policy**: the indexers sit behind Cloudflare; a stricter bot rule would stop the mirror and the
  proxy. They send `User-Agent: mutis` today and work from both hosts.
- **Clock**: invoices, sessions and tickets use the API host's clock; the real sidecar stamps the canary
  with its own `Date.now()` (same host).
- **The walletd half of the `@chain` suite has not run yet** (it needs the deployed config and keys as
  `drive`); the real sidecar and the live indexers were exercised separately (`ACCEPTANCE.md`).
- **Write-ahead log residue**: `secure_delete` zeroes freed bytes in the database file; an older page
  image can sit in `mutis.sqlite3-wal` until SQLite reuses the log (normally within minutes of writes).
- **App-core still exports `claimItem`/`keepWrap`** (App builders 2): harmless (404), but dead code there.

## 5. Devil's-advocate fix pass (2026-10-11)

Every high and medium issue of `REVIEW-devil.md` is fixed, and every low except L14 (reasons in its
"Builder response"). Schema 2 (`mutis/migrations/002_review_fixes.sql`) carries the storage changes; a
fresh install and a migrated schema-1 database are identical (`test_schema.py`). New or rewritten tests:

| Issue | Test |
|---|---|
| H1 stuck sends | `test_courier`: `test_crash_between_submit_and_result` (the worker dies after walletd took the transfer; the restart waits for the same tx, sends nothing new, scrubs the payload), `test_crash_before_the_transaction_was_recorded` (→ `interrupted`), `test_unexpected_errors_end_the_job`, `test_a_transaction_that_never_settles_is_given_up_and_scrubbed`, `test_cleanup_scrubs_a_send_left_by_a_dead_worker` |
| H2 PoW escalation | `test_vectors.ProofOfWork`: `test_a_shared_network_retries_at_base_difficulty` (4 challenges each for demo_pay, register, drop_create, sponsor from one IP key: all at base), `test_asking_for_challenges_never_escalates` (5,000 requests: still 16 bits, nothing stored per key), `test_a_real_flood_still_escalates` (9 solutions → 20 bits, 27 → 22) |
| H3 reconcile | `test_payments`: `test_a_transient_indexer_error_never_freezes_credits` (503, 429, a non-JSON 200, unreachable: no freeze; the next buyer is credited; critical log after 3), `test_check_outcomes` (9 answers), `test_a_mismatch_needs_every_indexer_to_agree`; live: `tests/chain/test_live_chain.py::test_committed_outcomes` on both indexers |
| H4 Keep | `test_contract.Links.test_no_server_side_keep` |
| M1 leaf indices | `test_seallog.LeafOrder` |
| M2 receipts | `test_seallog.Receipts.test_off_means_no_receipts_at_all`; `item_id` recomputes the exit leaf in `test_stored_and_exit_receipts_end_to_end` |
| M3 evidence slice | `test_courier.test_lockers_cant_reach_the_evidence_slice`, `test_claim_order_puts_evidence_and_reserved_first` |
| M4 shared counters | `test_courier.test_refused_senders_dont_use_up_a_destination` (the review's probe: 25 refused tries, then an honest sender gets 202), `test_refused_drop_deliveries_dont_use_up_the_drop` |
| M5 heartbeat | `test_courier.Heartbeat` (beats during a long step so `/courier` stays 202; stops after a 5-minute stall) |
| M6 disk sizes | `test_contract.System.test_stats_and_wall` |
| M7 tx view | `test_contract.ChainReads.test_tx_view_reads_each_output_before_calling_it_hidden`; `test_mirror.test_mirror_records_what_each_output_reveals`; the recorded live fixture |
| M8 spend bounds | `test_payments.test_demo_payments_go_only_to_our_receiver`, `test_courier.test_overrides_only_lower_a_budget`, `test_seallog.Receipts.test_failed_submission_retries_in_ten_minutes_and_force_is_rate_limited`, `test_schema` (the `seal` kind is refused) |
| Lows | L1 `test_input_safety.test_non_canonical_ticket_is_not_found`; L2 `test_contract.Uploads.test_a_bad_rewrite_of_a_good_chunk_unregisters_it`; L3 `test_contract.System.test_wall_is_shuffled_and_holds_new_items_back`; L5 `test_admin.test_judge_pass`, `test_judge_pass_expires`; L6 `test_quota`; L7 `test_schema.test_connections_zero_deleted_bytes`; L11 `test_contract.Links.test_items_page_cursor`; L12 `test_seallog.Tree` (level-based proofs equal the RFC's recursive PATH); L15 `test_mirror.test_a_switch_of_indexer_restarts_the_cursors`; L16 `test_vectors.Memory`; L17 `test_courier.Decoys` |

## 6. Integration responses (2026-10-11)

Every request aimed at `server/` in the builders' NOTES, NOTES-ui and REVIEW-devil "Builder response"
files, and every 12-integration §7 ratification that touches it, is applied below except one (rejected,
last). Schema 3 (`mutis/migrations/003_seal_chain_index.sql`) adds two columns; a migrated schema-1
database still equals a fresh install (`test_schema`).

| From | Request | Change | Test |
|---|---|---|---|
| template NOTES §2, 12-integration §7.2 | pad strictly: at least one pad per checkpoint | `seallog.make_checkpoint` pads to the next multiple of 64 above the size | `test_seallog.LeafOrder.test_every_checkpoint_grows_by_at_least_one_pad`, `SharedVector.test_padding_rule` |
| template NOTES §2 | a refused append settles as failed; the next checkpoint commits its leaves | already the behaviour; the fake chain now refuses like 2.0.0 (multiple of 64, must grow) so it is tested | `test_seallog.Receipts.test_a_refused_append_fails_and_the_next_checkpoint_covers_its_leaves` |
| template NOTES §2, 12-integration §7.2 | cadence from config, 900 s | `seal_log.checkpoint_interval_s` (default 900, refused below 600), used by the worker, the receipts' `next_checkpoint_eta` and `/config` | `test_seallog.Receipts.test_stored_and_exit_receipts_end_to_end`, `test_contract.System.test_config`, `test_input_safety.test_config_rules` |
| template NOTES §2 | name the component and the chain's checkpoint index | schema 3 columns; `chain_worker.root_event` reads the `SealLog.root` event from walletd's result; checkpoint objects: `index` (chain), `component` | `test_seallog.Receipts.test_stored_and_exit_receipts_end_to_end` |
| template NOTES §2 | load `seallog-v1.json` in the server tests | leaves, roots, proofs and the padding rule | `test_seallog.SharedVector` |
| 12-integration §7.3, deploy server 3 | SealLog from `service` | `ootle.operator_account` defaults to `"service"` | suite |
| site §3.1 | drop `state` and `ttl` from `/stats/wall` | items are `{size, exit}` | `test_contract.System.test_wall_shows_no_opens_and_no_takedowns` |
| 12-integration §7.7 | E2E cleans up after itself | taken-down items leave the wall at once (no purge needed there) | same test |
| site §3.2, app-core server 5 (review L8) | a reveal the restarted sidecar can't answer shows as missed | `{n, sealed_at, missed: true}` in `revealed[]`, never asked again | `test_canary.test_a_key_the_restarted_verifier_lost_is_published_as_missed` |
| app-core server 1 (review M1) | a judge pass lifts the per-/64 and per-/48 limits of sponsor and demo-pay | `invoices._unless_judge`; per-locker limits and the pass's uses stay | `test_admin.test_a_judge_pass_lifts_the_network_limits_of_grants_and_demo_payments` |
| app-ui NOTES-ui (review M8) | `/config.e2e_expiry_s` only where configured | config `e2e_expiry_s` (default 0 = absent) | `test_contract.System.test_e2e_expiry_preset_only_when_configured` |
| deploy server 1 | ids that start with `-` | `takedown` usage and help say `-- <id>`: argparse classifies an argument that starts with `-` as an option before any type runs, so no type can accept one (the E2E already passes `--`) | `test_admin.test_takedown_share_item_drop` |
| deploy server 2, 5 | umask; pre-migrate copy only when pending, 0600 | `os.umask(0o007)` in every `bin/*`; `admin._backup` + `db.version` | `test_admin.test_check_config_and_migrate` |
| deploy server 4, deploy integrator 1 | resolve `sidecar.dir` | `Config.sidecar_argv` uses `os.path.realpath` | `test_input_safety.test_config_rules` |
| deploy server 6 (review M6) | per-/64 cap on requests in flight | `api.InFlight`: 32 per /64, 128 per /48, else `429 rate_limited` | `test_input_safety.test_requests_in_flight_are_capped_per_network` |
| 12-integration §7.4 | claim registry | README "privacy promises": the credit row has the `wallet` and proven variants (C11), the relay row says direct-mode memos are bounded by the sponsor budget, SealLog volume and idle windows, the wall's two classes | — |

Already true, no change: app-core server 2 (every indexer request sends `User-Agent: mutis`); 3 (ids are
`codec.new_id()`, canonical 16-byte base64url; a non-canonical id matches nothing and answers 404); 4
(`amount_proof` is a string, `memo_origins` lists both hosts, `text_max_chars` = `quota.TEXT_MAX_CHARS`);
6, second half (`/me/items/{id}/open` answers `ticket`, `ticket_expires_at`, `inline_ct` like
`/s/{id}/open`); 7 (`judge_passes.pow_skips_left` has a default, so app-core's insert works).

Fixed while testing on the server: `test_real_sidecar`'s canary test failed about half the time. The test froze
the API clock while the real sidecar stamps `expires_at` with its own, later clock; once a second boundary
fell in between, `expires_at` exceeded `now + 48 h` (`422 invalid`). Production's API clock moves, so only
the test changed (the API reads the real clock there): 5 runs out of 5 pass since.

**Rejected:** app-core server 6, first half (return `item_id` from `/s/{id}/open`, or accept
`POST /s/{id}/claim`, for P1 "Keep"). A server-side claim lets a recipient cancel a Once link's exit
without opening it and shows the sender a false "revoked" (review H4). "Keep" stays a re-seal in the
browser with `sealItem(…, {keepFor})`, so every exit sentence stays literally true; both claim routes
answer 404 (`test_contract.Links.test_no_server_side_keep`).

## 7. Integration requests (2026-10-11)

**Deploy builder**
1. This release is schema 3: `mutis-admin migrate` on activation, as today (stop `mutis-chain` first).
2. Production config: `gates.amount_proof = "sidecar"` (12-integration §7.6) in `/etc/mutis/mutis.toml` and
   `mutis.toml.example`. `[seal_log] checkpoint_interval_s = 900` may be listed there (the default applies
   without it); `operator_account = "service"` is now the default.
3. E-05 against production: set `e2e_expiry_s = 60` for the run and remove it afterwards (or run before the
   go-live reset). `mutis-api --dev` leaves it off, as production does. Items the run takes down leave the
   wall immediately.
4. `/usr/local/lib/mutis/run-sidecar.sh` is optional now: `sidecar.dir` is resolved through symlinks.
5. `collect-evidence.py` may add `seal_checkpoints.chain_index` (and `component`) to `latest_checkpoint`, so
   `/evidence.json` names the checkpoint number a reader finds on chain.

**Site builder**
1. `/canary` `revealed[]` may hold `{"n", "sealed_at", "missed": true}` (no `fk`, `raw` or `header`): show
   "missed (the verifier restarted)" for that hour (your NOTES §3.2 asked for the field name: `missed`).

**App builders (core and UI)**
1. Checkpoint objects (`/seallog/proof`, `/s/{id}/exit` → `checkpoint`, `/seallog/checkpoints`) carry
   `index` = the component's own checkpoint number (null if the worker couldn't read the event) and
   `component`; `epoch` is the event's epoch, so `/verify`'s match on `leaf_count` and `epoch` against the
   component state is exact. `/verify` can also require `checkpoint.component === /config.seal_log.component`.

**Integrator (spec patches)**
1. §11.3: cadence = `seal_log.checkpoint_interval_s` (900 s), pad to the next multiple of 64 **above** the
   size. §6.3: checkpoint objects (`index` = chain index, `component`), `/stats/wall` items `{size, exit}`,
   `/canary` missed entries, `/config.e2e_expiry_s`. §6.2: the in-flight caps. §15.3: the new keys and the
   `operator_account` default.
