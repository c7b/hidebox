<!-- SPDX-License-Identifier: MIT -->
# End-to-end tests (spec §17)

Python standard library only. The orchestrator runs on the jarvis box (or as `lcam` on ultron with
`--local`); the browser is headless Chromium 154 on ultron, run as the unprivileged `build` user by
`relay.py`, which pumps the DevTools pipe over the ssh connection. That split keeps admin steps
(takedown, tamper, freeze, canary-now) and the outside log checks in one place without ever giving
`build` sudo. Every actor gets a fresh browser context; phones are emulated at 390×844 (iPhone-class)
and 412×915 (Android-class) with touch, a mobile user agent and 4× CPU throttling; desktop is
1440×900 (12-integration §1). Real-device sessions remain an owner check after delivery.

```sh
python3 -I tests/e2e/run.py --list                     # what would run
python3 -I tests/e2e/run.py                            # every scenario without chain transactions
python3 -I tests/e2e/run.py --chain                    # plus E-09…E-14, E-25 and E-J on Esmeralda
python3 -I tests/e2e/run.py --only E-01,E-15 --out /tmp/e2e
python3 -I tests/e2e/run.py --chain --final            # submission day: a SKIP fails the run (D-08)
python3 -I tests/e2e/griefer.py --then-judge https://srv2052606.hstgr.cloud   # E-23
python3 -I tests/e2e/griefer.py --slow-only           # just the slow-upload check (a minute)
```

Screenshots (`<id>-NN-<step>.png`, plus `<id>-failure-*.png`) and `report.json` go to `--out`. While
the holding page is live (no drop widget on `/`), browser scenarios report SKIP, and the run says
"PASS (with skips)"; `--final` turns every skip into a failure.

Against production (there is no staging; 12-integration §7.7):

- **When:** before the go-live database reset (deploy/README.md, "Turning the app on"). Scenarios
  don't take down their own items (only E-17's reported link and drop); a later run leaves them on
  the home page's wall until they leave by their rule, unless taken down
  (`sudo mutis-admin takedown item -- <id>`; a taken-down item leaves the wall at once).
- **Packs:** E-13 and E-J buy a real 2 GiB pack for 30 days and end it as their last step
  (`sudo mutis-admin release-pack -- <locker id>`). Paid space is capped at 40 % of the pool, so test
  packs left running would make `/upgrade` answer "sold out" for everyone, judges included.
- **Pace:** every browser runs on ultron, so all actors share one network, and the API allows 5 new
  lockers and 5 new drops per network an hour. A full `--chain` run makes about a dozen lockers: run
  it in batches an hour apart (`--only E-01,…`), or a later scenario fails with `rate_limited`.
- **E-05** needs the short expiry preset: set `e2e_expiry_s = 60` (top level) in
  `/etc/mutis/mutis.toml`, restart mutis-api, run E-05, then remove the line and restart again. Without
  it E-05 reports SKIP (so `--final` fails), and production never offers the preset.
- **E-J** follows `/judges` step by step (14-ghost-design §9): four steps on a computer and a phone
  (the computer drops a file, the phone opens the link and reloads to "It's gone. It said bye.", then
  the secret the release burned in advance shows its goodbye already checked on chain: it needs
  `judge_demo_gone`, from `deploy/scripts/demo-gone.py burn`), then six for the Tari part with the
  locker on the computer (its drop link made first, Later for the key) and the phone carrying things
  by its codes (the address code opens the phone's home with the address filled in; the drop code
  opens the drop page), See what came, See what a view key sees, Get more room. The phone is 390×844
  and the computer 1440×900; each step is timed (`report.json`, `notes` of E-J); both tracks together
  must take at most 6 minutes.
- **E-J in direct mode** (12-integration §7.5, before `send_mode = "direct"` goes public): with
  `send_mode = "direct"`, `features.direct_send` and `features.sponsor` on, E-J makes a judge pass
  (`mutis-admin judge-pass new --uses 3`) and gives it to both of its browser contexts, which share
  ultron's /64 like two judges in one office. It records the **cold start** (from the locker opening
  to the sponsor grant being spendable in the browser wallet; it must be there within 3:15, spec
  §18.2's step 5) and checks that B6's payment was built and submitted by the browser itself.
  **E-13** in direct mode takes a one-use pass the same way: its buyer's locker gets the sponsor grant
  it pays from, even after that network's two grants a day are spent.

| File | What |
|---|---|
| `cdp.py` | the DevTools client: contexts, device emulation, clicks (pointer or touch), typing, file inputs, downloads, screenshots, screencast recording (the film), the accessibility tree, request and CSP-violation capture |
| `relay.py` | starts Chromium with `--remote-debugging-pipe` as build and relays the pipe |
| `harness.py` | environment, scenario registry, admin steps, fixtures, E-03 secret search |
| `flows.py` | UI steps, written only against the §3.4.9 `data-testid` contract |
| `scenarios.py`, `scenarios_chain.py` | the §17.2 scenarios and E-J (the `/judges` script) |
| `apiclient.py` | a browserless API client with real proofs of work and synthetic ciphertext |
| `test_headers.py` | D-01: HTTPS, exact headers, CSPs and caching per route, error pages through every route, HTTP→HTTPS 308 without a Server header, certificate, redirect hosts; `--local` runs it on the throwaway stack with a full build |
| `test_privileges.py` | D-03, D-11: `deploy/scripts/privilege-check.sh` as root, and a port check from outside |
| `test_logs.py` | D-02: a scripted session over IPv6 and IPv4, forced 502s, then a root search of every log and of walletd's database and backups for its values; `--walletd-probe` makes one relay-shaped send through walletd and searches for its destination and memo |
| `test_fonts.py` | 11-brand P-18: every served WOFF2 loads in Chromium without an OTS error |
| `test_harness.py` | self-test of the driver against a small page on ultron (run it after changing `cdp.py`) |
| `smoke.py`, `headers_spec.py` | the deploy smoke test; the §14.2 header text, verbatim |
| `localstack.py` | a throwaway `mutis-api --dev` behind the production Caddyfile, on the server as build, on its own loopback ports; never production |
| `griefer.py` | E-23 on the local stack: forged `X-Real-IP` values straight to the API, slow uploads through Caddy; then E-J against the real site |

Scenario notes. E-03 has no session of its own: E-01, E-02, E-05, E-08, E-09, E-10 and E-12 register
what must never leave the browser (the link key, plaintext, file names, the password, the key file,
the view key) and every request they made is searched for it, raw and in hex and base64. E-21 runs
D-01 and D-03; D-02 is `test_logs.py` because it stops the API once. E-16's freeze and lane parts
(`E-16s`) change server limits and run only with `--staging`. E-23 (`griefer.py`) never runs against
production: it has its own stack. E-11's "other wallet" is a key pair the release's sidecar makes
(walletd 0.45 can't export a view key): the sidecar reads the output's memo with the view key alone,
and a fresh phone opens that `/t#4` link with it (that last step needs the `t-viewkey` and
`t-viewkey-submit` test ids from the app). Safety codes are compared as their 12 emoji, one grapheme
each (12-integration §2).

The film (`tools/film.py`) drives the same harness with a desktop and a phone, records both with CDP
screencasts and composes on the server with ffmpeg; `--demo` runs only the pipeline.
