<!-- SPDX-License-Identifier: MIT -->
# Devil's-advocate review: deploy/, tools/, tests/e2e/ and ultron's state

> Historical record (2026-10-11). The site and app also had Spanish pages then; the owner had them
> removed on 2026-10-12 (CHANGELOG), so mentions of `/es/`, `es.json` and the language switch below
> describe code that is now only in the git history. The current layout is in this directory's README.

Reviewed on 2026-10-11 against 12-integration, 10-spec §0, §2, §3, §8, §10, §14–§18 and 11-brand §7, §8,
§13.3, §16. I didn't trust the report: I re-ran the tests, probed the live host, read every script and
unit, and checked ultron read-only (as lcam/root `ls`, the walletd *backup* copy opened `immutable=1`).
I edited nothing except this file.

**What I re-ran:** `python3 -I -m unittest discover -s deploy/tests` → 43 OK; `tools/lint.py` → PASS;
`tools/check-copy.py` → PASS (3 "anonymous" to read); `tests/e2e/test_headers.py --holding` → PASS 25/25.
That last result covers less than it seems: 19 of the 22 page routes answer 404 on the holding build,
so the live check confirms the app CSP on `/` only.

**Verdict.** The infrastructure is unusually careful. The walletd move kept every balance and backup,
the admin API sits on a socket, the 18143 guard is in place, the Caddy filter was proven at DEBUG, and
the umask bug was found by a rehearsal. Four problems would still show in front of the Council:
1. the build publishes an internal review file;
2. a planned redeploy (the domain move or setting `security_drop_url`) silently rolls production back;
3. HTML with no `Cache-Control` and SRI-pinned JS can break the drop widget for returning judges
   after any deploy;
4. `/evidence.json` publishes the daily decoy count, which cancels the decoys' volume hiding.
Each is a small fix. Ranked below; every item has a concrete fix.

---

## High

### H1. The build serves `web/app/REVIEW-devil.md` and lists it in the public manifest
`tools/build.py:36` uses a deny-list (`NEVER_SERVED`: README, NOTES*, ACCEPTANCE*, package.json, *.py).
`copy_site()` on today's tree puts `app/REVIEW-devil.md` into `dist/`. That file is the app's internal
critique, and it would be served at `/app/REVIEW-devil.md` and listed in `/.well-known/mutis-manifest.json`,
the very file `/security` asks Fox to inspect. Reproduce with `build.copy_site(Path("web"), dist, False)`.
**Fix:** use an allow-list of served types (`.html .js .mjs .css .wasm .svg .png .woff2 .webmanifest .txt .xml .json`
plus `LICENSE`/`NOTICE`/`SHA256SUMS`/`PROVENANCE.md`). Add a test that fails on any other `.md` in `dist/`.

### H2. Redeploying the same commit after a config change rolls production back to older code
`deploy/scripts/activate-release.sh:126-135`: when `<sha>` is already `current`, the new build is
discarded. A changed manifest only prints the message "keeping the live copy". Then `smoke.py` compares
the live manifest (old `{{ORIGIN}}`/`{{SECURITY_DROP_URL}}`) with the local build (new values), fails,
and `deploy.sh:83` calls `rollback.sh --from-failed <sha>`. Because `current` is that same sha, the
rollback switches to the **previous** release. Two operations are planned exactly this way: README
"Moving to a domain" step 4 (re-run deploy after flipping `public_origin`), and 12-integration §1
(fill `security_drop_url` after the first deploy, then rebuild security.txt).
**Fix:** make the release id `<sha>-c<first 8 hex of sha256(config values the build uses)>`, and
widen the regex at `activate-release.sh:106`. If the same id is live and the manifest differs, refuse
with a clear message. Have `deploy.sh` roll back only if `current` actually changed. Add a unit test for
"same ref + new origin".

