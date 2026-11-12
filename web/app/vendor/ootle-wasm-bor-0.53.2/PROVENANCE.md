<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm-bor` 0.53.2

The official decoders for the values a Tari Ootle indexer serves in their CBOR encoding (base64 in the
JSON body, since 0.48): `decodeSubstateValue`, `decodeUtxo` and four more, each returning the JSON the
indexers served before. The browser reads substates through it (`../ootle-wasm-shim.js`, `lib/substate.js`).
Vendored as files, never installed with npm. License: BSD-3-Clause (`LICENSE`, tari-ootle at the same commit).

## What was fetched and checked (2026-11-12, with curl as data)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm-bor/-/ootle-wasm-bor-0.53.2.tgz` (145,109 bytes), published 2026-11-11T09:33:36Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-6oz12tze80TfF6r/0IgDfEoPp8xSUgIVOebq/BsuWEhnI9Iztqh39PnGauMduTc2se3ojYPI3h3qyLluWbMVyQ==`, the tarball's sha512 computed locally (`ea8cf5dadcdef344…` in hex) |
| Registry `gitHead` | `4be6db38fbee738b23624e64ad7ab90a52bc737c`, the commit tag v0.53.2 names (as ootle-wasm 0.53.2) |
| SLSA provenance and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm-bor@0.53.2`, sha512 `ea8cf5dadcdef344…` = the tarball |
| Build | `refs/tags/v0.53.2`, commit `4be6db38…`, `.github/workflows/npm_publish_ootle_wasm.yml`, run `42994973138` (attempt 1; the same run as ootle-wasm 0.53.2) |
| Transparency log | Rekor entries 3807170703 (provenance) and 3807191989 (npm publish attestation) |

As for ootle-wasm, the Sigstore signatures were not verified (no verifier without a third-party toolchain).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bor_bg.wasm` | `61dca2064ef9e993a59c0ffa942f136bb4f113a5a80e580b39d04e5c3a24f0ce` | 471,390 |
| `ootle_wasm_bor_bg.js` (glue) | `b7d668153c3ef4056030c3cc1eeb1828387e114a3747669f5cd94c4542a53b0b` | 7,851 |
| `ootle_wasm_bor.d.ts` (types, reference only) | `3d7bfabdde554eae89b32e33e1fee8d7310915d6fbf46eb4d545606e66e65def` | 1,024 |
| `LICENSE` (tari-ootle v0.53.2) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

## What changed against 0.52.0 for mutis

Only the `.wasm`: the glue, the types and the license are byte-identical to 0.52.0's. The decoder now refuses what a
canonical encoder never writes (trailing bytes, duplicate map keys; #3480) and reads CBOR bignum amounts and
indefinite-length strings (#3480, #3521). The layouts it decodes (`Utxo`, `SubstateValue`, `TransactionReceipt`,
`ExecuteResult`, `FeeReceipt`) are unchanged; a fee breakdown is decoded in canonical form (#3684).

The glue imports nothing from the page but `Error`. The server reads the few values it needs with its own
stdlib reader (`server/mutis/cbor.py`), held to this decoder's answers by `server/tests/test_cbor.py`.

Not vendored: `ootle_wasm_bor.js` (the bundler entry; `../ootle-wasm-shim.js` loads the module),
`package.json` and `README.md`.
