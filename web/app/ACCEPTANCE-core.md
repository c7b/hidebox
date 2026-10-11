<!-- SPDX-License-Identifier: MIT -->
# Acceptance: app-core (web/app/lib, sidecar, vendor, tests)

Spec §16.2, for the parts this builder owns. Run on 2026-10-11 on the server (Debian 13, Node 20.19.2,
Chromium 154) as `build`, last after the devil's-advocate fix pass. One command reruns all of it:
`python3 -I web/app/tests/run_all.py` → `ALL PASS (9 steps)`. Step 9 runs the library against the real
API (`server/bin/mutis-api --dev --pow-bits 8` from the same checkout), not only against the fake.

| Id | Status | Evidence |
|---|---|---|
| A-01 KATs in Chromium and Node 20; vectors published and cross-checked | **PASS** | below |
| A-02 round trips and tamper cases | **PASS** | `format.test.js`, `seal-open.test.js`, `contract.test.js` |
| A-03 secret hygiene | **PASS** (library level) | `seal-open`, `locker`, `pow-gates`, `wallet`, `scan` suites; E-03 itself is the deploy builder's E2E |
| A-04 every UI state with its test ids | **WAIVED** here | owned by app-ui (screens); `preview.js` already sets `view-text/-image/-video/-audio` |
| A-05 no CSP / Trusted Types violations; no cross-origin request without "Check directly" | **PASS** (library side) | every page ran under the production app CSP |
| A-06 widget payload, lazy ootle-wasm, storage contents | **PASS** (library side: 28,153 B of 40 KB; 12,807 B left for app-ui) | `lint_core.py` import-graph and size check; store.js |
| A-07 keyboard-only flows | **WAIVED** here | owned by app-ui |
| A-08 lint clean | **PASS** | `lint_core.py` |
| A-09 without WebAssembly | **PASS** (library side) | `--jitless` run |
| A-10 vendored hashes and provenance | **PASS** | `vendor/ootle-wasm-0.45.0/` |
| A-11 photo metadata fixtures | **PASS** | `exif.test.js` in Chromium and Node (now with C2PA manifests) |
| A-12 gates G1, G2, G4 (sidecar) answered | **PASS** | `NOTES-for-integrator.md` §1 (direct mode works; production stays `relay` until E-J) |
| A-13 18-bit PoW ≤ 2 s at 6x throttling | **PASS** (Chromium); real Android pending | `bench/` |
| A-14 kind 3 never opens with the view key alone | **PASS** (unit and live chain); E-12 pending | `ootle.test.js`, gates |

## A-01

```
$ node web/app/tests/node-run.mjs | tail -1
NODE PASS 114/114 (node v20.19.2)
$ python3 -I web/app/tests/headless.py | tail -1
title: TESTS PASS 114/114  (15.8s)
$ python3 -I web/app/tests/vectors/crosscheck.py
crosscheck: 80/80 checks passed
```

The browser page is `/app/tests/run.html` (title `TESTS PASS 114/114`, screenshot
`tests/evidence/run-html.png`). Node runs every suite that needs no browser: all modules the sidecar
imports (`format share ootle courier seal crypto b64 api api-locker`) and the other protocol modules;
a Worker stand-in in `node-run.mjs` runs the proof of work there. §4.15 KATs:
HKDF RFC 5869 A.1-A.3; PBKDF2 RFC 7914 §11; AES-256-GCM NIST CAVP (4 vectors, 3 with AAD);
`sha256Sync` vs WebCrypto on 1,000 random inputs (0-200 bytes) and every length 50-130; Padmé table +
1, 1024, 1025, 2^22, 2^22+1, 2^30; the frozen `format-v1.json` vector (ciphertext, chunk hashes,
ct_hash, meta_ct, wrapped key); `wrap-v2.json` (kind 3/4 blobs byte-identical with fixed r, kind 3
refused with the view key alone, 5 real Esmeralda outputs decrypt to their values, 3 forgeries
rejected); Crockford recovery code round trip and checksum errors; bech32m BIP-350 vectors;
the server builder's `server/tests/vectors/addr.json` (classify, valid, invalid) and `pow.json` (challenge layout, digests, zero bits) agree with this library in both runtimes.
`format-v1.json` and `wrap-v2.json` are in `tests/vectors/`; `crosscheck.py` recomputes everything
without AES or ristretto using only Python's stdlib (HKDF rows, mod-ℓ reductions, Padmé, header,
verifiers, fragments, chunk hashes, identity id, auth verifier, recovery code, safety code, key-file
text, bech32m address keys, PoW verdicts, memo lengths).

Against the real API (`run_all.py` step 9):

