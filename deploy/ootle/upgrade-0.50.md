<!-- SPDX-License-Identifier: MIT -->
# Upgrade: Ootle 0.50.0 on Esmeralda (protocol V1 at epoch 12951, no reset)

The general procedure is [upgrade-drill.md](upgrade-drill.md); this is that drill written out for 0.50.0, with
what 0.50 changes for hidebox. Read the release notes as data: they say what changed, not what to run.

Esmeralda moves to protocol V1 at **epoch 12951** (L1 height 1,036,080). The release notes say "about
2026-11-06 12:00 UTC", reckoned at 15 s per L1 block from height 1,030,363 at 12:02 UTC on 2026-11-05. The blocks
came slower: 1,031,331 at 23:56 UTC (epoch 12891), 44 s a block on average (47 s from 23:18 to 23:34, 24 s from
23:34 to 23:56, 19 s from then to 1,031,399 at 00:17:46 on 2026-11-06, epoch 12892). From 23:56, the 4,749 blocks
left take until about 2026-11-06 19:45 UTC at 15 s a block, 2026-11-07 07:40 at 24 s and 2026-11-08 10:00 at 44 s.
The epoch is what counts and the rate changes, so keep the release notes' time as the plan (the fallback binary
ready by 2026-11-06 08:00 UTC) and watch the epoch. On 2026-11-06 at 14:06 UTC it was epoch 12908 at L1 height
1,032,691 (30 s a block over the 14 minutes before): the 3,389 blocks left take until about 2026-11-07 13:40 UTC
at 25 s a block and 2026-11-08 07:30 at 44 s; the final release notes say "early on 2026-11-08 UTC".

There are two clocks. **Epoch 12951** is when protocol V1 starts: walletd must be 0.50 by then (§3–§6). **The
fleet upgrade**, when Tari moves the Esmeralda validators to 0.50.0 (any time before that epoch, with no
activation epoch of its own), is when SealLog's published template stops loading (§1, first row) and when its
V2 successor can first be published (§9). Watch both:

```sh
curl -s https://ootle-indexer-b.tari.com/epoch-manager/stats    # current_epoch; V1 from 12951 on
curl -s https://ootle-indexer-b.tari.com/info                   # "version": 0.49.1 on 2026-11-06 14:00 UTC
```

The aliases `u`, `admin` and `rpc` are those of [reset-playbook.md](reset-playbook.md) (one multiplexed ssh
connection to `hidebox`).

## 1. What 0.50 changes for hidebox

