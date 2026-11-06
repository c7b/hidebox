<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm` 0.50.0

The official Tari Ootle client crypto (Rust compiled to WebAssembly by wasm-bindgen), vendored as
files. Never installed with npm. License: BSD-3-Clause (`LICENSE`, from the source repository at the
same commit; the npm package declares BSD-3-Clause but ships no license file).

## What was fetched and checked (2026-11-06, the day v0.50.0 was tagged, with curl as data)

`deploy/ootle/npm-provenance.py check` held these to each other (deploy/ootle/upgrade-0.50.md §2).

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.50.0.tgz` (505,690 bytes), published 2026-11-06T13:39:07Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-Pgoq/OO5Ju9eUJoASKTmivb/yiGsMYW+dA14y7SXtqMMt8lZKhry9zZ5oEE42MiHH0zGXWLm4rAAY+6+6WVFrw==` |
| Tarball sha512, computed locally | identical (`3e0a2afce3b926ef…` in hex) |
| Registry `gitHead` | `d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb` |
| SLSA provenance (`https://slsa.dev/provenance/v1`) and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm@0.50.0`, sha512 `3e0a2afce3b926ef…` = the tarball (both attestations) |
| Source repository | `https://github.com/tari-project/tari-ootle`, ref `refs/tags/v0.50.0` |
| Source commit | `d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb`, the commit tag `v0.50.0` names (34 commits after `a5ea91cc`, which the release notes first called the release commit) |
| Cross-check on GitHub | tag `v0.50.0` (annotated, `3c0c9700…`, tagged 2026-11-06T13:33:15Z, signature verified) points at that commit; workflow run `42226426467` ("Publish ootle-wasm to npmjs", `.github/workflows/npm_publish_ootle_wasm.yml`, event push of `v0.50.0`, head sha `d3252ef1…`, attempt 1, success) |
| Transparency log | Rekor entries 3717962360 (provenance) and 3717988059 (npm publish attestation) |

**Not verified:** the Sigstore signatures on those attestations. We parsed the DSSE payloads and
matched the digests; we did not run a Sigstore verifier, because none is available without a
third-party toolchain. Anyone can re-check them with Sigstore's own verifier (`cosign`).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bg.wasm` | `f01d6e7855d60ec53a7f360eb0df5f02b9456d146904755ee5454293a94bca48` | 1,326,245 |
| `ootle_wasm_bg.js` (glue) | `1b5933930f06b0be346a5bcb2e679a7a486512e61a4f9d1f40dfb94320a9f044` | 60,400 |
| `ootle_wasm.d.ts` (types, reference only) | `1c9d69b476fe74481b9784690ba0c41987aa38bf39881e58aaa716275c592d8c` | 20,135 |
| `LICENSE` (tari-ootle v0.50.0) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

`SHA256SUMS` lists the same values (`sha256sum -c SHA256SUMS`). The two hashes the build checks
(spec §3.3 step 7) are the `.wasm` and the glue. At run time `../ootle-wasm-shim.js` hashes the
`.wasm` bytes again and refuses to instantiate anything else, in the browser and in the sidecar.

## What changed against 0.49.2 for mutis

Only the `.wasm`. The glue, the types and the license are byte-identical to 0.49.2's (same sha256), so
the API mutis calls and the way the shim loads the module are unchanged. `crates/ootle_wasm` is the
0.49.2 source but for its version, and one third-party crate moves in `Cargo.lock` (minicbor 2.3.0 to
2.3.1: native `Box<[T]>` codecs and a `Duration` overflow fix; the same wasm-bindgen 0.2.128). The
Ootle crates it compiles in decode more strictly (at most 1,024 input declarations, 1,024 signatures
and 256 blobs; access rules and spend conditions through minicbor's own boxed slices) and encode as
before. The transaction, stealth statement and value
layouts the browser builds and reads are unchanged, and a send of wallet.js (at most 4 inputs, a
signature per input) is far inside the new bounds. Its fee phase, a stealth transfer, its output on
the workspace and `PayFeeFromBucket`, is what 0.50 validators now require of a fee intent (one
instruction that can pay, nothing they refuse there). See deploy/ootle/upgrade-0.50.md §1.

Not vendored: `ootle_wasm.js` (the bundler entry, replaced by `../ootle-wasm-shim.js`),
`package.json` and `README.md`. The glue's only import from the page is `crypto.getRandomValues`
(and `Error`); it never touches `WebAssembly`, the DOM or the network.

## Reproduce

```sh
curl -fsS -o ootle-wasm-0.50.0.tgz https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.50.0.tgz
echo "sha512-$(openssl dgst -sha512 -binary ootle-wasm-0.50.0.tgz | base64 -w0)"   # = dist.integrity above
curl -fsS https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2footle-wasm@0.50.0   # DSSE payloads
mkdir x && tar -xzf ootle-wasm-0.50.0.tgz -C x && (cd x/package && sha256sum ootle_wasm_bg.wasm ootle_wasm_bg.js ootle_wasm.d.ts)
gh api repos/tari-project/tari-ootle/git/ref/tags/v0.50.0; gh api repos/tari-project/tari-ootle/actions/runs/42226426467
```
