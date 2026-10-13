<!-- SPDX-License-Identifier: MIT -->
# Architecture

What runs where, who may talk to whom, and where each privacy guarantee comes from. The behaviour
of every route is in [api.md](api.md); what each guarantee defends against is in
[threat-model.md](threat-model.md); the operator's view of the same machine is
[deploy/README.md](../deploy/README.md).

## The parts

```
 visitor's browser                                   ultron (Debian 13, one VPS)
 ┌──────────────────────────┐   HTTPS   ┌──────────────────────────────────────────────────────┐
 │ site pages, app modules  │──────────►│ caddy (user caddy): TLS, headers, per-route CSP,       │
 │ WebCrypto: AES-256-GCM,  │           │ static files from the release, /api/* → 127.0.0.1:8787 │
 │ HKDF, PBKDF2; the        │           └───────────────┬──────────────────────────────────────┘
 │ vendored ootle-wasm for  │                           │ X-Real-IP (trusted from loopback only)
 │ sealing keys, scanning   │           ┌───────────────▼──────────────────────────────────────┐
 │ and building sends       │           │ mutis-api (user mutis, Python 3.13 stdlib)            │
 └──────────────────────────┘           │   SQLite: ids, hashes, counters; blobs/ (ciphertext)  │
             ▲ "Check it on Tari's      │   rate limits and PoW in memory, keyed per day        │
             │  indexer" (explicit)     │   proxy to the indexers: allowlisted reads, one send  │
             ▼                          └───────────────┬──────────────────────────────────────┘
 ┌──────────────────────────┐                   shared DB (0660, group mutis) · jobs table
 │ Tari indexers a and b    │           ┌───────────────▼──────────────────────────────────────┐
 │ (Tari-run, public)       │◄──────────│ mutis-chain (user drive): relay sends, UTXO mirror,   │
 └──────────────────────────┘           │ sponsor grants, payment proofs, canaries, SealLog      │
             ▲                          │ checkpoints, decoys                                    │
             │                          │   ├─► sidecar (Node 20, permission model, ootle-wasm)  │
             │                          │   └─► tari_ootle_walletd 0.46 (user drive, :5100)      │
             │                          └───────────────┬──────────────────────────────────────┘
             └───────────── Esmeralda ◄─────────────────┘
```

| Part | Runs as | Reaches | Holds |
|---|---|---|---|
| Caddy | `caddy` | the internet (80, 443), the API on loopback | the release's `dist/`, the TLS key; no access log |
| `mutis-api` | `mutis` | the Tari indexers (reads, and the submit proxy); never walletd (a firewall guard on port 5100 answers it with a reset) | the database and `blobs/`; `secret.key` for PoW and canary tokens |
| `mutis-chain` and its sidecar | `drive` | walletd, the indexers, the API's loopback port (the canary upload) | the same database; the receiver and robot keys; the wallet's keyring password as a systemd credential |
| `tari_ootle_walletd` | `drive` | Esmeralda through the indexers | the `service` and `sponsor` accounts' testnet keys |
| timers (`cleanup`, `health`, `evidence`, `backup`, `backup-wallet`) | `mutis` or `drive` | the database, `/srv/mutis/status` | nothing new |
| `build` | `build` | nothing of the above (no sudo, no wallet, no data) | the test trees and the headless browser |

Only `drive` and root can open walletd's port; only `caddy`, `drive`, root and the operator can open
the API's, because the API believes `X-Real-IP` from loopback. These are owner-match rules in ufw,
listed in [deploy/ufw/README.md](../deploy/ufw/README.md).

## Trust boundaries

1. **Browser → server.** Everything that touches a file or a key happens in the browser: the file
   key, the per-link secret after the `#`, the password, the locker seed and everything derived from
   it never cross this line. The server receives ciphertext, hashes (of access tokens and login
   keys), padded sizes, exit rules and a locker id. See "Who sees what" below.