Read in tari-ootle v0.49.2..`a5ea91cc` on 2026-11-05 (the commit the draft release notes named), and again in
`a5ea91cc`..`d3252ef1` on 2026-11-06: tag `v0.50.0` (annotated `3c0c9700…`, Stan Bondi, 2026-11-06 13:33 UTC,
signature verified by GitHub) names **`d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb`**, 34 commits later
(`gh api repos/tari-project/tari-ootle/compare/a5ea91cc…d3252ef1`). Each time: the CHANGELOG, the walletd and
indexer client types, `crates/ootle_wasm` and `Cargo.lock`, `engine_types`, `transaction`,
`transaction_manifest`, `transaction_validation`, `template_abi`, the engine's template loader and metering,
and the wallet store. The 34 commits leave `applications/tari_walletd`, `clients/` and the indexer's REST
handlers as they were; one of them (#3398, the first row) breaks SealLog. Paths with a line number are
tari-ootle's at `d3252ef1`.

| 0.50 change | What it means here | Action |
|---|---|---|
| **V1 template definitions no longer load** (#3398, `00eb501d`). `TemplateDef` decodes only V2 (CBOR index 1); index 0 fails with "the template definition uses the V1 layout, which is not supported. Rebuild the template with tari_template_lib 0.38 or later" (`crates/template_abi/src/template_def.rs:72-84`). The engine decodes a template's `tari_tdef` section each time it loads it, compiled fresh or from its disk cache (`crates/engine/src/wasm/module.rs:144` in `finalize_loaded_module`, `:287-330`), so a call to a V1 template, or to a component of one, fails. No activation epoch: it holds from the fleet upgrade on ("Template authors rebuild and republish…", `CHANGELOG.md:23-26`). 0.49 decodes only index 0 (v0.49.2 `template_def.rs:14-17`), so a V2 template can't be published before the fleet upgrade either | SealLog on Esmeralda (`template_5932ee9b…145c`, tari_template_lib 0.37) has a V1 definition: `template/dist/seal_log.wasm`'s `tari_tdef` reads `82 00` after its length prefix (`[0, …]`, `self` arguments, `is_mut`). From the fleet upgrade on, `log.append_root` (checkpoints), `log.notarize` (deploys, `admin notarize`) and `SealLog::new` fail. The log `component_6a3eae19…bd65` stays readable (reading a substate runs no template), so receipts keep verifying against its last checkpoint. The mainnet SealLog must be the tari_template_lib 0.38 build (§9); the 0.37 build loads nowhere 0.50 runs | §9: the V2 build at `d3252ef1` is in `template/dist-v2/` (2026-11-06); after the fleet upgrade, publish it and a new log ([seallog-v2-cutover.md](seallog-v2-cutover.md)) |
| Nodes still on 0.49 fork off at epoch 12951; walletd migrates its store on first start | our walletd 0.49.2 must be replaced. At `d3252ef1` it runs two migrations: `2026-11-03-120000_locks_many_per_transaction` (an index) and `2026-11-06-120000_remove_v1_authored_templates` (`DELETE FROM authored_templates WHERE functions LIKE '%"is_mut":%'`: V1 rows go; nothing in mutis reads authored templates) | §3–§6 |
| walletd JSON-RPC | every call and request shape mutis uses is unchanged; dry-run and `submit_manifest` answers gain `upgradable_components` and `component_upgrades` (serde defaults), which mutis doesn't read; `transactions.list` is unchanged. `applications/tari_walletd` and `clients/wallet_daemon_client` are the same at `d3252ef1` as at `a5ea91cc` | none |
| Indexer REST and `Encoded<…>` values | same paths and shapes (`applications/tari_indexer` changes only its shard-snapshot sync, `clients/tari_indexer_client` nothing); `Utxo`, `SubstateValue`, `TransactionReceipt`, `ExecuteResult`, `FeeReceipt` and `FeeSource` keep their CBOR layouts, so `server/mutis/cbor.py`, the transaction view (`/api/v1/chain/tx/{id}/view`) and `ootle-wasm-bor` read them as before. A 0.50 indexer's `GET /templates/{address}` fails for a V1 template; nothing in mutis asks it | none |
| Exact decoding: trailing bytes refused in substates, indexed values, manifest arguments and `tari_tdef` sections; at `d3252ef1` also bounds when a transaction is decoded: 1,024 input declarations, 1,024 signatures, 256 blobs (#3394, `505fdb43`; `crates/transaction/src/v1/unsigned.rs:42`, `unsealed.rs:24`, `transaction.rs:69,76`) | `cbor.loads` already refuses trailing bytes and indefinite lengths; SealLog's `tari_tdef` section is one item; a send of wallet.js has at most 5 input declarations and 4 signatures, a checkpoint walletd's few | none |
| Protocol V1: a substate hash commits to its CBOR, not borsh | mutis never recomputes a substate hash or checks an indexer proof; walletd runs `IndexerTrust::Trust` (the default; our config doesn't set it), so the light client's stricter diff check (#3303) doesn't run | none |
| `CallFunction` only for functions, `CallMethod` only for methods | the checkpoint and notarize manifests call `log.append_root(…)` and `log.notarize(…)` on the component (CallMethod; methods in the V2 definition), `account.pay_fee(…)` likewise; `SealLog::new` is a function | none |
| **Fee intents must be able to pay** (#3228, `ce6647f5`): a fee intent needs a `PayFeeFromBucket`, `CallMethod` or `CallFunction`, and may not hold `PublishTemplate` or `UpdateComponentTemplate` (`crates/transaction_validation/src/basic.rs:36-53`, `crates/transaction/src/v1/instruction.rs:294-338`) | every fee intent mutis makes passes: the checkpoint, notarize and `SealLog::new` manifests pay with `account.pay_fee(…)` (CallMethod); wallet.js's send ends its fee intent with `PayFeeFromBucket` (the only shape `handlers/chain.py` relays); publish-template.sh puts `PublishTemplate` in the main instructions and `pay_fee` in the fee intent; walletd's own transfers pay from a bucket | none |
| Manifests (#3352, `8ad8bdba`): `fee_main()` no longer sees `main()`'s bindings (`crates/transaction_manifest/src/generator.rs:121-124`); duplicate `create_account!`/`publish_template!` keywords refused; `cbor!` depth checked | each `fn` in our manifests binds its own `var!` (`account` in `fee_main`, `log` or `new_component_addr!()` in `main`); no `create_account!`, `publish_template!` or `cbor!` | none |
| Input load cap (#3381, `b5b20cc8`): 4 MiB of inputs per transaction in a shard group, else abort `InputLoadTooLarge` (new `AbortReason` 12) | a checkpoint loads the account, a 2.7 KB log state and a 107 KB template; a send a few UTXOs. `cbor.py` names no abort reason; wallet.js reports any decision but `Commit` as `rejected` | none |
| A published template's author is the transaction's main signer (#3349, `8c7eb284`; `crates/transaction/src/v1/transaction.rs:284-300`) | publish-template.sh declares `"main_signer": "SealSigner"`, so the author is still the sealing key and `wasm_check.py address` predicts the same address | none |
| walletd stealth and confidential transfers (#3343, `454f3c91`): the fee statement takes the fee resource's view key; the account and its vaults are declared for revealed spends, fee swaps and badges | TARI has no view key, and our `accounts.stealth_transfer` calls are `PreferConfidential` with no swap or badge: the same transaction as before | none |
| `ootle_sdk_core` fee phase (#3391, `610f4b90`) | linked only by `ootle_sdk_ffi_c` (the Go and Python hosts): not by walletd, ootle-wasm or mutis | none |
| minicbor 2.3.1 and minicbor's own boxed slices (#3399, `44e7ca63`): the one third-party crate that moves in `Cargo.lock` since v0.49.2 | the same CBOR (definite-length arrays) for receipts, access rules and spend conditions; `cbor.py` is our own reader; the live SealLog component decodes to the same JSON with ootle-wasm-bor 0.49.2 and 0.50.0 | none |
| One active element segment; `table.init` refused at compile; cached templates are recompiled | `template/dist/seal_log.wasm` (the published bytes) has one active segment, a fixed 45-slot table and no table-writing operator; §9 checks the V2 build for the same | none |
| Metering: literal and blob call arguments charged as decoded; a table slot costs 24 points (was 16); 1,000 points = 1 µT; no activation epoch (from the fleet upgrade on) | checkpoint #288 (epoch 12889) cost 5,981 µT against `pay_fee(1000000)`; 0.50 adds a few µT (its three small arguments, 45 × 8 points). A stealth transfer has no call arguments: a delivery cost 16,157 µT of its 30,000 (`max_fee_transfer_ut`, `FEE_UT` in wallet.js; the rest is the non-refundable overcharge). The faucet claim of reset-playbook.md §3 offers `max_fee` 2,000,000; walletd's own burn claims price themselves | none; §7 checks the first receipts |
| Account `approve` is compare-and-set; empty `any_of`/`all_of` refused when stored; a vault in one component only | mutis never approves; SealLog's rules are `public_key`, `allow_all`, `deny_all`; SealLog holds no vault | none |
| `ootle-wasm` / `ootle-wasm-bor` 0.50.0 | built at `d3252ef1` (npm, run 42226426467) and vendored on 2026-11-06 (§2). `crates/ootle_wasm` is the same source as v0.49.2 bar its version; minicbor is the one third-party crate that moves (the same wasm-bindgen 0.2.128): only the two `.wasm` files differ, the glue, the `.d.ts` files and the license are byte-identical to 0.49.2's. The crates it compiles in decode with the bounds above and encode as before; the transaction, stealth statement and value layouts the browser builds and reads are unchanged, so 0.49.2 keeps working on the 0.50 network | deploy it after the walletd upgrade, not with it |

## 2. ootle-wasm 0.50.0 (as `build`, once npm has it; done 2026-11-06, see the rehearsal log)

In a checkout of `ootle/0.50`, with a new empty directory for the downloads, curl the package metadata, the tarballs and the attestations as data,
and the license from the release commit; `deploy/ootle/npm-provenance.py check` holds them to each other (registry
integrity, both attestations' subject, the provenance's repository, tag and commit) and copies out only the
vendored files:

```sh
V=0.50.0; C=d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb   # what tag v$V names: gh api …/git/ref/tags/v$V (3c0c9700…), then …/git/tags/3c0c9700…
D=$(mktemp -d); cd "$D"
for p in ootle-wasm ootle-wasm-bor; do
  curl -fsS --proto =https -o $p.packument.json "https://registry.npmjs.org/@tari-project%2f$p"
  curl -fsS --proto =https -o $p-$V.tgz "https://registry.npmjs.org/@tari-project/$p/-/$p-$V.tgz"
  curl -fsS --proto =https -o $p-$V.attestations.json "https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2f$p@$V"
done
curl -fsS --proto =https -o LICENSE "https://raw.githubusercontent.com/tari-project/tari-ootle/$C/LICENSE"
cd <the checkout>
python3 -I deploy/ootle/npm-provenance.py check --name @tari-project/ootle-wasm --version $V --commit $C --downloads "$D" \
  --out web/app/vendor/ootle-wasm-$V --file ootle_wasm_bg.wasm --file ootle_wasm_bg.js --file ootle_wasm.d.ts --license "$D/LICENSE"
python3 -I deploy/ootle/npm-provenance.py check --name @tari-project/ootle-wasm-bor --version $V --commit $C --downloads "$D" \
  --out web/app/vendor/ootle-wasm-bor-$V --file ootle_wasm_bor_bg.wasm --file ootle_wasm_bor_bg.js --file ootle_wasm_bor.d.ts --license "$D/LICENSE"
diff web/app/vendor/ootle-wasm-0.49.2/ootle_wasm.d.ts web/app/vendor/ootle-wasm-$V/ootle_wasm.d.ts           # the API: expect none
diff web/app/vendor/ootle-wasm-bor-0.49.2/ootle_wasm_bor.d.ts web/app/vendor/ootle-wasm-bor-$V/ootle_wasm_bor.d.ts
python3 -I deploy/ootle/npm-provenance.py repin --from 0.49.2 --to $V
git rm -rq web/app/vendor/ootle-wasm-0.49.2 web/app/vendor/ootle-wasm-bor-0.49.2
git grep -l "ARTIFACT-PIN(ootle-0.50)" -- tools server deploy/scripts web | xargs sed -i '/ARTIFACT-PIN(ootle-0.50)/d'   # comment lines
sed -i 's/ *# ARTIFACT-PIN(ootle-0.50).*//' deploy/config/mutis.toml.example                  # a trailing comment: keep the setting
git grep -n "ARTIFACT-PIN(ootle-0.50)"                       # only this runbook: its commands and the §3a walletd row (the real value)
python3 -I -m unittest discover -s deploy/tests              # PinnedWasmTest and the repin guards
```

`check` prints the PROVENANCE.md facts (tarball, integrity, `gitHead`, build run, Rekor entries) and the files'
sha256: write `PROVENANCE.md` in each new folder after the 0.49.2 ones (`git show HEAD:web/app/vendor/…`), with
"what changed against 0.49.2 for mutis" from §1. Cross-check the run on GitHub
(`gh api repos/tari-project/tari-ootle/actions/runs/<run>`: `npm_publish_ootle_wasm.yml`, `refs/tags/v0.50.0`,
head sha `$C`). The Sigstore signatures are not verified, as for 0.49.2; say so. Then the prose: `NOTICE`, the
sidecar README, the `0.49.2` comments `repin` leaves (`git grep -n 0.49.2 -- ':!docs' ':!deploy/evidence' ':!CHANGELOG.md'`),
and `ootle.wasm_version = "0.50.0"` in `/etc/mutis/mutis.toml` when it is deployed. Run the suites of
upgrade-drill.md §2 (the sidecar selftest must still reject every forged output). `npm-provenance.py check` must
fail on anything that doesn't agree; never edit around it. If it refuses (a packument without `gitHead`, a third
attestation, another commit), stop there: compare by hand on GitHub and the registry, and let a person decide.

## 3. walletd 0.50.0: the binary

### 3a. The official release

From the workstation, as data (`gh api repos/tari-project/tari-ootle/releases/tags/v0.50.0`): the assets
`tari_ootle_walletd-0.50.0-<short>-linux-x86_64` (`<short>` is the commit's first 7 hex, so `d3252ef`, as 0.49.2's was
`aa7b0c8`), its `.sha256` and `tari_ootle-0.50.0.sha256-unsigned.txt`, with GitHub's digests; the tag
(`git/ref/tags/v0.50.0`, then `git/tags/<sha>`: annotated, signature verified, and the commit it names, recorded below). On the server, in a new 0700 directory, as in `docs/evidence/2026-10-20/upgrade-0.47.0/checksums.txt`:

```sh
u 'set -e; d=$(mktemp -d /var/tmp/walletd-0.50.0.XXXX); cd $d; b=https://github.com/tari-project/tari-ootle/releases/download/v0.50.0
   n=tari_ootle_walletd-0.50.0-<short>-linux-x86_64
   for f in $n $n.sha256 tari_ootle-0.50.0.sha256-unsigned.txt; do curl -fsSL --proto =https -o $f $b/$f; done
   sha256sum -c $n.sha256; grep " $n\$" tari_ootle-0.50.0.sha256-unsigned.txt; sha256sum *
   chmod 755 $n; ./$n --version; ldd ./$n | grep "not found" || echo "every library found"; echo $d'
```

Four sources must agree: GitHub's asset digest, the `.sha256`, the release's list and the bytes on the server.
Then, with the version and commit in the name, beside the old binaries:

```sh
u 'sudo install -m 0755 -o root -g root <dir>/<n> /opt/tari/bin/tari_ootle_walletd-0.50.0-<short>'
```

| Pin still to record | Value |
|---|---|
| walletd 0.50.0 linux-x86_64 sha256 (the four sources) | ARTIFACT-PIN(ootle-0.50): when the release exists. The CI artifact it will carry (§3a'): `282199b077a2e1388f8ea77d786c4be4a841f7a8a02f46589fba9d0285a07d94`, by the artifact's digest, its `.sha256` and the job log |
| tag v0.50.0 → commit | `d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb`: tag object `3c0c9700bcc2381c6380d329d5512c2dd5cfb5e9`, annotated, Stan Bondi, 2026-11-06T13:33:15Z, "v0.50.0 — protocol V1 on Esmeralda at epoch 12951, no reset", GitHub `verification.verified` true. 34 commits after `a5ea91cc`, the commit the draft notes named (§1) |

### 3a'. If the release is still a draft when the fleet moves: the CI build itself

The release's binaries come from workflow run `42226426470` ("Build Matrix of Binaries", the push of tag v0.50.0,
head `d3252ef1`). Its `create-release` job ran at 14:11 UTC on 2026-11-06 and left a **draft**
(`gh api …/releases/tags/v0.50.0` answers 404 to the public); the run reads `cancelled` because its
`macos-arm64` job was, while `Building linux-x86_64 on ubuntu-22.04` (job 127921038796) succeeded at 14:08 UTC.
Its artifact is the file the release will carry, so prefer it to a source build (§3b). Fetched on 2026-11-06 as
data:

| | |
|---|---|
| Artifact | `tari_ootle_walletd-0.50.0-d3252ef-linux-x86_64`, id 13509545739, a 19,676,024-byte zip whose sha256 is GitHub's digest `51126f4933094c584b3c2d6175068f461c68ec63053551de429301f49c12b07c` |
| Inside | the binary (mode 0755) and its `.sha256` |
| Binary | 65,665,568 bytes, sha256 `282199b077a2e1388f8ea77d786c4be4a841f7a8a02f46589fba9d0285a07d94`: its `.sha256`, and the job log's two `shasum` lines (14:08:10Z, 14:08:26Z) |
| `--version` | `tari_ootle_walletd 0.50.0` (as `build`, in a unit with no network, a read-only file system and no capabilities) |
| Libraries | 13, every one found on the server, as for the 0.49.2 release binary |
| `--help`, `run --help` | equal to 0.49.2's but for the version and the binary's name |

```sh
d=$(mktemp -d); cd "$d"
gh api repos/tari-project/tari-ootle/actions/artifacts/13509545739/zip > artifact.zip    # GitHub keeps it for the run's retention
sha256sum artifact.zip                                                                  # 51126f49…b07c
python3 -I -c 'import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); print(z.namelist()); z.extractall(sys.argv[2])' artifact.zip x
(cd x && sha256sum -c tari_ootle_walletd-0.50.0-d3252ef-linux-x86_64.sha256)
```

A verified copy is already on the server, owned by `build`: `/home/build/work/walletd-0.50.0-d3252ef-ci/`. To use
it, install it under a name that says where it came from, then §3c and §5 with that `NEW`:

```sh
u 'cd /home/build/work/walletd-0.50.0-d3252ef-ci && sha256sum -c tari_ootle_walletd-0.50.0-d3252ef-linux-x86_64.sha256 &&
   sudo install -m 0755 -o root -g root tari_ootle_walletd-0.50.0-d3252ef-linux-x86_64 /opt/tari/bin/tari_ootle_walletd-0.50.0-d3252ef-ci'
```

Once the release is published, its asset's sha256 must be `282199b0…7d94`; if it is, the `-ci` binary is the
release's and nothing needs installing again.

### 3b. Fallback: built from source (no release by about 2026-11-06 08:00 UTC)

`deploy/ootle/build-walletd-src.sh` builds the binary as `build` at the release commit, in
`/home/build/work/ootle-0.50`, with no package installed (the headers it needs are Debian's own packages, unpacked
into a private sysroot) and capped so the live services keep their CPU and memory (`nproc` is 2: one job).

**The 2026-11-05 build is not the release.** It was built at `a5ea91cc`, before the tag moved to `d3252ef1`
(§1): it lacks #3398 and the 33 other fixes, and its store would miss the second migration until a later
binary ran it. Don't install it. Only if no release binaries appear (§3a) build again at `d3252ef1`: `$W/src` is
still at `a5ea91cc`, so move it to the tag first (`prepare` refuses any other commit) and keep `$W/target`,
which saves the third-party crates' compile:

```sh
W=/home/build/work/ootle-0.50; C=d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb
u "sudo -u build mkdir -p $W && sudo -u build tee $W/build-walletd-src.sh >/dev/null && sudo -u build chmod 755 $W/build-walletd-src.sh" < deploy/ootle/build-walletd-src.sh
u "cd /tmp && sudo -u build git -C $W/src fetch -q --depth 1 origin $C && sudo -u build git -C $W/src -c advice.detachedHead=false checkout -q FETCH_HEAD"
u "sudo -u build $W/build-walletd-src.sh 0.50.0 $C prepare"          # checks the tree is at $C and clean
u "sudo systemd-run --unit=ootle-build --uid=build --gid=build -p MemoryMax=4500M -p MemorySwapMax=0 -p CPUWeight=10 -p IOWeight=10 \
   -p StandardOutput=append:$W/logs/build.log -p StandardError=append:$W/logs/build.log $W/build-walletd-src.sh 0.50.0 $C build"
u "sudo tail -3 $W/logs/build.log"                                  # done …, and the binary's sha256
```

It differs from a release binary in two ways: no web UI (the release builds it with pnpm; JSON-RPC is the same)
and other bytes. The 2026-11-05 build at `a5ea91cc` (superseded; for comparison only): `tari_ootle_walletd 0.50.0`,
63,123,664 bytes, sha256 `881e61e5b64c4e4963d2fd74847e42b467c8ab58b2cd85c0c473b11c4aacea81`, linking the same 13
libraries as the 0.49.2 release binary (`ldd`: libssl, libcrypto and libdbus-1 among them), 38 minutes from cold.
Install the `d3252ef1` build with its origin in the name, and check it is the bytes `build.log` names:

```sh
u "sudo install -m 0755 -o root -g root $W/target/x86_64-unknown-linux-gnu/release/tari_ootle_walletd \
   /opt/tari/bin/tari_ootle_walletd-0.50.0-d3252ef-src && sha256sum /opt/tari/bin/tari_ootle_walletd-0.50.0-d3252ef-src"
```

Replace it with the release binary once one exists (§3a, §5 again; the store is already migrated).

### 3c. Either binary, before it goes live

```sh
u 'diff <(/opt/tari/bin/tari_ootle_walletd-0.49.2-aa7b0c8 --help) <(/opt/tari/bin/tari_ootle_walletd-0.50.0-<suffix> --help)'
```

New options are fine; every one `run-walletd.sh` passes (`--network`, `--base-path`, `--config`, `--log-config`,
`--listen-on`, `--authentication`, the `run` subcommand) must still be there. Then upgrade-drill.md §3 on a copy of the
wallet with `NEW=/opt/tari/bin/tari_ootle_walletd-0.50.0-<suffix>`: two migrations
(`2026-11-03-120000_locks_many_per_transaction`, an index; `2026-11-06-120000_remove_v1_authored_templates`, which
deletes the `authored_templates` rows in the V1 layout, SealLog's among them if walletd recorded it), the same
accounts and balances as `rpc balances` on the live wallet, nothing refused by the sandbox.

## 4. Before walletd stops: let the sends settle (2 to 10 minutes)

Only sends (jobs) and SealLog checkpoints go through walletd; payments and claims are found by the mirror and
proven by the sidecar, so they keep working while walletd is down. Pause the Tari sends and the log
(reset-playbook.md §1), then wait until nothing is in flight:

```sh
for f in relay_send direct_send drops demo_pay sponsor decoys seallog; do admin feature $f off; done
u "cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'" <<'EOF'
import sqlite3
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
for what, sql in (("jobs sending (must be 0)", "SELECT count(*) FROM jobs WHERE state = 'sending'"),
                  ("checkpoints pending (must be 0)", "SELECT count(*) FROM seal_checkpoints WHERE state = 'pending'"),
                  ("jobs queued (wait for the resume)", "SELECT count(*) FROM jobs WHERE state = 'queued'"),
                  ("invoices open", "SELECT count(*) FROM invoices WHERE status IN ('pending','seen','proven') AND expires_at > unixepoch()"),
                  ("pack payments pending_check", "SELECT count(*) FROM payments WHERE status = 'pending_check'"),
                  ("claims open", "SELECT count(*) FROM claims WHERE status IN ('pending','seen') AND expires_at > unixepoch()"),
                  ("sale payments pending_check", "SELECT count(*) FROM sale_payments WHERE status = 'pending_check'")):
    print(f"{c.execute(sql).fetchone()[0]:6d}  {what}")
EOF
rpc call transactions.list "'{\"status\":\"Pending\",\"account\":null}'"       # walletd's own: must be empty
```

Run it until the first two lines and walletd's list are empty (a send settles within `SEND_TIMEOUT_S`, 15
minutes). Open invoices and claims are fine; note them, and look again after §7 that each one moved on. Keep clear
of 12:00 UTC, when the daily evidence payment is queued.

## 5. Back up, install, restart (walletd is down for seconds)

One script as root, as `docs/evidence/2026-10-20/upgrade-0.47.0/scripts/swap.sh`, with an exit trap that starts
walletd again whatever fails:

```sh
u 'sudo bash -s' <<'EOF'
set -euo pipefail
NEW=/opt/tari/bin/tari_ootle_walletd-0.50.0-<suffix>                 # §3a or §3b
TS=$(date -u +%Y%m%dT%H%M%SZ); B=/var/backups/mutis; LIVE=/opt/tari/bin/tari_ootle_walletd
RPC="sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py"
umask 077; cd /tmp
trap 'systemctl is-active --quiet walletd || { systemctl start walletd || true; echo "trap: walletd $(systemctl is-active walletd || true)"; }' EXIT
$RPC balances > "$B/balances-$TS-before-0.50.0.json"
systemctl stop walletd
tar -C /home/drive -cf "$B/wallet-$TS-pre-0.50.0.tar" wallet .local/share/tari
sha256sum "$B/wallet-$TS-pre-0.50.0.tar"; tar -tf "$B/wallet-$TS-pre-0.50.0.tar" | grep -c wallet.sqlite
cp -a "$LIVE" "$B/tari_ootle_walletd.$TS"                  # = tari_ootle_walletd-0.49.2-aa7b0c8, for a rollback
install -m 0755 -o root -g root "$NEW" "$LIVE"
sha256sum "$LIVE" "$NEW"; "$LIVE" --version
systemctl start walletd
for i in $(seq 60); do $RPC call wallet.get_info '{}' >/dev/null 2>&1 && break; sleep 2; done   # the migration runs at start
$RPC balances > "$B/balances-$TS-after-0.50.0.json"
diff <(grep -v '"version"' "$B/balances-$TS-before-0.50.0.json") <(grep -v '"version"' "$B/balances-$TS-after-0.50.0.json") \
  && echo "balances unchanged" || echo "BALANCES DIFFER: compare the two files before going on"
echo "TS=$TS"
EOF
```

Restart order: walletd only. mutis-api and Caddy don't talk to walletd; mutis-chain needs no restart (its
cached token is refused after walletd restarts, error 401, and it asks for a new one once). Nothing deploys with
this step: the code on `ootle/0.50` reads 0.49.2 and 0.50.0 alike, and ootle-wasm moves later (§2).

```sh
u 'sudo journalctl -u walletd --since "-5 min" --no-pager | grep -iE "migrat|deserialize|error" | tail -20'
rpc call validator_set.get_status "'{}'"                              # indexer_trust, anchored, walk not failing
for f in relay_send direct_send drops demo_pay sponsor decoys seallog; do admin feature $f clear; done
```

If the fleet already runs 0.50.0 and §9 hasn't published the V2 log yet, the live log's checkpoints fail once
`seallog` is clear again, at a bounded cost and without a word on the site; seallog-v2-cutover.md §0 says why it
stays on.

## 6. Rollback (before epoch 12951 only)

Stop walletd; move the migrated `/home/drive/wallet` and `/home/drive/.local/share/tari` aside (to
`…-0.50.0-<TS>`, so no `-wal` or `-shm` file of the 0.50 run is left beside the restored store);
`tar -C /home/drive -xpf $B/wallet-<TS>-pre-0.50.0.tar`; install `$B/tari_ootle_walletd.<TS>` at
`/opt/tari/bin/tari_ootle_walletd`; start; `rpc balances` against the before file. 0.50.0 migrated the store, so the
tar, not the binary alone, is the way back. After epoch 12951 there is no going back to 0.49.

## 7. Checks afterwards

Right after §5, and once more after epoch 12951 (the first V1 epoch). From the fleet upgrade until §9 has
published the V2 log, `seal-now` and `notarize` can only fail (the live log's template no longer loads): leave
them for §9's end.

```sh
admin canary-now                       # within 15 min: /status.json canary green (delivered, in the mirror, opened)
admin seal-now                         # a checkpoint (10 min after the last at the earliest): seal_checkpoints state committed
admin notarize "$(curl -fsS https://hidebox.app/.well-known/mutis-manifest.json | sha256sum | cut -d' ' -f1)"   # {"committed": true}
python3 -I tests/e2e/run.py --host hidebox --chain --only E-09,E-10,E-13,E-25,E-29,E-30,E-J
```

The notarize names the live release's manifest again (the same hash `notarize-release.py` notarized at its deploy),
so it says nothing new about it. E-10 and E-13 send transactions the browser builds with ootle-wasm; E-25 is the
canary; E-29 and E-30 pay to open; E-J is the judge script.

Then the first receipts' fees against their caps (metering is the one thing 0.50 changes without an epoch), from
the repository's root:

```sh
python3 -I - <tx id> <<'EOF'
import importlib.util, json, sys, urllib.request
s = importlib.util.spec_from_file_location("cbor", "server/mutis/cbor.py"); cbor = importlib.util.module_from_spec(s); s.loader.exec_module(cbor)
req = urllib.request.Request(f"https://ootle-indexer-b.tari.com/transaction-receipts/{sys.argv[1]}", headers={"User-Agent": "mutis"})
fee = cbor.b64(json.load(urllib.request.urlopen(req, timeout=20))["receipt"])[4]   # FeeReceipt
print({"payment": fee[0], "paid": fee[1], "overcharge": fee[2], "cost": sum(fee[3][0].values())})
EOF
```

For a checkpoint (from `/evidence.json`, `seallog.latest_checkpoint.tx_id`) `cost` stays near 6,000 µT of the
1,000,000 it pays; for a delivery (`deliveries[0].tx_id`) near 16,000 of 30,000. A cost above 25,000 for a
delivery means `max_fee_transfer_ut` and wallet.js `FEE_UT` must rise together (every send pays the same fee).

## 8. If walletd is still 0.49.2 at epoch 12951

What doesn't depend on walletd keeps working whatever its version: links and files, the mirror, payments and
claims (found by the mirror, proven by the sidecar), the canary's opening, and every transaction the browser builds
with ootle-wasm 0.49.2 (same transaction and value layouts). Before the epoch, walletd 0.49.2 reads 0.50 indexers
as it reads 0.49 ones (same paths and shapes). After it, walletd 0.49.2 verifies no proof and recomputes no hash
(`IndexerTrust::Trust`), so it may well keep working, but nobody upstream says so: a 0.49 node forks off, and any
answer it parses that carries something only V1 writes (for instance a protocol version of 1: 0.49 knows only 0)
would stop it reading. Watch from the
epoch on:

```sh
u 'sudo journalctl -u walletd --since "-10 min" --no-pager | grep -iE "deserialize|error" | tail'
u 'sudo journalctl -u mutis-chain --since "-10 min" --no-pager | grep -E "walletd_down|seal_failed|job_failed" | tail'
```

At the first "Failed to deserialize response", pause the Tari features (reset-playbook.md §1) before anything else:
a send submitted then stays `Pending` with its inputs and change locked until a walletd that can read its result
sees it, and results age out after one or two epochs (upgrade-drill.md §4). Then §3 to §7.

## 9. SealLog: the V2 build and a new log (from the fleet upgrade on)

The live SealLog can't outlive 0.50.0 and its successor can't be published before it (§1, first row), so the log
has a gap: from the fleet upgrade (at the latest epoch 12951) until the V2 log takes its first checkpoint. In the
gap uploads still get their receipts' leaves in the server's tree, the old log's last checkpoint still verifies
the receipts it covers, and new ones wait for the next checkpoint. Keep the gap short: have the V2 bytes built
and checked before the fleet moves.

**Before the fleet moves: done on 2026-11-06** (no production change; the build ran as `build` in capped units
under `/home/build/work/`). `template/seal_log_v2/` (lane `launch/mainnet`, brought here) builds the unchanged 2.0.0
source against `tari_template_lib = "=0.38.0"`, `tari_template_test_tooling = "=0.50.0"` and
`tari_ootle_template_build = "=0.18.0"`, all from crates.io: each was published on 2026-11-06 between 13:38 and
13:52 UTC from `d3252ef1`, as its `.crate`'s `.cargo_vcs_info.json` says and BUILD-INFO.txt records. Against the
`a5ea91cc` pins only the sources move in `Cargo.lock`, plus tari_bor 0.16.6 → 0.17.0 and ootle_serde 0.6.2 → 0.7.0;
no other third-party crate. `check.sh --v2 --dist` passed: vectors, rustfmt, clippy, tari lint, the 14 tests and
the encoded-vector test under the `d3252ef1` engine (which refuses a V1 definition and any table-writing
operator), the ABI and the build-path checks. The two vectors moved only in the test engine's template address and
entity id (the binary moved); they were blessed, and `server/tests/fixtures/seallog-encoded-0.50.json` is again
their copy. `template/dist-v2/seal_log.wasm`: 107,038 bytes, sha256
`00ca5f34e5f7a2b036319047fd09ab3c112556dbec119d9a5e75735e462f878f`; by hand, `tari_tdef` reads `82 01` after its
length prefix and is byte-identical to the `a5ea91cc` build's (sha256 `2e030356…99b5`), one table of 45 slots,
one active element segment, under 110 KiB. The same bytes serve the mainnet's SealLog.

`tools/verify-deploy.py` now holds every log to `template/dist-v2/`, except the one it names in `V1_LOGS`:
Esmeralda's live log (`component_6a3eae19…bd65`), held to `template/dist/` until `ootle.seallog_component` names
its successor. So this lane can deploy before the V2 log exists, and no other log can pass on the V1 build.
`publish-template.sh check | publish` take `--wasm`.

**When the fleet moves, and then:** the commands, in order, are
[seallog-v2-cutover.md](seallog-v2-cutover.md). In short: a checkpoint against the V1 log after the fleet upgrade
is `AcceptFeeRejectRest` (the fee intent runs, the call fails, `service` pays the cost of what ran and keeps the
rest of `pay_fee`), retried every 10 minutes (`SEAL_RETRY_S`): at most about 0.9 tTARI a day. Turning `seallog`
off stops that, but then `/made` and `/verify` say there is no public record, which isn't true of a log with over 350
checkpoints; `/status.json` has no SealLog check and `/evidence.json` reads `mutis.toml`, so neither changes
either way. So `seallog` stays on through the gap unless the first failed attempt costs far more than a checkpoint.
Then, with walletd 0.50.0: publish the V2 build and a new log, point `ootle.seallog_component` at it, restart
mutis-chain and mutis-api, take a checkpoint, notarize the live release again, verify-deploy.

The worker records each checkpoint's component and that log's own index (migration 003), so the new log starts
at index 0 beside the old rows, as after the 2026-11-02 reset. `/evidence.json` then lists the V1 log under
`seallog.retired` (`RETIRED_LOGS`, shown only once it is no longer the configured log).

## Rehearsal log

| Date | What | Result |
|---|---|---|
| 2026-11-05 | §1 read in v0.49.2..a5ea91cc. §2: `check` on the 0.49.2 downloads gives back both vendored folders byte for byte, with the run and Rekor entries their PROVENANCE files list; a `repin` of a copy of the tree passes deploy/tests. §3b: built on the server as `build`, 23:07 to 23:45 UTC (38 min, 32 min of CPU, 1.8 GB peak, with two other lanes building), the API answering in under 10 ms throughout; §3c: `--help` and `run --help` equal to 0.49.2's but for the name. A throwaway wallet (its own data dir, port 5219, as `build`): made by the 0.49.2 release binary, opened by the build, which ran the one migration at start (`20261103120000`, index `locks_transaction_id`) and kept both accounts' keys and addresses; mutis's client (`info`, `account`, `stealth_balance_ut`, `stealth_utxos`) and `walletd-rpc.py` work against it. Not run: a send, a checkpoint or a dry run (walletd 0.50 dry-runs only from an account on chain, and the faucet was empty) | pass, so far as run |
| 2026-11-06 | Tag v0.50.0 came at 13:33 UTC on `d3252ef1`, not `a5ea91cc`. §1 read again in `a5ea91cc..d3252ef1` (34 commits): #3398 breaks the live SealLog (V1 definition), the rest needs nothing (first row and §9). §2 with `C=d3252ef1…`, both packages on npm (published 13:38 and 13:39 UTC): `check` passes for each (dist.integrity = the tarball's sha512, gitHead and the provenance's commit `d3252ef1`, `refs/tags/v0.50.0`, run 42226426467, which GitHub shows as "Publish ootle-wasm to npmjs", a push of v0.50.0 at head sha `d3252ef1`, success; Rekor 3717962360/3717988059 and 3717966527/3717982009); the `.d.ts` diffs are empty and the glue is byte-identical; `repin`, the 0.49.2 folders and the markers removed, PROVENANCE.md, NOTICE and the comments. deploy/tests 123 OK, server/tests 384 OK (5 skipped); app lint 1031/1031, vectors 97/97, KATs under Node 160/160 (the 2026-11-02 indexer vectors decode as 0.49.2 did), contract 12/12; sidecar 19/20 under Node 22 (selftest G4: every forged output rejected; a tampered wasm refused; the one failure is the test's Node 20 check), test_real_sidecar 4/4; the live SealLog component decodes to the same JSON with ootle-wasm-bor 0.49.2 and 0.50.0. Not run: the headless Chromium steps (A-01 in the browser, A-05, A-09, A-13, the scan bench) and the chain gate page, for want of a Chromium where this ran; anything on the server | pass, so far as run; SealLog's V2 build and republish open (§9) |
| 2026-11-06 (later) | §9's first step, as `build` on the server in capped units (MemoryMax 4500M, CPUWeight and IOWeight 10) under `/home/build/work/`: `seal_log_v2` re-pinned to the crates.io releases from `d3252ef1`, `check.sh --v2 --dist` passed (14 tests and the encoded vector under the 0.50 engine; vectors re-blessed for the new test-engine template address), `dist-v2/seal_log.wasm` 107,038 bytes, sha256 `00ca5f34…878f`, ABI `2e030356…99b5`; a second build from clean in another directory gave the same bytes. Brought onto this lane with verify-deploy's `V1_LOGS` exception and `publish-template.sh --wasm`; deploy/tests 132 OK, server/tests 385 OK (5 skipped), Node KATs 161/161. §3a': the CI artifact of run 42226426470 fetched (zip = GitHub's digest `51126f49…b07c`; binary `282199b0…7d94` = its `.sha256` = the job log), `--version` 0.50.0, `--help` and `run --help` equal to 0.49.2's but for the name, in a unit with no network; staged, not installed. seallog-v2-cutover.md written: why `seallog` stays on through the gap | pass; nothing on chain, no service touched |
