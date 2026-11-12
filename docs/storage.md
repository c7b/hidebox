<!-- SPDX-License-Identifier: MIT -->
# Storage: our disk, capped, and an S3-compatible store for later

**The mainnet beta keeps files on this server's disk** (`storage.backend = "local"`, the default and hidebox.app's), as
the testnet always has. It shares that disk with production, so it takes at most `limits.disk_cap_bytes` of it,
**20 GiB**, and never takes the disk below its reserve (`limits.reserve_min_bytes`, 10 GiB). Within that the free
share, the packs and the freezes work as on any disk: the cap is the pool's size ([pricing.md](pricing.md)). Nothing
is rented and nothing is paid for.

The code can also keep ciphertext in rented object storage, through the S3 API that most providers offer, so a drive
could one day hold more than one server's disk. That is a setting (`storage.backend = "s3"`), off, and kept for later;
the rest of this page describes it.

Code: `server/mutis/s3.py` (the client, standard library only), `server/mutis/storage.py` (`TieredBlobs`),
`server/mutis/fake_s3.py` (a local stand-in for tests and `mutis-api --dev`). Tests: `server/tests/test_s3.py`,
`server/tests/test_storage_remote.py`.

## How it works

1. **Uploads land on our disk, as before.** Each chunk is written at its offset, the finished blob is synced and
   renamed. A slow or unreachable store never slows an upload. While a blob is local, reads come from our disk.
