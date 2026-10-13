<!-- SPDX-License-Identifier: MIT -->
# English-only pass, 2026-10-12

The receipts of the third pass (docs/review/fix-log.md, "Third pass"; times in CST, UTC−6): Spanish
removed from the product, the self-hosting guide followed from a clean clone, the suites, the deploy,
the end-to-end runs against production and the purge. Nothing here is a secret: no judge pass, no
link, no transaction id of a test send, and no screenshot (the E-J shots show test transaction ids, so
they stayed out).

| Folder | What |
|---|---|
| `suites/` | On the server as `build` from a `git archive` of `fd2706f`: `server.log` (202 tests OK, 4 opt-in skips), `site.log` (27 of 27), `ui.log` (UI PASS 220/220; widget payload 23,287 B at load, 39,572 B after a drop), `core.log` (ALL PASS, 9 steps). `local-checks.txt`: the deploy tests (67 OK), the lint, the copy check against the live `/config`, the widget's string subset. |
| `deploy/` | `deploy-abc5d71.txt`: `deploy.sh HEAD` → release `abc5d71f33d05bca462c76b9169e70e52bb2f2b6-cc6fca59c`, smoke test PASS, manifest `412d99c44366…` notarized in tx `1a9212e1b0dd875a5058901af9a1f3c1acfebd56929c274c2c4e1d3a20dcd348`. `verify-deploy-abc5d71.txt`: 0 differences across 129 files, and the chain runs the SealLog template byte for byte. `d01-test_headers-abc5d71.txt`: D-01 against production, 40 PASS, `/es/` and `/es/how` answer 404. `post-deploy-abc5d71.txt`: health on the commit, `/config` with direct sends, the sidecar proof, SealLog every 900 s and no `e2e_expiry_s`, `/status.json` green, a sitemap of 9 URLs with none under `/es/`. `walletd-resubmit.txt`: the walletd journal line of the second pass's open item 3, explained. |
| `selfhost/` | `try-it.log`: `docs/self-host.md`'s "Try it on your machine" from a clean clone (build, dev server, routes). `dryrun.sh` with `stubs/` and `dryrun.log`: `provision.sh` run on a simulated fresh Debian 13 root, steps 2–4 of the guide (stand-in commands log what would change; Debian's own ufw rules), then its two refusals, the guards it left and the accounts it made. `walletd-first-start.txt`: walletd's first start as step 4 describes it, tried with a throwaway wallet as `build` on the server. |
| `e2e/` | `run.py` against production on release `abc5d71…-cc6fca59c`: `ej.log` (E-J in direct mode, PASS in 75 s: track A 5 s, track B 67 s, cold start 43 s, both the send and the pack payment built and submitted by the browser), `batch1.log` (every scenario without chain transactions, `--final`, with `e2e_expiry_s = 60` from 20:49:17 to 21:00:13: 16 of 17, E-20 failed one check), `batch1b.log` (E-20 again, unchanged: PASS), `batch1c.log` (E-20 with the test's wait for the live region: PASS), `reports/`, `e2e-expiry-times.txt`, and `purge.txt`. |

E-20's one failure was the test, not the product: it read the live region the moment the link showed,
and `announce()` fills the region on the next animation frame. Its rerun passed as it was, and the
scenario now waits up to 5 s for the region (`tests/e2e/scenarios.py`).

The purge (21:02) went by id, from a read-only diff against a snapshot taken at 20:19 before the
deploy: 19 items and 6 drops taken down (`mutis-admin takedown`), E-J's judge pass deleted. Every item
was made in the run's UTC hours (02:00 and 03:00 on the 13th) and none belongs to an identity older
than the snapshot; every drop carries a label the runs type ("E2E E-08", "E2E E-17", "E2E E-20",
and E-J's "Council" and "Council computer") and none shares a locker address with an older drop. Kept, as in the earlier purges: E-J's credited pack invoice (tTARI the receiver really holds)
and the 9 test lockers. Afterwards: 20 judge passes, the security drop `/d/3w7m8k2v5t` active,
`/config` and `/etc/mutis/mutis.toml` without `e2e_expiry_s`, `/status.json` green, the wall quiet.
