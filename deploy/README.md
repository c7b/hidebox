<!-- SPDX-License-Identifier: MIT -->
# mutis deploy: operator runbook

Everything that turns this repository into the running service on the server (Debian 13, one VPS): the
build, the web server, the units, the wallet daemon's supervision, backups, health, evidence, the
playbooks and the end-to-end tests. Python standard library, bash and Debian packages only; nothing
is installed from npm, pip or a CDN.

The commands below reach the server as `ssh hidebox`: `hidebox` is its SSH alias in `~/.ssh/config`.
The scripts and the E2E tools take `--host`, else the `MUTIS_SSH_HOST` environment variable, else `hidebox`.

```
deploy/caddy/Caddyfile              TLS, the spec §14.2 headers and CSPs, routes, caching; no access log
deploy/systemd/                     walletd, mutis-api, mutis-chain, timers (cleanup, backups, health, evidence)
deploy/journald/mutis.conf          7-day journal
deploy/config/mutis.toml.example    /etc/mutis/mutis.toml (every key the server accepts)
deploy/holding/                     the page served until the full site builds
deploy/scripts/                     provision, deploy, activate-release, rollback, notarize-release,
                                    demo-gone (the judges' burned demo secret), backup, healthcheck,
                                    collect-evidence, init-keys, privilege-check, mutis-admin (wrapper)
deploy/ootle/                       run-walletd.sh, walletd-log4rs.yml, walletd-rpc.py, publish-template.sh,
                                    setup-accounts.md, reset-playbook.md, upgrade-drill.md
deploy/ufw/README.md                the firewall
tools/                              build.py, lint.py, check-copy.py, verify-deploy.py, film.py
tests/e2e/                          the E2E suite, the griefer and the local stack (README there)
```

## Tests, one command

```sh
python3 -I -m unittest discover -s deploy/tests        # about 3 s, no network
```

They cover the build (the served-file allow-list, layout, copy variants from the config, includes,
placeholders, SRI, vendored hashes, lint gate, sitemap, manifest determinism, content ids, holding
mode), the lint and copy rules, verify-deploy's comparison and rebuild config, backups (age-based retention equal to the published
`db_backup_days`, no side files) and the restore drill, the healthcheck's reaction to every D-07
failure, the evidence collector's privacy rules, the walletd start script, the config example against
the server's schema, the Caddyfile against spec §14.2 (and its caching and error pages), every copy
of the pinned wasm hash, and the systemd hardening. Against the server (from the workstation):

```sh
python3 -I tests/e2e/test_headers.py                    # D-01 (add --holding while the holding page is live)
python3 -I tests/e2e/test_headers.py --local hidebox     # D-01 on a throwaway stack: the Caddyfile with a full build
python3 -I tests/e2e/test_privileges.py                 # D-03, D-11, from inside and outside
python3 -I tests/e2e/test_logs.py                       # D-02 (needs mutis-api running; restarts it once)
python3 -I tests/e2e/test_logs.py --walletd-probe       # what walletd keeps of a relay send (no API needed)
python3 -I tests/e2e/test_fonts.py                      # 11-brand P-18: no OTS errors in Chromium
python3 -I tests/e2e/griefer.py [--slow-only]           # E-23 on a throwaway stack, never production
python3 -I tests/e2e/run.py [--chain] [--final]         # the §17 scenarios (tests/e2e/README.md)
python3 -I tools/verify-deploy.py https://hidebox.app <tag>              # D-09 (and the SealLog template on chain)
```

## The server

