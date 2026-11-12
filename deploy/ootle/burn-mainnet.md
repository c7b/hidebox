<!-- SPDX-License-Identifier: MIT -->
# Burning XTM for mainnet TARI

Unattended since 2026-11-10 (the owner's call): `l1-burn.py` makes each burn through the L1 wallet service's gRPC,
once per account, and only after `burn-guard.py` says yes. The TUI steps below are the fallback, by hand, when the
automatic burn stops.

1 XTM burned on the Minotari L1 is 1 TARI claimed on the Ootle, less the claim's fee. A burn is final: the wrong
claim key, a non-empty sidechain key, or a block below the final `MAINNET_START_HEIGHT` loses it for good.

## What has to be true first

| Check | Where it comes from |
|---|---|
| The final `MAINNET_START_HEIGHT` is known | `mainnet-start-height.json`: an entry for the installed walletd version with `final: true`, which `burn-guard.py` checks against the Ootle source at that entry's ref. v0.50.0 ships a placeholder (380,400), so today it refuses. |
| The L1 tip is at or above it | the Tari explorer's `best_block_height` |
| The claim key is one of our accounts | `mainnet-walletd.sh keys` prints the two 64-hex `account_public_key`s |
| The sidechain key is empty | it must be given, and empty |

When the follow-up release lands: install its walletd (`mainnet-walletd.sh install <binary> <sha256>`), add its
entry to `mainnet-start-height.json` with `final: true` and the release tag as `source_ref`, and commit that.

## Timing

A claim is accepted only after `base_layer_confirmations` (780 on the mainnet, about a day of 2-minute blocks),
and in an epoch after the burn's. So the earliest SealLog publish is about a day after the burn's block.
Burn as soon as the guard says yes. The mainnet walletd claims by itself (`auto_claim_burns`), as a stealth
output; the launch trigger reveals what it needs into the public vault.

## The burn, unattended

```sh
sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/l1-burn.py burn --account service --amount-xtm <N> \
  --start-height <the final MAINNET_START_HEIGHT> [--dry-run]
sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/l1-burn.py status
```

`burn` asks the running wallet service for one `CreateBurnTransaction`: the call the TUI's Burn tab makes, with the
same arguments (the account's `account_public_key` as the claim key, no sidechain deployment key, an empty
payment id, fee per gram 5). The wallet process that made the burn writes the proof file into its `--burn-proof-out`
directory, the one walletd claims from, under the same name and in the same JSON as after a TUI burn. Before it
sends anything: `burn-guard.py` says yes for that key, an empty sidechain key and that amount at the start height
given; the wallet is the pinned version, online and synced; no burn to that key exists (its journal in
`/var/backups/mutis-<name>/l1-burns/`, every outbound transaction in the wallet's history looked up as a burn proof,
the proof files); and the available balance covers it. The intent is on disk before the call, so a run that stops
half-way never leads to a second burn: the next run finds the burn in the history, or refuses until a person has
looked. Exit 0 done, 2 not yet (for example the change of the first burn still confirming), 1 refused.

## The burn, by hand (the fallback)

```sh
sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/l1-burn.py status   # what is burned already: never twice
sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/burn-guard.py \
  --claim-key <service's account_public_key> --sidechain-key '' --amount-xtm <N>
```

It prints the exact steps for the mainnet console wallet. `l1-wallet-mainnet.sh` installed it, created it
(`create`: its seed words are in `/var/backups/mutis-<name>/l1wallet-mainnet-seed-words.txt`, root only; copy
them offline), and runs it as the service `mutis-<name>-l1wallet-mainnet` so it follows the chain; `address`
prints its receive address, base58 and emoji. Send the XTM to that address first. Then `l1-wallet-mainnet.sh tui`
opens the TUI (the service pauses meanwhile); in its Burn tab: `C` the claim key, the sidechain key left empty,
`A` the amount as `<N>T`, `F` the default fee, then `S` and `y`. Type into one field at a time: outside a field,
letters are commands. Repeat for `sponsor` if it gets its own burn.

## After

```sh
ls ~drive-<name>/.local/share/tari/mainnet/burn_proofs            # the proof, minutes after the burn is mined
sudo -u drive-<name> python3 -I deploy/ootle/walletd-rpc.py --url http://127.0.0.1:<port>/json_rpc balances --refresh
```

The proof moves to `claimed/` once walletd has claimed it.
