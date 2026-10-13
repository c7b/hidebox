<!-- SPDX-License-Identifier: MIT -->
# Threat model

What **bye** defends against, what it doesn't, and where each guarantee comes from. The live pages
[/made](https://srv2052606.hstgr.cloud/made) and [/fine-print](https://srv2052606.hstgr.cloud/fine-print)
say the same things for this deployment's settings (`send_mode`, `amount_proof` and `features` in
[`/api/v1/config`](https://srv2052606.hstgr.cloud/api/v1/config)); this file covers both send modes.

## What we protect

The contents, name, type and real size of every file, and the key that opens it. The server stores
ciphertext and never receives a file key, a link's secret, a password or a locker's seed.

## Adversaries

| Adversary | Can | What stops them | What remains |
|---|---|---|---|
| Network observer | see TLS metadata | HTTPS only, HSTS, Padmé size buckets | timing and volume |
| A curious or compromised server (including our host) | read the database and the stored files, change responses, watch IP addresses live | everything is encrypted in the browser; tokens and verifiers are hashed; no public keys or locker addresses stored for logins; no sharing graph; each chunk is authenticated together with its header | can serve malicious JavaScript (see "Verify"); can refuse service; sees the metadata listed on `/made#who`; in relay mode knows each send's destination while it is queued; can ignore a deletion and keep ciphertext, which is useless without the key |
| Someone with only the link's path | ask for its status | the key lives only after the `#`; opening needs an access token derived from it; link + password adds a link proof | learns that a link exists, its state, and once it has ended why and on what day (with SealLog: its exit receipt, so the file's id and which checkpoint windows its arrival and exit fell in); not the open count |
| Password guesser, online | try passwords | the access token comes from the password; growing pauses; proof of work; only holders of the full link can count as wrong passwords | slow guessing against weak password-only links |
| Password guesser, with a copy of our database | guess password-only links offline | PBKDF2-SHA256; link + password is the default, and password-only links come with a warning | weak password-only secrets |
| Chain observer | read all public state | stealth outputs, encrypted memos, one fee and one amount for every relay send, decoy sends | the fee and the transaction graph are public; relay sends are recognisable as ours; direct sends link to our sponsor wallet and to each other |
| A view-key holder | read arrivals, amounts and memo text | files sealed to a locker need its owner key too | files sent with "The recipient uses another Ootle wallet" open with the view key (labelled at send time) |
| Phishing through our sends | make someone receive a **bye** link | relay mode: the server writes every memo our relay sends, from its own address; a client supplies only a 125-byte sealed blob; sends need a locker; drop deliveries only go to the drop's own address. Direct mode: sends are bounded by the daily sponsor budget, and the inbox shows any memo that isn't an exact **bye** delivery as plain text | someone can send unwanted **bye** deliveries to an address: daily caps, closable drops, a separate inbox section, no automatic preview, a warning before programs |
| Griefer | fill storage, push proof of work up, drain daily budgets, lock links | reserved lanes for small files and files without a locker, limits per network prefix, a first-day limit for new lockers, public and reserved budget slices with alerts, a cap on requests in flight per network | someone with many networks can use up the public slices for a day; the reserved slices keep the guided demo working |
| Someone hosting abuse | upload and share | small and short-lived files without a locker, one open by default, proof of work, rate limits, downloads only, a warning before programs, no listing or search, `noindex`, the report form, removal by id | we can't scan encrypted content, by design |
| Script injection or a poisoned dependency | run code in our origin | no third-party scripts; a strict content security policy with Trusted Types where supported; no HTML sinks in our code; the one vendored artifact is pinned by hash and re-hashed before it runs; SRI on each page's top-level scripts and stylesheets, and the hash manifest (`verify-deploy`) for the modules they import | browser extensions (out of scope) |
| Draining our wallet through the API | spend the sponsor wallet | the internet-facing API runs as a separate user that can't reach the wallet (a firewall rule per user on the wallet port); jobs are validated; daily budget slices | at most the daily budgets |

## Send modes

- **Relay** (the default): our wallet posts the stealth payment that carries a file's sealed key. The
  server learns the destination address while the job is queued and scrubs it once the job is done; it
  writes the memo itself, so a client can only supply the 125-byte sealed blob. Relay sends all come
  from one wallet with one fee, so an observer can group them as "sent by **bye**", but not see to whom.
  The chain worker puts the outputs of its own transactions (deliveries, change and decoys alike) into
  the public UTXO mirror as soon as they commit, instead of waiting for the indexers' streams (which
  list an output only once the network's consensus epoch reaches it); the chain already shows those
  transactions as ours.
- **Direct** (`send_mode = "direct"`): the browser builds, signs and pays for the payment from a small
  grant our sponsor wallet sends to the locker (one a day per locker, two per /64), and the server
  passes it to the network without learning who it's for. That submit path takes a locker session and
  relays only a transaction shaped like the app's own send (one stealth transfer paying its own fee,
  one output plus change), so it is no address-hiding relay for other transactions. The chain links those sends to the sponsor
  wallet and to each other. When the browser asks our proxy for its transaction's result and it has
  committed, the server adds its outputs to the mirror; it already passed that transaction on, so it
  learns nothing new. Until the grant is spendable (a minute or two after the locker opens), or all day
  when the day's grant is refused, a send falls back to the relay, and the send screen says which way
  the next send goes, and why, before Send is pressed.
  Dead-drop deliveries still go through the relay, because a drop's address is public by design.