2. **API → chain worker.** They share one SQLite database (group `mutis`, mode 0660) and one
   HTTP path: the worker uploads the hourly canary through the API's loopback port, like any client. The API queues work (a relay send, an invoice to watch); the worker performs it with the
   wallet and writes the result back. The API can't reach the wallet, so a compromised API can at
   most queue the jobs the handlers already allow (bounded by the daily budgets).
3. **Server → Tari.** The chain worker and the API talk to the two Tari-run public indexers over
   HTTPS (reads: substates, transaction results, the UTXO stream; writes: submitting a signed
   transaction). walletd signs for the server's own accounts only. A browser's direct send is built
   and signed in the browser and passed through the API's submit proxy, which relays only a
   transaction shaped like the app's own send.
4. **Server → visitor's IP.** Seen while connected, hashed with a key that lives one day in memory
   for rate limits, never written: no access log, an error log with every request field removed,
   fixed event codes in the API's and worker's logs (`server/mutis/logsafe.py`). The price of that
   key never touching disk: a restart of `mutis-api` (a deploy, a reboot, a crash) forgets every
   per-network and per-locker counter (rate limits, the daily caps on sponsor grants, demo payments,
   registrations and drop uploads, proof-of-work escalation, wrong-password tries per network on
   password-only links), so a visitor starts that day afresh. A link's own wrong-password count and
   lock are rows in SQLite and survive. The money ceilings don't reset either: the daily budgets every
   grant, delivery and demo payment draws on are rows in SQLite (`server/mutis/budgets.py`).

## Who sees what

