<!-- SPDX-License-Identifier: MIT -->
# Threat model

What **hidebox** defends against, what it doesn't, and where each guarantee comes from. The live pages
[/made](https://hidebox.app/made) and [/fine-print](https://hidebox.app/fine-print)
say the same things for this deployment's settings (`send_mode`, `amount_proof` and `features` in
[`/api/v1/config`](https://hidebox.app/api/v1/config)); this file covers both send modes.

## What we protect

The contents, name, type and real size of every file, and the key that opens it. The server stores
ciphertext and never receives a file key, a link's secret, a password or a locker's seed.

## Adversaries

| Adversary | Can | What stops them | What remains |
|---|---|---|---|
| Network observer | see TLS metadata | HTTPS only, HSTS, Padmé size buckets | timing and volume |
| A curious or compromised server (including our host) | read the database and the stored files, change responses, watch IP addresses live | everything is encrypted in the browser; tokens and verifiers are hashed; no public keys or locker addresses stored for logins; no sharing graph beyond folders (which files share a folder, how deep, how many; never a name); each chunk is authenticated together with its header | can serve malicious JavaScript (see "Verify"); can refuse service; sees the metadata listed on `/made#who`, including a drive's folder shape and how many times each link opened per hour (never who opened it); in relay mode knows each send's destination while it is queued; can ignore a deletion and keep ciphertext, which is useless without the key |
| Someone with only the link's path | ask for its status | the key lives only after the `#`; opening needs an access token derived from it; link + password adds a link proof | learns that a link exists, its state, and once it has ended why and on what day (with SealLog: its exit receipt, so the file's id and which checkpoint windows its arrival and exit fell in); not the open count |
| Password guesser, online | try passwords | the access token comes from the password; growing pauses; proof of work; only holders of the full link can count as wrong passwords | slow guessing against weak password-only links |
| Password guesser, with a copy of our database | guess password-only links offline | PBKDF2-SHA256; link + password is the default, and password-only links come with a warning | weak password-only secrets |
| A dishonest payer (packs) | build an output that opens with our receiver's view key but that they can still spend | the one-time key must be the one our receiver's owner key derives ("Ownership" below) | none known |
| A curious or compromised server, for paid links (pay to open) | hold half of each paid link's key (`sB`); read each seller's payments through the view key of the sales address | `sA` stays after the `#`; `sB` is erased when the link ends; the view key arrives sealed to the payment checker's keys, which the API user and a copy of the database can't use; outputs that pay no claim of that seller are not recorded | our server together with a leaked link could open a paid link; `sB` stays in database backups for `retention.db_backup_days`; the payment checker sees a seller's sales payments while it scans (amount, time, claim) |
| A compromised API, for test money | invent sellers and claims to steer demo payments | the chain worker re-checks every demo payment to a claim: the claim waits for money on a live link, the address is that link owner's sales address with the claim's reference, the seller's view key opened, the amount is at most what is missing; per-network caps; the daily `demo_pay` budget | at most a day's demo budget, in test money, to an address the attacker picks |
| A dishonest buyer (pay to open) | build a payment the seller's view key opens while keeping its spend key, to get the key for the fee | only test money our demo wallet built for the whole price releases by itself; every other payment waits until the owner's drive has compared its one-time keys and confirmed ("Pay to open" below); a failed check voids the claim | a wallet payment opens nothing until the owner's drive has run its check |
| A buyer passing a paid file on | share the file, or the link with their claim token | each claim gives `pay_to_open.buyer_views` opens within `pay_to_open.buyer_window_s`; the link alone opens nothing | anyone who opens a file can share it further (stated on the pay page) |
| A dishonest seller | sell something other than the preview says | none: no disputes, no refunds (stated before paying) | stated |
| Chain observer | read all public state | stealth outputs, encrypted memos, one fee and one amount for every relay send, decoy sends | the fee and the transaction graph are public; relay sends are recognisable as ours; direct sends link to our sponsor wallet and to each other |
| A view-key holder | read arrivals, amounts and memo text | files sealed to a locker need its owner key too | files sent with "The recipient uses another Ootle wallet" open with the view key (labelled at send time) |
| Phishing through our sends | make someone receive a **hidebox** link | relay mode: the server writes every memo our relay sends, from its own address; a client supplies only a 125-byte sealed blob; sends need a locker; drop deliveries only go to the drop's own address. Direct mode: sends are bounded by the daily sponsor budget, and the inbox shows any memo that isn't an exact **hidebox** delivery as plain text | someone can send unwanted **hidebox** deliveries to an address: daily caps, closable drops (closing one, or a takedown, also cancels the deliveries still waiting in the queue), a separate inbox section, no automatic preview, a warning before programs |
| Griefer | fill storage, push proof of work up, drain daily budgets, lock links | reserved lanes for small files and files without a locker, limits per network prefix, a first-day limit for new lockers, public and reserved budget slices with alerts, a cap on requests in flight per network | someone with many networks can use up the public slices for a day; the reserved slices keep the guided demo working |
| Griefer, the space (sixth pass) | buy packs from many drives fast so paid space sells out; make many drives and fill free space so uploads freeze for everyone | a judges' slice of the paid cap; one pack per drive; open invoices count against the cap; daily sales brakes per network (in memory) and per deployment (from the invoices); daily brakes on new drives and free uploads per network (in memory); the hard freezes at the disk's margins; `/status.json` amber and a kill switch ("Griefing the space" below) | many networks (a botnet, or one IPv6 /32) still get through at the deployment's daily pace; a restart forgets the per-network counts |
| Someone hosting abuse | upload and share | small and short-lived files without a locker, one open by default, proof of work, rate limits, downloads only, a warning before programs, no listing or search, `noindex`, the report form, removal by id | we can't scan encrypted content, by design |
| Someone who sends or sells a hostile file | make a preview run code on our origin, where this browser's keys live: an SVG with a script, a web page named `.txt`, a picture with a page after it | the preview picks what to show from the decrypted bytes, never the name or stored type: pictures in an `<img>`, an SVG drawn into a canvas, text as text nodes, everything else download only; the content security policy still refuses inline script ("Previews" below) | a flaw in the browser's own image or SVG decoder; a downloaded file opened elsewhere is as safe as its sender (the app warns before programs) |
| Someone uploading a program to attack the server | send any bytes in place of ciphertext: an executable, a script, a web page, an archive | the server never decodes, parses or runs what it stores, and names each file itself; the files are 0600 on a mount where nothing executes; nothing a service can write is executable in its view; stored bytes leave only as downloads ("Uploads are inert" below) | a flaw in the kernel, Python, Caddy or SQLite reached through the HTTP request itself rather than through the stored bytes |
| Script injection or a poisoned dependency | run code in our origin | no third-party scripts; a strict content security policy with Trusted Types where supported; no HTML sinks in our code; the one vendored artifact is pinned by hash and re-hashed before it runs; SRI on each page's top-level scripts and stylesheets, and the hash manifest (`verify-deploy`) for the modules they import | browser extensions (out of scope) |
| A misbehaving indexer | answer the chain worker's and the API's reads with anything | the UTXO stream and fetch answers are checked field by field before use (bounded numbers, 32-byte nonces, JSON objects); a malformed answer counts against that indexer alone and the others keep the mirror; a credit needs the official library's amount proof and a verified substate | an indexer can hide or delay what only it shows; the health check turns red when the mirror lags |
| A compromised service user (the chain worker's `drive`, or `mutis`) | write where its unit may write, such as the status directory both share | the status directory is mounted `nosymfollow`, so no process (Caddy and root included) follows a link placed there; status files are written under random names and renamed into place ("Uploads are inert" below; `docs/review/security-audit-1.md`) | what that user may do by design: drive holds the testnet wallet's keys and writes the database |
| Draining our wallet through the API | spend the sponsor wallet | the internet-facing API runs as a separate user that can't reach the wallet (a firewall rule per user on the wallet port); jobs are validated; daily budget slices | at most the daily budgets |

## Send modes

- **Relay** (the default): our wallet posts the stealth payment that carries a file's sealed key. The
  server learns the destination address while the job is queued and scrubs it once the job is done; it
  writes the memo itself, so a client can only supply the 125-byte sealed blob. Relay sends all come
  from one wallet with one fee, so an observer can group them as "sent by **hidebox**", but not see to whom.
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
happened), so **hidebox** credits rented space only after its own checks. With `amount_proof = "sidecar"`
the official Tari™ library (ootle-wasm 0.46.0, in a Node process under the permission model that can
only read its own directory) opens the output's commitment to the exact amount, and a Tari-run public
indexer shows the output committed. walletd never decides a credit. With `amount_proof = "wallet"`
(the fallback when the sidecar can't run) the amount is the one our wallet reads, and the site says
so.

**Ownership (R1, fixed in October 2026).** A view key proves an output's amount and memo, not who can spend
it: a payer can build an output that opens with our receiver's view key while its one-time key is the
payer's own. Before this fix such an output credited a pack and the payer kept the money (spending it
back would then have frozen every credit at the hourly reconcile). Now the chain worker also derives
the output's one-time key from our receiver's owner key and the output's nonce (the official library's
`stealthDhSecret`, the sidecar's `oneTimeKey`) and compares it with the key the indexer shows; a
mismatch marks the payment `rejected`, never credited. Tested on the fake chain and with an offline
known-answer test made with the real library (`web/app/sidecar/selftest.json`, `ownership`), never with
forged outputs on the public testnet. The walletd fallback relies on walletd's own list for ownership.

**Pay to open (October 2026).** A buyer pays the owner's sales address directly; the money never reaches
us. To see those payments the payment checker holds the view key of each seller's sales address, which the seller's drive
seals to the checker's keys (kind 3, flag `0x08`, bound to the address); it is opened only in the chain
worker's memory, and only if its public half is the address's view key. A payment counts as for packs:
amount proven by `unblindOutput`, output committed on an indexer, each output once, ever. The ownership
check above can't run here, because only the seller's drive holds the sales owner key, so the release
gate decides: test money our demo wallet built for the whole price (spendable by the owner by
construction) releases `sB` at `paid`; any other payment waits at `owner_check: pending`
until the owner's drive compares each output's one-time key with its own (`stealthDhSecret`, as in
"Ownership") and confirms; a failed check voids the claim and shows "The payer kept control of this
payment". Tested on the fake chain only (`test_release_gate.py`, `test_sales_worker.py`); the sidecar's
`openWatchKey` has an offline round trip in its selftest. Not yet: a locked payment with a refund (a
native Ootle HTLC), which has never run, so nothing is promised about it.

## Griefing the space

The disk is one real disk ([`server/mutis/quota.py`](../server/mutis/quota.py)), and space is the thing a
griefer can take without breaking anything: buy packs from many drives so nobody else can, or make
drives and fill free space until uploads pause for everyone. Sixth pass
([`server/mutis/packs.py`](../server/mutis/packs.py)); each number is a key in `/etc/mutis/mutis.toml`
(`[packs]`, `[brakes]`), defaults here:

- **Paid space** is at most 40 % of the pool. 30 % of that is a slice only purchases made with a judge
  pass draw from; public buyers can't reach it, and judges spill into the public slice once theirs is
  used. "Sold out" is the public slice's answer. An open invoice holds its bytes until it expires, so
  paying many invoices at once can't overbook a slice. An invoice that gave its bytes back (replaced by
  another pack, or its hour over) and is paid later anyway credits only if its slice has room again; until
  then the payment waits, within the 7-day grace (`docs/review/security-audit-1.md`).
