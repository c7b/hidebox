<!-- SPDX-License-Identifier: MIT -->
# Notes for the integrator (template builder)

The fix pass after `REVIEW-devil.md` produced **seal_log 2.0.0** (`dist/seal_log.wasm`, 106,770 bytes, sha256 `9af71aa2…d6f2`). It has the same ABI as every earlier build, but the code, the state layout and two event payloads changed, so it needs its own publish and a new log. **Do §1 to §3 before `features.seallog` is turned on.** Until then nothing on chain depends on the old log, which is empty.

## 1. Publish 2.0.0 and create a new log (deploy builder)

1. **Publish the exact `dist/seal_log.wasm` bytes**, not walletd's wasm-opt output. `transactions.publish_template` runs wasm-opt and stores different bytes; that is why both live templates (`e064…`, `b571…`) can't be tied to any source (`ACCEPTANCE.md` E-6). walletd's `transactions.submit` takes a pre-built transaction with raw instructions (`ootle-skills/claude-code/tari-manifest/references/wallet-daemon-api.md`). Build one with a single `PublishTemplate` instruction carrying the binary, and dry-run it first. The binary has only the `tari_tdef` custom section, which the engine requires; it is 8 whole KiB over the 96 KiB price allowance, and the excess is charged quadratically, so read the fee from the dry run.
2. **Before publishing**, `python3 -I template/wasm_check.py address <publishing key hex> template/dist/seal_log.wasm` prints the address the publish will create. The author is the key that seals the publish transaction: for `b571…` it was `2846d6ff…c50a`, for `e064…` the `service` key `9c686313…5420`.
3. **After publishing**, `template/check.sh --onchain <template address>` must print `the chain runs seal_log.wasm byte for byte`. Please wire the same command into `tools/verify-deploy.py`, and give `/security` a line saying anyone can run it.
4. **Create the log:** `deploy/ootle/publish-template.sh instantiate <template>` works unchanged, since its manifest calls `SealLog::new(alloc)`. The signer becomes the writer: with walletd 0.45 that is the `service` key, the same key that appends today (G5 fallback). Dry-run it, then check the new component's header on an indexer: `owner_rule` must be `"None"`, and the `append_root` rule's badge id must be the `service` public key (`ACCEPTANCE.md` E-2 shows the shape). Appends keep working through `submit_manifest`: the signer's badge satisfies `rule!(public_key(writer))` exactly as it satisfied 1.0.0's `ByPublicKey` owner check (`tracker_auth.rs` checks both with `contains_badge`).
5. **Retire the old logs:** point `ootle.seallog_component` at the new log, and list `component_0ff7e892…22aa` (1.0.0, empty) and `component_32dae273…e36e` (research, one test checkpoint) as retired in `/evidence.json` with the new one. The README's "That this is our only log" bullet points readers to that list and to `/api/v1/config`.
6. **Fallback, if walletd can't submit a raw publish:** publish with `transactions.publish_template`, then save the chain's bytes with `python3 -I template/wasm_check.py onchain <addr> --out template/dist/seal_log.onchain.wasm` and commit them with their sha256. The README's "Build and publish" and `BUILD-INFO.txt` must then say plainly that the chain runs walletd's wasm-opt output of this build, which can't be rebuilt here, and `check.sh --onchain <addr> --wasm dist/seal_log.onchain.wasm` becomes the check. Tell me (or edit `template/`) and I'll make those edits.
7. `transactions.submit` also takes `signing_key_id`. If it signs with the `operator` key, G5 may pass after all (log created and fed by `operator`). That is worth one dry run, but `service` is fine.
8. `Cargo.toml` sets `supersedes = b571909e…` for the metadata submission (Q4).

## 2. Server (`server/mutis/seallog.py`, `chain_worker.py`)

The new template refuses two things the current server does:

- **Padding: always add at least one pad.** 2.0.0 refuses a `leaf_count` that doesn't grow, so the first idle window would fail with `append-only: leaf_count must grow`. In `make_checkpoint`, `for _ in range(-(placed + waiting) % PAD_TO)` becomes `for _ in range(PAD_TO - (placed + waiting) % PAD_TO)`. That is 10-spec §11.3's "next multiple of 64 **above**", and it stops the log showing which windows were idle. It costs at most 64 rows per window and nothing on chain.
- **A refused append** (for example a resubmitted checkpoint that already committed) fails with a `TemplateError` carrying that message. Settle it as failed and let the next checkpoint commit the leaves; `latest()` on chain says what committed.

And three changes so the copy stays true:

