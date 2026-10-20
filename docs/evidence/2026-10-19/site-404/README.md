<!-- SPDX-License-Identifier: MIT -->
# The 404 page (2026-10-19)

Prepared on the branch `site/404`; **not deployed** by this session. What and why: `docs/review/site-404.md`.

| What | Where |
|---|---|
| Screenshots | `shots_404.py` (headless Chromium as `build` on the server, the tree served by `web/site/tests/serve.py`): `404-{1440,390}-{dark,light}.webp`, the first screen in the system's theme; `404-1440-dark-selected.webp` and `404-390-light-selected.webp`, the page selected as Ctrl+A does, which shows the hidden line |
| What the browser saw | `page.json`: per capture, the status (404), the art's file and box, the bytes at load, every request and the console (the 404 of the page itself, then the ghost and its credit as `log` lines) |
| The art | `encode_404.sh`: the ffmpeg commands that made `web/site/media/404/` from the owner's PNG (not committed) |
| Budget | `budget-404.json`: the page at load, uncached, before (main after the brand kit) and after, at 1440 and 390 |
| Mutants | `mutants.txt`: four broken copies of the page, and what the static and browser checks said |
| D-01 and SEO on the production Caddyfile | `test_headers-local.txt` (`tests/e2e/test_headers.py --local`: an unknown page is a 404 with the site policy and `no-store`; the art is `image/avif`, in byte ranges, kept a day) and `check-seo-local.txt` (`tools/check-seo.py --local`: "an unknown page answers 404, noindex") |
| Suites | `suites/final/`: lint PASS, check-copy PASS, the build OK, deploy tests 89 OK, site 44/44, on the server as `build`, on the branch's last code commit (`done.txt`: all exit 0); `suites/before/site.log`: `main` before this pass, 42/42; `suites/first-run-site.log`: the branch's first full run, 43/44 (`/made`'s contents under a load near 8; that check passed alone on `main` and on the branch, and in the final run) |

The best two: `404-1440-light.webp` (the art on its ink card above the words) and `404-1440-dark-selected.webp` (the
words selected and the hidden line showing under Go home).