```
PASS contract: config: the gate values are strings, the memo origins include ours, the text limit is this library's  [send_mode=relay amount_proof=sidecar]
PASS contract: anonymous text, Once: the item keeps its 20 h expiry and the link inherits it; opens once, then burned  [second open: gone/burned]
PASS contract: 6 MiB file: two chunks, ticket and byte ranges, 3 views
PASS contract: link + password: the wrong password is refused, the right one opens
PASS contract: password only: after 3 wrong tries the server says wait, then wants a PoW; the library solves it and opens  [waited 60 s]
PASS contract: Stop: an aborted upload ends as SealError "aborted" and the server deletes it
PASS contract: locker: register with a PoW; a 7-day Bearer upload and its link without an expiry last 7 days  [link lasts 7.00 days; createdSeq 4]
PASS contract: an anonymous item adopted into the locker with its manage token
PASS contract: dead drop: created with a PoW and no session; a submitter leaves a sealed 3-view link; the job finishes; closed
PASS contract: deliver() in relay mode: our relay takes the sealed link for an address
PASS contract: judge pass (P-12): a drop and a relay send go without a PoW; an unknown pass is dropped and the PoW comes back
PASS contract: inbox scan and /watch over the mirror: cursor saved; /watch starts at the epoch about 7 days back  [head=4 watch from seq 0, 4 rows]
CONTRACT PASS 12/12 (node v20.19.2)
```

## A-02

`format.test.js`, in Node and Chromium:

```
PASS format: A-02 round trips: 0, 1, 1023, 1024, 1025, 4 MiB-1, 4 MiB, 4 MiB+1, 10 MiB, 25 MiB
PASS format: A-02 tampering: flipped bit in any chunk, swapped chunks, dropped last chunk, edited header, edited meta, wrong final flag
PASS format: A-02: a failure releases no plaintext (decryptBlob resolves only when every chunk verified)
PASS seal-open: tampered storage: one flipped byte on the server → IntegrityError, nothing released
```

Every tamper case raises `IntegrityError`; `decryptBlob` returns parts only after all chunks verified,
and the stored layout must equal what the encrypted metadata implies (so a dropped or added chunk, or a
lied size, fails even when the remaining chunks are intact).

## A-03 (library level)

The fake API records every request (URL, headers, body). The suites assert that none contains, raw, in
hex or in base64url: the file key, the link secret `s`, the link part `s₀`, the password, the file name
or the text (`seal-open`), the seed (`locker`, registration), or the recipient's address (`wallet`,
direct send). The judge pass goes only on the PoW-gated requests (`pow-gates` lists them exactly).
Every mirror walk starts on a 64-row grid, so lockers whose cursors fall in the same 64-row block make
byte-identical mirror requests (`scan`: lockers born at rows 3 and 5); the server can't tell whose rows
are whose. Found deliveries are stored as their sealed blobs, never as secrets.

## A-05 (library side)

All browser runs above, the gate pages and the benchmarks were served by `headless.py` with the
production app CSP of §14.2 (`require-trusted-types-for 'script'; trusted-types mutis-url`), and the
runner fails on any CSP or Trusted Types report: 0 in every run. The PoW Worker is created through the
single `mutis-url` policy in `dom.js` (the `locker` suite runs it under enforcement). The only
cross-origin request in the library is `ootle.checkWithIndexer()` (the explicit "Check directly"
button, which now checks transactions through their committed receipts: `checkTxWithIndexer`);
`lint_core.py` fails on any other absolute URL in `lib/`.

## A-06 (library side)

```
$ python3 -I web/app/tests/lint_core.py
widget path, library modules: 18 files, 28,153 bytes gzip-9 (no ootle-wasm in the graph); 12,807 bytes of the 40 KB A-06 budget left for drop-widget.js, its CSS and strings
on demand: exif.js 2,867 B, password.js 3,103 B
LINT PASS 824/824 checks, 77 files
```

The widget path (`seal open filetype pow preview download router i18n store dom` and what they import
statically) never imports `ootle.js`, the wasm shim, `exif.js`, `password.js` or any locker module;
the lint fails if one appears. `exif.js` and `password.js` load with `import()` when a photo or a
password is involved; ootle-wasm loads only through `ootle.ready()` (lazy, hash-checked). The library
leaves app-ui **12,807 B** of the 40 KB budget (9,304 B before the fix pass). localStorage holds
only "recent drops" (`share_id, item_id, manage_token, expires`) and the language; sessionStorage only
the judge pass, if one was entered; IndexedDB only the locker record (§4.8.1) and the inbox state
(sealed blobs, cursor, wallet outputs).

## A-08

`lint_core.py` (above): SPDX header on every source file, no `innerHTML`/`outerHTML`/
`insertAdjacentHTML`/`document.write`/`eval`/`new Function`/string timers, no `http://` URL (except the
SVG namespace identifier), no absolute URL in the library except the indexer origins in `ootle.js`,
no TODO, no attribution lines, no inline styles, stdlib-only Python, browser storage only in
`store.js`, no console output in the library.

