<!-- SPDX-License-Identifier: MIT -->
# Moving hidebox.app to the mainnet (the cut-over)

hidebox.app has served the October contest entry on the Esmeralda testnet since 2026-10-18. With the November MVP it
serves the Ootle mainnet instead, and the October entry keeps running, unchanged, at testnet.hidebox.app for the judges.
The owner decided it on 2026-11-11; this page is how, and how to undo it.

| Host | Before | After |
|---|---|---|
| hidebox.app, www.hidebox.app | production: the October entry (Esmeralda) | the mainnet instance (the MVP); www answers 308 to the apex, as before |
| testnet.hidebox.app | none | production, the same code (only its host and origin change) |
| mainnet.hidebox.app | the mainnet instance | 308 to hidebox.app with the same path and query (the t/521 links) |

## What keeps working, and how

- **Links the testnet made on hidebox.app** (shares `/s/`, pay links `/p/`, drops `/d/` with the security drop,
  `/verify/tx/` of our own transactions, the canaries' links): at the move, `deploy/scripts/legacy-ids.py export` writes
  the frozen set of the testnet's ids, one empty file each, under `/srv/mutis-NAME/legacy`. The mainnet instance's
  config names the testnet (`legacy_origin`), and its Caddy site (`deploy/scripts/instance.py`) answers exactly those
  paths with a 308 there, the query with them; a browser keeps the `#fragment`, where the key is, across a redirect.
  Export only adds, and runs again after the switch for what was made in between. Mainnet ids are random 128-bit
  (drops: 50-bit) values, so a mainnet link never falls in the set.
- **Links that carry their id in the fragment**: a judge pass (`/judges#pass=…`) goes to the testnet's `/judges`;
  `/verify#<share id>` and a delivery (`/t#…`) whose share is in the set go there too (`web/app/lib/legacy.js` asks
  with a same-origin HEAD that stops at the redirect). A delivery sealed for the drive set aside (next point) shows the
  handover; any other delivery that doesn't open here offers "Open it at testnet.hidebox.app".
- **A drive saved in the browser on hidebox.app**: its record carries no network mark (the October code wrote none;
  this release writes `net`). On a host with `legacy_origin` the app sets such a record aside whole, never opens it as
  a mainnet drive and never deletes it, and the drive's start screen says it moved: Save its key file, then Open
  testnet.hidebox.app and use the file there (the October app restores from any key file). The key leaves the browser
  only as a file on the device. Make my drive then makes a new, separate mainnet drive.
- **Caches**: no service worker exists in either version, every page revalidates (`Cache-Control: no-cache`) and assets
  have hashed names, so no testnet page survives the switch in a browser cache.
- **releases.json, status.json, SealLog**: each instance serves its own. hidebox.app shows the mainnet's; the October
  ones are at testnet.hidebox.app.
- **The owner's and the robot's lockers**: the robot's keys are on the server, untouched; the owner's drive in his
  browser gets the handover above. The owner's real `/s/` and `/p/` links are never opened: `legacy-ids.py check`
  answers from the set's names.

## Before (days or hours ahead)

1. testnet.hidebox.app resolves to the server (A and AAAA).
2. The release is on the mainnet instance and passed its acceptance (docs/mvp-november-2.md).
3. The mainnet database holds no drive but ours (`sqlite3 … "SELECT COUNT(*) FROM identities"` against the list of
   ours). Drives made on mainnet.hidebox.app stay in that origin's storage, so keep the gap since the flip short.
4. A certificate for testnet.hidebox.app: a temporary site, `/etc/caddy/mutis.d/cutover-preissue.caddy`
   (`testnet.hidebox.app { header -Server; redir https://hidebox.app{uri} 302 }`), validated, one reload. The switch
   leaves it out.
5. A worktree of the October code (the commit production runs) for its redeploy.

## The switch (one Caddy reload)

`deploy/scripts/cutover.py` runs steps 1 to 7, as root from a copy of the release's `deploy/`; with `--check` it
stops after step 5, nothing installed. Run that first.

```sh
sudo python3 -I deploy/scripts/cutover.py switch --host hidebox.app --testnet-host testnet.hidebox.app \
     --old-host mainnet.hidebox.app --mainnet-instance NAME [--check]
sudo python3 -I deploy/scripts/cutover.py rollback --from /var/backups/mutis-cutover-<time>
```

What it does, with `B=/var/backups/mutis-cutover-<time>` (0700):

1. **Keep the old state**: copy `/etc/caddy/mutis.d/*.caddy`, `/etc/mutis/caddy.env`, `/etc/mutis/mutis.toml` and
   `/etc/mutis-NAME/mutis.toml` into `$B`.
2. **The frozen set**: `legacy-ids.py export --db /srv/mutis/data/db/mutis.sqlite3 --out /srv/mutis-NAME/legacy`
   (read-only), then `legacy-ids.py check` on the security drop (`d/3w7m8k2v5t`), the newest canary shares and a
   sample of pay links and drops.
3. **Configs**:
   - `/etc/mutis/mutis.toml`: `public_origin = "https://testnet.hidebox.app"`, that origin added to `memo_origins`
     (the old ones stay, for memos already on the chain), `security_drop_url` on the new host.
   - `/etc/mutis/caddy.env`: `MUTIS_HOST=testnet.hidebox.app`.
   - `/etc/mutis-NAME/mutis.toml`: `public_origin = "https://hidebox.app"`, `memo_origins = ["https://hidebox.app",
     "https://mainnet.hidebox.app"]`, `testnet_origin` and `legacy_origin` = `"https://testnet.hidebox.app"`,
     `redirect_hosts = ["mainnet.hidebox.app"]`.
   - `mutis-admin check-config` and `mutis-admin-NAME check-config`.
4. **The mainnet site**: rendered by the live release's own `instance.py` from the new config. The temporary
   certificate block (`/etc/caddy/mutis.d/cutover-preissue.caddy`) is left out, and moved to `$B` at the install.
5. **Validate everything together**: a copy of `/etc/caddy/mutis.d` with the two new files, production's Caddyfile
   importing that copy, and `MUTIS_HOST=testnet.hidebox.app`: `caddy validate`. Nothing is installed unless it passes.
6. **Install and reload**: the two site files and caddy.env, then `systemctl reload caddy` (systemd reads caddy.env
   again for the reload). If the reload refuses (Caddy keeps the old config), restore `$B` and stop.
7. **Restart** mutis-api and mutis-NAME-api and mutis-NAME-chain (the new origins), then `legacy-ids.py export`
   again for what was made since step 2.
8. **Rebuild each site for its host**: `deploy.sh <release> --instance NAME` (the mainnet site, built for
   hidebox.app; its Caddy site comes out unchanged), then, from the October worktree, `deploy.sh <its commit>`
   (production built for testnet.hidebox.app; its Caddyfile is the same file).

## Checks, logged out

- `https://hidebox.app/api/v1/config`: `network` mainnet, `origin` https://hidebox.app, `legacy_origin` the testnet.
- `https://testnet.hidebox.app/api/v1/config`: esmeralda, origin https://testnet.hidebox.app; its home, `/judges`,
  `/canary`, `/releases.json`; `verify-deploy` on both.
- `https://mainnet.hidebox.app/x?y=1` → 308 `https://hidebox.app/x?y=1`; `www` → hidebox.app.
- Test items made on the testnet before the switch (a share, a folder link, a pay link, a drop) open from
  `hidebox.app/…#key` after it; `/judges#pass=…` lands on the testnet's /judges with the pass; the security drop and
  the canaries by `legacy-ids.py check`; a browser holding a testnet drive gets the handover.
- The E2E suite against both hosts (`tests/e2e/run.py --origin … [--instance NAME]`).

## Rollback

`cutover.py rollback --from $B` puts back the files it kept (the site files, caddy.env, both mutis.toml), reloads
Caddy and restarts the services. If step 8 ran, `deploy/scripts/rollback.sh` (and `--instance NAME`) goes back to
the previous release of each, which was built for the old hosts. The frozen set does nothing while `legacy_origin` is
unset, and a drive set aside stays in the browser either way: the October app reads only `current`, so a browser that
met the mainnet app needs the key file once (the handover offered it).

The rehearsal of 2026-11-12 ran all of this on cut.hidebox.app, cut-testnet.hidebox.app and cut-mainnet.hidebox.app:
docs/evidence/2026-11-12/cutover-rehearsal/.
