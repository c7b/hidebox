<!-- SPDX-License-Identifier: MIT -->
<div align="center">

<h1><img src="docs/media/hidebox-lockup-card.svg" width="268" height="108" alt="hidebox"></h1>

**Your private cloud storage. Store, send, and sell files privately.**<br>
Built on Tari™. No KYC. No email.

[**Open your drive**](https://hidebox.app) · [For judges](https://hidebox.app/judges) · [How it works](https://hidebox.app/how) · [Docs](docs/README.md)

[![Live site status](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhidebox.app%2Fstatus.json&query=%24.overall&label=live%20site&labelColor=0A0A0A&color=171717)](https://hidebox.app/status.json)
![Network: Esmeralda testnet](https://img.shields.io/badge/network-Esmeralda%20testnet-7008E7?labelColor=0A0A0A)
[![License: MIT](https://img.shields.io/badge/license-MIT-BCFE00?labelColor=0A0A0A)](LICENSE)

</div>

<a href="https://hidebox.app"><img src="docs/media/home.webp" alt="The hidebox home page: Your private cloud storage. Store, send, and sell files privately. Built on Tari. No KYC. No email."></a>

## Try it in 2 minutes

1. Open [hidebox.app](https://hidebox.app) and tap **Open your drive**. No email, no password.
2. Drop in a file, then **Share**, keep **Once**, and **Make link**.
3. Open the link in a private window, then reload it: "This link has ended."

Both judge tracks, step by step: [/judges](https://hidebox.app/judges). The long tour: [docs/overview.md](docs/overview.md).

## How it works

Files lock in your browser first. You pick how each file opens: once, with a word, or for Tari.

<img src="docs/media/how-it-works.svg" alt="Four parts. Your browser locks every file. Our server gets scrambled noise. Never the key. Whoever has the link opens it by its rule. When a file leaves your drive, we write that on the Tari chain, for anyone to check. The key hides in the link, after the # sign.">

## Exit rules

| Rule | It opens |
|---|---|
| **Once** | one time, then the link ends |
| **A few times** | up to 3 times |
| **Until a date** | until tomorrow, or for a week |
| **Public link** | until you stop it |
| **Secret word** | with the link and the word |
| **One Tari address** | only for that address |
| **Pay to open** | once they pay your Tari address |
| **Delete it after** | by its rule; when the link ends, the file leaves your drive too |

## Run it yourself

```sh
git clone https://github.com/c7b/hidebox && cd hidebox
python3 -I tools/build.py --config deploy/config/mutis.toml.example --origin http://127.0.0.1:8787 --web web --out /tmp/mutis-dist --release /tmp/mutis-release
python3 -I server/bin/mutis-api --dev --data /tmp/mutis-dev --dist /tmp/mutis-dist --port 8787 --pow-bits 10
python3 -m webbrowser http://127.0.0.1:8787   # --dev fakes the wallet, indexer and chain: every flow runs offline
```

## Docs

[Privacy](docs/privacy.md) · [Tari](docs/tari.md) · [Architecture](docs/architecture.md) · [Threat model](docs/threat-model.md) ·
[API](docs/api.md) · [Self-host](docs/self-host.md) · [Verify and test](docs/verify.md) · [Fix log](docs/review/fix-log.md) ·
[Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## License

MIT ([LICENSE](LICENSE), [NOTICE](NOTICE)). Built with AI coding agents under the author's direction.

Built on the Tari™ Ootle testnet. tTARI is the coin on Tari's test network. It is worth nothing.
**hidebox** is an independent project, not affiliated with, endorsed by, or sponsored by Tari Labs, the Tari
Council, or the Tari project. "Tari" is a trademark of Tari Labs. All rights reserved.
