<!-- SPDX-License-Identifier: MIT -->
# SealLog on the Ootle mainnet (2026-11-12)

The launch trigger (`deploy/ootle/launch.py`, armed as `deploy/ootle/mainnet-launch.md` §1 says) published SealLog
and created its log by itself, unattended, once the network was live and the burn's claim had landed. The template is
the V2 build in `template/dist-v2/`, byte for byte.

| | |
|---|---|
| Template | `template_494d34a5f55bcef614655c9f8b7fdcb672f1d086467fc96816c0a93a4a5c8472`, author `9250fcab…4762` (the `service` account's key), epoch 38542 |
| Publish transaction | `dbb5173483176a9cadbc82bec4b981d44dd178eb8dfa750febe1e1462bc74dca`, Commit, 842,961 µT; finalized 2026-11-12 18:28:36 UTC (the indexer's record of it); its result says 2026-11-12 18:28:34.0 |
| Log | `component_45efaa40c370fa98b86ad59bd395694a241313d741f81ed30bc772b88ef84690`, transaction `ba9792cfd15ad29ba4465007e7a89048d0a223454389b8a3f093c62ba5e44d9d`, Commit, 2,414 µT; owner `None`, upgrade `Locked`, `append_root` only for the author's key |
| From outside | `template/check.sh --v2 --onchain template_494d34a5f55bcef614655c9f8b7fdcb672f1d086467fc96816c0a93a4a5c8472 --indexer https://indexer-a.ootle.tari.com`: `wasm-check.txt`, byte for byte |
| Then | mainnet.hidebox.app moved from its staging rehearsal to the mainnet (`deploy/ootle/flip-to-mainnet.sh`) and was deployed from this commit's tag |

Files: `evidence.json` (what the trigger wrote), `launch.log.jsonl` (its events), `wasm-check.txt`, and the raw answers
of https://indexer-a.ootle.tari.com, fetched 2026-11-12T18:29:20Z. A transaction's full result may not stay on the public indexers;
the template's record keeps its epoch for good.

- `indexer/component-substate.json`
- `indexer/epoch-manager-stats.json`
- `indexer/log-receipt.json`
- `indexer/log-result.json`
- `indexer/log-transaction.json`
- `indexer/publish-receipt.json`
- `indexer/publish-result.json`
- `indexer/publish-transaction.json`
- `indexer/template-substate.json`
