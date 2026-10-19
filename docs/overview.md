<!-- SPDX-License-Identifier: MIT -->
# The long tour

The [README](../README.md) is the short version. This page keeps what it used to say in full: the six steps,
two screens of the drive, the exit rules in whole sentences, what the server never sees, the architecture in
five lines, and the status and roadmap.

## Try it: the six steps of track one

You need one device and no wallet. The second track, with a phone and Tari™, is on
[/judges](https://hidebox.app/judges).

1. On the [home page](https://hidebox.app), tap **Open your drive**. Your drive opens, with your Tari address. No email, no password. Your key is the account.
2. On a computer, drop a small folder on it. Each file says Locking, then Uploading.
3. On one file: **Share**, keep **Once**, turn on **Delete it from my drive after**, **Make link**.
4. Open the link in a private window and tap **Open it**. Reload: "This link has ended."
5. Back in your drive, open **Activity**: opened, then "It left your drive." That goes on the Tari chain within 15 minutes.
6. Tap **What our server knows**: a padded size, the hour, the rule, how many times it opened each hour, and its folder.

<p align="center">
  <img src="media/drive.webp" width="49%" alt="The drive in dark mode: two files, one Private and one shared Once, with its opens and when it ends">
  <img src="media/share.webp" width="49%" alt="The share window: a link that opens once, Copy link, and Stop sharing">
</p>

## How it works

The diagram of the four parts is in the [README](../README.md#how-it-works).

The key hides in the link, after the # sign. Browsers don't send it to any server, including ours.
Every party, fact by fact: [/made#who](https://hidebox.app/made#who) and
[privacy.md](privacy.md). Where Tari comes in, and how to check each part: [tari.md](tari.md).

## Exit rules

Each file or folder gets its own rule. You can stop a link any time, from its menu.

| Rule | What happens |
|---|---|
| **Once** (the default) | It opens one time. Then the link ends. |
| **A few times** | It opens up to 3 times. Then the link ends. |
| **Until a date** | Anyone with the link can open it until then: tomorrow, or in a week. |
| **Public link** | Anyone with the link can open it until you stop it. |
| **Secret word** | They need the link and the word. Send the word a different way than the link. |
| **One Tari address** | Send by Tari: the key rides inside a payment to their address. Only they can open it. |
| **Pay to open** | They pay your Tari address, then it opens. The chain shows a payment with a hidden amount and a hidden owner. The fee is public. |
| **Delete it after** | When the link ends, the file leaves your drive too. We write that on the Tari chain, for anyone to check. |

## What the server never sees

Our server gets scrambled noise. Never the key.

| Never sees | Sees, and keeps |
|---|---|
| Names, types, contents and real sizes of your files and folders | Ciphertext, and a padded size, so the real size stays hidden |
| File keys, link secrets, passwords or your seed | A hash of the login key, and a hash of each link's access token |
| Who opened a link, or who holds one | How many times a link opened in each hour |
| Your IP address on disk: it sees it while you're connected and never writes it to a log | The hour a file arrived, its rule, and which files share a folder (never a name) |

Pay links: we keep half of the key and give it to each buyer once the chain shows their payment. The other half is in the link. Neither half opens it alone.

## Run it yourself

```sh
git clone https://github.com/c7b/hidebox && cd hidebox
python3 -I tools/build.py --config deploy/config/mutis.toml.example --origin http://127.0.0.1:8787 \
  --web web --out /tmp/mutis-dist --release /tmp/mutis-release
python3 -I server/bin/mutis-api --dev --data /tmp/mutis-dev --dist /tmp/mutis-dist --port 8787 --pow-bits 10
```

Open <http://127.0.0.1:8787>: `--dev` runs the real API with a fake wallet, indexer and chain, so every flow
completes offline. A real deployment: [self-host.md](self-host.md). Check the live site against a
commit, and run the tests: [verify.md](verify.md).

## Architecture

- **Browser:** the app is ES modules with no build step. WebCrypto does AES-256-GCM with a fresh key per file, HKDF and PBKDF2; the vendored official `ootle-wasm` 0.46.0 seals keys and builds Tari sends.
- **API:** `mutis-api`, Python 3.13 standard library only, behind Caddy. SQLite holds ids, hashes and counters; ciphertext sits on disk. It runs as its own user and can't reach the wallet.
- **Chain worker:** `mutis-chain` runs relay sends, the UTXO mirror, payment proofs (official library in a Node 20 sidecar) and SealLog checkpoints, through the official `tari_ootle_walletd`.
- **SealLog:** an Ootle template (Rust, compiled to WASM): a public Merkle log of stored-file hashes, exit receipts and release notarizations, checked in your browser at `/verify`.
- **Release:** a per-route CSP, SRI on each page's top-level scripts and stylesheets, and a hash manifest of every served file, notarized on chain; `tools/verify-deploy.py` compares the live site with a commit.

Nothing is installed from npm or pip. The one third-party piece, `ootle-wasm`, is pinned and hash-checked (see [NOTICE](../NOTICE)).
More: [architecture.md](architecture.md) · [threat-model.md](threat-model.md) · [api.md](api.md).

## Status and roadmap

| When | What |
|---|---|
| **Now** | Live on the Esmeralda testnet. tTARI is the coin on Tari's test network. It is worth nothing. |
| **October 2026** | Built for the Tari Ootle contest "Spooky Secrets"; the judged release is the tag `spooky-secrets-2026-10`. |
| **Nov 11, 2026** | The Ootle mainnet launches. hidebox stays on the testnet until its code is reviewed. |
| **After review** | Paid features open only after that review. |

Reviews of the live site and what each one changed: [review/fix-log.md](review/fix-log.md).
Evidence for every pass: [evidence/](evidence/). Security reports: [SECURITY.md](../SECURITY.md).
