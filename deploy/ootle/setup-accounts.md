<!-- SPDX-License-Identifier: MIT -->
# walletd accounts, keys and the SealLog log

Spec §10.2. What exists on Esmeralda for mutis, how it was made, and how to make it again after a
reset. Every call runs as `drive` through `walletd-rpc.py` (stdlib JSON-RPC; the port guard lets only
root, the operator and drive reach walletd):

```sh
alias u='ssh -o ControlMaster=auto -o ControlPath=/tmp/cm-hidebox -o ControlPersist=30m -o ClearAllForwardings=yes hidebox'
rpc() { u "cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py $*"; }
rpc balances --refresh
```

Dry run first, always: every transfer below was sent with `"dry_run": true`, its fee read with
`transactions.get`, and only then repeated for real and followed with `transactions.wait_result`.
The parameters name only our own accounts and addresses, never a user's, so they may sit on a
command line (sudo logs it).

## 0. After the Esmeralda reset (2026-11-02, Ootle 0.49.2)

walletd 0.49.2, reset; it came back with a new seed (reset-playbook §2b), so every key below is new. The
tables in §1–§4 are the chain before the reset, kept as the record of how it was done.

| Holder | Key index, owner public key | Component | Funded with |
|---|---|---|---|
| `service` (default) | 0, `78c215f87db6afcc916cb20cb032f9989ccf7f54905bdf5e9e64cca69260ac06` | `component_453538fd…d6e8` | an L1 burn of 150 tXTM (claim landed as a stealth output); 100 tTARI then revealed into its public vault with a stealth transfer to itself (tx `72b45851…4f81`), for `pay_fee` |
| `buyer-demo` | 1, `bc5b3dae…8974` | `component_bb1017a0…7b2b` | — |
| `sponsor` | 2, `50f56f64eabc3e84ef3e50a766f3b1ac45748358384e9076bb56bb6fbdb10b3d` | `component_e9489a5f…98f4` | an L1 burn of 4,000 tXTM |
| `operator` | 3, `3e1a4eaa…0519` | `component_fadaea01…07b3` | — |

