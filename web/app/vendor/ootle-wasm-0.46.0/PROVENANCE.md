<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm` 0.46.0

The official Tari Ootle client crypto (Rust compiled to WebAssembly by wasm-bindgen), vendored as
files. Never installed with npm. License: BSD-3-Clause (`LICENSE`, from the source repository at the
same tag; the npm package declares BSD-3-Clause but ships no license file).

## What was fetched and checked (2026-10-13, the jarvis box, with curl as data)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.46.0.tgz` (495,859 bytes), published 2026-10-13T10:03:26Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-EwTH+dKSN1XqWxSiR1ETRXQKj87AwJ6GnIQFXzTo0zgV3CGnn60imMSM9zofd6KG8+51FcmrcLsCmqWBTq9wVA==` |
| Tarball sha512, computed locally | identical (`1304c7f9…4eaf7054` in hex) |
| Registry `gitHead` | `cc8a83bcab88e03e0fcf760d2652ab6f1e067d8a` |
| SLSA provenance (`https://slsa.dev/provenance/v1`) and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm@0.46.0`, sha512 `1304c7f9…4eaf7054` = the tarball (both attestations) |
| Source repository | `https://github.com/tari-project/tari-ootle`, ref `refs/tags/v0.46.0` |
| Source commit | `cc8a83bcab88e03e0fcf760d2652ab6f1e067d8a` (the same commit as the `tari_ootle_walletd 0.46.0-cc8a83b` binary we run) |
| Cross-check on GitHub | tag `v0.46.0` (annotated, `b2fa1e5b…`, signature verified by GitHub) points at that commit; workflow run `38380202149` ("Publish ootle-wasm to npmjs", `.github/workflows/npm_publish_ootle_wasm.yml`, event push of `v0.46.0`, head `cc8a83bc…`, conclusion success); `crates/ootle_wasm/wasm/Cargo.toml` at the tag is 0.46.0. The GitHub release has no wasm asset, so the tag and the run are the GitHub side of the check |
| Build workflow | `.github/workflows/npm_publish_ootle_wasm.yml`, GitHub-hosted runner, run `38380202149` attempt 1 |
| Transparency log | Rekor entries 3243649512 (provenance) and 3243652870 (npm publish attestation) |

**Not verified:** the Sigstore signatures on those attestations. We parsed the DSSE payloads and
matched the digests; we did not run a Sigstore verifier, because none is available without a
third-party toolchain. Anyone can re-check them with Sigstore's own verifier (`cosign`).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bg.wasm` | `2856d86b688959fc6620ac8cf2cb4629ee554c94bd81a6baaa2a71a7e7a393f2` | 1,289,871 |
| `ootle_wasm_bg.js` (glue) | `2a338a3c8ef81b314c41487c9e2dc3d1f77942ea9f47c672fd971ab40d3ac36b` | 55,787 |
| `ootle_wasm.d.ts` (types, reference only) | `afe54a5ac884104aae5e1e2f2986c7671dad2a2daf47a75742603416933a5102` | 18,760 |
| `LICENSE` (tari-ootle v0.46.0) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

`SHA256SUMS` lists the same values (`sha256sum -c SHA256SUMS`). The two hashes the build checks
(spec §3.3 step 7) are the `.wasm` and the glue. At run time `../ootle-wasm-shim.js` hashes the
`.wasm` bytes again and refuses to instantiate anything else, in the browser and in the sidecar.

Against 0.45.0, only the `.wasm` changed: the glue, the types, the bundler entry and the license are
byte for byte the same files, so the JavaScript API is the same. The Rust behind the module
(`crates/ootle_wasm`) did not change between the tags; what did, in the crates it links, is decoding
(bounds on instructions, stealth inputs and outputs, access rules), a balance check before a
confidential withdraw proof, and the transaction builder's signing message, which the module doesn't
use (it hashes and signs through its own `sign.rs`, unchanged).

Not vendored: `ootle_wasm.js` (the bundler entry, replaced by `../ootle-wasm-shim.js`),
`package.json` and `README.md`.

The glue's only imports from the page are `crypto.getRandomValues`, `Error` and its own externref
table; it never touches `WebAssembly`, the DOM or the network.

## Reproduce

```sh
curl -fsS -o ootle-wasm-0.46.0.tgz https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.46.0.tgz
echo "sha512-$(openssl dgst -sha512 -binary ootle-wasm-0.46.0.tgz | base64 -w0)"   # = dist.integrity above
curl -fsS https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2footle-wasm@0.46.0   # DSSE payloads
mkdir x && tar -xzf ootle-wasm-0.46.0.tgz -C x && (cd x/package && sha256sum ootle_wasm_bg.wasm ootle_wasm_bg.js ootle_wasm.d.ts)
gh api repos/tari-project/tari-ootle/git/ref/tags/v0.46.0; gh api repos/tari-project/tari-ootle/actions/runs/38380202149
```

## Not vendored: ootle.ts 0.8.0

`@tari-project/ootle`, `ootle-indexer` and `ootle-secret-key-wallet` 0.8.0 were fetched and checked
for 0.45.0 (integrity matched the registry; provenance: `tari-project/ootle.ts` tag `v0.8.0`,
commit `865569e8a5b520d4ab3698c4dba7d4277832349c`) and read for reference. They are **not** shipped:
gate G1 passed with this module alone (`web/app/lib/wallet.js` builds the same transaction shape as the
official wallet daemon), so the browser needs one official artifact instead of four.
