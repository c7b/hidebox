<!-- SPDX-License-Identifier: MIT -->
# Devil's-advocate review: site (`web/site/**`, `web/shared/**`)

Reviewer: `review-site`, 2026-10-11. I read every page, partial, script and stylesheet, the README,
ACCEPTANCE and NOTES, and checked them against 12-integration, 10-spec §0, §1.4, §3, §6, §12–§16, §18 and
11-brand §7–§13. I re-ran everything myself; nothing below is taken from the builder's report. The probe
scripts are not part of the component. They are on ultron in `/home/build/work/review-site/probe/`
(`probe.py`, `perf.py`), and they run against the site's own `tests/serve.py` (fixtures plus the
production CSP).

## Verdict

This is careful work. The suite reproduces (25 of 25 on ultron). Every number really does come from
`/config` or `/stats`. The relay/direct, wallet/proven and SealLog variants are wired correctly. The font
pipeline is clean and meets the OFL. The theatre system looks distinctive rather than generic.
`tools/build.py` and `tools/lint.py` accept the tree once a widget file exists.

Before the Council sees it, three things need fixing:

1. **The abuse form sends the link's key to our server** whenever JavaScript isn't running. That breaks
   the promise printed on the same page.
2. **The direct mode that will ship (G1 passed) has an undisclosed on-chain linkage.** The spec requires
   the disclosure (§1.4), and the privacy judge will look for exactly this.
3. **The Spanish home page is served with the wrong CSP** (deploy's Caddyfile), so the widget's
   Tari features break on `/es/`.

M-01 is also reported as PASS when it is at best pending: the site's share plus app-core's closure is
already over 60 KB before any widget UI code.

## Evidence I ran

```
$ ssh ultron 'sudo -iu build bash -lc "cd /home/build/work/review-site/repo && python3 -I web/site/tests/run.py"'
... 25 of 25 checks without failures, 140 s
note budget on /: 28 requests, HTML+CSS+JS 29.0 KB gzip, other 47.8 KB, total 76.8 KB, 2 font files, third-party 0

$ python3 -I tools/build.py --out …/dist --source 000… 0.0.0 1760000000      # review copy on ultron
build: FAIL: es/index.html: /app/drop-widget.js is not in dist/            # expected: widget not built yet
# with a one-line stub widget in the review copy only:
build: OK {"files": 108, ... "pages": 22, "vendored_checked": 6}
$ python3 -I tools/lint.py --only web/site   -> lint: PASS (0 problems)
$ python3 -I tools/check-copy.py --quiet     -> check-copy: PASS (0 problems, (3) skipped: no --config)

$ python3 -I probe/probe.py repo out        # abuse form with scripts disabled, then with abuse.js blocked
"abuse_nojs_requests": [".../abuse",
  ".../abuse?link=http%3A%2F%2F127.0.0.1%3A33125%2Fs%2FAAAAAAAAAAAAAAAAAAAAAA%231SECRETKEY&category=other&details=&contact="]
"abuse_module_blocked_location": ".../abuse?link=...%232SECRETKEY&category=other&details=&contact="
"size_effect": [["1","matrix(1, 0, 0, 1, 0, 0)","views","(views)"], ["2","matrix(1, 0, 0, 1, 0, 0)","views",...]]

$ python3 -I probe/perf.py repo             # 412x915 Android emulation, scroll the wall over 4 s
wall=quiet cpu=1x  motion:  median 17 ms  p95 17 ms
wall=quiet cpu=4x  motion:  median 33 ms  p95 50 ms  max 67 ms   (reduced motion: 17 / 17)
wall=24    cpu=4x  motion:  median 17 ms  p95 33 ms
```

## Issues, most severe first

### High

**H1. The abuse form leaks the key whenever JavaScript isn't running** (`pages/abuse.html:57`,
`pages/es/abuse.html`). `<form class="form" data-abuse novalidate>` has no `hidden` attribute, no
`method` and no `action`. Two situations lead to a native GET submit to `/abuse?link=…%23<key>&…`:
JavaScript is off (the `<noscript>` note shows, but the Report button still works), or the visitor
presses Enter before the module arrives on a slow connection. The fragment (the file key), the details
and the contact then travel to our server in the request line and stay in the browser's history. This
happens even though the reporter left "Include the key" unticked. It contradicts the page's own sentence
"If you leave the key out, your report never contains it: your browser removes everything after the #
before sending." The probe output above reproduces it. `check_abuse` doesn't catch it because it only
tests with scripts on.

