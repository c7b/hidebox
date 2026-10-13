<!-- SPDX-License-Identifier: MIT -->
# The ghost, stage 1 (Phase 6B steps 0 to 4), 2026-10-13

The receipts of the first build stage of the redesign (14-ghost-design §17 steps 0 to 4: the
baseline and the A-06 measure, the copy rules and the public name, tokens and brand files, the ghost
partial, the six pages and their redirects). Times in UTC. Nothing here is a secret: no judge pass,
no production link, no screenshot of a link (the E-19 shots show one, so they stayed out); the one
key in `suites/ui.log` belongs to a throwaway dev server's link.

| Folder | What |
|---|---|
| `suites/` | On the server as `build` from a `git archive` of `fb8860c` (the six pages): `server.log` (203 tests OK, 4 opt-in skips), `site.log` (29 of 29), `ui.log` (UI PASS 255/255, the new `ghost-states` flow included), `core.log` (ALL PASS in 9 steps), `deploy.log` (73 tests OK). Lint PASS and the copy check PASS (with the claim registry, `tools/claim-registry.json`). The two commits after it hold only screenshots. |
| `deploy/` | `deploy-67fdb06.txt`: `deploy.sh HEAD` → release `67fdb06e2bde2eb0ef3098e4e2d5271a99a8086b-c112bb50f`, the Caddyfile reloaded (the 301s), smoke test PASS, manifest notarized. `verify-deploy-67fdb06.txt`: 0 differences across 122 files. `d01-test_headers-67fdb06.txt`: D-01, 50 PASS, with the 14 redirects of the old pages. |
| `e2e/` | `run.py --only E-18,E-19,E-21` against production on that release: 3 of 3 PASS (`e18-e19-e21.log`, `reports/`), no chain transaction, no grant spent; `purge.txt`: the two E-19 items taken down by id, the hourly test file kept. |

Before the stage, the same suites at `8116ee2` were green except one UI flake (deaddrop's click to
`/verify/tx` raced an evaluation; fixed in the test harness, `8f05413`). The widget's A-06 payload after a
text drop went from 39,590 B to 39,754 B (the brand constant and the rounded buttons). After the
purge: 20 judge passes, the security drop active, no `e2e_expiry_s`, `/status.json` amber for
`budget.sponsor.evidence.90` only.
