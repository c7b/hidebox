<!-- SPDX-License-Identifier: MIT -->
# Checklist: SealLog from the V1 build to the V2 build on Esmeralda (upgrade-0.50.md §9)

The commands for §9's last two steps, in order, from a checkout of `ootle/0.50` on the workstation. The aliases
`u`, `admin` and `rpc` are reset-playbook.md's. `<…>` is a value that exists only when you get there. Nothing
here runs by itself.

| Fixed value | |
|---|---|
| The V2 build | `template/dist-v2/seal_log.wasm`, 107,038 bytes, sha256 `00ca5f34e5f7a2b036319047fd09ab3c112556dbec119d9a5e75735e462f878f`, ABI `2e0303562dcae9babcb2d59bf72abcb4460c3ee6fab08ee527c67baf43b699b5` (tari_template_lib 0.38.0 from crates.io, published from tari-ootle `d3252ef1`) |
| The live V1 log | `component_6a3eae198ed483565abf978f7c5289263f13b2edf3ef3900a9924dd41141bd65` on `template_5932ee9ba5a969f59eac0cddc8fae7112b22dfc85abdaa751911d11ce533145c` |
| Who pays | `service` (`account.pay_fee`, refundable: only the cost is kept) |

## 0. Before: what a failed checkpoint costs, and why `seallog` stays on

