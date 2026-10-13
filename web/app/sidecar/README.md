<!-- SPDX-License-Identifier: MIT -->
# mutis verifier sidecar

A long-lived Node 20 child of the chain worker (`server/mutis/sidecar.py` starts it, as `drive`). It
runs the **same** `web/app/lib` code and the **same** vendored official `@tari-project/ootle-wasm`
0.46.0 as the browser, so the server proves payment amounts with the official library instead of
trusting a wallet (spec D10, gate G4), seals the hourly canary with the real file format, and makes
decoy addresses.

## Start

```sh
MUTIS_API=http://127.0.0.1:8787 /usr/bin/node --experimental-permission --allow-fs-read=<dir> \
  --disallow-code-generation-from-strings <dir>/sidecar.mjs
```

`<dir>` is `release/sidecar` in production (layout below) or `web/app` in the source tree (then the
script is `web/app/sidecar/sidecar.mjs`). Under Node's permission model the process can read only
`<dir>`; file writes, child processes and workers are denied, and `--disallow-code-generation-from-strings`
turns `eval` off. `tests/sidecar_test.py` checks each of those. The environment holds `MUTIS_API` and
nothing else. Node prints one fixed notice on stderr ("Permission is an experimental feature");
`--no-warnings` silences it if wanted.

### Release layout (deploy builder)

`loader.mjs` finds `lib/` next to itself (release) or one level up (source tree):

```
release/sidecar/
  sidecar.mjs  loader.mjs  selftest.json  README.md     <- web/app/sidecar/*
  lib/*.js  lib/package.json                            <- web/app/lib/
  vendor/package.json  vendor/ootle-wasm-shim.js        <- web/app/vendor/ (those two files)
  vendor/ootle-wasm-0.46.0/*                            <- web/app/vendor/ootle-wasm-0.46.0/
```

`lib/package.json` and `vendor/package.json` contain only `{"type": "module"}`. Node looks up the
nearest `package.json` to learn a `.js` file's module type; without these it would walk above the
permitted folder and the permission model would stop it.

## Protocol (§3.4.6)

One UTF-8 JSON request per stdin line, one response per stdout line (≤ 8 MiB), in request order.
Bytes are lowercase hex. Responses are `{"id", "ok": true, …}` or `{"id", "ok": false, "error": code}`.
stderr carries fixed strings only (`mutis-sidecar: ready`, or the load failure line), never data.

| cmd | Request | Response | Notes |
|---|---|---|---|
| `hello` | | `version`, `wasm_sha256`, `node`, `permission` | the process exits with code 2 before answering if the wasm isn't the pinned build |
| `newKeys` | | `owner_sk`, `view_sk`, `owner_pk`, `view_pk`, `address` | receiver and robot-locker keys (init only) |
| `decoyAddress` | | `address` | keys made and dropped inside the sidecar |
| `scan` | `view_sk`, `utxos: [{id, nonce, enc}]` | `found: [{id, value_ut, memo}]` | for each row: AEAD key from `view_sk` and the nonce, then the official `unblindOutput` with the commitment taken from the id. It derives the AEAD key from that commitment and re-commits the decrypted value and mask, so `value_ut` (decimal string) is proven against the chain's commitment; any other row is skipped. `memo` is the decoded memo object (`{"Message": …}`, `{"PayRefAndBytes": hex}`, …) or null |
| `selftest` | | `passed`, `cases` | 3 real Esmeralda outputs must open; 3 forged ones (a value claim against another commitment, a payload swap, a commitment off by one bit) and a fresh swap must be rejected. Data in `selftest.json` (a subset of `tests/vectors/wrap-v2.json`) |
| `canary` | `n`, `canary_token`, `robot_address` | `item_id`, `share_id`, `sealed_at`, `job_id` | seals the §8.4 text (4,000 characters) as a text item, uploads it through `MUTIS_API` with `X-Mutis-Canary` (48 h), makes one link (3 views, 24 h), seals it kind 3 to the robot locker and posts `/courier` with `evidence: true` |
| `openDelivery` | `memo` (string or `{"Message"}`), `owner_sk`, `view_sk`, optional `origins` | `share_id`, `flags`, `ref`, `access_token` | health check. `access_token` (b64u) is what `X-Mutis-Access` needs to open the link once through the real API; the link secret itself stays here |
| `reveal` (P1) | `n` | `n`, `sealed_at`, `fk` (b64u) | the file key of a canary this process sealed, for "yesterday's key"; `not_found` for one sealed before the last restart (keys live in memory only), which the site shows as a missed reveal |

Error codes: `bad_json`, `unknown_cmd`, `bad_request`, `not_a_delivery`, `cannot_open`, `not_found`,
`too_large`, `api_<code>` (an API error during the canary), `internal`.

Measured on ultron (2 vCPU, Node 20.19.2): `scan` 3,861-4,956 foreign rows per second.

The canary's link has no URL (`createLink` without an origin): nobody opens it but the health check,
which uses `openDelivery`'s access token.
