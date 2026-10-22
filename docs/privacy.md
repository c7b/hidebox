<!-- SPDX-License-Identifier: MIT -->
# What the server sees, and the cryptography

The short version is in the [README](../README.md#what-the-server-never-sees). The complete tables, party
by party, are on [`/made#who`](https://hidebox.app/made#who); what we can't protect you from
is on [`/made#cant`](https://hidebox.app/made#cant) and in [threat-model.md](threat-model.md).

## What the server sees

Encryption hides contents, not everything. The server stores ciphertext, padded sizes, arrival hours,
expiries (rounded up to the hour when an hour or more away), exit rules and open counts. It sees IP addresses
while you are connected and never writes them to a log. The server counts how many links and drives were made after
someone tapped Make your own secret or Sell your own files: one number per day for each, nothing about who. A tab that
came through one of those buttons keeps that in its own sessionStorage until it makes a link or a drive, and says so
once with that request (`from_share`); the `daily_counts` table holds the day, which of the two, and a count, for
`retention.count_days` days. The send mode is `send_mode` in
[`/api/v1/config`](https://hidebox.app/api/v1/config), and the site's copy follows it:

- **Direct** (this deployment's setting): once the browser wallet holds the testnet grant our sponsor
  wallet sends when a drive opens, the browser builds and pays for the send itself and we pass it to
  the network, so we see that your drive sent a transaction, not to whom. The chain links those sends
  to the sponsor wallet and to each other. Dead-drop deliveries, and any send made before the grant is
  spendable (a minute or two), go through our relay, which learns the destination while the send is
  queued and then scrubs it.
- **Relay**: our wallet posts every send; we learn the address while it is queued, then scrub it.
  Anyone watching the Ootle sees that our wallet paid a fee; the amount, the recipient and the key
  stay hidden.

Space is one real disk: packs and free space have daily limits per network, which slow anyone trying
to take it ([threat model, "Griefing the space"](threat-model.md#griefing-the-space)).

## Cryptography, in short

- A fresh 256-bit key per file, AES-256-GCM in 4 MB chunks, Padmé padding; name, type and real size
  encrypted separately. Each chunk authenticates the file's header, so reordering, truncation and
  extension fail.
- A per-link 32-byte secret after the `#` unwraps the file key and derives an access token; the server
  keeps only the token's SHA-256. Link + password combines that secret with PBKDF2-SHA256.
- A drive is one 32-byte seed made in your browser; its login key, Tari™ keys, wallet key and drop
  tags are derived from it with HKDF-SHA256. The server keeps only a hash of the login key.
- Sending to a Tari address seals the link's secret to the address's owner and view keys with the
  official Tari library; the 125-byte blob is the stealth output's memo.
- Proof of work (SHA-256) instead of a captcha; no third-party scripts, a strict CSP with Trusted Types
  where the browser supports them.
