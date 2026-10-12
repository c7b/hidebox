<!-- SPDX-License-Identifier: MIT -->
# Go-live evidence, 2026-10-11

mutis went live on `https://srv2052606.hstgr.cloud` on 2026-10-11 (times below are CST, UTC−6). This
folder holds the receipts of that day: the SealLog publish, the deploys, the acceptance drills
(deploy/ACCEPTANCE.md, "Go-live results") and the end-to-end runs. Nothing here is a secret: no
owner key, no judge pass, no transaction id of a test send (spec §8.4: only the canary and the
service's own transactions are public), and no screenshot that shows one.

## What is live at the end of the day

| | |
|---|---|
| Release | built from the repository's HEAD (`deploy/scripts/deploy.sh HEAD`; anyone checks it with `python3 -I tools/verify-deploy.py https://srv2052606.hstgr.cloud <commit>`). The last code change of the day is `68cd712`; its release `68cd712…-c88c6fb32` passed D-09 at 19:59 and is notarized on SealLog in tx `c2ac2616…d8e8` (`public/json/releases.json`). The commits after it only add documentation, each deployed the same way |
| Config | `send_mode = "direct"` (with `features.direct_send` and `features.sponsor`), `amount_proof = "sidecar"`, `features.seallog = true`, `seal_log.checkpoint_interval_s = 900`, `hosting.snapshots = "weekly"`, `ootle.mirror_start_epoch = 12140`; `e2e_expiry_s` removed (`public/json/config.json`) |
| SealLog 2.0.0 | template `template_40c5f1cfccf753613ce99245ed49ebef0b308084a52ad0c5cd48959d90fa0a47`, published raw by `service` in tx `07b4422b…e546` (the chain holds `template/dist/seal_log.wasm` byte for byte, sha256 `9af71aa2…d6f2`); the log `component_b7d212151546338e8e17975f7d8a4fb67023047357fe41308935fbb75604fdf2`, made in tx `3fb7657f…f726`; retired logs listed in `/evidence.json` (`seallog/`) |
| Database | fresh at go-live (schema 3); after the tests, every E2E item and drop taken down by id, the forged E-14 payment rows and their invoices deleted, the E-J judge pass deleted; the owner's locker, the security dead drop that `security.txt` points to, the robot's canary items and the 20 judge passes untouched (`deploy/step7-purge.txt`) |
| Wall | quiet, canary only (`public/json/stats_wall.json`); `/status.json` green on every check (`public/json/status.json`) |
| Units | walletd, caddy, mutis-api, mutis-chain; timers cleanup (1 min), health (5 min), evidence (hourly), backup 03:30, backup-wallet 03:35 |

## Timeline

17:37 go-live config and fresh database · 17:41 SealLog 2.0.0 published and instantiated · 17:42 first
deploy with `features.seallog` on · 17:48–17:53 D-01, D-02 (`--relay`), D-03, P-18 · 18:04–19:03 E2E
batches 1–3 (fixes between them, each committed) · 18:32 D-07 health drill · 19:30 E-11 and E-14 ·
19:32 E-J relay · 19:32 backups and restore drill · 19:35 D-04 reboot · 19:37 E-23 griefer and the
final consolidated run · 19:44 E-J direct · 19:47 purge · 19:48 `e2e_expiry_s` removed, deploy
`68cd712` with the direct copy variants · 19:59 D-05 idempotent redeploy, D-09 verify-deploy.

## Acceptance (deploy/ACCEPTANCE.md "Go-live results" has the full table)

D-01 PASS · D-02 PASS · D-03 PASS · D-04 PASS · D-05 PASS · D-06 restore drill PASS, three days of
timer runs pending · D-07 PASS · D-08 PASS · D-09 PASS · D-10 PASS · D-11 PASS · D-12 WAIVED (G5
fallback: `service` owns and writes the log) · P-18 PASS.

## End-to-end runs (`e2e/`)

| Scenario | Result | Where |
|---|---|---|
| E-01, E-02, E-04, E-05, E-06, E-07, E-08, E-11, E-13, E-14, E-15, E-16, E-17, E-18, E-19, E-20, E-21, E-22, E-24, E-25, E-03 | PASS, 21 of 21 | `final.log`, `reports/final-20261011-193727.json` (`run.py --chain --final`) |
| E-09, E-10, E-12 | PASS | `batch2c.log`, `reports/batch2c-*.json` |
| E-J, relay mode | PASS, 2.1 min (track A 5 s, track B 123 s) | `batch5.log`, `reports/batch5-*.json`, `shots/batch5-*` |
| E-J, direct mode | PASS, 1.8 min (track A 5 s, track B 105 s), cold start 82 s, B6 built and submitted by the browser | `direct.log`, `reports/direct-*.json`, `shots/direct-*` |
| E-23 griefer | PASS (local stack, never production) | `../deploy/e23-griefer.txt` |
| E-18, E-21 after the switch to direct | see `post.log` | `reports/post-*.json` |

`batch1*.log`, `batch2*.log` and `batch3.log` are the earlier runs with their failures; each failure
was root-caused and fixed in the repository before the next batch (git log of 2026-10-11). E-11's
last failure was in the test itself: `needs-locker` is also a `VIEW_END` state, so the wait returned
before the pasted view key had been used.

## Fix pass (`fix-pass/`, 22:11–00:35)

The fix pass after the judge-run and claims reviews (docs/review/fix-log.md) deployed release
`7c9e627…-c9a2957d0` at 22:11 and, after the tests, the last code change `3cd5622` (tests only) with this
documentation, the same way (`/api/v1/health` prints the release that is live). `suites/` holds the four suites' logs on the server
(server 197, site 28/28, app-ui 229/229, app-core ALL PASS) and `deploy/` the deploy log, D-01 on the
throwaway stack and on production, and D-09. `e2e/` holds the production runs on the new code: every
scenario and E-J in direct mode (`batch1.log` to `batch2e.log`, `reports/`, a few screenshots as PNG
in `shots/`); the two E-13 failures and E-J's first attempt were the test and the rate limit, not the
product (the fix-log's "Evidence" section). The E2E data was purged by id (`deploy/purge.txt`); the wall reads quiet, canary only.

## Files

- `seallog/`: publish dry run, publish, instantiate, `check --onchain`, the component header from the indexer, the `service` top-up.
- `deploy/`: the deploy logs, D-01…D-07, D-09 outputs, the reboot drill, the backups and restore drill, the griefer, the fonts check, the purge summary and the post-purge checks (`step7-*.txt`).
- `e2e/`: batch logs, `reports/*.json` (every scenario's checks and timings), `shots/` (a few screenshots as JPEG; none shows a link with its key or a transaction id).
- `public/json/`: `/api/v1/config`, `/api/v1/stats`, `/api/v1/stats/wall`, `/api/v1/canary`, `/api/v1/seallog/checkpoints`, `/evidence.json`, `/releases.json`, `/status.json`, the hash manifest and the SealLog component's substate, as served after the purge; `public/headers/`: response headers of the main routes and the HTTP→HTTPS redirect.