- **One pack per drive.** Buying again is refused until the pack's last 3 days; then the same pack adds
  days, not bytes. The big pack is 5 GiB, so one purchase is a small part of the slice.
- **Sales brakes:** 1 pack a UTC day per IPv6 /64 or IPv4 address (with a judge pass, 2 per network and 2
  per pass), held in the API's memory; 3 public packs a UTC day for the whole deployment, and 10 bought with judge passes, counted
  from the invoices table (which holds no network), so a restart doesn't reset them. An unpaid invoice
  stops counting when it expires (an hour), and so does a pack ended early (`release-pack`) or a
  deleted drive's: the ceiling bounds how much of a day's selling holds space at once.
- **Free-space brakes**, a UTC day each and in memory: 5 new drives per /64 or IPv4 address and 20 per
  /48 or IPv4 /24 (a judge pass skips them), and 2 GiB of uploads to free drives per /64 or IPv4 address
  and 6 GiB per /48 or /24 (with a judge pass, 8 GiB per /64 and per pass; a drive with a pack is bounded
  by its pack).
  A drive's first day stays at 64 MiB (probation).
- **The server's own addresses** (`brakes.exempt_addresses`; its end-to-end tests run there) skip the
  per-network brakes and the daily ceilings; what they buy still counts toward the ceilings.
