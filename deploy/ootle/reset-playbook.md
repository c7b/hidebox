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

## 3. Funds (human step; the burn is never automated)

The L1 console wallet (`/home/drive/l1wallet`, tmux session `l1`, ~1,000 tXTM reserve) burns tXTM
into tTARI. Follow 03-ootle-integration §5.1 exactly, in the TUI, with the capture check:

```sh
u -t 'sudo -iu drive tmux attach -t l1'     # detach with Ctrl-b d; never Ctrl-c
```

If the L1 wallet is empty, ask the L1 faucet for tXTM first. walletd claims the burn proof by itself
(it watches `/home/drive/.local/share/tari/esmeralda/burn_proofs`); check with
`rpc call burn_proofs.list '{"filter_by_public_key":null}'` and, if it didn't, claim it with
`accounts.claim_burn`. Wait for the claim (about an hour, 03 §5).

## 4. Accounts and keys (10 minutes)

```sh
rpc balances --refresh                 # where the claimed tTARI landed (the default account: service)
```

Re-create and re-fund `sponsor` (and `operator` once SealLog is live) exactly as in
[setup-accounts.md](setup-accounts.md) §2–§3, then republish SealLog and instantiate a new log
(setup-accounts.md §4) and put the new `ootle.seallog_component` in `/etc/mutis/mutis.toml`
(`admin check-config`). The receiver and robot-locker keys survive a reset:
addresses are derived from keys, not from chain state. `init-keys.sh` confirms they are there and
never overwrites them:

```sh
u 'sudo -u drive bash /srv/mutis/app/current/deploy/scripts/init-keys.sh'
```

## 5. The mirror (2 minutes)

The UTXO mirror's per-shard cursors point into the old chain, and epochs start again from zero after
a reset, so the old `ootle.mirror_start_epoch` would hide the new chain. Set it to the new chain's
current epoch and forget the cursors so the worker starts over:

```sh
curl -s https://ootle-indexer-b.tari.com/epoch-manager/stats      # {"current_epoch": N, …}
u 'sudo editor /etc/mutis/mutis.toml'                             # [ootle] mirror_start_epoch = N
admin check-config
u 'sudo systemctl stop mutis-chain'
echo "import sqlite3; c = sqlite3.connect('/srv/mutis/data/db/mutis.sqlite3'); c.execute(\"DELETE FROM meta WHERE key = 'mirror_cursor'\"); c.commit()" |
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
