<!-- SPDX-License-Identifier: MIT -->
# The eleventh pass: home v3 at /v3 (2026-10-18 UTC)

On `main`: `3e3e9bc` (the page, its stills, the mark, the pipeline, the tests, the review), then `6c25119` (the share
window of `481e626`, from another session, brought to `/v3`). What and why: `docs/review/home-v3.md`.

Live at <https://srv2052606.hstgr.cloud/v3> since release `6c640f5` (00:39 UTC), served by `b749cdd` (00:49 UTC) when
the checks below ran; both were deployed from `main` by another session, as the coordinator arranged. The tag
`spooky-secrets-2026-10` was not moved: it stays at `0e05f27`.

| What | Where |
|---|---|
| Suites (the server, as build, on `6c25119`'s tree `dd0acca`) | `suites/`: lint PASS, check-copy PASS, server 331 OK (5 skipped), deploy 83 OK, app core ALL PASS (9 steps), site 39/39 (V-02's two checks new), UI 731/731 |
| verify-deploy | `deploy/verify-6c640f5.log` and `deploy/verify-b749cdd.log`: 0 differences across 206 files each, SealLog's template on chain byte for byte. `deploy/verify-tag.log`, against the unmoved tag: 66 differences, the commits since it |
| D-01 | `deploy/d01-6c640f5.log`, `deploy/d01-b749cdd.log`: test_headers PASS, with `/v3` and `/v3/` under the app policy and `X-Robots-Tag: noindex`, and v3's AVIF, WebP and SVG with their types, in byte ranges, kept a day |
| Live checks | `checks/live-checks.log`: `/v3` 200 with noindex (meta and header), no JSON-LD, no video, five pictures, v3's favicons; no link to `/v3` from any page, the sitemap, robots or llms files; a 206 for a byte range; the production favicon unchanged |
| Live probe | `probe-live.json` (`shots_v3.py --origin https://srv2052606.hstgr.cloud --only probe`, a fresh browser per case): at load 114,164 B on a computer and 108,061 B on a phone (the hero's AVIF and the mark), after a full scroll 135,202 B and 129,099 B, the hero's file once; one run met a 502 from the API while `b749cdd` was being deployed |
| Screenshots | `v3-{1440,390}-{dark,light}.webp` (first screen), `-full.webp` (`-full-1`, `-full-2` on a phone), `-{hero,different,who,tari,closing}.webp`, `-mark.png` (the header's tile), `v3-1440-reduced.webp`. From production at `6c640f5` |
| The mark's sources | `logo/`: the four `final-a-open-*` SVGs as generated (`#C9EB00` lime and black on white), kept for provenance; the served mark is `web/site/media/v3/hidebox-mark.svg` (`#BCFE00`) |
| Not run | No E2E batch and no film: the app, the API and the home are other sessions' this pass |
