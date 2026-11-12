<!-- SPDX-License-Identifier: MIT -->
# The cut-over rehearsal (2026-11-12)

[docs/cutover.md](../../../cutover.md) run end to end on three hostnames beside production, with two instances of this
release on Esmeralda. cut.hidebox.app played hidebox.app, cut-testnet.hidebox.app played testnet.hidebox.app and
cut-mainnet.hidebox.app played mainnet.hidebox.app.
- **`cutt`, the testnet's role**: production's shape (no staging, judge passes, pay links), at cut.hidebox.app before
  the switch and cut-testnet.hidebox.app after it.
- **`mvp`, the mainnet's role**: at cut-mainnet.hidebox.app before and cut.hidebox.app after.

The October code itself can't run as an instance (main has no instance support), so the testnet's role ran this
release. tests/e2e/cutover.py's helpers are byte-identical to the October tree's, which ran them against production.
With `--unmark`, the drive's record lost its network mark before the switch, as the October app writes none.

| File | What |
|---|---|
| `cutover-run.txt` | `tests/e2e/cutover.py --unmark`, with `deploy/scripts/cutover.py switch` and both rebuilds as its `--switch`. The result: **19 of 19**. Before the switch, test links were made on the host: a text secret, a drive file link, a pay link, a drop link and a judge pass. After it, on the same host, all of these held: each link went to the testnet with its path and key and opened there; the judge pass was saved on the testnet's /judges; `/verify#<share>` followed; the drive got the handover screen, its key file held the key and no address, and the file opened the same drive with its file on the testnet; a link made after the switch stayed on the host; the old mainnet host answered 308, path and query kept, on both ports. The switch took 383 s with both rebuilds; the Caddy part is one reload |
| `cutover-run-first.txt` | the first full run: 13 of 15. Two failures, neither in the cut-over: a check that wanted the `#key` still in the address bar after the viewer cleared it, and the handover missing because the testnet's role marks its drives (`--unmark` since) |
| `rollback.txt` | `cutover.py rollback` and `rollback.sh` on each instance, between the two runs: every host back as it was before |
| `e2e-chain-0.53.2.txt` | after the switch, the chain scenarios against Esmeralda's 0.53.2 validators with this release's ootle-wasm 0.53.2: E-10, E-12, E-13, E-29, E-30 (the browser builds and signs the payment) and E-J pass; E-01 and E-08 on both hosts |
| `production-frozen-set-drill.txt` | `legacy-ids.py export` from production's own database, read-only, into a scratch folder: 1,038 shares, 21 pay links, 76 drops, 3,645 transactions; the security drop, the newest canaries and two pay links found by name |

Found and fixed on the way:
- **Shop pages**: the Referrer-Policy header was sent twice (the 2026-11-10 rehearsal; already fixed).
- **D-01 on the testnet's host**: Caddy's adapter sorts handle blocks with a path matcher by the path's length. On a
  non-staging instance that put the plain-name media route ahead of the fingerprinted one, so pictures were kept a day
  instead of a year. The mainnet instance has that shape from its flip until the cut-over. `/app/`, `/shared/fonts/`
  and `/site/media/` now match by regexp, and `deploy/tests/test_instance.py` CaddyOrder adapts the real config with
  caddy. It fails on the old matchers and passes on the new ones.
- **The handover's first draft** stopped "Delete my drive" from erasing a drive's links and purchases. The Node test
  for that caught it, and the store is cleared again, keeping only a drive set aside from another network.

Torn down the same day: every `mutis-cutt-*` and `mutis-mvp-*` unit, timer and mount stopped and disabled, and both
Caddy sites moved out of `/etc/caddy/mutis.d` after the configuration validated without them. Production and the
mainnet instance stayed up throughout.
