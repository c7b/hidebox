<!-- SPDX-License-Identifier: MIT -->
# Devil's-advocate review: template/ (SealLog)

Reviewer: devil's advocate for the template component, 2026-10-11. I read every file in `template/`, re-ran the builder's checks on ultron in my own work dir (`/home/build/work/review-template`), read the engine sources in `/home/build/.cargo/registry`, and checked the chain through the public indexer. I didn't edit any of the component's files; this file is the only one I wrote here.

## Verdict

The build is careful. The pins and lockfile are exact, `dist/` rebuilds byte for byte in a second directory, the `get()` aliasing fix is real, the "What it does not prove" section is the most honest text in the repo, and the cost table matches its own arithmetic. **But the central claim is false for the code as shipped.** The log's owner can swap the code under the component and rewrite every checkpoint in one transaction. I demonstrated it in the test engine; the fix is six lines and I tested that too (H1). Two other problems would also cost points with the Council: the chain runs different bytes from `dist/`, so nobody can tie the live template to this source (H2), and the 6-hour cadence the template forces breaks step B5 of the judge script (H3).

**Do all three before `features.seallog` is turned on.** H1 and H2 both need a new publish and a new component. Today that costs 0.7 tTARI and orphans nothing; once checkpoints start, every receipt would point at a log we then have to abandon.

## What I ran