### H3. With no `Cache-Control` on HTML and SRI-pinned JS, a deploy can break the widget for returning visitors
Live: `/`, `/shared/tokens.css`, `/shared/theme.js` and `/holding.css` carry only `ETag` and
`Last-Modified`, with no `Cache-Control`. Browsers then cache heuristically, for 10 % of the time since
`Last-Modified`. `/app/*` is `no-cache`, so it is always fresh. After a redeploy, a judge who follows
the forum link again can get the cached `index.html`, whose `integrity="sha384-…"` for
`/app/drop-widget.js` no longer matches the freshly revalidated script. The browser blocks it, and the
hero is dead until the cache expires. That is hours after a deploy that is a day old, and the
Oct 20–31 window will have many deploys.
**Fix:** add `header Cache-Control "no-cache"` to every response by default in the site block (ETags
keep it cheap). Keep long caching only for content-addressed files. Separately, `/shared/fonts/*` is
`immutable` for a year but the names carry no version (`MutisScript-Regular.woff2`): rename them with
a version or content hash, or drop `immutable`. It also caches a **404** for a year (live:
`/shared/fonts/nope.woff2` → 404 with `immutable`). Apply the header only on success, or override it
in `handle_errors`.

### H4. `/evidence.json` publishes `decoys_today`, which lets anyone compute real relay volume
`deploy/scripts/collect-evidence.py:72` and `web/site/pages/judges.html:104` ("Decoy sends today"). The
sponsor's transaction graph is public (spec §10.2), so a chain observer counts every mutis-shaped send
per day. It then subtracts `decoys_today` and the canary deliveries, which `/evidence.json` also lists,
and gets the exact number of real sends per day, hourly as the file refreshes. `/security.html:71`
offers "decoy sends" as the mitigation against that observer. Kinkajou will connect the two pages.
**Fix:** remove the field; the spec listed it in §15.6, so patch the spec. On `/judges`, show
"Decoy sends: on, about one every {decoy_mean_gap} min" from `/config` instead of a count.

## Medium

### M1. `evidence.json.wasm_sha256` reports the pinned constant when no sidecar ever reported
`collect-evidence.py:67`: `sidecar.get("wasm_sha256") or PINNED_WASM`. The live file shows the hash
today, although mutis-chain has never run. Evidence must record what was observed. **Fix:** publish
`null` until the sidecar's `hello` reports a hash; if the expected value is wanted too, add
`wasm_sha256_pinned` as a separate field.

### M2. Pre-migrate DB copies outlive the published retention (claim C5-db)
`mutis-admin migrate` runs on **every** activation and writes `data/backup/pre-migrate-*.sqlite3`.
`backup.py:74` prunes these by count (keep 7), never by age. Ultron already has 5 copies from today,
two of them 0644. After the Nov 1 feature freeze, the last 7 copies stay until the server is gone.
`/privacy` and `/how` state "each copy is deleted after {db_backup_days}". Those copies hold
`wrapped_key`/`meta_ct` rows of links that later burned. **Fix:** in `backup.py db`, delete
`pre-migrate-*` older than `DB_BACKUP_DAYS` by mtime. Make `activate-release.sh` skip the copy when the
schema version doesn't change, and chmod copies 0600. Also remove orphaned `-shm`/`-wal` siblings: the
restore drill left `mutis-20261011.sqlite3-shm` beside the backup, and `prune` never deletes those.

### M3. D-02's relay check can't see where a destination would really leak, and `/how` claims "never stores"
`/how` says relay mode "Sees, never stores: … the destination Tari address of every send, the sealed
125-byte blob". Our relay **is** walletd, and walletd keeps `transactions.transaction_json`,
`wallet_events.event_data` and `transaction_requests` forever in `wallet.sqlite`.
`mutis-backup-wallet` copies that database daily and keeps 7 copies. Two gaps follow:
- `test_logs.py` searches only the journal and `/var/log` for the **bech32** address. walletd logs and
  stores keys as hex.
- No relay send with a memo has happened yet. The backup copy I inspected has 0 `otl_esm_`/`/t#`
  hits, but that is not evidence either way.

