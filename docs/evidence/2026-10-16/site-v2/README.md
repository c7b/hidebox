<!-- SPDX-License-Identifier: MIT -->
# The seventh pass: site v2, and the stop and pay feedback (2026-10-16 UTC)

`main` took `fix/share-stop-pay` (Pay from my drive shows its steps from the click; Stop sharing and Stop
selling in the row menu and the share result) and `design/site-v2` (the redesigned site: a hero over the
ripple field, the comparison table, the tTARI box, Who sees what as cards, a short /judges, /made renamed
Under the hood, the sticky header, the home in a Geist subset, A-06h, claims C50 to C56). The integration
devil then checked the merged result on the real pages and fixed five defects. Its verdicts were in
`docs/review/site-v2.md` ("Integration devil", pruned on 2026-10-20); `docs/review/fix-log.md` ("Seventh pass") keeps them.

Live and tagged: `410f21098fa34a594c2acf33594501088078f228`, release `410f2109…-c0a7e1276`. Its manifest,
`7fbb3811…9ac3`, is notarized through SealLog in tx `481f40e3…615c` (22:44 UTC).

| What | Where |
|---|---|
| Suites (the server, as build, from a tarball of the commit) | `suites/`. **Run 1** (`d3bf966`): server 330 OK (5 skipped), deploy 79 OK, lint PASS, check-copy PASS, app `run_all` 9/9, site 34/34. UI was 665/666: `nav.my_locker` was unused, removed in `7646442`. **Run 2** (`faf93da`): every suite passed, UI 666/666. **Run 3** (`32bffc5`, the link pages' button): UI 97/97 on pay-page-states, pay-drive, drive-budget, budget, share-stop and sell-stop. **Run 4** (`410f210`, the no-JS quiet zone): site 34/34. Each deploy's gate ran server (327 OK on 3.13), deploy, lint and copy again |
| Budgets | A-06 on a phone: 40,536 B (limit 40,960). On a computer: 43,503 B (limit 43,520). A-06d: 113,793 B (limit 131,072). A-06h: field.js 3,428 B (limit 6,144); home.css grew 2,235 B (limit 3,072). M-01: 53.4 KB of HTML, CSS and JS gzipped (limit 60 KB), 0 third-party requests |
| Releases | `deploy/deploy-1-32bffc5.log`, then `deploy/deploy-2-410f210.log` (the fix for no-JS contrast). `verify-*.log` and `verify-tag.log`: 0 differences across 159 files, and SealLog's template on chain matches byte for byte. `d01-*.log`: D-01 PASS (58 checks) |
| The devil | `devil/`. `devil_site.py` ran on `serve.py` before the deploy (`devil-dev-serve.log`), then on production: `devil-live-1-32bffc5.log` had 2 FAIL (no-JS contrast), and `devil-live-2-410f210.log` has 86 checks and 0 FAIL. `nojs_contrast.py` and `nojs-contrast.log` cover 8 widths in both themes: 10 FAIL before, 0 after, and 0 with JavaScript. `http-checks.txt` covers the routes, `/es/` at 404, the llms, robots and security files at 200, the 301s and the anchors. `screenshots.txt` lists the screenshots and marks the ones looked at |
| E2E on production | `e2e/batch.log`: the non-chain batch, 13/13 (E-01, E-02, E-04, E-06, E-07, E-15 to E-21, E-03). `e2e/ej-1-judge-pass.log`: E-J with its judge pass, the one judge-pass drive allowed. **It FAILED at step 5**: the Once link's "Delete it from my drive after" never reached the server, so the file stayed. `probe-ej3*.log`: two probes of that step on production, with E-J's steps and four shares, all applied. `e2e/ej-2-no-pass.log`: E-J unchanged except that `mutis-admin judge-pass new` returns nothing (`ej_nopass.py`). It PASSED both tracks: track one in 9 s, track two in 38 s (a pay link, test money, Ready to open, Received as Yours to spend, hidden amounts) |
| Tag | `checks/tag.txt`: annotated, moved from `f89963c` (sixth pass) to `410f210` and pushed with main; the live version matches |
| Purge | `e2e/purge.txt`: 15 items and 1 drop taken down by id, from a read-only diff against a snapshot taken before the runs. `e2e/survivors.txt`: the security drop `/d/3w7m8k2v5t` is active, the 47 ready canary items are kept, 42 judge passes plus E-J's new one, both held packs kept, and the owner and robot keys kept |
| Status | `checks/status.json`: overall green; the only reason is `budget.decoy.reserved.50` (a daily budget) |
