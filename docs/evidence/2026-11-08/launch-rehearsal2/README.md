<!-- SPDX-License-Identifier: MIT -->
# The launch trigger's V2 rehearsal on Esmeralda (2026-11-08)

`deploy/ootle/mainnet-launch.md` §1 step 6: the mainnet's launch trigger, unattended, with the V2 build it will
publish on the mainnet, against Esmeralda on Ootle 0.50 (walletd 0.50.1). Armed from the tag
`mainnet-launch-candidate-2026-11-11` (6ebbe16) on the staging instance:

```sh
sudo MUTIS_INSTANCE=mainnet bash <tree>/deploy/ootle/launch-arm.sh --label rehearsal2 --network esmeralda \
  --walletd-port 5102 --account rehearsal --wasm <tree>/template/dist-v2/seal_log.wasm
```

The `rehearsal` account was funded first with 1,000 tTARI from the Esmeralda faucet
(`accounts.create_free_test_coins`), test money only, into its public balance.

| | |
|---|---|
| Steps | `indexer → walletd → funds → publish → log → evidence → done`, all in the first pass (05:58:44 to 05:58:58 UTC) |
| Template | `template_45a467821933d68b39f807bf8d0b1d9641128bbbd4c43aaf215de012a0b0b82e`, author `90ac469b…ee24` (the `rehearsal` key), epoch 12949, publish tx `376e2c38…d713`, Commit, 842,962 µT (the dry run's figure) |
| Log | `component_e7a58799b7adb1dcb00ae9ab4bb01306703650eb906b3064e815de9ae062b639`, tx `e556f0d4…c55d`, Commit, 2,412 µT; owner `None`, upgrade `Locked`, `append_root` only for the author's key |
| From outside | `wasm_check.py onchain … --wasm template/dist-v2/seal_log.wasm`: 107,038 bytes, sha256 `00ca5f34…878f`, ABI equal, byte for byte (`wasm-check.txt`) |
| After | disarmed (`launch-arm.sh --label rehearsal2 --disarm`); its state stays with the instance |

Files: `evidence.json` (what the trigger wrote), `launch.log.jsonl` (its events), `wasm-check.txt`.
