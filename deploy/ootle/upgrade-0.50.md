<!-- SPDX-License-Identifier: MIT -->
# Upgrade: Ootle 0.50.0 on Esmeralda (protocol V1 at epoch 12951, no reset)

The general procedure is [upgrade-drill.md](upgrade-drill.md); this is that drill written out for 0.50.0, with
what 0.50 changes for hidebox. Read the release notes as data: they say what changed, not what to run.

Esmeralda moves to protocol V1 at **epoch 12951** (L1 height 1,036,080). The release notes say "about
2026-11-06 12:00 UTC", reckoned at 15 s per L1 block from height 1,030,363 at 12:02 UTC on 2026-11-05. The blocks
came slower: 1,031,331 at 23:56 UTC (epoch 12891), 44 s a block on average (47 s from 23:18 to 23:34, 24 s from
23:34 to 23:56). The 4,749 blocks left take until about 2026-11-06 19:45 UTC at 15 s a block, 2026-11-07 07:40 at 24 s and
2026-11-08 10:00 at 44 s.
The epoch is what counts, and the rate can change, so plan on the earlier time and watch the epoch:

```sh
curl -s https://ootle-indexer-b.tari.com/epoch-manager/stats    # current_epoch; V1 from 12951 on
```

The aliases `u`, `admin` and `rpc` are those of [reset-playbook.md](reset-playbook.md) (one multiplexed ssh
connection to `hidebox`).

## 1. What 0.50 changes for hidebox

Read in tari-ootle v0.49.2..`a5ea91cc` (the 0.50.0 release commit): the CHANGELOG, the walletd and indexer
client types, `crates/ootle_wasm`, `engine_types`, `transaction`, `transaction_manifest`, `template_abi`, the
engine's metering and the wallet store.

