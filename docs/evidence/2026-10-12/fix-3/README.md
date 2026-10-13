<!-- SPDX-License-Identifier: MIT -->
# Function review fixes, 2026-10-13

The receipts of the function review's fixes (docs/review/fix-log.md, "The function review"; times in
UTC on 2026-10-13): the suites, the deploy, the release of the test packs, the end-to-end runs against
production, the purge, the link crawl and the secrets gate before the public step. Nothing here is a
secret: no judge pass, no link, no transaction id of a test send, and no screenshot (the E-J shots
show test transaction ids, so they stayed out).

| Folder | What |
|---|---|
| `suites/` | On the server as `build` from a `git archive` of `8959c6f`: `server.log` (203 tests OK, 4 opt-in skips), `site.log` (27 of 27), `ui.log` (UI PASS 220/220), `core.log` (ALL PASS in 9 steps: lint 836/836, KATs 120/120 in Node 20 and in Chromium, jitless 75/75, sidecar 16/16, the 4× scan bench 47.7 s, contract 12/12). Locally: deploy tests OK, lint PASS, copy check PASS. |
| `deploy/` | `deploy-39bd45c.txt`: `deploy.sh HEAD` → release `39bd45cc439bd835f35effccb05d7536af949008-cb6b8404f`, smoke test PASS, manifest `c059e205a6f8…` notarized in tx `60b75600…c707`. `verify-deploy-39bd45c.txt`: 0 differences across 129 files, and the chain runs `seal_log.wasm` byte for byte. `d01-test_headers-39bd45c.txt`: D-01, 40 PASS. `release-packs.txt`: the 11 test packs ended with `mutis-admin release-pack`. |
| `e2e/` | `run.py` against production on that release: `ej.log` (E-J, direct mode), `batch1.log` (every scenario without chain transactions, `--final`), `e13.log` (E-13), their `reports/`, `e2e-expiry-times.txt` and `purge.txt`. |
| `links/` | `crawl.txt`: every link on the live pages, fetched anonymously. |
| `gate/` | `secrets-gate.txt`: what was searched before the public step, where, and why the public step stopped. |

| Run | Scenarios | Result |
|---|---|---|
| ej, 04:28 | E-J, direct mode | PASS, 104 s: track A 5 s, track B 95 s (B2 37 s, B3 15 s, B6 22 s); cold start 71 s (within 3:15); the send and the pack payment built and submitted by the browser; its pack released at the end |
| batch1, 04:31–04:36 | E-01, E-02, E-04 to E-08, E-15 to E-22, E-24, E-03, with `e2e_expiry_s = 60` | 17 of 17 PASS |
| e13, 04:37 | E-13, direct mode | PASS, 37 s: grant, Waiting → Seen → Amount proven → Added, quota +2 GiB, pack released |

Before E-J, the 11 test packs that had filled the paid-space cap were released (0 active packs
afterwards), so B6 could buy one. After the purge: 20 judge passes, the security drop active, no
active pack, no `e2e_expiry_s` in `/config` or the TOML, the wall quiet. `/status.json` reads amber
for one reason, `budget.sponsor.evidence.90`: the end-to-end runs of this pass and the two before it
used 9 of the 10 grants the judge-pass slice has for the UTC day; it resets at 00:00 UTC, and a
judge whose grant is refused now sees it said and can pay with demo tTARI instead.