**Fix:** in `test_logs.py --relay`, add needles for the destination's owner and view public keys (hex,
from `ootle_addr`) and the memo blob in raw, hex and b64. Also search `/home/drive/wallet/esmeralda/data/wallet.sqlite`
(opened `immutable=1`) and `/home/drive/wallet/backup/`. If anything is found, either scrub it after
`wait_result` (only if walletd tolerates that) or change the `/how` and `/privacy` copy to "…and our
wallet's own database keeps the transaction it built".

### M4. A `Server: Caddy` header and an ERROR log line on several live error paths
Live probes:
- `http://…/how?x=1` (308) → `Server: Caddy`;
- `/status.json` (absent while health is off) → 404, empty body, `Server: Caddy`;
- `/evidence-archive-nope.json` → the same;
- `/es/nope` on the holding build → the same.

Root cause: `handle @status` sets `root * /srv/mutis/status`, `handle_errors` inherits it, `/404.html`
isn't there, and the error inside the error handler bypasses `header -Server`. It is logged at
**ERROR** ("error handling handler error"; four such lines from my probes, with no request fields).
That contradicts README §Logs "logged at DEBUG, so in practice nothing", and D-01 "no Server header".
**Fix:**
- put `root * /srv/mutis/app/current/dist` as the first line in `handle_errors`;
- add an explicit `http://{$MUTIS_HOST} { header -Server; redir https://{host}{uri} 308 }` (ACME
  challenges still work);
- add `/status.json`, `/evidence.json`, `/evidence-archive-x.json`, `/shared/fonts/x.woff2` and the
  port-80 response to `headers_spec.ROUTES`.

### M5. There is no staging, and `griefer.py` aims at production and leaves it degraded
E-23 is "staging only", but `--origin` and `--host` default to the production host, and no staging
instance exists. `--budgets` lowers **today's live** public courier/demo_pay slices and never restores
them. Every run leaves 200 lockers, 10 drops and real sponsor sends to random addresses. If it runs
near submission, our own test throttles the judge path for the rest of the UTC day.
**Fix:**
- run the lane, PoW and budget half against `mutis-api --dev` (fakes, tiny limits; spec §3.6) on
  ultron's loopback, as build, on another port;
- run only E-J against production;
- restore budgets with `budget set … clear` in `finally`, and take down what was created;
- refuse to run when `/api/v1/config` shows production-sized limits, unless `--production` is given.

### M6. Thread exhaustion of the judge path is untested (with the server)
`mutis-api` is thread-per-request with `TasksMax=256`. Caddy streams bodies (`read_body 120s`), so
about 250 slow chunk PUTs, each needing only an upload id, hold every API thread, and new requests get
502. Nothing caps concurrency per /64 (`server/mutis/api.py` `InFlight` only counts), and E-23 has no
slow-client case. **Fix:** raise `TasksMax` to about 2048 (idle Python threads cost little RSS). Add
`transport http { max_conns_per_host 200 }` so Caddy queues instead of overrunning the API. Ask the
server builder for a per-/64 in-flight cap, and add a slow-upload burst to `griefer.py` followed by an
E-J pass.

### M7. Any local user, `build` included, can reach 127.0.0.1:8787 and forge `X-Real-IP`
`build` compiles third-party Rust crates, whose `build.rs` runs arbitrary code. From loopback it can
claim any IP and bypass every per-IP limit and the PoW escalation. `deploy/ufw/README.md` documents
this as expected. **Fix:** add an owner-match guard on 8787 like the 5100 one, allowing `caddy`,
`drive` (the sidecar canary), root and lcam (the griefer tunnel). Add `build cannot connect to
127.0.0.1:8787` to `privilege-check.sh`.

### M8. Manifest notarization (P-9, kept by 12-integration §2) isn't wired, and chain admin commands can't work
`server` ships `mutis-admin notarize <sha256>`, but `deploy.sh` never calls it. The
`/usr/local/sbin/mutis-admin` wrapper always runs as `mutis`, which the 5100 guard rejects, so
`notarize` and `walletd-fixture` fail with a reset. **Fix:** route chain commands in the wrapper to
`drive` (spec §15.7). After a passing smoke test with `features.seallog` on, run
`notarize $(sha256 of the served manifest)` and append `{release, manifest_sha256, tx_id}` to
`/srv/mutis/status/releases.json` for `/security` to link.

