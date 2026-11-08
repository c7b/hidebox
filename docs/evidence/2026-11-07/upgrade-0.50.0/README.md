<!-- SPDX-License-Identifier: MIT -->
# walletd to Tari Ootle v0.50.0, 2026-11-07

Esmeralda moves to protocol V1 at epoch 12951, and walletd 0.49 can't follow it. The v0.50.0 release (tag on
`d3252ef1`) was published at 03:27 UTC, with the Esmeralda fleet still on 0.49.1 at epoch 12922. This folder is
upgrade-0.50.md §3a, §3c, §4, §5 and §7 as they ran on production, ahead of the fleet, and then §9: the fleet
moved to 0.50.0 between 03:28 and 03:43, the V1 SealLog stopped, and the V2 build was published with a new log.
No code was deployed (the site still serves release `0b7e341`, ootle-wasm 0.49.2); the one config change is
`ootle.seallog_component`. Times are UTC. Nothing here is a secret: no key, no judge pass, no link with its key;
hashes are cut where the full value isn't the point.

## Result

| What | State |
|---|---|
| walletd | **0.50.0** live since 03:34:11 (`282199b0…7d94`; four sources agree, and they are the CI build fetched the day before); 0.49.2 kept beside it and in `/var/backups/mutis`; down 17.8 s |
| The drill | on a copy, with no network, under every directive of `walletd.service`: two migrations, the same accounts and balances, nothing refused by the sandbox |
| The store | migrated (three applied migrations, newest `20261106120000`); the one authored template in the V1 layout dropped, as 0.50 does; balances unchanged (the before and after files differ only in the version) |
| Backup | `/var/backups/mutis/wallet-20261107T033353Z-pre-0.50.0.tar`, 617,922,560 B, root 0600, cold, sha256 `5a9c9179ecb37d3f7dca11c5a89b0d5e0b44654d0da890c4ff890157d8a7fde4` |
| Tari sends | paused 03:33:20 to 03:34:39 (79 s); nothing was in flight |
| Checkpoint | **#2552 committed** (chain index 405, epoch 12922), tx `dbdcf775…`, cost 5,982 µT of the 1,000,000 `pay_fee` (5,981 before) |
| Notarization | the live release's manifest (`95ec8bc6…`) again, tx `3d88e238…`, committed, 2,388 µT |
| Canary | #637 delivered by walletd 0.50.0 at 03:35:21, tx `3ce0ab61…`, cost 16,157 of its 30,000 (as before) |
| e2e | E-09, E-10, E-13, E-25, E-29, E-30 pass (03:35 to 03:47); E-J failed there (its demo payment, submitted at 03:40:43 while the fleet restarted, never reached the network: `seallog-v2.txt`) and **passed on a rerun at 04:06**, with the V2 log live and the sponsor refilled (`e2e/`) |
| The fleet | both indexers on 0.50.0 at 03:43:19, epoch 12922; the V1 log's next checkpoint (#2553, 03:49:50) failed as expected, `AcceptFeeRejectRest`, 1,208 µT |
| SealLog 2.1.0 | **`template_7441d162…869f`** (`dist-v2/seal_log.wasm` byte for byte, tx `f8d84734…`, 842,962 µT) and its log **`component_f8820af0…4fbe`** (tx `5c0ef368…`, 2,412 µT), live since 03:51:38; checkpoint 0 (#2554) committed at 03:55:04, tx `4e43ad14…`, 2,432 µT; the live manifest notarized in it, tx `9ffb488e…`, 2,036 µT |
| A fresh receipt | a synthetic upload at 03:56:29, covered by checkpoint 1 (#2555, 04:05:05, tx `fec4a898…`, 2,488 µT): its leaf recomputed here, the server's inclusion proof, the root and tree size read from ootle-indexer-b, checked with the live release's own `lib/seallog.js`: verified |
| Sponsor | its one output held by the lost payment until epoch 12929 (walletd 0.50.0 releases it by itself); refilled with 15 tTARI from `service` (tx `ff236c60…`) so the canary and the sends go on |
| `/status.json` | green at 03:37:19, after the swap; amber from 03:42 on: `sponsor_balance` below 200 tTARI (the held output) and the sponsor's evidence budget past 50% (the e2e run); the canary green throughout (snapshots at 03:43 and 04:06 in `status/`) |

## The dry run: walletd 0.50.0 asks the indexer, it doesn't run templates itself

Settled from tari-ootle `d3252ef1` before the swap, so that swapping walletd couldn't break checkpoints before the
fleet moves. walletd's SDK binds one network interface, the indexer REST client
(`applications/tari_walletd/src/lib.rs:75`, `type NetworkInterface = IndexerRestApiNetworkInterface`), the only
implementation of `WalletNetworkInterface` (`crates/wallet/sdk_services/src/indexer_rest_api.rs:340`). A dry run
goes from `TransactionApi::submit_dry_run_transaction` (`crates/wallet/sdk/src/apis/transaction.rs:181-195`) to
that client (`indexer_rest_api.rs:435-460`), which POSTs `transactions/dry-run` to the indexer
(`clients/tari_indexer_client/src/rest_api_client.rs:198-203`); `submit_manifest` dry-runs that way before it
submits (`applications/tari_walletd/src/handlers/transaction.rs:964-989`). walletd takes
`tari_ootle_app_utilities` without its `execution` feature (`Cargo.toml:105`, `default-features = false`;
`applications/tari_ootle_app_utilities/Cargo.toml:60-66`: "The wallet daemon only prices and submits
transactions"). The release binary does carry the engine's code (its compilation units are named in it,
presumably through feature unification when the release builds the workspace's binaries together), but no walletd
call reaches it. It decodes template definitions only for its authored-templates list
(`services/template_monitor.rs:62`) and the `templates.get` call (`handlers/templates.rs:53`), neither of which
mutis uses.
So the indexers and validators, still 0.49.1, keep running the V1 SealLog: checkpoint #2552 and the
notarization committed through walletd 0.50.0 after the swap. The V1 SealLog stops at the fleet upgrade, not at
this one (upgrade-0.50.md §9).

## Files

| File | What |
|---|---|
| `checksums.txt` | walletd: GitHub's digests, the `.sha256`, the release's list, the bytes on the server, the CI copy, the signed tag; what is installed |
| `drill-log.txt` | §3c on a copy under the production sandbox with no network, and its journal |
| `walletd.txt` | §4 (the pause, nothing in flight), §5 (the swap, the backup, the balances), walletd's journal after, the rollback |
| `chain.txt` | §7: the checkpoint, the notarization, the canary, their fees against their caps, the state of the fleet |
| `seallog-v2.txt` | §9: the V1 log's first failure and its fee, the publish, the new log, the config change and restart, its first checkpoints, the lost payment and the sponsor's refill |
| `receipt.txt` | the fresh receipt checked end to end against the V2 log |
| `verify-deploy.txt` | `tools/verify-deploy.py` against the live tag after the switch, with the live release's tools and with this lane's |
| `deploy.txt` | the release `spooky-secrets-2026-10-ootle-0.50`: the privacy scan, the tag, the deploy, verify-deploy with 0 differences, the notarization and the checks after |
| `status/` | `/status.json` at 03:43 (after the swap) and 04:06 (after the V2 log) |
| `e2e/` | the chain scenarios against production after the swap, from the deployed commit's tree |
| `scripts/` | `drill.sh` (§3c), `swap.sh` (§5), `wsum.py` (read-only walletd summary), `inflight.py` (§4, read-only) |