2. **The offloader copies it to the store.** A background thread of `mutis-api` copies each finished blob over
   `keep_local_max_bytes` (256 KiB by default) to the bucket, under `<prefix><item id>`: one signed PUT up to 64 MiB,
   a multipart upload above. Then it writes a marker beside the old path (`<id>.remote`, the blob's size) and deletes
   the local copy. Smaller blobs stay on our disk: they are read whole every time their link opens.
3. **Reads.** The API streams a range of the object from the store to the browser, 64 KiB at a time, through our
   server. The browser never talks to the provider, so the provider never sees a visitor's address. If the store
   can't answer, the download gets `503 store_unavailable` before anything is sent, and the ticket isn't charged.
4. **Deletes.** Whoever ends an item (the API, the cleanup pass, a takedown) queues the deletion (`.delete/<id>`) in
   the same step that writes its exit receipt, without the network: the cleanup pass has none. The offloader deletes
   the object and retries until the store confirms it. A blob deleted before its copy is never uploaded; one deleted
   while it is being copied is deleted from the store right after.
5. **Where a blob is** lives on our disk beside it (the marker), never in the database, so a database copy says no
   more than before.
6. **Our disk can't fill.** A new upload that would leave less than `staging_free_min_bytes` free on our disk is
   refused with `503 uploads_frozen` until the offloader catches up. The cleanup pass writes the backlog to
   `meta.storage` every minute; the healthcheck adds `storage.offload_behind` to `/status.json` when a blob or a
   deletion has waited more than an hour.
7. **The pool is the space rented.** With the store, `limits.capacity_bytes` replaces the disk's size in the quota
   formulas (`quota.measure`): what we store is taken from it, the free share and the paid cap follow from it, and
   uploads freeze at its margins as they do at a disk's.

Every request is signed with AWS Signature Version 4 over the payload's SHA-256, so the provider can't take a
request for another body. It goes over HTTPS with the system's certificate checks. The client is about 300 lines of
Python's standard library: no SDK, no XML parser (the two values a multipart upload needs are matched as plain text).
The signature code is checked against AWS's published test vectors.

## What the provider sees

What our disk holds: ciphertext, encrypted in the browser, under a random item id, with its padded size and the times
it arrived and left. Never a file name, a key, a link, a drive or who uploaded it. It sees our server's address, not
our visitors'.

It can withhold or delete a blob. It can't read one, and it can't change one unseen: each chunk is authenticated in
the browser that opens it (AES-GCM, bound to the file's header), and the blob's hash is in SealLog. A provider that
keeps deleted objects keeps ciphertext, which is useless without the key, as a host's disk snapshots already can.
That is why the setup below turns old versions off.

## Which provider

Prices fetched on 2026-11-08 from each provider's pricing page. They change: check before renting.

| Provider | Storage, per TB-month | Egress | Requests | Minimum | Notes |
|---|---|---|---|---|---|
| **Backblaze B2** (recommended) | $6.95 | free up to 3× what's stored, then $0.01/GB | free for what we use | none; first 10 GB free | US and EU regions; keeps every version unless a lifecycle rule says otherwise |
| **Cloudflare R2** (alternative) | $15 | free | $4.50 per million writes, $0.36 per million reads, deletes free | none; first 10 GB free | no versioning, so a delete is final; region "auto" |
| Hetzner Object Storage | €6.49 a month includes 1 TB and 1 TB egress | €1/TB past that | free | €6.49 a month, even empty | EU only; may ask for an ID |
| Wasabi | $7.99 | free | free | 1 TB charged; each object billed for 90 days | |
| IDrive e2 | $6 | free up to 3× stored | free | 1 TB charged | |

Sources: backblaze.com/cloud-storage/pricing, developers.cloudflare.com/r2/pricing, hetzner.com/storage/object-storage,
wasabi.com/pricing, idrive.com/s3-storage-e2/pricing.

**Backblaze B2** is the cheapest pay-as-you-go store with no minimum: we pay for what is stored, so
`capacity_bytes` is a ceiling, not a rent. At 1 TiB stored it is about $7.60 a month. Downloads are free while they
stay under three times what is stored, and `items.egress_ok` already caps each file's daily downloads. **Cloudflare
R2** costs twice as much to store but never charges egress, and has no versions to turn off. It is the better choice
if downloads grow past B2's allowance. Both work with path-style addressing and signed payloads.

## Rented storage, later

Nothing below is set up for the beta: no account, no bucket, nothing paid. It is what turning the store on would take,
with Backblaze B2 as the example.

1. Create an account at backblaze.com (B2 Cloud Storage) and add a card. Pick the region when asked, nearest the server
   (EU Central if in doubt).
2. **Buckets → Create a Bucket.** Name: something unguessable, like `hidebox-main-` and 8 random letters. Files in
   bucket: **Private**. Default encryption: either; it adds nothing to ours. Object Lock: **off**.
3. On the new bucket, **Lifecycle Settings → Keep only the last version of the file.** Without it, a deleted file stays
   in the bucket as a hidden version.
4. **Application Keys → Add a New Application Key.** Name: `hidebox-mainnet`. Allow access to: **that bucket only**. Type
   of access: **Read and Write**. Leave the prefix and the duration empty. Copy the **keyID** and the
   **applicationKey**: B2 shows the key once.
5. On the bucket's page, copy the **Endpoint**, such as `s3.eu-central-003.backblazeb2.com`.

What would go where, on the server (`NAME` is the instance's name):

| Value | Where |
|---|---|
| `https://` + the endpoint | `/etc/mutis-NAME/mutis.toml`, `[storage] s3_endpoint` |
| The region: the endpoint's second part (`eu-central-003`) | `[storage] s3_region` |
| The bucket's name | `[storage] s3_bucket` |
| `"s3"` | `[storage] backend` |
| The space to sell from, in bytes, e.g. `1099511627776` (1 TiB) | `[limits] capacity_bytes` (and `disk_cap_bytes` back to 0) |
| The keyID, then the applicationKey, one per line | `/etc/mutis-NAME/s3.key` (below) |

The key file, written on the server by whoever holds the key, so the secret passes through nobody else:

```sh
sudo install -m 0640 -o root -g mutis-NAME /dev/null /etc/mutis-NAME/s3.key
sudo nano /etc/mutis-NAME/s3.key     # line 1: keyID, line 2: applicationKey
sudo mutis-admin-NAME check-config
```

Then the operator restarts the instance's API and cleanup (`deploy.sh --instance NAME`). Blobs that were already on
the disk stay there and stay readable; `mutis-admin-NAME offload-existing` queues them for the store too. The first
upload over 256 KiB should show up in the bucket within a few seconds.

**Cloudflare R2 instead:** R2 → Create bucket (location Automatic); R2 → Manage API tokens → Create Account API token,
Object Read & Write, that bucket only. Endpoint `https://<account id>.r2.cloudflarestorage.com`, region `auto`,
`s3_addressing = "path"`. R2 has no versioning, so step 3 doesn't apply.

**On every provider**, add a lifecycle rule that aborts incomplete multipart uploads after one day if the provider
offers one. The offloader aborts the ones it gives up on, but a restart in the middle of a copy can leave parts behind.

## Not yet

- One bucket per deployment, one store at a time; no moving blobs back to the disk (switching back to `local` would
  leave offloaded blobs unreadable: don't).
- A disk shared by two deployments: each measures the same free space, so their caps should add up to less than the
  disk above its reserve (production's pool still counts the whole disk; the beta's 20 GiB is what it may take).
- No re-check of the store's copy against the blob's hash after upload: the store answers the PUT only once the
  signed payload hash matches, and the browser checks every chunk it opens.
- Downloads come through our server, so its bandwidth is still the limit on how fast files leave.
