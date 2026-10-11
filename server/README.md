<!-- SPDX-License-Identifier: MIT -->
# mutis server

The server side of mutis: an HTTP API that stores ciphertext it can't read, a chain worker that delivers
sealed keys inside stealth TARI outputs and proves payments, and the cleanup and admin tools around them.
**Python 3.13, standard library only** (no pip, no third-party code; `test_stdlib.py` checks every import).

Behaviour, numbers and shapes follow `docs/api.md` / spec §6 exactly; this file says how to run things.

## Run the tests (one command)

From the repository root:

```sh
python3 -I -m unittest discover -s server/tests
```

178 tests, about 30 seconds (ultron, Python 3.13.5: `Ran 178 tests in 28.056s, OK`). Opt-in suites:

| Command | What it adds |
|---|---|
| `MUTIS_BIG=1 python3 -I -m unittest discover -s server/tests -p test_streaming.py` | S-09: 2 GiB up and down through the API, API peak RSS < 96 MiB (needs 2 GiB of disk; set `TMPDIR` off tmpfs) |
| `MUTIS_SIDECAR_DIR=$PWD/web/app python3 -I -m unittest discover -s server/tests -p test_real_sidecar.py` | the client against the real Node sidecar (official ootle-wasm): pinned hash, forgery selftest, a canary sealed with the real `lib/` through this API and opened with the robot keys |
| `MUTIS_CHAIN=1 MUTIS_CONFIG=/etc/mutis/mutis.toml python3 -I server/tests/chain/test_live_chain.py` | the `@chain` suite as `drive` on ultron: walletd, the public indexers, the deployed sidecar; `MUTIS_CHAIN_SEND=1` also sends 1,000 µT to the robot locker |

`test_crossvectors.py` reads the app builder's `web/app/tests/vectors/{format-v1,merkle-rfc9162}.json`
(skipped when they are absent). `tests/make_vectors.py` writes `tests/vectors/{addr,quota,pow}.json`;
`test_vectors.py` fails if the committed files drift from the code. `test_schema.py` migrates a copy of
the deployed schema 1 (`tests/fixtures/schema-v1.sql`) and requires exactly the schema a fresh install gets.

## Development mode

```sh
python3 -I server/bin/mutis-api --dev --data /tmp/mutis-dev --dist dist --port 8787 --pow-bits 10
```

The real API contract on `http://127.0.0.1:8787` with: a temporary data directory and a random
`secret.key`; small lanes and budgets; a fake walletd and a fake indexer over one fake chain (the
mirror fills, deliveries and payments complete, the hourly canary seals and is verified); the fake
sidecar; the chain worker and cleanup in threads; and, with `--dist`, the built site and app with
Caddy's rewrites and CSP headers. `--pow-bits` fixes the PoW difficulty (no escalation). Fake chain
outputs are not real cryptography and don't decrypt in a browser; chain flows are tested on staging.

## Processes

| Program | Runs as | Job |
|---|---|---|
| `bin/mutis-api` | `mutis` | `ThreadingHTTPServer` on `127.0.0.1:8787` behind Caddy; refuses to start if the schema is behind |
| `bin/mutis-chain` | `drive` | the chain worker: UTXO mirror (3 s), payment proof (10 s), sends, decoys, hourly canary, daily evidence payment, hourly reconcile, SealLog checkpoints every 6 h; a heartbeat thread for the API |
| `bin/mutis-cleanup` | `mutis` | one pass of spec §8.2; a timer runs it every 60 s |
| `bin/mutis-admin` | `mutis` (`drive` for walletd commands) | `migrate`, `check-config`, `takedown share/item/drop <id>`, `reports [--new]`, `freeze all/free/none`, `feature <name> on/off/clear`, `budget show` / `budget set <kind> <slice> <value>` (lowers a limit for the day), `unfreeze-credits`, `canary-now`, `evidence-pay-now`, `seal-now`, `judge-pass new [--uses N] [--pow-skips N] [--count N]`, `walletd-fixture <method> [json]`, `notarize <sha256>`, `e2e-forge-payment <invoice>` (E-14) |

Every script inserts its own `server/` directory into `sys.path`, so they run with `python3 -I`.
`server/GIT_SHA`, if present, is reported by `/api/v1/health` (deploy writes it into the release).

A send is claimed, submitted to walletd, its transaction id recorded, and its result read on later
ticks. A restart waits for a recorded transaction instead of sending again; a job claimed but never
recorded ends as `interrupted`. The worker gives a transaction up after 15 minutes, and cleanup ends
any send still open 30 minutes after it was due or submitted (for a worker that is down), scrubbing its
destination either way.

