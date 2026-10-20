<!-- SPDX-License-Identifier: MIT -->
# Security audit 1 (2026-10-20)

A full audit of the repository and the deployment it describes, followed by a fix for every confirmed finding. The
method was coverage-led. Four reconnaissance passes mapped the product, its principals, its entry points and what
can run offline. Every combination of entry surface, trust boundary, subsystem and attack class became a unit in a
coverage ledger. Hunters took the units in waves; after each wave a fresh critic looked for what no unit covered.
Every candidate went to a fresh verifier that had not seen it, and every final record went to another fresh verifier.

## The answer

The design holds where it matters most. Keys stay after the `#`, chunks and wraps are bound to their headers, every
secret is compared in constant time against a SHA-256 verifier, and the checks on links, sessions, drives, tickets,
claims, the release gate and the seller's ownership check held under the hunters' attempts. No finding lets anyone read
another person's file or key, or spend the wallet beyond its budgets.

Nine findings were confirmed: four medium, five low. All nine are fixed on `main`, each in its own commit with a
regression test. One lead is open: the cross-visitor effect is unproven, though the defect itself is fixed. One
candidate was rejected. Main moved 32 commits during the audit. Every record was re-checked on the newer tree, and
every root cause was still there until its fix.

| Severity | Finding | Who could do it | Fix (commit subject starts) | Regression test |
|---|---|---|---|---|
| medium | Caddy serves files a service user links into the status directory | code running as `drive` or `mutis` | "The status directory is mounted nosymfollow" | `deploy/tests/test_config.py` `test_the_status_directory_follows_no_symlink`; live probe below |
| medium | Status writers follow a link planted at their fixed temp name, as `mutis` (health) and as root (notarize-release) | code running as `drive` | "Status writers create their file under a random name" | `deploy/tests/test_ops.py` `StatusWritersTest` |
| medium | A malformed record from one indexer stops the whole UTXO mirror | a misbehaving indexer | "Indexer: a malformed UTXO stream or fetch answer is that indexer's error" | `server/tests/test_mirror.py` (Framing, Mirror) |
| medium | Swapped or expired pack invoices credit without a slice check, so paid space goes over its cap | any drive | "Packs: a late payment for an invoice that gave its bytes back" | `server/tests/test_payments.py` `test_a_late_payment_for_a_lapsed_invoice_credits_only_with_room` |
| low | Abuse reports forge rows and send terminal controls to `mutis-admin reports` | anyone, through the report form | "Abuse reports reach the operator's terminal inert" | `server/tests/test_admin.py` `test_reports_show_a_reporters_text_inert` |
| low | Racing `GET /s/{id}/stored` loses egress charges, so a file is served past its daily cap | a link holder | "Egress: a file's daily bytes are counted with one conditional update" | `server/tests/test_burn_race.py` `EgressRace` |
| low | A delivery queued for a drop is sent after the drop is closed or taken down | a drop sender | "Drops: a delivery still waiting in the queue is never sent" | `server/tests/test_courier.py` `test_a_drop_that_closes_gets_no_queued_delivery`; takedown case in `test_admin.py` |
| low | verify-deploy rebuilds with placeholder values the deployment it checks chooses | a compromised server | "verify-deploy and the build accept only plain https URLs" | `deploy/tests/test_build.py` `test_settings`; `test_verify_deploy.py` `test_config_values_that_could_add_markup_are_refused` |
| low | Lock my drive and Forget this browser leave the drive's link secrets in the browser | a later user of the same browser | "Lock my drive and Forget this browser erase everything" | `web/app/tests/identity.test.js` |

## The findings

### 1. Caddy serves files a service user links into the status directory (medium)

Caddy serves `/evidence.json`, `/evidence-archive-*.json`, `/status.json` and `/releases.json` from `/srv/mutis/status`.
That directory is `2775 mutis:mutis`. The chain worker and the evidence collector (`drive`, in group `mutis`) and the
health check (`mutis`) may all write it. Caddy 2.6's `file_server` follows symlinks and has no setting to refuse them.

