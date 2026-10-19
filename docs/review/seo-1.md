<!-- SPDX-License-Identifier: MIT -->
# SEO pass 1: search results and link previews, with nothing watching (2026-10-19)

The owner wants hidebox to rank, and to look right wherever its links are pasted: social networks, Telegram, WhatsApp,
Slack, Discord, iMessage and other products. The rule for this pass: no analytics, no Google or Meta consoles or
connectors, no tracking, no third-party script, no new external origin in any policy. Everything here is markup in our
own pages, headers from our own Caddy, and a checker that reads the site the way a crawler does.
Evidence: [`docs/evidence/2026-10-19/seo-1/`](../evidence/2026-10-19/seo-1/).

On the branch `seo/pass-1`, pushed to `main`. **No deploy**: the integrator deploys. No icon file, `og.png` or
`og-s.png` byte, `render-images.py` or `docs/media/` file changed (the brand pass owns them).

## Before

`tools/check-seo.py` (new, below) against the live site before this pass: 3 checks passed, 10 failed
(`check-seo-live-before.txt`).

- Titles put the name first or in the middle ("hidebox: your private drive", "How hidebox works", "hidebox for
  judges"); four of the five said little more than the name.
- No page had a Twitter title, description or image (X, Slack and Discord fall back to Open Graph, but not every
  product does), nor `og:image:secure_url` or `og:image:type`.
- No robots meta: Google shows a large image preview (and Discover a large card) only where a page allows it with
  `max-image-preview:large`.
- JSON-LD only on the home, and it said "Dead-drop links" (a retired noun) and "every exit is written to a public log",
  which the claim registry doesn't allow (C42: only a file that leaves gets a record). `tools/check-copy.py` never read
  JSON-LD or `twitter:*`, so nothing caught it.
- The home's five stills had empty alt text: an image search saw five nameless pictures.
- `og.png`, the icons, `robots.txt` and `sitemap.xml` were served `no-cache`, and the cards and icons with
  `Cross-Origin-Resource-Policy: same-origin`, which stops any product that draws a preview from the page in a browser
  (a forum's onebox, a web chat client) from showing our image.
- `/app/drive.html`, `/app/view.html`, `/app/app.html` and every API answer were served without `X-Robots-Tag` (the
  three pages had a robots meta; the API had nothing).
- The sitemap had no `lastmod`; the manifest had no `id` and still described the drive with the old tagline.

## What changed

### Every page's head (`web/site/pages/*.html`)

| Tag | Now |
|---|---|
| `<title>` | what the page is for, then ` · hidebox`; at most 60 characters; unique |
| `description` | what the page is for, at most 155 characters; unique; on the home it complements the title instead of repeating it (a search result shows both, and the Say It Once rule holds there too) |
| `robots` | `index, follow, max-image-preview:large` on the five public pages (a large image in Google's results and Discover); the 404 page stays `noindex` |
| `canonical` | `{{ORIGIN}}/path`, which the build fills with `https://hidebox.app`; `og:url` repeats it |
| Open Graph | `og:type`, `og:site_name`, `og:title` (the title without the name, which `og:site_name` carries), `og:description`, `og:url`, `og:image` (absolute), `og:image:secure_url`, `og:image:type`, `og:image:width` 1200, `og:image:height` 630, `og:image:alt` |
| Twitter | `twitter:card` `summary_large_image`, and `twitter:title`, `twitter:description`, `twitter:image`, `twitter:image:alt` equal to their Open Graph twins |
| Icons and app | theme colours for light and dark (as before), `apple-mobile-web-app-title`, and every icon on every page: `/favicon.ico` (192 px, the one search engines and unfurlers ask for by name), `/favicon-32.png`, `/favicon.svg`, `/apple-touch-icon.png`, the manifest |
| JSON-LD | the home: `WebSite` and `SoftwareApplication` (below); every other public page: a `BreadcrumbList`, Home then the page |

The app's own pages carry the same card without an address in it (no `og:url`, no canonical: one page serves every
link): `view.html` (served for `/s/`, `/t` and `/p/`) keeps `og-s.png`, "Someone shared something with you.";
`app.html` (`/d/`, `/send`, `/watch`, `/verify`) and `drive.html` (`/drive`, which had no card at all) carry the
site's. All three stay `noindex, nofollow`. A preview never uses up a link: unfurlers fetch the page without running
JavaScript, the key is after the `#` and never reaches the server, and a file opens only on Open it.

### The titles and descriptions

| Page | Title before | Title now (characters) | Description now (characters) |
|---|---|---|---|
| `/` | hidebox: your private drive | Your private cloud storage · hidebox (36) | Files lock in your browser first. You pick how each file opens: once, with a word, or for Tari. No email, no password. Your key is the account. (143) |
| `/how` | How hidebox works | How it works: a key, a lock and a link · hidebox (48) | Five steps, each with a picture of the drive: open your drive, drop your files, share it your way, let Tari do the private parts, see what happened. (148) |
| `/made` | Under the hood: how hidebox was made | Under the hood: how it's made and how to check it · hidebox (59) | The grown-up page: your key, folders, pay to open, who sees what, space, receipts on the Tari chain, and what we can't hide. (124) |
| `/judges` | hidebox for judges | For judges: try it step by step · hidebox (41) | Two six-step tracks for the Tari Council: one device and no wallet, about two minutes; then two devices with Tari, about five minutes. (134) |
| `/fine-print` | The fine print · hidebox | The fine print: privacy policy and terms · hidebox (50) | What we keep, table by table, how long each thing lasts, what you may not do with it, and the form to report a link. (116) |

Each search topic has one page that owns it, so the pages don't compete: private cloud storage and sharing a file
your way (the home), the steps (`/how`), the keys, the locks, Tari and how to check us (`/made`), privacy policy,
terms and reports (`/fine-print`), the judges' script (`/judges`). The key statements keep their registered words
(`tools/claim-registry.json`): the home's description is statement 1 (C32's "Files lock in your browser first.") and
statement 7, the title says neither. `tools/check-copy.py` passes.

### Structured data

The home's graph: `WebSite` (name, URL, language) and `SoftwareApplication`: name, URL, the home's description,
`applicationCategory` `SecurityApplication`, `operatingSystem` "Any (web browser)", free (`isAccessibleForFree`, an
`Offer` at 0), a feature list made of registered sentences (the account, browser encryption, what our server gets, search in the browser, a rule per file, Send by Tari, the chain
record), the card as its image, `/how` as its help, the MIT licence and the repository as `sameAs`. No rating, no
review and no price beyond free: there are none to show, and the site suite fails a page that adds one. Pay to open
is left out: it is a switched feature (`features.pay_to_open`) and a JSON-LD block can't follow the build's copy
variants. `BreadcrumbList` on `/how`, `/made`, `/judges` and
`/fine-print` (Home, then the page; `/made` shows the same trail on screen). No `FAQPage`: the home's two questions are
headings over a table and a box, not a list of answers, and Google shows FAQ rich results only for well-known
government and health sites. No `Organization`: hidebox is an independent project, not a company.

**The content security policy did not change.** A `<script type="application/ld+json">` is a data block: the
browser never runs it, so `script-src 'self'` doesn't apply and needs no hash. The site suite's browser checks load
every page in Chromium and fail on any CSP violation (pass, below); D-01 shows both policies are still the spec's text,
byte for byte (pass, below); the build's lint and the site's markup check allow inline `<script>` only for JSON-LD.

### The home's stills

Each of the five `<img>` says what it shows ("An open box with its lid lifted and five glowing files rising out of
it: a photo, two documents, a video and a song", "A file with a lime padlock inside a browser window; beside it, the
same file as grey static, then a server", and so on). Their stages stay `aria-hidden`: a screen reader still hears the
words beside each picture, not a description of a render. Width, height, the AVIF and WebP `srcset`s, the hero's
`fetchpriority="high"` and the other stills' `loading="lazy"` are unchanged.

### Caddy (`deploy/caddy/Caddyfile`)

| Route | Before | Now |
|---|---|---|
| `/og.png`, `/og-s.png`, `/favicon.ico`, `/favicon.svg`, `/favicon-32.png`, `/apple-touch-icon.png`, `/icon-192.png`, `/icon-512.png` | `no-cache`, CORP `same-origin` | `public, max-age=86400` (a day, not immutable: the brand pass swaps the bytes under the same names), `Cross-Origin-Resource-Policy: cross-origin` (public pictures with nothing to protect) |
| `/robots.txt`, `/sitemap.xml` | `no-cache`; the sitemap as `text/xml` | `public, max-age=3600`; `text/plain; charset=utf-8` and `application/xml; charset=utf-8`, set by name |
| `/api/*` | no `X-Robots-Tag` | `noindex, nofollow` (`/api/v1/config` and `/api/v1/stats` stay allowed in `robots.txt`, so a crawler that renders the pages still reads the numbers they show) |
| `/app/*`, `/vendor/*` | no `X-Robots-Tag` | `noindex, nofollow` (`/app/drive.html` and its siblings are the drive's pages under another address) |

Every other header, both CSPs and every other route are as they were. The private routes (`/s/`, `/t`, `/p/`, `/d/`,
`/drive`, `/send`, `/watch`, `/verify`, `/v2`) already answered `noindex`; `robots.txt` still blocks the ones that
aren't public by design and leaves `/d/` and `/v2` crawlable, so a crawler can read their `noindex`.

### Crawl files and the manifest

- `sitemap.xml` (made by `tools/build.py`): each public page with a `lastmod`, the built commit's date, the same for a
  checkout and for `git archive` with `--source`, so `tools/verify-deploy.py`'s rebuild still matches the manifest.
- `robots.txt`: unchanged (every crawler, AI crawlers included, may read the public pages; its `Sitemap:` line).
- `manifest.webmanifest`: an `id`, the home's words as its description, `dir`, `categories`, and each icon's
  `purpose`. No maskable entry: `icon-maskable-512.png` doesn't exist yet. Its colours are as they were; the home is
  dark first while the manifest's splash is white, which is the brand pass's call.

### The checks

- **`tools/check-seo.py`** (new, Python standard library): reads the site from outside, as a crawler and an unfurler
  do. For each public page: 200 HTML, `lang="en"`, the viewport, the title and description rules, robots, the
  canonical on the expected origin, the whole Open Graph and Twitter card, JSON-LD that parses with the right types and
  no rating or review, one `<h1>` and no skipped heading level, alt text and a size on every image, link text that
  says where it goes, at least three links into the site, both theme colours, the app title and the icons. Then the
  card's real size and weight (1200 x 630, under WhatsApp's 300 KB), its cache and resource policy, the icons and the
  manifest, `robots.txt` (its `Sitemap:` line, the public pages allowed, the private paths blocked, by Google's rule
  matching), `sitemap.xml` (it parses, exactly the public pages, each with a `lastmod`), `noindex` on fourteen private
  routes, and a 404 for an unknown page. `--origin` (the live site, the default), `--dist DIR` (a built tree, served
  locally; what only Caddy sets is reported as SKIP) or `--local` (the production Caddyfile on the server's throwaway
  stack). It prints PASS, FAIL or SKIP per check and the title and description table; `--json` writes the results.
  Named in `docs/verify.md`, `deploy/README.md` and `web/site/README.md`.
- **The site suite** (`web/site/tests/static_checks.py`, M-04): `check_seo` now holds every rule of the head table
  above on every page (titles measured as served), the JSON-LD types, alt text and sizes on every image, and the app
  pages' cards without an address; `check_home_stills` wants alt text on the stills and the three favicons;
  `check_static` checks the manifest's fields; "indexable" means "not noindex" (a robots meta that allows indexing no
  longer counts as noindex).
- **`tools/check-copy.py`** reads what search results and previews show like the page: `twitter:*` beside the
  description and `og:*`, and every string of a JSON-LD block. A new deploy test proves it.
- **D-01** (`tests/e2e/headers_spec.py`, `test_headers.py`): the cards and icons (type, a day, cross-origin), the
  crawl files (type, an hour, the `Sitemap:` line, the home in the sitemap), `noindex` on the API and on two `/app/`
  pages, and no `X-Robots-Tag` on any route that may be indexed. On the throwaway stack with the old Caddyfile it fails
  13 checks (`test_headers-local-old-caddyfile.txt`); with this one it passes 76 of 76.
- **Deploy tests**: `test_config` holds the Caddyfile to `headers_spec` (cards, crawl files, `noindex` routes, order
  before the catch-all); `test_build` checks the sitemap's `lastmod`; `test_check_copy` the new copy sources.

## How a link looks where it's pasted

Every one of these reads the HTML the server sends, without running JavaScript, so what they show is in the head of
each page as served (and for `/s/`, `/t`, `/p/`, `/d/`, `/drive`, in the app page's head).

| Where | What it reads | What a hidebox link shows |
|---|---|---|
| Telegram | Open Graph (`og:site_name`, title, description, image) | "hidebox", the page's title and description, the 1200 x 630 card |
| WhatsApp | Open Graph, fetched by the sender's phone; the image must be small (about 300 KB at most) | the card (`og.png` 142,970 B, `og-s.png` 50,018 B), the title, the description, `hidebox.app` |
| Slack | Open Graph and X (Twitter) card tags, plus the site's icon | "hidebox" with the icon, the title as a link, the description, the card large (`summary_large_image`) |
| X | `twitter:*`, falling back to Open Graph | the large card with the domain (`summary_large_image`) |
| Discord | Open Graph and `twitter:card`; `theme-color` for the embed's edge | "hidebox", the title, the description, the large card |
| iMessage | the title, the image and the icon, fetched by the sender's device | the card with the title and `hidebox.app` |
| LinkedIn, Facebook, Mastodon, Bluesky, forums | Open Graph | the card, the title, the description |
| Google | the title, description, canonical, robots, JSON-LD and the icons | the title and description above; the trail (`hidebox.app › How it works`); the open box as the favicon; a large image preview allowed |

A shared file's link (`/s/…`, `/p/…`) shows `og-s.png` ("Someone shared something with you.", "Open the link to
see it.") and nothing about the file: no name, no id, no key. A drop link (`/d/…`) and the drive (`/drive`) show the
site's card.

**The share cards will change.** The brand pass is replacing the mark and will re-render `og.png` and `og-s.png`
(and the icons) under the same names: the pages need no change, but if the new card says other words, its alt text
does (`og:image:alt` and `twitter:image:alt` in each page's head; the site suite and `check-seo.py` only ask that it is
there and that the two agree). Browsers keep the cards a day; Telegram, Slack, X and the rest keep their own copy of
a preview for a while after that, whatever our headers say.

## Not done, on purpose

- **No analytics, no tracking pixel, no tag manager, no third-party script, no new origin** in either policy.
- **No search consoles or webmaster tools**: no verification file or meta (Google, Bing, Yandex), no IndexNow key or
  ping. They need an account with an outside service; the sitemap and `robots.txt` are enough for any crawler to find
  every page.
- **No ratings, reviews or prices** in JSON-LD (there are none), no `FAQPage`, no `Organization` (above).
- **No new image**: the cards and icons are the brand pass's. The two cards are already 1200 x 630.
- **No `hreflang`**: the product is English only, and every page says `lang="en"`.
- **No preload of the hero still**: its `<img>` is in the HTML with `fetchpriority="high"`, so the browser's preload
  scanner finds it at once; a preload would add bytes and a second way to pick the same file. The home already
  preloads its font; the reading pages' Geist is `font-display: swap`, so their words never wait for it.
- **`/v2`**, the unlinked `noindex` preview, keeps the head and the stills' empty alt text it was made with.
- **`robots.txt`** didn't change: `/app/` and `/vendor/` stay crawlable because the home's widget loads its code and
  styles from there, and a crawler that can't fetch them can't render the home.

## Budgets

Measured on a build of each tree with the production origin (gzip -9; `sizes.txt`), and by the suites on the server.

| Budget | Before (`9bfee2c`) | After |
|---|---|---|
| The home's HTML (part of M-01) | 6,444 B | 6,605 B (+161) |
| M-01, HTML+CSS+JS on `/` (gzip, of 60 KB) | 58.3 KB | 58.4 KB |
| A-06, the widget: phone at load / after a drop (of 40,960 B); computer (of 43,520 B) | 25,013 / 40,510 B; 43,477 B | the same (no `/app/` script or style changed) |
| A-06d, `/drive` until the table renders (of 131,072 B) | 123,202 B, 38 files | 123,202 B, 38 files (the page is fetched as `/drive`, outside the count) |
| V-02, everything `/` asks for at load at 1440 (of 512 KiB) | 257,080 B, 37 requests | 258,461 B, 37 requests (+1,381: the page and the manifest; no new request, Chromium still takes `/favicon.svg`) |
| `/how`, `/made`, `/judges`, `/fine-print` HTML | 4,753 / 19,091 / 4,505 / 8,978 B | 5,026 / 19,331 / 4,769 / 9,219 B |
| `app/drive.html`, `app/view.html`, `app/app.html` | 2,466 / 2,676 / 2,346 B | 2,770 / 2,740 / 2,405 B |

No stylesheet or script changed, so A-06h, V-01 and V-02's files are as they were; no request was added to any page
(the new tags are metadata, the new icon link is one more candidate the browser picks from). V-02's row is the steady
state of three loads of `/` per tree (`requests-at-load.txt`; the first load of each varies with whether the lazy
still under the hero has arrived). The site suite's own V-02 notes swing the same way: 250,646 B before, 259,197 B on
the branch's first run and 341,620 B on the final tree, whose served files differ from that run only in two JSON-LD
words; all three are far inside the limit.

## Suites

On the server as `build` (Python 3.13, Chromium, Node 20), from `git archive` of the branch (`90806a5`, everything but
the last JSON-LD fix), of the final tree (`f045088`) and of `main` before this pass (`9bfee2c`); logs in `suites/`.
On the workstation: the build, the deploy tests, lint, check-copy, the site's file checks, D-01 and `check-seo.py`.

| Suite | Result |
|---|---|
| `tools/build.py --origin https://hidebox.app` | OK, 205 files, 7 pages, 6 vendored files checked |
| Lint | PASS (0 problems), on both trees |
| `tools/check-copy.py` | PASS (0 problems), on both trees |
| Deploy tests | 89 OK (86 before, plus `test_previews_and_crawlers`, `test_sitemap_lastmod_is_the_commits_date`, `test_previews_and_structured_data_are_copy`), on both trees |
| Server | 331 tests OK (5 skipped) |
| App core | ALL PASS (9 steps) |
| Site (`web/site/tests/run.py`) | 42/42 on the branch, 42/42 on the final tree (42/42 on `main`); every page in Chromium with no console error and no CSP violation, the JSON-LD included |
| App UI | 804/804 on the branch; the budget scenarios (A-06, A-06d) 18/18 on the final tree and on `main` |
| D-01, `tests/e2e/test_headers.py --local` (the production Caddyfile on the throwaway stack) | PASS, 76/76; with `main`'s Caddyfile, 13 of the new checks fail |
| `tools/check-seo.py --local` | PASS, 13 of 13 |
| `tools/check-seo.py --dist` (a build with the production origin) | PASS, 12 of 12, 2 SKIP (what only Caddy sets) |
| `tools/check-seo.py` against the live site, before | FAIL, 10 of 13 (the list under Before) |
| The site suite against ten broken copies (`mutants-site-suite.txt`) | each fails, as it should |

After the integrator deploys, `python3 -I tools/check-seo.py` against `https://hidebox.app` should pass all 13 checks,
and `python3 -I tests/e2e/test_headers.py` the new rows of D-01.

## Evidence

[`docs/evidence/2026-10-19/seo-1/`](../evidence/2026-10-19/seo-1/):

| File | What |
|---|---|
| `check-seo-live-before.txt`, `.json` | `tools/check-seo.py` against the live site before this pass (10 failures) |
| `check-seo-dist.txt`, `.json` | against a local build of this branch with the production origin, served by `web/site/tests/serve.py` |
| `check-seo-local.txt`, `.json` | against the throwaway stack: the production Caddyfile in front of a build of this branch |
| `test_headers-local.txt` | D-01 on the throwaway stack with this Caddyfile |
| `test_headers-local-old-caddyfile.txt` | D-01 with `main`'s Caddyfile: the 13 checks this pass added fail |
| `sizes.txt` | each built page and crawl file, raw and gzip -9, before and after |
| `mutants-site-suite.txt` | ten broken copies of the tree, each failing the site suite's new rules |
| `requests-at-load.txt` | what `/` asks for at load at 1440, three loads on each tree (no favicon request was added) |
| `suites/` | the suites' logs on the server: the branch (`after/`), the final tree (`final/`) and `main` before this pass (`before/`) |
