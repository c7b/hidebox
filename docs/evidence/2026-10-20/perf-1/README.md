<!-- SPDX-License-Identifier: MIT -->
# Performance and caching (2026-10-20)

Prepared on the branch `site/perf-1`; **not deployed** by this session. What and why: `docs/review/perf-1.md`.

| What | Where |
|---|---|
| Every page, first visit, repeat visit and after a release | `probe-before.json` (main before the pass, `4d38049`, built by its own `tools/build.py` and served by its own Caddyfile) and `probe-after.json` (the branch), from `tests/e2e/perf_probe.py` on the server's throwaway stack in headless Chromium; `probe-before.txt` and `probe-after.txt` are their one-line summaries, the after run with `--check` |
| The tables in the review | `tables.py` makes `tables.md` from the two JSON files and a build of each tree |
| The PNGs' pixels | `images/png-pixels.txt`: ffmpeg on the server decodes every PNG (and the three in `favicon.ico`) before and after `png_shrink.py` to the same RGBA |
| D-01 on the production Caddyfile | `test_headers-local.txt` (`tests/e2e/test_headers.py --local`): the hashed names a year and immutable, the folder's policy, made-up hashed names a 404 `no-store`, br, gzip or the file as the browser takes it |
| verify-deploy | `verify-deploy-local.txt`: the throwaway stack serving a clean build of the branch, compared with a fresh build of the same commit, every text file also as gzip and br, decoded: 0 differences |
| SEO on a build | `check-seo-dist.txt` (`tools/check-seo.py --dist`, a build for `https://hidebox.app`) |
| Mutants | `mutants.txt`: the two app modules put back as they were, building asset addresses at run time; the site suite's fingerprint check names both |
| Suites | `suites/final/`: on the server as `build`, on the branch's last code commit (`done.txt`: the exit codes); `suites/before/`: the site suite and the UI budgets on `4d38049`; `suites/first-run-ui-budget.txt`: the first full UI run on the branch, when A-06 still counted gzip -9; `suites/ui-races.txt`: the two scenarios that pressed a moving target, with their traces and runs |
