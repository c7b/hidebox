<!-- SPDX-License-Identifier: MIT -->
# Drive v3: the drive in the home's v3 look (2026-10-18 UTC)

What and why: [`docs/review/drive-v3.md`](../../../review/drive-v3.md).

| What | Where |
|---|---|
| Screenshots, after | `after/<state>-<width>-<theme>.webp`: `start`, `open` (Open my drive), `empty`, `files`, `picked` (1440) or `menu` (390, a phone has no picking column), `share-who`, `share-opens`, `share-result`, `key` (Save my key), `link` (a stranger on a Once link), `pay` and `pay-open` (the buyer page before and after paying); 1440 and 390, light and dark |
| Screenshots, before | `before/`, the same states on `8351f18` (the padlock, shadcn's neutral dark) |
| The script | `shots_drive3.py` (headless Chromium on the server as `build`, the UI suite's own test harness: build, dev server with folders and pay to open, the fake chain for the pay link) |
| Suites | `suites/` (the server, as build, on the promotion's `b203c86` with this pass's code on top; `d0f08ed` added only documents): lint PASS, check-copy PASS, core ALL PASS (9 steps), server 331 OK (5 skipped), deploy 83 OK, site 42/42, UI 751/751 (the `drive-v3` scenario's 19 checks new); A-06d 118,441 B in 36 files there, 119,760 B in 37 in the run before it (`entries.js` sometimes arrives before the table renders), of 131,072 |
| Live probe | `live_probe.py` (production /drive with no drive: its icons, the app's tokens and stylesheet, the start screen's picture, one lime, both themes, 1440 and 390) |
| Release | `deploy/`: `deploy-6e20248.log` (the gate, the build of 203 files, smoke PASS, notarized), `verify-6e20248.log` (0 differences across 203 files), `d01-6e20248.log` (PASS), `live-probe-6e20248.log` (23/23) |
| E2E on production | `e2e/`: the app batch (E-01, E-08, E-18, E-19, E-20, E-26, E-27, E-28, E-03): 7 PASS, E-28 PASS on rerun, E-19 FAIL on the Android profile at the home's Or write one (not this pass's files); the two failure screenshots |
