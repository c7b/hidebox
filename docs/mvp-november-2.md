<!-- SPDX-License-Identifier: MIT -->
# The November MVP, round two: storage, a bigger drive, currencies, a market

The owner's ask of 2026-11-09, for the mainnet beta at `mainnet.hidebox.app` (branch `mvp/november`, on
`launch/mainnet`): rent object storage so the drive can be more generous; pay for space in different currencies; a
marketplace for shoppers; and the approved MVP answers finished. Round one is [mvp-november.md](mvp-november.md).
Nothing here reaches hidebox.app, the October entry, beyond what that file already allows.

| # | The ask | What it becomes | Where | State |
|---|---|---|---|---|
| 1 | Rent storage ("subrentar S3") | an S3-compatible store behind the blob layer, provider set by config; for the beta, this server's disk capped at 20 GiB (the owner, 2026-11-10: no account, nothing paid) | [storage.md](storage.md) | built; the store tested against a local stand-in and left off |
| 2 | A more generous drive | 1 GiB free per drive on the mainnet (256 MiB to 5 GiB on the testnet), packs of +2 GiB for 50 TARI and +5 GiB for 100 TARI, set in config and sized to the 20 GiB | [pricing.md](pricing.md) | built |
| 3 | Pay in different currencies | TARI on the Ootle, checked end to end; XTM, Monero and Zcash designed, with what each needs | [currencies.md](currencies.md) | TARI built; pack revenue on our receiving key (the default; a watch-only address is in the code, empty); XTM vetted and not built (no signed release, deposits a view-only wallet can't tell from real ones); Monero and Zcash proposals |
| 4 | A shoppers' market | `/market`: every public shop's listings, searchable; buying without the shop's link by asking the seller's drive for its key half | [market.md](market.md) | built, with the UI flow: ask, the owner's open drive answers, pay, open |
| 5 | The approved answers | withdrawals, release without the seller, the shop key after the `#`, paid packs on the mainnet, the testnet line | [mvp-november.md](mvp-november.md) | built in round one; the line changed here |

## Decisions

- **Storage is tiered, not swapped.** Uploads still land on our disk (fast, unchanged), and a background thread copies
  each finished blob to the store, then drops the local copy. Deletion is queued without the network, so the cleanup
  pass (which has none) and a takedown work as before. Where a blob is lives on our disk beside it, not in the
  database. The S3 client is our own, from the standard library: signing is about 30 lines and is checked against
  AWS's published vectors; an SDK would be the largest dependency in the project.
- **No rented storage for the beta** (the owner, 2026-11-10: nothing waits on him, nothing is paid for). Files stay on
  this server's disk, at most 20 GiB of it (`limits.disk_cap_bytes`). If a store is ever rented, Backblaze B2 and
  Cloudflare R2 are the two to look at ([storage.md](storage.md), "Rented storage, later").
- **Prices are config, and an invoice keeps its terms.** `packs.catalog` replaces the two built-in packs where it is
  set; migration 012 stores each invoice's size and days, so re-pricing never changes an open invoice.
- **Currencies:** nothing that holds a buyer's money, nothing that pays a processor. TARI only for the beta: XTM was
  vetted and dropped, Monero would need a node (a disk upgrade: money), Zcash later ([currencies.md](currencies.md)).
  Pack revenue stays on our receiving key, the default; a watch-only revenue address is in the code, left empty.
- **The market keeps both halves apart.** Public shops no longer hand their key to our server. A shopper without the
  shop's link asks the seller's drive, which seals the listing's key half to the shopper; our server relays a
  sealed answer it can't open. Nobody pays before that half arrives. The shop's own link still buys at once, and the
  release still doesn't wait for the seller.
- **The testnet line.** From Nov 11 hidebox.app's footer would say "hidebox stays on the testnet until our code is
  reviewed", which stops being true when the mainnet beta opens. The owner approved new words (2026-11-07, question
  6), now the second sentence of claim C19-k. Changed here and, as a bug fix with the coordinator's OK, on hidebox.app
  (tag `spooky-secrets-2026-10-testnet-line`, 2026-11-09).

## Threat-model delta

| Change | What our server learns or holds now | What stays out of reach | What remains |
|---|---|---|---|
| A rented store | nothing new; the provider gets what our disk had: ciphertext under random ids, padded sizes, arrival and exit times, our server's address | file names, keys, links, drives, visitors' addresses (downloads go through us) | the provider can withhold or delete blobs, and could keep deleted ones (ciphertext) if versions aren't off; the setup turns them off |
| Configured packs | each invoice's size and days | | |
| The market and the new Public | asks: a listing, a time, a pair of public keys made for that ask; sealed answers | the shop key (Private and Public alike), any `sA` in the clear; what we store opens no listed file on its own | a public listing's `sA` goes to whoever asks, so whoever holds `sB` (us, a copy of our database) could open it by asking, as with a shop link posted in public |
| The testnet line | | | |

