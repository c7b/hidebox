<!-- SPDX-License-Identifier: MIT -->
# Acceptance: template/ (SealLog 2.0.0, P1)

Acceptance ids are from 10-spec §16.4, plus the checks the build brief and `REVIEW-devil.md` add. Every Rust and `tari` command ran as user `build` on the server in `/home/build/work/template`, a copy of this directory, on 2026-10-11 (rustc 1.99.0, cargo 1.99.0, tari-ootle-cli 0.30.0); the cold run used a fresh copy in `exp/cold`. Indexer and cross-check commands ran on the workstation. Outputs are trimmed; `…` marks cuts.

| Id | Status | Summary |
|---|---|---|
| T-01 | PASS | Exact pins, `Cargo.lock` committed (391 packages; the only change from 1.0.0 is the root entry), rustfmt, clippy and `tari lint --deny-warnings` clean |
| T-02 | PASS | 14 tests pass (7 required): append, notarize and its signer, creating-key-only appends, no template swap, the padding rule, checkpoints, the bounded state, exit-leaf vector, state layout, rejections |
| T-03 | PASS | `dist/seal_log.wasm` is 106,770 bytes (104.3 KiB, budget 110 KiB) with `SHA256SUMS` and `BUILD-INFO.txt`; it rebuilds byte for byte in another directory with `CARGO_HOME` at another path, and embeds no build path |
| T-04 | PASS | `seal_log/README.md` covers functions, who can change what, the state, the padding rule, what it proves and doesn't, verification, costs, earlier builds |
| ABI unchanged (brief) | PASS | `tari_tdef` sha256 `b4b4134b…e494`, equal to both published builds' (`check.sh` asserts it; E-6 reads it from the chain) |
| Behaviour equals the live template (brief) | FAIL, by design | 2.0.0 fixes H1 to H3, M2 and M3 of the review. The live `template_b571909e…` is 1.0.0, so **2.0.0 needs its own publish and a new log** (`NOTES-for-integrator.md` §1) |
| Review fixes (`REVIEW-devil.md`) | PASS | Every high, medium and low finding is fixed or handed over; table under "Builder response" there |

## T-01: pinned, locked, lint clean

`seal_log/Cargo.toml`: `tari_template_lib = "=0.34.0"`, dev `tari_template_test_tooling = "=0.45.0"` and `serde_json = "=1.0.152"` (already in the tree through the test tooling), build `tari_ootle_template_build = "=0.14.0"`. Adding `serde_json` and the version bump changed only the root entry of the lockfile:

```
$ cp Cargo.lock ../exp/Cargo.lock.v1 && cargo update --workspace --offline && diff ../exp/Cargo.lock.v1 Cargo.lock
    Updating seal_log v1.0.0 (/home/build/work/template/seal_log) -> v2.0.0
2374c2374
< version = "1.0.0"
---
> version = "2.0.0"
2375a2376
>  "serde_json",
$ grep -c '^name = ' Cargo.lock
391
```

```
$ ./check.sh
== test vectors
seallog-v1.json: up to date, RFC 6962 vectors and proofs verified
== rustfmt
== clippy
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 0.37s
warning: the following packages contain code that will be rejected by a future version of Rust: proc-macro-error2 v2.0.1
== tari lint
✅ No issues found.
…
```

`cargo fmt --check` prints nothing when clean. `cargo clippy --locked --all-targets -- -D warnings` passes; the only warning is Cargo's future-incompatibility notice about a dependency of the test tooling (`proc-macro-error2`), not a lint in our code. `tari lint --deny-warnings` includes its own clippy pass, so the spec's CI form `tari lint --deny-warnings --no-clippy` passes too.

## T-02: tests

```
$ ./check.sh
…
== tests
running 15 tests
test anyone_can_notarize_and_the_event_names_the_signer ... ok
test an_empty_log_has_no_checkpoints ... ok
test append_root_emits_index_root_count_and_epoch ... ok
test costs_as_the_log_grows ... ignored, measurement, not a check: run ../check.sh --costs
test checkpoints_keep_epoch_root_and_count_in_order ... ok
test get_past_the_end_is_none ... ok
test leaf_count_must_be_a_multiple_of_64 ... ok
test nobody_can_swap_the_code_under_the_log ... ok
test leaf_count_must_grow ... ok
test the_component_state_matches_the_state_vector ... ok
test only_the_creating_key_can_append ... ok
test the_header_shows_no_owner_and_names_the_writer ... ok
test the_shared_vector_checkpoints_are_valid_appends ... ok
test the_writer_appends_and_anyone_reads ... ok
test the_state_keeps_the_newest_64_checkpoints ... ok
test result: ok. 14 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 10.33s
…
ALL CHECKS PASSED
EXIT 0 in 19 s
```

