<!-- SPDX-License-Identifier: MIT -->
# Run your own mutis

File sharing needs Python's standard library and a web server. The Tari features (sending to a Tari
address, dead drops, packs paid in tTARI, SealLog) also need the official wallet daemon on the Ootle
testnet and Node for the payment checker. Nothing is installed from npm or pip.

## Try it on your machine

```sh
git clone https://github.com/c7b/mutis && cd mutis
python3 -I tools/build.py --config deploy/config/mutis.toml.example --origin http://127.0.0.1:8787 \
  --web web --out /tmp/mutis-dist --release /tmp/mutis-release
python3 -I server/bin/mutis-api --dev --data /tmp/mutis-dev --dist /tmp/mutis-dist --port 8787 --pow-bits 10
```

Open <http://127.0.0.1:8787>. `--dev` runs the real API with a temporary data directory, small limits,
and a fake wallet, indexer and chain, so every flow completes offline (fake chain outputs are not real
cryptography and don't decrypt in a browser). Python 3.13 is what production runs; the API uses the
standard library only.

## A real deployment

What runs in production (Debian 13, one VPS), in [`deploy/README.md`](../deploy/README.md) in full:

| Piece | What | Where it comes from |
|---|---|---|
| Caddy | TLS, the security headers and per-route CSPs, static files, the API proxy; no access log | Debian package, `deploy/caddy/Caddyfile` |
| `mutis-api` | the HTTP API on `127.0.0.1:8787`, as user `mutis` (it can't reach the wallet) | `server/` (Python 3.13, stdlib) |
| `mutis-chain` | relay sends, the UTXO mirror, payment proofs, canaries, SealLog checkpoints, as user `drive` | `server/` |
| the sidecar | the official Tari library under Node's permission model, started by `mutis-chain` | `web/app/sidecar`, `web/app/vendor` (pinned by hash); Debian's `nodejs` 20 |
| walletd | `tari_ootle_walletd` 0.45.0 on `127.0.0.1:5100`, as user `drive` | the official release binary |
| timers | cleanup (every minute), health, evidence, database and wallet backups | `deploy/systemd/` |

Steps on a fresh Debian 13 server, from your own login with sudo (each script says what it changes
and is safe to re-run). That login is the operator: with root, the only account besides `drive` that
may reach walletd and the API port.

1. **Packages and the firewall:** `sudo apt-get install --no-install-recommends caddy nodejs python3 ufw
   chromium fonttools python3-brotli woff2 ffmpeg` (provision checks for every one of them; Chromium,
   fonttools, woff2 and ffmpeg serve the test and asset tools). No npm, npx, pnpm, yarn or pip:
   provision and its privilege self-test fail while any is present. Then `sudo ufw limit 22/tcp && sudo ufw enable` (your SSH port, if it isn't 22).
2. **A copy of the repository and the config:** `git clone https://github.com/c7b/mutis` on the server,
   then `sudo install -d /etc/mutis && sudo cp mutis/deploy/config/mutis.toml.example /etc/mutis/mutis.toml`
   and set `public_origin` (the example names our server; Caddy gets a certificate for the host you
   write) and `memo_origins` (every origin you ever served from: courier memos carry it on chain).
3. **Provision:** `sudo bash mutis/deploy/scripts/provision.sh` creates the accounts (`mutis` runs the
   API; `drive` runs walletd and the chain worker; `build` runs the tests and compiles, and can read no
   secret), the directories, `/etc/mutis/secret.key`, the units, the Caddyfile and the logging
   settings; it opens ports 80 and 443 and adds loopback guards (only root, you and `drive` reach
   walletd's port 5100; only those and Caddy reach the API's 8787), then runs the privilege self-test.
   Without walletd it says so and skips it: set `features.drops`, `relay_send`, `demo_pay`, `decoys`
   and `seallog` to false and leave `mutis-chain` disabled.
4. **walletd (for the Tari features):** put the official `tari_ootle_walletd` for the current Esmeralda
   release at `/opt/tari/bin/tari_ootle_walletd` (check its hash against the release). As `drive`
   (`sudo -iu drive`): write a random keyring password,
   `(umask 077 && head -c 30 /dev/urandom | base64 | tr -d '/+=' > ~/wallet/.keyring-pass)`, and start
   walletd once in the foreground so it writes its default config:
   `/opt/tari/bin/tari_ootle_walletd --network esme --base-path ~/wallet --authentication none run`.
   It stops with "OS keyring not supported on this device"; that is expected. Run provision again: it
   copies the password into a root-only credential and starts `walletd.service`, which hands it over
   on every start (`deploy/ootle/run-walletd.sh`). Then create and fund the accounts (`service`,
   `sponsor`): [`deploy/ootle/setup-accounts.md`](../deploy/ootle/setup-accounts.md).
5. **Configure** the rest of `/etc/mutis/mutis.toml` (every key is in
   [`deploy/config/mutis.toml.example`](../deploy/config/mutis.toml.example)): `gates` (`send_mode`,
   `amount_proof`), `features`, `ootle.mirror_start_epoch` (an epoch of the current chain, so the
   mirror doesn't scan its whole history). Then `sudo mutis-admin check-config`.
6. **Deploy** from your workstation's checkout (git and Python 3.13 there; on the server, your SSH
   login needs sudo without a password prompt): `deploy/scripts/deploy.sh --host <ssh host> <git-ref>`
   runs the tests on the server as `build`, builds, uploads one tarball, migrates the database,
   switches the release atomically and runs a smoke test (it rolls back if that fails). Then, on the
   server, `sudo systemctl enable --now mutis-api mutis-cleanup.timer mutis-health.timer mutis-evidence.timer`,
   and `mutis-chain` too when walletd runs.
7. **SealLog (optional):** publish the template's exact bytes and create your own log with
   `deploy/ootle/publish-template.sh check | publish | instantiate <template>`, then set
   `ootle.seallog_component` and `features.seallog = true` and deploy again.
8. **Check it:** `/status.json` (every check green once the first canary is verified, within the
   hour), `python3 -I tests/e2e/test_headers.py --origin <yours>`, and
   `python3 -I tools/verify-deploy.py <yours> <commit>`.

## Day to day

`deploy/README.md` has the operator commands: takedowns (`sudo mutis-admin takedown item -- <id>`),
freezing uploads, feature switches, budgets, balances, backups and the restore drill, the reboot
drill, moving to a domain, and the playbooks for a testnet reset and a walletd upgrade.
