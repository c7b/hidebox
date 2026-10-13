<!-- SPDX-License-Identifier: MIT -->
# NOTES for the integrator (site builder: web/site, web/shared)

Everything I need from other directories, and every decision I made where the documents disagreed or
were silent. Section numbers below are referenced from `ACCEPTANCE.md` and from the builder response
at the end of `REVIEW-devil.md`. Items marked **(review)** came out of the devil's-advocate review.

## 1. Deploy builder (`tools/build.py`, Caddy, CI)

1. **Includes:** pages use `<!--#include header-->`, `footer`, and the Spanish `header-es`,
   `footer-es` (the app may use `status-line` / `status-line-es`). Please map any
   `<!--#include NAME-->` to `web/shared/partials/NAME.html` and fail only when that file is missing.
   Partials never include other partials. Each partial starts with an SPDX comment; dropping it from
   the output is fine.
2. **Placeholders** used by my files: `{{ORIGIN}}`, `{{GIT_SHA}}`, `{{SECURITY_DROP_URL}}`,
   `{{REPO_URL}}`, `{{SRI}}`. Expand them in pages **and** in the static text files `robots.txt`,
   `llms.txt`, `llms-full.txt` and `.well-known/security.txt`. A static check now fails on a
   single-brace `{NAME}`, which the build would leave as it is (`/how` had one; fixed).
