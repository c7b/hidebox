<!-- SPDX-License-Identifier: MIT -->
# NOTES for the integrator (app-core builder)

Everything here was run on 2026-10-11 on the server (Debian 13, Node 20.19.2, Chromium 154) as `build`,
except the two walletd test sends (as `operator`). Raw outputs are in `tests/evidence/`. The fix pass after
the devil's-advocate review (`REVIEW-devil.md`, with the builder response at its end) changed the
library API in the places marked **(changed)** below.

## 1. Gate answers

| Gate | Answer | Runtime value (12-integration §3) |
|---|---|---|
| **G1** browser builds, signs and submits a stealth transfer | **PASS** | direct mode works; **keep `send_mode = "relay"`** until deploy's E-J passes with two browser contexts on one /64 and records the cold-start time (see "Direct mode in production" below) |
| **G2** (a) seed-derived keys, (b) owner-key DH symmetric, (c) walletd → seed address → browser | **PASS, PASS, PASS** | kind 3 possible: **yes** |
| **G4** sidecar half (Node 20 + permissions, `unblindOutput` rejects forgeries, scan ≥ 2,000/s) | **PASS** | `amount_proof = "sidecar"` once the server's client and the deploy install run it; the server's real-sidecar test passes against this tree (3/3 today) |

### G1: direct mode works, with one official artifact