### M9. `ootle.mirror_start_epoch = 0` in the live config
Spec §10.6 and §15.3 say "set at deploy". With 0, the mirror streams every unspent TARI UTXO in
Esmeralda's history, and every restored locker (E-08) scans all of it on a phone. The reset playbook
never resets it either: epochs restart after a reset, so a value set today would then hide the new
chain. **Fix:** add "set `mirror_start_epoch` to the indexer's current epoch" to README "Turning the
app on", and the same to reset-playbook §5.

### M10. The film isn't built
§18.3 says judges meet the Bluesky video first, and §18.1 #9 lists it in the definition of done.
12-integration §1 skipped the `/film` **page**; NOTES skipped `tools/film.py` as well. E-J already
drives an iPhone-sized and a desktop context. **Fix:** ask the integrator to decide explicitly. If it
stays in: `Page.startScreencast` in `cdp.py` during E-J, and ffmpeg `hstack` + `drawtext` with the
**Mutis Script** TTF (spec §18.5 says Inter, which 12-integration §2 dropped). It's about 150 lines.

### M11. `deploy.sh` gates on tests run with Python 3.14 on the jarvis box
`deploy.sh:56` runs the server suite locally, with 3.14 and its `sys.stdlib_module_names` for lint.
Production is 3.13 (12-integration §4: "the authoritative test run is on ultron"). The smoke test
checks only the API, never `mutis-chain`. **Fix:** in `activate-release.sh`, before the switch, run
`python3 -I -m unittest discover -s server/tests` from the unpacked release as `build`, in a scratch
copy. In smoke, also require `meta.chain_heartbeat` to be younger than 60 s when mutis-chain is enabled.

## Low

- **L1. `test_logs.py:169` reads `robot.json` (owner_sk, view_sk) onto the jarvis box** to learn a
  public address. Read `robot_address` from `/evidence.json`, or print only `["address"]` on the
  server side.
- **L2. Lint gaps.** It misses `Function(` without `new`, `setHTMLUnsafe`, `parseHTMLUnsafe`,
  `createContextualFragment` and `srcdoc`; I checked each with `lint.js_problems`. Site pages have no
  Trusted Types, so `setHTMLUnsafe` would be a live sink there. Add the patterns and tests.
- **L3. The pinned wasm hash is duplicated in 5 files** (`build.py`, `activate-release.sh`,
  `init-keys.sh`, `collect-evidence.py`, `server/mutis/config.py`). `upgrade-drill.md` §1 says "build.py
  refuses to build until all of them agree", which is false: nothing compares them. Read the hash from
  `vendor/ootle-wasm-*/SHA256SUMS`, or add a test that they all agree, and fix the sentence.
- **L4. Acceptance statuses overclaim.**
  - D-01 should be "PASS (holding: `/` only live)" until M4 is fixed.
  - D-12 requires the log to be instantiated by `operator`. Mark it **WAIVED (G5 fallback)**, not
    PASS.
  - `run.py` prints `e2e: PASS` with 16 of 17 scenarios skipped. Add `--final`, which fails on any
    SKIP.
- **L5. verify-deploy portability, the Fox path.** It needs Python ≥ 3.11 (`tomllib`, `datetime.UTC`).
  macOS's system Python 3.9 fails at import. `write_text` in `build.py` emits CRLF on Windows, so every
  HTML file would differ. Fail early with a version message, write with `newline="\n"`, and state the
  requirement on `/security`.
- **L6. E-11 needn't stay partial.** Use a sidecar-made keypair (`newKeys`) as the "other wallet"
  recipient, send kind 4 to it, and open `/t#4…` with its `view_sk`. That tests the whole path without
  walletd's missing view-key export.
- **L7. The E2E safety-code check compares free text** (`dd-safety` vs `locker-safety`) and never
  asserts **12** emoji (12-integration §2). Compare the emoji graphemes only, and assert there are 12.
- **L8. The rehearsal archive is published.** `/evidence-archive-20261011.json` (empty) is listed in
  `/evidence.json`, so a judge reads it as a real reset. Delete it before going live.
