<!-- SPDX-License-Identifier: MIT -->
# Round two of the November MVP: evidence (2026-11-09)

What [docs/mvp-november-2.md](../../../mvp-november-2.md) built, as the suites ran it. On the server as `build` (Python
3.13, Node 20, Chromium) unless the file says the workstation.

| File | What |
|---|---|
| `suites/ui-shop.txt` | `web/app/ui/tests/run.py --only shop`: the shop flow with the market: Public keeps the key, a visitor at the address asks, the owner's open drive answers (125 sealed bytes), Go to pay is the pay link, test money, open; `/market` as served and in the browser, search, the link to come back on another device |
| `suites/e2e-s3-contract.txt` | the workstation: the app's contract suite (`node-run.mjs --api`) against `mutis-api --dev --s3`, the real API with blobs in the local S3 stand-in, and what moved to the store |
| `suites/ui-all.txt` | `web/app/ui/tests/run.py`, every flow: UI PASS 1399/1399 (tree at `20bf4db`) |
| `suites/app-core.txt` | `web/app/tests/run_all.py`: lint, vectors, KATs in Node 20 and headless Chromium, no-WebAssembly, the sidecar, PoW and scan benches, the contract run: ALL PASS (9 steps) |
| `suites/site.txt` | `web/site/tests/run.py` at `f21bb0d`: 48 of 48, the home at 60.0 KB of HTML, CSS and JS (gzip), inside its 60 KB budget once the old pack variables and some comments went |
| `suites/server-deploy-313.txt` | the server's and deploy's unit tests under the server's Python 3.13, as `deploy.sh` runs them |

