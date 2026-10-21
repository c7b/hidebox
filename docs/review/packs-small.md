<!-- SPDX-License-Identifier: MIT -->
# Smaller space packs (2026-10-21)

The owner's change: the two packs sold in the drive's Upgrade dialog get smaller. Ids, days and prices stay
(invoices in the database name the ids).

| Pack | Before | Now | Days | Price |
|---|---|---|---|---|
| `s30` (small) | 2 GiB | **256 MiB** | 30 | 0.5 tTARI |
| `m30` (big) | 5 GiB | **1 GiB** | 30 | 1 tTARI |

Branch `packs/small`, rebased on `main` and pushed to it; **not deployed**, and the production database was
not touched. No test or rule forced a change to the ids, days or prices.

## What changed

| Where | Now |
|---|---|
| `server/mutis/quota.py` `PACKS` | 256 MiB and 1 GiB. The comment above says what is true now: packs are small next to the paid share and only a few sell a day, so a run of purchases can't take it at once. A comment over `CLASSES` says a class's `max_file_bytes` caps one file and the file must also fit the drive's room |
| `/config` `pricing.packs` | Read from `PACKS`; `bytes` are `268435456` and `1073741824` |
| `handlers/invoices.py` | The 409 `pack_active` message wrote the size in GiB only ("0.25 GiB"); it says "256 MiB" below 1 GiB, "2 GiB" for a pack bought before |
| `packs.py`, `payments.py` | Docstrings only: what `held` infers for a pack bought before schema 6, and that a renewal keeps the larger size |
| `chain_worker.py` (evidence invoice), `jobs.py` (`DEMO_PAY_MAX_UT`) | Nothing: they use the price, not the bytes, and the prices didn't change |
| The drive's Upgrade dialog, `/upgrade`, `/made` | Nothing in their code: they format `pricing.packs` from `/config` (below) |
| `/made` | One sentence under the Limits table (next section) |
| `docs/threat-model.md` | "Packs are 256 MiB and 1 GiB, so one purchase, or a whole day's, is a small part of the slice." |
| `tests/e2e/README.md`, E-13 | A test pack is 256 MiB; E-13 checks the quota grew by at least 256 MiB |

`web/app/i18n/en.json`, `tools/claim-registry.json`, `README.md`, `PRODUCT.md`, `DESIGN.md`, `docs/api.md` and the
other site pages never wrote a pack's size (the copy deck has `+{bytes} for {days}`), so they didn't change.
`web/site/js/stats.js` formats `pack_s30_size` as "256 MB" and `pack_m30_size` as "1 GB" with the formatter it
already had.

## What the Upgrade dialog shows