| Check | Result |
|---|---|
| `./check.sh` on a fresh copy (`/home/build/work/review-template/template`, cold) | `ALL CHECKS PASSED` in 8 m 20 s. 12 passed, 1 ignored. `seal_log.wasm 104286 bytes sha256 837391ce…e493`, the same as `dist/`, so the build reproduces in a second directory. ABI `b4b4134b…e494`. |
| On-chain template, `GET https://ootle-indexer-a.tari.com/substates/template_b571909e…15bb` (published by the deploy builder from this `dist/`, `deploy/ootle/setup-accounts.md` §4) | `binary` is **90,785 B, sha256 `e8064f7a…d99b`**, not 104,286 B / `837391ce…`. Its `tari_tdef` hash is `b4b4134b…e494` (the same ABI). Author `2846d6ff…c50a`, `at_epoch` 12136, `metadata_hash` null. |
| Template address recomputed with stdlib (Appendix B) | H(author, **on-chain bytes**) = `b571909e…15bb` (matches). H(author, **dist bytes**) = `7be0f78a…1084` (doesn't match). |
| Live log `component_0ff7e892…22aa` | `owner_rule: {"ByPublicKey": "9c686313…5420"}` (the `service` key), `state: [[]]`, the access rules as written in `lib.rs`. |
| Probe: owner swaps the code (Appendix A) against the **shipped** `lib.rs` | `devil_owner_swaps_code_and_rewrites_history ... ok`. In **one** owner-signed transaction (switch to a "Rewriter" template, call `rewrite`, switch back to SealLog), two checkpoints became `checkpoint_count=1 latest=Some((7, Hash32([238, …]), 64))`. Afterwards the component points at SealLog again. |
| Same probe on the **fixed** `lib.rs` (Appendix A) | Swap refused: `Execution failure (AccessDenied): … You must be the owner to perform this action: native.component.update_template`. All 12 existing tests pass. `cargo clippy -D warnings` is clean, `tari build` OK, 106,134 B, **ABI hash unchanged** `b4b4134b…e494`. |

## Findings, most severe first

### H1 (high) — The owner can rewrite the whole log. The README says nobody can.

- **Where:** `seal_log/src/lib.rs:44` `.with_owner_rule(OwnerRule::OwnedBySigner)`. The claims it breaks are in `seal_log/README.md:6` ("a public record we can't quietly rewrite"), `:32` ("Nobody, the owner included, can edit or remove a checkpoint"), `:74` ("Checkpoints can't be edited or removed"), and `lib.rs:9-10`.
- **Why it's real:** tari_engine 0.45 has `Instruction::UpdateComponentTemplate { component, new_template, migrate }` (`tari_engine-0.45.0/src/transaction/processor.rs:450-560`). Its only gate is `check_component_ownership(NativeAction::UpdateComponentTemplate)`. With `OwnedBySigner` (live: `ByPublicKey(9c6863…)`), the creator's key can point the component at any published template, run that template's code against the state, and point it back. The README's argument ("the engine only lets a component's own code change its rules, and SealLog has no function that does") checks `SetAccessRules` and misses this instruction. After my probe the component's header and state look clean. The browser verification in README §"How the browser verifies" reads only that state, so it can't detect the rewrite. Kinkajou needs about a minute to find this.
- **Fix (tested, Appendix A):** in `new`, bind `append_root` to the creating key and remove the owner:
  ```rust
  let writer = CallerContext::transaction_signer_public_key();
  … .method("append_root", rule!(public_key(writer)))
  … .default(rule!(deny_all)),
  )
  // No owner: nobody can change these rules or swap the template under the log.
  .with_owner_rule(OwnerRule::None)
  ```
  `OwnerRule::None` fails every ownership check (`tracker_auth.rs:127`), so the engine refuses `UpdateComponentTemplate`, `SetAccessRules` and `SetOwnerRule`. The ABI hash doesn't change. Then:
  - Add a test that the creator's `update_component_template(log, <SealLog's own address>)` fails with `AccessDenied` mentioning `native.component.update_template`. No second crate is needed: the ownership check runs before anything else.
  - Rename `only_the_owner_can_append` to `only_the_creating_key_can_append`.
  - Update the README (`:16-17`, `:32`, `:71`). Keep the honest residue: the writer key can still append any root it likes, and a lost key ends the log.
  - Ask (via the integrator) for `/verify` to also check the component header: `owner_rule == "None"` and `template_address ==` the published SealLog template. That makes "nobody can rewrite it" checkable in the browser, not just asserted. `web/app/lib/seallog.js:57` reads only `body.state`.
  - Republish, create a new log, and retire `component_0ff7e892…` before `features.seallog` goes on. The research log `32dae273…` has the same hole.

### H2 (high) — The chain runs bytes that nobody can rebuild from this repo

- **Where:** `dist/BUILD-INFO.txt` (last line), `seal_log/README.md:102`, `deploy/ootle/publish-template.sh:34-37` (`transactions.publish_template`).
- **Evidence:** see the table above. The live template address commits to `e8064f7a…` (90,785 B, walletd's wasm-opt output). `dist/SHA256SUMS` pins `837391ce…`, which isn't on chain. The official skill doc says the same thing: walletd's `publish_template` "runs `wasm-opt` … and stores the optimized result", while `TransactionBuilder::publish_template` "stores exactly the bytes it is handed" (`research/ootle-skills/claude-code/SKILL.md:170`). So the reproducibility work (exact pins, the fresh-directory rebuild, "the tests ran these exact bytes") stops one step short of the chain. Fox will ask "is the template on Esmeralda built from this source?", and today the answer is "we can't show it". `tools/verify-deploy.py` doesn't check the template at all.
- **Fix, in order of preference:**
  1. **Publish the exact `dist/` bytes.** `wasm_abi.py` already proves `dist/seal_log.wasm` has no custom section besides `tari_tdef`, so the engine accepts it raw. Ask the deploy builder (via NOTES) to publish with a raw `PublishTemplate` instruction instead of `transactions.publish_template`. First check whether walletd's `transactions.submit` accepts one. The size is 104–106 KB, about 6–8 whole KiB over the 96 KiB allowance, and the excess is charged quadratically, so dry-run it. If the fee hurts, measure `opt-level = "z"`.
  2. If no raw path exists: commit the bytes the chain holds as `dist/seal_log.onchain.wasm` with its sha256. Have `check.sh` assert that its `tari_tdef` equals `dist/`'s, and say plainly in the README and BUILD-INFO that the chain runs walletd's wasm-opt output of this build, which can't be reproduced here.
  - Either way, add `./check.sh --onchain <template_address>`. It fetches `GET /substates/template_<addr>` from an indexer, recomputes the address from `author` and `binary` (Appendix B, 15 lines of stdlib, verified against `b571909e…`), and compares the bytes with `dist/`. Hand it to the deploy builder for `verify-deploy.py` and `/security` → "Verify this deployment".

### H3 (high) — The 6-hour cadence breaks the judge script's Tari step

- **Where:** `lib.rs:13-16` (the cap and its rationale), `NOTES-for-integrator.md` §2 ("Use `21600`"), `seal_log/README.md:4,63,82,86` ("every 6 hours"), `server/mutis/seallog.py:14` (a hard-coded `6 * 3600`).
- **The conflict:** the judge guide promises the A3 exit receipt "within {checkpoint_min} minutes" (default 15, 11-brand §8.3). B5 asks the judge to **Verify** and see "the exit receipt from A3" in the same five-minute track (11-brand §11.6). The site already ships this as step B7 (`web/site/pages/judges.html:78`). At a 6-hour cadence, every judge sees "pending" on the one step built to show the chain doing work. The 6 hours isn't a privacy choice. It's forced by the template: every call decodes the whole log (O(n) fee), and the cap is 2,000 because of an out-of-memory boundary. At 15 minutes the log fills in 21 days, which is about when the Council judges.
- **Fix (preferred, rides along with the H1 republish):** keep the state bounded. Keep only the last *K* checkpoints in the `Vec` (K = 64) plus a `first_index: u64` field; `checkpoint_count` = `first_index + len`; `get(i)` returns `None` for evicted indices. Every root stays in the `SealLog.root` events. Because pads are permanent, each tree is a prefix of the next, so a receipt only ever needs the **latest** checkpoint, which is what `server/mutis/handlers/seallog.py:17` already proves against. The fee becomes flat: about 1,501 + 42.5 × 64 ≈ 4,200 µT in the test engine (≈ 5,200 µT live), or about 0.5 tTARI a day at 15 minutes. The "SealLog is full" path, `MAX_CHECKPOINTS`, the OOM rationale, the rotation note and `fill_to`'s batching all disappear. That's less code, not more. The ABI hash stays the same. Keep the `Vec` as the first field so the app's `state[0]` parser still works, and tell the app it must read `state[1]` for the offset.
- **Fix (no template change):** use a 1-hour cadence (2,000 checkpoints last 83 days, past judging and the Nov 11 date), top up `service` (16.29 tTARI public; the last appends cost about 0.1 tTARI each live), and reword A3 and B5 to say "within the hour". B5 would then show a receipt from `/evidence.json` instead of the judge's own.
- Either way, the integrator decides this now, and README, NOTES and `lib.rs` stop hard-coding "6 hours" and "500 days".

### M1 (medium) — README overclaims Kinkajou will catch

| Line | Says | Problem | Write instead |
|---|---|---|---|
| `README.md:72` | "shows we held exactly that ciphertext when the checkpoint was made" | An inclusion proof shows we committed to a **hash**, not that we held any bytes. The same overreach is in C22 ("It proves what we held and when"). | "shows the tree we committed to at that epoch contains your ciphertext's hash" |
| `README.md:4`, `:93` | "check, against the chain and not against us"; "Read that checkpoint from the chain, not from us" | The audit path and leaf inputs come from our API, and by default the substate comes through our proxy `/api/v1/chain/ix/*` (10-spec §0.7 rule 2). | "The root comes from the component state on the Ootle, through our read proxy by default, or straight from a Tari indexer with *Check directly*. Only the direct check takes us out of the path." |
| `README.md:71`, `:83`, `:86`; `NOTES` §1, §2, §4 | the owner is the `operator` account; "Ours come from our operator account" | G5 failed (`deploy/ootle/setup-accounts.md` §4): `service` (`9c6863…`), walletd's default key, created the log and is the only key that can append; `operator` only paid the template publish. | Name `service`, say it's the key that holds our public tTARI, and link the live template and component. |
| `README.md:6`, `:74` | "can't quietly rewrite"; "The record only grows" | Besides H1, we can start a new component at any time, and must at 2,000 checkpoints under the current design. | Add to "What it does not prove": "That this is our only log. We can start a new one; every log we've used is listed in `/evidence.json`, and each receipt names its component." Ask the server to put the component address in each checkpoint (`checkpoint_json`). |
| `README.md:4` | "one for every exit (a link that burned, …)" | The exit leaf is per **item**, written when the blob is unlinked (`server/mutis/items.py:50-66`), not per link. | "one for every file that leaves (its last link burned or expired, or it was deleted)" |
| `lib.rs:9-10` | "and that the log only grows" | It only shows that checkpoints are appended; append-only at the leaf level is unproven until consistency proofs exist (README `:81` says so). | "and that checkpoints are only ever added" |
| `lib.rs:70-71` (it ships: `tari_ootle_template_build` extracts function docs into the template metadata) | "does not record the caller" | Reads as an anonymity promise. The transaction's signer is public. | "The event doesn't name the caller; the transaction's signer is public." |

### M2 (medium) — The padding rule leaks idle windows. The stricter reading of the spec doesn't.

- **Where:** `tests/vectors/gen.py:105-127` (`padded`), the test `padded_counts_move_in_steps_of_64_and_repeat_when_idle`, `README.md:64-65`, `NOTES` §2. The server copied the same rule: `server/mutis/seallog.py:106` (`-count % PAD_TO`).
- **Problem:** "pad only when the size isn't already a multiple of 64" means an idle window repeats the count, so the public learns which windows had any activity (the builder disclosed this). 10-spec §11.3 says "up to the next multiple of 64 **above**". Read literally, that means always add at least one pad: `size = (count // 64 + 1) * 64`. The count then moves by 64 in every window, and only `floor(new_records / 64)` shows. The canary workaround depends on the canary running; this rule doesn't.
- **Fix:** change the rule in `gen.py`, the vector, the test and the README, and send it to the server builder. It costs at most 64 leaf rows per window and nothing on chain. Optionally enforce `leaf_count % 64 == 0 && leaf_count > last` in `append_root`. One line turns "anyone can check every count is a multiple of 64" from a worker promise into a chain rule.

### M3 (medium) — Anyone can put a `notarize` event on our component

- **Where:** `lib.rs:72-80`, `README.md:75` ("We use it for release manifests"), C10 ("release hashes notarized on the Ootle").
- **Problem:** `notarize` is `allow_all`, and its event carries only `commitment` and `epoch`. A stranger's `SealLog.notarize` on our component looks exactly like ours. Any page or script that lists the component's notarize events would show forged "release hashes".
- **Fix:** add `"signer" => CallerContext::transaction_signer_public_key().to_string()` to the event (`tari_template_lib-0.34.0/src/caller_context.rs:21`; the ABI is unchanged, and the signer is already public in the transaction). After H1, the writer key also appears in the component header (the `append_root` rule). `/security` and `verify-deploy.py` should accept a manifest notarization only when `signer` equals that key. Update `anyone_can_notarize_and_it_writes_no_state` to expect the new field.

### M4 (medium) — The cross-builder contracts aren't wired up, and one field means two things

- `seallog-v1.json` calls the hour index `exit_hour` (`gen.py:115`; 498,175 in the vector). The server's API returns `exit_hour` as **unix seconds** at the hour (`codec.floor_hour`, `handlers/seallog.py:66`), and the app's `exitLeaf(id, unixSeconds)` divides by 3600 (`web/app/lib/seallog.js:19`). The vector's `item_id` is hex; the API's is base64url. An app builder who trusts the vector would build wrong exit leaves against the live API. **Fix:** rename the field to `exit_hour_index`, add `exit_hour_unix` (= hour × 3600, as the API returns it) and `item_id_b64u`.
- Neither `server/tests` nor `web/app/tests` loads `seallog-v1.json`. The NOTES ask for it, but nobody wired it. **Fix (integrator):** both suites load `template/seal_log/tests/vectors/seallog-v1.json` and match its roots and proofs.
- The real browser contract is the **state layout** (`body.state[0][k] = [epoch, {"@cbor":"bytes","hex":…}, leaf_count]`, `web/app/lib/seallog.js:57-65`). `check.sh` pins only `tari_tdef`, which holds function signatures and not state (`tari_template_abi-0.20.1/src/template_def.rs:71-102`). A field reorder would still print "ABI equals the live template's" and break `/verify`. The app's fixture is the research log's junk state (`abab…`, count 3, the `e064…` header). **Fix:** add a template test that dumps the component substate after two appends to `tests/vectors/seallog-state-v1.json`, compare it in `check.sh`, and have the app use it instead of the research fixture.

### Low

1. **Build paths in the binary.** Both the dist and on-chain binaries embed `/home/build/.cargo/registry/src/index.crates.io-…` (8 strings). That leaks the build account's layout and is why BUILD-INFO says byte equality needs `CARGO_HOME=/home/build/.cargo`. Fix: export `RUSTFLAGS="--remap-path-prefix=$CARGO_HOME=/cargo"` in `check.sh` (check that it reaches both `tari build` and the test harness build); after that anyone can rebuild byte for byte.
2. **Two tests test their own arithmetic.** `padded_counts_move_in_steps_of_64_and_repeat_when_idle` pads in the test and checks that the template echoes the counts (it pads nothing; equal counts are already covered by `an_unchanged_leaf_count_is_allowed`). `exit_receipt_checkpoints_fit_the_unchanged_template` checks that a `Hash32` round-trips, through a line-prefix JSON scraper (`tests/seal_log.rs:461-473`). They inflate "12 tests (7 required)", and their names read like guarantees. Fix: make the padding test real (M2's `% 64` rule, then reject 65). For the vector, have `gen.py` also write `checkpoints.txt` (`<size> <root>` per line) and drop the scraper, or merge the two into one documented example.
3. `lib.rs:15` says "a new component takes over after that". No code does that. If H3's bounded state isn't adopted, say "after that the operator must create a new component (manual)".
4. The OOM boundary behind the 2,000 cap (ACCEPTANCE E-3) comes from `exp/explore/`, which isn't in the repo, so it can't be reproduced. Put the exploration test's source into ACCEPTANCE (moot if H3's bounded state lands).
5. Stale status: the deploy builder published this exact `dist/` as `template_b571909e…` and created `component_0ff7e892…`. ACCEPTANCE "Behaviour-equals-live: FAIL", NOTES §1 ("publish … create the log from `operator`") and the open risk about `e064…` are out of date. Add a "Live on Esmeralda" section to the README with both addresses and indexer links; a judge reading `template/` looks for them first. On the next publish, `supersedes` must name `b571909e…`, not `e064…`.
6. `rustup component add rustfmt clippy` changed the shared `build` toolchain. It's disclosed and official, but it's outside "install nothing new". The integrator should ratify it or revert it; the spec's CI form (`tari lint --no-clippy`) doesn't need it.
7. `README.md:86,98` and `NOTES` §1, §2 say "vault" (11-brand §7.4 bans it; here it's the technical Ootle term, and `tools/check-copy.py` doesn't scan this file). "the account's public balance" avoids the argument.

## Not checked

- Whether walletd 0.45 accepts a raw `PublishTemplate` instruction, and its exact fee. The deploy builder should dry-run both on Esmeralda.
- `OwnerRule::None` was tested in the 0.45 test engine only. Dry-run the new `new` on Esmeralda before the real publish.
- I didn't prototype H3's bounded `Vec` or re-measure its fees. The fee figure is extrapolated from the builder's measured slope (42.5 µT per stored checkpoint).
- `./check.sh --costs` wasn't re-run. I checked the README's cost arithmetic against the builder's table.

## Appendix A — the probe and the fix (my work dir only, not this repo)

`/home/build/work/review-template/template/rewriter/src/lib.rs` (crate `rewriter`, same pins and lockfile as `seal_log`):

```rust
use tari_template_lib::prelude::*;

#[template]
mod rewriter {
    use super::*;
    pub struct Rewriter {
        checkpoints: Vec<(u64, Hash32, u64)>,
    }
    impl Rewriter {
        pub fn rewrite(&mut self, checkpoints: Vec<(u64, Hash32, u64)>) {
            self.checkpoints = checkpoints;
        }
    }
}
```

The core of `seal_log/tests/devil.rs` (the log is created and given two checkpoints, then):

```rust
let mut test = TemplateTest::new(env!("CARGO_MANIFEST_DIR"), [".", "../rewriter"]);
// … create log, append (h1, 64) and (h2, 128) …
test.execute_expect_success(
    test.transaction()
        .update_component_template(log, rewriter)
        .call_method(log, "rewrite", args![forged.clone()])
        .update_component_template(log, seal_log)
        .build_and_seal(test.secret_key()),
    vec![test.owner_proof()],
);
// shipped lib.rs: checkpoint_count == 1, latest == forged[0]
// fixed lib.rs:   AccessDenied … native.component.update_template
```

For the repo's regression test, `update_component_template(log, <SealLog's own address>)` is enough (it must fail). The fix is the `new` shown in H1.

## Appendix B — recompute an Ootle template address (stdlib)

This follows `PublishedTemplateAddress::from_author_and_binary_hash` (`tari_engine_types-0.45.0/src/published_template.rs:98`): domain-separated BLAKE2b-256, label `com.tari.ootle.engine.v0.Template`, Borsh-encoded inputs (`RistrettoPublicKeyBytes` serialises as a length-prefixed slice, `Hash32` as 32 raw bytes). Checked against `template_b571909e…15bb`.

```python
import hashlib, struct

TAG = b"com.tari.ootle.engine.v0.Template"

def _h(*parts: bytes) -> bytes:
    d = hashlib.blake2b(digest_size=32)
    d.update(struct.pack("<Q", len(TAG)) + TAG)
    for p in parts:
        d.update(p)
    return d.digest()

def template_address(author_hex: str, binary: bytes) -> str:
    binary_hash = _h(struct.pack("<I", len(binary)) + binary)
    return _h(struct.pack("<I", 32) + bytes.fromhex(author_hex), binary_hash).hex()
```

## Builder response

Template builder, 2026-10-11, fix pass. I accepted every finding; none is rejected. Where I went further than, or differently from, the proposed fix, the row says why. The result is seal_log 2.0.0: `dist/seal_log.wasm`, 106,770 bytes, sha256 `9af71aa2…d6f2`, with the ABI unchanged (`b4b4134b…e494`). `./check.sh` passes with 14 tests. Evidence is in `ACCEPTANCE.md`, and what other builders must do is in `NOTES-for-integrator.md`.

| Finding | Decision | What changed |
|---|---|---|
| H1 owner can rewrite the log | **Fixed as proposed** | `new` binds `append_root` to `rule!(public_key(writer))` and sets `OwnerRule::None`. New test `nobody_can_swap_the_code_under_the_log`: the creating key's `UpdateComponentTemplate` fails with `AccessDenied … native.component.update_template`, state unchanged. New test `the_header_shows_no_owner_and_names_the_writer` reads `owner_rule: "None"` and the writer key from the substate JSON, the way `/verify` will. Renamed `only_the_creating_key_can_append`. README "Who can do what" states the residue: the writer key can append any valid root, stop, or start a new log, and a lost key ends the log. The `/verify` header check is asked of app-core (NOTES §3). I confirmed in the engine sources that `SetAccessRules` and `SetOwnerRule` also go through `require_ownership`, which is `Ok(false)` for `None` (`tracker_auth.rs:127`), even from the component's own code. |
| H2 chain bytes ≠ `dist/` | **Fixed in my scope; the publish is deploy's** | `wasm_abi.py` became `wasm_check.py` with `abi`, `address <author> <wasm>` (predicts a publish's address) and `onchain <addr>` (fetches from an indexer, recomputes the address from author and binary, compares bytes and ABI). `./check.sh --onchain <addr>` runs it. Checked against both live templates: their addresses recompute, the ABI is equal, the bytes differ (walletd's wasm-opt output), so the exit status is 1, as it should be. NOTES §1 asks deploy to publish the raw `dist/` bytes through `transactions.submit` with a `PublishTemplate` instruction, dry run first. The fallback (commit the chain's bytes and say so) is spelled out there. I can't publish or touch walletd. |
| H3 6-hour cadence breaks A3/B5 | **Fixed with the preferred variant** | The state keeps the newest 64 checkpoints plus `first_index`; `get` and `checkpoint_count` count every checkpoint ever appended, and `get` is `None` for evicted ones. Measured: an append costs 4,208 µT with 63 checkpoints already in the log, 4,212 with 64, 4,217 with 300, and 4,219 with 1,000, and the component stays at about 2.7 KB. The cap, the out-of-memory rationale, "SealLog is full", the rotation note and `fill_to`'s adaptive batching are gone. One addition: `SealLog.root` now carries `index`, so a checkpoint the state no longer keeps can still be found by index in the events. I confirmed in the engine that receipts are read-only substates (`SubstateId::is_read_only`), which makes "every root stays in its event" literally true. No "6 hours" or "500 days" is left in the template; NOTES §2 recommends 900 s with the cost (≈0.50 tTARI/day) and a top-up, and gives 3600 s as the alternative. |
| M1 overclaims | **Fixed** | README: "the tree we committed to at that epoch contains your ciphertext's hash"; reading through our proxy by default, with only *Check directly* taking us out; the writer named as walletd's default `service` key; "That this is our only log" and "That we held your file" added to "What it does not prove"; "every file that leaves"; "checkpoints are only ever added". In `lib.rs` (whose docs ship in the metadata), "the log only grows" is gone, and notarize now says the event names the signer. "vault" is gone from my files. |
| M2 idle windows leak | **Fixed, and enforced on chain** | The rule is `size = (count // 64 + 1) * 64` in `gen.py`, the vector (which gains an idle-window checkpoint at 192; the 64 and 128 roots are unchanged), the README and the tests. `append_root` refuses a count that isn't a multiple of 64 or doesn't grow, so the rule is the chain's, not the worker's. Consequence: today's server would be refused at its first idle window; NOTES §2 gives the one-line change. |
| M3 forgeable notarize | **Fixed as proposed** | The `notarize` event gains `signer`. Test `anyone_can_notarize_and_the_event_names_the_signer` checks that it equals the stranger's key. |
| M4 contracts not wired | **Fixed in my scope** | The vector fields are now `exit_unix`, `exit_hour_unix` (the API's `exit_hour`), `exit_hour_index`, and `item_id_b64u` next to the hex. A new state vector, `tests/vectors/seallog-state-v1.json`, is pinned by `the_component_state_matches_the_state_vector` (rewritten only with `SEALLOG_BLESS=1`). I cross-checked `seallog-v1.json` against `server/mutis/seallog.py` and `web/app/lib/seallog.js` (read-only, from scratch scripts): leaves, roots and proofs match. Loading the vectors in their suites, and replacing the app's research fixture, are asked of server and app-core (NOTES §2, §3). |
| L1 build paths | **Fixed** | `check.sh` exports `RUSTFLAGS=--remap-path-prefix=$CARGO_HOME=/cargo`, which reaches both `tari build` and the harness's nested cargo (it inherits the environment), and fails if `$CARGO_HOME` appears in the binary. 1.0.0 had 8 occurrences of `/home/build/.cargo/`; 2.0.0 has none. A build in another directory with `CARGO_HOME` at another path gives the identical sha256. Cargo's `trim-paths` would put this in `Cargo.toml`, but it is unstable in cargo 1.99 ("feature `trim-paths` is required"). |
| L2 self-arithmetic tests | **Fixed** | The padding test is now `leaf_count_must_be_a_multiple_of_64`: the template refuses 0, 65 and 100. The JSON line scraper is replaced by `serde_json` (`=1.0.152`, already in the lock through the test tooling; the lock diff is the root entry only). The vector test now checks that the shared vector obeys the on-chain rules, which is real interop value now that the template enforces them. |
| L3 "a new component takes over" | **Moot** | The bounded state removed the sentence and its reason. |
| L4 OOM evidence outside the repo | **Fixed** | The exploration test's source and output are quoted in `ACCEPTANCE.md` E-3, marked historical. |
| L5 stale status | **Fixed** | ACCEPTANCE and NOTES are rewritten. The README has an "Earlier builds" section with both retired templates and logs and indexer links. `supersedes` is `b571909e…`. I did not put the *new* addresses in the README, because they don't exist yet and a placeholder would go stale; the README points to `/api/v1/config` and `setup-accounts.md`. |
| L6 rustup components | **For the integrator** | Restated in NOTES §6 with the undo command. |
| L7 "vault" | **Fixed** | No longer used in my files. |
