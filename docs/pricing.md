<!-- SPDX-License-Identifier: MIT -->
# Sizes and prices on the mainnet

What a drive gets for free and what extra space costs at mainnet.hidebox.app, and the arithmetic behind both. The
testnet (hidebox.app) keeps its own numbers: a free share of 256 MiB to 5 GiB, and packs of 256 MiB and 1 GiB for 0.5
and 1 tTARI, test money worth nothing.

## The space

The beta's files live on this server's disk, which it shares with production ([storage.md](storage.md)). It may use at
most **20 GiB** of it (`limits.disk_cap_bytes`) and never takes the disk below its 10 GiB reserve. Nothing is rented, so
no price below has to pay a storage bill: the disk is part of the server we already run. What the numbers have to do is
fit the 20 GiB, so a few drives can't take it all, and charge enough in TARI that a pack means something.

| | Testnet | Mainnet beta |
|---|---|---|
| The pool | the disk | at most 20 GiB of it |
| Free share per drive | 256 MiB to 5 GiB, as the pool allows | **1 GiB** (`quota_floor_bytes` = `quota_ceiling_bytes`) |
| Paid space, at most | 40 % of the pool | 40 %: about 8 GiB |
| Largest file | 512 MiB free, 2 GiB with a pack | the same |

With the pool at 20 GiB, the small-file, drop and anonymous lanes keep about 4.6 GiB, and about 15 GiB is left for free
shares. That is 15 drives filling their 1 GiB completely; most never do. When free space runs low, free uploads pause
for everyone (`uploads_frozen`), as on a full disk, and packs keep working.

## The packs

| Pack (`packs.catalog`) | Size | Days | Price | Per GiB-month | In dollars |
|---|---|---|---|---|---|
| `p2` | +2 GiB | 30 | **50 TARI** | 25 TARI | about $0.05 |
| `p5` | +5 GiB | 30 | **100 TARI** | 20 TARI | about $0.11 |

TARI is about $0.00107 (XTM on CoinGecko, 2026-11-08; TARI on the Ootle is made only by burning XTM 1:1).

- **They fit.** The paid cap holds one big pack and one small one at once, or four small ones. The daily brakes (three
  packs a day for the whole deployment, one per network) keep a run of purchases from taking it, and "The disk is
  finite" answers when it is full.
- **They are small on purpose.** Real money on a beta: keep amounts small, as every money screen says.
- **If the space grows** (a bigger cap, or rented storage, [storage.md](storage.md) "Rented storage, later"), the
  catalog grows with it. At Backblaze B2's $6.95 per TB-month, 1 GiB for 30 days would cost about 7 TARI of storage, so a
  rented store would want prices of 20 to 25 TARI per GiB, which these already are.

## Re-pricing

When TARI moves by half either way, or the cap changes, edit `packs.catalog` in `/etc/mutis-NAME/mutis.toml` and restart
the API. An invoice keeps the size, days and price it was made with (migration 012), so a change never touches one
already open, and a drive that holds a pack keeps it to its end. Don't reuse a pack's id for a different kind of pack:
invoices name it.