## Configuration

`/etc/mutis/mutis.toml` (or `$MUTIS_CONFIG`) over the defaults in `mutis/config.py`. An unknown key or
a wrong type stops the program: `mutis-admin check-config` validates a file. Defaults worth knowing:
`public_origin = "https://srv2052606.hstgr.cloud"`, `memo_origins` = that and `https://mutis.sh`,
`gates.send_mode = "relay"`, `gates.amount_proof = "wallet"` (until the real sidecar runs in production),
`gates.key_bundle = false`, `features.kept = true` (kept "Only me" files), `features.seallog = false`
(needs `ootle.seallog_component`; while off the receipt endpoints answer `503 feature_disabled`),
`hosting.snapshots = "weekly"`, and three budget slices: `budgets.public`, `budgets.reserved`,
`budgets.evidence` (the canary, the daily evidence payment and judge passes).

## Where the privacy promises live in the code

| Promise | Enforced by |
|---|---|
| No IP, token, id, address or header value in logs | `logsafe.py` accepts only a route name, a status, a duration and fixed event codes; `api.py` replaces `http.server`'s logging; `test_never_store.py` runs the whole contract suite and requires every log line to match those two formats |
| IPs only in memory, keyed by the day | `ipkeys.py` (HMAC with a key regenerated at 00:00 UTC, never written); rate limits and the bounded tables in `ratelimit.py` |
| The schema has no name, type, IP, public key or recipient column | `schema.sql`; `test_never_store.Schema` |
| Exactly one of N concurrent opens burns a Once link | `handlers/shares.py` `_open_in_tx` in one `BEGIN IMMEDIATE`; `test_burn_race.py` (50 threads) |
| A link's wrapped key is scrubbed when it ends: in the request that opens, revokes or deletes it, or within a minute of its expiry. SQLite zeroes the bytes it frees in the database file (`PRAGMA secure_delete`); an older page can stay in the write-ahead log until the log is reused, and in the daily backups for their 7 days | `items.end_share`, `cleanup.expire_links`, `db.connect`; `test_cleanup.py`, `test_schema.py` |
| Ciphertext is unlinked within a minute of its exit, or when an open download ticket ends (at most 30 minutes); a canary is kept 48 hours | `items.unlink`, `cleanup.py`; `test_cleanup.py`, `test_canary.py` |
| No link outlives its rule: there is no server-side "Keep" for a received file | a recipient keeps one by sealing it again as their own file; `test_contract.Links.test_no_server_side_keep` |
| The relay can only carry our own memo to the intended address | `jobs.courier_memo` (built from `PUBLIC_ORIGIN`), drop deliveries use the drop's address, the worker re-validates every payload; `test_courier.py` |
| A destination address lives in the database only while its send is pending | payloads scrubbed to `NULL` when a job ends; an unsettled send ends within 30 minutes; finished user jobs deleted after a day; `test_courier.py` |
| Credit only what the official library proved and a Tari indexer (not walletd) confirms | `payments.py` (+ `sidecar.py`, `indexer.py`); credits freeze only when every indexer says a credited output is gone; `test_payments.py`, `test_real_sidecar.py` |
| A bug in the API can spend at most the daily budget slices, plus SealLog fees for at most one checkpoint every 10 minutes | the worker pays demo payments only to the receiver it learned itself, makes checkpoints itself (every 6 h; `seal-now` no faster than every 10 minutes, each fee capped at 1 tTARI), and ignores budget overrides above the TOML; `test_payments.py`, `test_seallog.py`, `test_courier.py` |
| SealLog shows volume only in steps of 64 | a leaf gets its index at the checkpoint that commits it, shuffled within that batch; `test_seallog.LeafOrder` |
| `/stats` shows disk sizes only in steps of 0.1 GiB, and the wall in random order without items under an hour old | `handlers/stats.py`; `test_contract.System`. (`last_sealed_min`, defined by the spec, does say to the minute when the latest upload finished.) |

## Gate G3 (indexer UTXO framing) — answered

`POST /utxos/stream` with `Accept: application/json` answers NDJSON lines `{"sos","update","eos"}` per
shard (1–256; shard 0 is refused), and an `Unspent` update carries only `tag` (u32) and `public_nonce`
(32 bytes as a number array). The worker keeps a per-shard cursor (`max_state_version`) per indexer and
fetches full outputs with `POST /utxos/fetch {tag_and_nonce_pairs}` → `[commitment_hex, {output:{output:
{public_nonce, encrypted_data, minimum_value_promise, viewable_balance}, auth, tag}}]`. Evidence:
`NOTES-for-integrator.md` §1.
