<!-- SPDX-License-Identifier: MIT -->
# NOTES for the integrator (deploy builder)

Everything below ran on 2026-10-11 from the workstation and on the server (as operator with sudo, `build`
for the browser, `drive` for walletd, `mutis` for the database). Nothing from the workstation was
copied to the server except this repository's code; every key and secret on the server was made there.

## 1. State of the server when I stopped

| Thing | State |
|---|---|
| `https://srv2052606.hstgr.cloud` | live, Let's Encrypt certificate (90 days), Caddy with `deploy/caddy/Caddyfile`, serving the **holding page** (`deploy/holding/`): the full site doesn't build until `web/app/drop-widget.js` exists |
| Release | `/srv/mutis/app/current` → `releases/641c91808ab6-dirty-20261011190904` (a working-tree build of this pass; 5 kept) |
| walletd | `walletd.service` (enabled, hardened; tmux session gone); data untouched; backups in `/var/backups/mutis/` |
| L1 wallet | still in tmux `l1` (deliberately: see deploy/README.md "Day to day") |
| ufw | 22 limit, 80 and 443 open, logging off, owner-match guards on 5100, 18143 and (this pass) 8787 |
| Enabled | `walletd`, `caddy`, `mutis-backup.timer`, `mutis-backup-wallet.timer` |
| Installed, **off** (yours to enable) | `mutis-api`, `mutis-chain`, `mutis-cleanup.timer`, `mutis-health.timer`, `mutis-evidence.timer` |
| Database | migrated (schema 2 since the server builder's migration), **test data only**: the 21 items and 7 drops of my D-02 runs, all taken down; mutis-api was started for each run and stopped again. Removed items stay as 30-day tombstones and `/api/v1/stats/wall` draws from the last 7 days, so they would show on the home page's wall. Requests below: start the database fresh before go-live |
| Keys | `/home/drive/mutis/receiver.json`, `robot.json` made by the sidecar's `newKeys`; `/etc/mutis/secret.key` made on the server |
| walletd accounts | `service` 16.29 public + 72.27 stealth; `sponsor` 8,900 stealth; `operator` 2.30 public; `buyer-demo` 3.5 stealth |
| SealLog | template and log published; owned by `service` (G5 failed); in `/etc/mutis/mutis.toml`; `features.seallog` still false. One manual `notarize` of the drill release's manifest committed (`evidence/2026-10-11-fix/notarize.txt`) |
| Live config changes this pass | `ootle.mirror_start_epoch = 12140` (Esmeralda's epoch on 2026-10-11); `[sidecar] command = ["/usr/local/lib/mutis/run-sidecar.sh"]` (see request 1). Copies of the previous file in `/var/backups/mutis/mutis.toml-*` |
| Installed helpers | `/usr/local/lib/mutis/{run-walletd.sh, run-sidecar.sh, backup.py}`, `/usr/local/sbin/mutis-admin` |

To turn the app on: decide the gates in `/etc/mutis/mutis.toml` (the app builder's notes say G1
passed → `send_mode = "direct"`, `features.direct_send`; `amount_proof = "sidecar"` now that the
sidecar runs in mutis-chain's sandbox through the wrapper), check `mirror_start_epoch`,
`sudo mutis-admin check-config`, then `systemctl enable --now mutis-api mutis-chain
mutis-cleanup.timer mutis-health.timer mutis-evidence.timer`, `deploy/scripts/deploy.sh <ref>`
(the smoke test then also requires `/api/v1/health` and `chain_ok`) and the tests in
deploy/README.md "Turning the app on".

## 2. Decisions I made (conservative, with the reason)

| Topic | Decision | Why |
|---|---|---|
| E2E orchestration | `tests/e2e/run.py` runs on the workstation (or as operator on the server with `--local`) and drives Chromium on the server **as build** through `relay.py` over ssh | spec §17.1 says "run.py on the server as build", but several scenarios need admin steps (takedown, tamper, freeze, canary-now) and `build` must never get sudo; the browser still runs as build on the server |
| D-02 method | the scripted session runs over IPv6 (never used for SSH) and IPv4; IPv4 hits in sshd/wtmp/lastlog are reported as operator access, not failures | the operator's SSH login is logged by sshd like on any server; visitor traffic is what the claim is about |
| walletd keyring password | systemd `LoadCredential` from `/etc/mutis/credentials/walletd-keyring-pass` (root 0600) → a private config copy in `/run/walletd` (0700, tmpfs) with `override_keyring_password` as a byte array (walletd 0.45 reads it as bytes); only bash builtins touch it | not on any command line; tested in a no-network copy first |
| walletd logs | `--log-config /etc/mutis/walletd-log4rs.yml`: warnings only, journal only, no files | its default debug files record every transfer; spec §14.3 |
| L1 wallet | no unit | it's a TUI used only for the human-checked burn; nothing depends on it |
| Port 18143 | added the same uid guard as 5100 | the L1 wallet's gRPC has no auth; mutis or build could otherwise spend the L1 reserve |
| Caddy admin | on `unix//run/caddy/admin.sock` (0700) instead of 127.0.0.1:2019 | the TCP admin API is unauthenticated: any local user could reconfigure the web server |
| HTTP/3 | `protocols h1 h2` | ufw opens 443/tcp only |
| CSP on non-page responses | the site CSP on everything that isn't an app route (API JSON, files, errors) | every response carries a strict policy; §14.2 lists headers for "all responses" |
| `{{NETWORK}}` | display case (`Esmeralda`) | it's used in copy |
| `{{BUILD_DATE}}` | the commit date, not the build time | builds of one commit must be byte-identical for verify-deploy |
| `{{SECURITY_DROP_URL}}` | `{{ORIGIN}}/abuse` while `security_drop_url` is empty | 12-integration §1 |
| Served vendor copies | `dist/app/vendor/` (the app imports `../vendor/…`) and also `dist/vendor/` (spec §3.3) | the spec's path and the app's both work |
| P-20 (2) allowlist | `tools/copy-allowlist.txt` holds **phrases** (format constants), not i18n keys | stricter (a key can't smuggle other numbers) and needs no list of the app's keys; add phrases there when copy needs another constant |
| P-20 (3) exemptions | text inside `data-v` bindings (the no-JS fallback) and the exit wall's `data-cue` labels; allowlisted constants | otherwise the wall's sample "3 views" labels and "4 MB chunks" fail |
| SQLite umask | every process that opens the database uses umask 007 (units, scripts, `sudo mutis-admin` wrapper, activation) | found in the reset rehearsal: a database or `-shm` file made with umask 022 is read-only for the other users of group mutis |
| Funding | `sponsor` 8,900 tTARI stealth (spec §10.2); `operator` then `service` for SealLog | see deploy/ootle/setup-accounts.md |
| Test data | my D-02 sessions' items and drops were taken down with `mutis-admin takedown` | they no longer open; their tombstones remain (request 4) |
| Font pipeline | no `tools/subset-fonts.sh`: the site builder owns it (`web/site/tools/subset-fonts.sh`, `rename-font.py`); the P-18 check that fails on any OTS error is `tests/e2e/test_fonts.py` | one copy of the pipeline; the check runs against what is actually served |
| The film | `tools/film.py` built and its pipeline proven (`--demo`); the 40 s story waits for the app | 12-integration §1 skips the `/film` **page**, not the film, which spec §18.1 #9 and §18.5 give to this builder. 11-brand §12.6 decides beats, captions and layout (desktop left, phone right), so the captions use Courier Prime (Mutis Script is its renamed subset), not spec §18.5's Inter |
| Release ids | `<sha>-c<first 8 hex of sha256 of the build's file map>` for a committed ref | the same commit built with a new origin or drop URL must be a new release, not a silent no-op followed by a rollback (REVIEW-devil H2) |
| Caching | every page, app file and status file `no-cache` (ETag revalidation); fonts `public, max-age=86400`; errors `no-store` | a page cached by heuristics could outlive a deploy with an SRI hash its new script no longer has; font names carry no version, so not `immutable` (spec §15.2 assumed versioned names) |
| Request bodies | Caddy `buffer_requests` with `max_buffer_size 6MB` (2.6.2 has no `request_buffers`); mutis-api `TasksMax=2048`; no `max_conns_per_host` | a slow upload then holds a Caddy goroutine, not an API thread (griefer: 300 slow uploads, API threads unchanged); a connection cap would make every judge wait behind slow clients |
| Port 8787 | owner-match guard: root, operator, drive, caddy | mutis-api believes `X-Real-IP` from loopback; `build` runs third-party build scripts |
| E-23 | only on `tests/e2e/localstack.py` (`mutis-api --dev` behind the production Caddyfile, as build, loopback, removed afterwards) | there is no staging, and the griefer used to lower production's budgets and leave its items behind |
| Deploy gate | unit tests, lint and check-copy run on the server as `build` (Python 3.13) before the build | 12-integration §4: the authoritative run is on the server |
| Backups | one installed `backup.py` for both units; every copy (pre-migrate too) deleted at 7 days, 0600, no side files | the published `db_backup_days` must be literally true |
| `decoys_today` | dropped from `/evidence.json` | with the canaries listed there, it lets a chain observer subtract its way to the real send count |
| The sidecar's start | `/usr/local/lib/mutis/run-sidecar.sh` as `sidecar.command` | Node's permission model resolves the `current` symlink and refused the sidecar its own files (request 1) |

## 3. Requests

### Integrator

1. **P0, found this pass:** with `sidecar.dir = /srv/mutis/app/current/sidecar`, mutis-chain could
   never start its sidecar: Node's permission model resolves the `current` symlink and refuses the
   sidecar's own files (`evidence/2026-10-11-fix/sidecar-symlink.txt`). The live config now uses
   `sidecar.command = ["/usr/local/lib/mutis/run-sidecar.sh"]`, which passes the real release path.
   Inside mutis-chain's own sandbox the sidecar answers `hello` with the pinned wasm and passes its
   `selftest`. The server builder may prefer `os.path.realpath` in `Config.sidecar_argv` (server
   request 4); the wrapper stays harmless either way.
2. **Decide before go-live:** start the database fresh, so the wall shows no test items: stop
   mutis-api and mutis-chain, move `/srv/mutis/data/db/mutis.sqlite3*` to `/var/backups/mutis/`
   (root, 0600), `sudo mutis-admin migrate`, start both again, and run the E2E suite before that,
   not after. Otherwise test items stay on the wall for 7 days.
3. **Spec patches (this pass):** §15.6 drop `decoys_today` from `/evidence.json`; §15.2 fonts
   `max-age=86400` (names carry no version) and `no-cache` on pages; D-12 is WAIVED under the G5
   fallback; §17.2 E-23 runs on the local stack, never production; §18.5 the film follows 11-brand §12.6.
4. **Spec patches (first pass):** §17.1 (where run.py runs, above); §10.2 and §15.3 (`operator_account = "service"`
   because G5 failed; record the G5 answer in §20); §16.5 D-01 tests the hstgr host until the domain;
   P-20 allowlist by phrase; D-02's operator-SSH note.
2. **docs/evidence:** copy `deploy/evidence/2026-10-11/` (text outputs with my machine's addresses
   redacted, and the holding-page screenshots).
3. **Privacy ledger and `/security`:** SealLog is owned by the same `service` account that holds our
   public tTARI (G5 fallback). The research log `component_32dae273…7e36e` is not ours to use.
4. **Incident to record:** during the first walletd trial, walletd rejected a config value and printed
   it, so the testnet wallet's keyring password appeared once in the server's journal (purged within
   minutes with `journalctl --rotate --vacuum-time=1s`; a grep of the journal and `/var/log` then found
   nothing) and in this build session's transcript on the workstation. walletd 0.45 has no way to change
   it. It only unlocks the testnet wallet database, which never leaves the server; a mainnet wallet would
   be new and get a new password.
5. **A slip, fixed:** a probe of `accounts.create_or_get` with empty parameters created an unnamed
   local account (key index 3, nothing on chain); I renamed it `operator` and used it as planned.
6. `/home/drive/wallet/.keyring-pass` stays (drive 0600). Deleting it would break the brief's rule
   about `/home/drive/wallet`, and it protects nothing from drive, who can already read the wallet
   it unlocks (REVIEW-devil L11).
7. **The film:** `python3 -I tools/film.py` once the app is live renders `film/film.mp4` and
   `poster.png` (about 40 s, ≤ 25 MB). Owner review, then the Bluesky upload (Tier 3). Re-render is the
   same command.
   Please add `film/` to the root `.gitignore` (the default output folder), so a render isn't
   committed by accident.
8. `features.seallog`: with it on, every `deploy.sh` notarizes the served manifest and appends it to
   `/releases.json` (P-9, claim C10). Until it's on, C10's "release hashes notarized on the Ootle"
   isn't true per release; `/security` doesn't show it today.

### Server builder

1. `mutis-admin takedown` (and every command taking an id): a base64url id may start with `-`,
   which argparse reads as an option (`error: the following arguments are required: id`). Callers can
   pass `--`; better, declare the id with a type that accepts it or document `--` in the help.
2. `mutis-admin migrate` creates the database with the caller's umask (it was 0644 from a root shell);
   deploy now runs it with umask 007, but `bin/*` could set `os.umask(0o007)` themselves. The
   `pre-migrate-*.sqlite3` copies are 0644 inside a 0700 directory and are never pruned
   (`deploy/scripts/backup.py db` now prunes them to 7).
3. The chain worker's SealLog calls use `ootle.operator_account`; with walletd 0.45 that must be
   `service` (G5). Set in the live config already.
4. `Config.sidecar_argv()`: resolve `sidecar.dir` with `os.path.realpath` (integrator request 1).
   The live config works around it with `sidecar.command`.
5. `mutis-admin migrate`: skip the pre-migrate copy when no migration is pending, and create it 0600.
   Deploy chmods it, and backup.py deletes it at 7 days, but every no-op deploy still writes one.
6. A per-/64 cap on requests in flight in `api.py` (`InFlight` only counts): with Caddy now buffering
   bodies, slow uploads no longer hold threads, but slow downloads still can, up to `TasksMax=2048`.

### App-ui builder (E2E selectors beyond §3.4.9 that the scenarios rely on)

1. Brand P-15 (key passphrase on by default): E-08 restores by pasting the key file's text into
   `restore-text` and pressing `restore-submit`. If a passphrase is asked for, please add
   `key-passphrase` (when saving) and `restore-passphrase` (when restoring).
2. Wrong password: E-04 recognizes the 11-brand text "That's not it." inside `view-root`.
3. `needs_wasm` (A-09, E-24): an element with `data-code="needs_wasm"`.
4. `/inbox`: E-09 opens a delivery by clicking the first `button` or `a` inside
   `[data-testid="inbox-item"]`.
5. E-05 needs a 60-second `expiry-preset` on staging (spec §17.1); without it the scenario skips.
6. `drop-link` may be an input or text; both are read.
7. E-11: the `/t#4…` "Use a view key instead" paste field and its button as `t-viewkey` and
   `t-viewkey-submit` (not in §3.4.9); without them E-11 opens everything except that last step and
   reports SKIP.
8. Caddy rewrites only these app routes to `app.html`: `/d/*`, `/locker*`, `/inbox*`, `/send*`,
   `/watch*`, `/upgrade*`, `/verify*` (and `/s/*`, `/t` to `view.html`). If the app uses another path
   (11-brand §10.4 mentions `/key`), tell me or the integrator so the Caddyfile and
   `headers_spec.ROUTES` add it.

### Site builder

- `/shared/fonts/NOTICE` has no extension; Caddy now serves it as `text/plain` (rule in the
  Caddyfile). The home page can't build until `/app/drop-widget.js` exists (SRI); that's expected.
1. **Remove "Decoy sends today"** from `pages/judges.html` (`data-ev="decoys"`) and `js/judges.js`
   (`ev.decoys_today`). `/evidence.json` no longer has it, because it let anyone compute the real send
   count. If you want a line, "Decoy sends: on, about one every {decoy_mean_gap} min" from `/config`
   reveals nothing.
2. `/evidence.json` `wasm_sha256` is now `null` until the running sidecar reports its hash: show
   "not reported yet" rather than a value.
3. `/security#verify`: say "Python 3.11 or newer"; verify-deploy now stops with that message on older
   ones.
4. `/security`: once `features.seallog` is on, link `/releases.json` (`[{release, manifest_sha256,
   tx_id, at}]`, served with the site CSP and `no-cache`) for C10's "release hashes notarized on the
   Ootle". Until then, keep the claim off the page (it is off today).
5. Fonts are cached for a day (not `immutable`), because their names carry no version. If you want
   long caching, version the file names (e.g. `MutisScript-Regular.v2.woff2`) and tell me.

## 4. Open risks

- **D-04 reboot drill** not run (a reboot would interrupt the other builders on the server).
- **ACME renewal over HTTP** with the explicit `http://` block (added so the redirect sends no
  Server header): Caddy answers HTTP-01 challenges before routes and also uses TLS-ALPN-01 on 443,
  but renewal (due around Dec 10) can't be tested before it happens. `journalctl -u caddy | grep -i
  certificate` after the first renewal window.
- **E2E on production leaves items on the wall** for 7 days (integrator request 2).
- **D-08** depends on the app UI; the scenarios are written against the contract and the driver is
  proven, but every UI scenario still has to pass once against the real app.
- **D-06** needs three calendar days of timer runs (day 1 done).
- **Esmeralda resets:** the reset playbook is rehearsed except the burn, which needs a human.
- **Budgets:** worst case ≈ 230 tTARI/day across all slices; sponsor holds 8,900. SealLog at the
  ratified 15-minute cadence ≈ 0.50 tTARI/day from `service` (16.29 public now): about a month, so a
  top-up before November (§5).

## 5. Integration pass (2026-10-11)

Every request aimed at `deploy/`, `tools/` or `tests/e2e/` in the builders' NOTES, NOTES-ui and the
reviews' builder responses, and every 12-integration §7 ratification that touches them. Nothing on
production changed: no deploy, no config edit, no transaction (only dry runs, and the throwaway local
stack as build). Evidence: `evidence/2026-10-11-integration/`.

### Integration responses

| From | Request | Change | Test |
|---|---|---|---|
| site §1.6, site §6 deploy 1 (review H3) | `/es/` needs the app CSP | Caddyfile `@home path / /index.html /es /es/ /es/index.html`; `/es/` and `/es/how` in `headers_spec.ROUTES` | `test_config.test_both_home_pages_get_the_app_policy`; `test_headers.py --local hidebox` 35 PASS (`test_headers-local.txt`) |
| site §1.13, site §6 deploy 2 (review M11), 12-integration §7.5, §7.6 | set the copy variants at build time | `build.py` runs the site's `tools/variants.py` on the copied pages before includes and placeholders (it also rewrites `llms-full.txt`); the build takes the parsed config, and the manifest records the config tables the variants read (`variant_config`: `gates`, `features`, `hosting`) | `test_build.test_copy_variants_follow_the_config`, `test_a_site_build_needs_the_variants_tool` |
| (follows from the above) | verify-deploy must rebuild the same pages | it writes the live manifest's `variant_config` into the rebuild's config (plain names and scalar values only; anything else a manifest carries is dropped), not `/config`'s runtime `features`, which `mutis-admin feature` can change without a rebuild | `test_verify_deploy.BuildConfigTest` |
| site §1.5, site §6 deploy 3 (review M7) | the sitemap's Spanish home is `/es/` | sitemap URLs come from the page's source name (`index` → a directory URL with its slash) | `test_build.test_sitemap_skips_404_and_noindex` |
| NOTES-ui (app review M9) | don't serve `web/app/shots` | `build.py` never copies `web/app/shots` or `web/app/ui/tests` (`web/site/shots` was never copied) | `test_build.test_test_evidence_is_never_served` |
| NOTES-ui 1 | count or expiry changes keep the link | `flows.set_rules` waits for the card's `data-rule` counter and returns the link, same or new | first run against the app (D-08) |
| NOTES-ui 2 (brand P-15) | key passphrase on by default | E-08 fills `key-passphrase`, checks the file holds `Locked key:`, restores with `restore-passphrase`; the passphrase is a registered secret for E-03 | first run against the app |
| NOTES-ui 5, server §7 deploy 3 | E-05: the 60 s preset, not `when=expires` | E-05 picks `expiry-preset` = `/config.e2e_expiry_s` and waits that long + 5 s, or skips; tests/e2e/README says how to turn it on for the run only | first run against the app |
| app-core deploy 6, 12-integration §7.5 | E-J in direct mode: two contexts on one /64, the cold start recorded | in direct mode E-J makes a judge pass (`judge-pass new --uses 3`), gives it to both contexts (sessionStorage `mutis.judge`, as `/judges` keeps it), measures from the locker opening until the browser wallet can pay (a fresh scan; `report.json` notes), requires that by step 5 (3:15), and checks step 5's payment was a browser `POST /api/v1/chain/ix/transactions` | `test_harness.py`: the pass is in the tab before its scripts run (18/18); E-J itself on its first run in direct mode (go-live gate) |
| site §1.11 | health check names the status page labels | checks are `https api chain_worker walletd sponsor_balance mirror canary credits disk budgets`: the verifier sidecar is part of `chain_worker` (`sidecar_down`), `credit_freeze` and `payments` became `credits`, an unreadable database turns `chain_worker` red, and `budgets` is new (amber at 90 %) | `test_ops.HealthTest.test_check_names_are_the_ones_status_labels` and the rest of `HealthTest` |
| server §3 deploy 10 | `reconcile_unknown ≥ 3` is an alert apart from a freeze | `credits` amber, detail `indexers_unreachable` | `test_ops.HealthTest.test_payments_the_indexers_cant_confirm_are_amber` |
| server §3 deploy 1, §7 deploy 1 | schema 3; stop mutis-chain for the migration | `activate-release.sh` stops mutis-chain (when active) around `mutis-admin migrate`, starts it again if the migration fails, and the restarts after the switch start it as before | `bash -n`; next deploy |
| server §7 deploy 2, 12-integration §7.6 | `amount_proof = "sidecar"` | `mutis.toml.example` (with `[seal_log] checkpoint_interval_s = 900` and `[budgets.evidence]`, server §3 deploy 9); the live `/etc/mutis/mutis.toml` is a go-live step (README "Turning the app on" 1), not changed now | `test_config.test_example_parses_with_the_server_config` |
| server §7 deploy 5 | `/evidence.json` names the chain's checkpoint number | `seallog.latest_checkpoint` = `{index, component, tree_size, tx_id, epoch}`, `index` = `seal_checkpoints.chain_index`, only checkpoints of the live component | `test_ops.EvidenceTest.test_seallog_names_the_live_log_its_chain_index_and_the_retired_ones` |
| template §1.5, 12-integration §7.2 | list the retired logs | `seallog.retired` = the 1.0.0 log `component_0ff7e892…22aa` and the research log `component_32dae273…e36e` | same test |
| template §1.1, §1.2, 12-integration §7.2 | publish 2.0.0's exact bytes | `publish-template.sh` builds the transaction itself (one `PublishTemplate`, the binary as its blob, `pay_fee` from `service`) for `transactions.submit_dry_run` / `transactions.submit` with `seal_signer` = the `service` key id; prints the address `wasm_check.py address` predicts, and after a publish runs `wasm_check.py onchain` | dry run: `Accept`, 755,531 µT, `template_40c5f1cf…0a47`, the chain's copy byte for byte (`publish-dry-run.txt`) |
| template §1.3 | wire `check.sh --onchain` into verify-deploy | when `/config.seal_log.component` is set, verify-deploy reads the log's template address from indexer-a and runs the tag's `template/wasm_check.py onchain` (what `check.sh --onchain` runs, without needing bash); both addresses must be 64 hex characters (they come from the live site and an indexer); a mismatch is a difference | `test_verify_deploy.test_no_seallog_no_check`, `test_a_component_that_isnt_an_address_is_a_difference`; tried on the retired 1.0.0 log: "different bytes", as it should |
| template §1.4, §1.5, 12-integration §7.2 | new log, header check, retire, top up `service` | `ootle/setup-accounts.md` §4 (go-live steps, the header check command, budget at 900 s), README "Turning the app on" 3, reset playbook §4 | — |
| 12-integration §7.7 | E2E against production before the fresh database | README "Turning the app on" 4–5; tests/e2e/README "Against production" (when, the hourly locker limit, E-05) | — |
| 12-integration §7.4 | claim registry | nothing in these directories states the changed claims (C9, C11, C13, Lock 1, takedown scope, C22, the memo bound); the film's "(Then it leaves. On the record.)" is SealLog's C7, so `film.py` now drops "On the record." while `features.seallog` is off | lint |
| app-core deploy 4 | compress `/api/v1/chain/utxos` | already true: the site-wide `encode zstd gzip` matches `application/json*`, so API JSON through Caddy is compressed (`/api/v1/config`: zstd on the local stack); no change | `test_headers-local.txt` |
| app-core deploy 1, 2, 3, 5; site §1.1–§1.4, §1.7–§1.10, §1.15; server §3 deploy 2–8, 11 | | already done in the build and fix passes (sidecar release layout, lint allowances, `application/wasm`, the served-file allow-list, includes, placeholders, `.well-known`, JSON-LD, SRI, font caching, `X-Real-IP`, body size, accounts by name) | existing tests |
| server §7 deploy 4 | `run-sidecar.sh` is optional now | kept as `sidecar.command`: it is what mutis-chain's sandbox was proven with (`evidence/2026-10-11-fix/sidecar-symlink.txt`) and E-11 runs the release's sidecar through it; with the server resolving `sidecar.dir` itself, `dir` alone would also work | — |
| found in this pass | `test_headers.py --local` couldn't build: the build's lint resolves `web/app/ui/tests/devserver.py`'s import of the server package, and the stub copy had no `server/` | `localstack.stub_build` copies `server/` next to `web/` | `test_headers.py --local hidebox` PASS |

**Not applied: template §1.7** (one dry run creating the log signed by `operator`, a G5 retry).
12-integration §7.3 settled that `service` writes SealLog, and the site's ratified `/security` lines
name it. Moving the writer to `operator` would need every append the chain worker makes to carry a
seal-signer key id (a server change) and new copy. For later: walletd 0.45's
`transactions.submit_manifest` takes `seal_signer_key_id` and `signing_key_ids` (its own web UI sends
them), and `transactions.submit` takes `seal_signer`; the earlier G5 probe tried other field names.

### Integration requests

**Go-live operator** (README "Turning the app on", in order): the config (`amount_proof = "sidecar"`,
`send_mode = "relay"`), the units, the tag; SealLog 2.0.0 from the committed `template/dist/seal_log.wasm`
(`publish-template.sh check`, `publish`, `instantiate`, the header check, `seallog_component`,
`features.seallog = true`, deploy again); the E2E in batches an hour apart (5 new lockers per network
an hour), E-05 with `e2e_expiry_s = 60` for its run only; the fresh database; `verify-deploy` against
the tag. E-J in direct mode is the gate for `send_mode = "direct"`.

**Owner (Tier 3, human step):** `service` pays the 15-minute checkpoints (≈ 0.50 tTARI a day) and has
16.29 tTARI public, about a month after the publish and the log. Before November, burn tXTM from the
L1 wallet so the claim lands in `service` (reset-playbook §3). `sponsor`'s stealth tTARI can't be
moved into a public vault with `accounts.transfer` (dry run: "vault not found").

**Server builder:** report `service`'s public balance in `meta.chain_status` (e.g.
`service_public_ut`), so the healthcheck can turn amber before SealLog can't pay its checkpoints.
Until then the fallback is `walletd-rpc.py balances` once a week (setup-accounts §4).

**Template builder:** the dry run and the predicted address are for `seal_log.wasm` sha256
`9af71aa2…d6f2`. If 2.0.0's bytes change before go-live, the address changes with them;
`publish-template.sh check` prints the new one.
