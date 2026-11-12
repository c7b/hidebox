<!-- SPDX-License-Identifier: MIT -->
# The November MVP, ready for the mainnet deploy: evidence (2026-11-10)

The owner's decisions of 2026-11-10 (storage on our disk, capped at 20 GiB; pack revenue on our receiving key; the
`gone` rule; the tombstone and testnet lines), the security pass merged, and every gate run again. On the server as
`build` (Python 3.13, Node 20, Chromium) unless the file says otherwise.

| File | What |
|---|---|
| `suites/server-deploy-313.txt` | the server's and deploy's unit tests under the server's Python 3.13 at `cd75cd9`: 577 and 177, OK |
| `suites/app-core.txt` | `web/app/tests/run_all.py`: lint, vectors, KATs in Node 20 and headless Chromium, no-WebAssembly, the sidecar (26/26), PoW and scan benches, the contract run: ALL PASS (9 steps) |
| `suites/site.txt` | `web/site/tests/run.py`: 48 of 48; the home at 60.0 KB of HTML, CSS and JS (gzip), inside its 60 KB budget |
| `suites/ui-all.txt` | `web/app/ui/tests/run.py`, every flow: 1411 of 1412. The one failure was the check of a link that isn't here, which still read the old tombstone sentence ("for 30 days") |
| `suites/ui-rerun.txt` | that flow at `01ba912`, with the check reading "for at least 30 days": UI PASS 34/34 |
| `rehearsal/e2e.txt` | the E2E suite against a rehearsal of this tree, below |

## The rehearsal

An instance `mvp` beside production (`deploy/scripts/provision-instance.sh`): its own users, database, API port, Esmeralda
walletd (0.52.0) and Caddy site, at `https://mvp-rehearsal.hidebox.app`, staging. Its config was the instance template
(the mainnet beta's shape) with test money on, so the chain scenarios could pay:
- demo payments, sponsor grants and judge passes;
- the testnet's pack catalog, since E-13 and E-J buy `s30`;
- `e2e_expiry_s = 60` for E-05;
- the server's own addresses in `brakes.exempt_addresses`.

Its sponsor got 50 tTARI from the staging instance's Esmeralda `rehearsal` account (tx `fd43c544…07d0`), because the
Esmeralda faucet was empty. Nothing else of production or the mainnet instance was used.

Every scenario passed: E-01 to E-31 and E-J, with E-05 and E-16s, and the chain ones on Esmeralda. The one exception is
D-03, the second half of E-21, which reads production's own users and units and so skips on an instance by design.

What the first pass found, and what changed:
- **E-21 (D-01).** `/shop/<id>` sent `Referrer-Policy` twice: once from Caddy's `security_headers`, once from the API's
  page. On a staging instance it also sent `X-Robots-Tag` twice.
  - The Caddyfile now drops the API's `Referrer-Policy` on the shop and market pages.
  - A staging instance's noindex is now a deferred set (Caddy 2.6's block `defer`; the `>` prefix came later), so it
    replaces the API's header instead of adding a second one.
  - D-01 now checks `/sitemap-shops.xml` as a file crawlers read (kept an hour), not as a page.
- **E-16s.** It waited for the code `uploads_frozen`. The widget names an operator's freeze of everything
  `uploads_frozen_all`.
- **E-11 and E-31.** They skipped on an instance. They now use the instance's own sidecar, database and backups, as its
  own users, like E-06.
- **E-30.** In relay mode, the mainnet's, the pay page offers no Pay from my drive, so it now skips there. It passes in
  direct mode. With `features.away_release` on, the page may open before the seller's drive does; the drive's own check
  must still say Yours to spend.

Then the rehearsal ran on `/etc/mutis-NAME/mutis.toml` as the Nov 22 deploy sets it (the template untouched):
- test money off; market, shop, withdraw, away release, packs and pay to open on;
- packs `p2` (+2 GiB, 50 TARI) and `p5` (+5 GiB, 100 TARI), 30 days;
- the free share 1 GiB and the paid cap 8 GiB (40 % of the 20 GiB pool);
- `disk_free_bytes` reported as the reserve plus the cap's room left, not the disk's own free space. After the code
  review below, `/stats` reports the cap itself as the total and the room left in it as free;
- `chain_ok`.

`/market`, `/api/v1/market` and `/sitemap-shops.xml` answered. The sitemap is empty on staging, by design.

Torn down the same day: every `mutis-mvp-*` unit, timer and mount stopped and disabled, and its Caddy site moved out of
`/etc/caddy/mutis.d` after the configuration validated without it. Production and the mainnet instance stayed up
throughout.

An independent review of the `gone` fix and the disk cap (code-critic) found no blocking issue and the server suite
green (577). Its nits are fixed in `897a68f`: a down state without its verified proof now has its own test, the wording
says proof everywhere, `/stats` counts our share of the disk, and a cap lowered below what is stored freezes every
upload (tested). The server suite is now 580, OK.

Not run here:
- `tests/e2e/test_harness.py` on the workstation fails one check ("a judge pass is in the tab's sessionStorage before the
  page's scripts run") on the tree before these changes too.
- The deploy's own acceptance on Nov 22 is the E2E suite on the live mainnet instance, without chain transactions, E-05
  or E-16s ([docs/mvp-november-2.md](../../../mvp-november-2.md)).
