<!-- SPDX-License-Identifier: MIT -->
# Changelog

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