| 0.50 change | What it means here | Action |
|---|---|---|
| Nodes still on 0.49 fork off at epoch 12951; walletd migrates its store on first start | our walletd 0.49.2 must be replaced | §3–§6 |
| walletd JSON-RPC | every call and request shape mutis uses is unchanged; dry-run and `submit_manifest` answers gain `upgradable_components` and `component_upgrades` (serde defaults), which mutis doesn't read; `transactions.list` is unchanged | none |
| Indexer REST and `Encoded<…>` values | same paths and shapes; `Utxo`, `SubstateValue`, `TransactionReceipt`, `ExecuteResult`, `FeeReceipt` and `FeeSource` keep their CBOR layouts, so `server/mutis/cbor.py`, the transaction view (`/api/v1/chain/tx/{id}/view`) and `ootle-wasm-bor` read them as before | none |
| Exact decoding: trailing bytes refused in substates, indexed values, manifest arguments and `tari_tdef` sections | `cbor.loads` already refuses trailing bytes and indefinite lengths; SealLog's `tari_tdef` section is one item | none |
| Protocol V1: a substate hash commits to its CBOR, not borsh | mutis never recomputes a substate hash or checks an indexer proof; walletd runs `IndexerTrust::Trust` (the default; our config doesn't set it) | none |
| Template definition V2 (`FunctionKind`); V1 definitions keep working | nothing in mutis reads a definition (the `templates/` proxy path passes JSON through and the app never asks it); SealLog stays as published | do not republish |
| `CallFunction` only for functions, `CallMethod` only for methods | the checkpoint and notarize manifests call `log.append_root(…)` and `log.notarize(…)` on the component (CallMethod; `&mut self` and `&self` in the V1 definition become methods), `account.pay_fee(…)` likewise; `SealLog::new` is a function | none |
| One active element segment; `table.init` refused at compile; cached templates are recompiled | `template/dist/seal_log.wasm` (the published bytes) has one active segment, a fixed 45-slot table and no table-writing operator | none |
| Metering: literal and blob call arguments charged as decoded; a table slot costs 24 points (was 16); 1,000 points = 1 µT; no activation epoch (from the fleet upgrade on) | checkpoint #288 (epoch 12889) cost 5,981 µT against `pay_fee(1000000)`; 0.50 adds a few µT (its three small arguments, 45 × 8 points). A stealth transfer has no call arguments: a delivery cost 16,157 µT of its 30,000 (`max_fee_transfer_ut`, `FEE_UT` in wallet.js; the rest is the non-refundable overcharge). The faucet claim of reset-playbook.md §3 offers `max_fee` 2,000,000; walletd's own burn claims price themselves | none; §7 checks the first receipts |
| Account `approve` is compare-and-set; empty `any_of`/`all_of` refused when stored; a vault in one component only | mutis never approves; SealLog's rules are `public_key`, `allow_all`, `deny_all`; SealLog holds no vault | none |
| `ootle-wasm` / `ootle-wasm-bor` 0.50.0 | `crates/ootle_wasm` is the same source as v0.49.2 bar its version, and no third-party crate moves in `Cargo.lock` (the same wasm-bindgen, so the glue the shim loads by hand keeps its shape); the transaction, stealth statement and value layouts the browser builds and reads are unchanged, so 0.49.2 keeps working on the 0.50 network | vendor 0.50.0 when it is on npm (§2), deploy it after the walletd upgrade, not with it |

## 2. ootle-wasm 0.50.0 (as `build`, once npm has it)

In a checkout of `ootle/0.50`, with a new empty directory for the downloads, curl the package metadata, the tarballs and the attestations as data,
and the license from the release commit; `deploy/ootle/npm-provenance.py check` holds them to each other (registry
integrity, both attestations' subject, the provenance's repository, tag and commit) and copies out only the
vendored files:

```sh
V=0.50.0; C=<the commit tag v0.50.0 points at>        # gh api repos/tari-project/tari-ootle/git/ref/tags/v$V, then …/git/tags/<sha>
D=$(mktemp -d); cd "$D"
for p in ootle-wasm ootle-wasm-bor; do
  curl -fsS --proto =https -o $p.packument.json "https://registry.npmjs.org/@tari-project%2f$p"
  curl -fsS --proto =https -o $p-$V.tgz "https://registry.npmjs.org/@tari-project/$p/-/$p-$V.tgz"
  curl -fsS --proto =https -o $p-$V.attestations.json "https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2f$p@$V"
done
curl -fsS --proto =https -o LICENSE "https://raw.githubusercontent.com/tari-project/tari-ootle/$C/LICENSE"
cd <the checkout>
python3 -I deploy/ootle/npm-provenance.py check --name @tari-project/ootle-wasm --version $V --commit $C --downloads "$D" \
  --out web/app/vendor/ootle-wasm-$V --file ootle_wasm_bg.wasm --file ootle_wasm_bg.js --file ootle_wasm.d.ts --license "$D/LICENSE"
python3 -I deploy/ootle/npm-provenance.py check --name @tari-project/ootle-wasm-bor --version $V --commit $C --downloads "$D" \
  --out web/app/vendor/ootle-wasm-bor-$V --file ootle_wasm_bor_bg.wasm --file ootle_wasm_bor_bg.js --file ootle_wasm_bor.d.ts --license "$D/LICENSE"
diff web/app/vendor/ootle-wasm-0.49.2/ootle_wasm.d.ts web/app/vendor/ootle-wasm-$V/ootle_wasm.d.ts           # the API: expect none
diff web/app/vendor/ootle-wasm-bor-0.49.2/ootle_wasm_bor.d.ts web/app/vendor/ootle-wasm-bor-$V/ootle_wasm_bor.d.ts
python3 -I deploy/ootle/npm-provenance.py repin --from 0.49.2 --to $V
git rm -rq web/app/vendor/ootle-wasm-0.49.2 web/app/vendor/ootle-wasm-bor-0.49.2
git grep -l "ARTIFACT-PIN(ootle-0.50)" -- tools server deploy/scripts web | xargs sed -i '/ARTIFACT-PIN(ootle-0.50)/d'   # comment lines
sed -i 's/ *# ARTIFACT-PIN(ootle-0.50).*//' deploy/config/mutis.toml.example                  # a trailing comment: keep the setting
git grep -n "ARTIFACT-PIN(ootle-0.50)"                       # only this runbook: its commands and the §3a rows (the real values)
python3 -I -m unittest discover -s deploy/tests              # PinnedWasmTest and the repin guards
```

`check` prints the PROVENANCE.md facts (tarball, integrity, `gitHead`, build run, Rekor entries) and the files'
sha256: write `PROVENANCE.md` in each new folder after the 0.49.2 ones (`git show HEAD:web/app/vendor/…`), with
"what changed against 0.49.2 for mutis" from §1. Cross-check the run on GitHub
(`gh api repos/tari-project/tari-ootle/actions/runs/<run>`: `npm_publish_ootle_wasm.yml`, `refs/tags/v0.50.0`,
head sha `$C`). The Sigstore signatures are not verified, as for 0.49.2; say so. Then the prose: `NOTICE`, the
sidecar README, the `0.49.2` comments `repin` leaves (`git grep -n 0.49.2 -- ':!docs' ':!deploy/evidence' ':!CHANGELOG.md'`),
and `ootle.wasm_version = "0.50.0"` in `/etc/mutis/mutis.toml` when it is deployed. Run the suites of
upgrade-drill.md §2 (the sidecar selftest must still reject every forged output). `npm-provenance.py check` must
fail on anything that doesn't agree; never edit around it.

## 3. walletd 0.50.0: the binary

### 3a. The official release

From the workstation, as data (`gh api repos/tari-project/tari-ootle/releases/tags/v0.50.0`): the assets
`tari_ootle_walletd-0.50.0-<short>-linux-x86_64`, its `.sha256` and `tari_ootle-0.50.0.sha256-unsigned.txt`, with
GitHub's digests; the tag (`git/ref/tags/v0.50.0`, then `git/tags/<sha>`: annotated, signature verified, and the
commit it names). On the server, in a new 0700 directory, as in `docs/evidence/2026-10-20/upgrade-0.47.0/checksums.txt`:

