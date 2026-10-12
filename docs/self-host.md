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

Steps, as root on the server (each script says what it changes and is safe to re-run):

1. **Packages:** `caddy`, `nodejs` (no npm), `python3`; `chromium` only for the browser tests.
2. **walletd:** install the official `tari_ootle_walletd` for the current Esmeralda release, create its
   accounts (`service`, `sponsor`) and fund them: [`deploy/ootle/setup-accounts.md`](../deploy/ootle/setup-accounts.md).
   Without walletd, turn the chain features off in the config (`features.drops`, `relay_send`,
   `demo_pay`, `decoys`, `seallog` = false) and leave `mutis-chain` disabled.
3. **Provision:** `sudo bash deploy/scripts/provision.sh` creates the users and directories, installs
   the config only if it is missing, makes `/etc/mutis/secret.key` on the server, installs the units,
   the Caddyfile and the logging settings, and opens ports 80 and 443.
4. **Configure** `/etc/mutis/mutis.toml` (every key is in
   [`deploy/config/mutis.toml.example`](../deploy/config/mutis.toml.example)): `public_origin`,
   `memo_origins` (every origin you ever served from: courier memos carry it on chain), `gates`
   (`send_mode`, `amount_proof`), `features`, `ootle.mirror_start_epoch` (an epoch of the current
   chain, so the mirror doesn't scan its whole history). Then `sudo mutis-admin check-config`.
5. **Deploy** from a checkout: `deploy/scripts/deploy.sh <git-ref>` runs the tests on the server,
   builds, uploads one tarball, migrates the database, switches the release atomically and runs a
   smoke test (it rolls back if that fails). Then
   `sudo systemctl enable --now mutis-api mutis-chain mutis-cleanup.timer mutis-health.timer mutis-evidence.timer`.
6. **SealLog (optional):** publish the template's exact bytes and create your own log with
   `deploy/ootle/publish-template.sh check | publish | instantiate <template>`, then set
   `ootle.seallog_component` and `features.seallog = true` and deploy again.
7. **Check it:** `/status.json` (every check green once the first canary is verified, within the
   hour), `python3 -I tests/e2e/test_headers.py --origin <yours>`, and
   `python3 -I tools/verify-deploy.py <yours> <commit>`.

## Day to day

`deploy/README.md` has the operator commands: takedowns (`sudo mutis-admin takedown item -- <id>`),
freezing uploads, feature switches, budgets, balances, backups and the restore drill, the reboot
drill, moving to a domain, and the playbooks for a testnet reset and a walletd upgrade.
