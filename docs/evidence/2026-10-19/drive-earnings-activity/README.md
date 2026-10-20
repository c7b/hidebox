<!-- SPDX-License-Identifier: MIT -->
# Earnings, and Activity at scale (2026-10-19)

What and why: [`docs/review/drive-earnings-activity.md`](../../../review/drive-earnings-activity.md). Branch
`drive/earnings-activity`, rebased on `main` (`c842fcc`); not deployed.

| What | Where |
|---|---|
| Earnings | `shots/earnings-{1440,390}-{light,dark}.webp`: a drive with two pay links and four payments (test money with its tx, two from a wallet the drive checked, one whose payer kept the key), whole pages; `earnings-1440-empty.webp`: a drive that sells and nobody paid yet |
| Activity, the owner's upload | `shots/activity-1440-grouped.webp`: a folder of 30 files dropped in (20 in hidebox-brand, 8 in drafts, 2 in snippets), five rows; `activity-open-{1440,390}-{light,dark}.webp`: the same with "Locked and uploaded 20 files to hidebox-brand" open |
| Activity by day | `shots/activity-days-{1440,390}-{light,dark}.webp`: the same 33 events spread over 33 hours (the test moves their hours), under Today and Yesterday with each day's count, after Show more |
| Activity, payments | `shots/activity-1440-payments.webp`: the Payments chip on the Earnings drive |
| Suites | `suites/`: `ui.log` (the full app UI suite, `--shots`), `budget-before.log` and `budget-after.log` (A-06d on `main` and on this branch), `core.log`, `server.log`, `site.log`, `deploy.log`, `lint.log`, `check-copy.log`, `build.log`, `versions.txt` |

The pictures come from the UI suite's `activity-groups` and `drive-earnings` scenarios (`run.py --shots`), at 1440
and 390 px wide, light and dark, on the dev server with the pay routes faked as the suite does (`PayFake`). On a phone
the floating New button is left out of the whole-page pictures: it is fixed to the screen's corner, so a whole-page
picture would draw it in the middle of the list. Paths in the logs are `<repo>` for the copy of the branch the suites
ran on.

A-06d, `/drive` until its table renders: **125,555 B** on `main`, **126,662 B** with this branch (38 files both, of
131,072 B).
