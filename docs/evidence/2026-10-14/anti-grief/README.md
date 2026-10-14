<!-- SPDX-License-Identifier: MIT -->
# The sixth pass: anti-griefing for the space (2026-10-14 UTC)

The owner's concern: someone buys space from many drives very fast, so the disk saturates, the packs
(test money) sell out at once, or free uploads freeze for everyone. What was built is in
`docs/threat-model.md` ("Griefing the space"), the runbook in `deploy/README.md` ("If someone games the
packs"), the verdicts in `docs/review/fix-log.md` ("Sixth pass (anti-griefing)"). Live and tagged:
`f89963c0c8d61ee696eed9ae60c1b81cbdeae179` (release `f89963c0c8d6…-c8484114c`, manifest `64ae70eb…d210`
notarized through SealLog in tx `e939fa44…486c`).

| What | Where |
|---|---|
| Suites (ultron, as build, a tarball of `d5fd958`) | `suites/`: server 329 OK (5 skipped), deploy 79 OK, lint PASS, check-copy PASS, app `run_all` 9/9, UI 621/621 (A-06 40,536 B ≤ 40,960 on a phone, 43,503 B ≤ 43,520 on a computer; A-06d 112,941 B ≤ 131,072; `storage-meter` checks the held pack's button, the other pack waiting, and the renewal date). Site 28/29 (`llms-full.txt` stale after the fine-print change), regenerated, `site-2.log` 29/29. Later commits were server-only plus docs; each deploy's gate ran server, deploy, lint and copy again (`deploy/deploy-*.log`: 327 OK on 3.13, 6 skipped) |
| Devil, before and after | `devil/`: `tests/e2e/devil.py` on a throwaway stack (`mutis-api --dev`, fake chain, forged documentation addresses). Below |
| Releases | `deploy/deploy-1.log` `c98031a` (schema 6; migration backup made), `deploy/deploy-2.log` `f89963c` (the day's ceiling counts packs that still hold space). `verify-2.log` and `verify-tag.log`: 0 differences across 157 files, SealLog's template on chain byte for byte; `d01-2.log`: D-01 PASS |
| Production config | `/etc/mutis/mutis.toml` gained `[brakes] exempt_addresses` = ultron's own IPv4 and IPv6 addresses (where the E2E browsers run), copy `/var/backups/mutis/mutis.toml.20261014T175213Z.before-anti-grief`; `check-config` ok, mutis-api restarted. No `e2e_expiry_s`. Everything else takes the defaults |
| E2E on `f89963c` | `e2e/batch-A1.log`: the non-chain batch 13/13 (E-01, E-02, E-04, E-06, E-07, E-15–E-21, E-03). **E-13 and E-J track two not run:** the evidence slice's sponsor budget was still spent (10/10 tTARI; it resets at 00:00 UTC), and in direct mode both pay from a browser wallet funded by that slice |
| A pack on chain with a judge pass | `e2e/pack-live.log` (`pack-live.py`, through the API, one judge-pass drive): invoice 201, the same pack again → 200 the same invoice, test money from the evidence slice's `demo_pay` budget, credited in 5 s with `amount_proven` and `committed_on_chain`, `/me` holds s30, a second purchase → 409 `pack_active` "You already have 2 GiB until Nov 13."; `e2e/packs-admin.log`: the judges' slice 2.0 / 8.1 GiB, then `release-pack` |
| Kill switch | `e2e/killswitch.log` (`killswitch.py`): `feature packs off` → an invoice 2.7 s later is 503 `feature_disabled` `{feature: packs}`; `feature packs clear`; the test drive deleted itself |
| Tag | `checks/tag.txt`: annotated, moved from `c73c7b4` to `f89963c`, pushed with main; the live version matches |
| Purge | `e2e/purge.txt`: 2 test items and 1 drop taken down by id (a read-only diff against a snapshot taken before the batch); `e2e/survivors.txt`: the security drop `/d/3w7m8k2v5t` active, canary items kept, 42 judge passes, one active pack (a visitor's, 2 GiB) |
| Status | `/status.json` amber only for `budget.decoy.reserved.50` and `budget.sponsor.evidence.90`; `packs` green. `/api/v1/stats`: `packs_sold_public` 2 GiB of `packs_cap_public` 18 GiB (pool 67.8 GiB, paid cap 27.1, judges' slice 8.1) |

## The devil: what got through, before and after

`devil.py` on the dev stack (pool about 68 GiB; dev budgets: 5 tTARI of public test money a day). Before =
`a27f020` (the fifth pass), after = `3c767a9` (with the per-pass fix; `after-23e10c9.json` is the first
run, before it).

| Attack | Before | After |
|---|---|---|
| P1 one network, 5 drives, a 10 / 5 GiB pack each | 5 invoices | 1; 4 `packs_limited` |
| P2 40 networks, one drive each, the big pack | 6 invoices, then `sold_out` once 2 were paid (20 GiB of a 27 GiB cap in about a minute; the dev test-money budget stopped the rest) | 2 (the day's 3 public, one taken by P1); 38 `packs_limited`; both paid; `/stats` 10 of 19 GiB |
| P3 one judge pass, 6 networks × 3 drives | 18 invoices | first run: 6, then `sold_out` (the judges' slice and the public one filled through the spill); with the per-pass fix: 2; 16 `packs_limited` |
| P4 a drive holding a pack asks for another | `sold_out` (it would have stacked bytes) | 409 `pack_active` |
| F1 one network, 3 drives on day two, 16 × 256 MiB | 16 (4 GiB) | 8 (2 GiB); 8 `uploads_limited` |
| F2 one /48, 8 /64s, 32 × 256 MiB | 32 (8 GiB) | 24 (6 GiB); 8 `uploads_limited` |
| D1 one /48, 40 /64s, a drive each | 20 (the hourly limit) | 20 (the same in the first hour; the daily cap holds the rest of the day: `test_packs.py`) |

Found and fixed: one judge pass spread over networks took the judges' slice and spilled into the public
one in minutes → a pass now buys 2 packs and uploads 8 GiB to free drives a day, wherever it is used
(`3c767a9`). Found on production: invoices made earlier in the day by test runs, whose packs had been
released, filled the day's public ceiling → the ceiling counts packs that still hold space (`f89963c`).
A refused pack swap closed the invoice it replaced → the swap happens in the new invoice's transaction
(`c98031a`).

Still open (stated in the threat model): many networks (a botnet, or an IPv6 /32) get through at the
deployment's daily pace and can fill free space at 6 GiB a /48 a day; someone with three networks an hour
can hold the day's public packs with unpaid invoices (they free up when the invoices expire, an hour);
judges' purchases may spill into the public slice by design (10 a day); a restart forgets the per-network
counts. The disk's hard freezes are what protect the disk itself.
