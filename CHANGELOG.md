<!-- SPDX-License-Identifier: MIT -->
# Changelog

## 2026-10-12: fix pass after the judge-run and claims reviews (docs/review/fix-log.md)

- Direct sends: the send screen says, before Send, whether this send goes from the browser's wallet or
  through our relay, and refreshes while you wait; the wallet is scanned before each decision, so a
  grant that has landed is found. Two sponsor grants a day per /64 (a phone and a computer on one
  network). The site's direct-mode sentences carry the condition (grant first, relay until then).
- `/judges` and `/pricing` name the button each send mode shows; `/judges` B1 has the computer open its
  locker early; a judge pass can be handed out as `/judges#pass=…` and is kept on the device for a week.
- Expiries at least an hour away are stored rounded up to the hour (an exact one gave the arrival second
  away); the ended-link body no longer carries the open count; copy on the link path, logs, SRI and
  invoice addresses made literally true; README describes both send modes.
- App: receipts on `/verify` say when the file was locked and where it went; inbox rows show when a
  delivery was found and whether it has made its exit; the header offers "My locker" once one exists;
  payment steps show the check in ink and lime only when the chain confirmed; app pages are one centred
  column on wide screens; the home page's indexer link follows the indexer that holds the receipt.
- The submit proxy (`POST /chain/ix/transactions`) takes a locker session and relays only a transaction
  shaped like the app's own send, read back from its BOR envelope (one stealth transfer paying its own
  fee of at most the courier fee, one output plus change, up to four inputs, no other instruction,
  12 KB at most): it is no relay for other Esmeralda transactions.
- The web server answers a request body declared over 5 MB with a 413 in the API's error shape (the
  app names the limit instead of "our server tripped"), and any other Host name with a 421 that
  carries the security headers, on both ports.
- Root's go-live and pre-migrate database copies under `/var/backups/mutis` are deleted at the
  published 7 days by the backup unit's first step; wallet tars, balance snapshots and config copies
  are never touched.
- Copy made literally true: the FAQ says the program rule lives in the app (our server can't see file
  types); the snapshot sentence says our host can keep weekly snapshots, that we haven't switched them
  off and haven't yet confirmed the retention in its panel.

## spooky-secrets-2026-10 (2026-10-11): first public release

Live at <https://srv2052606.hstgr.cloud> on the Esmeralda testnet.

- Files and text locked in the browser (AES-256-GCM, Padmé padding, 4 MB chunks), shared by link with
  the key after the `#`: once, a number of opens, an expiry, link + password or password only.
- Lockers made in the browser (no email): dead-drop links that deliver a file's key to the locker
  inside a stealth payment, sending to any Tari address, an inbox that scans the chain in the browser,
  a view-key page that sees deliveries and opens no file, packs paid in tTARI and credited after the
  official Tari library proves the amount.
- SealLog 2.0.0, published from this repository's exact bytes, with a checkpoint every 15 minutes:
  inclusion proofs for every stored file and every exit, checked by `/verify` against the component's
  state on the Ootle; each release's manifest hash notarized through it.
- An hourly canary sealed by our own code and delivered on chain, its key published a day later;
  `/evidence.json` lists our own test transactions; `/status` shows the health checks.
- Site in English and Spanish, the judges' guide at `/judges`, the threat model at `/security`.
- Go-live fixes: a fresh database is created group-writable for the API and the chain worker; the
  health check asks the verifier whether it runs; the UTXO mirror reads every indexer (one stopped
  advancing its stream while still answering).