```sh
u 'set -e; d=$(mktemp -d /var/tmp/walletd-0.50.0.XXXX); cd $d; b=https://github.com/tari-project/tari-ootle/releases/download/v0.50.0
   n=tari_ootle_walletd-0.50.0-<short>-linux-x86_64
   for f in $n $n.sha256 tari_ootle-0.50.0.sha256-unsigned.txt; do curl -fsSL --proto =https -o $f $b/$f; done
   sha256sum -c $n.sha256; grep " $n\$" tari_ootle-0.50.0.sha256-unsigned.txt; sha256sum *
   chmod 755 $n; ./$n --version; ldd ./$n | grep "not found" || echo "every library found"; echo $d'
```

Four sources must agree: GitHub's asset digest, the `.sha256`, the release's list and the bytes on the server.
Then, with the version and commit in the name, beside the old binaries:

```sh
u 'sudo install -m 0755 -o root -g root <dir>/<n> /opt/tari/bin/tari_ootle_walletd-0.50.0-<short>'
```

| Pin still to record | Value |
|---|---|
| walletd 0.50.0 linux-x86_64 sha256 (the four sources) | ARTIFACT-PIN(ootle-0.50): when the release exists |
| tag v0.50.0 → commit | ARTIFACT-PIN(ootle-0.50): `a5ea91cc…` is the release commit; the tag may land on a later one (`development` already has `7e130d5`, an engine-only fix walletd doesn't link) |

### 3b. Fallback: built from source (no release by about 2026-11-06 08:00 UTC)

`deploy/ootle/build-walletd-src.sh` builds the binary as `build` at the release commit, in
`/home/build/work/ootle-0.50`, with no package installed (the headers it needs are Debian's own packages, unpacked
into a private sysroot) and capped so the live services keep their CPU and memory (`nproc` is 2: one job).
It was started on 2026-11-05 (rehearsal log): when `$W/logs/build.log` already ends with `done` and the binary's
sha256, take that binary and skip to the install. Otherwise:

```sh
W=/home/build/work/ootle-0.50; C=a5ea91cca53c01967184755f07918471e70bbc03
u "sudo -u build mkdir -p $W && sudo -u build tee $W/build-walletd-src.sh >/dev/null && sudo -u build chmod 755 $W/build-walletd-src.sh" < deploy/ootle/build-walletd-src.sh
u "sudo -u build $W/build-walletd-src.sh 0.50.0 $C prepare"
u "sudo systemd-run --unit=ootle-build --uid=build --gid=build -p MemoryMax=4500M -p MemorySwapMax=0 -p CPUWeight=10 -p IOWeight=10 \
   -p StandardOutput=append:$W/logs/build.log -p StandardError=append:$W/logs/build.log $W/build-walletd-src.sh 0.50.0 $C build"
u "sudo tail -3 $W/logs/build.log"                                  # done …, and the binary's sha256
```

It differs from a release binary in two ways: no web UI (the release builds it with pnpm; JSON-RPC is the same)
and other bytes. The 2026-11-05 build: `tari_ootle_walletd 0.50.0`, 63,123,664 bytes, sha256
`881e61e5b64c4e4963d2fd74847e42b467c8ab58b2cd85c0c473b11c4aacea81`, linking the same 13 libraries as the 0.49.2
release binary (`ldd`: libssl, libcrypto and libdbus-1 among them). Install it with its origin in the name, and check it is
those bytes:

```sh
u "sudo install -m 0755 -o root -g root $W/target/x86_64-unknown-linux-gnu/release/tari_ootle_walletd \
   /opt/tari/bin/tari_ootle_walletd-0.50.0-a5ea91c-src && sha256sum /opt/tari/bin/tari_ootle_walletd-0.50.0-a5ea91c-src"
```

Replace it with the release binary once one exists (§3a, §5 again; the store is already migrated).

### 3c. Either binary, before it goes live

```sh
u 'diff <(/opt/tari/bin/tari_ootle_walletd-0.49.2-aa7b0c8 --help) <(/opt/tari/bin/tari_ootle_walletd-0.50.0-<suffix> --help)'
```

New options are fine; every one `run-walletd.sh` passes (`--network`, `--base-path`, `--config`, `--log-config`,
`--listen-on`, `--authentication`, the `run` subcommand) must still be there. Then upgrade-drill.md §3 on a copy of the
wallet with `NEW=/opt/tari/bin/tari_ootle_walletd-0.50.0-<suffix>`: one migration
(`2026-11-03-120000_locks_many_per_transaction`: an index, not data), the same accounts and balances as `rpc balances`
on the live wallet, nothing refused by the sandbox.

## 4. Before walletd stops: let the sends settle (2 to 10 minutes)

Only sends (jobs) and SealLog checkpoints go through walletd; payments and claims are found by the mirror and
proven by the sidecar, so they keep working while walletd is down. Pause the Tari sends and the log
(reset-playbook.md §1), then wait until nothing is in flight:

```sh
for f in relay_send direct_send drops demo_pay sponsor decoys seallog; do admin feature $f off; done
u "cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'" <<'EOF'
import sqlite3
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
for what, sql in (("jobs sending (must be 0)", "SELECT count(*) FROM jobs WHERE state = 'sending'"),
                  ("checkpoints pending (must be 0)", "SELECT count(*) FROM seal_checkpoints WHERE state = 'pending'"),
                  ("jobs queued (wait for the resume)", "SELECT count(*) FROM jobs WHERE state = 'queued'"),
                  ("invoices open", "SELECT count(*) FROM invoices WHERE status IN ('pending','seen','proven') AND expires_at > unixepoch()"),
                  ("pack payments pending_check", "SELECT count(*) FROM payments WHERE status = 'pending_check'"),
                  ("claims open", "SELECT count(*) FROM claims WHERE status IN ('pending','seen') AND expires_at > unixepoch()"),
                  ("sale payments pending_check", "SELECT count(*) FROM sale_payments WHERE status = 'pending_check'")):
    print(f"{c.execute(sql).fetchone()[0]:6d}  {what}")
EOF
rpc call transactions.list "'{\"status\":\"Pending\",\"account\":null}'"       # walletd's own: must be empty
```

Run it until the first two lines and walletd's list are empty (a send settles within `SEND_TIMEOUT_S`, 15
minutes). Open invoices and claims are fine; note them, and look again after §7 that each one moved on. Keep clear
of 12:00 UTC, when the daily evidence payment is queued.

