<!-- SPDX-License-Identifier: MIT -->
# hidebox

**Your private drive. Locked here. Shared your way.** A drive on the Tari™ Ootle.

**hidebox** is a drive for your files that opens only with your key, made in your browser: no email,
no password. Files and folder names lock in your browser before upload, and the server stores only
ciphertext. Each file or folder is shared by its own rule (once, a few times, until a time, with a
secret word, as a public link, or to one Tari address), and you always see what happened: how many
times it opened each hour, links that ended, files that left. Tari does the private parts: a file's
key travels to an address inside a stealth payment on the [Tari™ Ootle](https://ootle.tari.com)
testnet, more space is paid in tTARI and checked on the chain, and every file that leaves gets a
receipt in a public log on the Ootle. Pay to open (a buyer pays the owner's address, then the file
opens) is built behind a flag.

The internal codename is **mutis**: it stays in the code, the paths, the services, the CLI and this
repository's address.

- Live: <https://srv2052606.hstgr.cloud> (Esmeralda testnet; tTARI has no monetary value)
- The judges' guide, two tracks of six steps with what each should show: [/judges](https://srv2052606.hstgr.cloud/judges)
- How it works, in five pictures: [/how](https://srv2052606.hstgr.cloud/how) · under the hood (how it was made), who
  sees what and the threat model: [/made](https://srv2052606.hstgr.cloud/made) and
  [docs/threat-model.md](docs/threat-model.md)
- Space is one real disk: packs and free space have daily limits per network, which slow anyone trying
  to take it ([threat model, "Griefing the space"](docs/threat-model.md#griefing-the-space))

Built for the Tari Ootle October 2026 contest, "Spooky Secrets". MIT licensed.

## Try it

1. Open the home page and tap **Make my drive**. Your drive opens; its key was made in this browser.
2. On a computer, drop a small folder on it. Each file says Locking, then Uploading.
3. Open the folder. On one file tap **Share**, keep **Once**, turn on **Delete it from my drive
   after**, and tap **Make link**.
4. Open the link in a private window and tap **Open it**. Reload: "This link has ended."
5. Back in the drive, open **Activity**: opened, then "It left your drive", and soon its receipt on
   the Tari chain with its tx. **What our server knows** shows the rest: a padded size, the hour,
   the rule, how many times it opened each hour, and its folder.

No drive needed for one thing: **Just share one thing** on the home page gives a link that opens
once. The second track, with a phone and Tari, is on `/judges`.

## Where Tari comes in

| Tari capability | What it does in **hidebox** | How you check it |
|---|---|---|
| Stealth outputs (amount and owner hidden) | Send by Tari, dead-drop deliveries, more space, pay to open (behind its flag) | `/verify/tx/<id>`: amount hidden, owner a one-time key, memo encrypted, fee public |
| Encrypted memo | Carries a file's key, sealed to one Tari address's owner and view keys (125 bytes) | Only the recipient's keys open it; any other key fails |
| View keys, separate from spending | Received scans the chain in your browser; `/watch` shows what a view key sees; for pay links, a seller's view key, sealed on our server, sees payments and never spends them | A view key reads arrivals and amounts, can't spend and can't open files sealed to a drive |
| Invoice addresses with a reference | Matching a payment to its invoice or pay-link claim without accounts | The payment's memo carries the reference; nothing on chain links it to you |
| Payments checked against chain state | Crediting more space; releasing a pay link's key half | The official Tari library (ootle-wasm, in a sandboxed sidecar) opens the commitment to the exact amount; a Tari-run indexer shows it committed; a payment counts only if its one-time key is ours ([code](server/mutis/payments.py)) |
| A template: SealLog | A public Merkle log of the ciphertext hash of every stored file, a receipt for every file that leaves, and release notarizations | `/verify`: inclusion proofs against the component's state on the Ootle; `template/check.sh --onchain` |
| Keypair identity | Your drive and its Tari address, made in your browser | There is no email field anywhere |

Why not an escrow template: TARI held by a template reveals its amount on the Ootle, while native
stealth outputs keep it hidden, so **hidebox** uses those.

## What the server sees

Encryption hides contents, not everything. The server stores ciphertext, padded sizes, arrival hours,
expiries (rounded up to the hour when an hour or more away), exit rules and open counts. It sees IP addresses while you are
connected and never writes them to a log. The send mode is `send_mode` in
[`/api/v1/config`](https://srv2052606.hstgr.cloud/api/v1/config), and the site's copy follows it:

- **Direct** (this deployment's setting): once the browser wallet holds the testnet grant our sponsor
  wallet sends when a drive opens, the browser builds and pays for the send itself and we pass it to
  the network, so we see that your drive sent a transaction, not to whom. The chain links those sends
  to the sponsor wallet and to each other. Dead-drop deliveries, and any send made before the grant is
  spendable (a minute or two), go through our relay, which learns the destination while the send is
  queued and then scrubs it.
- **Relay**: our wallet posts every send; we learn the address while it is queued, then scrub it.
  Anyone watching the Ootle sees that our wallet paid a fee; the amount, the recipient and the key
  stay hidden.

The complete tables, party by party, are on `/made#who`; what we can't protect you from is on
`/made#cant`.

## Cryptography, in short

- A fresh 256-bit key per file, AES-256-GCM in 4 MB chunks, Padmé padding; name, type and real size
  encrypted separately. Each chunk authenticates the file's header, so reordering, truncation and
  extension fail.
- A per-link 32-byte secret after the `#` unwraps the file key and derives an access token; the server
  keeps only the token's SHA-256. Link + password combines that secret with PBKDF2-SHA256.
- A drive is one 32-byte seed made in your browser; its login key, Tari keys, wallet key and drop
  tags are derived from it with HKDF-SHA256. The server keeps only a hash of the login key.
- Sending to a Tari address seals the link's secret to the address's owner and view keys with the
  official Tari library; the 125-byte blob is the stealth output's memo.
- Proof of work (SHA-256) instead of a captcha; no third-party scripts, a strict CSP with Trusted Types
  where the browser supports them.

## Architecture

```
browser ──HTTPS──► Caddy ──► mutis-api (Python 3.13, stdlib only; runs as `mutis`, can't reach the wallet)
                     │            │ SQLite (ciphertext ids, hashes, counters) + blobs on disk
                     │            ▼
                     │      mutis-chain (runs as `drive`): relay sends, the UTXO mirror, canaries,
                     │            │ SealLog checkpoints, payment proofs through the sidecar
                     │            ├──► sidecar (Node 20 permission model + vendored ootle-wasm 0.46.0)
                     │            └──► tari_ootle_walletd 0.46.0 (official binary) ──► Esmeralda
                     └──► the site and the app: static files, a per-route CSP, SRI on each page's top-level
                          scripts and stylesheets, a hash manifest for everything served
```

| Directory | What |
|---|---|
| [`web/app`](web/app) | the app (ES modules, no build step) and its crypto and protocol library, the sidecar, the vendored ootle-wasm |
| [`web/site`](web/site), [`web/shared`](web/shared) | the site's pages, styles, fonts and partials |
| [`server`](server) | the API, the chain worker, cleanup and the admin CLI |
| [`template`](template) | SealLog, the Ootle template (Rust, compiled to WASM), with its byte-for-byte on-chain check |
| [`deploy`](deploy) | Caddy, systemd units, provisioning, deploy and rollback, backups, health, the operator runbook |
| [`tools`](tools) | the build, lint and copy checks, `verify-deploy.py` |
| [`tests/e2e`](tests/e2e) | the end-to-end suite (headless Chromium with phone and desktop emulation), the griefer |
| [`docs`](docs) | [API](docs/api.md), [threat model](docs/threat-model.md), [self-hosting](docs/self-host.md), [evidence](docs/evidence) |

Python's standard library, the browser's WebCrypto, Debian's Node and Caddy, and one
pinned, hash-checked piece of third-party code (`ootle-wasm`, see [NOTICE](NOTICE)). Nothing is
installed from npm or pip.

## Verify this deployment

Every build writes a manifest with the SHA-256 of every served file and its git commit; each release's
manifest hash is also notarized through SealLog (`/releases.json`).

```sh
git clone https://github.com/c7b/hidebox && cd hidebox
python3 tools/verify-deploy.py https://srv2052606.hstgr.cloud <commit>   # 0 differences, or a list
```

It rebuilds the site from that commit, downloads every file in the live manifest and compares them, and
checks that the live SealLog runs `template/dist/seal_log.wasm` byte for byte. Python 3.11 or newer.

## Run the tests

| Part | Command (from the repository root) |
|---|---|
| Server | `python3 -I -m unittest discover -s server/tests` |
| App library | `python3 -I web/app/tests/run_all.py` (Node 20 and Chromium) |
| App UI | `python3 -I web/app/ui/tests/run.py` (Chromium) |
| Site | `python3 -I web/site/tests/run.py` |
| Template | `template/check.sh` (Rust with the wasm32 target) |
| Deploy, lint, copy | `python3 -I -m unittest discover -s deploy/tests`, `python3 -I tools/lint.py`, `python3 -I tools/check-copy.py` |
| End to end | `python3 -I tests/e2e/run.py --chain --final` ([tests/e2e/README.md](tests/e2e/README.md)) |

Each directory's `ACCEPTANCE*.md` lists its acceptance criteria with evidence, and each
`REVIEW-devil.md` is an adversarial review of that part with the builder's response and fixes.

## How it's built

Built with AI coding agents under the author's direction. The design, threat model and crypto choices
were reviewed by the author; the verification evidence is linked below.

The parts and their trust boundaries are drawn in [docs/architecture.md](docs/architecture.md); how to
report a vulnerability is in [SECURITY.md](SECURITY.md); the reviews of the live site and what each
one changed are in [docs/review/fix-log.md](docs/review/fix-log.md).

## Evidence

Our own test transactions only, never a user's: the hourly canary delivery and the daily demo payment
in [`/evidence.json`](https://srv2052606.hstgr.cloud/evidence.json), the SealLog checkpoints, and the
go-live record in [docs/evidence](docs/evidence). The contest release (the tag `spooky-secrets-2026-10`: suites,
deploys, end-to-end runs, the film's check, a stranger's clone and crawl, the purge) is in
[docs/evidence/2026-10-14/release](docs/evidence/2026-10-14/release).

**hidebox** is an independent project, not affiliated with, endorsed by, or sponsored by Tari Labs, the Tari
Council, or the Tari project. "Tari" is a trademark of Tari Labs. Made in Mexico.