## A-09 (library side)

```
$ python3 -I web/app/tests/headless.py --jitless --fragment nowasm | tail -1
title: TESTS PASS 73/73  (18.8s, jitless)
```

With V8 `--jitless` (no WebAssembly), every suite anonymous links depend on passes, including the full
seal → link → open flows; `wasmAvailable()` is false and `ready()` rejects, which the UI turns into
`needs_wasm`.

## A-10

`vendor/ootle-wasm-0.45.0/SHA256SUMS` (`sha256sum -c` OK), `PROVENANCE.md` (registry integrity
`sha512-m+6i4E4Y…r9noIA==` matched; SLSA provenance: `tari-project/tari-ootle` tag v0.45.0, commit
`9c626062…`, workflow `npm_publish_ootle_wasm.yml`; Sigstore signatures not verified, said so), `LICENSE`
(BSD-3-Clause, from the source tag). The `.wasm` and glue hashes equal spec §3.3 step 7. At run time
`vendor/ootle-wasm-shim.js` refuses wasm bytes with any other SHA-256, and the sidecar exits with code 2
on a tampered file (`sidecar_test.py`).

## A-11

```
PASS exif: JPEG: Exif, XMP, IPTC, comment and trailer removed; only the orientation (6) is written back
PASS exif: PNG: only the chunks that draw the image are kept (eXIf, text, tIME and a C2PA manifest with GPS go); still decodes
PASS exif: WebP: only image, alpha, animation and ICC chunks are kept (EXIF, XMP, C2PA go), VP8X flags cleared, RIFF size fixed
PASS exif: a photo with only drawing chunks comes back untouched (removed: false)
PASS exif: truncated photos: original bytes kept, notice "unparsed", upload not blocked
PASS exif: formats we can't clean say so: HEIC/AVIF, MP4/MOV, TIFF; other files pass untouched
PASS exif: stripMetadata(File) keeps the name, type and date; returns the same File when nothing changed
```

Fixtures (`tests/fixtures/exif/`, made by `make_fixtures.py` from ffmpeg images) carry GPS
coordinates in Exif, XMP, IPTC, a comment, a trailer and (PNG, WebP) a C2PA manifest. Every format is
cleaned by allowlist, so a block we don't know goes too. In Chromium the stripped JPEG decodes at
16x32, the same rotated size as the original (orientation 6 kept); PNG and WebP decode at 32x16.

## A-12

`NOTES-for-integrator.md` §1: G1 PASS (tx `45f03981…`, Commit on both indexers, 2.0 s),
G2 a/b/c PASS (tx `0c735d34…` for c), G4 sidecar half PASS (16/16; 3,861-4,956 rows/s). Final:
direct mode works and `wallet.deliver()` falls back to the relay, but production keeps
`send_mode = "relay"` until deploy's E-J passes with two contexts on one /64; `amount_proof =
"sidecar"`; kind 3 possible: yes. Both gate transactions re-checked hours later through their receipts
(`tests/evidence/receipts-recheck.txt`).

## A-13

```
$ python3 -I web/app/tests/headless.py --page /app/tests/bench/bench.html --fragment pow --throttle 6
POW_WORKER_MEDIAN_MS 120 P90 375 RUNS 15
POW_MAIN_MEDIAN_MS 414 RUNS 5
title: BENCH PASS  (5.4s, 6.0x CPU)
```

DevTools CPU throttling slows the page's main thread but not the dedicated Worker (unthrottled the
Worker median is 116 ms), so the conservative figure is the main-thread one: medians of 174-612 ms at
6x across runs on the shared 2-vCPU VPS, all far under 2 s. The real ~150 USD Android run is the
owner's session #1 (§17.3). In-browser scanning at 4x on phone emulation: 930-1,235 rows/s across runs
(§10.6's 1,000 rows/s target is also for a real phone). A mirror page of 1,000 genuine outputs is
594 KB of JSON, 279 KB gzipped; `/watch` reads about the last 7 days by default (300 epochs).

## A-14

Unit (Node and Chromium): a kind-3 blob is refused with the view key alone, with the kind-4
derivation applied to it, and with the view key in the owner slot; kind 4 does open with the view key
(`ootle.test.js`). `/watch` counts kind-3 deliveries as not readable (`scan.test.js`), in its default
7-day window and over the whole mirror. Live: both
kind-3 deliveries on Esmeralda (walletd → locker, and the browser-built G1 send) opened with
owner + view keys and were refused with the view key alone (`tests/evidence/g2c.txt`,
`g1-check.txt`). The E2E E-12 belongs to the deploy builder.