## 5. Back up, install, restart (walletd is down for seconds)

One script as root, as `docs/evidence/2026-10-20/upgrade-0.47.0/scripts/swap.sh`, with an exit trap that starts
walletd again whatever fails:

```sh
u 'sudo bash -s' <<'EOF'
set -euo pipefail
NEW=/opt/tari/bin/tari_ootle_walletd-0.50.0-<suffix>                 # §3a or §3b
TS=$(date -u +%Y%m%dT%H%M%SZ); B=/var/backups/mutis; LIVE=/opt/tari/bin/tari_ootle_walletd
RPC="sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py"
umask 077; cd /tmp
trap 'systemctl is-active --quiet walletd || { systemctl start walletd || true; echo "trap: walletd $(systemctl is-active walletd || true)"; }' EXIT
$RPC balances > "$B/balances-$TS-before-0.50.0.json"
systemctl stop walletd
tar -C /home/drive -cf "$B/wallet-$TS-pre-0.50.0.tar" wallet .local/share/tari
sha256sum "$B/wallet-$TS-pre-0.50.0.tar"; tar -tf "$B/wallet-$TS-pre-0.50.0.tar" | grep -c wallet.sqlite
cp -a "$LIVE" "$B/tari_ootle_walletd.$TS"                  # = tari_ootle_walletd-0.49.2-aa7b0c8, for a rollback
install -m 0755 -o root -g root "$NEW" "$LIVE"
sha256sum "$LIVE" "$NEW"; "$LIVE" --version
systemctl start walletd
for i in $(seq 60); do $RPC call wallet.get_info '{}' >/dev/null 2>&1 && break; sleep 2; done   # the migration runs at start
$RPC balances > "$B/balances-$TS-after-0.50.0.json"
diff <(grep -v '"version"' "$B/balances-$TS-before-0.50.0.json") <(grep -v '"version"' "$B/balances-$TS-after-0.50.0.json") \
  && echo "balances unchanged" || echo "BALANCES DIFFER: compare the two files before going on"
echo "TS=$TS"
EOF
```

