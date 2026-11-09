<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm-bor` 0.52.0

The official decoders for the values a Tari Ootle indexer serves in their CBOR encoding (base64 in the
JSON body, since 0.48): `decodeSubstateValue`, `decodeUtxo` and four more, each returning the JSON the
indexers served before. The browser reads substates through it (`../ootle-wasm-shim.js`, `lib/substate.js`).
Vendored as files, never installed with npm. License: BSD-3-Clause (`LICENSE`, tari-ootle at the same commit).

## What was fetched and checked (2026-11-09, with curl as data)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm-bor/-/ootle-wasm-bor-0.52.0.tgz` (144,630 bytes), published 2026-11-09T13:50:20Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-33PrLgHp4vhNMZkqPqMwX9u1UHuAa9TvtaauecOpPMbJTnnhacskABo6sA5ILTdorVVioeGfcxm2+BvGSPg5YA==`, the tarball's sha512 computed locally (`df73eb2e01e9e2f8…` in hex) |
| Registry `gitHead` | `4ee751c4ee83f75635c958c993af0f3e0e04bfbf`, the commit tag v0.52.0 names (as ootle-wasm 0.52.0) |
| SLSA provenance and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm-bor@0.52.0`, sha512 `df73eb2e01e9e2f8…` = the tarball |
| Build | `refs/tags/v0.52.0`, commit `4ee751c4…`, `.github/workflows/npm_publish_ootle_wasm.yml`, run `42628301811` (attempt 1; the same run as ootle-wasm 0.52.0) |
| Transparency log | Rekor entries 3765878925 (provenance) and 3765883082 (npm publish attestation) |

As for ootle-wasm, the Sigstore signatures were not verified (no verifier without a third-party toolchain).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bor_bg.wasm` | `f22b0e1b7f96769e64731488f8d1e5e09b973af0dd9cd170866f4b21c7b531ee` | 467,210 |
| `ootle_wasm_bor_bg.js` (glue) | `b7d668153c3ef4056030c3cc1eeb1828387e114a3747669f5cd94c4542a53b0b` | 7,851 |
| `ootle_wasm_bor.d.ts` (types, reference only) | `3d7bfabdde554eae89b32e33e1fee8d7310915d6fbf46eb4d545606e66e65def` | 1,024 |
| `LICENSE` (tari-ootle v0.52.0) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

## What changed against 0.50.0 for mutis

Only the `.wasm`: the glue, the types and the license are byte-identical to 0.50.0's, and
`crates/ootle_wasm/bor` is the 0.50.0 source but for its version. The layouts it decodes (`Utxo`,
`SubstateValue`, `TransactionReceipt`, `ExecuteResult`, `FeeReceipt`) are unchanged; a fee breakdown now leaves
out zero charges (#3451), which is the same map with fewer entries. See deploy/ootle/upgrade-0.52.md §1.

The glue imports nothing from the page but `Error`. The server reads the few values it needs with its own
stdlib reader (`server/mutis/cbor.py`), held to this decoder's answers by `server/tests/test_cbor.py`.

Not vendored: `ootle_wasm_bor.js` (the bundler entry; `../ootle-wasm-shim.js` loads the module),
`package.json` and `README.md`.