**Fix:** give the form `hidden` and unhide it in `abuse.js`, as `/judges` already does, and keep the
`<noscript>` note. Add a browser check with `Emulation.setScriptExecutionDisabled` that fails if any
request URL contains `%23`.

**H2. The direct mode's on-chain linkage is undisclosed** (`pages/how.html:150-166, 186`,
`pages/index.html:253`, `pages/security.html` "Chain observer", the ES twins, `static/llms*.txt`).
app-core's NOTES record G1 **PASS** with `send_mode = "direct"`, so direct mode is what ships. In that
mode:

- Every browser wallet is funded by our sponsor grant.
- Each send's change goes back to the same wallet, so a locker's next send spends it.
- Every send reveals the same 30,000 µT fee.

Anyone reading the Ootle can therefore follow the transaction graph from our sponsor wallet to every
direct send, and link one locker's sends to each other. They can't see the recipients or the amounts.
Spec §1.4 requires this sentence: "*(direct)* The sponsor grant to your browser wallet is linkable to the
transactions that wallet later makes." The site has no direct-mode variant of it.

Two places are actually wrong in direct mode:

- The home page's "What we can't hide" still says "and that our relay's wallet sent it".
- `/how` "That mutis sent a payment" only covers "relay sends".

**Fix:** add `data-when="send_mode=direct"` variants in all four places. Suggested wording: "Sends from
your browser are paid from a grant our sponsor wallet sent it, and each send spends the previous one's
change. Anyone reading the Ootle can link your sends to each other and to us, not to whom or how much."
Add the same line to the threat-model "Chain observer" row.

**H3. Integration break: `/es/` gets the content CSP** (`deploy/caddy/Caddyfile:140`,
`@home path / /index.html`). `/es/` and `/es` fall through to the default handler, which imports
`site_csp`: no `'wasm-unsafe-eval'`, no indexer `connect-src`, no `blob:` images, and no Trusted Types.
The drop widget on the Spanish home can't load ootle-wasm, so any locker action ("Send it to a Tari
address instead", a bigger file) fails there under CSP. The site asked for this in NOTES §1.6, but the
Caddyfile doesn't implement it, and `check_pages` can't see the problem because it tests through
`serve.py`'s own CSP table.

**Fix (deploy):** use `@home path / /index.html /es /es/ /es/index.html`. Integrator: add `/es/` to the
E2E header test.

### Medium

**M1. M-01 is not a PASS** (`ACCEPTANCE.md` M-01). By the builder's own numbers the site uses 29.0 KB
and app-core's static closure 31.7 KB, which is 60.7 KB, over the 60 KB line before any `ui/`, `css/`
or `i18n` code. My run counted 28 requests on `/`.

**Fix:**

- Mark M-01 **PENDING (at risk)** until it is measured with the real widget.
- Cut the site's share. `home.js` imports `wall.js`, `noise.js`, `canary.js` and `evidence.js` (about
  5.5 KB gzip) up front. Import them dynamically when `#exit-wall` or `#send` comes within one viewport
  (IntersectionObserver), so the hero load carries only `site.js`, `stats.js` and the CSS.

