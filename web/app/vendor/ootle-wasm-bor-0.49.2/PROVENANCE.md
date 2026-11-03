<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm-bor` 0.49.2

The official decoders for the values a Tari Ootle indexer serves in their CBOR encoding (base64 in the
JSON body, since 0.48): `decodeSubstateValue`, `decodeUtxo` and four more, each returning the JSON the
indexers served before. The browser reads substates through it (`../ootle-wasm-shim.js`, `lib/substate.js`).
Vendored as files, never installed with npm. License: BSD-3-Clause (`LICENSE`, tari-ootle at the same tag).

## What was fetched and checked (2026-11-02, with curl as data)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm-bor/-/ootle-wasm-bor-0.49.2.tgz` (145,592 bytes), `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | matches the tarball's sha512 computed locally (`6a23b28a812f502a…` in hex) |
| Registry `gitHead` | `aa7b0c81719e5c3cfaf9bf3b5fb87bd83180cb90`, the tari-ootle v0.49.2 commit (as ootle-wasm 0.49.2 and walletd 0.49.2) |
| SLSA provenance and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm-bor@0.49.2`, sha512 `6a23b28a812f502a…` = the tarball |
| Build | `refs/tags/v0.49.2`, `.github/workflows/npm_publish_ootle_wasm.yml`, run `41436825599` |
| Transparency log | Rekor entries 3638579273 (provenance) and 3638582256 (npm publish attestation) |

As for ootle-wasm, the Sigstore signatures were not verified (no verifier without a third-party toolchain).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bor_bg.wasm` | `95effa09c3e4a7458676269c45229fc687a5a594134e791b5eb5c8d15ca14e89` | 473,221 |
| `ootle_wasm_bor_bg.js` (glue) | `b7d668153c3ef4056030c3cc1eeb1828387e114a3747669f5cd94c4542a53b0b` | 7,851 |
| `ootle_wasm_bor.d.ts` (types, reference only) | `3d7bfabdde554eae89b32e33e1fee8d7310915d6fbf46eb4d545606e66e65def` | 1,024 |
| `LICENSE` (tari-ootle v0.49.2) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

The glue imports nothing from the page but `Error`. The server reads the few values it needs with its own
stdlib reader (`server/mutis/cbor.py`), held to this decoder's answers by `server/tests/test_cbor.py`.

Not vendored: `ootle_wasm_bor.js` (the bundler entry; `../ootle-wasm-shim.js` loads the module),
`package.json` and `README.md`.
