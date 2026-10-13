<!-- SPDX-License-Identifier: MIT -->
# app-core tests

Tests for `web/app/lib`, the sidecar and the vendored ootle-wasm. Python stdlib, Debian `node` 20 and
Chromium only: nothing to install, no npm.

## One command

On the server as `build`, from a copy of the repository (the browser and Node 20 live there):

```sh
python3 -I web/app/tests/run_all.py
```

It runs, in order, and prints a summary (last run: `ALL PASS (9 steps)`):

| Step | What | Last result |
|---|---|---|
| `lint_core.py` | §0.7 rules on these folders, stdlib-only Python, the A-06 import graph and size of the widget path | 836/836 |
| `vectors/crosscheck.py` | independent Python re-computation of the frozen vectors | 80/80 |
| `node-run.mjs` | every suite that needs no browser, under Node 20 (what the sidecar imports); a Worker stand-in runs the PoW | 118/118 |
| `headless.py` | every suite in headless Chromium 154 with the production app CSP and Trusted Types | 118/118 |
| `headless.py --jitless --fragment nowasm` | V8 without WebAssembly (Tor Browser Safer-like): anonymous links still work | 75/75 |
| `sidecar_test.py` | the sidecar exactly as the chain worker starts it: protocol, G4, permissions | 16/16 |
| `bench/` PoW | 18-bit proof of work at 6x CPU throttling (A-13), fails above 2 s | main-thread median 455 ms on 2026-10-12 (174-612 across earlier runs) |
| `bench/` scan | trial decryption in the page, 390x844 touch emulation, 4x throttling; a report (the 1,000 rows/s target of §10.6 is for a real phone), failing only below 500 | 1,120 rows/s on 2026-10-12 (930-1,235 across earlier runs) |
| contract | `contract.test.js` through `node-run.mjs --api`, against `server/bin/mutis-api --dev --pow-bits 8` started from the same checkout (fresh data directory, free port, one judge pass inserted); prints the server log tail on failure | 12/12 |

Any single step runs on its own, e.g. `python3 -I web/app/tests/headless.py` (prints the page's
PASS/FAIL lines and `title: TESTS PASS n/n`) or `node web/app/tests/node-run.mjs`.

## Files

| File | Purpose |
|---|---|
| `run.html`, `run.js`, `run.css`, `suites.js` | browser runner; the title becomes `TESTS PASS n/n` or `TESTS FAIL k/n` |
| `node-run.mjs` | Node 20 runner for the same suites (those with `env = 'any'`); `--api <origin>` runs `contract.test.js` against a real API instead |
| `*.test.js` | suites: `b64 sha256 crypto format links identity emoji ootle courier pow filetype exif seal-open pow-gates scan wallet locker receipts ui-helpers`, plus `nowasm` for the jitless run and `contract` for the real API |
| `harness.js` | assertions and fixture loading for both runners |
| `fake-api.js` | in-memory stand-in for the §6 API (installed over `fetch`) that records every request, so tests can show no secret leaves the client; it follows the server where the client depends on it (upload session vs item expiry, link expiry rules, PoW or judge pass on gated routes, password-only PoW after 3 wrong tries), and `contract` checks the same flows against the server itself |
| `outputs.js` | builds chain-shaped stealth outputs offline with the official library |
| `headless.py` | stdlib CDP runner: serves `/app/**`, `/vendor/**`, `/shared/**` (and the server's and the template's vectors) with the app CSP, drives Chromium over `--remote-debugging-pipe`, fails on any CSP/Trusted Types violation; `--indexer` adds an allowlisted pass-through to the public indexer for the gate pages |
| `sidecar_test.py`, `make-rows.mjs` | sidecar protocol tests and the scan benchmark rows |
| `lint_core.py` | lint for `lib/`, `sidecar/`, `vendor/` (shim), `tests/` |
| `run_all.py` | the one command above |
| `vectors/format-v1.json`, `vectors/wrap-v2.json` | frozen vectors shared with the server builder (§3.4.8) |
| `vectors/generate.mjs` | regenerates both (Node 20) and `../sidecar/selftest.json`; a byte change in `format-v1.json` is a format break |
| `vectors/crosscheck.py` | recomputes everything without AES or ristretto with Python's stdlib |
| `vectors/esmeralda-outputs.json`, `vectors/fetch_outputs.py` | real outputs of four Esmeralda transactions (kept as data, so tests survive a testnet reset) |
| `vectors/merkle-rfc9162.json`, `vectors/merkle_vectors.py` | RFC 9162 inclusion proofs from an independent Python implementation |
| `vectors/seallog-component.json` | the research SealLog component on Esmeralda, as an indexer returned it: it has an owner, so `/verify` must refuse it. The 2.0.0 state and the Merkle leaves, roots and proofs come from the template builder (`template/seal_log/tests/vectors/`, served by `headless.py`) |
| `fixtures/exif/*`, `fixtures/exif/make_fixtures.py` | photos with planted GPS/Exif/XMP/IPTC/comments/trailers, and truncated copies (ffmpeg + stdlib) |
| `bench/bench.html`, `bench/bench.js` | PoW and scan benchmarks |
| `gates/chain.html`, `gates/chain.js`, `gates/walletd_send.py` | the live gate checks on Esmeralda (below) |
| `evidence/` | gate outputs and transactions, and a screenshot of the passing page |

## Known-answer sources

HKDF: RFC 5869 A.1-A.3. PBKDF2-HMAC-SHA256: RFC 7914 §11. AES-256-GCM: NIST CAVP
`gcmEncryptExtIV256.rsp` (four vectors, three with AAD). SHA-256: FIPS 180-4 examples and 1,000 random
inputs against WebCrypto. bech32m: BIP-350. The emoji alphabet: tari-project/tari v6.1.0
`base_layer/common_types/src/emoji.rs`. Every constant was checked byte for byte against those files,
fetched on 2026-10-11.

## Live gates (Esmeralda, by hand)

These spend testnet tTARI, so they are not part of `run_all.py`. Run on the server; `walletd_send.py` as
`operator` (walletd's port admits uids 0, 1000, 1002), the pages as `build`:

```sh
H="python3 -I web/app/tests/headless.py --page /app/tests/gates/chain.html --indexer"
$H --fragment mode=addr                          # LOCKER, WALLET addresses and a kind-3 MEMO + EXPECT_S
python3 -I walletd_send.py service <WALLET> 2000000             # fund the browser wallet
python3 -I walletd_send.py service <LOCKER> 1000 '<MEMO>'       # walletd -> seed address (G2c)
$H --fragment 'mode=check&utxos=<ids>&s=<EXPECT_S>'             # browser decrypts and unwraps (G2c)
$H --fragment 'mode=send&utxos=<wallet utxo id>&amount=1000'    # browser builds, signs, submits (G1)
$H --fragment 'mode=check&utxos=<new ids>&s=<EXPECT_S>'         # the delivery opens; change returned
curl -s https://ootle-indexer-a.tari.com/transaction-receipts/<tx>  # later: the committed receipt
```

`transactions/<tx>/result` answers only for a few hours after commit; the receipt stays
(`evidence/receipts-recheck.txt`).