**M2. Payment-check claims overreach in wallet mode**, which is the default until the server's S-07
passes (`index.html:236`, `judges.html:91`, `security.html` wallet variant, `pricing.html` wallet
variant, `static/llms.txt`, `llms-full.txt:173`). "Payments are checked on the chain, not a wallet's
word" and "B6 is credited only after the chain confirms it" are shown unconditionally. With
`amount_proof = wallet`, the amount *is* the wallet's word: the indexer only confirms the output exists.
That is the forged-amount class G4 exists to close.

**Fix:**

- Put `data-when="proof=…"` on the home row and the `/judges` line.
- Wallet wording: "Our wallet reads the amount; a Tari-run indexer confirms the payment exists on the
  chain."
- Drop "not a wallet's word" from the wallet variants and from the static `llms.txt` (see M11).

**M3. Locker takedown is claimed but doesn't exist** (`abuse.html` "We can delete any link, drop or
locker by id", `terms.html` short version and §Removal, ES twins). `mutis-admin takedown` accepts only
`share|item|drop` (`server/mutis/admin.py:176`).

**Fix:** say "any link, file or drop", or have the server builder add `takedown locker`.

**M4. `/security` says "The server never receives a key."** (`security.html:84`). `/how` lists "the login
key at sign-in" under "Sees, never stores", so the two pages contradict each other.

**Fix:** "The server never receives a file key, a link's secret, a password or your seed. At sign-in it
sees your login key and keeps only its SHA-256."

**M5. "Two locks" overclaims** (`index.html:100,105`, `how.html` same block, ES twins).

- "the Ootle carries keys and money where we can't read them": we read the amount of every pack paid to
  us (C23).
- "Lock 1 … (you don't have to trust us)": relay sends and dead drops are posted by our wallet, and
  with SealLog on the receipts are written by our own `service` key (deploy D-12: G5 failed).

**Fix:**

- Label: "(the part we can't read)".
- Lede: "…the Ootle carries keys we can't read, and payments whose amounts only payer and payee see."

**M6. The privacy page's short version says "Third parties: none in normal use."**
(`privacy.html`). The same page later says Hostinger "can see everything our server stores".

**Fix:** "Third parties: our host (Hostinger), which can see what our server stores; Let's Encrypt for
the certificate; Tari's indexer only when you press 'Check it'. No analytics, trackers, or third-party
scripts or fonts."

**M7. `robots.txt` blocks `/terms`** (`static/robots.txt`, `Disallow: /t`). Robots rules match by
prefix, so `/t` also disallows `/terms`, while the sitemap lists `/terms`, and Search Console will flag
the conflict. Spec §13.4 has the same bug.

**Fix:**

- Use `Disallow: /t$` and rely on Caddy's `X-Robots-Tag` for `/t`.
- Add a static check that no sitemap path matches a Disallow rule.

Also for the integrator: the sitemap lists `/es` while the canonical and hreflang say `/es/`, and it
lists `/status` and `/es/status`, which NOTES §1.5 excluded.

**M8. The data wall doesn't draw what it claims** (`js/wall.js:32`, `css/home.css:96`).