- **Visible:** `/status.json` turns amber (`packs.public_80`, `packs.ceiling`) when the public slice is
  80 % taken or today's public ceiling is reached; `/api/v1/stats` shows `packs_sold_public` and
  `packs_cap_public` in whole GiB, nothing per drive.
- **Kill switch:** `mutis-admin feature packs off` stops new invoices and test-money payments at once
  (503, "Space packs are paused."); a payment someone already sent on chain still credits.

The per-network counts live only in memory, keyed with the day key
that is never written, so a restart (a deploy) forgets them and gives each network a fresh day; the
deployment's ceilings survive it. The brakes slow a griefer to the deployment's daily pace and make it
visible; they don't stop someone with many networks: a botnet, or anyone with an IPv6 /32 (65,536 /48s),
can still make drives and fill free space at 6 GiB a /48 a day, and can take the day's public packs;
three networks an hour can hold them with unpaid invoices, which free up when they expire (an hour).
Judges' purchases may spill into the public slice by design (at most 10 a day). What
protects the disk itself are the hard freezes in `quota.py`: free uploads pause when free disk falls
within 2 GiB of the reserve, and all uploads within 256 MiB; files already stored are never deleted to
make room. `deploy/README.md` ("If someone games the packs") is the operator's side.

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

## Uploads are inert

