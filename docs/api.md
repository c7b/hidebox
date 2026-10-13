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
| `GET /config` | anyone | origins, network, `send_mode`, `amount_proof`, limits (with `links_per_item`), KDF bounds, pricing, `features` (`folders` and `pay_to_open` are off until the drive's routes ship), courier and SealLog settings (`seal_log.checkpoint_interval_s`, `seal_log.component`), retention (with `trash_days`), the security drop, and the drive's numbers: `folders` (`max_depth`, `max_children`, `max_tree`, `max_items`, `max_upload_files`, `zip_max_bytes`, `zip_max_bytes_phone`), `items.max_delete_after_days`, `send` (`views`, `expiry_s` of a link sent by Tari), `pay_to_open` (`prices_ut`, `fee_ut`, `buyer_views`, `buyer_window_s`, `claim_ttl_s`, `late_grace_s`, `demo_max_ut`, `watch_address`, `max_open_claims_per_share`). Copy variants follow it |
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
| `GET /blobs/{ticket}?item={id}` | the folder ticket | the ciphertext of a file that is, when asked for, a ready descendant of the ticket's folder outside the Trash (403 `not_in_folder` otherwise: moved out, trashed or deleted mid-visit); Range supported; the byte cap counts across files. A file's own ticket refuses any other `item` |
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

Checkpoint objects are `{"index", "component", "tree_size", "root", "epoch", "tx_id", "created_at"}`;
`index` is the log's own checkpoint number from the chain (null if the worker couldn't read it), and
`/verify` only counts a proof whose `component` is the one `/config` names.