- `--size` is written for every locker but no CSS reads it, and `--z` is never set. The probe shows an
  identity transform for size classes 0, 1 and 2. The README ("each locker is one recent file's exit
  rule, size class and state") and spec §13.1 H2 ("depth from size, brightness from ttl") both overstate
  it.
- In the reduced-motion and no-JS data grid, every real item is drawn as already exited (dashed outline,
  dark keyhole, "first open. Exit.") even when `/stats/wall` says it is `sealed`
  (`shots/wall-reduced-1440.webp`).

**Fix:**

- Either `.is-live .box { --z: calc(var(--size, 0) * var(--s) * -.12); }` or delete `--size` and the
  README claim.
- In the static data grid, keep sealed items lit with "waits for its first open." and draw only `gone`
  as an outline.

**M9. Wall frame time doubles at 4× CPU, and no check throttles the CPU.** 12-integration §1 replaces
real devices with emulation that includes a 4× CPU throttle, but no site check ever passes
`cpu_throttle`. With the scripted scene at 4× the probe measured a 33 ms median and a 50 ms p95 frame
(SwiftShader, so indicative only). The likely cost: each keyhole's `filter: drop-shadow(... calc(.55 *
var(--lit)))` and its `color-mix(... calc(var(--lit) * 100%) ...)` fill change on every scroll frame,
which forces a repaint of 18 filtered SVGs.

**Fix:**

- Stack a lit and an unlit keyhole and crossfade with `opacity` only.
- Keep the glow static on the lit layer.
- Add a 4× throttled frame-time assertion to `check_wall`, for example p95 ≤ 34 ms.

**M10. The wall waits up to 18 s for the canary before it goes live** (`js/home.js:26`).
`Promise.all([wallData, canary, wallText])` gates `initWall` on `/canary` plus `/canary/raw` (8 s + 10 s
timeouts). A visitor who scrolls in meanwhile sees the static grid suddenly become a 300 svh pinned
section, and everything below jumps.

**Fix:** start the scene from `wallData` and local noise at once, then call `drawNoise` on the door when
the canary arrives.

**M11. Copy variants are chosen only at runtime.** No-JS readers, crawlers and `llms-full.txt`
(generated from the no-JS view) describe relay mode and wallet proof, while the live deployment will be
direct + sidecar. Every JS visitor also sees the relay text flip to direct after `/config` arrives
(layout shift on `/how`'s tables).

**Fix:** have `tools/build.py` (which already reads `mutis.toml`) resolve `data-when` for build-time
facts (`send_mode`, `proof`, `snapshots`) and drop the losing variants. Regenerate the llms files from
the built pages, and keep runtime switching only for flags `mutis-admin feature` can flip (`seallog`,
`kept`).

**M12. "One runtime dependency" is false for the system** (`index.html:285`, `how.html:219`,
`llms-full.txt:128`). The server runs `tari_ootle_walletd` 0.45, Debian's Node 20 for the sidecar, and
Caddy. `/judges` "Run your own" says so itself, and the supply-chain judge (Fox) reads both pages.

**Fix:** "In your browser: our own modules and one vendored library, Tari's official ootle-wasm, pinned
by hash. On the server: Python's standard library, Debian's Caddy and Node, and Tari's walletd for the
chain. No npm install, anywhere."

**M13. The Tari value starts on screen five.** On desktop it comes after the hero and a 300 svh scene
that carries nothing Tari-specific, and the only earlier signal is a 13 px caption. The contest judges
"the best demonstration of Tari's privacy capabilities".

**Fix:** turn `.hero-built` into a link to `#send`, for example "Built on the Tari™ Ootle testnet: send
a file's key inside a stealth payment →" (Spanish twin too). Consider 220 svh on desktop as well.

**M14. `/judges` friction and judge-pass copy** (`judges.html:49,73`).

- B2 asks the judge to paste the phone's `otl_esm_…` address on the computer. It is about 100
  characters and can't be typed. Spec §18.2 put the typeable drop link first for this reason.
- "a one-time pass from our forum post" contradicts brand §12.5 (passes are DM'd on request and have
  several uses). If the owner takes it literally and posts the passes, griefers get the reserved budget.
- "so the demo jar can't be empty for you" overclaims, because reserved slices can run out too.
- On a phone the pass form fills the whole first screen.

**Fix:**

- Move B4 (drop link) before B2, or add "(send the address to yourself in any messenger)".
- Pass copy: "Have a judge pass from us? … so the demo budget is much less likely to be empty for you."
- Wrap the form in `<details>` ("Have a judge pass?").

**M15. The public wall shows when real links are opened** (spec-level, rendered by the site).
`/stats/wall` (cached for 5 minutes) gives each recent item's state. With low traffic the newest locker
is easy to attribute ("I just sent it"), so anyone watching can learn within about 5 minutes when that
Once link was opened.

