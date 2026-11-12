<!-- SPDX-License-Identifier: MIT -->
# Mainnet launch hour

The Ootle mainnet launches on 2026-11-11 (the hour isn't announced; 11:11:11 UTC is a guess). The contest "First to
Launch" ranks entries by the time of their contract's publish transaction, so SealLog goes out first, by itself,
and the site follows. Production (the testnet site) is not part of any of this and never changes.

```sh
alias u='ssh -o ControlMaster=auto -o ControlPath=/tmp/cm-hidebox -o ControlPersist=30m -o ClearAllForwardings=yes hidebox'
I=mainnet                     # the instance (deploy/scripts/instance.py); its site is mainnet.<domain>
```

## What runs

| Piece | Where |
|---|---|
| config | `/etc/mutis-$I/mutis.toml` (staging until §4), `instance.conf`, `credentials/` (root) |
| site and API | `/srv/mutis-$I/{app,data,status}`, `mutis-$I-api` on 127.0.0.1:8788, Caddy site `/etc/caddy/mutis.d/$I.caddy` |
| chain worker | `mutis-$I-chain`, as `drive-$I` |
| walletd, mainnet | `mutis-$I-walletd-mainnet` on 127.0.0.1:5101, `/home/drive-$I/wallet-mainnet`; accounts `service` (key 0, default) and `sponsor` (key 1) |
| walletd, staging | `mutis-$I-walletd-esmeralda` on 127.0.0.1:5102 (until §4) |
| L1 wallet | `mutis-$I-l1wallet-mainnet` (mainnet build 6.2.0, non-interactive, gRPC on guarded 127.0.0.1:18153), data `/home/drive-$I/l1wallet-mainnet`, seed words root-only beside walletd's; `l1-wallet-mainnet.sh address \| tui` |
| launch trigger | `mutis-$I-launch-<label>.timer` → `launch.py`, state in `/home/drive-$I/launch-<label>/` |
| timers | `mutis-$I-{cleanup,health,evidence,backup,backup-wallet}.timer` |
| seed | `/var/backups/mutis-$I/walletd-mainnet-seed-words.txt` and a cold tar with its keyring password (root only) |

Owner-match guards in ufw: 8788 (caddy, drive-$I, root, the operator), 5101 and 5102 (drive-$I, root, the operator).

## 1. Before (days ahead)

1. walletd ≥ 0.50 for the mainnet: `mainnet-walletd.sh install <binary> <sha256>`, `setup`, `backup` (done for
   0.50.0 on 2026-11-05). Then `systemctl enable --now mutis-$I-walletd-mainnet`: it runs before launch and claims
   burns by itself once it can.
2. SealLog for the mainnet: `template/dist-v2/seal_log.wasm` (tari_template_lib 0.38, V2 definitions), built by
   `template/check.sh`. The 0.37 build in `template/dist/` stays the testnet's.
3. The L1 wallet (`l1-wallet-mainnet.sh install | create | start`, done 2026-11-06): the owner sends XTM to the
   address `l1-wallet-mainnet.sh address` prints. Then the final `MAINNET_START_HEIGHT`, then the burn:
   [burn-mainnet.md](burn-mainnet.md). Since 2026-11-10 `l1-burn.py` makes the burns unattended, once per account, as soon as the guard says yes (the owner's call); the TUI is the fallback. At least ~3 XTM to `service` for the publish (under 1 TARI), the log and the reveal; more for a
   month of hourly checkpoints, and for `sponsor` (relay sends, decoys, the canary).
4. Arm the trigger, for real, from a committed tree:

   ```sh
   u "sudo MUTIS_INSTANCE=$I bash <tree>/deploy/ootle/launch-arm.sh --label mainnet --network mainnet \
        --walletd-port 5101 --account service --wasm <tree>/template/dist-v2/seal_log.wasm"
   ```

   Every 30 seconds it checks the mainnet indexer, then the funds; until launch it says "not live yet". A dry
   run first, any time: the same with `--dry-run` and another `--label`.

   Done on 2026-11-08 05:59 UTC, from the tag `mainnet-launch-candidate-2026-11-11`: a dry run first under
   `--label mainnetdry` (waiting at `indexer`: "no indexer answers", the mainnet not live yet), disarmed; then
   `--label mainnet` for real, `dry_run = false`, with `template/dist-v2/seal_log.wasm` (107,038 bytes, sha256
   `00ca5f34…878f`; the dry-run arm of 2026-11-06 held the 2026-11-05 build, `443bbe61…8555`). Its state was empty
   and stays so: it waits at `indexer`, and nothing was sent.
5. Rehearsed on Esmeralda with a scratch account and its own template (`--label rehearsal --network esmeralda
   --walletd-port 5102 --account rehearsal`): the same code, unattended, the same evidence.
6. Esmeralda turns on protocol V1 at epoch 12951 (Ootle 0.50.0's release notes: about 2026-11-06 12:00 UTC).
   From then the staging walletd needs 0.50 too (`provision-instance.sh … --walletd-bin
   esmeralda:<the 0.50 binary>`, then restart `mutis-$I-walletd-esmeralda`; back its directory up first), and
   the site needs the 0.50 `ootle-wasm` of the `ootle/0.50` branch. Rehearse the V2 template there once more
   (`--label rehearsal2 … --wasm template/dist-v2/seal_log.wasm`).

   Done on 2026-11-08: walletd 0.50.1 (the release binary production runs) on `mutis-$I-walletd-esmeralda`;
   ootle-wasm 0.50.0 with the launch candidate; staging's log moved to the V2 template Esmeralda already runs
   (`template_7441d162…869f`): `publish-template.sh instantiate template_7441d162… --instance $I --walletd-port 5102
   --account service --wasm template/dist-v2/seal_log.wasm` made `component_20e613c036a9e4a25329c8aed741a30ed2b6287bc670ac8bb58f3a8001450030`
   (2,412 µT), its checkpoint 0 committed, and verify-deploy holds it to `dist-v2`. A publish of staging's own
   needed more than its `service` held in its public vault (the fee is locked up to 3 TARI).

   `rehearsal2`, 2026-11-08, from the tag `mainnet-launch-candidate-2026-11-11`, with `--account rehearsal` (funded
   with 1,000 tTARI from the Esmeralda faucet, `accounts.create_free_test_coins`): every step in its first pass,
   `template_45a467821933d68b39f807bf8d0b1d9641128bbbd4c43aaf215de012a0b0b82e` (842,962 µT) and log
   `component_e7a58799b7adb1dcb00ae9ab4bb01306703650eb906b3064e815de9ae062b639` (2,412 µT, owner `None`, upgrade
   `Locked`); `wasm_check.py onchain` byte for byte against `dist-v2`; disarmed. Evidence:
   [docs/evidence/2026-11-08/launch-rehearsal2/](../../docs/evidence/2026-11-08/launch-rehearsal2/).
7. Ootle 0.51.0 and 0.52.0 (2026-11-09, no activation epoch; [upgrade-0.52.md](upgrade-0.52.md)): Esmeralda moved
   the same day, and this tree carries ootle-wasm 0.52.0 from main. 0.52 changes how a burn is claimed, and a claim
   built by an older walletd fails on a 0.52 network, so the mainnet walletd must be the release that sets the
   final `MAINNET_START_HEIGHT` (0.52 or later) before any burn: `burn-guard.py` refuses until that version has a
   final entry in `mainnet-start-height.json`. The jump from 0.50.1 needs nothing special: 0.51 and 0.52 keep the
   command line and add no store migration, and 0.52.0 opens a copy of the mainnet wallet with the same accounts
   (rehearsed 2026-11-09, no network, nothing swapped). The key a burn goes to is unchanged. Staging's Esmeralda
   walletd stays 0.50.1 until the flip: it sends and checkpoints on 0.52, but can't claim an Esmeralda burn.
7. After the October judging: production's evidence sponsor budget back from 20 to 10 tTARI
   (`[budgets.evidence] sponsor_ut = 10000000` in `/etc/mutis/mutis.toml`; raised for the Ootle 0.50 runs on 2026-11-07).

## 2. Launch hour: watch

```sh
u "sudo cat /home/drive-$I/launch-mainnet/status.json"        # step, state, message
u "sudo journalctl -fu mutis-$I-launch-mainnet"
```

The steps go `indexer → walletd → funds → publish → log → evidence → done`. "waiting" is normal; "attention" or
"halted" wants a person (§5). Nothing to type while it waits.

## 3. When it says done

`/home/drive-$I/launch-mainnet/evidence.json` holds the template and component addresses, both transaction ids,
their finalized times, the template's epoch and the fees. Check it from outside:

```sh
python3 -I template/wasm_check.py onchain <template_…> --indexer https://indexer-a.ootle.tari.com \
  --wasm template/dist-v2/seal_log.wasm                       # "the chain runs seal_log.wasm byte for byte"
```

Copy evidence.json into `docs/evidence/<date>/` and post the template address and its transaction on the forum.

Done on 2026-11-12: `template_494d34a5f55bcef614655c9f8b7fdcb672f1d086467fc96816c0a93a4a5c8472` at 18:28:36 UTC (epoch 38542), log `component_45efaa40c370fa98b86ad59bd395694a241313d741f81ed30bc772b88ef84690`; the receipt is [docs/evidence/2026-11-12/mainnet-launch/](../../docs/evidence/2026-11-12/mainnet-launch/).

## 4. Flip the site to the mainnet

```sh
u "sudo MUTIS_INSTANCE=$I bash <tree>/deploy/ootle/flip-to-mainnet.sh --component <component_…> --dry-run"
u "sudo MUTIS_INSTANCE=$I bash <tree>/deploy/ootle/flip-to-mainnet.sh --component <component_…>"
deploy/scripts/deploy.sh <ref> --instance $I                    # builds with the mainnet config
u "sudo systemctl start mutis-$I-api mutis-$I-chain"           # if the deploy didn't
```

The flip stops the instance, keeps a root-only copy of the staging database (deleted after 7 days like every
copy), deletes the staging files and keys, and writes the mainnet config: `network = "mainnet"`, `staging = false`,
the mainnet indexers, walletd on 5101, `mirror_start_epoch` = the current epoch, the new log and `features.seallog`.
The deploy makes new receiver and robot keys for the mainnet. Then:

- `curl -s https://mainnet.<domain>/api/v1/config` says `"network": "mainnet"`, `"coin": "TARI"`, `"staging": false`;
- the pages say real TARI, a beta, small amounts; no staging banner; no test money, no judge passes;
- `/status.json` turns green within the hour once the sponsor has TARI (the canary needs one send).

## 4b. The November MVP's switches (docs/mvp-november.md)

An instance provisioned before this release keeps the `mutis.toml` it was written with, and the flip doesn't touch
these lines. After the release is deployed, on the instance (staging or the mainnet):

```sh
u "sudo mutis-admin-$I feature away_release on"   # a sale opens without the seller's drive (our checker's watch-only check)
u "sudo mutis-admin-$I feature packs on"          # space packs, a beta in TARI on the mainnet
u "sudo mutis-admin-$I feature shop on"           # /shop/<username>, private or public (already on in instance.toml.example)
u "sudo mutis-admin-$I feature withdraw on"       # withdrawing earnings (already on in instance.toml.example)
```

or set them under `[features]` in `/etc/mutis-$I/mutis.toml` and restart the API and the chain worker. Each one turns
off the same way, at once. The shop's pages need no setting: the API reads `shop.html` from the release beside its own
code. Check: `curl -s https://mainnet.<domain>/api/v1/config | python3 -m json.tool | grep -E 'away_release|packs|shop|withdraw'`,
`/sitemap-shops.xml` answers XML (empty on staging), and `/shop/no-such-shop` answers the plain page with `noindex`.

## 5. When something goes wrong

| Says | Do |
|---|---|
| indexer: not live yet | wait; nothing is sent |
| funds: not enough TARI yet | the burn isn't claimable yet (780 confirmations, a later epoch). `walletd-rpc.py … call burn_proofs.list '{"filter_by_public_key":null}'`. A claim by hand: setup-accounts.md, `accounts.claim_burn` |
| attention: … dry run says Reject | read the reason in `launch.log`. A fee above `max_fee_publish_ut`: re-arm with `--max-fee-publish-ut`; the state is kept |
| halted | a submitted transaction failed and may have cost its fee; nothing more is sent. Look at it (`transactions.get`), then `sudo -u drive-$I python3 -I /usr/local/lib/mutis-$I/launch/launch.py unhalt --config /etc/mutis-$I/launch-mainnet.toml` |
| walletd runs on … | the trigger points at the wrong walletd: re-arm with the right `--walletd-port` |

Disarm when done (or to stop it): `launch-arm.sh --label mainnet --disarm`. Re-arming keeps the state.
