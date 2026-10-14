<!-- SPDX-License-Identifier: MIT -->
# M1: the drive in production (integration pass 1, 2026-10-14 UTC)

Research 16-drive-design §15, milestone M1: the drive (folders, every rule but Pay, Delete it after,
Activity, Received, Storage) with `features.pay_to_open` off.

| What | Where |
|---|---|
| Config | `features.folders = true` in `/etc/mutis/mutis.toml` (copy of the file before it: `/var/backups/mutis/mutis.toml.20261014T014952Z.before-folders`, root 0600). `e2e_expiry_s = 60` was set for batch A only (01:55Z) and removed right after (02:08Z), `mutis-api` restarted each time; `/api/v1/config` checked. |
| Releases | `deploy/deploy-1.log`: `2510bc6` (the drive, the home, the 301s). `deploy-2.log`: `8b170ef` (the folder viewer names a file moved out mid-visit, E-28). `deploy-3.log`: `e74d529` (a drive asks for its sponsor grant in direct mode, E-13 and E-J); live now: `e74d52989a8bc2808fcb7a0ecb6e4e1e46795591-ceb2bf1e8`. Each: the deploy gate (server, deploy tests, lint, copy check on the server), smoke, notarized manifest. |
| verify-deploy, D-01 | `deploy/verify-*.log`: 0 differences across 156 files for each release; `deploy/d01-*.log`: `tests/e2e/test_headers.py` PASS for each. `/status.json` green throughout, `sponsor_balance` green. |
| E2E without chain | `e2e/batch-A.log` (17 of 17 PASS, with E-05's preset): E-01, E-02, E-03, E-04, E-05, E-06, E-07, E-08 (the drive), E-15 to E-21, E-26, E-27. `e2e/batch-B.log`: E-22, E-24, E-31 PASS; E-28 failed on the banner's code (a 403 shown as `internal`), fixed in `8b170ef`, then PASS in `batch-C1.log`. |
| E2E with chain | `batch-C1.log`: E-09, E-10, E-12 PASS through the drive's Received and Settings. `batch-C2.log`: E-11, E-25 PASS; E-13 and E-J failed waiting for the drive's sponsor grant (the drive never asked for one; fixed in `e74d529`). `batch-C3.log`: both failed again (the test waited before opening the pack dialog; E-J's phone send timed out); test fix `ac43421`. `batch-C4.log`: E-J PASS, both tracks in 1.4 minutes. `batch-C5.log`: E-13 PASS (quota +2 GiB, pack released). E-14 not run: its forged payment row is a staging-only admin write, and chain ownership is tested only on the fake chain (bug-hunt rule; the server part is `server/tests/test_receiver_ownership.py`). |
| Purge | `e2e/purge.txt`: 30 test items and 7 drops taken down by id from a read-only diff against a snapshot taken before the first deploy; canary items kept; 20 judge passes, the security drop and the older lockers intact. |
| Pace | Each drive scenario makes a new identity (5 per network an hour): the batches ran apart or after a restart the config change needed. |