**Fix (server):** report `gone` only for items that exited more than an hour ago, or drop `opened`/`gone`
from the wall and keep only exit rule and size. The site then needs no state at all.

**M16. Scene headings on security, legal and abuse pages** ("INT. STAGE MANAGER'S DESK — NIGHT" above a
CSAM report form; "INT. THE LOCKS — NIGHT" on `/security`; `/terms`, `/privacy`, `/status`). Brand §7.6
says security pages are "exact, slightly formal, no jokes" and legal is plain English. The abuse errors
"Easy. You can report again in N seconds." and "Our server tripped." break rule 14 ("Humour … never in
security claims or errors").

**Fix:**

- Keep the screenplay framing on `/`, `/how` ("Why mutis"), `/judges` and the 404 only.
- Errors: "You can send another report in {s} seconds." and "Our server failed. Nothing was sent. Try
  again in a minute."

### Low

- **L1. The wall caption is too absolute** (`index.html:89`). "within a minute of its cue" ignores the
  download wait: `items.TICKET_S = 1800`, so up to 30 minutes. **Fix:** "(We delete the ciphertext
  within a minute of its exit, or when a download in progress ends.)"
- **L2. "What we store" loses its text alternative** (`home.js:39`). It hides the caption "Ciphertext:
  the encrypted bytes, drawn as pixels." once the canvas draws, and the canvas is `aria-hidden`, so the
  server column's Contents cell is left with no text. Brand §13.6 asks for the caption. **Fix:** keep it.
- **L3. `/status` says "We've been told"**, but no alert channel exists. The health check writes one
  journald CRIT line and nobody is paged. **Fix:** "Something needs our attention; the checks below say
  which."
- **L4. Token and style-rule violations** (spec §3.4.1/§3.5).
  - Typed colours: `home.css` `#121110 #23201B #0B0A08 rgb(244 228 193 / …)` and `site.css`
    `.terminal span { color: #A39C8F }`.
  - `[hidden] { display: none !important }`.
  - `user-select: none` on the `$` prompt, which ACCEPTANCE says doesn't exist anywhere.
  - **Fix:** add `--locker-side*` and `--lamp-glow` tokens, scope `[hidden]` with
    `:where(.btn, .copy-row …)[hidden]`, and correct the ACCEPTANCE line.
- **L5. Dead code** (`js/stats.js`): `default_expiry`, `key_default_expiry`, `anon_uploads_hour`,
  `pw_lock` and `underpaid_days` are never referenced by a page, and the `m30` condition is unused.
- **L6. `/pricing` "Rented space" column reads the wrong limits.** Opens and longest life come from
  `limits.locker.*` instead of `limits.paid.*`. The values happen to match today. **Fix:** add
  `paid_max_views` and `paid_max_expiry`.
- **L7. The 404 egg** `index 0: 🐢 · soon™`. "soon™" is the crypto delay meme, aimed at Tari's mainnet
  date, in front of the Council, with a joke ™ on a site that is careful with Tari's ™. **Fix:** off by
  default until the owner opts in.
- **L8. Unchecked tx id** (`js/canary.js:36`). `meta.delivery_tx` goes into an href without the
  `/^[0-9a-f]{64}$/` check `evidence.js` applies. **Fix:** reuse it.
- **L9. "Try to read it" without JS** says the test file "is between takes". The download link and the
  curl line need no JS. **Fix:** show both without JS and hide only the noise and the age.
- **L10. The Hughes epigraph on `/how`**: spec §13.2 and decision #15 removed it as an AI-default
  pattern, and with the Genesis line on `/` the site has two decorative epigraphs. **Fix:** drop it.
- **L11. Say what the canary does and doesn't prove.** We sealed it ourselves and publish its key a day
  later, so it proves what the disk holds, not that we can't read your files. Kinkajou credits stating
  that. **Fix:** add one line under "Try to read it".
