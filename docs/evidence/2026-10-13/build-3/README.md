<!-- SPDX-License-Identifier: MIT -->
# The ghost, stage 3 (Phase 6B steps 8 to 10), 2026-10-13

The receipts of the third build stage of the redesign (14-ghost-design §17 steps 8 to 10: the viewer,
the gone page and the locker on the ghost with the app's strings rewritten to the copy deck; the
judges' demo secret, `judge_demo_gone` and its release step; the public name in the documents). Times in
UTC. Nothing here is a secret: no judge pass, no production link with its key; the links in
`suites/ui.log` belong to a throwaway dev server. The judges' demo secret's id is public by design
(`/api/v1/config` serves it).

| Folder | What |
|---|---|
| `suites/`, `suites-fb8f9ee/` | On the server as `build` from a `git archive`; `suites-fb8f9ee/` is the final code of the stage (the same results; `fb8f9ee` only rounds the viewer's panels and lets the drop's name field wrap). At `f7016c4`: UI PASS 381/381 (with the new flow `ghost-screens`, whose screenshots are in `docs/review/ghost/`), server 204 tests OK (4 opt-in skips), site 29 of 29, core ALL PASS in 9 steps, deploy 77 tests OK (the new `DemoGone` class), lint and check-copy PASS. The run at `00d270e` before it had one UI failure (the wrong-word message no longer said how many tries were *left*; fixed in `f7016c4`). |
| `deploy/` | `deploy-612db64.txt`: `deploy.sh HEAD` → release `612db64ffcab6f30517f21999804ec19c8d69f98-c9afcf945`, smoke test PASS; the manifest's notarization did not commit (tx `d32cd042…`): SealLog checkpoints and courier jobs had been failing on the testnet since about 10:50 (the last committed checkpoint is #140 at 10:28). `verify-deploy-612db64.txt`: 0 differences across 126 files, the SealLog template byte for byte. `d01-test_headers-612db64.txt`: D-01 PASS. `demo-gone-burn.txt`: `deploy/scripts/demo-gone.py burn` on production (12:42): the judges' demo secret `tXoueLYCUlw-ZCgOcRMWAQ`, served as `judge_demo_gone`. |
| `deploy/` (2) | `deploy-27e2946.txt`: the stage's final release `27e29462b1a6922aa3fcc4fa629793fdf4f07f87-ca6894dee` (smoke PASS; notarization again not committed, tx `f9f992aa…`); `verify-deploy-27e2946.txt`: 0 differences across 126 files; `d01-test_headers-27e2946.txt`: D-01 PASS. |
| `e2e/` | `batch1.log`: `run.py --final` with the 17 scenarios that make no chain transaction (E-01, E-02, E-03, E-04, E-05, E-06, E-07, E-08, E-15, E-16, E-17, E-18, E-19, E-20, E-21, E-22, E-24) against production on `612db64`, with `e2e_expiry_s = 60` set for the batch and removed right after (the API restarted, `/api/v1/config` checked): 17 of 17 PASS. `purge1.txt`: its 14 items and 2 drops taken down by id (E-17 had taken down its own drop), from a read-only diff against a snapshot taken before the deploy; the demo secret is not a test item and stays; the 6 empty test lockers have no admin removal and stay. `batch2.log` and `purge2.txt`: the same 17 scenarios again on the final release `27e2946` (the preset set and removed the same way): 17 of 17 PASS; 14 items and 2 drops taken down by id. |
| `film/` | `tools/film.py --demo` once on production after the deploy (the pipeline on the live pages, no chain): a 13-second film, the night ground, Noto Sans captions from the deck, `poster-demo.png`. |

A-06 at `f7016c4` (gzip -9 of every `/app/` file the home page requested): **40,309 B on a phone**
after a text drop (≤ 40,960, no code encoder), **43,276 B on a computer** with the encoder (≤
`QR_CEILING` = 43,520 B), 45,347 B after a photo on a phone (≤ 48 KB). Step 8 cost the widget nothing:
the widget's first dictionary got shorter, and its stylesheet now reads the bye tokens.

Readability (Flesch-Kincaid, `research/design/copy/fk.py`, every string of `web/app/i18n/en.json` by
group): every group at grade 4 or lower except `claim` (6.1), which holds the claim registry's
sentences verbatim (C5, C8, C9, C11, C15). The judge script on `/judges`: 1.59 (the critic's
`fk_crit.py`: 1.18). No digits outside `{variables}`.
