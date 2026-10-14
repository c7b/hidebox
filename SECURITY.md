<!-- SPDX-License-Identifier: MIT -->
# Security policy

**bye** runs on the Tari Ootle **Esmeralda testnet**. tTARI has no monetary value, and the live site
at <https://srv2052606.hstgr.cloud> is a contest entry run by one person. That bounds what a report
can be worth, not how seriously it is read.

## Report a vulnerability

Please tell us privately before you tell anyone else.

1. **Our dead drop** (the channel [`/.well-known/security.txt`](https://srv2052606.hstgr.cloud/.well-known/security.txt)
   names, RFC 9116): open the drop link it lists and leave a file or a note. Your browser encrypts it
   before upload and its key travels to our locker inside a stealth payment on the Ootle, so the
   report is readable by us alone, and nothing on our server or on the chain says who left it. A
   drop takes a fixed number of files a day (`DROP_FILES_PER_DAY` in `server/mutis/handlers/uploads.py`);
   if it answers "took all it can today", try again after midnight UTC, or use the next channel.
2. **A GitHub private security advisory** on `c7b/hidebox`:
   [Report a vulnerability](https://github.com/c7b/hidebox/security/advisories/new) (*Security →
   Report a vulnerability*; it needs a GitHub account). Only you and the maintainer see the advisory.
   `security.txt` lists it as the second `Contact`, and `/made#disclosure` links it; the site's test suite
   checks, as a visitor who isn't signed in, that the form answers and that private reporting is on.

Please include what you saw, how to reproduce it, and which part of the site or the repository it
touches. A proof of concept against the live site is fine when it stays within your own files,
links and lockers; please don't test availability (floods, budget exhaustion, slow-loris uploads)
against production, since the limits are documented and can be read in the source.

## What to expect

- An acknowledgement within 3 days, by the channel you used (leave a way to reach you in the report
  if you want one: a dead-drop link of your own, a Tari address, an email).
- A fix or a documented decision within 14 days for anything that affects a visitor's files, keys,
  identity or IP address; longer for availability findings, which are weighed against the published
  limits.
- Credit in `docs/review/fix-log.md` and the changelog if you want it, and silence if you don't.

## Scope

In scope: everything this repository ships and the live deployment that runs it: the browser code
under `web/`, the API and chain worker under `server/`, the SealLog template under `template/`, and
the deployment under `deploy/` (Caddy, systemd, the firewall, backups, the admin CLI).

Out of scope: the Tari network, its indexers and `tari_ootle_walletd` (report those to the Tari
project), your own device and browser (extensions, malware, clipboard history), chat apps that
preview links, and findings that need the server's own keys or a copy of its database to matter
(those are already in the threat model under "a compromised server").

## What a finding is measured against

The privacy claims on [`/made`](https://srv2052606.hstgr.cloud/made) and
[`/fine-print`](https://srv2052606.hstgr.cloud/fine-print) and in [docs/threat-model.md](docs/threat-model.md)
are meant to be literally true for the code and configuration that ship. Any sentence there that the
code doesn't honour is a vulnerability, whether or not it leaks a byte. The reviews already run
against the live site, their findings and what each one changed are in
[docs/review/fix-log.md](docs/review/fix-log.md).

## Keys and secrets

No key material is committed: the owner's locker key, judge passes, the server's `secret.key`, the
wallet's keyring password and the sidecar's keys live only on the server or on the owner's machine,
and the lint refuses any public IP address but the server's own. If you believe a secret has reached
this repository or the site, that is the most urgent report there is; use the dead drop.