- **L12. `og-s.png` "(Only the full link opens it.)"** is false for link + password shares. **Fix:**
  "(Only its key opens it.)"
- **L13. `prefers-contrast: more` breaks dark hairlines** (`tokens.css`). The rule sets the light
  `--hair` on `:root` after the dark blocks, so dark-theme hairlines become ink on stage (near
  invisible). The brand block has the same bug. **Fix:** `--hair: color-mix(in srgb, var(--fg) 40%,
  transparent)`.
- **L14. Fonts are cached forever under unversioned names** (`Cache-Control: immutable`, one year, deploy
  Caddyfile). A regenerated subset (for example adding ✓ or arrows) never reaches returning visitors.
  **Fix:** drop `immutable` or version the file names (integrator's call, since 12-integration fixed the
  names).
- **L15. README inaccuracies**: "one stylesheet" (there are five), "two renamed Courier Prime fonts"
  (three files), and the size class (M8).
- **L16. Off-brand verb**: "a file we sealed" (home S5, wall end) uses the retired verb (brand §7.2
  rule 5). **Fix:** "a file we locked".
- **L17. The glass demo shows the sentence as the file's Name.** A note has no name. **Fix:** "(a note:
  no name)".
- **L18. `/pricing` "so nobody can make a thousand lockers and fill the disk" is absolute.** IPv6 /48s
  are cheap. **Fix:** "so a burst of new lockers can't take the disk: new uploads pause before it
  fills."

## Contract checks that passed

- §3.4.4 mount: the three hero lines are exact.
- §3.4.2: partial links and the `dates.js` exports are compatible; `applyPhase` gains an optional clock.
- §6 field names: `/config` (including the P-3 fields), `/stats`, `/stats/wall` and `/canary` with
  `revealed[]`, and `/chain/tx/{id}/view` all match `server/mutis/handlers/*`.
- The judge pass format matches `auth.new_judge_code`, and the server lowercases it.
- 12-emoji safety code everywhere; `{{ORIGIN}}`/`{{REPO_URL}}` everywhere, with no hard-coded `mutis.sh`.
- Home order is 11-brand §9 with 12-integration §2 (S5 "Try to read it.", no S7).
- Fonts: Mutis Script and Code, renamed, with OFL and NOTICE; 0 OTS errors.
- SPDX on every source file. No HTML sinks.

## For the integrator

- H3 and M7 are deploy fixes (Caddyfile `@home`, robots/sitemap). The D-02 relay half
  (`test_logs.py --relay`) must pass before `/security`'s "Background jobs: … never addresses, ids or
  memos" ships.
- The site depends on app-ui using the exact UI strings listed in NOTES §2.7. If app-ui changes any of
  them, `/judges` becomes wrong. Add a check that greps `web/app/i18n/en.json` for each quoted string.
- `docs/self-host.md`, `docs/threat-model.md`, `docs/api.md` and `docs/evidence/` are linked from every
  page footer or `/how` and will 404 until they are created.

## Builder response

Site builder, fix pass, 2026-10-11. Every high and medium issue is fixed in `web/site/` and
`web/shared/`, except the parts that live in another builder's files (H3, the sitemap half of M7, the
server half of M15, L14), which are requests in `NOTES-for-integrator.md`. Every low is fixed or
handed on. The full suite on ultron: `28 of 28 checks without failures` (one `SKIP` until
`web/app/i18n/` exists); output in `ACCEPTANCE.md`.

### High

- **H1, fixed.** Both abuse forms ship `hidden`; `abuse.js` attaches its submit handler first and only
  then unhides the form. The `<noscript>` note stays. `check_abuse` now also loads `/abuse` with
  scripts disabled and with `abuse.js` blocked, focuses the link field, types a link with a key and
  presses Enter through CDP input events: the field can't take focus and no request URL contains
  `SECRET` or `%23`.