| SealLog 2.0.0 (tari_template_lib 0.37) | Address | Transaction |
|---|---|---|
| template, author `service`, exactly `dist/seal_log.wasm` (sha256 `9a276b30…4c84`, 107,162 bytes) | `template_5932ee9ba5a969f59eac0cddc8fae7112b22dfc85abdaa751911d11ce533145c` | `44637f53…6924`, 842,994 µT |
| the log until 2026-11-07 (retired: Ootle 0.50 loads no V1 definition; 406 checkpoints, chain index 0 to 405, the last #2552, tx `dbdcf775…`): owner_rule `None`, upgrade_rule `Locked`, `append_root` only for the `service` key's badge | `component_6a3eae198ed483565abf978f7c5289263f13b2edf3ef3900a9924dd41141bd65` | `5aeec60b…63e6`, 2,403 µT |

A checkpoint (the worker's manifest) dry-runs at 2,428 µT. The receiver and robot keys didn't change.

**2026-11-07: walletd 0.50.0 and SealLog 2.1.0** (upgrade-0.50.md §5 and §9, seallog-v2-cutover.md;
`docs/evidence/2026-11-07/upgrade-0.50.0/`). The same accounts and keys; walletd 0.50.0 since 03:34:11 UTC. The
Esmeralda fleet moved to 0.50.0 between 03:28 and 03:43, after which the V1 log's checkpoints fail (#2553, 03:49:50,
`AcceptFeeRejectRest`, 1,208 µT).

| SealLog 2.1.0 (tari_template_lib 0.38, V2 definitions) | Address | Transaction |
|---|---|---|
| template, author `service`, exactly `dist-v2/seal_log.wasm` (sha256 `00ca5f34…878f`, 107,038 bytes), published 03:50:10 | `template_7441d16299220d821b3b0d091f59d82d4898bac2a21a1df7db606d4c8e5c869f` | `f8d84734d43fc12f…`, 842,962 µT (dry run the same) |
| the live log since 03:51:38: owner_rule `None`, upgrade_rule `Locked`, `append_root` only for the `service` key's badge, default `DenyAll` | `component_f8820af05feaf4e327e59b3210fe2566e864f5b6631f5e41d6e63d28dd384fbe` | `5c0ef36891cebf52…`, 2,412 µT |
| its checkpoint 0 (#2554, the whole tree: 163,648 leaves), 03:55:04 | | `4e43ad1461e9bb98…`, 2,432 µT |
| the live release's manifest (`95ec8bc6…`) notarized in it, 03:55:22 | | `9ffb488e873558e9…`, 2,036 µT |

`sponsor` refilled with 15 tTARI from `service` at 03:54:02 (tx `ff236c60…ea92`, 30,000 µT, cost 15,933): the
demo payment walletd submitted at 03:40:43, while the fleet restarted, never reached the network (`657d758a…`, on
no indexer) and holds the sponsor's one output (3,958 tTARI) and its change. walletd 0.50.0 releases them by itself
once the epoch passes the transaction's `max_epoch` 12925 by more than 3 (`TRANSACTION_EXPIRY_GRACE_EPOCHS`), so
from epoch 12929.

## 1. What exists (2026-10-11)

| Holder | Kind | Holds | Used for |
|---|---|---|---|
| `service` (`component_ae57…ca71`, key 0, walletd's default) | walletd account | 16.29 tTARI public, 72.27 tTARI stealth | owns and pays for SealLog (G5 fallback); the G4-fallback invoice receiver |
| `buyer-demo` (`component_d870…55bb`, key 1) | walletd account | 3.5 tTARI stealth | E-11 (kind 4 to another wallet) |
| `sponsor` (`component_d561…ddaf`, key 2) | walletd account | 8,900 tTARI stealth | relay sends, decoys, demo payments, sponsor grants |
| `operator` (`component_9cc2…47ff`, key 3) | walletd account | 2.30 tTARI public | paid the 1.0.0 template publish; idle since G5 failed (§4) |
| receiver | sidecar-made keys, `/home/drive/mutis/receiver.json` (0600) | — | invoice addresses (pack payments, proven by the sidecar) |
| robot locker | sidecar-made keys, `/home/drive/mutis/robot.json` (0600) | — | canary deliveries, health and evidence |

The keyring password that decrypts walletd's database is in `/etc/mutis/credentials/walletd-keyring-pass`
(root, 0600); `walletd.service` hands it over as a systemd credential (see `run-walletd.sh`). The
original `/home/drive/wallet/.keyring-pass` is still there and is part of every wallet backup.

## 2. The sponsor (done 2026-10-11)

```sh
rpc call accounts.create '{"account_name":"sponsor","is_default":false,"key_index":null}'
# → component_d5614f51…ddaf and its otl_esm_1… address
rpc call accounts.stealth_transfer '{"owner_account":{"Name":"service"},
  "fee_params":{"input_selection":"PreferConfidential","pay_fee_with_swap":null},
  "input_selection":"PreferConfidential","resource_address":"resource_0101…01",
  "transfers":[{"destination_address":"<sponsor address>","blinded_output_amount":"8900000000",
    "revealed_output_amount":"0","output_memo":{"Message":"mutis sponsor funding"},
    "pay_to":"StealthPublicKey","attach_sender_address":false}],
  "max_fee":"30000","dry_run":false}'
```

Dry run: fee 15,249 µT. Real: tx `1847d302c96fe7a577ea0cab5b301f595fdb77b44f141425846b3666212f46ec`,
`Commit` on indexer-b; a stealth-funded fee is not refunded, so it cost the full 30,000 µT. Funding
math (spec §9.5): every slice maxed every day costs about 230 tTARI, so 8,900 lasts about 38 days of
worst case and far longer in practice; the healthcheck turns amber below 200 tTARI.

**Refilled 2026-10-13** (the 10:39 send's change stays locked in walletd;
the 0.46.0 upgrade's evidence, pruned on 2026-10-20): 61.5 tTARI from `service` as above
(tx `a70eb538…7403`), then 400 tXTM burned on the L1 straight to the sponsor. In the TUI's Burn tab
the Claim Public Key is the sponsor's own `owner_public_key` (`rpc call accounts.get
'{"name_or_address":"sponsor"}'`), not `service`'s: walletd 0.46.0's auto-claimer finds the account by
that key and claims into it, so the tTARI arrive as a sponsor stealth output with no second transfer
(claim `a33d64e4…74d0`, 399.987 tTARI, fee 13,238 µT, 109 minutes after the burn). The L1 keeps about
600 tXTM in reserve.

## 3. The operator (done 2026-10-11)

A public vault pays transaction fees, so the account was funded with a public transfer
(`accounts.transfer` signs with the paying account's own key):

```sh
rpc call accounts.transfer '{"account":{"Name":"service"},"amount":"15000000",
  "resource_address":"resource_0101…01","destination_public_key":"<operator owner_public_key>",
  "max_fee":"2000000","dry_run":false}'
```

Tx `5b58aeb691669789801d9d2c96369bba20ce17ab6d906543acfd6f1c73715d0f` (fee 2,441 µT). After G5 failed
(§4), 12 tTARI went back to `service` the same way, signed by `operator`: tx
`13db3d8d27fcb1f5511c1d6552528a1f8d92a1200936b8a42cf9337b04071c55`.

## 4. SealLog (D-12, gate G5)

`deploy/ootle/publish-template.sh check | publish | instantiate <template>` checks
`template/dist/seal_log.wasm` against `template/dist/SHA256SUMS`, predicts the template address,
dry-runs, then publishes and creates the log. The publish is a transaction the script builds itself
(one `PublishTemplate` instruction, the binary as its blob, the fee from `service`), sealed by walletd
with the `service` key through `transactions.submit`: `transactions.publish_template` would run
wasm-opt first and put bytes on chain that no source can be tied to (template NOTES §1).

| Log | Template | Component | State |
|---|---|---|---|
| 1.0.0 | `template_b571909e…15bb` (tx `de5525dc…aa28`, 0.70 tTARI, paid by operator; wasm-opt'd bytes) | `component_0ff7e892…22aa` (tx `b8443adf…1314`), owned by the `service` key | retired, never appended to |
| research | `template_e064f38d…4441` | `component_32dae273…e36e` | retired, one test checkpoint |
| **2.0.0** | `template_40c5f1cf…0a47` once published: author the `service` key `9c686313…5420`, exactly `dist/seal_log.wasm` (sha256 `9af71aa2…d6f2`) | made at go-live by `instantiate` | the live log |

Both retired logs are listed in `/evidence.json` (`seallog.retired`), next to the live one, once
`features.seallog` is on.

**Dry run of the 2.0.0 publish (2026-10-11):** `Accept`, fee 755,531 µT, `template_40c5f1cf…0a47`,
holding `seal_log.wasm` byte for byte (`../evidence/2026-10-11-integration/publish-dry-run.txt`).
Nothing was submitted.

**Go-live, in this order** (from a committed tree, so the published bytes are the tag's):

```sh
deploy/ootle/publish-template.sh check                     # dry run: Accept, the predicted address, our bytes
deploy/ootle/publish-template.sh publish                   # ends with "the chain runs seal_log.wasm byte for byte"
deploy/ootle/publish-template.sh instantiate template_<hex>   # dry run, then the log: component_<hex>
curl -s -H 'User-Agent: mutis' https://ootle-indexer-b.tari.com/substates/component_<hex> |
  python3 -I -c 'import json, sys; b = json.load(sys.stdin); h = b["state"]["up"]["substate"]["Component"]["header"]; print(h["owner_rule"], h["template_address"], json.dumps(h["access_rules"]["method_access"]["append_root"]))'
```

(tari_indexer 0.47.0 answers the live value at `state.up.substate`; earlier indexers put it at `substate`.)

The header must show `owner_rule` `"None"`, the 2.0.0 template, and `append_root` restricted to a
badge whose id is the `service` public key (template ACCEPTANCE E-2 shows the shape). Then in
`/etc/mutis/mutis.toml`: `ootle.seallog_component` = the new component and `features.seallog = true`
(`sudo mutis-admin check-config`, restart mutis-chain and mutis-api). From then on
`tools/verify-deploy.py` also checks that the live log's template is the tag's `seal_log.wasm`.

**G5 answer: fail.** `transactions.submit_manifest` signs with walletd's default key whatever
account the manifest pays from. Creating the log with `operator` paying was refused in the dry run
(`AccessDenied: call component method 'pay_fee' on component_9cc2…47ff`); extra request fields
(`signing_key_index`, `key_index`, `account`, `fee_account`, `signing_account`) changed nothing. So
the spec's fallback applies: `service` owns the log and pays for checkpoints, and the privacy ledger
says the SealLog writer is the same account that holds our public tTARI.

**Budget.** One checkpoint every 15 minutes (`seal_log.checkpoint_interval_s = 900`, 12-integration
§7.2) costs about 5,200 µT each at Esmeralda's rate, about 0.50 tTARI a day, plus one notarization per
deploy. `service` holds 16.29 tTARI public; after the publish (0.76) and the log (under 1) that is
about a month of checkpoints, so top it up before November. `sponsor`'s tTARI are stealth outputs and
can't be moved into a public vault with `accounts.transfer` (dry run: "vault not found"); a burn's
claim lands in `service`'s public vault (reset-playbook §3, a human step with ~1,000 tXTM in
reserve), and `accounts.transfer` from `operator` (2.30 public) adds a little. The healthcheck doesn't
watch `service`'s balance yet (NOTES §5, a server request): `rpc balances --refresh` once a week.

## 5. Keys (done by provision and deploy)

`deploy/scripts/init-keys.sh` (as drive) asks the verifier sidecar for `newKeys` twice and writes
`receiver.json` and `robot.json` (0600) if they don't exist; it never overwrites them, because
invoice addresses and canary deliveries derive from them. Their public addresses appear in
`/evidence.json`.

## 6. After a testnet reset

Accounts and keys are local; only their on-chain state disappears. Re-fund `service` from the burn
(reset playbook §3), re-create the sponsor's funding (§2, a new transfer), publish the template and
create a new log (§4) and update `seallog_component`. The template address stays the same (it
depends only on the author key and the bytes). The receiver and robot keys stay.