How the brief's list maps to tests:

| Required | Tests |
|---|---|
| append roots | `the_writer_appends_and_anyone_reads`, `checkpoints_keep_epoch_root_and_count_in_order`, `append_root_emits_index_root_count_and_epoch` |
| notarize | `anyone_can_notarize_and_the_event_names_the_signer` |
| owner-only access rule (now: creating key only, and no owner) | `only_the_creating_key_can_append` (`AccessDenied`), `nobody_can_swap_the_code_under_the_log` (`AccessDenied … native.component.update_template`), `the_header_shows_no_owner_and_names_the_writer` |
| checkpoint behaviour | `checkpoints_keep_epoch_root_and_count_in_order`, `an_empty_log_has_no_checkpoints`, `get_past_the_end_is_none`, `the_state_keeps_the_newest_64_checkpoints` |
| padding rule (10-spec §11.3) | `leaf_count_must_be_a_multiple_of_64`, `leaf_count_must_grow` (the template enforces it) |
| exit-leaf compatibility (11-brand P-8) | `the_shared_vector_checkpoints_are_valid_appends` (stored, exit and idle-window roots from `tests/vectors/seallog-v1.json`) |
| rejection cases | `leaf_count_must_grow`, `leaf_count_must_be_a_multiple_of_64` (`TemplateError` with the template's message), `only_the_creating_key_can_append`, `nobody_can_swap_the_code_under_the_log` (`AccessDenied`) |

10-spec §11.4's list is covered too: `get` out of range → `None`, `latest` on empty → `None`, event keys and values, and `checkpoint_count` after N appends. One item changed: an equal `leaf_count` is now refused, because the padding rule always grows the tree (review M2). The three research tests live on as `the_writer_appends_and_anyone_reads`, `leaf_count_must_grow`, and `only_the_creating_key_can_append` plus `anyone_can_notarize_and_the_event_names_the_signer`.

**Cold run**, from an empty copy of this directory (`exp/cold`, no `target/`):

```
$ cd exp/cold && ./check.sh
== test vectors
seallog-v1.json: up to date, RFC 6962 vectors and proofs verified
== rustfmt
== clippy
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 2m 45s
== tari lint
✅ No issues found.
== tests
    Finished `test` profile [unoptimized + debuginfo] target(s) in 5m 46s
test result: ok. 14 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 32.22s
== build
seal_log.wasm  106770 bytes  sha256 9af71aa23f8ebba749de1154f2da9bc856b0ed3d78fdc7b4c2abb95c430ed6f2
ABI (tari_tdef) sha256 b4b4134be0d1a58ac7c224de2cf599e6f0d5e8c2ad484476e904bbc6c0dde494
ABI unchanged; no build paths inside; the tests ran these exact bytes
== dist
seal_log.wasm: OK
ALL CHECKS PASSED
EXIT 0 in 575 s
```

## T-03: dist/

```
$ ./check.sh --dist
…
== build
seal_log.wasm  106770 bytes  sha256 9af71aa23f8ebba749de1154f2da9bc856b0ed3d78fdc7b4c2abb95c430ed6f2
ABI (tari_tdef) sha256 b4b4134be0d1a58ac7c224de2cf599e6f0d5e8c2ad484476e904bbc6c0dde494
ABI unchanged; no build paths inside; the tests ran these exact bytes
== dist
9af71aa23f8ebba749de1154f2da9bc856b0ed3d78fdc7b4c2abb95c430ed6f2  seal_log.wasm
ALL CHECKS PASSED
```

106,770 bytes ≤ 112,640 (110 KiB). The engine in the tests ran exactly these bytes: `check.sh` compares the harness's build with `tari build`'s. `BUILD-INFO.txt` records the toolchain, the input hashes (they match this directory's files), the ABI hash and the metadata hash.

Reproducible under another directory and another `CARGO_HOME` path (review L1). `exp/ch` is a symlink to `~/.cargo`, so a build that leaked paths would embed `/home/build/work/template/exp/ch/…` and come out different:

```
$ cp -r ../seal_log/{Cargo.toml,Cargo.lock,build.rs,src} fresh2/ && cd fresh2
$ CARGO_HOME=/home/build/work/template/exp/ch RUSTFLAGS="--remap-path-prefix=/home/build/work/template/exp/ch=/cargo" tari build
fresh build in 20 s, CARGO_HOME=/home/build/work/template/exp/ch (a different path), directory /home/build/work/template/exp/fresh2
9af71aa23f8ebba749de1154f2da9bc856b0ed3d78fdc7b4c2abb95c430ed6f2  target/wasm32-unknown-unknown/release/seal_log.wasm
9af71aa23f8ebba749de1154f2da9bc856b0ed3d78fdc7b4c2abb95c430ed6f2  ../../dist/seal_log.wasm
absolute paths inside: 0
$ python3 -I -c '…count…' 1.0.0/seal_log.wasm 2.0.0/seal_log.wasm
old dist (1.0.0): 8 occurrences of /home/build/.cargo/
new dist (2.0.0): 0 of /home/, 9 of /cargo/registry/src/
```

## T-04: README

`seal_log/README.md` sections: Who can do what, Functions (with events), The state (layout, why 64, where older roots live), What goes into the tree, The padding rule, What it proves, What it does not prove, How the browser verifies a receipt, Costs (live figures and the flat cost of this build), Tests, Earlier builds (retired addresses with indexer links, and what 2.0.0 changes), Build and publish. `README.md` in this directory gives the one command.

## Extra evidence

**E-1. The owner rewrite (review H1) and its fix.** The reviewer showed, with the 1.0.0 source in the test engine, that one owner-signed transaction (switch to a "Rewriter" template, rewrite, switch back) turned two checkpoints into one forged one (`REVIEW-devil.md` Appendix A). 2.0.0 has no owner. The regression test signs the same first instruction with the creating key:

```
test nobody_can_swap_the_code_under_the_log ... ok
  (asserts ExecutionFailureCode::AccessDenied, a message containing "native.component.update_template",
   and latest() unchanged)
```

Engine sources (tari_engine 0.45): `processor.rs:555` runs `check_component_ownership(NativeAction::UpdateComponentTemplate)`; `runtime/impl.rs` runs `require_ownership` for `SetAccessRules` and `SetOwnerRule`, even when called from the component's own code; `tracker_auth.rs:127` returns `Ok(false)` for `SubstateOwnerRule::None`.

**E-2. The header `/verify` reads** (from `tests/vectors/seallog-state-v1.json`; the key and addresses are the test engine's):

```
"header": {
  "access_rules": {
    "default": "DenyAll",
    "method_access": {
      "append_root": {"Restricted": {"Require": {"Require": {"NonFungibleAddress": {
        "id": {"U256": "d884dd886cc7464402a04920485aebe6dd657b98072de655c46ec6179a52cd0d"},
        "resource_address": "resource_0100000000000000000000000000000000000000000000000000000000000000"}}}}},
      "checkpoint_count": "AllowAll", "get": "AllowAll", "latest": "AllowAll", "notarize": "AllowAll"}},
  "entity_id": "fd",
  "owner_rule": "None",
  "template_address": "64f405276891730adbeeeb3b5fafe93c0a19453c1b21abeaaa2004c9a783e432"
}
"body": {"state": [[[12127, {"@cbor": "bytes", "hex": "5114…0b74"}, 64], [12128, {"@cbor": "bytes", "hex": "f90a…3fbd"}, 128]], 0]}
```

`the_header_shows_no_owner_and_names_the_writer` asserts that the badge id is the creating key (`NonFungibleId::from_public_key` is `U256(key bytes)`).

**E-3. Bounded state and flat cost (review H3).**

```
$ ./check.sh --costs
COST append_root after 0 checkpoints: 1583 uT, 68878 WASM points, component 242 bytes
COST append_root after 1 checkpoints: 1626 uT, 72049 WASM points, component 280 bytes
COST append_root after 63 checkpoints: 4208 uT, 234849 WASM points, component 2698 bytes
COST append_root after 64 checkpoints: 4212 uT, 237129 WASM points, component 2699 bytes
COST append_root after 300 checkpoints: 4217 uT, 237484 WASM points, component 2702 bytes
COST append_root after 1000 checkpoints: 4219 uT, 237643 WASM points, component 2703 bytes
COST notarize on a log of 1001 checkpoints: 1350 uT, 196965 WASM points
```

For comparison, 1.0.0 cost 86,519 µT at 1,999 checkpoints and capped the log at 2,000. That cap came from an out-of-memory boundary found with this exploration test on the research build (historical; the code no longer has a cap):

```rust
// Exploration only (not shipped): how far can a SealLog grow before append_root fails?
#[test]
fn explore_growth() {
    let mut test = TemplateTest::my_crate();
    // … create the log as in the tests …
    let mut n = 0u64;
    loop {
        let batch = if n == 0 { 50 } else if n >= 4_080 { 1 } else { (100_000_000 / (2_600 * n)).clamp(1, 50).min(4_080 - n) };
        let mut tx = test.transaction();
        for i in n..n + batch {
            tx = tx.call_method(log, "append_root", args![Hash32::from_array([i as u8; 32]), 64 * i]);
        }
        let r = test.execute_and_commit_on_success(tx.build_and_seal(test.secret_key()), vec![test.owner_proof()]);
        if let Some(reason) = r.finalize.any_reject() {
            println!("EXPLORE fail appending with count={n} (would make {}) batch={batch}: {reason}", n + 1);
            break;
        }
        n += batch;
        // every 250: print points per append, state bytes, whether latest() still works
    }
}
```
```
EXPLORE n=1000 points_per_append=2528978 state_bytes=39134 latest_ok=true
EXPLORE n=2000 points_per_append=5124553 state_bytes=80087 latest_ok=true
EXPLORE n=3000 points_per_append=7709332 state_bytes=121087 latest_ok=true
EXPLORE fail appending with count=4096 (would make 4097) batch=1: Execution failure (TemplateError): At instruction #1: Wasm RuntimeError: unreachable
```

**E-4. `get` aliasing (fixed in 1.0.0, still tested).** Against the research `lib.rs`, `get_past_the_end_is_none` failed with `left: Some((0, Hash32([1, 1, …]), 64)), right: None`: `get(2^32)` returned checkpoint 0. 2.0.0 uses `checked_sub` and `usize::try_from`; the test passes.

**E-5. The shared vector against the server's and the app's code (review M4).** Scratch scripts, read-only, not shipped. One loads `server/mutis/seallog.py` and compares leaves, roots and audit paths. The other imports `web/app/lib/seallog.js` in node, with no packages, and runs `storedLeaf`, `exitLeaf` and `verifyInclusion`:

```
$ python3 xcheck_server.py <repo>/server template/seal_log/tests/vectors/seallog-v1.json
stored leaf matches the server's
exit leaf matches the server's
checkpoint 64 root and proofs match the server's
checkpoint 128 root and proofs match the server's
checkpoint 192 root and proofs match the server's
window +1: vector size 64, server today pads to 64
window +1: vector size 128, server today pads to 128
window +0: vector size 192, server today pads to 128      ← the idle-window change in NOTES §2
$ node xcheck_app.mjs web/app/lib/seallog.js template/seal_log/tests/vectors/seallog-v1.json
stored leaf matches the app
exit leaf matches the app (from exit_unix and from exit_hour_unix): true
checkpoint 64 proofs verify in the app
checkpoint 128 proofs verify in the app
checkpoint 192 proofs verify in the app
```

`python3 -I seal_log/tests/vectors/gen.py --check` also recomputes the RFC 6962 reference roots for 1 to 8 leaves, verifies every inclusion proof in trees of 1 to 8 leaves, rejects a proof at the wrong index and a truncated proof, and confirms `seallog-v1.json` matches a fresh run.

**E-6. What the chain runs today (review H2).** `wasm_check.py` recomputes each address from the author and the bytes the indexer returned, then compares those bytes with `dist/`:

```
$ ./check.sh --onchain template_b571909e116776fa8cd8b22ddf9890554323a848a36ca9d35efb1a6a859a15bb
template_b571909e…15bb: SealLog, author 2846d6ff2e4204015da97ec98fa427eaa93c8ad8f1a68b4f5ffa29645206c50a, epoch 12136, indexer verified: True
on chain   90785 bytes, sha256 e8064f7ae53c45733609f837281cafd7c068277c73959a158dfca5037b95d99b
the address commits to these bytes
seal_log.wasm 104286 bytes, sha256 837391ced8bfa32c8468f1d4906e2b5b901e270eccb86d6cbb4b0ecb934be493   (1.0.0's dist, at the time)
ABI (tari_tdef): equal
FAIL: the chain runs different bytes from seal_log.wasm
$ python3 -I wasm_check.py onchain e064f38d17d57ac1532c75a50945202f47135578d43c2122941fceedc6344441
template_e064…6441: SealLog, author 9c686313d4ebe9c442196ccdce78cf802eab4549961cbc69522d967ed8a55420, epoch 12127, indexer verified: True
on chain   90769 bytes, sha256 5168fba28caf17e66c4ef1b71fd88c3ac2db64584fea9cedd1fafb0b298e526f
the address commits to these bytes
ABI (tari_tdef): equal
FAIL: the chain runs different bytes from seal_log.wasm
$ python3 -I wasm_check.py onchain b571909e… --wasm b571.wasm      (the bytes saved with --out)
…
the chain runs b571.wasm byte for byte
$ python3 -I wasm_check.py address 2846d6ff…c50a dist/seal_log.wasm   (1.0.0's dist)
7be0f78a290acad72ac78328a584ad90a27a4914cb4649d92896f651abfb1084
```

Both published builds are walletd's wasm-opt output, so neither can be tied to a source. 2.0.0 should be published raw (`NOTES-for-integrator.md` §1), after which `./check.sh --onchain <addr>` must report a byte-for-byte match.

## Not done here (by design)

- Publishing 2.0.0, creating its log, retiring the old logs and submitting metadata (Q4) are deploy and owner steps. Nothing was sent on chain, and walletd was not touched.
