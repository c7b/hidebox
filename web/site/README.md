<!-- SPDX-License-Identifier: MIT -->
# The site of hidebox (codename mutis) and its shared design system

The site (`web/site/`) and the design system the app shares with it (`web/shared/`): the six pages of
16-drive-design §2 and §11 (the home with Make my drive beside a slice of a drive and the anonymous widget,
how it works in five stills of the real interface, how it was made, for judges, the fine print, 404), SEO
and static files, the brand tile and the partials.

No third-party code: our own ES modules and stylesheets, Geist (pinned) on the reading pages and the
system faces on the home (A-06), Python's
standard library for every tool and test, Debian's Chromium. The old Mutis Script fonts stay in
`../shared/fonts/` for one release; the build no longer copies them.

## Run the tests (one command)

```sh
python3 -I web/site/tests/run.py
```

On the server (as `build`) every check runs: 15 file checks (with `llms-full.txt`), `dates.js` under Node 20
in two time zones, and 11 browser checks in headless Chromium against `tests/serve.py`, which serves
the app's real widget from `web/app/`. Elsewhere, checks whose tool is missing print `SKIP`, never
`PASS`; `--static` runs only the file checks. "/judges quotes the app's words" compares `/judges`, in
each amount-proof mode, with `web/app/i18n/en.json`. Last run on the server: see `ACCEPTANCE.md`.

## Layout

| Path | What |
|---|---|
| `../shared/tokens.css` | 11-brand §13.2 colours verbatim, the §13.3 type scale and font faces, spacing, layout, motion |
| `../shared/base.css` | reset, page colours, focus ring, `.sr-only` `.mono` `.redact` `.container` `.skip-link`, reduced motion |
| `../shared/dates.js` | `MAINNET`, `phase()`, `isOctober31()`, `msToNextLocalMidnight()`, `applyPhase(root, now)` |
| `../shared/theme.js` | classic script in `<head>`, before the first paint: "Lights off / Lights on", and `html.motion` when scripts run and motion is allowed |
| `../shared/icons.svg` | the icon sprite of 11-brand §13.8, plus drop slot, watch and the wall's `keyhole` |
| `../shared/brand/` | `symbol.svg`, `favicon.svg`: the brand tile (ink square, Lucide lock), light and dark |
| `../shared/partials/` | `header`, `footer`, `status-line`, each also `-es` |
| `../shared/fonts/` | Mutis Script Regular and Bold, Mutis Script Code, `OFL.txt`, `NOTICE` |
| `pages/` | `index how security pricing faq judges terms privacy abuse status 404`, and `es/` |
| `js/` | `site.js` (every page: the mainnet phase, live numbers and copy variants), `stats.js` (numbers from `/config` and `/stats`), `made.js` with `canary.js` (then `reveal.js` on a click), `evidence.js` and `noise.js`; `abuse.js`, `judges.js`, `status.js` |
| `css/` | `site.css` (every page), `home.css` (`/` only, which also links the app's `widget.css`), `pages.css` (every other page), on `../shared/tokens.css` and `base.css` |
| `static/` | `robots.txt`, `llms.txt`, `llms-full.txt`, `.well-known/security.txt`, `manifest.webmanifest`, `favicon.svg`, icons, `og.png`, `og-s.png` |
| `og/` | HTML sources of the OG cards and app icons (not served) |
| `tools/` | `subset-fonts.sh`, `rename-font.py`, `render-images.py`, `llms_full.py`, `variants.py`, `cdp.py` |
| `tests/` | `run.py`, `static_checks.py`, `browser_checks.py`, `dates.test.mjs`, `serve.py`, `shots.py`, `make-canary.mjs`, `fixtures/` |
| `shots/` | curated WebP screenshots of the six pages at 1440 and 390, light and dark, made by `tests/shots.py` |

## How the pages get their numbers

No limit, price, duration or count is typed into a page (11-brand §8.3, P-20). An element
`<span data-v="anon_max_file"></span>` is filled by `js/stats.js` from `/api/v1/config` or
`/api/v1/stats`, formatted for the page's language. Every such element sits inside a block marked
`data-needs`, which stays `hidden` until all of its values arrive, so a failed request removes the
sentence instead of printing a guess. `data-when="send_mode=direct"` (also `proof`, `seallog`, `kept`,
`snapshots`, `security_drop`) marks a copy variant. The HTML ships the server's defaults visible (relay
sends, amounts read by our wallet, SealLog off, kept files on, host snapshots on); `tools/variants.py`
sets the deployment's own variants into the built pages from its `mutis.toml`, so readers without
JavaScript, crawlers and `llms-full.txt` get the true ones too, and `stats.js` switches them again
from `/config` for flags an admin changes later. The one exception is the mainnet date in the status
line, which spec §3.4.2 pins in the partial and `stats.js` then overwrites from `/config`.

## The home and how it works

`index.html` is the drive's home for strangers (16-drive-design §11): Make my drive and Open my drive
beside an inert slice of a drive, then Just share one thing (the anonymous widget that
`/app/drop-widget.js` mounts, its ids and the A-06 budget unchanged), the three ways to share and the
Tari rows. `/how` is five stills of the real interface, drawn inert from the drive's parts in
`css/how.css`, so they follow the theme; no mascot, no animation.

## Tools (run as `build` on the server)

| Command | Does |
|---|---|
| `sh web/site/tools/subset-fonts.sh` | subsets Debian's Courier Prime and Courier Prime Code, renames them Mutis Script / Mutis Script Code (OFL condition 3), writes WOFF2, `OFL.txt` and `NOTICE`; deterministic |
| `python3 -I web/site/tools/render-images.py` | renders `og/*.html` to `og.png`, `og-s.png` and the app icons; fails on a card over 150 KB or an OTS error |
| `python3 -I web/site/tools/llms_full.py` | writes `static/llms-full.txt` from `/how`, `/made` and `/fine-print` as a reader without JavaScript sees them (`--check` is part of the tests) |
| `python3 -I web/site/tools/variants.py --config mutis.toml dist` | sets a deployment's copy variants into its built pages and writes its `llms-full.txt` (for `tools/build.py`, before includes and placeholders) |
| `python3 -I web/site/tests/serve.py` | the pages with includes and placeholders expanded, production CSP headers and the API from fixtures (`--api URL` forwards to a real server, `--dist DIR` serves a built tree) |
| `python3 -I web/site/tests/shots.py` | rewrites `shots/` |
| `node web/site/tests/make-canary.mjs` | re-seals the canary fixtures with the app's real format code |

## Licence notes

Source files carry `SPDX-License-Identifier: MIT`. Data files can't (JSON, PNG, WOFF2, the llms files,
whose format starts with a heading). The fonts are under the SIL Open Font License 1.1
(`../shared/fonts/OFL.txt`); Mutis Script and Mutis Script Code are Modified Versions of Courier Prime
and Courier Prime Code by Quote-Unquote Apps, renamed as that licence requires.
