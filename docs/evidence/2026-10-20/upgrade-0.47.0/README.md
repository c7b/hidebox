<!-- SPDX-License-Identifier: MIT -->
# Upgrade to Tari Ootle v0.47.0, 2026-10-20

Esmeralda's indexers moved to tari-ootle v0.47.0 at about 05:12 UTC (the release itself was published at
05:43). `GET /substates/{id}` changed shape (`state.up.substate` where it was `substate`), so walletd 0.46.0
and our own code stopped reading substates. This folder is the outage and the upgrade drill
(`deploy/ootle/upgrade-drill.md`) as it ran, with the code fix and its deploy. Times are UTC. Nothing here is
a secret: no key, no judge pass, no link with its key; hashes are cut where the full value isn't the point.

## Result

| What | State |
|---|---|
| walletd | **0.47.0** live since 07:19:23 (`919579e6…ba52`, four sources agree, the tag's signature verified); 0.46.0 kept beside it and in `/var/backups/mutis`; store migrated (two additive migrations); balances unchanged; anchored on its first validator set (epoch 12506) and walking the handovers |
| The sandbox | `walletd.service` unchanged: 0.47.0 ran under every one of its directives on the drill's copy first, then live. Nothing loosened |
| Config | unchanged: nothing walletd 0.47.0 removed is in it, and its indexer list is still the key `indexer_api_url`, already naming both indexers (there is no `indexer_urls`) |
| Checkpoints | #777 to #789 failed before submitting (05:21 to 07:21, nothing stuck in walletd); **#790 committed at 07:26:54** (chain index 776); #791, #792 since |
| Notarizations | **`bfd72c8` at 07:22:20** (deployed at 07:05 during the outage, its notarization had failed), `d3bc449` at 07:29:59 (another lane's deploy), `e6d5f7c` at 07:56:32 (this fix) |
| Credits | frozen at 05:38:15 by a reconcile that read every credited output as missing; **unfrozen at 07:56:46**, after the fixed worker's first reconcile came back `ok` (07:56:38) |
| Paid during the outage | nothing: no invoice, claim or payment between 05:00 and the fix, so nothing to credit late and no claim or invoice ran out because of it (`credits.txt`) |
| First credits after the fix | E-13's pack payment (0.5 tTARI, paid from the browser's own wallet) credited at 08:00:05; E-29's test money counted for its claim at 08:01:06 |
| Code | deployed as `e6d5f7c` (release `e6d5f7c4ed0c…-cf89bbb79`): both shapes read everywhere, a proven down is never a credit, an unknown shape is `unknown` (no freeze), the walletd client renews a refused token once |
| ootle-wasm | unchanged (0.46.0, `2856d86b…93f2`): the sidecar never reads an indexer answer; the real-sidecar test and its selftest pass, and E-13's browser-built payment committed on the 0.47.0 network |
| `/status.json` | red (credits) at 07:28; **green** at 08:02 |

## Files

| File | What |
|---|---|
| `release-notes.txt` | v0.46.1 and v0.47.0, what touches us: the substate shape (#2968), verified reads, the config, the store, #2978, #2987, #2960 |
| `checksums.txt` | walletd: GitHub's digest, the `.sha256`, the release's list, the bytes on the server, the signed tag; what is installed |
| `drill-log.txt` | §3 on a copy under the production sandbox with no network, §4 live, balances, rollback |
| `walletd.txt` | walletd's journal when the indexers moved and after the upgrade (the refused JWT), its validator set |
| `chain.txt` | the chain worker's timeline, the first checkpoint and the notarizations |
| `credits.txt` | the freeze, what was paid during the outage (nothing), the checks before unfreezing |
| `status/` | `/status.json` after walletd (07:28, red: credits) and after the deploy and unfreeze (08:02, green) |
| `suites/` | the suites on the server as `build`, from a `git archive` of the branch (`scripts/suites.sh`; exit codes in `done`) |
| `e2e/` | E-13, E-25 and E-29 against production after the deploy |
| `headers.txt` | `tests/e2e/test_headers.py --origin https://hidebox.app` after the deploy |
| `scripts/` | `drill.sh` (§3), `swap.sh` (§4), `wsum.py` (read-only walletd summary), `check-credited.py` (read-only), `suites.sh` |

## What was done, in order

1. **The outage, read** (07:10 to 07:16): walletd's journal (`Failed to deserialize response` from 05:13), the
   chain worker's (checkpoints failing from 05:21, the freeze at 05:38), the database read-only (nothing paid
   since 05:00), and both indexers' answers recorded: a live output, a spent one (404 unversioned, a proven
   down at its version) and the SealLog component, byte for byte the same on both. The release notes and the
   pull requests behind them read as data (`release-notes.txt`).
