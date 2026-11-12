<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm` 0.53.2

The official Tari Ootle client crypto (Rust compiled to WebAssembly by wasm-bindgen), vendored as
files. Never installed with npm. License: BSD-3-Clause (`LICENSE`, from the source repository at the
same commit; the npm package declares BSD-3-Clause but ships no license file).

## What was fetched and checked (2026-11-12, the day after v0.53.2 was tagged, with curl as data)

`deploy/ootle/npm-provenance.py check` held these to each other (as deploy/ootle/upgrade-0.52.md §2; the upgrade to 0.53.2 is in CHANGELOG.md).

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.53.2.tgz` (504,218 bytes), published 2026-11-11T09:40:09Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-X+Rc/111B/SvguVt8y/mEH2JYkj9nclg9iMpJMeNdXh3gEAUUh+9sl3Eh23lt2FLTRAtCSsN9X0j0SasuRn0HQ==` |
| Tarball sha512, computed locally | identical (`5fe45cff5d7507f4…` in hex) |
| Registry `gitHead` | `4be6db38fbee738b23624e64ad7ab90a52bc737c` |
| SLSA provenance (`https://slsa.dev/provenance/v1`) and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm@0.53.2`, sha512 `5fe45cff5d7507f4…` = the tarball (both attestations) |
| Source repository | `https://github.com/tari-project/tari-ootle`, ref `refs/tags/v0.53.2` |
| Source commit | `4be6db38fbee738b23624e64ad7ab90a52bc737c`, the commit tag `v0.53.2` names (46 commits after 0.52.0's `4ee751c4`) |
| Cross-check on GitHub | tag `v0.53.2` (annotated, `f3af63ee…`, tagged 2026-11-11T09:24:49Z, signature verified) points at that commit; workflow run `42994973138` ("Publish ootle-wasm to npmjs", `.github/workflows/npm_publish_ootle_wasm.yml`, event push of `v0.53.2`, head sha `4be6db38…`, attempt 1, success) |
| Transparency log | Rekor entries 3807182036 (provenance) and 3807284736 (npm publish attestation) |

**Not verified:** the Sigstore signatures on those attestations. We parsed the DSSE payloads and
matched the digests; we did not run a Sigstore verifier, because none is available without a
third-party toolchain. Anyone can re-check them with Sigstore's own verifier (`cosign`).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bg.wasm` | `072f77c11de0ab34e0cae1cc9ffc3f732995fbed3ffb03ddfdb7027b1164c3ae` | 1,325,908 |
| `ootle_wasm_bg.js` (glue) | `1b5933930f06b0be346a5bcb2e679a7a486512e61a4f9d1f40dfb94320a9f044` | 60,400 |
| `ootle_wasm.d.ts` (types, reference only) | `1c9d69b476fe74481b9784690ba0c41987aa38bf39881e58aaa716275c592d8c` | 20,135 |
| `LICENSE` (tari-ootle v0.53.2) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

`SHA256SUMS` lists the same values (`sha256sum -c SHA256SUMS`). The two hashes the build checks
(spec §3.3 step 7) are the `.wasm` and the glue. At run time `../ootle-wasm-shim.js` hashes the
`.wasm` bytes again and refuses to instantiate anything else, in the browser and in the sidecar.

## What changed against 0.52.0 for mutis

Only the `.wasm`. The glue, the types and the license are byte-identical to 0.52.0's (same sha256), so the API mutis
calls and the way the shim loads the module are unchanged; `crates/ootle_wasm` is the 0.52.0 source but for its
version. No third-party crate moves in `Cargo.lock` (only Ootle's own crates change version). What the new build
carries is the engine types' stricter rules, which the validators of 0.53 apply too: one commitment once across a
transaction's confidential and stealth statements and withdrawals (#3646), withdrawal inputs bounded at decode
(#3683), a fee breakdown decoded in canonical form (#3684), canonical substate address prefixes and CBOR bignum
amounts (#3521). The transaction, its signing message and the stealth statements the browser builds keep their
layout, and a send of wallet.js (key-path inputs, distinct UTXOs, a canonical seal key) meets every one of them.
Esmeralda and the MainNet both run 0.53.2 (indexers and validators, `/info`, 2026-11-12).

Not vendored: `ootle_wasm.js` (the bundler entry, replaced by `../ootle-wasm-shim.js`),
`package.json` and `README.md`. The glue's only import from the page is `crypto.getRandomValues`
(and `Error`); it never touches `WebAssembly`, the DOM or the network.

## Reproduce

```sh
curl -fsS -o ootle-wasm-0.53.2.tgz https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.53.2.tgz
echo "sha512-$(openssl dgst -sha512 -binary ootle-wasm-0.53.2.tgz | base64 -w0)"   # = dist.integrity above
curl -fsS https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2footle-wasm@0.53.2   # DSSE payloads
mkdir x && tar -xzf ootle-wasm-0.53.2.tgz -C x && (cd x/package && sha256sum ootle_wasm_bg.wasm ootle_wasm_bg.js ootle_wasm.d.ts)
gh api repos/tari-project/tari-ootle/git/ref/tags/v0.53.2; gh api repos/tari-project/tari-ootle/actions/runs/42994973138
```
