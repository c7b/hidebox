<!-- SPDX-License-Identifier: MIT -->
# walletd and ootle-wasm to Tari Ootle v0.52.0, 2026-11-09

tari-ootle v0.51.0 (13:02 UTC) and v0.52.0 (14:35 UTC) were published the same day, each saying validators,
indexers and wallets upgrade together, with no activation epoch and no reset. The Esmeralda fleet moved with them:
by 18:14 both public indexers ran 0.52.0, and so did every validator they were connected to. hidebox kept working
through the move on walletd 0.50.1 and ootle-wasm 0.50.0. This folder is upgrade-0.52.md §2 to §7 as they ran on
production after the move. Times are UTC. Nothing here is a secret: no key, no judge pass, no link with its key;
hashes are cut where the full value isn't the point.

## Result

| What | State |
|---|---|
| The fleet | both indexers' `/info`: `"version":"0.52.0"`, epoch 12975; `/network/connections`: twelve of twelve on `/tari/validator/0.52.0`. The indexers answered HTTP 521 for a few seconds at 13:12 and 14:39 |
| Through the move | walletd 0.50.1 and the browser's ootle-wasm 0.50.0 kept working: SealLog checkpoints #2784 to #2804 all committed (5,996 µT before 13:12, mostly 5,997 after), deliveries at 16,157 µT of their 30,000 |
| walletd | **0.52.0** live since 18:16:23 (`34486747…d0d2`; four sources agree); 0.50.1 kept beside it and in `/var/backups/mutis`; down 1.4 s |
| The drill | on a copy, with no network, under every directive of `walletd.service`: no migration, the same accounts and balances, nothing refused by the sandbox |
| The store | unchanged: the same three applied migrations (newest `20261106120000`); balances unchanged (the before and after files differ only in the version) |
| Backup | `/var/backups/mutis/wallet-20261109T181621Z-pre-0.52.0.tar`, 309,913,600 B, root 0600, sha256 `190f3741ae7a8fdba3cad455632ad6cd25e0daf75c47487c75eeb338f612a09b` |
| Tari sends | paused 18:16:16 to 18:16:40 (24 s); nothing was in flight |
| Canary | delivered by walletd 0.52.0 at 18:17:12 (tx `3850e728…fb94`, cost 16,157 of its 30,000, as before), verified 18:17:13 |
| Checkpoint | **#2805 committed** at 18:20:49 through walletd 0.52.0 (chain index 251, tx `40c64b8b…625e`), 5,997 µT of the 1,000,000 `pay_fee` |
| ootle-wasm | `ootle-wasm` and `ootle-wasm-bor` 0.52.0 vendored from the npm tarballs of tag v0.52.0 (run `42628301811`); only the `.wasm` files changed; deployed with this release |
| Suites | as `build` on the server from this tree: sidecar (G4), server, deploy, lint, copy, app core (9 steps), the chain gate against Esmeralda, site, UI |

## Files

| File | What |
|---|---|
| `checksums.txt` | walletd: GitHub's digests, the `.sha256`, the release's list, the bytes on the server, the signed tag, the `--help` diffs; what is installed; the vendored wasm hashes |
| `drill-log.txt` | §3 on a copy under the production sandbox with no network, and its journal |
| `walletd.txt` | §4 (the pause, nothing in flight), §5 (the swap, the backup, the balances), walletd's journal after, the rollback |
| `chain.txt` | the fleet's versions, the move in our logs, every checkpoint's fee across it, and §7 after the swap |
| `scripts/` | `drill.sh` (§3), `swap.sh` (§5), `wsum.py` (read-only walletd summary), `inflight.py` (§4, read-only) |