Storage, Get more space (`/drive/storage#more`, where the header's Upgrade goes):

| Card | Line under it | Price | Button |
|---|---|---|---|
| **+256 MB for 30 days** | For a few more folders. | 0.5 tTARI | Get it |
| **+1 GB for 30 days** | For big folders and video. | 1 tTARI | Get it |

The invoice dialog repeats the card's title and, once credited, says "Added: 256 MB until Nov 20, 2026." for
a pack bought on Oct 21 (the date is the pack's end). `/upgrade` shows the same two titles and prices; `/made`'s pack table reads
"+256 MB for 30 days, 0.5 tTARI" and "+1 GB for 30 days, 1 tTARI".

## The paid class's 2 GiB largest file

`CLASSES["paid"]["max_file_bytes"]` stays 2 GiB, now more than either pack. `/config` and `/made`'s Limits table
(Largest file, More space: 2 GB) say so, so a reader could take it as "the 256 MB pack lets me upload a 2 GB
file". Kept, because:

- It is a per-file cap, like the others: a free drive's 512 MB already sits under a free share that can be
  256 MiB. Room is a second check: a drive holds its free share plus its pack (`quota.locker_limit`), and an
  upload that doesn't fit is refused at reservation with 507 `quota_exceeded` and `limit_bytes`, before any
  byte moves, never with a 413 that would contradict `/config`.
- Today it holds: the deployment's free share is 2 GiB (`/api/v1/stats`, 2026-10-21), so a drive with the small
  pack holds 2.25 GiB and one 2 GiB file fits.
- Capping it at the pack a drive holds would make the small pack *lower* the largest file from 512 MB to
  256 MB. Capping it at the big pack (1 GiB) would end S-09, the 2 GiB streaming proof, and the owner asked to
  leave the 2 GiB cap alone.

What changed for it: `/made` says it under the Limits table, from `/config`, shown only with the rows it
explains: "**The largest file** also has to fit in the drive: even with more space, a 2 GB file needs that much
room in its free share today plus its pack." Tested in `test_quota.test_a_paid_drive_s_largest_file_must_also_fit_its_room`:
with the small pack and a 1 GiB free share a 2 GiB upload gets 507 `quota_exceeded` (`limit_bytes` 1.25 GiB,
nothing reserved) while `/me` and `/config` say 2 GiB; one byte over 2 GiB is 413 `too_large`; with a 2 GiB
free share the same file is admitted (checked without allocating 2 GiB). `test_paid_locker_limits` now buys the
small pack: it still lifts a 600 MiB file past a free drive's 512 MiB.

## Packs already sold

A drive that holds a pack bought before this change keeps its bytes (2 GiB or 5 GiB) to the pack's end, as
`paid_bytes` says. A renewal in its last 3 days keeps them too: `grant_pack` takes the larger of the two sizes,
so a renewal never leaves a drive's files over its limit. Such a drive could keep 2 GiB for 0.5 tTARI a month for
as long as it renews; the paid slices count its real bytes, so the cap still holds. Test:
`test_a_pack_bought_when_packs_were_bigger_keeps_its_bytes`. A pack bought before schema 6 (no `paid_pack`, all
ended by 2026-11-13) no longer matches a size, so `held` gives it the id `null`, which the API and the dialog
already treat as "renew with either pack".

`/stats` still rounds `packs_sold_public` and `packs_cap_public` down to whole GiB, so four small packs move it by
one.

## Tests changed

| File | What |
|---|---|
| `server/tests/test_packs.py` | The slices' disk is a 4.75 GiB pool (cap 1.9, judges 0.57, public 1.33) so each scenario still meets its limit with the new sizes: the public slice fills with the big pack and a small one; the judges' slice takes two small packs before its spill finds no room; a judges' big pack spills 0.43 GiB and the public big pack no longer fits; a refused swap and a refused purchase use a 0.5 GiB pool; the 80 % alert a 2 GiB pool; `/stats` rounds 1.68 GiB down to 1. New: a pack bought when packs were bigger keeps its bytes |
| `test_payments.py`, `test_receiver_ownership.py`, `test_admin.py`, `test_cleanup.py`, `test_contract.py` | +256 MiB; the late-payment test's slice is 1.33 GiB; the sold-out contract test uses a 0.5 GiB pool (at 1 GiB the small pack now fits) |
| `make_vectors.py`, `vectors/quota.json` | The rented case is one big pack and two small ones (1.5 GiB, from `PACKS`), regenerated with the generator |
| `test_quota.py` | The two tests above |
| `deploy/tests/test_check_copy.py` | Its fake page writes the small pack as "256 MB" |
| `web/site/tests/fixtures/config.json` | The new `bytes` |
| `web/app/ui/tests/flows.py`, `flows_drive.py`, `run.py` | `upgrade` checks `/upgrade`'s two titles; `storage-meter` checks the dialog's two cards and "Added: 256 MB until"; both check the quota grew by at least 256 MiB |

## Suites

All green; logs in [`docs/evidence/2026-10-21/packs-small/suites/`](../evidence/2026-10-21/packs-small/suites/),
the Storage page with the two cards in
[`storage-1440.webp`](../evidence/2026-10-21/packs-small/storage-1440.webp).

| Suite | Where | Result |
|---|---|---|
| `python3 -I -m unittest discover -s server/tests` | the workstation, `TMPDIR` off tmpfs | 367 tests OK (5 skipped, the opt-in ones) |
| `python3 -I -m unittest discover -s deploy/tests` | the workstation | 113 tests OK |
| `tools/build.py`, `tools/lint.py`, `tools/check-copy.py` (with and without the fixture config) | the workstation | build OK, lint PASS, check-copy PASS |
| `web/site/tests/run.py` | the server, as `build` | 46 of 46 checks |
| `web/app/tests/run_all.py` (core) | the server, as `build` | ALL PASS (9 steps) |
| `web/app/ui/tests/run.py --only upgrade upgrade-wallet` | the server, as `build` | UI PASS 19/19 |
| `web/app/ui/tests/run.py --only drive-shell storage-meter` | the server, as `build` | UI PASS 44/44 |

The E2E scenarios (E-13 buys a real pack on chain) were not run: they run against the deployment, which this
change doesn't touch until it is deployed.

## Left

- The two lines under the cards ("For a few more folders.", "For big folders and video.") don't name a size and
  read true at 256 MB and 1 GB; the owner may want words for smaller packs.
- `server/ACCEPTANCE.md` and `web/app/ACCEPTANCE.md` still say "+2 GiB" for S-07 and the Upgrade flow: they are
  dated records of those runs (launch-hygiene.md).
- `test_streaming.py` (S-09, opt-in) gives its drive 2 GiB of paid space by hand to move one 2 GiB file; that is
  the 2 GiB file cap, not a pack.
- `web/app/shots/upgrade-390-*.webp` are curated shots from an older run (the old brand, "+2 GB" and "+10 GB");
  not rewritten here. `run.py --shots` makes new ones; `/upgrade`'s full-page capture puts the fixed bottom
  bar over the second card, as the old one did.
- The 2026-10-14 anti-grief evidence and the CHANGELOG's sixth pass still say "the 5 GiB pack": records of then.
- `tests/e2e/devil.py` names packs by id only and was not run (it needs the local stack on the server); its
  attacks are the same with smaller packs, only the bytes they would hold shrink.
