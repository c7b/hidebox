<!-- SPDX-License-Identifier: MIT -->
# The twelfth pass: the v3 design becomes the home (2026-10-18 UTC)

Prepared on the branch `site/promote-v3` (on `main` at `312eea1`); **deployed by the coordinator**, not by this
session: no `deploy.sh`, no production file, no tag. What and why: `docs/review/promote-v3.md`.

| What | Where |
|---|---|
| Suites (the server, as build, on the branch's final tree) | `suites/`: lint PASS, check-copy PASS, server 331 OK (5 skipped), deploy 84 OK, app core ALL PASS (9 steps), site 42/42, UI 732/732 (`done.txt`: all exit 0). `first-run-*.log`: an earlier full run of the same code before the docs and the `favicon.ico` commit, with one V-01 timing failure on `/v2` (site 41/42, then 42/42 in `first-run-site2.log`) and one UI timing failure (`drive-delete-account`, 724/725) while another session's runs shared the box; neither recurred |
| The old home's numbers | measured by `main`'s own checks at `312eea1` on the server (M-01 58.9 KB, words 66/650 and 70/666, `field.js` 3,752 B, `pixel.js` 3,864 B, `home.css` 4,987 B; `/v3` 282,692 / 275,920 B at load): the review's budget table |
| Screenshots | `shots_promote.py`: `home-{1440,390}-{dark,light}.webp` (first screen), `-full*.webp` (the whole page; 390's in two parts), `-mark.png` (the header's tile); `v2-{1440,390}.webp` and `-full*.webp` (reduced motion); `v3-redirect-1440.webp` |
| `/v3` redirecting | `redirect.json`: `/v3` and `/v3/` answer 301, `Location: /`; the browser lands on `/` |
| `/v2` unchanged | `v2-compare.json` (the one-mark commit's tree against the branch's, reduced motion: 1440 equal byte for byte; 390 equal but for one band) and `v2-tiles.txt` with `v2_tiles.py` (that band differs between two runs of the same tree too: noise) |
| Share cards and icons | rendered by `web/site/tools/render-images.py` on the server as build into `web/site/static/` (committed): `og.png` 145,788 B, `og-s.png` 50,018 B, `icon-512.png` 5,761 B, `icon-192.png` 2,184 B, `apple-touch-icon.png` 2,215 B, `favicon-32.png` 717 B, `favicon.ico` 2,206 B |
| Not run here | the deploy, verify-deploy, D-01 against production, the E2E batch, the film and the tag: the coordinator's, after the deploy (the commands are in the fix log's twelfth pass) |