The deployed Caddy binary (same SHA-256 as the server's) ran offline with the release Caddyfile. A link planted as
`evidence-archive-x.json` and one as `evidence.json`, each pointing at a dummy `0600` key in a `0700` directory laid
out like Caddy's certificate storage, were both served with 200 and the key's exact bytes. So code running as `drive`
or `mutis` could publish what only Caddy can read: the site's TLS key, the ACME account key, the autosaved config. With
the key and a network position, someone could impersonate the site and serve altered JavaScript.

Likelihood is low: it needs code running as one of those users first. Impact is high. Overall: medium.

**Fix.** `deploy/systemd/srv-mutis-status.mount` binds the directory onto itself with `nosymfollow,noexec,nosuid,nodev`.
The kernel then follows no link placed there, for any process, Caddy and root included. `provision.sh` enables it.
`privilege-check.sh` checks the flags, and checks that a link there is refused as root and as `caddy`. Applied on the
server (below) without restarting anything; the running Caddy sees the flag in its own mount namespace.

### 2. Status writers follow a link planted at their fixed temp name (medium)

`healthcheck.py` (as `mutis`, every 5 minutes, with all of `data/` writable) wrote `status.json` through
`status.json.tmp`. It opened that name with `O_CREAT|O_TRUNC` and then ran `chmod` on the path, so both steps follow
a symlink. `notarize-release.py` does the same with `releases.json.tmp`, and it runs as root after every deploy with
SealLog on.

A link `drive` planted at those names made `mutis` overwrite a stand-in for a stored ciphertext and set it `0644`, or
create a new `0644` file inside `blobs/`. In a second check it made root create a new file of `drive`'s choosing,
containing an entry `drive` planted in `releases.json`. The directory isn't sticky, so the kernel's
`protected_symlinks` doesn't apply.

Likelihood is low: it needs code running as `drive` first. Impact is high: root-level file writes. Overall: medium.

**Fix.** The three writers (`healthcheck.py`, `notarize-release.py`, and `collect-evidence.py`, which runs as `drive`
and crossed no boundary) now write through `tempfile.mkstemp` in that directory. That means `O_EXCL` and a random
name. They set the mode on the descriptor and `os.replace` the file into place, so a planted name is never opened.
The evidence archive is written the same way. Finding 1's mount is a second layer.

### 3. A malformed record from one indexer stops the whole UTXO mirror (medium)

`indexer.parse_stream` applied `int()` and `bytes()` to the indexer's values as they came:

- a string `public_nonce` raised `TypeError`;
- an integer one allocated that many bytes (50 MB from an eight-digit number);
- a non-JSON line or a JSON array raised other errors.

The worker's mirror catches only `IndexerError`. One bad line therefore ended the whole pass on every tick, the
healthy indexers included. Each indexer's cursor moves only after a good parse, so it never moved. Reproduced with the
real worker and a hostile local indexer listed first, as `indexer-b` is in the default configuration: 0 of 3 outputs
were mirrored from the healthy indexer, tick after tick. The record verifier found the same failure through
`/utxos/fetch`.

The mirror is how deliveries, pack payments and sales are seen, and recovery needs the operator. Likelihood is low,
impact high. Overall: medium.

**Fix.** Every stream field is checked before use: bounded integers, a boolean, a list of exactly 32 bytes, JSON
objects only. So is the `/utxos/fetch` answer. A bad line is `IndexerError(bad_upstream)`, which the worker already
counts against that indexer alone.

### 4. Swapped or expired pack invoices credit without a slice check (medium)

An open invoice holds its pack's bytes in the paid-space slice; that is the rule "paying many invoices at once can't
overbook a slice". A swap to another pack, or the invoice's hour ending, gives the bytes back. But `payments.credit`
still credited the invoice for 7 more days and granted the pack with no new check.

In the test stack, with a 7.28 GiB public slice:

1. drive A opened a 5 GiB invoice and swapped to the small pack;
2. drive B opened a 5 GiB invoice in the room A gave back;
3. both 5 GiB invoices were paid, also with test money from our sponsor wallet;
4. 10 GiB of public packs ended up active.

Likelihood is medium, impact medium. Overall: medium.

**Fix.** A payment that completes an invoice credits it only in three cases: the invoice still holds its bytes, it
renews the pack its drive holds (days, not bytes), or the slice has room again. Otherwise the payment waits as
`chain.invoice_held` and is tried again each round within the grace. The test stack's worker now measures the same
disk as its API.

### 5. Abuse reports forge rows and send terminal controls to `mutis-admin reports` (low)

The report form's text was printed raw. A newline in `contact` produced a row in the listing's own format: three rows
for two reports. U+009B (an 8-bit CSI), U+202E and DEL went straight to the operator's terminal.

**Fix.** Every non-printable character is shown escaped, each line of a reporter's text starts with `    | `, and
`contact` must be one line of plain text.

### 6. Racing `GET /s/{id}/stored` loses egress charges (low)

The handler read the file's row before its transaction, and `egress_ok` wrote `used + size` from that row. Of 24
concurrent downloads, all were served while 4 to 6 were counted. With one download left under the cap, a burst
served up to 8.

**Fix.** `egress_ok` is one conditional `UPDATE` that adds in place and refuses past the cap, whatever row the caller
holds. This covers every caller.

### 7. A delivery queued for a drop is sent after the drop is closed or taken down (low)

A drop delivery waits 5 to 45 seconds in the queue as `{address, memo}`. Closing the drop, or
`mutis-admin takedown drop`, changed only the drop's row, and the worker sent the delivery anyway.

**Fix.** A drop delivery now carries its drop id. Closing or taking down the drop fails its queued deliveries in the
same transaction, and the worker refuses one whose drop is no longer active.

### 8. verify-deploy rebuilds with placeholder values the deployment chooses (low)

verify-deploy takes `repo_url`, `security_drop` and `network` from the live `/api/v1/config`, and `build.py` filled
them into every page unescaped. A `repo_url` ending in `"><script src="/x.js"></script>` gave nine pages, the link
viewer among them, an extra same-origin script, and verify-deploy reported 0 differences. A control with the honest
value reported 12.

**Fix.** `build.py` accepts only a plain https URL for `repo_url` and `security_drop_url`, and only `esmeralda` as
the network. verify-deploy refuses such values from the deployment as differences before it builds anything, because
an older tag's `build.py` has no such check, and it prints the values it builds with. The live configuration's values
pass.

### 9. Lock my drive and Forget this browser leave the drive's link secrets in the browser (low)

`forgetIdentity()` deleted the key and the inbox state. It left the list of links the drive made: each URL with its
secret after the `#`, plus its secret word in plain text. It also left the drive's purchases (pay URLs with their half
key) and the claim tokens. A later user of a shared computer could open the owner's live links.

