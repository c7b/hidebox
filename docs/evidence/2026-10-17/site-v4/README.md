<!-- SPDX-License-Identifier: MIT -->
# The ninth pass: site v4, the owner's four changes (2026-10-17 UTC)

On `main` from `224cb1b`: the drive's one next step in Tari's lime (`6603383`); the home's headline "Your private
cloud storage. Privacy isn't an option. It's the default.", the comparison beside one popular cloud drive, and one
sentence a line everywhere (`4303362`); the docs and the screenshots (`0e05f27`). What and why:
`docs/review/site-v4.md`; `research/17-brand.md` v3 (outside this repository) and DESIGN.md.

Live and tagged: `0e05f27d01da2e9b9f56bd78e5b40bfb6f8fa1b5`, release `0e05f27d…-c41ca02e6`. Its manifest
`a8f29841…` is notarized through SealLog in tx `072495e2f4d143feb6a2442a8d092dd12c1a1028f3a5aa4af59dc2a64325c5df`.

| What | Where |
|---|---|
| Suites (the server, as build) | `suites/run1-*`: lint PASS, check-copy PASS, core ALL PASS (9 steps), UI 720/720, site 34/35 (M-05: the footer's two-sentence trademark line, now read without the breaks). `suites/run2-*` on the released tree (after that fix and the review's): lint PASS, check-copy PASS, core 9/9, UI 723/723, site 35/35. The deploy gate ran the server (328, 6 skipped) and deploy unit tests, lint and copy again (`deploy/deploy-0e05f27.log`) |
| Budgets | A-06 on a phone 25,001 / 40,536 B (limit 40,960), on a computer 43,503 B (limit 43,520): unchanged. A-06d 115,586 B (limit 131,072; was 113,793). A-06h: home.css 4,733 B, +2,963 of the 3,072 B growth row (not raised); field.js, motion.js, pixel.js unchanged. M-01: 57.9 KB of HTML, CSS and JS on / (limit 60 KB; +40 B). Home words 644 at 390, 660 at 1440 (fold 66 / 70) |
| Screenshots | `site/` (every page at 1280 and 390, before and after, the home's hero, comparison and closing, the sentence audits) and `app/before`, `app/after` (the drive's states), taken by `shots_v4.py` and the UI flows (`--shots`) |
| Sentence audit | `site/audit-before.json`, `site/audit-after.json`: 436 of 472 blocks with a sentence not on its own line before, 2 of 470 after (the status pill, kept one line) |
| Release | `deploy/deploy-0e05f27.log`: the gate, the build (162 files), smoke PASS, notarized |
| verify-deploy | `deploy/verify-0e05f27.log`: 0 differences across 162 files against the tag; SealLog's template on chain matches byte for byte |
| D-01 | `deploy/d01-0e05f27.log`: test_headers PASS |
| Site v4 on production | `checks/live_probe.py` → `checks/live-probe.log`: 18/18 (the headline and its breaks, the comparison as a table at 1280 and as cards at 390, the intro not repeating the hero, every sentence on its own line on the home, the meta, Open Graph and JSON-LD, the new share card, /drive's one lime Make my drive, no CSP or Trusted Types violation) |
| E2E on production | `e2e/batch.log`: the non-chain batch 13/13 (E-01, E-02, E-04, E-06, E-07, E-15 to E-21, E-03). No E-J ran; no judge pass from `keys/` was used |
| Film | rendered again on the release (`tools/film.py`), 87.97 s, 1920×1080, 2,125,651 bytes (`film/ffprobe.txt`); copied to the contest kit as `film.mp4`, the v3 one kept as `film-17f6c5b.mp4` |
| Tag | `checks/tag.txt`: annotated, moved from `17f6c5b` (site v3) to `0e05f27`, pushed with main |
| Status | `checks/status.json`: overall green; one reason, `budget.sponsor.evidence.50` (the film's test money) |
| Not done | No purge by id this pass: the batch's test drops and the film's drive stay until their rules end them (the film took its own pay link down) |
