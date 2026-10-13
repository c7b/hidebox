<!-- SPDX-License-Identifier: MIT -->
# Incident: walletd 0.45.0 can't read Esmeralda's v0.46.0 indexers, 2026-10-13

From about 10:39 UTC every chain send through walletd failed: canaries #39 to #45 undelivered,
SealLog checkpoints #141 on recorded as failed, sponsor grants, the 12:00 evidence payment and decoys
failed with `walletd_error`, and `/status.json` went red. The cause is on Tari's side: the public
Esmeralda indexers were upgraded to Ootle **v0.46.0** at about 10:30. That release drops a field
from every transaction result, and walletd 0.45.0 can't decode a result without it. Upgrading walletd
is a release decision (`deploy/ootle/upgrade-drill.md`), so this note stops at the diagnosis and the
decision it needs. Nothing on the server was changed but two stale processes of `build`. Times are UTC.
The receipts are `walletd.txt` (walletd's journal and RPC answers), `chain.txt` (mutis's database read
only, the indexers) and `release-0.46.0.txt` (the release, its digests, the field that broke).

## Timeline

| UTC | What |
|---|---|
| 09:58:59 | Tari tags v0.46.0 (commit `cc8a83bcab88`); `@tari-project/ootle-wasm` 0.46.0 on npm at 10:03; binaries uploaded 10:44, release published 10:47:46 |
| 10:03 to 10:28 | Last good work: canary #38 delivered (10:03:44) and verified, last job done 10:05:06, checkpoint #140 committed 10:28:08 (log index 139), the last transaction walletd marked `Accepted` (10:28:09) |
| 10:30:52 to 10:31:13 | indexer-a drops walletd's finalization stream, then answers 521 and 500: the indexer restarting |
| 10:39:22 | walletd submits a send from `sponsor` (`2749858a…`), which spends the sponsor's only output. It commits: its change (8,851.452 tTARI, `utxo_…3ee453ab…`) is on both indexers and in mutis's mirror at epoch 12214 from 10:39:32. walletd can't decode the result ("Failed to deserialize response … error decoding response body", every 5 s from then on), so the transaction stays `Pending` and the change stays `LockedUnconfirmed` |
| 10:43:09 | Checkpoint #141 is submitted and commits, but walletd can't read the result; mutis gives it up after 900 s as `failed`. The same for every checkpoint since, 25 minutes apart (900 s waiting for a result, then the 600 s retry delay) |
| 10:49:55 | First refusal of a sponsor send: "Insufficient funds: … Available: 0, Required: 31000". From then on every courier send (the hourly canary), decoy, grant (1,030,000) and the evidence payment (530,000 at 12:00) fails after 3 attempts with `walletd_error` |
| 11:03:31 | Canary #39 sealed; its delivery fails at 11:04:51 (the time the incident was first noted) |
| 11:11:42, 12:39:10, 13:35:33 | Three deploys restart `mutis-chain`; no effect, since walletd is the part that can't read results. Their release notarizations (`1ecdcf01…`, `d32cd042…`, `f9f992aa…`) stay `Pending` in walletd and are missing from `/releases.json` |
| about 14:10 | Epoch 12220: Esmeralda's Protocol V2 (v0.46.0) is active. Transactions built by walletd 0.45.0 still commit after it (#157 and #158 at 17:23 and 17:48, epoch 12226) |
| 14:39:35 | `chain.budget_50` (decoy, reserved): each retry charges the slice again |
| 17:50 to 18:10 | This diagnosis; the two stale `build` processes stopped |

## Cause