- **Cadence is config.** `CHECKPOINT_INTERVAL_S = 6 * 3600` is hard-coded; make it `seal_log.checkpoint_interval_s` (11-brand §8.3). With the bounded state, an append costs the same at any log length: about 4,220 µT in the test engine, about 5,200 µT at Esmeralda's rate. **Recommendation: 900 s (15 minutes)**, the brand default, so judge steps A3 and B5 (site B7) see the exit receipt in the same session. That costs about 0.50 tTARI a day, about 25 tTARI from Oct 12 to Dec 1, against the 16.29 tTARI public balance `service` had at setup. Top `service` up by about 15 tTARI from `sponsor` before turning SealLog on. The alternative is 3600 s (about 0.12 tTARI a day), with A3/B5/B7 and C7 reworded to "within the hour". Either way the server tree grows by at least 64 leaves per window: at 15 minutes, 6,144 rows a day, and `levels()` hashes the whole tree once per checkpoint. That is fine for months.
- **Name the component and the chain index in each checkpoint.** `checkpoint_json` should include `component` (the log's address) and the chain's checkpoint index, the `index` field of the `SealLog.root` event in the append's receipt. The server's `idx` also counts failed checkpoints, so "SealLog checkpoint #{n}" in the UI should show the chain index.
- **Shared vector:** please have the server tests load `template/seal_log/tests/vectors/seallog-v1.json`. Its fields now match the API: `item_id_b64u`, `exit_hour_unix` (the API's `exit_hour`), and `exit_hour_index` (what goes in the leaf). Its third checkpoint (192) is an idle window under the new rule. Against today's server code its leaves, roots and proofs match byte for byte, and only the idle-window padding differs (`ACCEPTANCE.md` E-5).

## 3. App (`/verify`, app-core)

- **State layout:** `state[0]` is unchanged (`[epoch, {"@cbor":"bytes","hex":…}, leaf_count]`, oldest first) but holds at most the newest 64 checkpoints; `state[1]` is `first_index`, the index of `state[0][0]`. The API proves against the latest checkpoint, so the match is always in `state[0]`.
- **Check the header before trusting a root.** In the `substate.Component.header` of `GET /substates/<component>`:
  - `owner_rule == "None"`
  - `template_address` is the published 2.0.0 template
  - `access_rules.method_access.append_root.Restricted.Require.Require.NonFungibleAddress` has `resource_address` = `resource_0100…00` (64 hex characters, `01` then zeros) and `id.U256` = our writer key in hex.

  That makes "nobody can rewrite it" checkable in the browser, not just asserted. Today `checkpointsFromComponent` reads only `body.state`.
- **Fixtures:** replace `web/app/tests/vectors/seallog-component.json`, which holds the research log's junk state (`abab…`, count 3, an owner), with `template/seal_log/tests/vectors/seallog-state-v1.json`. Its keys are sorted (serde_json); key order doesn't matter to a JSON parser. Load `seallog-v1.json` in the app tests too. `exitLeaf(id, unixSeconds)` gives the vector's leaf from either `exit_unix` or `exit_hour_unix`; I checked both (`ACCEPTANCE.md` E-5).
- **Notarizations** (P-9): accept a release-manifest notarization only when the event's `signer` equals the writer key from the header.

## 4. Copy (site, app-ui; spec text for the integrator)

- **C22** "It proves what we held and when" overclaims: a proof shows a committed hash, not that we held bytes. Suggest "It shows that the tree we committed to at that epoch contains your file's ciphertext hash."
- **`/security`, what SealLog leaks:** "a rough upper bound on how many records (stored files plus exits) we've written, in steps of 64; for each checkpoint window, how many whole multiples of 64 records arrived (usually none); and the writer key, which is the same `service` key that holds our public tTARI."
- **`/security`, what SealLog guarantees:** the log has no owner, so nobody, us included, can change its rules or the code behind it; anyone can check `owner_rule: "None"` on an indexer.
- **A3 / B5 / B7 / C7:** these depend on the cadence chosen in §2.

## 5. Spec corrections (10-spec, for `docs/`)

- §11.1: "the log only grows" → "checkpoints are only ever added". Without consistency proofs, leaf-level append-only is unproven; the README says so.
- §11.2: `new` → no owner, `append_root` bound to the creating key; no cap; `leaf_count` must be a multiple of 64 and larger than the last; the state keeps the newest 64 checkpoints plus `first_index`; `root` events carry `index`, `notarize` events carry `signer`.
- §11.3: pad to the next multiple of 64 **above** the size (at least one pad), and the template enforces the result.
- 03-ootle-integration §7.5 says the leaves are `BLAKE2b-256(ciphertext)`; 10-spec §4.4.4 (SHA-256, RFC 9162) is what everything implements.

## 6. What I changed on the server

- `rustup component add rustfmt clippy` for user `build`'s stable toolchain (in the first pass). These are official components, user-local, installed with no sudo and no apt. T-01 asks for fmt and clippy, and neither was installed; the spec's CI form `tari lint --no-clippy` doesn't need them. Please ratify, or revert with `rustup component remove rustfmt clippy`, after which `check.sh`'s rustfmt and clippy steps fail.
- Work directory `/home/build/work/template`. Its `exp/` (rebuilds, the out-of-memory exploration, the reproducibility probe, the cold-run copy) is disposable.
- ssh to the server refuses connections when several open in quick succession (it looks like a `ufw limit` rule); a multiplexed connection (`ControlMaster=auto`, `ControlPersist`) avoids it.

## 7. Repo housekeeping

- The root `.gitignore` ignores every `dist/`; `template/.gitignore` re-includes `template/dist/`.
- `wasm_abi.py` is gone; `wasm_check.py abi` replaces it. Nothing outside `template/` used it.
- `Cargo.toml` metadata (`repository`, `homepage`, `documentation`) uses `https://github.com/c7b/mutis`. Those fields feed only the metadata hash, not the WASM.
- After any edit to `src/lib.rs`, `Cargo.toml`, `Cargo.lock` or `build.rs`, run `./check.sh --dist` once so `BUILD-INFO.txt` lists the final input hashes. Doc-comment edits change the metadata hash, not the WASM.