- **Run:** `tests/gates/chain.html#mode=send` in headless Chromium 154 under the production app CSP
  with Trusted Types enforced (0 violations), through `/api/v1/chain/ix/*` (`headless.py --indexer`,
  an allowlisted pass-through to indexer-b, i.e. the production proxy's job).
- **Result:** tx `45f03981238907134d321e8f6ada288c18d3a5e8745d8f4f8fd28bee856c3d1a`, `Commit` on
  indexer-a and indexer-b, **finalized 2.0 s after submit**. One input (the browser wallet's
  2,000,000 µT output) → two outputs: 1,000 µT to the test locker with a kind-3 courier memo, and
  1,969,000 µT change back to the wallet. The locker opened the delivery (secret matched, view key
  alone refused) and the wallet decrypted its change (`tests/evidence/g1-*.txt|json`).
- **Shape** (same as walletd's own stealth transfers, e.g. research T8 `129618fd…`):
  `fee_instructions = [StealthTransfer (stealth inputs only; revealed output = the fee, to the seal
  key), PutLastInstructionOutputOnWorkspace, PayFeeFromBucket]`, `instructions = []`. The seal key is a
  fresh keypair per transaction and the input is authorised by its one-time key (`stealthDhSecret`). No
  account, vault or sender address appears on chain. Built with raw ootle-wasm calls in `lib/wallet.js`
  (`buildStealthTransferStatement`, `validateStealthTransfer`, `addTransactionSigner`,
  `sealTransaction`, `borEncodeTransaction`).
- **Indexer paths the browser calls (all through our proxy):** `GET epoch-manager/stats`,
  `GET substates/{utxo_id}`, `POST transactions` (body `{"transaction": "<base64 BOR envelope>"}`),
  `GET transactions/{tx_id}/result` (only while waiting for a fresh transaction to finish). The server's
  allowlist now has all four.
- **Fee behaviour:** the transfer reveals exactly `FEE_UT = 30000` µT into the fee bucket; it is spent
  in full (as with walletd; real cost ≈ 15,200). It's the same fee as every relay send and decoy, so a
  direct send doesn't stand out by its fee.
- **ootle.ts 0.8.0 not needed.** I fetched and verified `@tari-project/ootle`, `ootle-indexer` and
  `ootle-secret-key-wallet` 0.8.0 (integrity = registry, provenance = `tari-project/ootle.ts` v0.8.0,
  commit `865569e8`), but its `StealthTransfer` builder can't express a stealth-only spend whose fee
  comes from a revealed bucket (it requires a revealed source account). The browser ships one official
  artifact instead of four. Recorded in `vendor/ootle-wasm-0.45.0/PROVENANCE.md`.
- **Claims this makes true** (§0.1 direct sentence, §1.3 row 4), for a send that went direct: the
  browser seals the file and pays the delivery from its own wallet output; our server relays the signed
  transaction but sees only one-time keys, commitments and encrypted data, so it can't tell the
  recipient. As §1.4 says, the server can link "this locker made a transaction" because it funded the
  input (sponsor grant). `wallet.deliver()` reports per send whether it went direct or by relay, and the
  copy must follow that, not the config.

### Direct mode in production (review M1)

`wallet.deliver()` never strands a send: it goes direct only when `/config` says `send_mode: "direct"`,
`features.direct_send` is on and the wallet covers the courier amount plus the fee; otherwise, or when
the indexer shows the wallet's inputs gone, it uses the relay. What is not measured yet is the **cold
start** of a fresh locker's wallet before its first direct send: an 18-bit PoW for the grant
(main-thread medians 0.17-0.61 s at 6x CPU throttling, A-13), the sponsor job (queued without jitter;
a walletd transfer, which reached finality in about 2 s in G1), the mirror (polled every 3 s, §10.6)
and the browser's scan. That needs the production sponsor job and mirror, so deploy's E-J measures it
end to end. Two more things before `send_mode = "direct"`:

1. `POST /sponsor` allows one grant per /64 per day before the judge-pass check, so a second browser on
   the same network (E-J's two contexts; two judges in one office) never gets one. Those sends go by
   relay, which works but is the weaker claim. Request to the server builder in §3.
2. In direct mode the browser builds the memo, so §14.1's "the server builds every memo" holds only
   for relay sends (review M9). Request to the integrator in §3.

### G2: deterministic keys and kind-3 wraps

- **(a)** `HKDF(seed, "mutis/v1", "ootle-owner"|"ootle-view"|"wallet-…", 64)` reduced mod ℓ (32 B LE)
  is accepted by `ootlePublicKeyFromSecretKey`; public keys are `sk·G` (checked against
  `publicKeyFromSecretKey`); addresses round-trip through `parseOotleAddress`. Non-canonical scalars
  (≥ ℓ) are rejected, so the reduction is required. The one-time spend key of an output paid to a
  seed-derived address matches the output's `auth.Key`, and G1 then spent such an output live.
- **(b)** `encryptedDataDhKdfAead(r, O) == encryptedDataDhKdfAead(o, R)`: 20/20 random pairs, in Node
  and in Chromium (`ootle.test.js`, "G2b").
- **(c)** walletd `service` → the test locker's seed-derived address, tx
  `0c735d349f9941e280a3d1096f66909812cc8338ec2aec6cefafc705351ec4ff`, memo = a kind-3 link sealed in
  Chromium (201 bytes on the current host). Chromium found the output by trial decryption (value 1000,
  memo byte-exact), `parseMemo` accepted it, owner + view keys unwrapped it to the expected secret, and
  the view key alone was refused (`tests/evidence/g2c.txt`).
- So kind 3 ships; `/watch`'s "a view key can't open files sealed to a mutis locker" is true for every
  kind-3 delivery (A-14, tested three ways). Kind 4 opens with the view key, as labelled.
- The gate identity's seed is public on purpose (`SHA-256("mutis gate test seed v1")`, in
  `tests/gates/chain.js`) so anyone can re-run the G2c check. Its wallet still holds the 1,969,000 µT
  change: testnet tTARI with no value, left there deliberately.

### G4, sidecar half

- Debian Node 20.19.2 runs `sidecar.mjs` with exactly the §3.4.6 flags. Measured denials:
  `write:ERR_ACCESS_DENIED spawn:ERR_ACCESS_DENIED worker:ERR_ACCESS_DENIED read-outside:ERR_ACCESS_DENIED eval:EvalError`.
- The official `unblindOutput` rejects every forgery tried: the commitment of a real 2,000,000 µT
  output with the encrypted payload of a real 1,969,000 µT output to the **same** view key (the
  spec's "claims a value its commitment doesn't hold"), a payload swapped between two real locker
  outputs, a commitment one bit off, and a freshly made swap. Why, from the official source
  (`tari-ootle` v0.45.0 `crates/wallet/crypto/src/encrypted_data.rs`): the AEAD key is
  `Blake2b("encrypted_value_and_mask", key ‖ commitment)`, and after decryption the value and mask are
  re-committed and compared (`CommitmentMismatchDecryptedData`). Two independent layers.
- `scan`: **3,861 to 4,956 foreign rows per second** (median of 3 runs of 3,000 rows; target 2,000;
  4,658 in today's last run).
- `sidecar_test.py`: 16/16, including the canary against a fake API and the refusal to start on a
  tampered wasm (exit 2). The server's `test_real_sidecar.py` with `MUTIS_SIDECAR_DIR` pointing at this
  tree: `Ran 3 tests … OK`.

Test funds used: 2.091 tTARI from walletd's `service` (two sends + fees, `tests/evidence/walletd-sends.txt`).

### Commands and outputs (trimmed)

```
# G2c, after walletd sent 1,000 µT with a kind-3 memo to the test locker (tx 0c735d34…)
$ python3 -I web/app/tests/headless.py --page /app/tests/gates/chain.html --indexer \
    --fragment 'mode=check&utxos=<4 ids>&s=e72d7a7c…beadf4'
UTXO utxo_01010101010101010… verified true locker value 1000 wallet no
  memo kind 3 share 9SqKQs7Ahff5oF_cYGeg5Q s matches true
  view key alone on this kind-3 blob: refused
title: GATE PASS  (1.2s)

# G1, the browser wallet spends the 2,000,000 µT walletd sent it (tx aa1360fe…)
$ python3 -I web/app/tests/headless.py --page /app/tests/gates/chain.html --indexer \
    --fragment 'mode=send&utxos=utxo_01…01_68653592…6ba768&amount=1000'
TX 45f03981238907134d321e8f6ada288c18d3a5e8745d8f4f8fd28bee856c3d1a
FEE_UT 30000 INPUTS 1
SECONDS_TO_FINAL 2.0
indexer paths: GET /epoch-manager/stats, GET /substates/{utxo_id}, GET /transactions/{tx_id}/result, POST /transactions
title: GATE PASS  (2.9s)
$ … --fragment 'mode=check&utxos=<2 new ids>&s=37c2d07b…75db07'
UTXO … locker value 1000 wallet no
  memo kind 3 share BI2V4khSKRBgZk2Hz0H_CQ s matches true
  view key alone on this kind-3 blob: refused
UTXO … locker no wallet value 1969000

# Anyone, any time later: the committed receipts (transactions/{id}/result is gone a few hours after
# commit; tests/evidence/receipts-recheck.txt)
$ curl -s https://ootle-indexer-{a,b}.tari.com/transaction-receipts/45f03981…6c3d1a
45f03981 indexer-a Commit up 2 down 1 fee 30000
45f03981 indexer-b Commit up 2 down 1 fee 30000
$ curl -s https://ootle-indexer-{a,b}.tari.com/transaction-receipts/0c735d34…1ec4ff
0c735d34 indexer-a Commit up 2 down 1 fee 30000
0c735d34 indexer-b Commit up 2 down 1 fee 30000

# G4, sidecar half
$ python3 -I web/app/tests/sidecar_test.py
PASS hello: version, pinned wasm hash, node 20, permission model on  [v20.19.2 mutis-sidecar/1]
PASS selftest: real outputs open, every forgery is rejected (G4)
PASS scan speed ≥ 2,000 UTXOs/s (3,000 foreign rows, median of 3)  [4,658 rows/s]
PASS permission model: writes, child processes, workers, reads outside, eval all denied
PASS a wasm file that isn't the pinned build: the sidecar refuses to start  [exit 2]
SIDECAR PASS 16/16
```

## 2. For the app-ui builder: the library API

§3.4.7 signatures are implemented as written, except where noted **(deviation)**. All protocol
modules also run under Node 20. `tests/contract.test.js` shows each flow against the real API.

- **Module loading (A-06) (changed).** Keep these imports static in `drop-widget.js`: `seal open
  filetype pow preview download router i18n store dom`. That path is 18 files, 28,153 B gzip-9, which
  leaves **12,807 B of the 40 KB budget** for `drop-widget.js`, its CSS and its strings. Load with
  `import()` only when needed:
  - `exif.js` (2.9 KB): when `filetype.sniffImage(head)` returns a kind or `file.type` starts with
    `video/` (the stripper only reports a notice for videos);
  - `password.js` (3.1 KB) for `checkPassword()` (the strength hint), when a password mode is chosen.
    `seal.createLink` and `open.accessFor` already load it themselves;
  - `identity session courier drop scan wallet ootle api-locker` when the user picks a locker action,
    so ootle-wasm loads only then. `lint_core.py` fails if any of these becomes a static import of the
    widget path.
- **Seal (changed):** `sealItem(source, {headers, anonymous, expiresAt, dropId, keepFor, onPhase,
  signal, resume})` → `{itemId, uploadId, manageToken, expiresAt, uploadExpiresAt, fk, headerHash,
  sizeStored, chunkCount, headers}`.
  - `expiresAt` (unix seconds) is **required unless the item is kept** (`keepFor`); compute it from
    `/config` limits (anonymous `default_expiry_s` = 24 h, locker 7 days, drops `limits.expiry_s`).
    `item.expiresAt` is the item's expiry, for "Leaves …"; `uploadExpiresAt` is when this upload
    session ends (2 h), for resuming.
  - `createLink(item, {mode, password, maxViews, expiresAt, origin})` → `{shareId, url, fragment, s,
    state, maxViews, expiresAt}`. Without `expiresAt` the link lives as long as its item.
    `url` is `null` without an origin.
  - `SealError {code, resume}`: pass `resume` back to continue from the first missing chunk. Stop
    (`signal` aborted) gives `code: 'aborted'`, no resume, and the upload is deleted on the server.
- **Open (changed):** `linkStatus(shareId)`, `accessFor(status, {s | s0, password})`,
  `peek(shareId, access, {signal, onProgress})`, `openItem(shareId, access, {signal, onProgress})` (uses
  a view; only after **Open it**), `fetchContent(opened, {onProgress, signal})` → plaintext parts,
  released only when every chunk verified. Password-only links: after 3 wrong tries the server first
  answers `ApiError 428 pow_required` **with `retryAfter`** (show the wait, then let the user try
  again); after that `peek`/`openItem` solve the PoW the server asks for by themselves (pass
  `onProgress` to show it). These two modules are additions to §3.4.7 (the same flow serves the
  widget, the drop page, `/send` and the sidecar canary).
- **Judge passes, P-12 (new):** `pow.setJudgePass(code)` with the code from the `/judges` field;
  `null` clears it; a malformed code throws `TypeError`. pow.js keeps it in memory; to carry it from
  `/judges` to the app pages of the same tab, the page that takes it calls `store.saveJudgePass(code)`
  (sessionStorage key `mutis.judge`, this tab only) and every app page calls
  `setJudgePass(store.savedJudgePass())` on load. While set, every PoW-gated request the library makes
  (anonymous upload, locker registration, drop creation, drop delivery, relay send, sponsor grant,
  demo pay) carries `X-Mutis-Judge` instead of a PoW; no other request carries it. If the server calls
  the pass unknown or used up, the library drops it and sends that request again with a PoW:
  `hasJudgePass()` turns false; then call `saveJudgePass(null)` and say "That judge pass is used up;
  the anti-bot check is back."
- **Photos:** `exif.stripMetadata(file)` → `{file, removed, notice: null|'video'|'heic'|'unparsed'}`;
  "Keep original" = use the original file. PNG and WebP are cleaned by allowlist now, so C2PA manifests
  and unknown chunks go too (review M3).
- **Recipient safety, P-14 (changed):** `filetype.checkRisky(name, head)` → `{risky, active, reason,
  ext}` with `head` = the first `SNIFF_BYTES` (0x8006) bytes. `risky`: a program (anonymous uploads
  refuse it; the viewer's two-step save). `active`: a web page, SVG, saved web page, OneNote,
  macro-enabled Office file or Excel web query (`html htm xhtml xht shtml svg svgz mht mhtml one onepkg
  docm dotm xlsm xltm xlam pptm potm ppsm ppam sldm iqy slk`): uploads are allowed; the viewer shows a
  softer notice before **Save** (copy request in §3). Also `isExecutableName`, `isActiveDocumentName`,
  `isArchiveName`, `sniffImage`.
- **Text secrets:** at most `TEXT_MAX_CHARS` = 10,000 **code points** (`Array.from(text).length`, the
  same number as `/config.text_max_chars`); the counter should count the same way.
- **PoW:** call `prefetchPow('upload')` on page load; `solvePow(purpose, {signal, onProgress})` →
  `{challenge, nonce}`. `onProgress` gets the probability of having found it (honest, monotone).
- **Viewer:** `parseFragment(location.hash)`; kinds 1/2 are links, 3/4 deliveries:
  `decodeInner(await unwrapBlob(identity, blob, kind))` → `{shareId, s, isDeadDrop}`, then the open
  flow with `{s}`. For `/t#4` with a pasted view key: `unwrapBlob({viewSk, viewPk: await
  viewPublicKey(viewSk)}, blob, 4)`. Call `router.clearFragment()` only after a successful open.
  `preview.makePreview(parts, meta, {label})` sets `data-testid` `view-text|view-image|view-video|view-audio`.
  `download.saveFile(parts, meta.name)` (sanitized, octet-stream, revoked after 60 s).
- **`wrong-key` state:** a blob doesn't say which address it was sealed to (by design), so the page
  can't show "It was sealed for {safety code}". Show "Your locker is {safety code}" only.
- **No WebAssembly (`needs_wasm`, review M8):** on `/d/*` the submitter can't seal to the drop without
  WebAssembly, and the people a tip line is for are the ones who turn it off. Use a `/d/*` variant of
  the copy that names the two common causes and the way past each: Tor Browser's Safer level (set the
  security level to Standard while leaving the file) and iPhone Lockdown Mode (exclude this one site
  from Lockdown Mode in Safari's website settings). That Lockdown Mode turns WebAssembly off is from
  WebKit's documentation, not tested here; the owner checks it, and the exact iOS wording, on a real
  iPhone.
- **Identity** (deviation: extra fields; **changed:** `persistent` is gone): `{id, seed, authKey,
  vaultKey, locker, wallet, safetyCode: {emoji: string[12], hex: "xxxx xxxx …"}, created, createdSeq,
  dropIndex, drops, keySaved, storageAvailable, persisted, dropTag(i), dropManage(i)}`.
  - `storageAvailable` is false only when IndexedDB is blocked. It is **true in private windows**
    (Chrome, Firefox and Safari give them an in-memory IndexedDB that is wiped on close), so it can't
    detect them.
  - `persisted` is the answer to `navigator.storage.persist()`, asked at locker creation and restore
    (Firefox may show a permission prompt then), and to `persisted()` on load: `true`, `false` or
    `null` (unsupported).
  - Whatever the two say, keep the key-file banner until the user presses "I saved it" (`keySaved`).
    Show the "won't keep your key" copy when `storageAvailable === false`, and the eviction hint when
    `persisted !== true`.
  - Extras: `updateIdentity(identity, patch)` (keySaved, drops, dropIndex, createdSeq),
    `identityFromSeed`, `parseRecoveryCode`, `keyFileName`, `lockedKeyFileText(identity, passphrase)`
    (brand P-15: passphrase on by default), `restoreFromText(text, passphrase)`,
    `passwordManagerEntry(identity)`, `KeyError.code` ∈ `no_key|checksum|locked|wrong_passphrase`.
- **Safety code: 12 emoji** (12-integration §2), shown 3×4; `hex` is 6 groups of 4 for the aria-label.
- **Sessions:** `ensureSession(identity, {signal, onProgress})` (registers with a PoW or a judge pass on
  first use), `authHeaders()`, `endSession()`, `deleteLocker(identity)`.
- **Drops:** `createDrop(identity, label)` → `{drop_id, url}`, `getDrop(id)`, `closeDrop(identity, i)`,
  `rotateDrop(identity, i)` ("New link"), submitter side `leaveInDrop(drop, link)` → `{job_id}` then
  `courier.waitJob(job_id, {onState})`. `DropError.code` ∈ `limit|unknown`. A drop item's
  `expiresAt` is `now + drop.limits.expiry_s` and its link's `maxViews` is `drop.limits.views`.
- **Inbox and /watch (changed):** `scan(identity, {onDelivery, onReceipt, onProgress, signal})`,
  `inboxState(identity)` → `{deliveries, receipts, wallet, cursor}` (deliveries store only the sealed
  blob; `deliverySecret(identity, d)` unwraps it again when opened). `watch({viewSk, viewPk}, {fromSeq,
  onRow, onProgress})` → `{deliveries, receivedUt, readable, rows, fromSeq, checked}` looks back about
  7 days by default (`recentStart()`: 300 epochs of ~34 min); `{fromSeq: 0}` is "Look at everything".
  Receipts' `text` is plain text; never linkify it.
- **Sending to a Tari address (changed):** `wallet.deliver(identity, {address, kind, blob, signal})` →
  `{mode: 'direct', tx_id, …}` or `{mode: 'relay', job_id, not_before}`. It needs a session
  (`ensureSession` first). Pick the copy from `mode` per send (11 §8 claim registry), not from
  `/config`. For a relay send, follow it with `courier.waitJob(job_id)`.
- **Direct-mode wallet:** `balance(identity)`, `requestGrant(identity)` (call it in the background right
  after the locker's first session when `/config` says `send_mode: "direct"` and `features.sponsor`;
  ignore `rate_limited`), `send(identity, {to, amountUt, memo, signal})`, `payInvoice(identity,
  invoice)`, `demoPayInvoice(invoiceId)` ("pay with our demo wallet"; PoW or judge pass).
  `WalletError.code` ∈ `insufficient|input_gone|rejected|timeout`. A send that times out holds its
  inputs back for 3 minutes, then the next send asks the indexer about them again.
- **Addresses:** `classifyAddressInput(str)` (sync) + `addressErrorCode(cls)` →
  `null|mainnet_address|l1_address|bad_address`; `safetyCodeForAddress(address)`.
- **"Check directly with the Tari indexer" (changed):** `ootle.checkTxWithIndexer(txId)` for a
  transaction (its committed receipt: `transactions/{id}/result` is gone a few hours after commit) and
  `ootle.checkWithIndexer('substates/<utxo_… or component_…>')` → `{origin, status, body}`. The only
  cross-origin requests the app makes.
- **API (changed):** `api.js` holds the anonymous endpoints, `request`, `ApiError {status, code,
  message, retryAfter, details}` and `config()` (cached per page); `api-locker.js` holds the locker,
  drop, courier, chain, payment and P1 endpoints. A network failure or timeout is `code: 'network'`,
  `status: 0` (not in §6.4; map it to "Retry").
- **P1:** kept files `sealItem(…, {keepFor: identity})`, `api-locker.listMyItems`, `openKept(identity,
  row)`, `keepWrap(identity, opened)` + `api-locker.claimItem(itemId, wrap, headers)`; receipts
  `seallog.js` (`storedLeaf`, `exitLeaf`, `verifyInclusion`, `checkpointsFromComponent`),
  `api-locker.sealProof`, `api.exitReceipt`. The tree size used with a proof must be the on-chain
  checkpoint's `leaf_count`.
- **i18n:** flat JSON (`{"viewer.ready.title": "…"}`), plural values `{one, other, …}` chosen by
  `params.count`; `loadLanguage()`, `t(key, params)`, `formatBytes` ("2.4 MB"), `formatRelative`.
- **DOM:** `h(tag, props, ...children)` refuses `innerHTML`/`srcdoc`/`style`/string handlers and
  `javascript:` URLs; dynamic CSS only via `setVar(el, '--x', v)`.

## 3. Requests

**Server builder**
1. Let a valid judge pass lift the per-/64 and per-/48 limits of `POST /sponsor` (and of demo-pay), so
   two judges on one network both get a grant (review M1). The per-locker limit can stay.
2. The indexers' CDN rejects Python's default `User-Agent: Python-urllib/3.x` with **HTTP 403,
   Cloudflare error 1010**. Send your own User-Agent from the proxy and the mirror.
3. Share ids must be canonical base64url of exactly 16 bytes: the courier carries the id as 16 raw
   bytes (`share_id(16) ‖ s ‖ flags ‖ ref`), and decoding is strict.
4. `/config.amount_proof` is a string (`"sidecar"|"chromium"|"wallet"`, 12-integration §3), not the
   boolean of the §6.3 example. `memo_origins` must list both hosts. `text_max_chars` must stay equal
   to this library's `TEXT_MAX_CHARS` (`contract.test.js` checks it).
5. Sidecar protocol additions: `openDelivery` also returns `access_token` (b64u, for opening the
   canary link once in the health check) and accepts optional `origins`; new P1 command `reveal {n}`
   → `{n, sealed_at, fk}`; `scan` returns `memo` as the decoded object (pay-ref extraction stays yours).
   `reveal` answers `not_found` for a canary sealed before the sidecar last restarted (keys live in its
   memory only): publish that hour as "missed (the verifier restarted)" rather than skipping it (review L8).
6. P1 "Keep": the viewer never learns an item id, so `POST /items/{id}/claim` can't be called from it.
   Either return `item_id` in `/s/{id}/open` (it's harmless to someone who can already open the file)
   or accept the claim at `/s/{id}/claim`. `/me/items/{id}/open` should answer with the same transfer
   fields as `/s/{id}/open` (`ticket`, `ticket_expires_at`, `inline_ct`).
7. Cross-checks done: your `addr.json` (classify, valid, invalid) and `pow.json` (layout, digests,
   zero bits) agree with this library in Node 20 and Chromium. `web/app/tests/vectors/format-v1.json`
   and `wrap-v2.json` are ready for your side. `run_all.py` step 9 starts your `bin/mutis-api --dev`
   from the same checkout and inserts one row into `judge_passes` (`code_hash, uses_left, created_at`).

**Deploy builder**
1. Sidecar release layout and command: `sidecar/README.md` (copy `lib/`, the two `package.json`
   markers, the shim and `vendor/ootle-wasm-0.45.0/`).
2. Build lint: allow the SVG namespace identifier `http://www.w3.org/2000/svg` in `lib/dom.js` (it is
   not fetched) and the two indexer origins in `lib/ootle.js`.
3. Serve `.wasm` as `application/wasm`. `lib/package.json`/`vendor/package.json` are harmless in
   `dist/` (or exclude them).
4. Compress `/api/v1/chain/utxos` (Caddy `encode zstd gzip` on the API route): a 1,000-row page of
   genuine outputs is 594 KB of JSON and 279 KB gzipped (47%).
5. `tools/build.py` `NEVER_SERVED` skips `NOTES*` and `ACCEPTANCE*` but not `REVIEW*`: add
   `REVIEW[^/]*`, or `web/app/REVIEW-devil.md` is served at `/app/REVIEW-devil.md`.
6. `tests/headless.py` is a ready base for `tests/e2e` (CDP over the pipe, CSP enforcement, device
   emulation, throttling, screenshots). E-J should run its two browser contexts from one /64 and
   record the cold-start time of the first direct send (§1 above).

**Site builder**
1. The `/judges` "Judge pass (optional)" field: store the code for the tab with
   `import { saveJudgePass } from '/app/lib/store.js'` (or `sessionStorage.setItem('mutis.judge', code)`,
   trimmed, lower case, `judge-` + 24 characters); the app pages pick it up from there.
2. `/canary` reveals: an hour whose `reveal` the sidecar can't answer (it restarted) is shown as
   "missed (the verifier restarted)", never skipped (review L8).

**Integrator**
1. **`send_mode`:** keep `"relay"` in production config until E-J passes as above; then `"direct"`.
2. **Threat model (review M9):** §14.1's "Phishing through our relay … the server builds every memo
   from its own origin" holds for relay sends only. In direct mode the browser builds the memo and pays
   with tTARI from our sponsor grant, so anyone who writes their own client can put any memo text,
   including look-alike `/t#` links, on chain to any address. The bound is the daily sponsor budget
   (one grant per locker and per /64 a day), and the inbox shows any memo that isn't exactly a `/t`
   link on an allowed origin as plain text, never as a link. Please say so in §14.1 and `/security`.
3. **Copy for the active-document notice (11-brand §10.6, review M4):** a softer variant of the
   `opened-risky` card for `active` files, e.g. **This is a web page or document that can run code
   ({ext}).** "Opened from your computer it runs outside this site's protections. Save it only if you
   expected exactly this file." · **`Save file`** · `Don't save` (one step, not two).
4. **Copy for `needs_wasm` on `/d/*` (review M8):** see §2 "No WebAssembly".
5. **SealLog cadence:** spec §11.3 says a checkpoint every 6 hours, brand C7/§8.3 `{checkpoint_min}` =
   15 minutes. `seallog.js` no longer states a cadence; please reconcile before any copy prints one.
6. **Key file name and format (P-15):** I kept the spec's text format and name
   (`mutis-key-<6 hex>.txt`); the passphrase-locked variant is the same text with a `Locked key:` line
   instead of `Key:`. Brand §10.4's `mutis-recovery-{id4}.json` would change only the name; say if you
   want it.
7. **Common passwords:** 391 hand-written entries plus pattern rules (repeats, keyboard rows,
   sequences, years, undone substitutions, trailing digits) rather than the spec's 1,000-entry list.
   Only the minimum length is a rule; the rest drives the hint.
8. bech32m decoding has no 90-character limit (Ootle addresses are ~140 characters); BIP-350's other
   vectors pass. L1 and Tari Universe shapes still need the owner's samples (§0.6); today: base58 of
   60-100 characters, or ≥ 20 emoji from the alphabet.
9. Gate evidence for `docs/evidence/`: `web/app/tests/evidence/`.
