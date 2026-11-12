<!-- SPDX-License-Identifier: MIT -->
# Every gate at the release head (2026-11-12)

mvp/november with launch/mainnet merged, Ootle 0.53.2 and the cut-over, on the server as `build` (Python 3.13, Node 20,
Chromium, caddy).

| File | What |
|---|---|
| `server-deploy-313.txt` | the server's and deploy's unit tests: 580 and 206, OK. The deploy tests include CaddyOrder, the route order adapted by the server's caddy |
| `app-core.txt` | lint, vectors, KATs in Node 20 (205/205) and headless Chromium, no-WebAssembly, the sidecar on ootle-wasm 0.53.2 (26/26), PoW and scan benches, the contract run: ALL PASS (9 steps) |
| `site.txt` | 48 of 48 at `aba5ff5`; the home at 60.0 KB of HTML, CSS and JS (gzip), inside its budget |
| `ui-all.txt` | every flow: UI PASS 1412/1412 |

The cut-over rehearsal and the chain scenarios on Ootle 0.53.2 are in `../cutover-rehearsal/`.
