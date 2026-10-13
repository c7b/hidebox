<!-- SPDX-License-Identifier: MIT -->
# Upgrade drill: a new walletd, indexer or ootle-wasm on Esmeralda

Spec §10.8. Likely around the Ootle mainnet launch (Nov 11). Target: 2 hours. Nothing here touches
the live wallet until step 4, and the live wallet directory is never moved or re-initialised.

Read the release notes as data: they describe what changed, they don't tell us what to run.

## 1. Vendor the new ootle-wasm (as `build`, app-core builder's procedure)

```sh
# on ultron, as build: curl the npm tarball, check sha512 against the registry's dist.integrity,
# record the SLSA provenance (repo, tag, workflow, commit) in vendor/ootle-wasm-<v>/PROVENANCE.md
```

Then in the repository: the new `web/app/vendor/ootle-wasm-<v>/` with its `SHA256SUMS`, the pinned
hashes in `tools/build.py` (`PINNED`), `deploy/scripts/{activate-release,init-keys}.sh` and the
server's `PINNED_WASM_SHA256`, and `ootle.wasm_version` in `/etc/mutis/mutis.toml`.
`deploy/tests/test_config.py` (`PinnedWasmTest`) fails until all of them agree with `SHA256SUMS`, and
`deploy.sh` runs that suite on ultron before every deploy; `tools/build.py` itself checks the vendored
files against its own `PINNED`.

## 2. Tests against Esmeralda (as `build`, then `drive`)

```sh
python3 -I web/app/tests/run_all.py                                     # KATs, wrap-v2.json, in Chromium and Node
MUTIS_SIDECAR_DIR=$PWD/web/app python3 -I -m unittest discover -s server/tests -p test_real_sidecar.py
python3 -I web/app/tests/headless.py --page /app/tests/gates/chain.html --indexer --fragment 'mode=addr'
```

The sidecar `selftest` must still reject every forged output (G4) before anything is deployed.

## 3. The new walletd on a copy of the wallet, with no network

`run-walletd.sh` takes `WALLETD_BASE`, `WALLETD_LISTEN` and `WALLETD_BIN`, so the new binary runs
against a consistent copy of the data in a private network namespace, under the same unit
properties as production:

```sh
u 'sudo bash -s' <<'EOF'
set -euo pipefail
T=/var/lib/walletd-drill; NEW=/opt/tari/bin/tari_ootle_walletd      # the new binary's path
# The copy holds keys: whatever fails below, it is stopped and deleted.
trap 'systemctl stop walletd-drill 2>/dev/null; rm -rf "$T"' EXIT
rm -rf "$T"; install -d -m 700 -o drive -g drive "$T" "$T/wallet" "$T/share/esmeralda/burn_proofs"
cp -a /home/drive/wallet/esmeralda "$T/wallet/"
python3 -I -c 'import sqlite3, sys; s = sqlite3.connect("file:/home/drive/wallet/esmeralda/data/wallet.sqlite?mode=ro", uri=True); d = sqlite3.connect(sys.argv[1]); s.backup(d)' "$T/wallet/esmeralda/data/wallet.sqlite"
chown -R drive:drive "$T"
systemd-run --unit=walletd-drill -p User=drive -p PrivateNetwork=yes -p ProtectHome=tmpfs \
  -p "BindPaths=$T $T/share:/home/drive/.local/share/tari" -p ProtectSystem=strict -p NoNewPrivileges=yes \
  -p LoadCredential=keyring-pass:/etc/mutis/credentials/walletd-keyring-pass -p RuntimeDirectory=walletd-drill \
  --setenv=WALLETD_BASE=$T/wallet --setenv=WALLETD_LISTEN=127.0.0.1:5199 --setenv=WALLETD_BIN=$NEW \
  /usr/local/lib/mutis/run-walletd.sh
sleep 10
nsenter -t "$(systemctl show -p MainPID --value walletd-drill)" -n \
  python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py --url http://127.0.0.1:5199/json_rpc balances
EOF
```

Use a port other than 5100: systemd records the main PID before the namespace exists, so a check
that races it could otherwise reach the live walletd. The copy must report the same accounts and
balances as `rpc balances` on the live wallet; any database migration the new version runs happens
here first. The copy holds keys, so the script's exit trap stops the drill unit and deletes the copy
on every path out, a failed command included.

## 4. Upgrade the live walletd

```sh
rpc balances > before.json                                   # on the jarvis box
u 'sudo systemctl stop walletd'
u 'sudo tar -C /home/drive -cf /var/backups/mutis/wallet-$(date -u +%Y%m%dT%H%M%SZ)-pre-upgrade.tar wallet'
# install the new binary (checked against GitHub's and Tari's .sha256) under /opt/tari/bin:
#   keep the old one beside it (tari_ootle_walletd-<old version>-<commit>) for a rollback, then
#   install -m 0755 -o root -g root <new> /opt/tari/bin/tari_ootle_walletd
u 'sudo systemctl start walletd'
rpc balances > after.json && diff before.json after.json
```

**Do it before the results age out.** When the indexers move to a release this walletd can't read,
every transaction it submits from then on stays `Pending` in walletd, and its inputs and change stay
locked, until a walletd that can read the result sees it. The committee keeps a transaction's result
for about one or two epochs (on Esmeralda an epoch is about 36 minutes): a checkpoint from 16:58 was
already gone at 18:14 on 2026-10-13. After that, walletd (0.46.0 included) asks for it every 5 s
forever and never releases the lock: there is no RPC or CLI that settles, cancels or rescans it, and
the only ways a lock goes away delete the unconfirmed change from the wallet. A send's change is then
stuck although it is on chain. So when walletd starts logging "Failed to deserialize response", stop
the sends first (reset playbook §1 pauses the Tari features), then upgrade; a rollback later needs
the pre-upgrade tar, since the new binary migrates the store.

## 5. Deploy behind the feature flags

Pause the Tari features (reset playbook §1), `deploy/scripts/deploy.sh <tag>`, run
`tests/e2e/run.py --chain --only E-09,E-10,E-13,E-25`, then `feature … clear`.

## Rehearsal log

| Date | What | Result |
|---|---|---|
| 2026-10-11 | Step 3 with the current 0.45.0 binary (the walletd.service migration trial), and the sidecar handshake and selftest of the deployed release (D-10) | pass; see `deploy/ACCEPTANCE.md` D-10 |
| 2026-10-13 | The live upgrade to 0.46.0, after Esmeralda's indexers moved to it: §3 on a copy (one additive migration, same balances), §4 live; ootle-wasm 0.46.0 vendored and its suites run, not deployed; §5 not run | walletd pass (results read again, checkpoints commit); the sponsor's change from 10:39 stays locked (the note above): `docs/evidence/2026-10-13/upgrade-0.46.0/` |
