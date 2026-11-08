<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm-bor` 0.50.0

The official decoders for the values a Tari Ootle indexer serves in their CBOR encoding (base64 in the
JSON body, since 0.48): `decodeSubstateValue`, `decodeUtxo` and four more, each returning the JSON the
indexers served before. The browser reads substates through it (`../ootle-wasm-shim.js`, `lib/substate.js`).
Vendored as files, never installed with npm. License: BSD-3-Clause (`LICENSE`, tari-ootle at the same commit).

## What was fetched and checked (2026-11-06, with curl as data)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm-bor/-/ootle-wasm-bor-0.50.0.tgz` (143,165 bytes), published 2026-11-06T13:38:27Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-c5+2DCTPAwnCGdoYhlKQJW7hHxCfrrZDyPyJ08h6UFJ+rDHOGsVws+pYWD98YpAGf5gQ3Gli8PRVy6ZG3Oi8CA==`, the tarball's sha512 computed locally (`739fb60c24cf0309…` in hex) |
| Registry `gitHead` | `d3252ef11de0a4100fe0eb6c0dc6c47b2502f5cb`, the commit tag v0.50.0 names (as ootle-wasm 0.50.0) |
| SLSA provenance and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm-bor@0.50.0`, sha512 `739fb60c24cf0309…` = the tarball |
| Build | `refs/tags/v0.50.0`, commit `d3252ef1…`, `.github/workflows/npm_publish_ootle_wasm.yml`, run `42226426467` (attempt 1; the same run as ootle-wasm 0.50.0) |
| Transparency log | Rekor entries 3717966527 (provenance) and 3717982009 (npm publish attestation) |

As for ootle-wasm, the Sigstore signatures were not verified (no verifier without a third-party toolchain).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bor_bg.wasm` | `98b4e4aa2b0d89de2c8f79ac05b3365bde5ee03273c63ae10549e11aac8690cb` | 467,027 |
| `ootle_wasm_bor_bg.js` (glue) | `b7d668153c3ef4056030c3cc1eeb1828387e114a3747669f5cd94c4542a53b0b` | 7,851 |
| `ootle_wasm_bor.d.ts` (types, reference only) | `3d7bfabdde554eae89b32e33e1fee8d7310915d6fbf46eb4d545606e66e65def` | 1,024 |
| `LICENSE` (tari-ootle v0.50.0) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

## What changed against 0.49.2 for mutis

Only the `.wasm`: the glue, the types and the license are byte-identical to 0.49.2's. The layouts it
decodes (`Utxo`, `SubstateValue`, `TransactionReceipt`, `ExecuteResult`, `FeeReceipt`) are unchanged;
receipts' boxed slices now go through minicbor 2.3.1's own codec, which writes and reads the same
definite-length arrays. New: the abort reason `InputLoadTooLarge` (variant 12), for a transaction whose
inputs in one shard group pass 4 MiB; nothing mutis sends comes near it. See deploy/ootle/upgrade-0.50.md §1.

The glue imports nothing from the page but `Error`. The server reads the few values it needs with its own
stdlib reader (`server/mutis/cbor.py`), held to this decoder's answers by `server/tests/test_cbor.py`.

Not vendored: `ootle_wasm_bor.js` (the bundler entry; `../ootle-wasm-shim.js` loads the module),
`package.json` and `README.md`.
