<!-- SPDX-License-Identifier: MIT -->
# hidebox docs

The [README](../README.md) is the short version. Everything longer lives here.

## About

**hidebox** is a drive that opens only with a key made in your browser: no email,
no password. Files and folder names lock in your browser before upload, and the server stores only
ciphertext. Each file or folder is shared by its own rule (once, a few times, until a time, with a
secret word, as a public link, or to one Tari™ address), and you always see what happened: how many
times it opened each hour, links that ended, files that left. Tari does the private parts: a file's
key travels to an address inside a stealth payment on the [Tari™ Ootle](https://ootle.tari.com)
testnet, more space is paid in tTARI and checked on the chain, and every file that leaves gets a
receipt in a public log on the Ootle. Pay to open (a buyer pays the owner's address, then the file
opens) is on in this deployment (`features.pay_to_open` in
[`/api/v1/config`](https://hidebox.app/api/v1/config)).

The internal codename is **mutis**: it stays in the code, the paths, the services, the CLI and the
repository's history.

## Read next

| Doc | What's in it |
|---|---|
| [overview.md](overview.md) | The long tour: the six steps, two screens of the drive, the exit rules in full, what the server never sees, the architecture in five lines, status and roadmap |
| [tari.md](tari.md) | Where Tari comes in: each capability, what it does here, how to check it |
| [privacy.md](privacy.md) | What the server sees, the two send modes, the cryptography in short |
| [architecture.md](architecture.md) | The parts, the repository, trust boundaries, who sees what, the life of a file |
| [threat-model.md](threat-model.md) | What we protect, the adversaries, payments, griefing the space, what we can't protect you from |
| [api.md](api.md) | The HTTP API, route by route |
| [self-host.md](self-host.md) | Run it on your machine, or a real deployment |
| [verify.md](verify.md) | Check the live site against a commit, run the tests, the evidence, how it's built |
| [review/fix-log.md](review/fix-log.md) | Every review of the live site and what each one changed |
| [evidence/](evidence/) | Suites, deploys, end-to-end runs and screenshots, one folder per day |
| [media/](media/) | The README's pictures and the repository's social preview |

On the live site: [/judges](https://hidebox.app/judges) (two tracks of six steps),
[/how](https://hidebox.app/how) (how it works, in five pictures),
[/made](https://hidebox.app/made) (under the hood: every claim with its limits) and
[/fine-print](https://hidebox.app/fine-print).

Security reports: [SECURITY.md](../SECURITY.md). Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md).