The server can't tell ciphertext from anything else, so every uploaded byte is opaque to it. A client may send an
executable, a script or a web page in place of ciphertext; on the server nothing happens to it.

- **Nothing reads the bytes.** The API writes each chunk where it belongs and checks only its length and SHA-256.
  It never decodes, unpacks, sniffs, previews or runs a stored file, and hands it to no other program; a test keeps
  decoders and process launchers out of the API's code (`server/tests/test_uploads_inert.py`).
- **Nothing from the client names a file.** A stored file's path comes from the server's own random id; no file
  name, type or path from a request reaches the disk.
- **Nothing there can run.** Each file is `0600` under `0700` directories, on a mount with `noexec`, `nosuid` and
  `nodev`: the kernel refuses to execute it or map it as code, even for root, through the dynamic loader too. Every
  service sees what it can write as `noexec` and the rest of the system read-only, runs without new privileges or
  capabilities (Caddy keeps only the one to bind ports 80 and 443), behind a system-call filter, and without
  writable code where its runtime allows that.
- **Nothing renders them on this site.** Stored bytes leave only through the API, as `application/octet-stream`
  attachments with `nosniff` and a sandboxed content security policy, so a browser saves them rather than showing
  them; the web server itself can't read the directory.
- **They are bounded.** Size limits per kind of link, lanes, quotas, daily brakes per network and a body limit at
  the web server; uploads stop while the disk still has its reserve, and a full disk refuses an upload with 503
  while the API keeps answering.
- **Not scanned.** The server holds ciphertext, so a malware scanner would only see random bytes, and parsing
  untrusted files is the risk this design avoids. A file is as safe as its sender for the person who opens it; the
  app warns before programs.