| Path | Owner, mode | What |
|---|---|---|
| `/srv/mutis/app/releases/<id>/` | root 0755 / 0644 | `dist/` (served), `server/`, `sidecar/`, `deploy/`, `RELEASE` |
| `/srv/mutis/app/current` | root | symlink to the live release, switched by one rename |
| `/srv/mutis/app/history` | root | one line per activation (rollback reads it) |
| `/srv/mutis/data/` | mutis:mutis 2770 | `db/` (the database, 0660, shared with drive), `blobs/` (0700), `backup/` (0700), `health.json` |
| `/srv/mutis/status/` | mutis:mutis 2775 | `status.json`, `evidence.json`, `evidence-archive-*.json`, `releases.json` (served) |
| `/etc/mutis/` | root:mutis 0750 | `mutis.toml`, `secret.key` (32 random bytes, made here), `caddy.env`, `walletd-log4rs.yml` |
| `/etc/mutis/credentials/` | root 0700 | `walletd-keyring-pass` (systemd `LoadCredential`) |
| `/home/drive/wallet/` | drive 0700 | walletd's data (never moved, deleted or re-initialised); `backup/` daily copies |
| `/home/drive/mutis/` | drive 0700 | `receiver.json`, `robot.json` (sidecar-made keys) |
| `/var/backups/mutis/` | root 0700 | wallet tars and balance snapshots taken before any change to walletd; config copies; the go-live and pre-migrate database copies, which `backup.py prune-root` (the first step of `mutis-backup.service`, run as root) deletes at the published `db_backup_days` like every other database copy |
| `/usr/local/lib/mutis/` | root | `run-walletd.sh`; `run-sidecar.sh`, the config's `sidecar.command` (Node's permission model needs the release's real path, not the `current` symlink); `backup.py`, the one copy both backup units run (provision installs it, every activation refreshes it, a rollback leaves it) |
| `/usr/local/sbin/mutis-admin` | root | `sudo mutis-admin …` = the release's admin CLI as mutis (as drive for `notarize` and `walletd-fixture`, which talk to walletd), umask 007 |

Users: `mutis` (no login; API, cleanup, health, DB backups; cannot reach walletd), `drive` (walletd,
the chain worker and its Node sidecar, wallet backups, evidence; in group `mutis`), `build`
(compiles and runs the headless browser; no sudo, no wallet, no data), `caddy`.

