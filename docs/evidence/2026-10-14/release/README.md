<!-- SPDX-License-Identifier: MIT -->
# The release: the fifth pass, the tag `spooky-secrets-2026-10`, the film and the stranger checks (2026-10-14 UTC)

The fifth pass fixed the devil's findings on the drive (`docs/review/fix-log.md`, "Fifth pass (the drive)"), renamed
the repository to `c7b/hidebox`, and released. Live and tagged: `c73c7b415ecdc88bc848a76fc68c91528702be62`
(release `c73c7b415ecd…-cbb8c1e8a`, manifest `91bbe7e3…c56f` notarized through SealLog in tx `3ea47bc8…7e51`).

| What | Where |
|---|---|
| Suites (on ultron as build, on a tarball of HEAD) | `suites/core-1.log`: lint, check-copy, server 309 OK, site 29/29, `run_all` 9/9; the deploy tests' five failures there were fixed before the deploy (78 OK). `suites/ui-1.log`: UI 571/578, the seven fixed (`ui-2.log` 140/140); `ui-3.log` 102/102 and `ui-4.log` 186/186 after the later changes. A-06 40,442 B, A-06d 112,459 B. |
| Releases | `deploy/deploy-1.log` `e0e53a5`, `deploy-2.log` `e72853e`, `deploy-3.log` `ad319d9`, `deploy-4.log` `c73c7b4` (the tag). `verify-{1..4}.log`: 0 differences across 157 files, SealLog's template on chain byte for byte; `d01-{1..4}.log`: D-01 PASS. |
| The tag | `checks/tag.txt`: annotated, on `c73c7b4`, pushed with main; moved twice before anything referred to it (fix-log). |
| E2E on `e0e53a5` | `e2e/batch-N1.log` 15/16 (E-24 met the 5-an-hour drive limit), `batch-P1.log` E-J, E-25 PASS. |
| E2E on `e72853e` | `batch-R1.log` 15/16 (E-24 again rate-limited), `batch-Q1.log` E-J, E-25 PASS. |
| E2E on `ad319d9` | `batch-T1.log` 15/15, `batch-T2.log` E-J, E-25 PASS; `batch-R2.log` E-26, E-27, E-28, E-31, E-03 PASS; `batch-R3.log` E-24 PASS; `batch-R4.log` E-05 PASS (with `e2e_expiry_s = 60`, removed and mutis-api restarted right after). |
| E2E on `c73c7b4` (the tag) | `batch-U1.log` E-J PASS (track one 9 s, track two 37 s; the folder's menu, Activity's Opened and It left, Received's live Payments row with the folder's name, Test money, Checked and its tx); `batch-U2.log` 13/13 (E-01, 02, 04, 06, 07, 15–21, 03); `batch-Q2.log` E-09, E-29 PASS, E-30 FAIL (below); `batch-Q3.log` E-10, E-11, E-12 PASS. |
| Not run, or not green | **E-30** waited 600 s for the buyer drive's sponsor grant: it holds a judge pass, so its grant comes from the evidence slice, spent for the day (`budget.sponsor.evidence.90`); it passed in pass 2 and runs after 00:00 UTC. **E-13** needs the same slice. **E-14** is staging-only. The drive scenarios E-08, E-22, E-24, E-26–E-28, E-31 and E-05 ran on `ad319d9`; `c73c7b4` changes only `/judges`' copy and docs. |
| Film | `checks/film-render.log`, `checks/film-ffprobe.txt`: `tools/film.py` against production (`ad319d9`): 1920×1080, H.264, 30 fps, 87.97 s, 2,055,542 bytes, one stream (no audio). Six frames and the Payments frame were looked at. The film itself is in the owner's contest kit, not in the repository. |
| Stranger checks | `checks/clone.txt`: an unauthenticated clean clone of `https://github.com/c7b/hidebox`: the tag, `verify-deploy` against production 0 differences, the server suite 309 OK. `checks/crawl.txt`: 13 pages and 67 links fetched anonymously, 0 failures; `/locker`, `/inbox`, `/upgrade`, `/terms`, `/privacy`, `/security`, `/abuse` answer 301 then 200; `/es/` and `/es/how` 404; the repository 200 at its new URL and the old URL 301 to it; every GitHub link on the site uses the new URL. |
| Purge | `e2e/purge.txt`: 29 test items and 7 drops taken down by id (a read-only diff against a snapshot taken before the first batch; 5 canary items kept). `e2e/survivors.txt`: the security drop `/d/3w7m8k2v5t` active, 0 active paid links (13 released claims), 41 judge passes (none removed), the canary items; `/status.json` amber only for budgets (`budget.sponsor.evidence.90`, `budget.decoy.reserved.50`). The owner's and the robot's drives existed before the snapshot and were not touched. |
| Config | `/etc/mutis/mutis.toml`: `memo_origins` without `https://mutis.sh`, `repo_url` → `https://github.com/c7b/hidebox` (copy `/var/backups/mutis/mutis.toml.20261014T110033Z.before-fifth-pass`); `e2e_expiry_s` only for E-05 (copy `…before-e05`). No limit, budget or database row was changed by hand. |
