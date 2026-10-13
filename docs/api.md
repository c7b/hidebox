<!-- SPDX-License-Identifier: MIT -->
# bye HTTP API (v1)

The API the app and the site use, served under `/api/v1` by `mutis-api` behind Caddy. The routes are
`server/mutis/router.py`; each handler is in `server/mutis/handlers/`; `server/tests/test_contract.py`
holds the shapes the app relies on, and `web/app/lib/api.js` and `api-locker.js` are the client.

## Conventions

- JSON in and out (`application/json`), except chunk uploads, blob downloads, `/canary/raw` and
  `/s/{id}/stored` (`application/octet-stream`). JSON bodies are at most 64 KiB.
- Binary fields are base64url without padding. Chain ids, commitments and nonces are lowercase hex as
  the indexers print them. Amounts are decimal strings in µT (`"500000"` = 0.5 tTARI).
- Times are unix seconds (UTC). Fields named `*_hour` are unix seconds floored to the hour, not hour
  counts: `exit_hour` in `GET /s/{id}/exit` is one of them.
- Credentials travel in headers, never in a query string:
  - `Authorization: Bearer <token>`: a locker session (30 days at most, 7 days idle).
  - `X-Mutis-Manage`: the manage token of an item uploaded without a locker, or of a drop.
  - `X-Mutis-Access`: a link's access token, derived in the browser from the secret after the `#`;
    the server stores only its SHA-256. `X-Mutis-Link`: the link proof of a link + password share.
  - `X-Mutis-Judge`: a judge pass (it stands in for proofs of work and draws on a reserved budget).
- A state-changing request with an `Origin` header must carry the deployment's own origin
  (403 `bad_origin`). No CORS headers are sent.
- Proof of work: `POST /pow {"purpose"}` returns a challenge and a difficulty; requests that need one
  carry `"pow": {"challenge", "nonce"}`. A missing or stale one answers 428 `pow_required`. A challenge
  is good for 300 s, once, from the network it was issued to (the network key is part of its MAC), and
  only at a difficulty within two bits of what that network is asked for at the time it is spent:
  a 428 `pow_invalid` says to solve a fresh one, at the difficulty in `details`.
- Errors: `{"error": {"code": "<snake_case>", "message": "<English>", "retry_after": <s>, "details": {…}}}`
  (`retry_after` and `details` only when they apply). The app maps `code` to its copy; `message` is for
  logs and fallbacks. 429 `rate_limited` and `budget_exhausted` carry `Retry-After`.
- Rate limits key on a keyed hash of the client's network (IPv6 /64 or the IPv4 address, and /48 or
  /24), held in memory with a key that changes daily; a restart forgets them. At most 32 requests per
  network are in progress at once (128 per /48 or /24). The limits per route are in the handlers.

## Routes

