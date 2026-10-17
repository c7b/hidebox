<!-- SPDX-License-Identifier: MIT -->
# The tenth pass: home v2 at /v2 (2026-10-17 UTC)

On `main` from `da8f943`: `8fa0925` (the page, its loops, the pipeline, the tests, the review). What and why:
`docs/review/home-v2.md`.

Live: `8fa092522902ceaa22cc26c068f233392f05a3d8`, release `8fa09252…-cd224129f` (177 files), at
<https://srv2052606.hstgr.cloud/v2>. Its manifest `74d9d0bc69bc…` is notarized through SealLog in tx
`a7a1e1a35bb206a88ceda904d63820ff5f6d97bd9ae61009b77a028368e09f5a`. The tag `spooky-secrets-2026-10` was not moved: it
stays at `0e05f27`, and the home it describes is served byte for byte as it was.

| What | Where |
|---|---|
| Suites (ultron, as build, before the release) | lint PASS, check-copy PASS, server 331 tests OK (5 skipped), deploy 81 OK, app core ALL PASS (9 steps), UI 723/723, site 37/37 (35 before: V-01's two checks are new). The deploy gate ran the server (328, 6 skipped) and deploy tests, lint and copy again (`deploy/deploy-8fa0925.log`) |
| Release | `deploy/deploy-8fa0925.log`: the gate, the build (177 files, 15 of them new), the Caddyfile validated and reloaded, smoke PASS, notarized |
| verify-deploy | `deploy/verify-8fa0925.log`: 0 differences across 177 files against the release commit, SealLog's template on chain byte for byte. `deploy/verify-tag.log`, against the unmoved tag: 18 differences, all expected: the commit, the 15 new files (`v2/index.html`, `site/css/v2.css`, `site/js/clips.js`, 12 under `site/media/motion/`), and `made/index.html` and `llms-full.txt`, whose only changed lines are the commit /made tells visitors to verify against (`checks/live-checks.log` has the diff's summary) |
| D-01 | `deploy/d01-8fa0925.log`: test_headers PASS, with `/v2` and `/v2/` under the app policy and `X-Robots-Tag: noindex`, and the loops as `video/webm` and `video/mp4` in byte ranges, kept a day. Before the release the same test ran on the server's throwaway stack (`--local ultron`): PASS |
| Live checks | `checks/live-checks.log`: `/v2` 200 with noindex (meta and header) and no JSON-LD; no link to `/v2` from `/`, `/how`, `/made`, `/judges`, `/fine-print`, `sitemap.xml`, `robots.txt`, `llms.txt`, `llms-full.txt`; the sitemap's five pages; a 206 for a byte range; the home's SHA-256 equal to the tag's build |
| Live probe | `probe-live.json` (`shots_v2.py --origin https://srv2052606.hstgr.cloud`, headless Chromium on ultron, the browser cache off): which media each visitor asked for at load and after scrolling, and the bytes; no loop played off screen; no console error. `checks/cache-probe.json`: the same scroll with the cache on (the closing reuses the hero's loop) |
| Screenshots | `v2-1440-{dark,light}.webp` (first screen), `-full.webp`, `-{hero,different,who,tari,closing}.webp`; `v2-390-{dark,light}.webp` and `-full-1`, `-full-2` (a phone's page is taller than one capture); `v2-390-iphone-{dark,light}.webp` (Safari's MP4 on its stage); `v2-1440-reduced.webp` (the poster, no switch); `v2-hero-frame-1.png` and `-2.png` (the hero's loop at 1.28 s and 2.52 s: it plays) and `v2-1440-dark-midloop.webp`. All from production |
| Not run | No E2E batch and no film this pass: nothing they cover changed (the app, the API and the home are as released at `0e05f27`) |
