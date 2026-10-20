<!-- SPDX-License-Identifier: MIT -->
# Preview 1: file previews (2026-10-19 UTC)

What and why: [`docs/review/preview-1.md`](../../../review/preview-1.md).

| What | Where |
|---|---|
| Screenshots | `shots/<where>-<width>-<what>[-dark].webp`, written by the UI suite's own flows (`web/app/ui/tests/flows_preview.py`) with `MUTIS_PREVIEW_SHOTS=<dir>` on the final tree, headless Chromium on the server as `build`. The drive at 1440: a PNG named `.svg` (`picture`), an SVG named `.png` drawn into a canvas (`svg`), Markdown with scripts as text (`text`), the 300 KB file's end with the cap's note (`text-cap`), HTML named `.txt` (`none`); at 390: `picture`, `text`, `none`. A folder link's visit at 1440 (`folder-1440-svg`, the pager on the stage's sides) and a paid link at 1440 and 390 (`pay-*-svg`, the file shown as soon as Open it decrypts it). Light and dark (`-dark`) for each but `drive-390-none` |
| Suites, full run | `suites/full/`: lint, check-copy, build, the app core (`run_all.py`, 9 steps) and the whole UI suite (940/940) on `da05e87` (its id before the branch was rebased) |
| Suites, final tree | `suites/final/`: lint, check-copy, the core suite in Chromium (150/150) and without WebAssembly (87/87), the mutants (`mutants.txt`, 3 of 3 fail the suite), and the UI scenarios the review's fixes touch (243/243) on `e4dd45d` (before the rebase) |
| Suites, rebased | `suites/rebased/`: after the rebase onto `main`'s new pay page, the core suite in Chromium (150/150) and the UI scenarios that touch the pay page, the folder viewer and the budgets (172/172); `preview-drive` before the swipe fix (`*-before-swipe-fix.log`: the phone's tap on Next after a swipe lost) and twice after it (75/75 each) |
| Budgets | `budgets.txt`: A-06d on `main` and on the branch (twice), the changed files' compressed sizes, the files that load on the first open, A-06 |
| End to end on production | `e2e/`: `run.log` and `report.json` of E-29 (pay to open a folder) on `https://hidebox.app` with this branch's front end served by `tests/e2e/run.py --candidate` (the link's id replaced by `<link>`); `E-29-01-1-teaser.png` (the phone before paying) and `E-29-03-3-open.png` (after the preview closed with Esc: focus is back on `minutes.txt`) |

How the suites ran: a copy of the working tree in the build user's work directory, then, as `build`,
`tools/lint.py`, `tools/check-copy.py`, `tools/build.py --source <sha> <version> <time> --origin https://hidebox.app`,
`web/app/tests/run_all.py`, `web/app/ui/tests/run.py`; the mutants copy the tree, change one line of
`web/app/ui/lightbox.js` each and run `web/app/tests/headless.py`. E-29 ran from the workstation:
`tests/e2e/run.py --origin https://hidebox.app --only E-29 --candidate <a local build of the branch>`.
