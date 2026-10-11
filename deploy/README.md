<!-- SPDX-License-Identifier: MIT -->
# mutis deploy: operator runbook

Everything that turns this repository into the running service on the server (Debian 13, one VPS): the
build, the web server, the units, the wallet daemon's supervision, backups, health, evidence, the
playbooks and the end-to-end tests. Python standard library, bash and Debian packages only; nothing
is installed from npm, pip or a CDN.

```
deploy/caddy/Caddyfile              TLS, the spec §14.2 headers and CSPs, routes, caching; no access log
deploy/systemd/                     walletd, mutis-api, mutis-chain, timers (cleanup, backups, health, evidence)
deploy/journald/mutis.conf          7-day journal
deploy/config/mutis.toml.example    /etc/mutis/mutis.toml (every key the server accepts)
deploy/holding/                     the page served until the full site builds
deploy/scripts/                     provision, deploy, activate-release, rollback, notarize-release,
                                    backup, healthcheck, collect-evidence, init-keys, privilege-check,
                                    mutis-admin (wrapper)
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

They cover the build (the served-file allow-list, layout, includes, placeholders, SRI, vendored
hashes, lint gate, sitemap, manifest determinism, content ids, holding mode), the lint and copy
rules, verify-deploy's comparison, backups (age-based retention equal to the published
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
python3 -I tools/verify-deploy.py https://srv2052606.hstgr.cloud <tag>   # D-09
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
| `/var/backups/mutis/` | root 0700 | wallet tars and balance snapshots taken before any change to walletd |
| `/usr/local/lib/mutis/` | root | `run-walletd.sh`; `run-sidecar.sh`, the config's `sidecar.command` (Node's permission model needs the release's real path, not the `current` symlink); `backup.py`, the one copy both backup units run (provision installs it, every activation refreshes it, a rollback leaves it) |
| `/usr/local/sbin/mutis-admin` | root | `sudo mutis-admin …` = the release's admin CLI as mutis (as drive for `notarize` and `walletd-fixture`, which talk to walletd), umask 007 |

Users: `mutis` (no login; API, cleanup, health, DB backups; cannot reach walletd), `drive` (walletd,
the chain worker and its Node sidecar, wallet backups, evidence; in group `mutis`), `build`
(compiles and runs the headless browser; no sudo, no wallet, no data), `caddy`.

Units: `walletd.service` (enabled), `caddy.service` (Debian's, plus `caddy.service.d/mutis.conf`),
`mutis-backup.timer` and `mutis-backup-wallet.timer` (enabled), and, installed but left off until the
integrator turns the app on: `mutis-api`, `mutis-chain`, `mutis-cleanup.timer`, `mutis-health.timer`,
`mutis-evidence.timer`.

## Provisioning (idempotent)

```sh
tar -cf - deploy | ssh hidebox 'rm -rf /tmp/mutis-deploy && mkdir -m 711 /tmp/mutis-deploy && tar -xf - -C /tmp/mutis-deploy'
ssh hidebox 'sudo bash /tmp/mutis-deploy/deploy/scripts/provision.sh'
```

It checks the Debian packages (it installs nothing; npm/npx must be absent), creates the `mutis`
user and the tree above, installs the config only if missing, generates `secret.key` if missing,
copies the keyring password into the credential store once, writes `caddy.env` from `public_origin`,
installs units and logging config, opens 80/443, keeps logging off, adds the 18143 and 8787 guards, installs
the Caddyfile (validated first; the admin API moves to a socket), moves walletd from tmux into its
unit once (backup, graceful stop, cold backup, start, same balances or stop), enables the backup
timers, makes the receiver/robot keys if a release exists, and ends with `privilege-check.sh`.

## Deploying

```sh
deploy/scripts/deploy.sh <git-ref>               # production: a committed ref (id <sha>-c<content id>)
deploy/scripts/deploy.sh --working-tree          # staging: the working tree as it is (id <sha12>-dirty-<time>)
deploy/scripts/deploy.sh --working-tree --holding   # the holding page (while the app isn't built)
```

It refuses uncommitted changes for a ref. On the server, as `build` with the server's Python 3.13, it
runs the server's and these unit tests, the lint and the copy check (a 3.14-only API on the workstation can't pass them by accident); then it builds here with the live `/etc/mutis/mutis.toml`. The
release id ends in a hash of what the build serves, so the same commit built with a new
`public_origin` or `security_drop_url` is a new release that really goes live. Then one tarball
over one multiplexed SSH connection; on the server `activate-release.sh` fixes ownership, makes the
sidecar prove it runs the pinned ootle-wasm, checks the config, migrates the database (the migration
backs it up; copies are made 0600), switches `current` with one rename, restarts what is enabled,
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

## Turning the app on (integrator)

Before: decide the gates in `/etc/mutis/mutis.toml` (`gates.send_mode`, `gates.amount_proof`,
`features.*`, 12-integration §3). Keep `sidecar.command = ["/usr/local/lib/mutis/run-sidecar.sh"]`:
without it the chain worker can't start its sidecar from the `current` symlink. Check `ootle.mirror_start_epoch`: it must be an epoch of the
current chain at or before the first delivery mutis should see (it was set to 12140, Esmeralda's
epoch on 2026-10-11; after a testnet reset, see reset-playbook §5). With 0, the mirror and every
restored locker would scan Esmeralda's whole history. Then `sudo mutis-admin check-config`.

```sh
curl -s https://ootle-indexer-b.tari.com/epoch-manager/stats     # current_epoch, for the check above
ssh hidebox 'sudo systemctl enable --now mutis-api mutis-chain mutis-cleanup.timer mutis-health.timer mutis-evidence.timer'
deploy/scripts/deploy.sh <ref>                   # the smoke test now includes /api/v1/health and chain_ok
python3 -I tests/e2e/test_headers.py && python3 -I tests/e2e/run.py --chain --final
```

Test runs on production leave their items on the home page's wall for 7 days (removed items stay
as 30-day tombstones). To start clean after the last test run and before the public post: stop
mutis-api and mutis-chain, move `/srv/mutis/data/db/mutis.sqlite3*` into `/var/backups/mutis/`
(root, 0600), run `sudo mutis-admin migrate` (a new, empty database, mode 0660) and start the two
services again.

## Day to day

| Task | Command |
|---|---|
| Health | `https://srv2052606.hstgr.cloud/status.json`; full detail `sudo cat /srv/mutis/data/health.json`; red checks log one CRIT line each (`journalctl -p crit -u mutis-health`) |
| Takedown | `sudo mutis-admin takedown share|item|drop <id>`; `sudo mutis-admin reports --new` |
| Freeze uploads | `sudo mutis-admin freeze all|free|none` |
| Features, budgets | `sudo mutis-admin feature <name> on|off|clear`; `sudo mutis-admin budget show` |
| Canary, evidence | `sudo mutis-admin canary-now`; `sudo systemctl start mutis-evidence` |
| walletd | `systemctl status walletd`; `journalctl -u walletd` (warnings only); restart `sudo systemctl restart walletd` |
| Balances | `cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py balances [--refresh]` |
| Backups | daily 03:30 (database, as mutis) and 03:35 (wallet + keys, as drive); restore drill: `cd /tmp && sudo -u mutis python3 -I - restore-drill < …/backup.py` (and as drive) |
| L1 wallet | stays in tmux `l1` (a TUI, needed only for burns): `sudo -iu drive tmux attach -t l1`, detach with Ctrl-b d |

The L1 wallet has no unit on purpose: its console UI is how the burn's human capture check is done
(reset playbook §3), and nothing in the service depends on it running. After a reboot, start it by
hand only when a burn is needed.

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