`deploy/scripts/privilege-check.sh` checks the mount, the modes and every service's view on the live server;
`docs/review/upload-safety-1.md` has the evidence.

## Previews

Anyone can send a file to someone's drive (a drop link, Send by Tari, a shared folder saved there) or sell one on a
paid link, so the bytes a preview shows are a stranger's, and a script that ran on hidebox.app could read the keys
this browser holds. What the API sends stays ciphertext and a download ("Uploads are inert" above); the preview is
about what the page shows once it has decrypted a file. It reads the decrypted bytes and never the file's name or
stored type (`web/app/lib/sniff.js`, `web/app/ui/lightbox.js`):

- **Pictures** (PNG, JPEG, GIF, WebP, AVIF, by their first bytes) show in an `<img>` from a Blob of exactly that
  type. An image runs no script and loads nothing, and opened on its own it is still only a picture.
- **SVG** is drawn once into a canvas from an image that never joins the page, and its `blob:` address is revoked
  before the canvas shows: what remains is pixels, with no SVG document and no address anyone can open as a page. An
  SVG with internal entities, over 4 MiB, or not wholly UTF-8 is download only.
- **Text** (UTF-8 without NUL bytes) shows as one text node in a `<pre>`, its first 256 KB; Markdown stays its own
  characters, never HTML or links.
- **Everything else is download only:** HTML and any file that starts with markup, whatever its name; PDF, sound,
  video, fonts, archives, programs and empty files. Download saves an `application/octet-stream` Blob through a link
  with `download`; nothing opens a window or navigates to a file.
- **The content security policy did not change:** no inline script, and images only from this site, `blob:` and
  `data:`.
- **Every place a file opens uses it:** a drive's file, a folder visit (`/s/` and paid folders), a paid file, a
  single-file link (`/s/`, `/t`) and a single file in Received. Nothing in the app chooses what to show by a file's
  stored type any more (`lib/preview.js` is gone), and sound and video are download only there too.

The core suite (`web/app/tests/preview.test.js`) and the UI suite (`preview-drive`, `preview-folder`, `preview-pay`,
`preview-link`, `preview-received`)
open hostile files (an SVG with scripts named `.png`, a web page named `.txt`, a GIF with a web page after it,
Markdown with scripts and `javascript:` links) and check that nothing runs, nothing is fetched and nothing navigates;
`docs/review/preview-1.md` has the table. What remains: a flaw in the browser's own decoders, and a very large or
deeply nested SVG can keep the opener's tab busy while it draws.

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
- Metadata: padded size, arrival hour, exit rule, open counts per hour, a drive's folder shape, and your IP address while you're
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
checkout, downloads every file in the live manifest (and each text file again as gzip and Brotli, decoded) and
prints any difference, and checks the live SealLog's template. Assets have the hash of their content in their
names and are cached a year (docs/review/perf-1.md): a page that revalidates names the new files after a release,
and an old name can never be served new bytes. Since SealLog went on, each release's manifest hash is notarized through it
(`/releases.json`); anyone can call `notarize`, so only events signed by the log's writer key count.
The rebuild takes the deployment's public settings (`repo_url`, `security_drop`) from its `/api/v1/config`;
verify-deploy refuses any that isn't a plain https URL as a difference, so a server can't make markup of
its own part of the build it is compared against (`docs/review/security-audit-1.md`).

## Known incidents

- 2026-10-11, during setup: walletd rejected a config value and printed it, so the testnet wallet's
  keyring password appeared once in the server's journal (purged within minutes; a search of the
  journal and `/var/log` then found nothing) and in the build session's transcript. It only opens
  the testnet wallet's database, which never leaves the server; a mainnet wallet would be new, with a
  new password.
- 2026-10-11, at go-live: one of the two public indexers kept answering while its UTXO stream stopped
  advancing, so deliveries didn't reach the mirror. The chain worker now mirrors every indexer, each
  with its own cursors.
