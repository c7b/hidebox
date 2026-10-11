<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm` 0.45.0

The official Tari Ootle client crypto (Rust compiled to WebAssembly by wasm-bindgen), vendored as
files. Never installed with npm. License: BSD-3-Clause (`LICENSE`, from the source repository at the
same tag; the npm package declares BSD-3-Clause but ships no license file).

## What was fetched and checked (2026-10-11, as user `build` on ultron)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.45.0.tgz` (494,660 bytes) |
| Registry integrity (`dist.integrity`) | `sha512-m+6i4E4YaJZxLoKyEyxuPx5k5Yt6ZQ1Z2Ax46VdU8H29uPSG9xo/FbUQ5s5N1/uBXdNH5s0/i8wFbN5mr9noIA==` |
| Tarball sha512, computed locally | identical (re-checked twice: during research and before vendoring) |
| SLSA provenance (`https://slsa.dev/provenance/v1`), subject | `pkg:npm/%40tari-project/ootle-wasm@0.45.0`, sha512 `9beea2e0…afd9e820` = the tarball |
| Source repository | `https://github.com/tari-project/tari-ootle`, ref `refs/tags/v0.45.0` |
| Source commit | `9c626062673760530ffb075b6b006a67becebe5a` (the same commit as the `tari_ootle_walletd 0.45.0-9c62606` binary we run) |
| Build workflow | `.github/workflows/npm_publish_ootle_wasm.yml`, GitHub-hosted runner, run `37451553791` attempt 1 |
| Transparency log | Rekor entries 3107528607 (provenance) and 3107545400 (npm publish attestation) |

**Not verified:** the Sigstore signatures on those attestations. We parsed the DSSE payloads and
matched the digests; we did not run a Sigstore verifier, because none is available without a
third-party toolchain. Anyone can re-check them with Sigstore's own verifier (`cosign`).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bg.wasm` | `57de0088e9b96ecdd47daad41f1c48fcfbf1773358244a4663c1f40766d6d4df` | 1,288,793 |
| `ootle_wasm_bg.js` (glue) | `2a338a3c8ef81b314c41487c9e2dc3d1f77942ea9f47c672fd971ab40d3ac36b` | 55,787 |
| `ootle_wasm.d.ts` (types, reference only) | `afe54a5ac884104aae5e1e2f2986c7671dad2a2daf47a75742603416933a5102` | 18,760 |
| `LICENSE` (tari-ootle v0.45.0) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

`SHA256SUMS` lists the same values (`sha256sum -c SHA256SUMS`). The two hashes the build checks
(spec §3.3 step 7) are the `.wasm` and the glue. At run time `../ootle-wasm-shim.js` hashes the
`.wasm` bytes again and refuses to instantiate anything else, in the browser and in the sidecar.

Not vendored: `ootle_wasm.js` (the bundler entry, replaced by `../ootle-wasm-shim.js`),
`package.json` and `README.md`.

The glue's only imports from the page are `crypto.getRandomValues`, `Error` and its own externref
table; it never touches `WebAssembly`, the DOM or the network.

## Reproduce

```sh
curl -fsS -o ootle-wasm-0.45.0.tgz https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.45.0.tgz
echo "sha512-$(openssl dgst -sha512 -binary ootle-wasm-0.45.0.tgz | base64 -w0)"   # = dist.integrity above
curl -fsS https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2footle-wasm@0.45.0   # DSSE payloads
mkdir x && tar -xzf ootle-wasm-0.45.0.tgz -C x && (cd x/package && sha256sum ootle_wasm_bg.wasm ootle_wasm_bg.js ootle_wasm.d.ts)
```

## Not vendored: ootle.ts 0.8.0

`@tari-project/ootle`, `ootle-indexer` and `ootle-secret-key-wallet` 0.8.0 were fetched and checked
the same way (integrity matched the registry; provenance: `tari-project/ootle.ts` tag `v0.8.0`,
commit `865569e8a5b520d4ab3698c4dba7d4277832349c`) and read for reference. They are **not** shipped:
gate G1 passed with this module alone (`web/app/lib/wallet.js` builds the same transaction shape as the
official wallet daemon), so the browser needs one official artifact instead of four.