3. **`{{SECURITY_DROP_URL}}` empty** (until the owner's drop exists): expand it to
   `{{ORIGIN}}/abuse`, as 12-integration §1 says. security.txt then has two `Contact:` lines that both
   work. Its `Expires:` is a fixed `2027-10-01T00:00:00Z`; refresh it yearly.
4. **Copy `static/.well-known/`** (a dot directory) to `dist/.well-known/`.
5. **Spanish pages and the sitemap:** `pages/es/index.html` → `dist/es/index.html`,
   `pages/es/<name>.html` → `dist/es/<name>/index.html`, `pages/es/404.html` → `dist/es/404.html`.
   Caddy answers a missing path under `/es/` with `/es/404.html` (done). **(review M7)** Two sitemap
   fixes in `build.py`: write the Spanish home as `{{ORIGIN}}/es/` (its canonical and hreflang), not
   `/es`; `/status` and `/es/status` now carry `<meta name="robots" content="noindex">`, so the
   existing `NOINDEX` test already leaves them out. The sitemap should then hold the 9 indexable
   pages and their 9 `/es/` twins.
6. **CSP (review H3, still open in `deploy/caddy/Caddyfile`):** `/` **and `/es/`** both embed the
   drop widget, so both need the app CSP. Today `@home path / /index.html` sends `/es/` the content
   CSP: no `'wasm-unsafe-eval'`, no indexer `connect-src`, no Trusted Types, so every Tari feature of
   the widget fails on the Spanish home. Please use `@home path / /index.html /es /es/ /es/index.html`
   and add `/es/` to the E2E header test. Every other site page takes the content CSP. Every site page
   passes in Chromium under those exact headers (`check_pages`, through `tests/serve.py`'s table).
7. **Lint:** `index.html` (both languages) and `faq.html` (both) carry a JSON-LD data block,
   `<script type="application/ld+json">`. It isn't executed and CSP doesn't apply to it; please
   allow it. My SVG files contain the namespace identifier `http://www.w3.org/2000/svg` (not a fetch).
   No `style=` attribute and no inline handler anywhere (`check_markup`).
8. **Not served:** `web/site/og/`, `tools/`, `tests/`, `shots/`, README/ACCEPTANCE/NOTES/REVIEW.
9. **Runtime imports into the app's library:** `js/abuse.js` imports `/app/lib/pow.js` and
   `/app/lib/api.js`; `js/reveal.js` imports `/app/lib/b64.js`, `crypto.js`, `format.js`;
   `js/judges.js` imports `/app/lib/store.js`. `dist/app/lib/` must keep those paths. The
   proof-of-work Worker is `/app/lib/pow-worker.js` (the app's own policy).
10. **SRI on the widget:** both home pages reference `/app/drop-widget.js` with `integrity="{{SRI}}"`.
    Until the app-ui builder adds that file the build's SRI step has nothing to hash; build after it
    lands (my test server leaves the attribute out while the file is missing).
11. **Shapes my scripts read** (please keep `collect-evidence.py` and the health check to these):
    - `/evidence.json`: `network`, `ootle_version`, `wasm_sha256`, `deliveries`, `payments`,
      `decoys_today`. Each entry of `deliveries`/`payments` may be a 64-hex tx id or `{"tx_id", "epoch"}`;
      the home card uses `deliveries[0]`. Anything else is ignored.
    - `/status.json`: `{"updated_at": <unix s>, "attention": bool, "checks": {name: "green"|"amber"|"red"}}`.
      Names with a label: `https api chain_worker walletd sponsor_balance mirror canary credits disk
      budgets`; other names are shown as they are.
12. **CI:** `python3 -I web/site/tests/run.py` (Python stdlib, Node 20, Chromium). It covers the
    11-brand P-18 font check (any `OTS parsing error` fails) and parts of P-20 (banned phrases and
    typed `/config` numbers in site pages). The font pipeline is `web/site/tools/subset-fonts.sh`
    (12-integration §2 says `tools/subset-fonts.sh`; the task placed it in my directory).
13. **Copy variants at build time (review M11), one call in `build.py`:** after `copy_site()` and
    before `process_files()` (so its `llms-full.txt` gets its placeholders filled):
    ```python
    sys.path.insert(0, str(web / "site" / "tools")); import variants
    variants.apply(dist, tomllib.load(open(config_path, "rb")))
    ```
    It gives every `data-when` variant in the site pages its `hidden` attribute from the deployment's
    `mutis.toml` (`gates.send_mode`, `gates.amount_proof`, `features.seallog`, `features.kept`,
    `hosting.snapshots`, `security_drop_url`; a key the file doesn't set keeps the HTML's default,
    which is the server's), and writes `dist/llms-full.txt` again from the built `/how` and
    `/security`. Readers without JavaScript, crawlers and AI readers then get the true sentences when
    the integrator flips `send_mode` or `amount_proof`, and nobody sees the copy switch after `/config`
    arrives. `stats.js` still switches variants at runtime for flags `mutis-admin feature` changes.
    It touches only site pages (not `app/`, `vendor/`, `shared/`, `site/`). The deterministic build is
    kept: the same config gives the same files.
14. **robots.txt (review M7):** `Disallow: /t$` (Google and Bing read `$` as the end of the path), so
    `/terms` is no longer blocked by the `/t` rule. The viewer `/t` also gets `X-Robots-Tag: noindex`
    from Caddy's `@viewer` (already there). A static check simulates the matching for every indexable
    page and every private path.
15. **Font caching (review L14):** Caddy sends `/shared/fonts/*` with `max-age=31536000, immutable`,
    but 12-integration fixed the file names, so a regenerated subset (say, one that adds a glyph)
    would never reach a returning visitor. Please drop `immutable` and use a day, or version the
    names; the integrator decides, since the names are 12-integration's.

## 2. App-ui builder

1. **The hero is split between us.** The site renders, around `#mutis-drop`: the page's only `<h1>`
   ("Drop a file." with a pointer, "Choose a file." on touch, by CSS), line 2, then under the mount
   "Free. No sign-up. We can't open it." and "Built on the Tari™ Ootle testnet: a file's key can ride
   sealed inside a stealth payment →" (a link to `#send`, review M13). With `data-variant="hero"` the
   widget should render only the zone and its states, no heading.
2. **Widget CSS:** the home pages link `tokens.css`, `base.css`, `site.css` and `home.css` only.
   Either `drop-widget.js` loads its own stylesheet, or tell the integrator which file to add (with
   SRI) to the head of `pages/index.html` and `pages/es/index.html`.
3. **Budget (M-01), at risk (review M1):** the site's share of `/` at first load is now **24.9 KB** of
   compressed HTML+CSS+JS (it was 29.0): the wall's code and words, the noise and canary code and the
   chain card load as their sections come near. Your library closure is 31.7 KB, so the page is at
   56.6 KB before any widget UI code. To stay under 60 KB, load on first use what the hero doesn't
   need before a drop (the viewer-side `open`, `preview`, `download`, `filetype` paths, the i18n file
   for other languages). Keep `--font-code` out of the idle state, so `/` still loads two font files.
4. **Optional event detail:** if `mutis:state` with `state: 'sealed'` carries
   `detail.preview = {name, size, sizeStored, noise}` (`noise` = the first ≤ 9,216 bytes of the
   ciphertext as a `Uint8Array`), the site shows the visitor's own file in "What we store" and labels
   the wall's centre locker "(yours)" with its noise. Nothing leaves the tab. Without it, both keep
   our demo sentence and our canary.
5. **Shared assets you can use:** `/shared/icons.svg` (ids `lock link copy send check warning report
   save exit menu close external arrow drop watch keyhole`;
   `<svg class="icon"><use href="/shared/icons.svg#arrow"/></svg>`), `/shared/theme.js` (classic
   script in `<head>`; buttons `[data-theme-toggle]` with `data-off` / `data-on` labels; choice in
   `localStorage['mutis.theme']`; it also sets `html.motion` when scripts run and motion is allowed),
   `/shared/dates.js` (`applyPhase(root, now)` takes an optional clock), the partials. `base.css` has
   **no `.ticks`**: 11-brand v2 §13.4 removed corner ticks, and 11-brand wins on visuals. New tokens:
   `--locker-side --locker-top --locker-bottom --lamp-glow --stage-fg-2`.
6. **Judge pass (changed, to match app-core's `store.js`):** `/judges` lower-cases a valid pass and
   keeps it with `saveJudgePass()` from `/app/lib/store.js`, i.e. `sessionStorage['mutis.judge']`,
   for the tab. Please read it with `savedJudgePass()` and hand it to `pow.setJudgePass()`; app-core
   already drops it when the server answers `details.judge = "invalid"`.
7. **Words the site quotes from your UI**; please use exactly these, or tell me. A static check
   (`check_ui_strings`) compares every bold phrase in a `/judges` step with `web/app/i18n/en.json`
   (`{placeholders}` match anything) and fails on a phrase it doesn't say:
   - `/judges`: "Opens once", "Copy link", "Open it", "This secret already made its exit.", "What we
     know about this link", "Open my locker", "Later", "Leave me a file", "Make my drop link",
     "Location and camera data removed", "Delivered", "Left in your drop", "Send it to a Tari address
     instead", "Send", "Sent", "On the Ootle ✓", "What the chain sees", "Inbox", "Open", "See what a
     view key sees", "{n} files readable with this key", "Get more room", "Pay with demo tTARI",
     "Waiting → Seen on chain → Amount proven → Added", "Verify", the 12-emoji safety code. Track B
     now puts the drop link (typeable) before the send to a Tari address (review M14).
   - `/how`, `/security`, `/faq`, `/privacy`: "Check it on Tari's indexer", "The recipient uses
     another Ootle wallet", the "What we know" page, "Delete my locker", keeping the original photo
     (unstripped), "This secret already made its exit.".
   - Vocabulary: locker, drop link, view key, safety code.
8. **Direct-mode inbox (from app-core's note, now printed on `/security` in direct mode):** "inboxes
   show a memo that isn't exactly a mutis link as plain text, never as a link". Please keep that true
   in the inbox UI.

## 3. Server builder

1. **The wall publishes whether a recent link was opened (review M15).** `/stats/wall` gives each
   item's `state` (`sealed` / `opened` / `gone`), and `ttl` 0 is derived from it. With little traffic
   the newest locker is easy to attribute ("I just sent it"), so anyone told about it can learn,
   within the 5-minute cache, when that Once link was opened. The site no longer reads `state` or
   `ttl`: each locker shows only its exit rule, with its size class as the box's depth. Please drop
   `state` and `ttl` from `/stats/wall` (or report neither for items younger than a day). `/how`
   describes what the API publishes and will be updated when you do.
2. **Canary reveals:** the site opens the newest `revealed[]` entry that carries `fk`. If `/canary`
   starts listing hours the verifier missed (app-core's review L8), give them no `fk` and tell me the
   field to show "missed (the verifier restarted)".
3. **Takedown:** `mutis-admin takedown` takes `share|item|drop`, so the site now says "any link, file
   or drop" (review M3). No locker takedown is needed for the copy.

## 4. Integrator: claims, copy and docs

1. **11-brand C15 is false for this build.** It says a view key "can read everything sent to this
   address, including files". G2 passed (kind-3 wraps), so the site uses spec §1.4 / §13.2: a view key
   shows arrivals and amounts, can't spend, can't open files sealed to a locker; files sent with "The
   recipient uses another Ootle wallet" (kind 4) are the labelled exception. Please patch C15.
2. **C8's direct-mode sentence overclaims.** "In direct mode your browser sends it and we learn
   nothing" ignores what spec §1.4 says we still see. The site says: "Your browser builds and pays for
   the payment itself. We pass it to the network, so we see that your locker sent a transaction, not
   who it was for."
3. **C9 needs a direct-mode sentence (review H2), spec §1.4.** In direct mode the browser wallet spends
   our sponsor grant and then each send's change, so the chain links a locker's sends to each other
   and to our sponsor wallet. The site says, on `/`, `/how` (two places), `/security` (threat model
   and "Who posts the payment") and in their Spanish twins: "Sends from your browser spend a grant
   from our sponsor wallet, then each send's change. Anyone reading the Ootle can link your sends to
   each other and to our sponsor wallet, but not see to whom or how much." Please add it to the
   registry, and keep `send_mode = "relay"` until deploy's E-J passes, as app-core asks.
4. **C11 has two variants now, and the short form belongs to one (review M2):** `wallet` (the default
   until G4's sidecar runs in production): "We credit a payment only after our wallet sees it and a
   Tari-run public indexer confirms it exists on the chain. The amount is the one our wallet reads."
   (home row: "We credit a payment only after a Tari-run indexer confirms it exists on the chain.").
   `sidecar`/`chromium`: "We credit a payment only after the official Tari library opens its
   commitment to the exact amount and a Tari-run public indexer shows it committed on the chain."
   The short form "not a wallet's word" appears only in that second mode. `llms.txt` says only what
   is true in both. "Two independent indexers" is never said.
5. **C13 is false for the whole system (review M12).** "One runtime dependency" ignored walletd,
   Debian's Node and Caddy. The site now says: "In your browser: our own modules, its WebCrypto, and
   one vendored library, Tari's official ootle-wasm, pinned by hash. On the server: Python's standard
   library, Debian's Caddy and Node, and Tari's walletd for the chain. No npm install, anywhere."
6. **Two locks (review M5):** Lock 1's label is "(the part we can't read)", not "(you don't have to
   trust us)": our wallet posts relay sends and dead drops, we read the amount of every pack paid to
   us, and SealLog receipts are written by our own `service` key. The lede: "The Ootle carries keys
   we can't read and payments whose amounts only the payer and the payee see".
7. **SealLog copy** (C7, C22, exit receipts, "(every exit)", the footer link) appears only while
   `/config.features.seallog` is true. `llms.txt` doesn't mention SealLog: add it when it's live.
8. **Brand S5 row "Nobody else is watching."** is replaced by C21's own words, "No analytics, no
   trackers, no third-party scripts or fonts." (the host and the network can still watch). The
   privacy page's short version now names the third parties itself (review M6).
9. **Home order** is 11-brand §9 with 12-integration §2 (S5 "Try to read it.", no S7). I added the dead
   drop ("Or let anyone leave you one.") as the second half of S3: it is P0, it's the contest's literal
   "secret submissions", and brand v2 had dropped it from the home page. Remove it if you disagree.
   "Try to read it" now says what the canary proves and what it doesn't (review L11).
10. **The wall's "(paid)" locker** is now "(one week)": no copy mentions paying to open.
11. **Not printed until they're true:** the 24-hour abuse review (brand §11.5 marks it as the owner's
    commitment), `abuse@mutis.sh` (no domain or mailbox), "self-host in 10 minutes" (unmeasured),
    "Pay from any Ootle wallet" (unverified), "we warn you in the app from day one" (app behaviour),
    "We've been told" on `/status` (no alert channel exists, review L3).
12. **Please confirm** the two CSAM links on `/abuse` (spec marks them [A]):
    `https://report.cybertip.org/` and `https://www.inhope.org/EN`.
13. **Docs the site links to** (please create; they 404 until then): `docs/self-host.md`,
    `docs/threat-model.md` (with the self-review findings, and app-core's direct-mode memo note),
    `docs/api.md`, `docs/evidence/`. Existing targets: `LICENSE`, `server/mutis/payments.py`,
    `tools/verify-deploy.py` (deploy builder).
14. **`/security` "Background jobs: … never addresses, ids or memos"** holds only once deploy's D-02
    relay half (`test_logs.py --relay`) passes (review, "for the integrator").
15. **Owner, Tier 3:** approve `/terms` and `/privacy` (full texts written, not legal advice); review
    the Spanish pages (M-10). The optional 404 line `index 0: 🐢 · soon™` (brand §11.7, owner's call)
    is **out** until he opts in (review L7). Judge passes are described as "from us, on request"
    (brand §12.5: DM'd); if they are ever posted publicly, griefers get the reserved budget.
16. **tokens.css** is the 11-brand §13.2 block with these changes: `body` and `::selection` live in
    `base.css` (spec §3.4.1 puts them there), `--shadow-float` is defined per theme (11-brand §13.5
    values), five additions for the wall and the terminal (§2.5 above), and `prefers-contrast: more`
    sets `--hair` from `--fg` so dark hairlines stay visible (review L13; 11-brand's block has the
    same bug).
17. **Screenplay framing** (scene headings) stays on `/`, `/how`, `/judges`, `/pricing`, `/faq` and the
    404; it's gone from `/security`, `/terms`, `/privacy`, `/abuse` and `/status` (brand §7.6, review
    M16). The abuse form's errors are plain (brand rule 14).

## 5. Decisions this build made

| Topic | Decision | Why |
|---|---|---|
| Numbers in copy | runtime fill from `/config` and `/stats`; each sentence that carries one is hidden until its values arrive | the build has no config placeholders, and P-20 forbids typed numbers; a failed request removes a sentence instead of showing a guess |
| Copy variants | the HTML ships the server's defaults (relay, wallet-read amounts, SealLog off, kept files on, host snapshots on); `tools/variants.py` sets a deployment's own at build time; `stats.js` corrects them at runtime | if nothing else runs, the page claims less, never more; once the build runs, every reader gets the true sentence (§1.13) |
| The wall | brand v2's front-facing 2.5-D lockers (3D boxes, no camera turn) playing brand §9.3's beats; real coarse data from `/stats/wall` relabels the lockers when there are at least 8 items and they aren't on screen yet | 12-integration: brand wins on visuals and motion, and asks for the data wall; nothing changes under the visitor's eyes |
| Data-wall content | exit rule and size class (the box's depth) only; every real item drawn lit with its rule | `state` tells when a link was opened (§3.1); brightness from `ttl` is dropped with it |
| Wall performance | the stage is laid out for motion before the first paint (`html.motion`); per frame, only the leaving lockers' `--e` and the closing words' `--p` change; a lit keyhole fades over a dark one | a global `--p` restyled ~145 elements every frame (5.4 ms of main-thread CPU, ~30 ms at 4x); now 8–19 elements and 1.7–1.9 ms (review M9) |
| Home page loading | the first screen's code only; the wall, noise, canary and chain card load as their sections come near (the wall: its top edge in view) | M-01 (review M1); the wall's data is still asked for at once, so it can arrive before the lockers show |
| Data-mode stage directions | phrased as rules ("Once: the first open is the cue.") | the real files haven't been opened; the scene plays their rules forward without claiming events that didn't happen |
| Fonts | subset adds U+2122 (™) to brand §13.3's ranges | "Tari™" appears in script-set headings |
| `/` fonts | code samples on the home page use Mutis Script | spec M-01: two font files on `/` |
| Theme toggle | in the footer of every page, plus "Lights off" from 18:00 local on Oct 31 unless the visitor chose | brand §9.1 and §13.11 |
| Status chip | `<details>` in the header with the status line; the line is repeated in header, footer and the `status-line` partial, and a test keeps the three identical | the build may not expand includes inside partials |
| `[hidden]` | `[hidden][hidden] { display: none; }` in `site.css` | wins over `.steps li`, `.btn` and the like without `!important` (spec §3.5, review L4) |
| Screenshots | WebP from Chromium, 112 files, 3.0 MB; hero shots use a test-only stand-in for the widget | the widget doesn't exist yet; the stand-in is never served |
| Stencil numerals (M-09) | not made | optional per 12-integration; no real use in brand v2's wall |

## 6. Integration pass (2026-10-11)

Every request aimed at `web/site` or `web/shared` in the builders' NOTES, NOTES-ui, the reviews'
builder responses and 12-integration §7 (including the §7.4 claim-registry ratifications), as the
owner of this directory. Sections 1 to 5 above are the site builder's record; the rows below say
what became of them.

### Integration responses

| From | Request | Change |
|---|---|---|
| NOTES-ui, site 1 | link the widget's stylesheet with SRI | `<link rel="stylesheet" href="/app/css/widget.css" integrity="{{SRI}}">` after `home.css` in `pages/index.html` and `pages/es/index.html` |
| NOTES-ui, site 2 | `detail.preview` on `sealed` | already read by `home.js`; a note's empty `name` now keeps "(a note: no name)" instead of an empty cell |
| NOTES-ui, site 3 (app review L7) | hide line 2 while the card shows | `home.js`: hidden on `mutis:state` `sealed`, shown again on `idle`; `check_interactions` |
| NOTES-ui, site 4 (app review H4) | `/judges` B6 per amount-proof mode, and a check per mode | B6 shows "Seen on chain → Amount proven" (proven) or "Seen by our wallet → Exists on chain" (wallet), EN and ES. `check_ui_strings` reads `/judges` in each mode through `variants.resolve`, drops hidden variants, and requires a bold arrow sequence with the payment steps to equal the app's `upgrade.step.*` labels for that mode; `check_variants` checks the same sentence in Chromium with `/config` in each mode |
| NOTES-ui, site 5 (app review M4) | prefill `/abuse` from `#link=` | `abuse.js` reads the fragment, clears it at once with `history.replaceState`, and fills the field through `cleanLink` (our origins, no key); `check_abuse` covers a drop link, a link with a key (stripped) and a foreign origin (refused) |
| app-core, site 1 | judge pass through `store.js` | already done in the site builder's fix pass (review M14) |
| app-core site 2, server site 1 (app-core review L8) | show a missed canary reveal | `canary.js` lists every `revealed[]` entry with `missed: true` as "Test file #n: missed (the verifier restarted)." under the reveal box (EN, ES); fixture and `check_reveal` |
| server §3, site 3.1 (review M15) | `/stats/wall` items are `{size, exit}` | the site already read only those; the wall fixtures now match the server |
| server §3 | render the tx view as given | the home chain card describes the output that carries the sealed key and shows only when that output reads `amount: "hidden"` and `owner: "one-time key"`; otherwise it stays hidden (it prints "hidden" for both) |
| server decisions (`/stats`, `/stats/wall`), Integrator 7, review L7, L10 | `/privacy`, `/how` and the glass box | `/privacy` gains "What we publish" (every `/stats` field, the latest upload to the minute, the wall's classes and that someone who knows a file's size and rule may recognise it); backups hold the wrapped key of every link open at backup time; erased rows can sit in the write-ahead log and the backups. `/how`: the live-numbers row (no time-left or state any more), "Sees and stores" (when it left, the first open's time, owner-only), backups. Glass box "Opens": "a count, and the time of the first open". EN and ES |
| deploy, site 1 (review H4) | remove "Decoy sends today" | gone from `pages/judges.html`, `pages/es/judges.html` and `judges.js`; fixture without `decoys_today` |
| deploy, site 2 (review M1) | `wasm_sha256` may be `null` | `/judges` shows "not reported yet" |
| deploy, site 3 (review L5) | verify-deploy needs Python 3.11 | `/security#verify`: "It needs git and Python 3.11 or newer." (EN, ES) |
| deploy site 4, review M8, 11-brand P-9 | link `/releases.json` once SealLog is on | `/security#verify`, `seallog=on` only: release hashes notarized through SealLog since it went on, `/releases.json`, and only events signed by the log's writer key count (template review M3); C10's sentence gains "release hashes notarized on the Ootle" in the same variant |
| deploy site 5, site §1.15 (review L14) | font caching | Caddy caches `/shared/fonts/*` for a day; the names stay as 12-integration fixed them. Closed |
| template §1.3, §4 (review M1, M3); 12-integration §7.3, §7.4 | SealLog on `/security`, C22 | new `/security#seallog` (`seallog=on`, with its TOC entry): what a proof shows (C22's ratified wording), that the log has no owner and anyone can check `owner_rule: "None"`, that one key writes it, our `service` key, which holds our public tTARI (G5), the template's leak line (steps of 64), and `template/check.sh --onchain`. `/how` gains C22 after C7, and its who-sees-what SealLog row names the writer. SealLog counts on `/` and `/how` now say "in steps of 64" (EN, ES) |
| 12-integration §7.2 | cadence only from `/config` | no page types it (`checkpoint` variable); the config fixture is 900 s; `check_config_numbers` now also flags a seconds value typed as minutes ("15 minutes"); B7 says each receipt is "not on the record yet" (the app's words) until the next checkpoint, at most `{checkpoint}` away |
| 12-integration §7.4 | "the server builds every memo" holds for relay sends | `/security` phishing row: "the server writes every memo our relay sends, from its own address" (EN, ES). C9 (direct), C11 (two variants), C13, Lock 1 "(the part we can't read)" and "any link, file or drop" were already on the pages |
| 12-integration §7.5, §7.6 | relay; `amount_proof = sidecar` | the HTML keeps shipping the server's defaults; the deployment's own variants need `variants.apply` in `build.py` (request below) |
| 12-integration §7.8 | Spanish ships, zh-CN doesn't | every change above has its Spanish twin; no zh-CN |

Also in this pass: the budget check now measures `/` with the real widget (non-GET requests, the
widget's anti-bot challenge, are counted as they arrived): 35 requests, 47.8 KB compressed
HTML+CSS+JS, 94.3 KB in all, 2 font files, 0 third-party, so M-01 passes. With the app's widget in
the tree, the test-only stand-in (`tests/fixtures/widget-stand-in.js`, `--widget` in `serve.py` and
`shots.py`) and the browser checks' allowance for a missing widget are gone, and `shots/` was
rendered again with the real widget.

**Not applied**, deploy site 1's optional line "Decoy sends: on, about one every {decoy_mean_gap}
min": `/config` has no such field (only `features.decoys`), and typing a gap would break P-20.
`/security` already names decoy sends among what stops a chain observer.

### Integration requests

**Deploy**
1. Still open (site §1.6, review H3): `deploy/caddy/Caddyfile` still has `@home path / /index.html`,
   so `/es/` gets the content CSP and the widget's Tari features fail there. Use
   `@home path / /index.html /es /es/ /es/index.html`, and add `/es/` to the E2E header test.
2. Still open (site §1.13, review M11): `tools/build.py` doesn't call `variants.apply` yet. With
   `amount_proof = "sidecar"` (12-integration §7.6) readers without JavaScript, crawlers and
   `llms-full.txt` would otherwise get the wallet-mode sentences ("this deployment doesn't prove it
   with the official Tari library"), which are false for that deployment. Visitors with JavaScript
   get the right ones from `/config`.
3. Still open (site §1.5, review M7): the sitemap's Spanish home is `{{ORIGIN}}/es/`.

**Integrator (root, `docs/`)**
1. Still open (site §4.13): `docs/self-host.md`, `docs/threat-model.md`, `docs/api.md` and
   `docs/evidence/` are linked from every footer, `/how`, `/judges` and `/security`, and `docs/` is
   empty.
2. Owner, Tier 3, unchanged (site §4.15): `/terms`, `/privacy`, the Spanish pages.
