<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm` 0.52.0

The official Tari Ootle client crypto (Rust compiled to WebAssembly by wasm-bindgen), vendored as
files. Never installed with npm. License: BSD-3-Clause (`LICENSE`, from the source repository at the
same commit; the npm package declares BSD-3-Clause but ships no license file).

## What was fetched and checked (2026-11-09, the day v0.52.0 was tagged, with curl as data)

`deploy/ootle/npm-provenance.py check` held these to each other (deploy/ootle/upgrade-0.52.md §2).

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.52.0.tgz` (505,600 bytes), published 2026-11-09T13:50:27Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-RPT57z4HnC3wlCgB6tAPvpVuzATBxfD8JjmG9ajFzTZ6UySPq5+PEZMZX2gSW35cvzROyNaoC6whJl8uH7d1fQ==` |
| Tarball sha512, computed locally | identical (`44f4f9ef3e079c2d…` in hex) |
| Registry `gitHead` | `4ee751c4ee83f75635c958c993af0f3e0e04bfbf` |
| SLSA provenance (`https://slsa.dev/provenance/v1`) and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm@0.52.0`, sha512 `44f4f9ef3e079c2d…` = the tarball (both attestations) |
| Source repository | `https://github.com/tari-project/tari-ootle`, ref `refs/tags/v0.52.0` |
| Source commit | `4ee751c4ee83f75635c958c993af0f3e0e04bfbf`, the commit tag `v0.52.0` names (82 commits after 0.50.0's `d3252ef1`) |
| Cross-check on GitHub | tag `v0.52.0` (annotated, `6a7ca980…`, tagged 2026-11-09T13:45:34Z, signature verified) points at that commit; workflow run `42628301811` ("Publish ootle-wasm to npmjs", `.github/workflows/npm_publish_ootle_wasm.yml`, event push of `v0.52.0`, head sha `4ee751c4…`, attempt 1, success) |
| Transparency log | Rekor entries 3765880261 (provenance) and 3765883533 (npm publish attestation) |

**Not verified:** the Sigstore signatures on those attestations. We parsed the DSSE payloads and
matched the digests; we did not run a Sigstore verifier, because none is available without a
third-party toolchain. Anyone can re-check them with Sigstore's own verifier (`cosign`).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bg.wasm` | `29087e5618c4f5e1c94f31f42a00ccf0f33fc634ddece6f79f1cc37557c85725` | 1,322,810 |
| `ootle_wasm_bg.js` (glue) | `1b5933930f06b0be346a5bcb2e679a7a486512e61a4f9d1f40dfb94320a9f044` | 60,400 |
| `ootle_wasm.d.ts` (types, reference only) | `1c9d69b476fe74481b9784690ba0c41987aa38bf39881e58aaa716275c592d8c` | 20,135 |
| `LICENSE` (tari-ootle v0.52.0) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

`SHA256SUMS` lists the same values (`sha256sum -c SHA256SUMS`). The two hashes the build checks
(spec §3.3 step 7) are the `.wasm` and the glue. At run time `../ootle-wasm-shim.js` hashes the
`.wasm` bytes again and refuses to instantiate anything else, in the browser and in the sidecar.

## What changed against 0.50.0 for mutis

Only the `.wasm`. The glue, the types and the license are byte-identical to 0.50.0's (same sha256), so
the API mutis calls and the way the shim loads the module are unchanged. No third-party crate moves in
`Cargo.lock` (the same wasm-bindgen 0.2.128, js-sys and minicbor 2.3.1); `crates/ootle_wasm` adds refusals only:
an address or a revealed receiver whose key is not a canonical Ristretto point (#3487), and the same input
commitment twice in a stealth inputs statement (#3580). The transaction, stealth statement and value layouts the
browser builds and reads are unchanged (instructions keep their explicit CBOR indices; the signing message is the
same), and a send of wallet.js (key-path inputs, distinct UTXOs, a canonical seal key) passes every new rule of
the 0.51 and 0.52 validators. See deploy/ootle/upgrade-0.52.md §1.

Not vendored: `ootle_wasm.js` (the bundler entry, replaced by `../ootle-wasm-shim.js`),
`package.json` and `README.md`. The glue's only import from the page is `crypto.getRandomValues`
(and `Error`); it never touches `WebAssembly`, the DOM or the network.

## Reproduce

```sh
curl -fsS -o ootle-wasm-0.52.0.tgz https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.52.0.tgz
echo "sha512-$(openssl dgst -sha512 -binary ootle-wasm-0.52.0.tgz | base64 -w0)"   # = dist.integrity above
curl -fsS https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2footle-wasm@0.52.0   # DSSE payloads
mkdir x && tar -xzf ootle-wasm-0.52.0.tgz -C x && (cd x/package && sha256sum ootle_wasm_bg.wasm ootle_wasm_bg.js ootle_wasm.d.ts)
gh api repos/tari-project/tari-ootle/git/ref/tags/v0.52.0; gh api repos/tari-project/tari-ootle/actions/runs/42628301811
```
