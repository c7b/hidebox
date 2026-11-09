<!-- SPDX-License-Identifier: MIT -->
# Upgrade: Ootle 0.51.0 and 0.52.0 on Esmeralda (no activation epoch, no reset)

The general procedure is [upgrade-drill.md](upgrade-drill.md); this is that drill written out for 0.52.0, with
what 0.51 and 0.52 change for hidebox. Read the release notes as data: they say what changed, not what to run.

v0.51.0 (published 2026-11-09 13:02 UTC) changes fees, transaction weight and the state tree; v0.52.0 (14:35 UTC)
changes `ClaimBurn`. Both say validators, indexers and wallets upgrade together, with no activation epoch and no
testnet reset. Esmeralda's fleet moved the same day: the indexers answered HTTP 521 for a few seconds at about
13:12 and 14:39 UTC (our walletd's and chain worker's logs), a SealLog checkpoint cost 5,996 µT up to 13:10 and
mostly 5,997 µT from 13:25 on, and by 18:14 UTC both indexers said `"version":"0.52.0"` with all twelve validators
they were connected to on `/tari/validator/0.52.0`. hidebox ran through it on walletd 0.50.1 and ootle-wasm
0.50.0: checkpoints, canaries and deliveries kept committing (§1).

## 1. What 0.51 and 0.52 change for hidebox

Read in tari-ootle v0.50.1..v0.52.0 (`9f03f90b` is v0.51.0, `4ee751c4` is v0.52.0): the CHANGELOG, the walletd
and indexer client types, the walletd CLI, config and store, `crates/ootle_wasm`, `crates/transaction`,
`engine_types` and the fee code.