2. **walletd 0.47.0** downloaded on the server into a new directory and checked (`checksums.txt`), put at
   `/opt/tari/bin/tari_ootle_walletd-0.47.0-9dabb2a`.
3. **Drill §3** (07:17:42): on a copy, with no network, under every directive of `walletd.service`. Two
   additive migrations, the same balances as the live wallet, nothing denied by the sandbox. The exit trap
   didn't delete the copy (a line this run added; `drill-log.txt`); it was deleted by hand 23 s later.
4. **Drill §4** (07:19:21): balances, stop, a cold tar of the wallet, the replaced binary copied to
   `/var/backups/mutis`, 0.47.0 installed, start (down 1 s); balances equal; anchored at epoch 12506.
5. **Notarized** the release deployed during the outage (07:22:20). **Checkpoint #790** committed at 07:26:54
   after `mutis-admin seal-now` (#789 failed on the worker's stale token: `walletd.txt`).
6. **The code** (branch `chain/ootle-0.47`, pushed to `main` as `1085c9c` and `e6d5f7c`): both shapes read in
   the worker, the API, the browser, `verify-deploy` and `wasm_check`; an unknown shape is `unknown`; the
   walletd client renews a refused token; recorded answers as fixtures and test vectors; the drill and its
   deploy test; the self-hosting guide. Suites on the server as `build` (`suites/`).
7. **Deploy** of `e6d5f7c` (07:54 to 07:56): the gate, build, activation (the sidecar's handshake and selftest
   with the pinned 0.46.0 wasm), the chain worker restarted, smoke, notarization. The first try of `1085c9c`
   stopped at the gate: a new deploy test loaded `template/`, which the gate doesn't copy (fixed in
   `e6d5f7c`); one more try stopped on one error in the server suite that no later run repeated (seven
   runs, on the server under load and here).
8. **Unfrozen** credits at 07:56:46, after the new worker's first reconcile came back `ok`.
9. **Checks**: `tools/verify-deploy.py https://hidebox.app e6d5f7c` 0 differences across 217 files, the
   SealLog template check included ("the chain runs seal_log.wasm byte for byte"); `test_headers.py` 81
   PASS, 0 FAIL (`headers.txt`); `/releases.json` lists `e6d5f7c`; E-13, E-25 and E-29 pass (`e2e/`).

## Suites

On the server as `build`, from a `git archive` of `1085c9c` (`e6d5f7c` adds only a skip to one deploy
test, run in the deploy's gate): the real sidecar 4 tests OK (pinned wasm `2856d86b…`, selftest 17
cases), server 355 OK (5 opt-in skips), deploy 100 OK, lint PASS, copy PASS, core ALL PASS in 9 steps
(KATs 153/153 under Node 20 and in Chromium, jitless 87/87, sidecar 20/20, contract 12/12), site 44 of 44,
UI 958 of 959: `share-rules` waited 20 s for its share dialog while four UI suites ran on the server at
once (load 11 to 13); run again alone it passes 27 of 27 (`suites/ui-share-rules.log`). It doesn't touch
the chain code. E2E against production after the deploy: E-13, E-25, E-29 PASS. E-14 (forged payment) was
not run against production: its admin helper leaves a forged `pending_check` row that keeps `credits`
amber; `test_admin.test_e2e_forged_payment_is_never_credited` and `test_payments` cover it in the server
suite, in both answer shapes.

## What remains for the owner

1. **The old locks.** 0.47.0 changes nothing for the 21 transactions of 2026-10-13 that stay `Pending`, or for
   the sponsor's change `3ee453ab…` (8,851.452 tTARI) that walletd holds `LockedUnconfirmed`
   (`../../2026-10-13/upgrade-0.46.0/`). The sponsor spends its newer output meanwhile (348.30 tTARI).
2. **First-use trust.** walletd 0.47.0 took its indexer's word for its first validator set (anchor
   `FirstUse`, epoch 12506) and verifies everything after it by the handovers. Tari's own design; noted
   because before 0.47.0 walletd trusted the indexer for everything.
3. **`service`'s public tTARI**: 13.75 tTARI at 07:59, about 26 days of checkpoints at 15 minutes.
4. **Backups with keys**: `/var/backups/mutis/wallet-20261020T071921Z-pre-upgrade.tar` (293 MB, root 0600).
5. **ootle-wasm 0.47.0** is published; nothing here needs it (stealth outputs are unchanged by #2978, and a
   browser-built payment committed). Vendoring it is the drill's §1 and §5 when wanted.
6. The tag is not moved.