From the fleet upgrade on, every checkpoint and notarization against the V1 log fails in its main intent. The fee
intent has already run, so the transaction finalizes as `AcceptFeeRejectRest`: tari-ootle `d3252ef1`,
`crates/engine/src/transaction/processor.rs:376-388` ("The fee charges for the successful instructions are still
charged even though the transaction failed"). A template that won't load is no node fault: only
`ClaimProofVerifierFault` is (`crates/engine/src/transaction/error.rs:61-66`). `pay_fee` from the account's vault
is a refundable payment, so `service` keeps everything but the cost (`crates/engine/src/runtime/working_state.rs:2190-2236`).
walletd submits anyway: a failed dry run only widens its input declarations
(`applications/tari_walletd/src/handlers/transaction.rs:964-989`).

mutis-chain tries again 10 minutes after a failure (`SEAL_RETRY_S`, `server/mutis/chain_worker.py:42` and
`_seal_failed`), so at most 6 attempts an hour, each logged `chain.seal_failed` and paying about what a checkpoint
costs (5,981 µT for #288; the failed call runs less): at most about 0.9 tTARI a day. Each deploy's notarization
fails once too (deploy.sh says so; the release stays live).

Turning `seallog` off (`admin feature seallog off`) stops that, but it is not a silent pause: `/api/v1/config`
says `features.seallog: false`, so `/made` reads "This deployment keeps no public record yet: SealLog is off
here.", `/verify` reads "Receipts are off on this deployment, so there's nothing to check yet.", the receipt line
leaves the link page and the drive's Activity, and the receipt endpoints answer 503 `feature_disabled`. Not one
of those is true of a log with over 350 checkpoints. `/status.json` has no SealLog check, so it stays green either way;
`/evidence.json` reads `features.seallog` from `mutis.toml`, not the override, so it keeps showing the V1 log and
its last committed checkpoint either way.

So **leave `seallog` on through the gap.** The receipts stay checkable against the V1 log's last checkpoint (a
substate read runs no template), new uploads show as pending, and the cost is at most a few tTARI. Turn it off
only if the first failed attempt costs far more than a checkpoint (below), or fails in a way that holds walletd's
inputs.

**As it ran on 2026-11-07** (`docs/evidence/2026-11-07/upgrade-0.50.0/seallog-v2.txt`): the first failed attempt
(#2553) cost 1,208 µT, a fifth of a checkpoint, and `seallog` stayed on; a demo payment submitted while the fleet
restarted was lost and held the sponsor's one output, so the sponsor was refilled from `service` (setup-accounts.md §0).

## 1. When the fleet moves

```sh
curl -fsS https://ootle-indexer-b.tari.com/info | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["version"])'
u 'sudo journalctl -u mutis-chain --since "-30 min" --no-pager | grep -E "seal_failed" | tail -3'
u "cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'" <<'EOF'
import sqlite3
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
for row in c.execute("SELECT idx, state, chain_index, tx_id, submitted_at FROM seal_checkpoints ORDER BY idx DESC LIMIT 4"):
    print(row)
EOF
```

The first `failed` row's `tx_id` goes to upgrade-0.50.md §7's fee script: `cost` near 6,000 µT is the expected
price of the gap. Only if it is much higher:

```sh
admin feature seallog off              # the copy above changes at once; clear it in §3
```

## 2. Then, with walletd 0.50.0 in place (upgrade-0.50.md §3–§5) and the `ootle/0.50` tag deployed

The deployed tag must carry `template/dist-v2/` and verify-deploy's V1 exception, so `verify-deploy` passes for
the V1 log now and for the V2 log after §3. `service` needs about 1 tTARI in its public vault (the V1 publish
cost 842,994 µT on 2026-11-02; publish-template.sh caps the fee at 3,000,000 µT).

```sh
W=template/dist-v2/seal_log.wasm
sha256sum $W                                            # 00ca5f34…878f, as above
rpc balances                                            # service: the public vault holds at least 1 tTARI
deploy/ootle/publish-template.sh check --wasm $W        # "Accept fee …", the predicted template_<template>
deploy/ootle/publish-template.sh publish --wasm $W      # tx, status, fee; then "ABI (tari_tdef): equal" and byte for byte
python3 -I template/wasm_check.py onchain template_<template> --wasm $W     # again, from any machine
deploy/ootle/publish-template.sh instantiate template_<template>           # prints the new log: component_<new>
```

The log's header (owner `None`, upgrade rule `Locked`, `append_root` only for `service`'s badge) is what the
browser's check reads (`lib/seallog.js` `readSealLog`): `/verify` refuses any other, so §3's check covers it.

## 3. Point mutis at the new log

```sh
u 'sudo cp -a /etc/mutis/mutis.toml /var/backups/mutis/mutis.toml.$(date -u +%Y%m%dT%H%M%SZ).before-seallog-v2'
u 'sudo editor /etc/mutis/mutis.toml'                   # [ootle] seallog_component = "component_<new>"
admin check-config
u 'sudo systemctl restart mutis-chain mutis-api'        # both read the component at start (setup-accounts.md §4)
admin feature seallog clear                             # only if §1 turned it off
admin seal-now                                          # the new log's checkpoint 0 holds the whole tree so far
```

Until that checkpoint commits (a minute or two), `/verify` reads the new log while receipts still point at the
V1 log's last checkpoint, so a check in that window fails; run `seal-now` right after the restart. Then:

```sh
# the newest row: state committed, component_<new>, chain_index 0
u "cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'" <<'EOF'
import sqlite3
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
print(c.execute("SELECT idx, state, component, chain_index, tree_size FROM seal_checkpoints ORDER BY idx DESC LIMIT 1").fetchone())
EOF
admin notarize "$(curl -fsS https://hidebox.app/.well-known/mutis-manifest.json | sha256sum | cut -d' ' -f1)"   # {"committed": true}
u 'sudo python3 -I /srv/mutis/app/current/deploy/scripts/notarize-release.py'    # a release deployed in the gap, if any
python3 -I tools/verify-deploy.py https://hidebox.app <tag>                     # 0 differences, the log against dist-v2
curl -fsS https://hidebox.app/api/v1/config | python3 -I -c 'import json, sys; c = json.load(sys.stdin); print(c["features"]["seallog"], c["seal_log"])'
python3 -I tests/e2e/run.py --host hidebox --chain --only E-25,E-J
```

`/evidence.json` names the new log at the next evidence run.

## 4. The record

In the repository: setup-accounts.md §0 (the V2 template, superseding `template_5932ee9b…145c`, and the new log,
with their transactions and fees), `SEALLOG_TEMPLATE` in `deploy/tests/test_verify_deploy.py` and the fixtures
that name the live log stay as the record of 2026-11-02, the CHANGELOG entry, and upgrade-0.50.md's rehearsal log.
verify-deploy's `V1_LOGS` can stay: it names only the retired log. `/evidence.json` lists the V1 log under
`seallog.retired` as soon as `mutis.toml` names its successor (`RETIRED_LOGS` in `deploy/scripts/collect-evidence.py`).