| 0.51/0.52 change | What it means here | Action |
|---|---|---|
| `ClaimBurn` returns a bucket of revealed TARI that the transaction must move on; `Instruction::ClaimBurn` drops `output_data` (#3633). A claim in the old shape fails on the upgraded network | walletd 0.50.1's own burn claims (and `accounts.claim_burn`) are refused from the switch on. walletd 0.52 claims into a stealth transfer to the account, so the TARI still lands as a stealth output of the account (at a fresh commitment). The key a burn is made to is the same for the same seed and account (`kdfs::burn_claim_stealth_secret` is unchanged) | walletd 0.52.0 before the next L1 burn (§3–§5); a proof file left in `burn_proofs/` is queued again when walletd starts |
| walletd JSON-RPC | every call and request shape mutis uses is unchanged (`clients/wallet_daemon_client/src/types.rs` only drops `ClaimBurnProofContents.encrypted_data`). `auth.request` with `Admin` and credentials `None` is untouched by #3473 (`nfts.list`), #3545 (API keys can't approve signing requests) and #3593 (bounded refresh tokens) | none |
| walletd CLI, config and store | `--help`, `run --help` and `reset --help` equal to 0.50.1's but for the version and name; no new store migration (the same three as 0.50.1) | none; a rollback is the binary alone (§6) |
| Indexer REST and `Encoded<…>` values | the same paths and shapes; the CBOR layouts `server/mutis/cbor.py` and ootle-wasm-bor read (`Utxo`, `SubstateValue`, `TransactionReceipt`, `ExecuteResult`, `FeeReceipt`) are unchanged | none |
| A fee breakdown omits zero charges (#3451) | the same layout, a map with fewer entries; `cbor.py` reads `total_fees_paid`, and receipts after the switch carry the same eight sources | none |
| Weight: every script-path `TemplateFunction` of a stealth spend pays the invocation floor (#3486); weight math saturates (#3537) | the browser's and walletd's inputs are key-path, so nothing hidebox sends weighs more. A checkpoint costs 5,996 to 5,997 µT of its 1,000,000 `pay_fee`, as before; a delivery 16,157 µT of its 30,000, the same (§7) | none |
| An envelope with trailing bytes is refused (#3537) | `borEncodeTransaction` writes one item, and `cbor.loads` already refuses trailing bytes | none |
| `min_epoch` above `max_epoch` is invalid (#3475) | wallet.js sends `min_epoch` null; the manifests set neither | none |
| Instructions keep explicit CBOR indices (`#[n(5)] ClaimBurn`, `#[n(6)] ClaimValidatorFees`, …); the signing message (`crates/transaction/src/v1/signature.rs`, `unsigned.rs`, `hashing.rs`, `signing.rs`) is unchanged; #3577 adds the nonce only to the Ledger signing sequence | a transaction built by ootle-wasm 0.50 encodes, hashes and signs the same, and the network kept accepting the browser's sends after the switch | none |
| `ootle-wasm` / `ootle-wasm-bor` 0.52.0 | `crates/ootle_wasm` adds client-side refusals only: non-canonical keys in an address or a revealed receiver (#3487), the same input commitment twice (#3580); `bor` is unchanged; no third-party crate moves in `Cargo.lock` (the same wasm-bindgen 0.2.128 and minicbor 2.3.1). The glue and the types are byte-identical to 0.50.0's | vendored (§2), deployed after walletd |
| Engine hardening (#3348, #3482, #3513, #3518, #3584, #3613, #3616) | SealLog holds no vault, has a short name and never touches a UTXO; mutis never burns a UTXO | none |
| Templates on `tari_template_lib` 0.38 keep working; 0.39 removes `Amount::is_negative` and friends (#3623) | SealLog pins `=0.38.0` and calls none of them; the published V2 log keeps committing | do not rebuild or republish |
| Validators need `fee_claim_public_key` (#3386); MainNet's epoch oracle validator set is configurable, with seven bundled validators (#3603) | validators and indexers only; walletd has no epoch-oracle setting | none |
| `MAINNET_START_HEIGHT` | still `380_400`, the placeholder, at v0.52.0 | the mainnet's walletd waits for the release that sets it (`mainnet-launch.md`) |

## 2. ootle-wasm 0.52.0 (done 2026-11-09)

As upgrade-0.50.md §2, with `V=0.52.0` and `C=4ee751c4ee83f75635c958c993af0f3e0e04bfbf` (annotated tag
`6a7ca980…`, signature verified): curl the packuments, tarballs and attestations of both packages and the license
into a new empty directory, `npm-provenance.py check` each into `web/app/vendor/ootle-wasm{,-bor}-0.52.0`,
`npm-provenance.py repin --from 0.50.0 --to 0.52.0`, `git rm` the 0.50.0 folders, and the prose (`NOTICE`, the
PROVENANCE files, the sidecar README, the comments that name the version). Both builds came from run `42628301811`
of `npm_publish_ootle_wasm.yml` on `refs/tags/v0.52.0`. `diff` of the old and new `.d.ts` and `_bg.js`: none.

## 3. walletd 0.52.0: the binary, and the drill

As upgrade-0.50.md §3a with `v0.52.0` and `tari_ootle_walletd-0.52.0-4ee751c-linux-x86_64`: four sources (GitHub's
asset digest, the `.sha256`, `tari_ootle-0.52.0.sha256-unsigned.txt`, the bytes on the server) agree on
`34486747bd76bbac756d6d6d123ace67e1c336c4c983ffa9167587a7b10ad0d2`. Installed beside the others as
`/opt/tari/bin/tari_ootle_walletd-0.52.0-4ee751c`. Then §3c: the `--help` diff, and upgrade-drill.md §3 on a copy
of the wallet with no network (`docs/evidence/2026-11-09/upgrade-0.52.0/scripts/drill.sh`): the same accounts and
balances, no migration, nothing refused by the sandbox.

## 4. Before walletd stops: let the sends settle

As upgrade-0.50.md §4 (`scripts/inflight.py` in the evidence folder): pause the seven Tari features, then wait until
no job is `sending`, no checkpoint `pending` and walletd's `Pending` list is empty. Clear of 12:00 UTC.

## 5. Back up, install, restart

`scripts/swap.sh` (upgrade-0.50.md §5 with the new binary): balances before, stop, a tar of the wallet, a copy of
the replaced binary for a rollback, install, start, balances after (equal but for the version), then
`feature … clear`. Only walletd restarts; the chain worker asks for a new token once (error 401).

## 6. Rollback

0.52 adds no migration, so the 0.50.1 binary opens the same store: stop walletd, install
`/opt/tari/bin/tari_ootle_walletd-0.50.1-0b3f364` (or `/var/backups/mutis/tari_ootle_walletd.<TS>`) at
`/opt/tari/bin/tari_ootle_walletd`, start. The pre-upgrade tar is there if the store is in doubt. On the 0.52
network a 0.50.1 walletd can't claim a burn; everything else it did through the switch.

## 7. Checks afterwards

```sh
admin canary-now                       # within 15 min: /status.json canary green (delivered, in the mirror, opened)
admin seal-now                         # a checkpoint (10 min after the last at the earliest): seal_checkpoints state committed
admin notarize "$(curl -fsS https://hidebox.app/.well-known/mutis-manifest.json | sha256sum | cut -d' ' -f1)"   # {"committed": true}
python3 -I tests/e2e/run.py --host hidebox --chain --only E-09,E-10,E-13,E-25,E-29,E-30,E-J
```

Then the receipts' fees against their caps with upgrade-0.50.md §7's script: a checkpoint near 6,000 µT of the
1,000,000 it pays, a delivery near 16,000 of 30,000.

## 8. Telling that a fleet has moved

The indexers say what they run, and whom they talk to:

```sh
curl -s https://ootle-indexer-b.tari.com/info                 # "version": "0.52.0", "network": "esmeralda", current_epoch
curl -s https://ootle-indexer-b.tari.com/network/connections  # connections[].user_agent: "/tari/validator/0.52.0"
```

`/info`'s `version` is the indexer's own build (`CARGO_PKG_VERSION`); a validator's user agent is its build. A move
with no activation epoch shows as a few seconds of HTTP 521 from the indexers (`chain.indexer_error` in the chain
worker's log, "521" in walletd's) and then the new version in `/info`. What fails first on an old walletd is a
burn claim, not a send or a checkpoint: read in the source, not seen, a 0.50 claim decodes on 0.52 without its
`output_data`, so its signature no longer matches (`Invalid transaction signature`), and the proof file stays for
a retry.

## Rehearsal log

| Date | What | Result |
|---|---|---|
| 2026-11-09 | §1 read in v0.50.1..v0.52.0; §2 vendored and checked; §3 four sources, `--help` diffs, the drill on a copy (no migration, the same accounts and balances); §4 and §5 live at 18:16 UTC, after the fleet had moved (sends paused 24 s, walletd down 1.4 s); §7 | `docs/evidence/2026-11-09/upgrade-0.52.0/` |