Removed: "a public shop's key is on our server, which could open what it lists" ([shop.md](shop.md)).

## Plan

| Date (2026) | Milestone |
|---|---|
| Nov 9 | this design; storage and packs built with tests |
| Nov 12 | the market built: server, app, `/market`, the ask flow, the drive's answers |
| Nov 20 | every suite, the UI flows and an end-to-end run on the local stack with the S3 stand-in; independent reviews of the market and the storage client; fixes |
| Nov 22 | deployed to mainnet.hidebox.app, once the Nov 11 flip has happened and the launch lane says it's safe; tagged |
| Nov 23 | the t/520 entry and its announcements rewritten from what shipped |

## Review

Two independent reviews (`code-critic`), one of the storage and packs (`git diff 4de4932..12d171d`), one of the market and
the revenue address (`git diff cc8aa42..71ee1c2`), each with its own probes. Both said FAIL first; the fixes are in
`d741257`.

| Finding | Severity | Fix |
|---|---|---|
| `unlink` looked at the marker before the offload queue: an offload finishing between the two looks left an object in the store for good | blocking | the queue first, and again after the local copy goes; a test forces the interleaving |
| An id with a trailing newline passed `PARAM_RE` (`$`): 50 such asks would fill a seller's page with asks the drive can't answer | blocking | every pattern ends in `\Z`; 422 for both ids |
| A revenue view key file missing or wrong left invoices paying an address nothing watched, with no alert | blocking | setup checks the key against the address first; until it passes no invoice is made (503), and the worker retries |
| An old test rewrote `receiver_address` only | blocking (test) | it rewrites `invoice_address` too |
| A queue entry gone between listing and stat raised; the backlog was read inside cleanup's transaction | non-blocking | skipped; read before |
| Free-share bounds off the 64 MiB step could put the share under the floor; catalog sizes unbounded | non-blocking | whole steps; at most 1 PiB |
| No size check before the local copy goes; a lost object answered 503; cleanup needed the store's key | non-blocking | HEAD before drop; 404; `offline` |
| Search folded Unicode, SQLite folds ASCII | nit | ASCII only |
| **Anyone holding `sB` can ask for a public listing's `sA`** | risk | said as it is in market.md, the threat model, `/fine-print` and the Make it public dialog |
| Removing the revenue keys after credits would freeze the reconcile | risk | documented in currencies.md |

## Deploying round two to the mainnet instance

Only after the Nov 11 flip, with the launch lane's OK. The code runs with the instance's config as it is (every new key
has a default), but that would sell the built-in 0.5 and 1 TARI packs and keep the market off, so the deploy sets these
in `/etc/mutis-NAME/mutis.toml` first, as `deploy/config/instance.toml.example` has them:

| Table | Keys |
|---|---|
| `[features]` | `market = true` |
| `[limits]` | `disk_cap_bytes = 21474836480`, `quota_floor_bytes = 1073741824`, `quota_ceiling_bytes = 1073741824` |
| `[packs]` | the `catalog` of `p2` and `p5` |
| `[storage]` | `backend = "local"` (nothing rented) |
| `[ootle]` | `revenue_address` and `revenue_view_key` stay empty: pack revenue stays on our receiving key |

Then `mutis-admin-NAME check-config`, `deploy.sh --instance NAME <ref>` (migrations 012 and 013 run with the chain worker
stopped; both are additive), `verify-deploy https://mainnet.hidebox.app <tag>`, and on the live site: `/api/v1/config`
shows the catalog, the quota and `features.market`; `/market` answers indexable; a test shop made public shows there; an
ask from a second browser is answered by the owner's open drive; `/api/v1/stats` shows `disk_total_bytes` at the 20 GiB cap, `free_quota_bytes` at 1 GiB and `packs_cap_public` at 8 GiB.

The deploy's acceptance step is the E2E suite against the live instance, without chain transactions there (on the mainnet
they would spend TARI): `tests/e2e/run.py --origin https://mainnet.hidebox.app --instance NAME --only <every scenario but the
chain ones, E-05 and E-16s>`. E-05 needs the short expiry preset, which a production config never has, and E-16s freezes
uploads for everyone. Every browser runs on the server, so `brakes.exempt_addresses` holds its addresses, and the hourly
limit of 5 new drives a network still applies: run in batches an hour apart. The test items a run leaves are taken down
by id (`mutis-admin-NAME takedown share|drop -- <id>`), never by a reset. The chain scenarios ran instead on the
rehearsal of 2026-11-10 (`docs/evidence/2026-11-10/mvp-november-3/`): this tree on Esmeralda with test money, beside
production, torn down after.