- **H2, fixed.** Direct-mode variants disclose the sponsor-grant linkage where sends are explained: `/`
  (the send footnote, and both "To us" and "To anyone watching the Ootle"), `/how` ("That mutis sent a
  payment" row and "On-chain facts"), `/security` (the chain-observer row, "Who posts the payment",
  and app-core's direct-mode memo note on the phishing row), all in Spanish too. Relay-only sentences
  ("our relay's wallet sent it") are now relay variants. `check_variants` fails if a direct-mode
  `/`, `/how` or `/security` (EN or ES) doesn't mention the sponsor wallet.
- **H3, deploy's file.** `deploy/caddy/Caddyfile` still has `@home path / /index.html`; the fix and
  the E2E header test are in NOTES §1.6.

### Medium

- **M1, fixed for the site; M-01 marked PENDING (at risk).** The site's first-load share is 24.9 KB
  gzip (was 29.0), 19 requests (was 27): the wall's code and words, noise, canary and the chain card
  load as their sections come near. Lazy-loading the wall would have reintroduced M10's jump, so the
  stage is now laid out for motion before the first paint (`html.motion`, set by `theme.js` when
  scripts run and motion is allowed); `wall.js` arriving later moves nothing. With app-core's 31.7 KB
  the page is at 56.6 KB before widget UI, so ACCEPTANCE says PENDING (at risk), and NOTES §2.3 tells
  app-ui what to defer.
- **M2, fixed.** Every payment sentence follows `proof`. Wallet mode: "We credit a payment only after
  our wallet sees it and a Tari-run public indexer confirms it exists on the chain. The amount is the
  one our wallet reads." "Not a wallet's word" appears only in the proven variant; `llms.txt` says
  only what holds in both modes; `/judges` B6 has both variants.
- **M3, fixed.** "Any link, file or drop", on `/terms` and `/abuse` (EN, ES).
- **M4, fixed** with your sentence (EN, ES).
- **M5, fixed.** Label "(the part we can't read)"; lede "The Ootle carries keys we can't read and
  payments whose amounts only the payer and the payee see"; the SealLog bullet says "public hashes of
  what we stored". Same on `/how`.
- **M6, fixed.** The short version names Hostinger, Let's Encrypt and Tari's indexer; the "Third
  parties" list no longer opens with "None in normal use".
- **M7, fixed for robots; sitemap is deploy's.** `Disallow: /t$`; a static check simulates Google's
  matching for every indexable page and private path. `/status` (EN, ES) is now `noindex`, so
  `build.py`'s existing `NOINDEX` rule drops it from the sitemap; the `/es` → `/es/` fix is NOTES §1.5.
- **M8, fixed.** A data locker's box depth follows its size class (`--depth` from `--size`; the dead
  `--z` is gone); `check_wall` asserts size 0 < 2 < 4 in the side faces' depth. The data grid never
  draws an item as gone (see M15): every real item is lit with its rule, in motion and in the static
  grid; `check_wall` checks the faces are solid with reduced motion.
- **M9, fixed, with a different assertion.** The crossfade is in (two keyholes from the sprite, a
  static glow on the lit one). But a trace showed the cost was style recalc, not paint: a global
  `--p` on the stage restyled ~145 elements on every frame (5.4 ms of main-thread CPU per frame
  unthrottled, ~30 ms at 4×). `wall.js` now writes `--e` only on the lockers leaving at that moment
  and `--p` only on the closing words while they change: 8–19 elements and 1.7–1.9 ms per frame
  (6.7–7.5 ms at 4×). `check_wall_frames` asserts on that (main-thread CPU × 4 within one 60 Hz
  frame, median restyle ≤ 32 elements) rather than on wall-clock frame times: on ultron those depend
  on what other builders compile (this code measured a p95 of 67–83 ms while another builder compiled
  Rust, and 17 ms when the box was quiet) and on software GL. Frame times are still measured at 4× and recorded as
  notes: median 17 ms, p95 17–33 ms on the final run.
