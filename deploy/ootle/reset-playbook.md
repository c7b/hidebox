<!-- SPDX-License-Identifier: MIT -->
# Reset playbook: the Esmeralda testnet forgot our state

Spec §10.8. Use it when the indexers no longer know our UTXOs or components: sends fail with
`input_gone`/"is down", balances read zero after a refresh, the healthcheck's `mirror` or `walletd`
turns red for more than an hour, and the Tari forum or Discord announces a reset. Links and file
sharing keep working throughout; only the Tari features pause.

Target: under 30 minutes of operator time plus the ~1 hour burn wait. Every command runs from the
workstation through one multiplexed connection:

```sh
alias u='ssh -o ControlMaster=auto -o ControlPath=/tmp/cm-hidebox -o ControlPersist=30m -o ClearAllForwardings=yes hidebox'
admin() { u "sudo mutis-admin $*"; }          # /usr/local/sbin/mutis-admin: as mutis (walletd commands as drive), umask 007
rpc() { u "cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py $*"; }
```

## 1. Pause the Tari features (2 minutes)

```sh
for f in relay_send direct_send drops demo_pay sponsor decoys seallog; do admin feature $f off; done
```

`seallog` too: the SealLog component is gone with the old chain, and its checkpoints would fail.

The site and app read `features` from `/api/v1/config` and show the 11-brand §10.7 "Tari features
are paused" state. Uploads, links and the viewer are unaffected.

## 2. Archive the evidence (2 minutes)

```sh
u 'sudo systemctl start mutis-evidence.service'      # refresh evidence.json first
u 'cd /tmp && sudo -u drive env MUTIS_CONFIG=/etc/mutis/mutis.toml python3 -I /srv/mutis/app/current/deploy/scripts/collect-evidence.py --archive'
```

This keeps `/srv/mutis/status/evidence-archive-YYYYMMDD.json` (served at `/evidence-archive-…json`).
Tell the integrator: it goes into `docs/evidence/<date>/` with screenshots, because the transactions
it names will no longer resolve on the indexers.

## 2b. When the reset comes with a new Ootle release (as on 2026-11-02, 0.47 → 0.49.2)

New walletd first, then reset its chain state: back up the whole wallet (`/home/drive/wallet` and
`/home/drive/.local/share/tari`), stop walletd, install the binary (checksum against the release's
`.sha256` and its `sha256-unsigned.txt`), and run `tari_ootle_walletd reset --confirm` under walletd's own
sandbox (the run script with `reset --confirm` in place of `run`). The reset moves `wallet.sqlite` to a
`.bak` file. **Our seed lived in that database** (`config.cipher_seed`), not in an OS keyring, so the
wallet came back with a **new seed**: new account keys, a new SealLog author, a new template address.
The old seed stays in the `.bak` and the backup. Then create the accounts again in the same order
(`service`, `buyer-demo`, `sponsor`, `operator`: key indexes 0 to 3). The code side is
[upgrade-drill.md](upgrade-drill.md) §1–§2 (the 2026-11-02 row).

## 3. Funds (human step; the burn is never automated)

First try the L2 faucet: `rpc call accounts.create_free_test_coins '{"account":{"Name":"service"},"max_fee":"2000000"}'`
(1,000 tTARI a claim). Right after the 2026-11-02 reset it held nothing ("Claim tTARI by burning on L1
instead"), so the burn below was the way.

The L1 console wallet (`/home/drive/l1wallet`, tmux session `l1`, ~1,000 tXTM reserve) burns tXTM
into tTARI. Follow 03-ootle-integration §5.1 exactly, in the TUI, with the capture check:

```sh
u -t 'sudo -iu drive tmux attach -t l1'     # detach with Ctrl-b d; never Ctrl-c
```

If the L1 wallet is empty, ask the L1 faucet for tXTM first. Type the TUI's fields one step at a time
with a capture after each: keys typed outside an edit field are commands (the claim key's hex has `d`,
"delete the selected proof"). The L1 wallet writes the proof a few minutes after the burn to
`/home/drive/.local/share/tari/esmeralda/burn_proofs` (drive's: list it with sudo); check with
`rpc call burn_proofs.list '{"filter_by_public_key":null}'`. A claim is valid only once the L2 has passed
the burn's epoch (`mined_in_epoch` in the file; an epoch is 80 L1 blocks, and the L2 reads L1 about 100
blocks behind), and then walletd 0.49.2 claims it by itself and moves the file to `claimed/` (on
2026-11-02, about 80 and 115 minutes after the two burns). A claim by hand (`accounts.claim_burn` with
`"claim_proof": {"FromFile": {"file_name": "<that file>"}}`) before that is rejected `NotYetValid`,
though its dry run accepts it; it costs nothing and leaves the file for walletd's retry. On 0.49 the claim lands
as a stealth output, not in the account's public vault; what pays fees with `account.pay_fee` (the
template publish, the log, its checkpoints) needs a stealth transfer from `service` to its own address
with a `revealed_output_amount`, which goes to its public vault.

## 4. Accounts and keys (10 minutes)

```sh
rpc balances --refresh                 # where the claimed tTARI landed (the default account: service)
```

Re-create and re-fund `sponsor` exactly as in [setup-accounts.md](setup-accounts.md) §2 (the burn
lands in `service`, which pays for SealLog), then republish SealLog and instantiate a new log
(setup-accounts.md §4, `publish-template.sh check | publish | instantiate`) and put the new
`ootle.seallog_component` in `/etc/mutis/mutis.toml` (`admin check-config`). The receiver and robot-locker keys survive a reset:
addresses are derived from keys, not from chain state. `init-keys.sh` confirms they are there and
never overwrites them:

```sh
u 'sudo -u drive bash /srv/mutis/app/current/deploy/scripts/init-keys.sh'
```

## 5. The mirror (2 minutes)

The UTXO mirror's per-shard cursors point into the old chain. Set `ootle.mirror_start_epoch` to the new
chain's first epoch (12812 on 2026-11-02: epochs follow L1 and didn't start again from zero). The hourly
payment reconcile checks only payments from that epoch on: the outputs credited on the old chain are gone,
and checking them freezes credits every hour (`credit_freeze`; then `mutis-admin unfreeze-credits` once the
setting is in). Then forget the cursors so the worker starts over:

```sh
curl -s https://ootle-indexer-b.tari.com/epoch-manager/stats      # {"current_epoch": N, …}
u 'sudo editor /etc/mutis/mutis.toml'                             # [ootle] mirror_start_epoch = N
admin check-config
u 'sudo systemctl stop mutis-chain'
echo "import sqlite3; c = sqlite3.connect('/srv/mutis/data/db/mutis.sqlite3'); c.execute(\"DELETE FROM meta WHERE key = 'mirror_cursors'\"); c.commit()" |
  u "cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'"
u 'sudo systemctl start mutis-chain'
```

## 6. Resume (2 minutes)

```sh
for f in relay_send direct_send drops demo_pay sponsor decoys seallog; do admin feature $f clear; done
admin canary-now
```

`clear` drops the override, so the TOML decides again. Within 15 minutes the canary is delivered,
found in the mirror and opened (`/status.json` → `canary: green`). Then run the chain scenarios:
`python3 -I tests/e2e/run.py --chain --only E-09,E-25`.

## Rehearsal log

| Date | What | Operator time | Result |
|---|---|---|---|
| 2026-10-11 | Steps 1, 2, 4 (keys), 5 and 6 on the live server, services stopped, no burn (D-10) | see `deploy/ACCEPTANCE.md` D-10 | pass |
