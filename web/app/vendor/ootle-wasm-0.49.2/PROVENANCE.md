<!-- SPDX-License-Identifier: MIT -->
# Provenance: `@tari-project/ootle-wasm` 0.49.2

The official Tari Ootle client crypto (Rust compiled to WebAssembly by wasm-bindgen), vendored as
files. Never installed with npm. License: BSD-3-Clause (`LICENSE`, from the source repository at the
same tag; the npm package declares BSD-3-Clause but ships no license file).

## What was fetched and checked (2026-11-02, the day of the Esmeralda reset, with curl as data)

| Item | Value |
|---|---|
| Tarball | `https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.49.2.tgz` (503,921 bytes), published 2026-11-02T11:36:01Z, `dist-tags.latest` |
| Registry integrity (`dist.integrity`) | `sha512-vVN7ipbNchVFQWgO3TxAhoiWVPF0R08UeZV6tjFHDQRjTSu88D9YSAIckqHK6cNyGyLQIbzBFIocbcBziIndjQ==` |
| Tarball sha512, computed locally | identical (`bd537b8a96cd7215…` in hex) |
| Registry `gitHead` | `aa7b0c81719e5c3cfaf9bf3b5fb87bd83180cb90` |
| SLSA provenance (`https://slsa.dev/provenance/v1`) and npm publish attestation, subject | `pkg:npm/%40tari-project/ootle-wasm@0.49.2`, sha512 `bd537b8a96cd7215…` = the tarball (both attestations) |
| Source repository | `https://github.com/tari-project/tari-ootle`, ref `refs/tags/v0.49.2` |
| Source commit | `aa7b0c81719e5c3cfaf9bf3b5fb87bd83180cb90` (the same commit as the `tari_ootle_walletd 0.49.2-aa7b0c8` binary we run) |
| Cross-check on GitHub | tag `v0.49.2` (annotated, `1c1330dd…`) points at that commit; workflow run `41436825599` (`.github/workflows/npm_publish_ootle_wasm.yml`, ref `refs/tags/v0.49.2`) |
| Transparency log | Rekor entries 3638586672 (provenance) and 3638598712 (npm publish attestation) |

**Not verified:** the Sigstore signatures on those attestations. We parsed the DSSE payloads and
matched the digests; we did not run a Sigstore verifier, because none is available without a
third-party toolchain. Anyone can re-check them with Sigstore's own verifier (`cosign`).

## Files vendored (byte-identical to the tarball's `package/` folder)

| File | sha256 | Bytes |
|---|---|---|
| `ootle_wasm_bg.wasm` | `26d6531c98866aeefd5b9fb44af3d5dd4f18deb1334e0d81315d53088d1c8eeb` | 1,317,089 |
| `ootle_wasm_bg.js` (glue) | `1b5933930f06b0be346a5bcb2e679a7a486512e61a4f9d1f40dfb94320a9f044` | 60,400 |
| `ootle_wasm.d.ts` (types, reference only) | `1c9d69b476fe74481b9784690ba0c41987aa38bf39881e58aaa716275c592d8c` | 20,135 |
| `LICENSE` (tari-ootle v0.49.2) | `3e0d201a40d7af2808441703bba89f827b78f132dbf3474d4a14ec6684d15036` | 1,536 |

`SHA256SUMS` lists the same values (`sha256sum -c SHA256SUMS`). The two hashes the build checks
(spec §3.3 step 7) are the `.wasm` and the glue. At run time `../ootle-wasm-shim.js` hashes the
`.wasm` bytes again and refuses to instantiate anything else, in the browser and in the sidecar.

## What changed against 0.46.0 for mutis

The Esmeralda reset (0.48.0, then 0.49.x) moved transaction signatures to sr25519; the module still
signs through `sealTransaction` and `addTransactionSigner`. In the API mutis calls:
`stealthDhSecret(network, account_secret, view_secret, public_nonce)` takes the view secret
(`c = H(network || v·R)`, was `k·G·r`); the memo variant `PayRefAndBytes` is now
`DestinationTagAndBytes`, and an address's `memo` is its `destination_tag`; `schnorrSign` is gone
(mutis never called it); a stealth input's `witness` must be given. Keys and addresses derive as
before: the same secret gives the same public key and the same `otl_esm_…` address.

Not vendored: `ootle_wasm.js` (the bundler entry, replaced by `../ootle-wasm-shim.js`),
`package.json` and `README.md`. The glue's only import from the page is `crypto.getRandomValues`
(and `Error`); it never touches `WebAssembly`, the DOM or the network.

## Reproduce

```sh
curl -fsS -o ootle-wasm-0.49.2.tgz https://registry.npmjs.org/@tari-project/ootle-wasm/-/ootle-wasm-0.49.2.tgz
echo "sha512-$(openssl dgst -sha512 -binary ootle-wasm-0.49.2.tgz | base64 -w0)"   # = dist.integrity above
curl -fsS https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2footle-wasm@0.49.2   # DSSE payloads
mkdir x && tar -xzf ootle-wasm-0.49.2.tgz -C x && (cd x/package && sha256sum ootle_wasm_bg.wasm ootle_wasm_bg.js ootle_wasm.d.ts)
gh api repos/tari-project/tari-ootle/git/ref/tags/v0.49.2; gh api repos/tari-project/tari-ootle/actions/runs/41436825599
```