Units: `walletd.service` (enabled), `caddy.service` (Debian's, plus `caddy.service.d/mutis.conf`),
`mutis-backup.timer` and `mutis-backup-wallet.timer` (enabled), and, installed but left off until
go-live ("Turning the app on"): `mutis-api`, `mutis-chain`, `mutis-cleanup.timer`, `mutis-health.timer`,
`mutis-evidence.timer`.

## Provisioning (idempotent)

```sh
tar -cf - deploy | ssh hidebox 'rm -rf /tmp/mutis-deploy && mkdir -m 711 /tmp/mutis-deploy && tar -xf - -C /tmp/mutis-deploy'
ssh hidebox 'sudo bash /tmp/mutis-deploy/deploy/scripts/provision.sh'
```

It checks the Debian packages (it installs nothing; npm/npx must be absent, and so must pnpm and yarn:
Debian's `nodejs` ships `corepack`, which would fetch them from the registry on first use; nothing here
calls it, and `privilege-check.sh` fails if a shim appears), creates the `mutis`, `drive` and `build`
users where missing (the login that runs it with sudo is the operator, or `MUTIS_OPERATOR`) and the
tree above, installs the config only if missing, generates `secret.key` if missing, copies the
keyring password into the credential store once (and skips walletd while it isn't set up), writes
`caddy.env` from `public_origin`, installs units and logging config, opens 80/443, keeps logging off,
adds whichever of the 5100, 18143 and 8787 guards is missing (ufw must be active), installs the
Caddyfile (validated first; the admin API moves to a socket), moves walletd from tmux into its unit
once (backup, graceful stop, cold backup, start, same balances or stop), enables the backup timers,
makes the receiver/robot keys if a release exists, and ends with `privilege-check.sh`. A new server
follows [`docs/self-host.md`](../docs/self-host.md), which also covers walletd's first start.

## Deploying

```sh
deploy/scripts/deploy.sh <git-ref>               # production: a committed ref (id <sha>-c<content id>)
deploy/scripts/deploy.sh --working-tree          # staging: the working tree as it is (id <sha12>-dirty-<time>)
deploy/scripts/deploy.sh --working-tree --holding   # the holding page (while the app isn't built)
```

It refuses uncommitted changes for a ref. On the server, as `build` with the server's Python 3.13, it
runs the server's and these unit tests, the lint and the copy check (a 3.14-only API on the
workstation can't pass them by accident); then it builds here with the live `/etc/mutis/mutis.toml`. The
release id ends in a hash of what the build serves, so the same commit built with a new
`public_origin`, `security_drop_url` or copy-variant setting (`gates`, `features`, `hosting`; the
manifest records these for verify-deploy) is a new release that really goes live. Then one tarball
over one multiplexed SSH connection; on the server `activate-release.sh` fixes ownership, makes the
sidecar prove it runs the pinned ootle-wasm, checks the config, migrates the database with
mutis-chain stopped (the migration backs it up; copies are made 0600), switches `current` with one
rename, restarts what is enabled,
validates and reloads a changed Caddyfile, refreshes the installed `backup.py`, warns when units
differ (run provision), makes missing keys, and keeps 5 releases. A release id that is already live
is left alone if it serves the same files and refused if it doesn't. Last, `tests/e2e/smoke.py` from
the workstation: home page with the app CSP, the live hash manifest equal to the local build,
`/api/v1/health` when the API is enabled, and `chain_ok` in `/api/v1/stats` when mutis-chain is. A
failing smoke test rolls back, but only if this run switched `current`. With `features.seallog` on,
`notarize-release.py` then writes the served manifest's SHA-256 to SealLog and appends
`{release, manifest_sha256, tx_id}` to `/releases.json` (brand patch P-9); a failure there leaves
the release live and says how to retry.

```sh
ssh hidebox 'sudo bash /srv/mutis/app/current/deploy/scripts/rollback.sh [<release-id>]'
```

Rolling back code never rolls back the database: migrations only go forward, and an older API
refuses a newer schema (it says so in the journal; the healthcheck turns red).

Every restart of `mutis-api` (a deploy, a rollback, a reboot) forgets the in-memory counters: rate
limits, each network's and each locker's daily caps (sponsor grants, demo payments, registrations,
drop uploads, and the sixth pass's daily brakes: new drives, free uploads and packs per network), proof-of-work escalation and wrong-password tries per network on password-only
links (a link's own failure count and lock are database rows and survive). They are keyed with a day key
that is never written, which is why they live only in memory (`server/mutis/ipkeys.py`,
`ratelimit.py`). The daily budgets (sponsor µT, deliveries, demo payments, decoys per slice) are rows
in the database and survive, so a restart can't raise what the wallet spends in a day; it only gives
each network a fresh allowance within those budgets. Persisting the counters would mean writing the
day key, which the privacy design rules out.

## Turning the app on (go-live)

12-integration §7 decides production; in this order, from the commit that will be tagged:

1. **Config** (`sudo editor /etc/mutis/mutis.toml`; keep a copy in `/var/backups/mutis/`):
   `gates.send_mode = "relay"` (§7.5: `"direct"`, with `features.direct_send` and `features.sponsor`,
   only after E-J passes in direct mode, tests/e2e/README.md; production switched to `direct` on
   2026-10-11 after that run, cold start 82 s: docs/evidence/2026-10-11/) and `gates.amount_proof = "sidecar"`
   (§7.6). `[seal_log] checkpoint_interval_s = 900` is the default (§7.2). Keep
   `sidecar.command = ["/usr/local/lib/mutis/run-sidecar.sh"]` (the server resolves `sidecar.dir`
   through the `current` symlink as well now; the wrapper is what mutis-chain's sandbox was proven
   with, and E-11 runs the release's sidecar through it). Check `ootle.mirror_start_epoch`: an epoch
   of the current chain at or before the first delivery mutis should see (12140, Esmeralda's epoch on
   2026-10-11; after a testnet reset, reset-playbook §5). With 0, the mirror and every restored locker
   would scan Esmeralda's whole history. Then `sudo mutis-admin check-config`.
2. **Units and the release.** The build sets the copy variants (relay or direct, how payments are
   checked, SealLog on or off) into the pages from this config, so every config change that copy
   follows is a redeploy (a new release id). Activation migrates the database (schema 3 in this
   release) with mutis-chain stopped and starts it again.
   ```sh
   curl -s https://ootle-indexer-b.tari.com/epoch-manager/stats     # current_epoch, for the check above
   ssh hidebox 'sudo systemctl enable --now mutis-api mutis-chain mutis-cleanup.timer mutis-health.timer mutis-evidence.timer'
   deploy/scripts/deploy.sh <ref>                   # the smoke test now includes /api/v1/health and chain_ok
   ```
3. **SealLog 2.0.0** ([ootle/setup-accounts.md](ootle/setup-accounts.md) §4): publish the raw
   template, create the new log, check its header, set `ootle.seallog_component` and
   `features.seallog = true`, deploy again. From then on every deploy notarizes its manifest
   (`/releases.json`), and `/evidence.json` names the live log, its latest checkpoint's chain index
   and the two retired logs. Top up `service` before November (same section).
4. **Tests** (tests/e2e/README.md: in batches an hour apart, E-05 with `e2e_expiry_s = 60` for the
   run only):
   ```sh
   python3 -I tests/e2e/test_headers.py
   python3 -I tests/e2e/run.py --chain --final --only E-01,E-02,E-03,…   # each batch with E-03 (it reads its batch's traffic)
   python3 -I tests/e2e/test_logs.py --relay        # D-02 after a real relay send
   ```
5. **A fresh database** (§7.7), after the last test run and before the public post, so the wall
   shows no test items: stop mutis-api and mutis-chain, move `/srv/mutis/data/db/mutis.sqlite3*` into
   `/var/backups/mutis/` (root, 0600), run `sudo mutis-admin migrate` (a new, empty database at the
   current schema, mode 0660), start both again, `sudo mutis-admin canary-now`.
6. **The judges' goodbye** (14-ghost-design §9): at least one checkpoint (15 minutes) before the tag,
   and after a fresh database, `sudo python3 -I /srv/mutis/app/current/deploy/scripts/demo-gone.py burn`
   locks a note nobody has a key for, burns its Once link and writes `judge_demo_gone` into the config
   (/judges, track one, step 4 opens it; its gone page shows the goodbye already on chain). Repeat
   it if judging runs past 30 days (tombstones). Tag only when `demo-gone.py check` exits 0.
7. **The tag:** `python3 -I tools/verify-deploy.py https://hidebox.app <tag>` → 0
   differences, the SealLog template included.

## Day to day

| Task | Command |
|---|---|
| Health | `https://hidebox.app/status.json` (the checks `/status` labels: https, api, chain_worker with its verifier, walletd, sponsor_balance, mirror, canary, credits, disk, budgets); full detail `sudo cat /srv/mutis/data/health.json`; red checks log one CRIT line each (`journalctl -p crit -u mutis-health`) |
| Takedown | `sudo mutis-admin takedown share|item|drop <id>`; `sudo mutis-admin reports --new` |
| Packs "sold out" | paid space is capped at `packs.paid_cap_fraction` (40 %) of the pool, 30 % of it kept for judge passes (`server/mutis/packs.py`); `sudo mutis-admin packs` shows both slices and today's sales (read-only); end a test drive's pack with `sudo mutis-admin release-pack -- <drive id>` (never a visitor's). See "If someone games the packs" |
| Freeze uploads | `sudo mutis-admin freeze all|free|none` |
| Features, budgets | `sudo mutis-admin feature <name> on|off|clear` (at once for the app and for pages read with JavaScript; the built pages follow the TOML at the next deploy); `sudo mutis-admin budget show` |
| Canary, evidence | `sudo mutis-admin canary-now`; `sudo systemctl start mutis-evidence` |
| Credits frozen (`credits` red, `credit_freeze_on`) | the hourly reconcile found a mismatch twice in a row, five minutes apart (a single one only holds credits until that second check); it keeps running while frozen, so a later `event=chain.reconcile_ok` in `journalctl -u mutis-chain` means every credited output is proven and committed again. Find out what changed, then `sudo mutis-admin unfreeze-credits` |
| walletd | `systemctl status walletd`; `journalctl -u walletd` (warnings only); restart `sudo systemctl restart walletd` |
| Balances | `cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py balances [--refresh]` |
| Backups | daily 03:30 (root's database copies under `/var/backups/mutis` pruned, then the database, as mutis) and 03:35 (wallet + keys, as drive); restore drill: `cd /tmp && sudo -u mutis python3 -I - restore-drill < …/backup.py` (and as drive) |
| L1 wallet | stays in tmux `l1` (a TUI, needed only for burns): `sudo -iu drive tmux attach -t l1`, detach with Ctrl-b d |

The L1 wallet has no unit on purpose: its console UI is how the burn's human capture check is done
(reset playbook §3), and nothing in the service depends on it running. After a reboot, start it by
hand only when a burn is needed.

## If someone games the packs

Sixth pass (`docs/threat-model.md`, "Griefing the space"). The signs: `/status.json` amber with
`packs.public_80` (the public slice of paid space is 80 % taken) or `packs.ceiling` (today's public
packs are sold), `/api/v1/stats` `packs_sold_public` close to `packs_cap_public`, or many 429s
`packs_limited`, `drives_limited`, `uploads_limited` in `journalctl -u mutis-api` (route and status only).

1. Look: `sudo mutis-admin packs` (slices, open invoices, judges' overflow, sales today against the
   ceilings) and `sudo mutis-admin budget show` (test money spent today).
2. Stop sales at once: `sudo mutis-admin feature packs off`. New invoices and test-money payments get
   503 and the Storage page says "Space packs are paused." within two seconds; payments already sent on
   chain still credit (the money is real to the payer). `sudo mutis-admin feature packs clear` turns
   them back on (the TOML's `features.packs`).
3. Tighten, if it continues: in `/etc/mutis/mutis.toml` (copy first to
   `/var/backups/mutis/mutis.toml.<UTC time>.before-<why>`), lower `[packs] public_per_day` or
   `per_network_day`, or `[brakes]` (drives and upload bytes per network a day), then
   `sudo mutis-admin check-config` and `sudo systemctl restart mutis-api`. A restart forgets the
   per-network counts (they live in memory) but not the day's ceilings (counted from the invoices).
4. Free space: `sudo mutis-admin freeze free` pauses uploads to free drives (paid drives and downloads
   keep working); `freeze none` resumes. The disk's own freezes need nothing from you.
5. A test drive's pack (an end-to-end run) can be ended with `release-pack`, which also frees its place
   under the day's ceiling; a visitor's pack is theirs, even a griefer's: packs are paid for, and the
   brakes, not refunds, are the answer.

`[brakes] exempt_addresses` lists the server's own public addresses (the end-to-end tests run there:
`ip -br addr` on the server); nothing else belongs there.

## Logs (spec §14.3)

| Source | What reaches disk |
|---|---|
| Caddy | no access log; errors only, with remote IP, port, host, URI, headers and TLS fields deleted. A 404 is logged at DEBUG, so not at all; a 5xx (the API stopped) is logged at ERROR with only the protocol and method left (`caddy-filter-debug.txt`) |
| mutis-api, chain, cleanup, health | route names, status codes, durations, fixed codes (`server/mutis/logsafe.py`) |
| walletd | warnings and errors only, to the journal; no log files (`walletd-log4rs.yml`) |
| journald | 7 days |
| ufw | off |
| sshd | operator logins (the operator's IP), as on any server; never visitor traffic |

`tests/e2e/test_logs.py` proves it from outside: see `deploy/ACCEPTANCE.md` D-02.

## Moving to a domain

1. Point the domain's A/AAAA at the server.
2. In `/etc/mutis/mutis.toml`: `public_origin = "https://mutis.sh"`; keep both hosts in `memo_origins`
   (courier memos already on chain name the old host).
3. `/etc/caddy/mutis.d/redirect.caddy` (imported by the Caddyfile), two blocks, each with
   `header -Server` like the rest (browsers carry the #key across a 308):
   ```
   srv2052606.hstgr.cloud {
   	header -Server
   	redir https://mutis.sh{uri} 308
   }
   http://srv2052606.hstgr.cloud {
   	header -Server
   	redir https://mutis.sh{uri} 308
   }
   ```
4. Re-run provision (rewrites `caddy.env`, reloads Caddy), deploy (the build fills `{{ORIGIN}}`), and
   `python3 -I tests/e2e/test_headers.py --origin https://mutis.sh --redirect-from srv2052606.hstgr.cloud`.

## Reboot drill (D-04)

`sudo systemctl reboot`, then within 3 minutes: `systemctl is-active walletd caddy mutis-api mutis-chain`,
`systemctl list-timers 'mutis-*'`, `/status.json` green except the canary (it reseals within the hour),
`python3 -I tests/e2e/smoke.py --origin … --manifest <dist manifest> --api`. Restart the L1 wallet's
tmux session only if a burn is planned.

## Playbooks

- [ootle/setup-accounts.md](ootle/setup-accounts.md): accounts, funding, SealLog, keys (what exists and how it was made)
- [ootle/reset-playbook.md](ootle/reset-playbook.md): the testnet forgot us
- [ootle/upgrade-drill.md](ootle/upgrade-drill.md): new walletd / indexer / ootle-wasm