## Payments

A wallet saying "sent" isn't enough (in September 2026 a testnet wallet showed deposits that never
happened), so **bye** credits rented space only after its own checks. With `amount_proof = "sidecar"`
the official Tari library (ootle-wasm 0.45.0, in a Node process under the permission model that can
only read its own directory) opens the output's commitment to the exact amount, and a Tari-run public
indexer shows the output committed. walletd never decides a credit. With `amount_proof = "wallet"`
(the fallback when the sidecar can't run) the amount is the one our wallet reads, and the site says
so.

## SealLog

- A template on the Ootle. At each checkpoint the chain worker adds one Merkle root (RFC 9162 hashing)
  over the ciphertext hash of every stored file and a record of every exit, padded to the next multiple
  of 64 above the tree's size, so an idle window looks like any other.
- A proof shows that the tree we committed to at that epoch contains your file's ciphertext hash, or
  the record of its exit. Not that we held the bytes, and not that we deleted them.
- The log has no owner (`owner_rule: "None"` in its header), so nobody, us included, can change its
  rules or the code behind it. Checkpoints are only ever added; nothing yet proves that each one
  extends the last (there are no consistency proofs).
- One key writes it: our `service` key, the same one that holds our public tTARI (walletd 0.45 signs
  manifests with that key whichever account pays, so the planned separate operator key wasn't
  possible). It can add any root, stop, or start a new log.
- It shows everyone a rough upper bound on how many records we've written, in steps of 64, and when.
- `template/check.sh --onchain <template>` (or `tools/verify-deploy.py`) checks that the template on
  the chain is `template/dist/seal_log.wasm` byte for byte. Older logs are listed as retired in
  `/evidence.json`; the live one is the one `/api/v1/config` names.

## What never touches a disk

- Web server: no access log; the error log drops addresses, paths, hosts and headers.
- API, chain worker, cleanup: route names, status codes, durations and fixed event codes only
  (`server/mutis/logsafe.py` refuses anything else).
- Rate limits: a keyed hash of the network prefix, in memory, with a key that changes every day.
- walletd: warnings only, to the journal. Its database keeps its own transactions (that's how a
  wallet works); it keeps no destination address or memo of a relay send (`tests/e2e/test_logs.py
  --walletd-probe` searches for them).
- Firewall logging is off; the system journal keeps seven days.

`tests/e2e/test_logs.py` runs a scripted session from outside, then searches every journal entry,
every file under `/var/log` and walletd's storage for its addresses, ids, tokens, keys and memos.

That isn't "nobody ever sees your IP": the server sees it while you're connected, and so could our host.

## What we can't protect you from

- The person you send it to, and anyone who gets the full link (the link is the key).
- Chat apps that preview links, your browser history and its sync, clipboard history, extensions that
  read your tabs, and malware on your device.
- A malicious version of this website: if the server were compromised it could serve code that leaks
  keys. SRI pins files to a page, not against us. What helps: `tools/verify-deploy.py`, the release
  hashes notarized through SealLog, and running your own copy.
- Metadata: padded size, arrival hour, exit rule, open counts, and your IP address while you're
  connected. A VPN or Tor hides your IP from us; links without a locker work in Tor Browser's Safer
  mode, and Tari features need WebAssembly.
- Deletion you can't see: we delete on cue, and nothing can prove we kept no copy. The daily database
  backup holds the wrapped key of every link open at that moment (useless without the link's secret);
  the host's snapshots and free disk blocks can hold ciphertext until they rotate.
- Testnet resets and legal requests: we can hand over what we have (ciphertext, the columns on the
  "What we know" panel, invoices), never contents or keys.

## Verify

Every build writes a manifest with the SHA-256 of every served file and its commit
(`/.well-known/mutis-manifest.json`). `tools/verify-deploy.py <origin> <commit>` rebuilds from a clean
checkout, downloads every file in the live manifest and prints any difference, and checks the live
SealLog's template. Since SealLog went on, each release's manifest hash is notarized through it
(`/releases.json`); anyone can call `notarize`, so only events signed by the log's writer key count.

## Known incidents

- 2026-10-11, during setup: walletd rejected a config value and printed it, so the testnet wallet's
  keyring password appeared once in the server's journal (purged within minutes; a search of the
  journal and `/var/log` then found nothing) and in the build session's transcript. It only opens
  the testnet wallet's database, which never leaves the server; a mainnet wallet would be new, with a
  new password.
- 2026-10-11, at go-live: one of the two public indexers kept answering while its UTXO stream stopped
  advancing, so deliveries didn't reach the mirror. The chain worker now mirrors every indexer, each
  with its own cursors.
