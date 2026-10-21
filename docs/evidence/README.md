<!-- SPDX-License-Identifier: MIT -->
# Evidence

The raw outputs of our own test runs, deploys and drills: logs, reports, probes and screenshots, one folder per
pass under the day it ran. There is no hosted CI, so these files are the record. Each folder's README, or its
review in [`../review/`](../review/), says what ran and what it showed. Nothing here is a secret: no key, no judge
pass, no transaction id of a visitor's send.

## What each folder proves

| Folder | What it proves |
|---|---|
| [`2026-10-11/`](2026-10-11/) | The go-live: SealLog 2.0.0 published and its log made, the deploy acceptance (D-01 to D-12, P-18) that `deploy/ACCEPTANCE.md` cites, every E2E scenario's report, and what the public endpoints served after the purge |
| [`2026-10-12/english/suites/`](2026-10-12/english/suites/) | The core and UI suite logs that `web/app/ACCEPTANCE-core.md` and `web/app/ACCEPTANCE.md` cite |
| [`2026-10-14/anti-grief/`](2026-10-14/anti-grief/) | One pack per drive, the 5 GiB pack and the brakes on buying space, with the devil's run before and after (`server/mutis/handlers/invoices.py` cites it) |
| [`2026-10-14/m2/`](2026-10-14/m2/) | Pay to open in production with test money: E-29, E-30 and E-J green |
| [`2026-10-14/release/`](2026-10-14/release/) | The fifth pass's release, where the tag `spooky-secrets-2026-10` first pointed: suites, deploys, verify-deploy, the E2E runs, the film's check, a stranger's clone and crawl, the purge |
| [`2026-10-16/judge-race/`](2026-10-16/judge-race/) | E-J step 3's "Delete it from my drive after" failure: the probes, the hardened check, and E-J passing with a judge pass |
| [`2026-10-16/site-v2/`](2026-10-16/site-v2/) | The seventh pass's release (Stop sharing, Stop selling, the pay steps from the click): suites, deploy and the E2E batch |
| [`2026-10-17/site-v3/`](2026-10-17/site-v3/) | The release the contest entry links (`17f6c5b`): suites, verify-deploy at 0 differences, D-01, the live probe 25/25, the non-chain E2E batch 13/13, the purge |
| [`2026-10-19/brand-kit-1/`](2026-10-19/brand-kit-1/) | The brand kit as served: every surface before and after at 1440 and 390, the icons against the kit, the ICO against the SVG |
| [`2026-10-19/drive-earnings-activity/`](2026-10-19/drive-earnings-activity/) | Earnings, and Activity at scale: the screens and the suites |
| [`2026-10-19/owner-5/`](2026-10-19/owner-5/) | The pay page and its steps after paying, measured before and after; /verify/tx's link to Tari's indexer, probed with real transactions |
| [`2026-10-19/preview-1/`](2026-10-19/preview-1/) | Safe file previews: the hostile fixtures, the budgets, the suites and E-29 on production |
| [`2026-10-19/seo-1/`](2026-10-19/seo-1/) | Search and link previews: `check-seo` on the live site, on a build and on the production Caddyfile, D-01, the mutants |
| [`2026-10-19/site-404/`](2026-10-19/site-404/) | The 404 page: what the browser saw, its budget, the mutants, D-01 on the production Caddyfile |
| [`2026-10-19/upload-safety-1/`](2026-10-19/upload-safety-1/) | Uploads are inert: the data path, the sandbox probes, the mounts, the kernel settings, the limits and the provisioning runs, before and after |
| [`2026-10-20/perf-1/`](2026-10-20/perf-1/) | Hashed, precompressed assets: every page's bytes at a first visit, a repeat visit and after a release, before and after; verify-deploy and D-01 |
| [`2026-10-20/security-audit-1/`](2026-10-20/security-audit-1/) | Security audit 1: the findings, the coverage ledger, the check behind each fix, and the suites |
| [`2026-10-20/upgrade-0.47.0/`](2026-10-20/upgrade-0.47.0/) | The 0.47.0 outage and the walletd upgrade drill: the same balances, checkpoints and notarizations committing again, E-13, E-25 and E-29 passing |

Elsewhere: [`../../deploy/evidence/`](../../deploy/evidence/) (the deploy lane's first, fix and integration passes,
cited by `deploy/ACCEPTANCE.md`) and [`../../web/app/tests/evidence/`](../../web/app/tests/evidence/) (the app
library's live gate checks on Esmeralda, cited by `web/app/ACCEPTANCE-core.md`).

## What was pruned

On 2026-10-20 the raw evidence of the passes that later passes replaced went: the 2026-10-11 fix passes and
screenshots, the 2026-10-12 and 2026-10-13 lanes, 2026-10-14/m1, the 2026-10-17 home v2 and site v4, every
2026-10-18 design lane, and the review screenshots of the same designs. The reviews keep the results those files
recorded and mark each pruned path. Commit `8bcd889` still holds every pruned file:
<https://github.com/c7b/hidebox/tree/8bcd889/docs>.