- **L9. `upgrade-drill.md` §3** leaves a key-bearing wallet copy in `/var/lib/walletd-drill` if any
  command fails. Use `trap 'systemctl stop walletd-drill; rm -rf "$T"' EXIT`.
- **L10. Small inconsistencies.**
  - README says `backup.py` lives outside releases, but `mutis-backup.service` runs the release copy:
    there are two copies that can drift.
  - `flows.view_state` is dead code.
  - The reset playbook doesn't pause `seallog`, and the dead component will fail its checkpoints.
  - Caddy's app routes are a fixed list: if the app-ui builder follows 11-brand §10.4 `/key`, it 404s.
    Agree the list in NOTES.
  - `deploy.sh` leaves a 10-minute ControlMaster running after its trap deletes the socket dir; add
    `ssh -O exit`.
- **L11. `/home/drive/wallet/.keyring-pass` still exists.** "Nobody but root reads the keyring
  credential" is true of the file, not of the secret. Delete it once a root-only tar is confirmed to
  contain it.

## Blind spots a judge finds in five minutes

- A judge running `curl -I http://<host>/` or opening `/status.json` before health runs sees
  `server: Caddy` (M4).
- The live `/evidence.json` already claims a wasm hash, and lists an "archive", for a sidecar and
  a reset that never happened (M1, L8).
- No UI scenario has run. The first run against the real app is also the first proof of the selector
  contract, so plan a day for it.
- The E2E and griefer runs leave traffic in production's `/stats` and wall, the "real coarse data"
  the home page draws from. Take test items down after each run, or mark them excluded from stats.

---

## Builder response (deploy builder, fix pass, 2026-10-11)

Every high and medium item is fixed, M3 is answered with evidence (the claim holds), and every low
item is fixed except L11, rejected below. Evidence is in `deploy/evidence/2026-10-11-fix/`;
`deploy/ACCEPTANCE.md` has the updated statuses.

