<!-- SPDX-License-Identifier: MIT -->
# walletd accounts, keys and the SealLog log

Spec §10.2. What exists on Esmeralda for mutis, how it was made, and how to make it again after a
reset. Every call runs as `drive` through `walletd-rpc.py` (stdlib JSON-RPC; the port guard lets only
root, operator and drive reach walletd):

```sh
alias u='ssh -o ControlMaster=auto -o ControlPath=/tmp/cm-hidebox -o ControlPersist=30m -o ClearAllForwardings=yes hidebox'
rpc() { u "cd /tmp && sudo -u drive python3 -I /srv/mutis/app/current/deploy/ootle/walletd-rpc.py $*"; }
rpc balances --refresh
```

Dry run first, always: every transfer below was sent with `"dry_run": true`, its fee read with
`transactions.get`, and only then repeated for real and followed with `transactions.wait_result`.
The parameters name only our own accounts and addresses, never a user's, so they may sit on a
command line (sudo logs it).

## 1. What exists (2026-10-11)

| Holder | Kind | Holds | Used for |
|---|---|---|---|
| `service` (`component_ae57…ca71`, key 0, walletd's default) | walletd account | 16.29 tTARI public, 72.27 tTARI stealth | owns and pays for SealLog (G5 fallback); the G4-fallback invoice receiver |
| `buyer-demo` (`component_d870…55bb`, key 1) | walletd account | 3.5 tTARI stealth | E-11 (kind 4 to another wallet) |
| `sponsor` (`component_d561…ddaf`, key 2) | walletd account | 8,900 tTARI stealth | relay sends, decoys, demo payments, sponsor grants |
| `operator` (`component_9cc2…47ff`, key 3) | walletd account | 2.30 tTARI public | paid the template publish; not used for checkpoints (G5, §4) |
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

## 4. SealLog (done 2026-10-11; D-12, gate G5)

`deploy/ootle/publish-template.sh check | publish | instantiate <template>` checks
`template/dist/seal_log.wasm` against `template/dist/SHA256SUMS`, dry-runs, then publishes and
creates the log.

| What | Value |
|---|---|
| Template | `template_b571909e116776fa8cd8b22ddf9890554323a848a36ca9d35efb1a6a859a15bb` (publish tx `de5525dca8e986ca0f8e22382133c884bde1d85bd334f4a0fdaf83633823aa28`, 0.70 tTARI, paid by operator) |
| Log component | `component_0ff7e892de37ee65d60e37a5e55cdfe24b11bd9e84cb5af49831e309f6bd22aa` (tx `b8443adf2a2f4d5d26b85f4687aa0e07ccfe0edea83a7382512a069a6b3c1314`), `verified: true` on indexer-b |
| Owner (may append) | the `service` key |
| In `/etc/mutis/mutis.toml` | `ootle.seallog_component` = the log; `ootle.operator_account = "service"`; `features.seallog` stays `false` until the integrator turns checkpoints on |

**G5 answer: fail.** `transactions.submit_manifest` signs with walletd's default key whatever
account the manifest pays from. Creating the log with `operator` paying was refused in the dry run
(`AccessDenied: call component method 'pay_fee' on component_9cc2…47ff`); extra request fields
(`signing_key_index`, `key_index`, `account`, `fee_account`, `signing_account`) changed nothing. So
the spec's fallback applies: `service` owns the log and pays for checkpoints, and the privacy ledger
says the SealLog owner is the same account that holds our public tTARI. The research log
`component_32dae273…7e36e` is not used (the template builder's NOTES §1).

Budget: about 47 tTARI a year of checkpoints at a 6-hour cadence (template builder's estimate);
`service` holds 16.29 public, enough past Nov 30. Top up with another public transfer into
`service` if the healthcheck's balance numbers say so.

## 5. Keys (done by provision and deploy)

`deploy/scripts/init-keys.sh` (as drive) asks the verifier sidecar for `newKeys` twice and writes
`receiver.json` and `robot.json` (0600) if they don't exist; it never overwrites them, because
invoice addresses and canary deliveries derive from them. Their public addresses appear in
`/evidence.json`.

## 6. After a testnet reset

Accounts and keys are local; only their on-chain state disappears. Re-fund `service` from the burn
(reset playbook §3), re-create the sponsor's funding (§2, a new transfer), publish the template and
create a new log (§4) and update `seallog_component`. The receiver and robot keys stay.