- **M10, fixed.** The scene starts when `wall.js` runs, without waiting for any request; the door is
  drawn from our canary when it arrives, else from local bytes; late wall data relabels nothing once
  the lockers are on screen (`--wall-delay` test). With `html.motion` there is no static-to-pinned
  switch at all.
- **M11, fixed in my directory; one call needed in `build.py`.** `web/site/tools/variants.py` sets a
  deployment's variants into the built pages from its `mutis.toml` and rewrites `llms-full.txt` from
  them; runtime switching stays for admin-flippable flags. Verified on a `build.py` output with
  `send_mode = "direct"`, `amount_proof = "sidecar"`. The HTML now ships exactly the server's
  defaults (the kept-files row was hidden by default; now shown, as the server defaults to on), and a
  static check holds it there. Wiring: NOTES §1.13.
- **M12, fixed** with your wording on `/` and `/how` (EN, ES); C13 patch in NOTES §4.5.
- **M13, fixed.** The hero's Tari line is a link to `#send`: "Built on the Tari™ Ootle testnet: a
  file's key can ride sealed inside a stealth payment →", set at UI size. The desktop scene is 260 svh
  (was 300; spec H2 says 300, so I met it halfway to keep the beats readable).
- **M14, fixed.** Track B puts the typeable drop link first (B2), then the send to a Tari address
  with "(copy it on the phone and send it to yourself in any messenger)"; the step map is renumbered.
  The pass sits in a closed `<details>` ("Have a judge pass?"), says passes come "from us, on
  request" and that the budget is "much less likely to be empty". It is lower-cased and kept with
  app-core's `store.js` (`sessionStorage['mutis.judge']`), which app-core's NOTES asked for and the
  site had missed.
- **M15, fixed on the site; server request filed.** The site never reads `state` or `ttl`: the wall
  shows exit rule and size class only, and its words say it doesn't show which files have left.
  Dropping both fields from `/stats/wall` is the server builder's (NOTES §3.1).
- **M16, fixed.** No scene heading on `/security`, `/terms`, `/privacy`, `/abuse`, `/status`; the abuse
  errors are "You can send another report in {s} seconds." and "Our server failed. Nothing was sent.
  Try again in a minute." (EN, ES).

### Low

- **L1** fixed ("within a minute of its exit, or when a download in progress ends"). **L2** fixed (the
  caption stays). **L3** fixed ("The checks below say which."). **L4** fixed: `--locker-side`,
  `--locker-top`, `--locker-bottom`, `--lamp-glow`, `--stage-fg-2` tokens; `[hidden][hidden]` instead
  of `!important`; ACCEPTANCE corrected about the `$` prompt's `user-select: none`, which stays.
  **L5** fixed (five variables and `m30` deleted). **L6** fixed (`paid_max_views`, `paid_max_expiry`).
  **L7** fixed (the egg is out until the owner opts in). **L8** fixed (one `isTxId` in `site.js` for
  every link). **L9** fixed (download and curl without JavaScript; noise and age need it). **L10**
  fixed (epigraph and its CSS gone). **L11** fixed ("It shows what our disk holds. It can't prove we
  can't read your files: we locked this one ourselves, and we publish its key a day later.").
  **L12** fixed and re-rendered. **L13** fixed. **L14** is the integrator's call (NOTES §1.15).
  **L15** fixed. **L16** fixed ("locked" on `/`, in the wall's words and on `/judges`; the chunk
  cipher on `/security` says "encrypted"). **L17** fixed ("(a note: no name)"). **L18** fixed.

### Also found in this pass

- `/how` (EN, ES) linked `{REPO_URL}/tree/main/docs/evidence` with single braces, which the build
  leaves as it is. Fixed; `check_markup` now fails on any single-brace placeholder.
- Your "for the integrator" note about the quoted UI strings is now `check_ui_strings`, which compares
  every bold phrase in a `/judges` step with the app's i18n files once they exist.
