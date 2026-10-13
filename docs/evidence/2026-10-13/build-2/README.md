<!-- SPDX-License-Identifier: MIT -->
# The ghost, stage 2 (Phase 6B steps 5 to 7), 2026-10-13

The receipts of the second build stage of the redesign (14-ghost-design §17 steps 5 to 7: the home
widget with the whole window as its target and the wow, the rule on the figure with the secret word,
and the QR codes with the locker's hand-offs). Times in UTC. Nothing here is a secret: no judge pass,
no production link, no screenshot of a link (the E2E shots show production links, so they stayed
out); the links in `suites/ui.log`, and the one secret word it prints, belong to a throwaway dev
server.

| Folder | What |
|---|---|
| `suites/` | On the server as `build` from a `git archive`: `ui.log` at `d5e41b4` (UI PASS 341/341, with the new flows `window-drop` and `rule-ghost`); `server.log` (203 tests OK, 4 opt-in skips), `site.log` (29 of 29), `core.log` (ALL PASS in 9 steps), `deploy.log` (73 tests OK), `lint.log` and `copy.log` (PASS) at `fdcafa1`, which differs from `d5e41b4` only in the UI flow file. The step 5 to 7 commit `12d6651` had all of these green except one site check (a synthetic drag can't send `dragleave`; fixed in `fdcafa1`). |
| `deploy/` | `deploy-ec2956b.txt`: `deploy.sh HEAD` → release `ec2956b4ccbac02621f5f88bf772cc1577916c93-c546f93a7`, smoke test PASS. The manifest's notarization did not commit (tx `1ecdcf01…`, and once more by the documented retry, tx `4541a3fb…`): the chain worker was already logging failed jobs on the testnet before the deploy, so it was left for a later retry. `verify-deploy-ec2956b.txt`: 0 differences across 125 files. `d01-test_headers-ec2956b.txt`: D-01 PASS (51 checks, the 14 redirects included). |
| `e2e/` | `run.py --only E-01,E-02,E-03,E-04,E-06,E-07,E-15,E-16,E-19,E-20,E-22,E-24` against production on that release: 12 of 12 PASS (`batch.log`, `reports/`), no chain transaction, no grant spent, no `e2e_expiry_s` (E-05 was not in this batch). `purge.txt`: the twelve items and the one drop the batch made, taken down by id from a read-only diff against a snapshot taken before it; the four empty test lockers have no admin removal and stay. |

A-06 (the widget's payload after a first text drop, gzip -9 of every `/app/` file the home page
requested), measured after each step: step 5's first cut 40,081 B; with its layout 40,163 B; steps 5 to
7 together 40,332 B on a phone. At `d5e41b4`: **40,322 B on a phone** (≤ 40,960, the QR encoder never
loads there), **43,289 B on a computer** with the encoder (≤ `QR_CEILING` = 43,520 B, the waiver
decided in step 0), 45,360 B after a photo on a phone (≤ 48 KB). After the purge: 20 judge passes, the
security drop active, no `e2e_expiry_s`, `/status.json` amber with the one reason
`budget.sponsor.evidence.90`; among its checks `sponsor_balance` read `sponsor_low` and `canary` read
`canary_in_flight`. About ten minutes later `canary` turned red (`canary_unverified`): canary #39's
delivery job (sealed 11:03:31) had failed with `walletd_error` after three attempts at 11:04:51, seven
minutes before this deploy restarted the chain worker (11:11:42); #34 to #38 were verified, and two
sponsor jobs and three decoy jobs of the last six hours failed the same way. The wallet daemon belongs
to the drive user and was not touched; the next hourly canary shows whether it recovered.
