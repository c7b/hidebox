<!-- SPDX-License-Identifier: MIT -->
# Upgrade to Tari Ootle v0.46.0, 2026-10-13

The owner's decision on the incident of the same day (`../incident-walletd/`): Esmeralda's indexers
moved to v0.46.0 at about 10:30 UTC and walletd 0.45.0 couldn't read a transaction result after
that. This folder is the upgrade drill (`deploy/ootle/upgrade-drill.md`) as it ran, from 18:10 UTC.
Times are UTC. Nothing here is a secret: no key, no judge pass, no production link with its key;
hashes are cut where the full value isn't the point.

## Result

| What | State |
|---|---|
| walletd | **0.46.0** live since 18:14:37 (`26d4c269…6e05`, four sources agree); 0.45.0 kept beside it; store migrated (one additive table), balances unchanged |
| Results | read again: checkpoints #157 to #160 settled, #159 and #160 recorded `committed` by mutis-chain |
| Pending in walletd | 21 that never will settle: the sponsor's 10:39 send and 20 manifests from `service` whose results the network no longer serves (it keeps them about one or two epochs, not four hours) |
| Sponsor | **still can't spend**: its change `3ee453ab…` (8,851.452 tTARI) is on chain and in the mirror, walletd holds it `LockedUnconfirmed`, and 0.46.0 has no way to release it without deleting it. Stopped here (below) |
| Checkpoints #141 to #158 | recorded `committed` (epochs and indices 140 to 157 from the log's state on both indexers), one transaction after a backup; #159 to #161 committed by the worker since |
| `/releases.json` | `27e29462`, `ec2956b4`, `612db64f` notarized (21 entries) |
| `/evidence.json` (18:32) | latest checkpoint index 159 (#160), epoch 12227 |
| `/status.json` (18:32, 18:43) | **red**: canary red (no delivery since #38; amber for 20 minutes after each hourly seal), sponsor_balance amber, budgets amber (`decoy.reserved.50`, `sponsor.evidence.90` from the day's E2E); walletd, chain worker, mirror, credits, api green |
| ootle-wasm | **0.46.0 vendored** in the repository (integrity, provenance and the GitHub tag and run checked; only the `.wasm` changed); every suite passes with it; **not deployed** (below). Production keeps 0.45.0 |
| Browser library on the V2 chain | **both 0.45.0 and 0.46.0 pass the live gates G1 and G2c**: a stealth transfer built, signed and submitted in Chromium commits (2.6 s, 2.7 s), and its courier memo opens (`gates.txt`) |
| E2E chain scenarios, `canary-now` | **not run**: every one of E-09, E-10, E-12, E-13, E-25 and E-J, and the canary, starts with a sponsor send |
| Survivors | 20 judge passes, the security drop `3w7m8k2v5t` active, 118 lockers (no test item was made, so nothing was purged) |

## Files

| File | What |
|---|---|
| `checksums.txt` | walletd: GitHub's digest, the `.sha256`, the release's list and the bytes on ultron; what is installed. ootle-wasm: registry integrity, local sha512, both attestations, the GitHub tag and workflow run, file hashes against 0.45.0 |
| `release-notes.txt` | the v0.46.0 notes that touch us, the store migration, #2855 against `--authentication none`, #2859 from our client's side, what 0.46.0 doesn't offer |
| `drill-log.txt` | §3 on a copy with no network, §4 live, what settled |
| `walletd.txt` | walletd before and after, its journal after the start, and why the sponsor's change stays locked (source lines at the tag) |
| `chain.txt` | the chain worker's journal; checkpoints #141 to #158 against the log; the transaction that recorded them; the three notarizations on chain |
| `status/` | `/status.json` at 18:19 (walletd upgraded), 18:32 (after the checkpoints and notarizations) and 18:43 (the end: the same); red before the upgrade too (the incident) |
| `suites/` | the suites with ootle-wasm 0.46.0, on ultron as `build` from the working tree (`scripts/suites.sh`; exit codes in `done`) |
| `gates.txt` | the live gates G1 and G2c with ootle-wasm 0.45.0 and 0.46.0 on the V2 chain |
| `survivors.txt` | read-only counts after the changes and at the end |
| `scripts/` | the read-only helpers and the one write (`markseal.py`) |

## What was done, in order

1. **walletd 0.46.0** checked (`checksums.txt`) and put at `/opt/tari/bin/tari_ootle_walletd-0.46.0-cc8a83b`.
2. **Drill §3** (18:13:57): the drill's script on a copy, with no network. One migration
   (`signing_requests`, additive), the same accounts and balances but one checkpoint fee that landed
   between the copy and the live read (`drill-log.txt`). The copy was deleted by the script's trap.
3. **Drill §4** (18:14:37): balances snapshot, `systemctl stop walletd`, cold tar
   `/var/backups/mutis/wallet-20261013T181437Z-pre-upgrade.tar` (root 0600), the 0.45.0 binary kept as
   `tari_ootle_walletd-0.45.0-9c62606`, 0.46.0 installed at the unit's path, start. Balances equal
   (the version line aside). Nothing else on the unit or its config changed.
4. **Settling** (18:14 to 18:31): three results read at once; 21 stay pending (`walletd.txt`). The
   sponsor's change stays `LockedUnconfirmed`; decoys keep failing with "Available: 0".
5. **Looked for walletd's own remedy** in 0.46.0's RPC table, CLI and source: none settles, cancels or
   rescans a transaction whose result is gone, the scanner keeps a held output's status, and every
   way a lock is released deletes the unconfirmed change (`walletd.txt`). `reset` would wipe the
   wallet. So, as the brief says, the sponsor work stops here and nothing in the store was touched.
6. **Re-notarized** the three releases (18:19 to 18:20, `chain.txt`), now that `service` sends work.
7. **Checkpoints #141 to #158** (18:21): all 18 are in the live log with the same root and tree size;
   database backup, then one transaction (`chain.txt`). `sudo systemctl start mutis-evidence` (the
   runbook's) refreshed `/evidence.json`.
8. **ootle-wasm 0.46.0** (18:16 to 18:45): fetched as data from the registry, checked, vendored; the
   suites ran on ultron as `build` (`suites/`). Not deployed: the drill's §5 is "pause, deploy, run
   the chain scenarios, clear", and the scenarios can't pass while the sponsor can't send, so a deploy
   now would ship a browser library change without the proof the drill asks for.
   The scenarios don't prove 0.45.0 either; step 9 shows both libraries work on the V2 chain for what
   the library itself does, and the module's own Rust didn't change between the tags
   (`crates/ootle_wasm`), so production keeps 0.45.0 meanwhile.
9. **The live gates G1 and G2c** (18:35 to 18:37, `gates.txt`), the browser library's own chain
   test (web/app/tests/README.md), with both libraries: walletd 0.46.0 funded the gates' test wallet
   from `service` (200,000 µT), then 0.45.0 and 0.46.0 each built, signed and submitted a stealth
   transfer in Chromium that the V2 committee committed, and each courier memo opened (the view key
   alone refused). So production's 0.45.0 works on the V2 chain for what the library does there; the
   scenarios that would show the whole flows (grants, payments, the UI) still wait for the sponsor.

## ootle-wasm 0.46.0 in the repository

Only `ootle_wasm_bg.wasm` differs from 0.45.0 (`2856d86b…93f2`, 1,289,871 B); the glue, the types, the
bundler entry and the license are the same bytes. Changed with it: `web/app/vendor/ootle-wasm-0.46.0/`
(with `SHA256SUMS` and `PROVENANCE.md`), the shim's pinned hash, `tools/build.py` `PINNED`,
`deploy/scripts/{activate-release,init-keys}.sh`, the server's `PINNED_WASM_SHA256` and
`wasm_version` default, the example config, the test paths and fixtures, `NOTICE`. No API change, so
nothing in `web/app/lib` or the sidecar's code. Suites (`suites/`): core ALL PASS in 9 steps (KATs
120/120 under Node and in Chromium, jitless 75/75, sidecar 16/16, contract 12/12), the real sidecar 3
tests (it reports `2856d86b…`), server 204 (4 opt-in skips), deploy 77, lint, copy, site 29 of 29,
UI 375 of 376: the one failure was the workspace, not the code (`template/seal_log/tests/vectors`
wasn't copied, so the receipts flow couldn't read its fixture); with it copied, the receipts flow
passes 13/13 (`suites/ui-receipts.log`). And the live gates G1 and G2c (`gates.txt`).
(`suites/gate-chain.log` is the drill's `mode=addr` step, which only makes the test identity's
addresses and a memo.)

To ship it (the owner's call, once the sponsor can spend): `ootle.wasm_version = "0.46.0"` in
`/etc/mutis/mutis.toml`, then the drill's §5 (`deploy.sh` with the Tari features paused, the chain
scenarios, `feature … clear`). Until that deploy, `tests/e2e/test_headers.py` from this commit on
fails against production on the wasm's path (`/app/vendor/ootle-wasm-0.46.0/…`, production serves
`…-0.45.0/…`); run it from `2ede662` or earlier meanwhile.

## What remains for the owner

1. **The sponsor's 8,851.452 tTARI.** On chain and ours, but walletd won't spend it. Ways out, none
   taken here:
   - Fund `sponsor` afresh from `service` (it holds 72.268 tTARI confidential and 17.09 tTARI
     revealed; the sponsor's slices allow 140 tTARI a day, 22 are counted used today) with
     a stealth transfer: the new output is spendable once it commits. A spend between our own
     accounts, and `service` also pays every checkpoint, so it waits for the owner.
   - Ask Tari for a walletd remedy (settle or drop a pending transaction whose result is gone without
     deleting its change, or a rescan that re-validates held outputs). The code says so itself:
     "TODO: if this happens forever we might want to resubmit or mark as invalid"
     (`crates/wallet/sdk/src/apis/transaction.rs:240`).
   - Not recommended: editing walletd's store by hand, or `reset` (re-initialises the wallet).
2. **The chain scenarios** E-09, E-10, E-12, E-13, E-25 and E-J, and `canary-now`, once the sponsor
   can send; then the ootle-wasm deploy (above). The evidence slice resets at 00:00 UTC
   (`budget.sponsor.evidence.90` is today's).
3. **The 21 pending transactions** stay in walletd's list and cost one indexer request each every 5 s
   (about 15,000 journal lines an hour). Harmless so far (no rate-limit answers), but the indexers now
   rate-limit public reads (#2823) and the mirror polls them every 3 s from the same address.
4. Until the sponsor can send, the Tari features fail visibly (grants, deliveries, the demo payment)
   and `/status.json` stays red on the canary; pausing them (reset playbook §1) is the owner's call.