| Route | Who | What |
|---|---|---|
| `GET /health` | anyone | `{"ok", "version", "time"}` |
| `GET /config` | anyone | origins, network, `send_mode`, `amount_proof`, limits, KDF bounds, pricing, `features`, courier and SealLog settings (`seal_log.checkpoint_interval_s`, `seal_log.component`), retention, the security drop. Copy variants follow it |
| `POST /pow` | anyone | a proof-of-work challenge for one purpose |
| `GET /stats` | anyone | free quota, minutes since the last upload, disk use, `uploads_frozen`, `chain_ok`, the latest SealLog tree size and epoch |
| `GET /stats/wall` | anyone | up to 24 recent items as `{size, exit}` classes (none until 8 exist), and the latest canary's age and size |
| `POST /uploads` | anyone (PoW) or a locker | reserve an upload: header, encrypted metadata, chunk count, padded size, expiry, optional `drop_id` → `upload_id`, `item_id`, `manage_token` |
| `PUT /uploads/{id}/chunks/{n}` | the uploader | one chunk's ciphertext (`X-Mutis-Chunk-SHA256`); idempotent |
| `POST /uploads/{id}/complete` | the uploader | → `item_id`, `ct_hash`, `size_stored` |
| `DELETE /uploads/{id}` | the uploader | abandon it and release the reservation |
| `POST /items/{id}/shares` | owner or manage token | a link: mode (`link`, `link_password`, `password`), wrapped key, access verifier, link verifier, KDF, views, expiry |
| `GET /s/{id}` | anyone with the path | state, mode, whether it needs a password (410 `gone` with the reason and the day once it has left; never the open count) |
| `POST /s/{id}/peek` | `X-Mutis-Access` | what the server knows about the link, without using a view (the "What we know" panel) |
| `POST /s/{id}/open` | `X-Mutis-Access` | uses a view; returns the wrapped key, the header and metadata, and the ciphertext inline (small files) or a short-lived download ticket |
| `GET /blobs/{ticket}`, `POST /blobs/{ticket}/done` | the ticket | the ciphertext (Range supported); "done" ends the ticket, and a file whose last link has left loses its ciphertext at once |
| `PATCH /s/{id}`, `GET /s/{id}/manage`, `DELETE /s/{id}` | owner or manage token | tighten views or expiry, read the link's state, revoke |
| `GET /s/{id}/exit` | anyone with the path | the exit receipt: reason, `item_id`, `exit_hour`, leaf hash, and an inclusion proof against the latest committed checkpoint, or `{"pending": true, "next_checkpoint_eta"}` |
| `GET /s/{id}/stored` | `X-Mutis-Access` | the link's file exactly as the disk holds it, without using a view (the key is released only by `/open`) |
| `DELETE /items/{id}` | owner or manage token | delete the file and every link to it |
| `POST /items/{id}/adopt` | a locker and the item's manage token | move a file locked without a locker into the locker |
| `POST /auth/register` | anyone (PoW) | a new locker: id and login-key verifier → session |
| `POST /auth/session`, `DELETE /auth/session` | the locker | sign in with the login key; sign out |
| `GET /me`, `DELETE /me` | the locker | quota, packs, probation; delete the locker and its files |
| `GET /me/items`, `POST /me/items/{id}/open` | the locker | the locker's files and their links, newest first; read one without using a link's views |
| `PUT /me/bundle`, `GET /me/bundle` | the locker | an encrypted key bundle (used only when `gates.key_bundle` is on) |
| `POST /drops` | anyone (PoW) | a dead drop: the locker's Tari address, a tag, a label, a manage verifier → `drop_id`, URL |
| `GET /drops/{id}`, `PATCH /drops/{id}`, `DELETE /drops/{id}` | anyone; manage token | the drop page's data; rename or close |
| `POST /courier` | drop submitters (PoW), lockers | queue a delivery: a 125-byte sealed blob to a drop or to a Tari address (relay); the server writes the memo |
| `GET /jobs/{id}` | whoever holds the job id | `queued`, `sending`, `done` (with `tx_id`) or `failed`; never an address |
| `GET /chain/utxos?after=&limit=` | anyone | the server's mirror of every TARI UTXO since `mirror_start_epoch`, for scanning in the browser |
| `GET /chain/seq?epoch=` | anyone | the mirror position right before an epoch, to pass as `after` |
| `GET /chain/tx/{id}/view` | anyone | "What the chain sees" for one transaction: hidden amounts, one-time owners, encrypted memos, the fee. An id the indexers don't know (up to four upstream calls) draws on a budget of ten a minute per network |
| `GET /chain/ix/{path}` | anyone | an allowlisted pass-through to the Tari indexers (substates with proofs, results, the epoch) |
| `POST /chain/ix/transactions` | a locker session | submits a transaction in direct mode: only `{"transaction": <base64 BOR envelope>}` shaped like the app's own send (one stealth transfer paying its fee of at most `courier.max_fee_ut` from a bucket, one output plus change, up to four inputs, no other instruction), 12 KB at most; anything else is `422 invalid`. The proxy is not a relay for other transactions |
| `POST /invoices`, `GET /invoices/{id}` | the locker | a pack invoice: a receiver address with the invoice's reference, the amount; its status (`pending`, `seen`, `credited`, …) |
| `POST /invoices/{id}/demo-pay` | the locker (PoW) | our demo wallet pays the invoice (play money, real stealth transaction) |
| `POST /sponsor` | the locker (PoW) | direct mode: a small grant to the locker's wallet address, once a day |
| `GET /canary`, `GET /canary/raw[?n=]` | anyone | the latest hourly canary (header, encrypted metadata, ciphertext hash, delivery transaction) and its bytes; keys published a day later, or `missed: true` for an hour whose key the verifier lost |
| `POST /abuse` | anyone (PoW) | report a link or a drop (the fragment is stripped by the client) |
| `GET /seallog/checkpoints?after=` | anyone | committed checkpoints, oldest first (`next` is an opaque cursor) |
| `GET /seallog/proof/{item_id}` | anyone | the stored-file receipt for an item, as for `/s/{id}/exit` |

Checkpoint objects are `{"index", "component", "tree_size", "root", "epoch", "tx_id", "created_at"}`;
`index` is the log's own checkpoint number from the chain (null if the worker couldn't read it), and
`/verify` only counts a proof whose `component` is the one `/config` names.
