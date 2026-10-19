<!-- SPDX-License-Identifier: MIT -->
# hidebox HTTP API (v1)

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
  - `X-Mutis-Claim`: a pay-to-open claim token (32 bytes), drawn by the buyer's browser; the server
    stores only its SHA-256. A paid link's fragment is kind `5`: `/p/<share_id>#5<b64u(sA)>`.
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
| `GET /config` | anyone | origins, network, `send_mode`, `amount_proof`, limits (with `links_per_item`), KDF bounds, pricing (with `one_per_drive` and `renew_days`), `features` (`folders` and `pay_to_open` are off until the drive's routes ship), courier and SealLog settings (`seal_log.checkpoint_interval_s`, `seal_log.component`), retention (with `trash_days`), the security drop, and the drive's numbers: `folders` (`max_depth`, `max_children`, `max_tree`, `max_items`, `max_upload_files`, `zip_max_bytes`, `zip_max_bytes_phone`), `items.max_delete_after_days`, `send` (`views`, `expiry_s` of a link sent by Tari™), `pay_to_open` (`prices_ut`, `fee_ut`, `buyer_views`, `buyer_window_s`, `claim_ttl_s`, `late_grace_s`, `demo_max_ut`, `watch_address`, `max_open_claims_per_share`). Copy variants follow it |
| `POST /pow` | anyone | a proof-of-work challenge for one purpose |
| `GET /stats` | anyone | free quota, minutes since the last upload, disk use, `uploads_frozen`, `chain_ok`, the latest SealLog tree size and epoch, `packs_sold_public` and `packs_cap_public` (the public slice of paid space, whole GiB) |
| `GET /stats/wall` | anyone | up to 24 recent items as `{size, exit}` classes (none until 8 exist), and the latest canary's age and size |
| `POST /uploads` | anyone (PoW) or a locker | reserve an upload: header, encrypted metadata, chunk count, padded size, expiry, optional `drop_id` → `upload_id`, `item_id`, `manage_token`. A drive without a pack: 429 `uploads_limited` past 2 GiB a UTC day per /64 or IPv4 address, 6 GiB per /48 or /24 (with a live judge pass in `X-Mutis-Judge`, 8 GiB per /64 and per pass) |
| `PUT /uploads/{id}/chunks/{n}` | the uploader | one chunk's ciphertext (`X-Mutis-Chunk-SHA256`); idempotent |
| `POST /uploads/{id}/complete` | the uploader | → `item_id`, `ct_hash`, `size_stored` |
| `DELETE /uploads/{id}` | the uploader | abandon it and release the reservation |
| `POST /items/{id}/shares` | owner or manage token | a link: mode (`link`, `link_password`, `password`), wrapped key, access verifier, link verifier, KDF, views, expiry |
| `GET /s/{id}` | anyone with the path | state, mode, whether it needs a password (410 `gone` with the reason and the day once it has left; never the open count) |
| `POST /s/{id}/peek` | `X-Mutis-Access` | what the server knows about the link, without using a view (the "What we know" panel) |
| `POST /s/{id}/open` | `X-Mutis-Access` | uses a view; returns the wrapped key, the header and metadata, and the ciphertext inline (small files) or a short-lived download ticket |
| `GET /blobs/{ticket}`, `POST /blobs/{ticket}/done` | the ticket | the ciphertext (Range supported); "done" ends the ticket, and a file whose last link has left loses its ciphertext at once |
| `PATCH /s/{id}`, `GET /s/{id}/manage`, `DELETE /s/{id}` | owner or manage token | tighten views or expiry, read the link's state, revoke |
| `GET /s/{id}/exit` | anyone with the path | the exit receipt: reason, `item_id`, and `receipt`: `exit` (`exit_hour`, leaf hash, and an inclusion proof against the latest committed checkpoint, or `{"pending": true, "next_checkpoint_eta"}`), `pending` (the file is on its way out), or `none` (the link ended on a file its owner keeps: no leaf, `proof` null; C42) |
| `GET /s/{id}/stored` | `X-Mutis-Access` | the link's file exactly as the disk holds it, without using a view (the key is released only by `/open`) |
| `DELETE /items/{id}` | owner or manage token | delete the file and every link to it |
| `POST /items/{id}/adopt` | a locker and the item's manage token | move a file locked without a locker into the locker |
| `POST /auth/register` | anyone (PoW) | a new locker: id and login-key verifier → session. 429 `drives_limited` past 5 new drives a UTC day per /64 or IPv4 address, 20 per /48 or /24 (a judge pass skips both) |
| `POST /auth/session`, `DELETE /auth/session` | the locker | sign in with the login key; sign out |
| `GET /me`, `DELETE /me` | the locker | quota, packs (`pack`: `id`, `bytes`, `until`, `renew_from`, or null), probation; delete the locker and its files |
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
| `POST /chain/ix/transactions` | a locker session | submits a transaction in direct mode: only `{"transaction": <base64 BOR envelope>}` shaped like the app's own send (one stealth transfer paying its fee of at most `courier.max_fee_ut` from a bucket, one output plus change, up to four inputs, no other instruction), 12 KB at most; anything else is `422 invalid` |
| `POST /invoices`, `GET /invoices/{id}` | the locker (a judge pass in `X-Mutis-Judge` buys from the judges' slice) | a pack invoice: a receiver address with the invoice's reference, the amount; its status (`pending`, `seen`, `credited`, …). An open invoice for the same pack comes back with 200; one for the other pack, unpaid, is closed and replaced. 409 `pack_active` (`details`: `pack`, `bytes`, `until`, `renew_from`) while the drive holds a pack, except the same pack in its last `pricing.renew_days` days (days stack, bytes don't); 409 `sold_out` (the slice is full, open invoices included); 429 `packs_limited` with `Retry-After` until 00:00 UTC (1 a day per /64 or IPv4 address; with a judge pass 2 per network and 2 per pass; 3 a day for the deployment, 10 with judge passes); 503 `feature_disabled` `{feature: packs}` (the kill switch) |
| `POST /invoices/{id}/demo-pay` | the locker (PoW) | our demo wallet pays the invoice (play money, real stealth transaction); 503 `feature_disabled` (the kill switch) |
| `POST /sponsor` | the locker (PoW) | direct mode: a small grant to the locker's wallet address, once a day |
| `GET /canary`, `GET /canary/raw[?n=]` | anyone | the latest hourly canary (header, encrypted metadata, ciphertext hash, delivery transaction) and its bytes; keys published a day later, or `missed: true` for an hour whose key the verifier lost and its delivery on the Ootle couldn't give back |
| `POST /abuse` | anyone (PoW) | report a link or a drop (the fragment is stripped by the client) |
| `GET /seallog/checkpoints?after=` | anyone | committed checkpoints, oldest first (`next` is an opaque cursor) |
| `GET /seallog/proof/{item_id}` | anyone | the stored-file receipt for an item, as for `/s/{id}/exit` |

<!-- lane S: the drive (16-drive-design §15 steps 4 and 6), behind features.folders -->
| Route | Who | What |
|---|---|---|
| `POST /folders` | a drive session | a folder: `{parent_id (null for the root), header, meta_ct, owner_wrap, parent_wrap?}` → 201 `{item_id}`. The header is format v1 with flags `0x0001` and no chunks (uploads refuse that flag). 403 `forbidden` (the parent isn't this drive's folder), 409 `too_deep` (more than `folders.max_depth` folders), `folder_full` (`folders.max_children`), `trashed`, 413 `too_many` (`folders.max_items` in the drive). 600 an hour per drive |
| `PATCH /items/{id}` | the drive | one change per request (several fields allowed, `trashed` alone): **move** `{parent_id, parent_wrap}` (`parent_id: null` for the root; 409 `cycle`, `too_deep`, `folder_full`), **rename** `{meta_ct}` (new metadata under the same key; the ciphertext and its SealLog leaf don't change), **Delete it after** `{expires_at}` on a kept file (at most `items.max_delete_after_days` ahead, rounded up to the hour, or `null` to clear; the file stays kept and leaves at that time with its exit receipt), **Trash** `{trashed: true}` or `{trashed: false}` (into the Trash with everything below it: every link of those items ends now; out of it with what went in with it, to the root if its folder is gone or still in the Trash; links stay ended). 409 `trashed` for any other change while in the Trash. → the item as `/me/items` lists it |
| `DELETE /items/{id}` (folder) | the drive | deletes the folder and everything below it in one transaction; each file leaves with its exit receipt |
| `POST /uploads` (into a folder) | the drive | `parent_id` and `parent_wrap` (60 bytes: the file key wrapped under the folder's) on a kept file; 403, 409 `trashed`, `folder_full`, 413 `too_many`. With folders on, kept uploads are limited to 600 an hour per drive (100 on its first day) and 1,200 per network |
| `GET /me/items?view=&parent=` | the drive | `view=all` (default): everything outside the Trash, flat, as before; `parent=root` or `parent=<folder id>`: one folder's contents (inside a trashed folder, what it took with it); `view=trash`: what was put in the Trash, latest first; `view=gone`: what left in the last `tombstone_days` days (`item_id`, `kind`, `created_hour`, `exit_hour`, `reason`: `deleted`, `expired`, `trash`, `link_ended` or `removed`, `exit_receipt`, and `header`, `meta_ct`, `owner_wrap` so the browser can read the name). Items carry `kind`, `parent_id`, `parent_wrap`, `trashed_at` |
| `GET /me` | the drive | adds `quota.trash_bytes` (the Trash still counts in `used_bytes` until it empties, after `retention.trash_days`), and `files`, `folders` (outside the Trash) |
| `GET /seallog/proof/{item_id}?kind=exit` | anyone | the exit receipt of a file that left, by its id (for files that left without a link: Delete it after, the Trash, a deletion) |
| `POST /items/{id}/shares` (folder) | the drive | a folder link, in any mode: the folder's key wrapped under the link's secret; it shares everything the folder holds when it is opened |
| `POST /items/{id}/shares` + `then_delete: true` | the drive | "Delete it from my drive after": on a kept file and a link that ends by itself (an expiry is required); the file becomes `ephemeral` with `expires_at` no later than the link's, so it leaves with its last link and gets its exit receipt. The response adds `item_expires_at`. 422 `then_delete` on a folder, without an expiry, or on a file that isn't the drive's own kept file |
| `POST /s/{id}/open` (folder) | `X-Mutis-Access` | one view is one visit: `kind: "folder"`, the folder's `wrapped_key`, `header`, `meta_ct`, and `tree`: `[{id, kind, parent_id, header, meta_ct, parent_wrap, size_stored, chunk_count}]` for every ready descendant outside the Trash, breadth first (413 `too_many` beyond `folders.max_tree`, before a view is used), and `folder_ticket` with `ticket_expires_at` (`retention.ticket_s`; at most 3 times the tree's stored bytes). Nothing inline. A file's open says `kind: "file"` |
| `GET /blobs/{ticket}?item={id}` | the folder ticket | the ciphertext of a file that is, when asked for, a ready descendant of the ticket's folder outside the Trash (403 `not_in_folder` otherwise: moved out, trashed or deleted mid-visit); Range supported; the byte cap counts across files, and each file's daily egress is counted as it is served (429 `rate_limited` past it). A file's own ticket refuses any other `item` |
| `POST /s/{id}/peek`, `GET /s/{id}/manage` | as before | `item.kind`, and `item.child_count` for a folder. `GET /s/{id}` (the path alone) doesn't say whether a link opens a file or a folder. `GET /s/{id}/stored` on a folder: 409 `conflict` |
| `GET /s/{id}/manage`, `GET /me/items` | the owner | each link gains `opens`: `[[hour, n], …]`, how many times it opened in each UTC hour (all of them in `manage`, the last 168 hours in `/me/items`). Never who opened it or from where; the counts go with the link's tombstone |

**Folders.** A folder is an item without ciphertext (`kind: "folder"`, size 0, no SealLog leaf) with its
own key and encrypted name. Each item inside one carries `parent_id` and `parent_wrap`, its own key wrapped
under the folder's, and keeps its `owner_wrap`, so the drive lists any folder without walking the tree,
and one folder key opens everything below it and nothing above. Moves and renames are one `PATCH`, made
in the browser. The server learns which items share a folder, how deep and how many; never a name, a type
or a real size. Folders cost no space; files in the Trash do until it empties. A folder link opens the
subtree as one visit: a Once folder link gives one visit of `retention.ticket_s`, then ends; the files
stay in the drive.
<!-- /lane S -->

<!-- lane S: pay to open (16-drive-design §4, §15 step 14), behind features.pay_to_open -->
| Route | Who | What |
|---|---|---|
| `PUT /me/sales` | a drive session | `{address, view_sealed}` → 204: the drive's sales address (testnet, no payment reference) and its view key sealed (kind 3, flag `0x08`, `ref16` = SHA-256(`"mutis-watch-v1"` ‖ address)[0:16]) to `pay_to_open.watch_address`. Replaces the previous one (checked again from the start). 422 `invalid`, `bad_address`; 10 a day per drive |
| `GET /me/sales` | a drive session | `{seller: {address, state} or null, to_check: [{claim_id, share_id, paid_at, amount_ut, received_ut, utxo_ids}], paid: [{utxo_id, share_id, value_ut, seen_at, demo, checked, owner_ok, tx_id}]}` (`paid`: the 50 newest payments to this drive's paid links, for Received → Payments; `tx_id` only for test money): `state` is `pending` (not yet opened by the payment checker), `ok` or `bad_key`; `to_check` lists paid claims waiting for this drive's ownership check, with the outputs that paid them and aren't answered yet (at most 100, oldest first) |
| `POST /me/sales/claims/{claim_id}/confirm` | the link's owner | `{utxo_id, spendable: true | false}` → 200 `{claim_id, status, owner_check}`: the drive compared one output's one-time key with the one its sales owner key derives. Once every output that counted for the claim is `spendable`, `owner_check` is `ok` and the buyer's next poll releases it; one `false` voids the claim (`owner_check: "bad"`). 404 not this drive's; 409 `conflict` with `details.status` unless the claim is `paid`, waiting, not test money, and the output counted for it (an open status means: ask again later) |
| `POST /items/{id}/shares` + `mode: "pay"` | the drive | `{mode: "pay", wrapped_key, access_verifier, server_half (32 bytes), price_ut (one of pay_to_open.prices_ut), teaser_ct? (at most 2,076 bytes)}` on the drive's own kept file or folder: stored as a plain link without a rule of its own, plus its price and our half of its key. The response's `path` is `/p/{id}`. 409 `seller_not_registered` (no `PUT /me/sales` yet), `conflict` (one paid link per item at a time), 422 (`price_ut`, a rule, `then_delete`, a password, or not the drive's kept item), 503 `feature_disabled` |
| `PATCH /s/{id}` (paid) | the owner | `{paused: true | false}`: Stop selling / Sell again; no new claims while paused, released claims keep their opens. Rules can't be changed on a paid link (422); `paused` on any other link is 422 |
| `GET /s/{id}/manage`, `GET /me/items` (paid) | the owner | each paid link gains `paid: {price_ut, paused, seller_state, counts: {pending, seen, underpaid, paid, released, expired, void}, earned_ut}`; `manage` adds `recent`: the last 50 claims as `{ref4, status, received_ut, paid_hour, released_hour, demo, owner_check}`. Never who paid |
| `GET /s/{id}` (paid) | anyone | adds `paid: true` (the viewer moves to `/p/{id}`) |
| `GET /p/{id}` | anyone | `{state: "selling" | "paused", price_ut, fee_ut, buyer_views, buyer_window_s, kind, size_stored, child_count, teaser_ct, seller: {ready}, testnet: true}`; never the seller's address. 404, 410 `gone` as `/s/{id}`. 120 a minute per network |
| `POST /p/{id}/claims` | anyone (PoW `claim`) | `{claim_verifier: b64u(SHA-256(t)), pow}` → 201 `{claim_id, address, amount_ut, expires_at, status: "pending"}`: `address` is the owner's sales address with the claim id as its payment reference; pay within `pay_to_open.claim_ttl_s`. 409 `not_for_sale` (paused), `seller_not_ready`, `busy` (`max_open_claims_per_share` waiting on this link), 503 `busy` (500 waiting in all). 10 an hour per network, 30 per /48 |
| `GET /p/{id}/claims/{claim_id}` | `X-Mutis-Claim` | `{claim_id, status, address, amount_ut, received_ut, expires_at, demo, owner_check, payments: [{value_ut, seen_at, counted, checks: {amount_proven, committed_on_chain}}]}`, plus `tx_id` once our demo wallet has sent test money for it; once released, `views_left`, `open_until` and, while opens and time are left, `server_half`. The first poll of a claim that passes the release gate releases it. 403 `bad_claim`, 404. 60 a minute per network |
| `POST /p/{id}/claims/{claim_id}/demo-pay` | `X-Mutis-Claim` (PoW `demo_pay` or a judge pass) | `{pow}` → 202 `{job_id}`: our demo wallet pays what the claim still misses (at most `pay_to_open.demo_max_ut`), with test money, to the claim's address. 409 `conflict` (paid, closed, or one already on its way), `seller_not_ready`, 422 (the price is over `demo_max_ut`), 429 `rate_limited` / `budget_exhausted`, 503 `feature_disabled`. 3 a day per network, 6 per /48 (a judge pass lifts both); the `demo_pay` budget |
| `POST /s/{id}/open`, `/peek`, `GET /s/{id}/stored` (paid) | `X-Mutis-Access` + `X-Mutis-Claim` | the claim must be this link's, released, with opens left and inside its window; each open spends one. 402 `payment_required` (no claim, or not paid yet), 403 `bad_claim`, 410 `claim_used` (`details.reason`: `no_opens_left` or `window_over`); checked before the access token |

**Pay to open.** A paid link splits its key: `sA` after the `#`, `sB` (`server_half`) with us; the link's
secret is HKDF(`sA` ‖ `sB`), so one half without the other opens nothing. A buyer's browser draws a claim token `t`,
makes a claim and pays the claim's address; the memo carries the claim id. Our chain worker opens the
seller's sealed view key, scans the mirror from the claim's position, proves the amount with the official
`unblindOutput`, and counts it once an indexer commits it (`pending` → `seen` → `paid`; short payments
are `underpaid` at expiry and top-ups count for `late_grace_s` more; anything after `paid` is `extra`,
kept by the owner). **The release gate:** a view key proves amount and memo, not who can spend the
output, so only test money our demo wallet built for the whole price releases at `paid`; any other
payment waits (`owner_check: "pending"`) until the owner's drive has run its check and confirmed. Released, the
claim gives `buyer_views` opens within `buyer_window_s`. Ending the link (revoke, delete, removal) erases
`server_half`, voids claims not yet released and leaves released ones without opens. Payments are
final.
<!-- /lane S -->

Checkpoint objects are `{"index", "component", "tree_size", "root", "epoch", "tx_id", "created_at"}`;
`index` is the log's own checkpoint number from the chain (null if the worker couldn't read it), and
`/verify` only counts a proof whose `component` is the one `/config` names.