Restart order: walletd only. mutis-api and Caddy don't talk to walletd; mutis-chain needs no restart (its
cached token is refused after walletd restarts, error 401, and it asks for a new one once). Nothing deploys with
this step: the code on `ootle/0.50` reads 0.49.2 and 0.50.0 alike, and ootle-wasm moves later (§2).

```sh
u 'sudo journalctl -u walletd --since "-5 min" --no-pager | grep -iE "migrat|deserialize|error" | tail -20'
rpc call validator_set.get_status "'{}'"                              # indexer_trust, anchored, walk not failing
for f in relay_send direct_send drops demo_pay sponsor decoys seallog; do admin feature $f clear; done
```

## 6. Rollback (before epoch 12951 only)

Stop walletd; move the migrated `/home/drive/wallet` and `/home/drive/.local/share/tari` aside (to
`…-0.50.0-<TS>`, so no `-wal` or `-shm` file of the 0.50 run is left beside the restored store);
`tar -C /home/drive -xpf $B/wallet-<TS>-pre-0.50.0.tar`; install `$B/tari_ootle_walletd.<TS>` at
`/opt/tari/bin/tari_ootle_walletd`; start; `rpc balances` against the before file. 0.50.0 migrated the store, so the
tar, not the binary alone, is the way back. After epoch 12951 there is no going back to 0.49.

## 7. Checks afterwards

Right after §5, and once more after epoch 12951 (the first V1 epoch):

```sh
admin canary-now                       # within 15 min: /status.json canary green (delivered, in the mirror, opened)
admin seal-now                         # a checkpoint (10 min after the last at the earliest): seal_checkpoints state committed
admin notarize "$(curl -fsS https://hidebox.app/.well-known/mutis-manifest.json | sha256sum | cut -d' ' -f1)"   # {"committed": true}
python3 -I tests/e2e/run.py --host hidebox --chain --only E-09,E-10,E-13,E-25,E-29,E-30,E-J
```

