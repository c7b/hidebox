<!-- SPDX-License-Identifier: MIT -->
# The eighth pass: site v3, the owner's six changes (2026-10-17 UTC)

`design/site-v3` (from `main` at `ff9597e`, with `main`'s `6bca9e4` merged in before the release): Open your
drive as the one action, always on in the header; Tari's lime `#BCFE00` as the action colour; scroll motion
(`web/site/js/motion.js`) and the hero picture's decode; the pixel field behind the home's closing
(`web/site/js/pixel.js`); A-06h over both modules. What and why: `docs/review/site-v3.md` (with the
screenshots in `docs/review/site-v3/`) and `research/17-brand.md` v2 (jarvis side).

Live and tagged: `17f6c5bf4fb53c14b3a62566b2ba7a354f43b051`, release `17f6c5bf…-c6017e701`. Its manifest
`ead96304…` is notarized through SealLog in tx `57f30e19…8d1d`.

| What | Where |
|---|---|
| Suites (ultron, as build, from the branch) | `suites/run1-*`: lint PASS, check-copy PASS, app core 9/9 (ALL PASS), UI 691/691, site 35/35. `suites/run2-site.log`: site 35/35 again on the released tree (after the closing's padding change and the merge of `main`). The deploy gate ran the server and deploy unit tests, lint and copy again (`deploy/deploy-17f6c5b.log`) |
| Budgets | A-06 on a phone 25,001 / 40,536 B (limit 40,960); on a computer 43,503 B (limit 43,520); A-06d 113,793 B (limit 131,072): unchanged, no `/app/` file changed. A-06h: field.js 3,463 B (6,144), motion.js 3,149 B (4,096), pixel.js 3,640 B (8,192); home.css 4,684 B, +2,914 of the 3,072 B growth row (not raised). M-01: 57.9 KB of HTML, CSS and JS (limit 60 KB) |
| Release | `deploy/deploy-0-refused.log` (the evidence folder was untracked: deploy.sh refuses a dirty tree), then `deploy/deploy-17f6c5b.log`: smoke PASS, notarized |
| verify-deploy | `deploy/verify-17f6c5b.log` and `deploy/verify-tag.log`: 0 differences across 161 files; SealLog's template on chain matches byte for byte |
| D-01 | `deploy/d01-17f6c5b.log`: test_headers PASS |
| Site v3 on production | `checks/live_probe.py` → `checks/live-probe.log`: 25/25 (the header's Open your drive at the top and the end of `/`, `/how`, `/judges`; motion.js and pixel.js after the load event; the decode behind an aria-hidden layer with the real words kept, the picture's DOM unchanged after it; no element still hidden after scrolling through; the pixel field live, then paused off screen; no CSP or Trusted Types violation; reduced motion loads neither module and shows every word; without JavaScript every word shows) |
| E2E on production | `e2e/batch.log`: the non-chain batch 13/13 (E-01, E-02, E-04, E-06, E-07, E-15 to E-21, E-03). No E-J ran; no judge pass was used |
| Purge | `e2e/purge.txt`: 3 items and 1 drop taken down by id, from a read-only diff against a snapshot taken before the release (`e2e/dbsnap.py`, as mutis, mode=ro). `e2e/survivors.txt`: the security drop `/d/3w7m8k2v5t` active, the 48 ready canary items kept, the 48 judge passes and the owner's and robot's keys untouched, no older item changed state |
| Tag | `checks/tag.txt`: annotated, moved from `61e39c8` (the judge race) to `17f6c5b`, pushed with main |
| Status | `checks/status.json`: overall green, no reasons |
