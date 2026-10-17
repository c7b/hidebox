<!-- SPDX-License-Identifier: MIT -->
# The judge race: E-J step 3's "Delete it from my drive after" (2026-10-17 UTC)

The seventh pass's E-J with a judge pass failed at step 5: its Once link was made without
`then_delete`, so `minutes.txt` stayed. The production database confirms it: that drive's share was created
`max_views 1`, a week, and the file stayed `kept` with no expiry (the server applies `then_delete` or
refuses it with a 400; it never drops it). The guess was a race with the sponsor grant.

Live and tagged: `61e39c810198644c488e025b70d09d6837cbb8a6`, release `61e39c81…-c2a42c251`. Its manifest
`8c0ea525…` is notarized through SealLog in tx `9f1be213…09fa`. Commits: `992bee2` (the share dialog),
`61e39c8` (judge-pass extend), then `ff9597e` (E-J's diagnostics, tests only) above the tag.

## What was found

- **Not a grant race.** Nothing redraws an open share dialog on a wallet, grant, `/me`, index or toast
  event; the server takes `then_delete` for any kept file of the owner, whatever the class (probation
  included) and whether a grant is pending.
- **Not reproduced on the dev stack**: UI flow `share-then-delete-race` (a judge-pass drive in direct mode,
  CPU 4×, the grant answered 0, 200, 500 and 1500 ms after the dialog opens with the view drawn again then,
  and an index reload between the switch and Make link) passed against the old dialog and the new one, and
  again with ultron's CPU saturated by three busy loops.
- **Seen once more on production, then not.** E-J's new step-3 check failed on the first run after the
  deploy (`e2e/ej-1-judge-pass.log`, `ej-1-step3-switch-off.png`: the switch off right after the press,
  nothing covering it). Six logged probes of the same steps (`e2e/probes/`, two with a judge pass) and the
  E-J rerun (`e2e/ej-2-judge-pass.log`) all had the switch on at once. Both failures were the first browser
  session after a deploy, on ultron, which also runs production (and was shared with the film agent's
  runs); no probe could make it happen on purpose. Cause not established.

Judge-pass drives: four instead of the one allowed (E-J twice, two probes with a pass minted for them,
`--uses 2` and `--uses 1`), because E-J's first run reproduced the failure and the cause had to be looked
at with a pass. None of the judges' 20 passes was used. Their four test passes stay on the server, like
E-J's earlier ones; their codes were never written down.

## What was hardened (`992bee2`)

- The link is built from the dialog's own controls at the click (Once/A few/No limit, It ends, the word,
  the switch), not from a copy of the form.
- `openShare()` builds its state whole before touching the page; an earlier opening still loading steps
  aside; an open dialog is never reset or drawn again by another opening.
- E-J step 3 fails at once, with what the press met, if the switch is off before Make link, and checks the
  result says the file leaves (`992bee2`, `ff9597e`).
- The stray "null" under It ends (Element.append() writes a null child as text): gone there and in four
  other places (the pay step without C35, the sent-by-Tari result without a tx, the invoice without demo
  pay, What our server knows without access). share-once and share-rules search every dialog state they
  reach for a text node that reads null; against the old dialog they fail (`suites/` has the passing run).

## Judge passes (`61e39c8`)

A pass works for 30 days after its `created_at`; the 20 judges' passes (minted 2026-10-11T23:45Z) would have
ended 2026-11-10T23:45Z. New subcommand, with a test (`test_admin.test_judge_pass_extend`):
`ssh ultron 'sudo mutis-admin judge-pass extend --until 2026-12-15' < judge-passes.txt` (the codes on stdin,
never the command line). `checks/judge-pass-extend.txt`: 20 passes, each now valid until
2026-12-16T00:00:00Z (through 2026-12-15 UTC), uses unchanged (99 left in all), none regenerated.

| What | Where |
|---|---|
| Suites (ultron, as build, a tarball of the working tree that became `992bee2` + `61e39c8`) | `suites/`: lint PASS, check-copy PASS, server 331 OK (5 skipped), app `run_all` 9/9, UI 691/691 (A-06d 113,793 B ≤ 131,072). The deploy gate ran server (328 OK on 3.13), deploy, lint and copy again |
| Deploy | `deploy/deploy-61e39c8.log`; `verify-61e39c8.log` and `verify-tag.log`: 0 differences across 159 files, SealLog byte for byte; `d01-61e39c8.log`: D-01 PASS |
| Tag | `checks/tag.txt`: `spooky-secrets-2026-10` → `61e39c8` (tag object `50c37b3`; was `aae9052` on `410f210`) |
| E2E on production | `e2e/ej-1-judge-pass.*`: FAIL at step 3 (the switch off). `e2e/ej-2-judge-pass.*`: E-J with its judge pass PASSED both tracks (track one 10 s, track two 38 s; step 5 Opened, then It left your drive). `e2e/batch.log`: the non-chain batch 12/13. **E-04 failed on the network's daily brake**, not on the code: "Your network has made all the new drives it can today" (`batch-E-04-drives-limited.png`). The four probes without a pass had spent ultron's /64 day of new drives (5, in memory since the deploy's restart); ultron's browser address is not one of `brakes.exempt_addresses`. E-04 can run again after 00:00 UTC or the next restart |
| Purge | `e2e/purge-1.txt`: the 28 items (7 folders, 21 files) of the seven drives that E-J's first run and the probes made, by id. `e2e/purge-2.txt`: the batch's 4 anonymous items and E-20's drop, from a read-only diff against a snapshot taken right before it (no other traffic then). `e2e/survivors.txt`: the security drop active, 47 canaries ready, the held pack kept, no drive removed, judge passes 44 → 48 (E-J's two, the probes' two), and nothing that existed before the deploy changed except a canary that ended by its own expiry. The database was never reset |