| Item | Response |
|---|---|
| H1 | **Fixed.** `tools/build.py` copies by allow-list: served extensions plus `LICENSE`, `NOTICE`, `SHA256SUMS`, `PROVENANCE.md` and `*.d.ts` (listed in the vendored `SHA256SUMS`). `test_only_served_types_reach_dist` puts a `REVIEW-devil.md`, a `NOTES-*.md`, a `.py`, a `.bak` and a `.ts` in `web/app/` and requires that the only Markdown in `dist/` is the two vendored `PROVENANCE.md`. |
| H2 | **Fixed.** A committed release is `<sha>-c<content id>`, the first 8 hex of SHA-256 over the build's file map, so a new origin or drop URL makes a new release (`test_content_id_names_what_is_served`). `activate-release.sh` leaves an id that is live alone when it serves the same files and refuses loudly when it doesn't. `deploy.sh` rolls back only when this run moved `current`. Live drill: `h2-drill.txt`. |
| H3 | **Fixed.** Every non-API route sends `Cache-Control: no-cache` (pages, app files, status files, site CSS/JS). Fonts get `public, max-age=86400`, not `immutable`: their names carry no version (12-integration §2 fixes the names, and they are the site builder's files), and a font has no SRI hash, so a stale one can only look old for a day. `handle_errors` sends `no-store`, so a 404 is never cached. `test_headers.py` checks caching on every route. |
| H4 | **Fixed** in `collect-evidence.py`: no decoy count, and no count of sends of any kind (the docstring says why). `web/site/pages/judges.html` and `web/site/js/judges.js` still show "Decoy sends today": they are the site builder's files, so it's request 1 to the site builder in NOTES, with the spec §15.6 patch for the integrator. |
| M1 | **Fixed.** `wasm_sha256` is what the sidecar reported, `null` until then. The pinned constant is gone from the collector (`EvidenceTest`). |
| M2 | **Fixed.** `backup.py` deletes every copy once it is 7 days old, by mtime: the daily copies, the wallet copies and `pre-migrate-*` (`KEEP_DAYS` equals the server's `DB_BACKUP_DAYS`, which `/config` publishes; a test enforces it). It chmods pre-migrate copies to 0600 (`activate-release.sh` does too, right after the migration), removes leftover `-wal`, `-shm` and `.part` files, writes each copy as one self-contained file (`journal_mode=DELETE`), and the restore drill opens backups with `immutable=1`, so it leaves nothing behind. Skipping the copy when no migration is pending belongs in `mutis-admin migrate`: request 2 to the server builder. |
| M3 | **Verified; the claim holds.** `test_logs.py --walletd-probe` makes one send exactly as the relay does, with the server's own `jobs.courier_memo` and `Walletd.stealth_transfer`, to a throwaway address the sidecar makes. It then searches the journal, `/var/log` and all of `/home/drive/wallet` (`wallet.sqlite` and its `-wal`, the logs, the daily backups) for the address, both public keys (hex and as JSON byte arrays) and the memo blob (base64url, base64, hex). Result: 0 hits (`walletd-probe.txt`). walletd keeps the transaction it built, but only in its on-chain form: a one-time stealth key and encrypted data. The `--relay` session now uses the same needles and places. The robot/receiver key backups are skipped by name, because they hold our own robot address by design. |
| M4 | **Fixed.** `handle_errors` sets its own root (the release), the `/es/` 404 falls back to `/404.html`, and an explicit `http://{$MUTIS_HOST}` block redirects with no Server header. `test_headers.py` now covers the status files, a font, a 404 through every route and the port-80 answer. Running it against the new local stack also found an issue the live API had never shown: `X-Content-Type-Options: nosniff, nosniff`, from Caddy and the API both. Fixed with `header_down -X-Content-Type-Options`. |
| M5 | **Fixed.** `griefer.py` never touches production. `tests/e2e/localstack.py` starts `mutis-api --dev` behind the production Caddyfile (paths and ports rewritten, loopback only, as build) and removes it afterwards. `--then-judge ORIGIN` runs E-J against the real site. |
| M6 | **Fixed differently.** Caddy 2.6.2 has no `request_buffers` (tried: "unrecognized subdirective"). Instead it buffers request bodies with `buffer_requests` and `max_buffer_size 6MB`, so a slow upload holds a Caddy goroutine, not an API thread. `TasksMax=2048`. I did **not** add `max_conns_per_host`: with slow clients it turns the thread limit into a queue every judge waits in. The griefer holds 300 slow uploads open through Caddy and counts the API's threads while it times `/api/v1/health` (`griefer.txt`, `griefer-slow.txt`: with buffering the API stays at 7 threads and answers in 0.21 s; with `--unbuffered` it climbs from 7 to 264 threads and a health request gets no answer in 20 s). A per-/64 in-flight cap is request 3 to the server builder. |
| M7 | **Fixed.** An owner-match guard on 8787 (root, lcam, drive, caddy) in `before.rules` and `before6.rules`, added idempotently by provision. `privilege-check.sh` checks that build and mutis are refused and caddy and drive get through. While the API is off it raises a stand-in listener, so the guard itself is what gets tested. |
| M8 | **Fixed.** The wrapper runs `notarize` and `walletd-fixture` as drive. With `features.seallog` on, `deploy.sh` calls `notarize-release.py` after a passing smoke test, which notarizes the SHA-256 of the served manifest and appends `{release, manifest_sha256, tx_id, at}` to `/releases.json` (now served). Linking it from `/security` is request 4 to the site builder. |
| M9 | **Fixed.** Live `ootle.mirror_start_epoch = 12140`, Esmeralda's epoch on 2026-10-11 (`check-config` ok). It is documented in README "Turning the app on" and in reset playbook §5, which also covers epochs restarting after a reset. |
| M10 | **Built.** I can't ask, so I took the conservative reading: 12-integration skips the `/film` page, not the film (§18.1 #9), and spec §18.5 gives the film to this builder. `tools/film.py` records a desktop and a phone with `Page.startScreencast` (frames saved and acked as they arrive), cuts the waiting, retimes each shot to its slot, and composes on ultron with ffmpeg: 1920×1080, 30 fps, H.264, `+faststart`, no audio, ≤ 25 MB. It uses the 11-brand §12.6 beats and captions (brand wins over spec §18.5's E-J beats and Inter; captions are in Courier Prime, whose renamed subset is Mutis Script) and ends on the lockup card. `--demo` proved the pipeline on the holding page (`film-demo-poster.png`). The story itself needs the app: PENDING-INTEGRATION. |
| M11 | **Fixed.** `deploy.sh` runs the server suite, this suite, lint and check-copy on ultron as build with Python 3.13 before it builds. `smoke.py --chain` (added when mutis-chain is enabled) requires `chain_ok` in `/api/v1/stats`. |
| L1 | **Fixed.** Only `address`, `owner_pk` and `view_pk` leave ultron. |
| L2 | **Fixed**, with tests: `Function(` in any form, `setHTMLUnsafe`, `parseHTMLUnsafe`, `createContextualFragment`, and `srcdoc` as a property or attribute. The bare word `srcdoc` is allowed, because `web/app/lib/dom.js` names it in its block-list. |
| L3 | **Fixed.** `PinnedWasmTest` requires every copy to agree with `SHA256SUMS` (build.py, both shell scripts, the server's config). The upgrade-drill sentence now says what enforces it. |
| L4 | **Fixed.** D-01 is now backed by both the live holding page and a full build on the local stack, and is stated per run. D-12 is WAIVED (G5 fallback). `run.py --final` fails on any SKIP, and without it a run with skips says so. |
| L5 | **Fixed.** verify-deploy stops on Python < 3.11 with a clear message, exports with `core.autocrlf=false`, and build.py writes LF. Saying "Python 3.11+" on `/security` is request 5 to the site builder. |
| L6 | **Fixed.** E-11's other wallet is a key pair the sidecar makes. The sidecar's `scan` reads the memo with the view key alone, and a fresh phone opens the `/t#4` link by pasting it. That last step needs `t-viewkey`/`t-viewkey-submit` (not in §3.4.9): request to app-ui. |
| L7 | **Fixed.** Safety codes are compared as emoji graphemes (`Intl.Segmenter` plus `\p{Extended_Pictographic}`, checked against all 256 of the alphabet), with exactly 12 required. E-10 also compares the send screen's code. |
| L8 | **Fixed.** The rehearsal archive is deleted from the live status directory, and `/evidence.json` is regenerated. |
| L9 | **Fixed.** An exit trap stops the drill unit and deletes the copy on every path. |
| L10 | **Fixed.** One installed `backup.py`, run by both units and refreshed by every activation. `flows.view_state` is gone. The reset playbook pauses and clears `seallog` and republishes SealLog. `deploy.sh` closes its ControlMaster. Caddy's app-route list is in NOTES for the app-ui builder to confirm (11-brand §10.4 mentions `/key`). |
| L11 | **Rejected.** The brief forbids deleting, moving or re-initialising `/home/drive/wallet`, and I read that conservatively as covering its contents. That file is the only copy outside root's credential store and the root-only tars. It is `drive` 0600, and drive can already read the wallet database the password protects, so deleting it gains nothing against any user who couldn't already read the wallet. The claim is reworded to what is true: "mutis, build and caddy can't read the keyring password; root's credential copy is root-only". |
| Found during this pass | Running the sidecar the way mutis-chain would, for the M3 probe, showed that it could never have started in production. Node's permission model resolves the `current` symlink and refused the sidecar its own files. `run-sidecar.sh` passes the real release path and is now the live `sidecar.command`; inside mutis-chain's own sandbox the sidecar answers `hello` and passes `selftest` (`sidecar-symlink.txt`). The local stack also caught the duplicate `nosniff` (M4 row). |
| Blind spots | The Server header and evidence findings are fixed. No UI scenario has run against the real app yet: that stays PENDING-INTEGRATION. E2E traffic on production does show on the wall for 7 days (the server counts every non-canary item). The griefer no longer touches production, and NOTES asks the integrator to choose between running E2E before launch and a server-side purge of test items. |