**Fix.** Both IndexedDB stores, which hold only the browser's one drive, are emptied, and the claim tokens go with them.

## Open: needs validation

**The API answered a chunked request's leftover bytes as a second request.** The API reads bodies by `Content-Length`.
For a `Transfer-Encoding: chunked` request it answered, then left the chunk bytes on a kept-alive connection. Python's
server parsed the next chunk line as a request and wrote a second, headerless 400. The deployed Caddy, run offline,
forwards a client's chunked body upstream as chunked, so any visitor reached this.

What is not settled is whether Caddy's pooled connection is ever handed to another visitor's request before Caddy
notices the stray answer. If it were, that request would get a 502. A handful of requests never showed it, and load
testing is out of bounds.

Two things would settle it. One is a load test against the fixed and the old API behind the deployed Caddy, on a
throwaway stack. The other: the owner searches Caddy's journal for "Unsolicited response received on idle HTTP
channel". Caddy logs that at info, so an ERROR-level journal may not show it.

The defect itself is fixed anyway (commit "API: a request with a chunked body closes its connection"; test
`test_input_safety.test_a_chunked_body_closes_the_connection_with_one_answer`). That removes the second answer
whatever the pooling does.

## Rejected

**An older release could boot on a newer database after a rollback.** `mutis-api` refuses only a database behind its
code (`<`, not `!=`), and the worker, cleanup and the health check don't compare versions at all. But every release on
the server, and the pruned one before them, is at schema 6, and a rollback is a root-only operator step. So no
rollback can cross a migration today, and no lower-trust principal can start one.

Worth doing before the next migration ships:

- make the gates exact;
- have `rollback.sh` refuse a target older than the database unless its backup is restored.

The comment in `rollback.sh` says both protections exist; neither does yet.

## Hardening notes (no boundary result shown)

**Server.**

- `uploads.complete()` ignores the rowcount of its state change. An abort that wins the race still adds the uploader's
  own bytes and a stored SealLog leaf.