v0.46.0 (PR #2859, "stop recording template return values in the transaction result") removes
`execution_results` from `FinalizeResult`. In 0.45.0 that field is required (`Deserialize` with no
`#[serde(default)]`). The indexers' JSON for `GET /transactions/<id>/result` no longer has it, so
walletd 0.45.0 can't decode any transaction result or manifest dry run from an upgraded indexer. Both
configured indexers (a and b) are upgraded and agree on the chain (epoch 12227, the same block at 18:03).
There is no older indexer to fall back to.

Two effects follow, and between them they account for every failure:

1. **Every transaction walletd submits stays `Pending` in walletd**, although it commits on chain. 23
   are pending now: the 10:39 sponsor send and 22 manifests from `service` (checkpoints and the three
   notarizations). mutis's worker waits 900 s for each and records it as `timeout`/`failed`.
2. **The sponsor can't spend.** Its whole balance is the change output of the 10:39 send, which walletd
   holds as `LockedUnconfirmed` until it sees that transaction finalize, and it never will. So every
   stealth transfer from `sponsor` is refused with "Available: 0" (`walletd_error`), and the worker's
   balance check reads 0 (`sponsor_balance` amber).

Ruled out:

- **The testnet stalling or resetting:** epochs advance (12213 at 10:28, 12227 at 18:03), and both
  indexers serve our committed checkpoints and the sponsor's change output.
- **Protocol V2 (epoch 12220):** it began about 3.5 hours after the first failure, and 0.45.0's
  transactions still commit under it.
- **walletd down, disk or memory:** walletd answers its RPC (unit up since 2026-10-12 01:35, 77 MB of
  2 GB); disk 37 % used, 7,199 of 7,945 MiB of memory available.
- **Funds:** nothing was spent that shouldn't have been. The sponsor's 8,851 tTARI is in a confirmed
  output on chain, and `service` paid 5,287 µT a checkpoint, as before.
- **The stored dry run `a599a962…`:** status `New` since 2026-10-11 23:06, its three inputs are
  `service`'s, and its resubmit line runs at the same rate before and after 10:30 (about 725 an hour).
  It doesn't touch the sponsor's output and isn't involved.

A walletd restart wouldn't help: the decode failure is in the binary, and the 23 pending transactions
would be polled again with the same result. No RPC in the runbook clears a pending transaction. So no
fix was applied.

## What happened on chain meanwhile

- SealLog: checkpoints #141 to #157 all reached the log in order (#157 and #158 hold indices 156 and
  157; #140 held 139), each paying about 5,287 µT. mutis records #141 to #157 as `failed`, and #158 will
  follow, so `/evidence.json` still names #140 (index 139) as the latest checkpoint. The next checkpoint
  mutis does record will cover all their leaves.
- The 10:39 sponsor send committed. No other sponsor send was submitted after it.
- The indexers keep a result for about 4 hours. Results for `2749858a…` and every checkpoint up to
  #149 (14:03) already answer 404 on both.

## What the owner has to decide

**Upgrade walletd (and ootle-wasm) to v0.46.0** through `deploy/ootle/upgrade-drill.md` §1 to §5:

| Piece | v0.46.0 |
|---|---|
| Tag | `v0.46.0` → commit `cc8a83bcab88e03e0fcf760d2652ab6f1e067d8a`, prerelease, published 2026-10-13T10:47:46Z |
| walletd for ultron | `tari_ootle_walletd-0.46.0-cc8a83b-linux-x86_64`, 61,979,368 B, SHA-256 `26d4c269dfb091e47156aaa2af4cfb12bbdab9c5812ef8a292b0dd8b73976e05` (GitHub's digest, the asset's `.sha256` and `tari_ootle-0.46.0.sha256-unsigned.txt` agree) |
| ootle-wasm | `@tari-project/ootle-wasm@0.46.0`, integrity `sha512-EwTH+dKSN1XqWxSiR1ETRXQKj87AwJ6GnIQFXzTo0zgV3CGnn60imMSM9zofd6KG8+51FcmrcLsCmqWBTq9wVA==` (provenance not checked yet) |
| Running now | walletd 0.45.0, `8cfdae03…2fae` (the hash in `docs/self-host.md`); ootle-wasm 0.45.0 |

What v0.46.0 changes that touches us (release notes, `release-0.46.0.txt`): no return values in
transaction results (the break); Protocol V2 on Esmeralda from epoch 12220; "approving a transaction
request needs the wallet's own session" (#2855: check that `auth.request` with `--authentication none`,
which our client and `walletd-rpc.py` use, still works); confidential outputs finalize against the
transaction diff, and transfer-proof change nets out the revealed amount (#2898, #2824: stealth
transfers, which we send); indexer failover bounds and substate checks (#2802, #2813); rate limits on
the indexers' public read routes (#2823: the mirror polls them every 3 s).

Things the drill must check before step 4, beyond `balances` before and after:

1. **The sponsor's locked change.** Once walletd can decode results, the pending transactions still on
   the indexers should settle. `2749858a…`, the one that holds the sponsor's output, is already 404 on
   both indexers. If 0.46.0 never finalizes it, `sponsor` stays at "Available: 0" after the upgrade.
   Check `stealth_utxos.list` for `sponsor` after the upgrade: commitment `3ee453ab…` must become
   spendable. If it doesn't, that takes walletd's own remedy, and the wallet store is not edited by hand.
2. **The wallet store.** Whether 0.46.0 migrates walletd's database (drill §3 runs it on a copy first).
3. **ootle-wasm 0.45.0** in the browser and the sidecar: the browser's `waitFinal` reads only
   `final_decision`, so the new result shape is fine there. Whether a 0.45.0-built browser send is valid
   under V2 is untested; vendoring 0.46.0 (drill §1) settles it.

**Meanwhile (also the owner's call, not done here):** pause the Tari features (reset playbook §1) so the
site shows its paused state instead of failing grants and deliveries, and checkpoints stop landing
unrecorded. Left as it is, nothing is lost: checkpoints land on chain, and failed jobs spend nothing.

**After the upgrade:** `sudo mutis-admin canary-now`, then the brief's step 3: a checkpoint committed in
`seal_checkpoints`, a canary delivered and verified, a sponsor and a decoy job `done`, `/status.json`
green or amber only for `budget.sponsor.evidence.90`, and `tests/e2e/run.py --chain --only
E-09,E-10,E-13,E-25` (drill §5) with its items purged by id. Re-notarize the three releases missing from
`/releases.json` (`ec2956b4`, `612db64f`, `27e29462`). Whether to mark checkpoints #141 to #158
`committed` in the database is a production-database change, left to the owner.

## What was done on the server

- Read-only: `journalctl` for walletd and mutis-chain, walletd's RPC as `drive` on the loopback port
  (`wallet.get_info`, `balances`, `transactions.get_all`, `stealth_utxos.list`), the database as `mutis`
  in read-only mode, `health.json`, disk and memory. The indexers and GitHub were read from the jarvis box.
- Not done: no walletd restart, no config or feature change, no database write, no wallet call that
  sends. E-25 wasn't run: the canary can't be delivered until walletd reads results again, and a run
  would only leave test items in production.
- Stopped, as asked: two stale processes of `build` left by earlier sessions, `python3 -m http.server
  8765` (the design-lead prototype, with its `bash -c` wrapper) and `mutis-api --dev` on port 51157
  from `/var/tmp/mutis-ui-run-8qjj6mor` (with its fake sidecar). Both ports are closed; the directory
  was left in place.

## What to watch

- `journalctl -u walletd`: "Failed to deserialize response" and "Insufficient funds … Available: 0"
  stop after the upgrade. Until then each continues every 5 s and on each send.
- `walletd-rpc.py call transactions.get_all`: the `Pending` count goes to 0, or only the aged-out ones
  are left (then see point 1 above).
- `/status.json`: `canary` red until a delivery is verified; `sponsor_balance` amber while the sponsor
  reads 0; `budget.decoy.reserved.50` clears at 00:00 UTC when the slices start again;
  `budget.sponsor.evidence.90` is from the day's E2E runs.
- Tari releases (`gh api repos/tari-project/tari-ootle/releases`): this one went live on the public
  indexers within minutes of publication, with no notice we saw. Mainnet is planned for 2026-11-11.
