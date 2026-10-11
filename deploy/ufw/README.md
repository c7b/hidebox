<!-- SPDX-License-Identifier: MIT -->
# Firewall (ufw) on the server

`deploy/scripts/provision.sh` sets and checks all of this; the table is what it leaves in place.

| Rule | Why |
|---|---|
| `limit 22/tcp` (IPv4 and IPv6) | SSH, rate-limited: more than 6 new connections in 30 s from one address are dropped, so every tool here uses one multiplexed connection (`ControlMaster`) |
| `allow 80/tcp`, `allow 443/tcp` | Caddy: HTTPS, and HTTP only for the redirect and Let's Encrypt |
| `ufw logging off` | blocked packets would otherwise be logged with their source IP (spec §14.3) |
| owner-match guard on `lo` port **5100** | walletd runs with `--authentication none`: only uids 0 (root), 1000 (operator) and 1002 (drive) may connect; `mutis`, `build`, `caddy` and everyone else get a TCP reset |
| owner-match guard on `lo` port **18143** | the L1 console wallet's gRPC has no authentication either; same three uids |
| owner-match guard on `lo` port **8787** | mutis-api believes `X-Real-IP` from loopback (Caddy sets it): only `caddy`, `drive` (the sidecar uploads the hourly canary), root and operator may connect. `build` runs third-party build scripts when it compiles crates, and could otherwise claim any client address and walk past every per-IP limit and the PoW escalation |

The guards live in `/etc/ufw/before.rules` and `before6.rules`, before the loopback `ACCEPT`:

```
-A ufw-before-output -o lo -p tcp --dport 5100 -m owner --uid-owner 0    -j ACCEPT
-A ufw-before-output -o lo -p tcp --dport 5100 -m owner --uid-owner 1000 -j ACCEPT
-A ufw-before-output -o lo -p tcp --dport 5100 -m owner --uid-owner 1002 -j ACCEPT
-A ufw-before-output -o lo -p tcp --dport 5100 -j REJECT --reject-with tcp-reset
```

The 5100 lines date from the research phase (backups `*.bak-walletguard`). provision.sh adds the
same lines for 18143 and for 8787 (with the caddy uid as a fourth) after the 5100 block (backups
`*.bak-mutis`) and reloads ufw.

Everything else that listens is on loopback only: Caddy's admin API on a socket in `/run/caddy`
(0700, caddy only; no TCP port) and systemd-resolved. The griefer (E-23) never needs 8787: it runs
against a throwaway `mutis-api --dev` on its own port (tests/e2e/localstack.py).

Check it: `sudo bash deploy/scripts/privilege-check.sh` on the server (while the API is off it puts a
stand-in listener on 8787 so the guard itself is tested), and from outside
`python3 -I tests/e2e/test_privileges.py`, which also confirms that 5100, 8787, 18143, 2019, 9000
and 9100 don't answer on the public IPv4 and IPv6 addresses.