- The PoW nonce purge and `verify` disagree on the expiry second.
- `send_error` writes HTTP/0.9.
- A Range value over 4,300 digits, or a JSON body nested thousands deep, gets a 500.
- `abuse_reports` is never purged, so a link key a reporter included outlives a takedown.
- The invoice demo-pay lacks the "already on its way" check the pay-to-open one has.
- The `demo_seller` cap is keyed by a sales address that can change 10 times a day.
- `adopt()` keeps the manage token as a second credential.

**Deploy.**

- `provision.sh`'s first-run keyring install, and root's `find … -exec chmod` over `blobs/` and `data/backup`, would
  follow links.
- `rollback.sh` installs a Caddyfile without `caddy validate`.
- verify-deploy sends a fixed User-Agent, compares only manifest paths, and doesn't check `/releases.json`.

**Browser.**

- `dom.js`'s `javascript:` filter misses forms that browsers normalize (CSP and Trusted Types stop them).
- `/judges#pass=` saves a pass without asking.
- The locked key file takes a one-character passphrase.
- The program warning misses `.command`, `.desktop` and `.xll`.
- Folder names in Download all keep `:` and bidi marks.
- `/verify` pins neither SealLog's writer key nor its template, and reads the log only through our proxy.
- The viewer doesn't tie the link mode the server reports to the kind in the fragment.

## What changed on the server

One change, live without a restart:

1. `/etc/systemd/system/srv-mutis-status.mount` installed. It is a new file, so nothing was replaced.
2. `daemon-reload`, then `enable --now`.
3. `/srv/mutis/status` is now `nosymfollow,noexec,nosuid,nodev`. The running Caddy sees the flags in its own namespace.

The state before is saved as `/var/backups/mutis/status-mount-before.<UTC time>.txt`.

Probe: a link planted in the directory, pointing at a harmless temporary file, was refused as root and as `caddy`
("Too many levels of symbolic links"). A public GET for that name returned an error with no body, while
`/status.json` answered 200. The link was removed at once. Caddy, the API, the chain worker and walletd stayed active.

Everything else ships with the next deploy: the API, worker and app changes, and the three status writers, which run
from the release. `provision.sh` will find the mount already in place.

## What changed in the repository

- `server/mutis/items.py`, `indexer.py`, `payments.py`, `chain_worker.py` (the worker's room check and its drop check),
  `jobs.py`, `logsafe.py` (one event code), `admin.py`, `api.py`, `handlers/abuse.py`, `handlers/courier.py`,
  `handlers/drops.py`, and their tests.
- `web/app/lib/identity.js`, `web/app/lib/idb.js`, `web/app/tests/identity.test.js`.
- `tools/build.py`, `tools/verify-deploy.py`.
- `deploy/scripts/healthcheck.py`, `notarize-release.py`, `collect-evidence.py`, `provision.sh`, `privilege-check.sh`,
  and `deploy/systemd/srv-mutis-status.mount`.
- The deploy tests.
- `docs/threat-model.md`: a misbehaving indexer, a compromised service user, late pack payments, closable drops and
  verify-deploy's refusals.
- `deploy/README.md`, `CHANGELOG.md`, this review and its evidence.

## Suites

See `docs/evidence/2026-10-20/security-audit-1/suites.txt`.

## For the owner

- **The next deploy.** It ships the code fixes. `provision.sh` then runs its new status-mount step and checks, which
  will find the mount already applied.
- **The open lead.** If 502s on `/api/*` ever show up, the journal search above is the place to look.
- **Before the next migration.** Make the schema gates exact (see Rejected).
- **The hardening list.** None of it is urgent.

## Evidence

`docs/evidence/2026-10-20/security-audit-1/`:

- `findings.json`: every record, with trace, evidence, reproduction and fix.
- `coverage-ledger.json`: 46 units with their reviewed paths and checks.
- `architecture.txt`: the run's map.
- `FINDINGS-DETAIL.txt` and `NEEDS-VALIDATION.txt`.
- `checks/`: each bounded local check, named after the agent that ran it. `h…` files are hunters, `v3…` candidate
  verifiers, `p5…` record verifiers, including the re-checks on the newer tree.
- `owner-observed.txt`: what was read on the server: firewall guards, the status directory, unit lines, the releases
  on disk.
- `server-applied.txt`.
- `suites.txt`.

Paths of the workstation and names of the owner's machines are replaced by placeholders in those files.