| | Our server | Anyone watching the Ootle | Someone with the full link | The person you send it to |
|---|---|---|---|---|
| File contents, name, type, exact size | no (ciphertext, a padded bucket) | no | yes | yes |
| The key | no | no | yes (the link is the key) | yes |
| That a file exists, its arrival hour, rule and opens | yes | counts only, in steps of 64 per checkpoint (SealLog) | partly (state, opens left) | — |
| Your IP address | while connected; never on disk | no, unless you press "Check it on Tari's indexer" | no | no |
| Who you send to | direct sends from your browser: no; relay sends and dead-drop deliveries: yes, while the job is queued, then scrubbed | no (a one-time stealth address) | — | they know it's them |
| That **bye** sent a payment | yes | relay sends: one wallet, one fee; browser sends trace back to our sponsor wallet's grant and to each other | — | — |
| Payment amounts | for space rented from us (we're the seller) | no (a Pedersen commitment) | — | — |
| Folder structure: which files share a folder, how deep, how many | yes (never a name) | no | yes, for the folder the link opens | — |
| How many times a link opened, per hour | yes (a count per link per UTC hour; never who or from where) | no | no | — |

The long form, with every party and every column the database keeps, is on `/made#who` and `/fine-print#privacy`.

## The life of a file

```
 choose ──► (photos: EXIF removed) ──► key = random 256 bits ──► AES-256-GCM, 4 MB chunks, Padmé padding
   │                                                                      │
   │   POST /uploads (PoW or locker session): header, encrypted metadata, chunk count, padded size
   │   PUT  /uploads/{id}/chunks/{n} (SHA-256 per chunk)  ──►  POST /uploads/{id}/complete → ct_hash
   │                                                                      │
   ▼                                                                      ▼
 link = /s/{share id}#{32-byte secret}        SealLog: ct_hash in the next checkpoint's Merkle root
   │   (POST /items/{id}/shares: wrapped key, SHA-256 of the access token, rule: once / N / time / kept)
   │
   ├─► recipient opens: GET /s/{id} (state) → POST /s/{id}/open with X-Mutis-Access (derived from the
   │   secret) → wrapped key + ciphertext (or a short-lived download ticket) → decrypts in the browser
   │
   └─► exit: the last open, the expiry (stored rounded up to the hour when it's an hour or more away), a deletion or a takedown
         → the ciphertext is deleted within a minute (after a download in progress ends)
         → a note (state, day) stays for the published number of days
         → the exit record goes into the next SealLog checkpoint; GET /s/{id}/exit returns its proof
```

In a drive, a file can sit in a **folder**: `POST /folders` makes an item without ciphertext whose own
random key wraps the keys of what it holds (each child's `parent_wrap`), so a folder key opens its whole
subtree and nothing above it. A move or a rename is one `PATCH /items/{id}` made in the browser (a new
wrap under the new folder, a new encrypted name); the ciphertext and its SealLog leaf don't change.
Deleting a folder deletes everything below it, and each file leaves with its own exit receipt. The
**Trash** keeps files for `retention.trash_days` (their links end when they go in); **Delete it after**
sets a date on a kept file, and it leaves then, with its exit receipt. A **folder link** is an ordinary
link on the folder: one open is one visit that returns the folder's tree (ids, headers, encrypted names,
wraps) and a folder ticket; the ticket serves a file only while it is still inside the folder, so a file
moved out mid-visit is refused at once. A file's link can carry **Delete it from my drive after**
(`then_delete`): the file then leaves with its last link, with its exit receipt. Each open adds one to
its link's count for that UTC hour (`share_opens`), which the owner sees in the drive.

Where the key travels instead of a link: **send to a Tari address** (the link's secret is sealed to
the address's owner and view keys with the official library; the 125-byte blob is the memo of a
stealth payment) and **dead drops** (a public intake page whose uploads are sealed to the drop
owner's locker and delivered the same way). The recipient's inbox scans the public UTXO mirror in
the browser, so the server never learns which outputs a browser can open.

## The Tari parts

| Part | What it does here | Where in the code |
|---|---|---|
| Stealth outputs (hidden amount, one-time owner) | every send, delivery, grant and pack payment | `web/app/lib/wallet.js` (browser-built sends), `server/mutis/chain_worker.py` and `walletd.py` (relay sends) |
| Encrypted memos | carry a file's sealed key (125 bytes) to one address | `web/app/lib/courier.js`, `server/mutis/handlers/courier.py` |
| View keys | the inbox scans with them; `/watch` shows what a view key sees and can't open | `web/app/lib/scan.js`, `web/app/ui/watch.js` |
| Dead drops | a public address plus a tag; deliveries sealed to the owner's keys | `server/mutis/handlers/drops.py`, `web/app/ui/droppage.js` |
| The UTXO mirror | every TARI output since `mirror_start_epoch`, served to every browser alike | `server/mutis/mirror.py`, `GET /chain/utxos` |
| Direct sends | the browser builds, signs and pays from a sponsor grant; the server relays only that shape | `web/app/lib/wallet.js`, `server/mutis/handlers/chain.py`, `server/mutis/cbor.py` |
| Pack payments | credited only after the sidecar (official library) opens the commitment to the exact amount, an indexer shows it committed, and its one-time key is the one our receiver's owner key derives (spendable by us, not only readable with our view key) | `server/mutis/payments.py`, `server/mutis/chain_worker.py`, `web/app/sidecar/` |
| SealLog | a Merkle root over stored-file hashes and exit records per checkpoint; proofs checked in the browser against the component's state; release manifests notarized | `template/seal_log/`, `server/mutis/seallog.py`, `web/app/lib/seallog.js` |

The template is published from this repository's exact bytes; `template/check.sh --onchain` and
`tools/verify-deploy.py` compare the chain's copy with `template/dist/seal_log.wasm`.

## Verify, don't trust

Every build writes a manifest with the SHA-256 of every served file and its commit
(`/.well-known/mutis-manifest.json`); each release's manifest hash is notarized through SealLog
(`/releases.json`). `python3 -I tools/verify-deploy.py <origin> <commit>` rebuilds that commit,
downloads every served file and prints any difference. Each page carries SRI for its top-level
scripts and stylesheets, and the manifest covers the modules they import.

## How it's built

Built with AI coding agents under the author's direction. The design, threat model and crypto choices
were reviewed by the author; the verification evidence is in [evidence/](evidence/). Python's
standard library, the browser's WebCrypto, Debian's Node and Caddy, and one pinned, hash-checked
piece of third-party code (`ootle-wasm`, see [NOTICE](../NOTICE)). Nothing is installed from npm or pip.