The notarize names the live release's manifest again (the same hash `notarize-release.py` notarized at its deploy),
so it says nothing new about it. E-10 and E-13 send transactions the browser builds with ootle-wasm; E-25 is the
canary; E-29 and E-30 pay to open; E-J is the judge script.

Then the first receipts' fees against their caps (metering is the one thing 0.50 changes without an epoch), from
the repository's root:

```sh
python3 -I - <tx id> <<'EOF'
import importlib.util, json, sys, urllib.request
s = importlib.util.spec_from_file_location("cbor", "server/mutis/cbor.py"); cbor = importlib.util.module_from_spec(s); s.loader.exec_module(cbor)
req = urllib.request.Request(f"https://ootle-indexer-b.tari.com/transaction-receipts/{sys.argv[1]}", headers={"User-Agent": "mutis"})
fee = cbor.b64(json.load(urllib.request.urlopen(req, timeout=20))["receipt"])[4]   # FeeReceipt
print({"payment": fee[0], "paid": fee[1], "overcharge": fee[2], "cost": sum(fee[3][0].values())})
EOF
```

For a checkpoint (from `/evidence.json`, `seallog.latest_checkpoint.tx_id`) `cost` stays near 6,000 µT of the
1,000,000 it pays; for a delivery (`deliveries[0].tx_id`) near 16,000 of 30,000. A cost above 25,000 for a
delivery means `max_fee_transfer_ut` and wallet.js `FEE_UT` must rise together (every send pays the same fee).

## 8. If walletd is still 0.49.2 at epoch 12951

What doesn't depend on walletd keeps working whatever its version: links and files, the mirror, payments and
claims (found by the mirror, proven by the sidecar), the canary's opening, and every transaction the browser builds
with ootle-wasm 0.49.2 (same transaction and value layouts). Before the epoch, walletd 0.49.2 reads 0.50 indexers
as it reads 0.49 ones (same paths and shapes). After it, walletd 0.49.2 verifies no proof and recomputes no hash
(`IndexerTrust::Trust`), so it may well keep working, but nobody upstream says so: a 0.49 node forks off, and any
answer it parses that carries something only V1 writes (for instance a protocol version of 1: 0.49 knows only 0)
would stop it reading. Watch from the
epoch on:

```sh
u 'sudo journalctl -u walletd --since "-10 min" --no-pager | grep -iE "deserialize|error" | tail'
u 'sudo journalctl -u mutis-chain --since "-10 min" --no-pager | grep -E "walletd_down|seal_failed|job_failed" | tail'
```

At the first "Failed to deserialize response", pause the Tari features (reset-playbook.md §1) before anything else:
a send submitted then stays `Pending` with its inputs and change locked until a walletd that can read its result
sees it, and results age out after one or two epochs (upgrade-drill.md §4). Then §3 to §7.

## Rehearsal log

| Date | What | Result |
|---|---|---|
| 2026-11-05 | §1 read in v0.49.2..a5ea91cc. §2: `check` on the 0.49.2 downloads gives back both vendored folders byte for byte, with the run and Rekor entries their PROVENANCE files list; a `repin` of a copy of the tree passes deploy/tests. §3b: built on the server as `build`, 23:07 to 23:45 UTC (38 min, 32 min of CPU, 1.8 GB peak, with two other lanes building), the API answering in under 10 ms throughout; §3c: `--help` and `run --help` equal to 0.49.2's but for the name. A throwaway wallet (its own data dir, port 5219, as `build`): made by the 0.49.2 release binary, opened by the build, which ran the one migration at start (`20261103120000`, index `locks_transaction_id`) and kept both accounts' keys and addresses; mutis's client (`info`, `account`, `stealth_balance_ut`, `stealth_utxos`) and `walletd-rpc.py` work against it. Not run: a send, a checkpoint or a dry run (walletd 0.50 dry-runs only from an account on chain, and the faucet was empty) | pass, so far as run |
