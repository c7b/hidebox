<!-- SPDX-License-Identifier: MIT -->
# SealLog: tamper-evident storage receipts

SealLog is the one Ootle template mutis ships. Our server keeps a Merkle tree of SHA-256 hashes: one leaf for every ciphertext we store, one for every file that leaves (its last link burned or expired, or it was deleted), plus padding. On a fixed cadence the chain worker appends the tree's root and size to a SealLog component. Your browser can then check that the tree we committed to on the Ootle contains your ciphertext's hash, and that your file's exit went on the record.

It is **tamper evidence, not privacy**. It hides nothing: the log is public state, and AES-256-GCM already authenticates every chunk you download. What SealLog adds is a public record of what we committed to and when, which nobody can edit afterwards, us included.

Every check runs with one command, as user `build` on ultron: `../check.sh` (see [Tests](#tests)).

## Who can do what

- **Append:** only the key that signed the transaction that created the log, the *writer*. For mutis that is walletd's default key, the `service` account's, which also pays for checkpoints from its public balance (`deploy/ootle/setup-accounts.md` §4).
- **Anything else that changes the log:** nobody. The log has no owner (`OwnerRule::None`). In tari_engine 0.45, changing a component's access rules or its owner, and pointing it at another template (`UpdateComponentTemplate`), all require the owner; with no owner the engine refuses every one of them, the writer key included. So the only code that ever runs against the state is this template's, and no function in it edits or removes a checkpoint.
- **Read and notarize:** anyone.

What the writer key can still do: append any root it likes, as long as the count is a multiple of 64 and larger than the last; stop appending; or create a new log. If that key is lost, the log can't grow again and a new log has to take over.

Earlier builds gave the log an owner, and an owner can swap the code under the component, rewrite every checkpoint and swap SealLog back in one transaction, leaving a state that looks untouched. See [Earlier builds](#earlier-builds).

## Functions

| Function | Who may call it | What it does |
|---|---|---|
| `new(alloc: ComponentAddressAllocation) -> Component<SealLog>` | anyone; the signer becomes the writer | Creates an empty log with no owner. |
| `append_root(&mut self, root: Hash32, leaf_count: u64)` | the writer only | Appends `(epoch, root, leaf_count)`. Refuses a `leaf_count` that isn't a multiple of 64 or isn't larger than the last one. Emits `SealLog.root`. |
| `notarize(&self, commitment: Hash32)` | anyone | Emits `SealLog.notarize` for an opaque 32-byte value. Writes no state. |
| `latest(&self) -> Option<(u64, Hash32, u64)>` | anyone | The newest checkpoint. |
| `get(&self, index: u64) -> Option<(u64, Hash32, u64)>` | anyone | Checkpoint `index` (0 = the first ever appended). `None` past the end, and for the older checkpoints the state no longer keeps. |
| `checkpoint_count(&self) -> u64` | anyone | How many checkpoints have ever been appended. |

A checkpoint is `(epoch, root, leaf_count)`: the Ootle epoch the append ran in, the tree's root, and the tree size it covers.

Events, as they appear in a transaction receipt:

| Topic | Fields (all strings) |
|---|---|
| `SealLog.root` | `index` (decimal), `root` (64 lowercase hex characters), `leaf_count` (decimal), `epoch` (decimal) |
| `SealLog.notarize` | `commitment` (64 lowercase hex characters), `signer` (the transaction signer's public key, 64 lowercase hex characters), `epoch` (decimal) |

The ABI section (`tari_tdef`, the function signatures) is byte for byte the same as in every earlier SealLog build; `check.sh` asserts it.

## The state

The state keeps the newest 64 checkpoints and the index of the first one it keeps:

```
state[0] = [[epoch, root, leaf_count], ...]   oldest first, at most 64
state[1] = first_index                         the index of state[0][0]
```

An indexer's `GET /substates/<component address>` returns it under `substate.Component.body.state`, each root as `{"@cbor": "bytes", "hex": "…"}`. `substate.Component.header` holds `template_address`, `owner_rule` (`"None"`) and the access rules. The `append_root` rule names the writer key as a badge: `NonFungibleAddress` with `resource_address` `resource_0100…00` (the public-identity resource) and `id.U256` = the key's 32 bytes in hex. [`tests/vectors/seallog-state-v1.json`](tests/vectors/seallog-state-v1.json) is that substate after two appends, written by a test that fails when the layout changes.

Why only 64: every call decodes the whole state into the template's WASM memory and `append_root` writes it back. In a state that grows, each append costs more than the last, and appending to a log of 4,096 checkpoints runs out of memory (measured on the research build; 1.0.0 stopped at 2,000 because of it). With 64 kept, an append costs the same however long the log runs ([Costs](#costs)), so the cadence is a price choice, not a limit. No root disappears: each checkpoint's index, root, count and epoch stay in the `SealLog.root` event of its append. That event is part of the transaction receipt, a substate no transaction can write once it exists (`SubstateId::is_read_only` in tari_engine_types 0.45). A receipt only ever needs the latest checkpoint anyway (see [How the browser verifies a receipt](#how-the-browser-verifies-a-receipt)).

## What goes into the tree

The tree is the RFC 9162 §2.1 Merkle Tree Hash with SHA-256: a leaf hashes as `SHA-256(0x00 ‖ leaf_data)`, an inner node as `SHA-256(0x01 ‖ left ‖ right)`. There are three kinds of `leaf_data`, each with its own prefix so one can't pass for another:

| Kind | `leaf_data` | Defined in |
|---|---|---|
| stored | `"mutis-leaf-v1" ‖ item_id (16 bytes) ‖ ct_hash (32 bytes)` | 10-spec §4.4.4; `ct_hash` is the hash your browser computes while encrypting |
| exit | `"mutis-exit-v1" ‖ item_id (16 bytes) ‖ u32be(floor(unix_time / 3600))` | 11-brand §16 P-8; the hour the item left |
| pad | `"mutis-pad-v1" ‖ 32 random bytes` | 10-spec §11.3 |

Exit receipts need nothing from the template: an exit is one more leaf, and its checkpoint is an ordinary `append_root`.

[`tests/vectors/seallog-v1.json`](tests/vectors/seallog-v1.json) is the worked example for the server and the app: one stored file (checkpoint 64), its exit (128), then a window with nothing new (192). It has every root, inclusion proofs, item ids in hex and in the API's base64url, exit hours both as the leaf's hour index and as the API's `exit_hour` (unix seconds), and the RFC 6962 reference vectors. `python3 -I tests/vectors/gen.py --check` rebuilds it from scratch and verifies every proof. On 2026-10-11 its leaves, roots and proofs matched `server/mutis/seallog.py` and `web/app/lib/seallog.js` byte for byte (`../ACCEPTANCE.md` E-5).

## The padding rule

So that the log can't be read as a usage meter (10-spec §11.3):

1. The chain worker appends on a fixed cadence, whether or not anything changed.
2. Before each append it adds pad leaves up to the next multiple of 64 **above** the tree size: at least one pad, at most 64. Pads stay in the tree, so each checkpoint's tree is the first part of the next one.
3. So `leaf_count` grows by 64 at every checkpoint, and by more only when 64 or more records arrived in that window.

The template enforces the result: `append_root` refuses a count that isn't a multiple of 64 or doesn't grow.

## What it proves

- **We committed to this tree at that epoch.** Only the writer key can append, and each checkpoint carries the epoch the chain ran it in.
- **The tree contains your ciphertext's hash.** An inclusion proof from your stored leaf to a checkpoint's root shows that the tree we committed to at that epoch contains the hash your browser computed while encrypting.
- **We put its exit on the record.** An exit leaf in a later checkpoint shows we published, permanently, that the item left in that hour.
- **Checkpoints are only ever added.** Nobody can edit or remove one, the writer included, and `leaf_count` only grows.
- **With `notarize`: this 32-byte value existed by that epoch, and which key sent it.** We notarize release manifests (11-brand §16 P-9) with the writer key, so ours are the events whose `signer` equals the key in the log's `append_root` rule. Anyone else can notarize on the same component under their own key.

## What it does not prove

- **That we deleted anything.** An exit receipt proves we *said* the item left, publicly and for good. It can't prove we kept no copy.
- **That we held your file.** The tree holds hashes. A proof shows we committed to your ciphertext's hash, not that we stored the bytes.
- **That every file is in the log.** You can check that *your* file's hash is in it. Nobody can check from the log that we left nothing out.
- **That each checkpoint extends the last one.** The template checks that `leaf_count` grows, not that the new tree contains the old one. That takes an RFC 9162 consistency proof between checkpoints, which we haven't built (10-spec P2).
- **That this is our only log.** We can create a new one at any time. The ones created so far are listed under [Earlier builds](#earlier-builds); the one in use is `seal_log.component` in `/api/v1/config`.
- **When a file arrived.** The epoch is when the checkpoint ran, up to one cadence interval after the leaf was added, and an epoch is coarse chain time, not a clock.
- **Anything private.** SealLog is not in the privacy capability map.

What anyone can read from it: every checkpoint's epoch, root and padded count, which gives a rough upper bound on how many records (stored files plus exits) we've written, in steps of 64; for each window, how many whole multiples of 64 records arrived in it (usually none); and the writer key, with the fees it pays from its public balance. No name, size, owner, key or link.

## How the browser verifies a receipt

1. Compute the leaf hash locally: for a stored file from its `item_id` and the `ct_hash` your browser computed; for an exit from the `item_id` and the exit hour.
2. Ask our API for the audit path and the checkpoint it leads to: `GET /api/v1/seallog/proof/{item_id}`, or `GET /api/v1/s/{share_id}/exit` for an exit receipt.
3. Recompute the root from the leaf and the path (RFC 9162 §2.1.3.2).
4. Read the log's component from the Ootle with `GET /substates/<component address>`, through our read proxy by default or straight from a Tari indexer with *Check directly*. Only the direct check takes us out of the path. Check the header first: `owner_rule` is `"None"`, `template_address` is the published SealLog template, and the `append_root` rule names our writer key.
5. Find the checkpoint in `state[0]` whose `leaf_count` equals the proof's tree size. The receipt holds if its root equals the recomputed one. Pads stay in the tree, so the latest checkpoint covers every earlier leaf and is always enough. A checkpoint the state no longer keeps is still in its `SealLog.root` event.

## Costs

Measured on Esmeralda on 2026-10-11 with the research build, fees paid from a public account balance, which is refunded down to the real cost (03-ootle-integration §8.3, §9):

| Call | Cost |
|---|---|
| Publish the template (104,272 bytes; walletd's wasm-opt stored 90,769, under the 96 KiB price allowance) | 702,660 µT (0.70 tTARI) |
| `new` | 1,600 µT |
| `append_root` on an empty log | 1,837 µT |
| `notarize` on a log with one checkpoint | 1,461 µT |

`../check.sh --costs` measures this build in the test engine, whose fee table charged 1,501 µT for the research build's first append, about 18% below Esmeralda's 1,837:

| Checkpoints already appended | `append_root` fee (test engine) | WASM points | Component size |
|---|---|---|---|
| 0 | 1,583 µT | 68,878 | 242 bytes |
| 1 | 1,626 µT | 72,049 | 280 bytes |
| 63 | 4,208 µT | 234,849 | 2,698 bytes |
| 64 | 4,212 µT | 237,129 | 2,699 bytes |
| 300 | 4,217 µT | 237,484 | 2,702 bytes |
| 1,000 | 4,219 µT | 237,643 | 2,703 bytes |

`notarize` on a log of 1,001 checkpoints: 1,350 µT. From the 64th checkpoint on, an append costs about 4,220 µT in the test engine, about 5,200 µT at Esmeralda's rate. At Esmeralda's rate that is about 0.50 tTARI a day at one checkpoint every 15 minutes, 0.12 at one an hour, and 0.02 at one every 6 hours. The engine's per-transaction limit (250 million WASM points) is never close.

Publishing this build's exact bytes (106,770 bytes, 8 whole KiB over the 96 KiB allowance, which is charged quadratically) costs more than the research build's publish; the deploy dry run gives the figure.

## Tests

`../check.sh` takes about 10 minutes cold (mostly compiling the engine) and under 20 seconds warm. It runs, in order: the vector check, `cargo fmt --check`, `cargo clippy --all-targets -D warnings`, `tari lint --deny-warnings`, `cargo test` (14 tests running the compiled WASM in the Ootle engine), `tari build`. Then it checks the size budget (110 KiB), that the ABI is unchanged, that the binary embeds no build path, that the tests ran the bytes `tari build` produced, and that the build equals `../dist/seal_log.wasm`.

| Test | Checks |
|---|---|
| `the_writer_appends_and_anyone_reads` | appends by the writer; `latest`, `get` and `checkpoint_count` from a stranger's transaction |
| `only_the_creating_key_can_append` | a stranger's `append_root` is refused with `AccessDenied`; state unchanged |
| `nobody_can_swap_the_code_under_the_log` | the creating key's `UpdateComponentTemplate` is refused with `AccessDenied` (`native.component.update_template`); state unchanged |
| `leaf_count_must_grow` | an equal or smaller count is refused with the template's message |
| `leaf_count_must_be_a_multiple_of_64` | 0, 65 and 100 are refused; 64 and 192 are accepted |
| `checkpoints_keep_epoch_root_and_count_in_order` | five appends at five epochs read back in order |
| `an_empty_log_has_no_checkpoints` | `latest` and `get(0)` are `None`, the count is 0 |
| `get_past_the_end_is_none` | `get(len)`, `get(2^32)` and `get(u64::MAX)` are `None` |
| `append_root_emits_index_root_count_and_epoch` | exact topic, keys and values of `SealLog.root` |
| `anyone_can_notarize_and_the_event_names_the_signer` | a stranger notarizes; the event's `signer` is the stranger's key; the component isn't written |
| `the_state_keeps_the_newest_64_checkpoints` | after 300 appends: the count is 300, `get(0)` and `get(235)` are `None`, `get(236)` and `latest` read back, the component is the same size as after 100 appends, and the last event's `index` is 299 |
| `the_shared_vector_checkpoints_are_valid_appends` | the roots of `seallog-v1.json` (stored, exit, idle window) are accepted and come back byte for byte, in state and in the event |
| `the_header_shows_no_owner_and_names_the_writer` | `owner_rule` is `"None"`; the `append_root` rule's badge is the public-identity resource with the creating key as its id |
| `the_component_state_matches_the_state_vector` | the component substate equals `tests/vectors/seallog-state-v1.json`; `SEALLOG_BLESS=1 cargo test` rewrites it after an intended change |

## Earlier builds

Both earlier builds have the same ABI, and both were published through walletd's `transactions.publish_template`, so the chain holds walletd's wasm-opt output rather than the bytes they were built as. Neither log should take checkpoints.

| Build | Template | Log | Why it is retired |
|---|---|---|---|
| research spike (`research/ootle-spikes/seal_log`) | [`template_e064f38d…6441`](https://ootle-indexer-a.tari.com/substates/template_e064f38d17d57ac1532c75a50945202f47135578d43c2122941fceedc6344441) | [`component_32dae273…e36e`](https://ootle-indexer-a.tari.com/substates/component_32dae273fb4c4c63c77cd1c70ef4e53e07cb56aaa378730fabcd228e45a7e36e), holds one test checkpoint (root `abab…`, count 3) | the owner can rewrite it; `get(2^32)` returned checkpoint 0; its 10,000 cap was unreachable (out of WASM memory at 4,097) |
| 1.0.0 | [`template_b571909e…15bb`](https://ootle-indexer-a.tari.com/substates/template_b571909e116776fa8cd8b22ddf9890554323a848a36ca9d35efb1a6a859a15bb) | [`component_0ff7e892…22aa`](https://ootle-indexer-a.tari.com/substates/component_0ff7e892de37ee65d60e37a5e55cdfe24b11bd9e84cb5af49831e309f6bd22aa), empty | the owner (the `service` key) can rewrite it through `UpdateComponentTemplate`; a 2,000-checkpoint cap and growing fees |

What 2.0.0 changes, all behind the same ABI:

1. No owner, and `append_root` bound to the creating key, so nobody can swap the code or change the rules.
2. The state keeps the newest 64 checkpoints plus `first_index`, so fees stay flat and there is no cap. `get` and `checkpoint_count` count every checkpoint ever appended.
3. `append_root` enforces the padding rule: a multiple of 64, larger than the last.
4. `SealLog.root` gains `index`; `SealLog.notarize` gains `signer`.
5. The build remaps dependency paths, so the binary embeds no build path and rebuilds byte for byte under any user or directory.

The log in use is `seal_log.component` in `/api/v1/config`, and its header names its template; `deploy/ootle/setup-accounts.md` records both.

## Build and publish

`../check.sh --dist` writes `../dist/seal_log.wasm`, `SHA256SUMS` and `BUILD-INFO.txt` (toolchain, input hashes, ABI and metadata hashes). Dependencies are pinned exactly (`tari_template_lib =0.34.0`, `tari_template_test_tooling =0.45.0`, `tari_ootle_template_build =0.14.0`, and `serde_json =1.0.152` for the tests, already in the tree) and `Cargo.lock` is committed; it resolves the same 391 packages as the research build.

Publish the exact `dist/seal_log.wasm` bytes with a `PublishTemplate` instruction. walletd's `transactions.publish_template` runs wasm-opt first and stores different bytes, which is what happened to both earlier builds. Then anyone can tie the chain to this source:

- `../check.sh --onchain <template address>` fetches the template from a public indexer, checks that the address commits to the bytes it returned (the engine derives it from the author key and the binary), and says whether they are `dist/seal_log.wasm` byte for byte.
- `python3 -I ../wasm_check.py address <publisher key> ../dist/seal_log.wasm` prints, before publishing, the address a publish signed by that key will create.

Publishing, creating the log and submitting metadata are deploy steps (10-spec §11.4, D-12), not part of this directory.
