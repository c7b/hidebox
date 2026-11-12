<!-- SPDX-License-Identifier: MIT -->
# Paying for space in more than one currency

The owner's ask (2026-11-09): pay for storage in different currencies. The rule for every one of them is that hidebox
never holds a buyer's money in between, that it uses no paid payment processor, and that it can tell a payment arrived
without anyone's spend key. Packs are hidebox's own revenue, so the question for packs is only whose key receives it
and what our server must hold to see it. A seller's sales are the seller's money; paying sellers in other currencies
is a later and larger step (the last section).

What runs today: **TARI on the Ootle**. The rest is a design with what each one needs, for later.

## 1. TARI on the Ootle (built)

A pack is an invoice: an address that carries the invoice's reference (`ootle_addr.with_pay_ref`), the price in TARI,
an hour to pay. The chain worker credits the pack only after its own checks, never a wallet's word:

| Check | How |
|---|---|
| The amount | the official library (`ootle-wasm`, in the sidecar) opens the output's commitment to the exact value (`unblindOutput`) |
| On the chain | a Tari-run indexer shows the output committed |
| Ours to spend | the one-time key the indexer shows equals the one our receiving key derives from the output's nonce (R1, [threat-model.md](threat-model.md) "Ownership"); a payer who kept the spend key gets nothing |
| Once | each output credits once, ever |
| The terms | the invoice keeps the pack's size, days and price from when it was made (migration 012); paying late within the grace still credits, paying short leaves it `underpaid` |
| Brakes | one pack per drive, daily sales per network and per deployment, the paid cap, a kill switch (`mutis-admin feature packs off`) |

On the mainnet there is no test money: no demo payment, no sponsor grant. A buyer pays from any Ootle wallet. Prices
are in [pricing.md](pricing.md).

**Where the revenue sits.** By default pack payments go to our receiving address, whose keys the server holds
(`receiver_keys`, made on the server, backed up with the wallet): our money on a hot key. **Built, and off for the beta: a
watch-only revenue address** (`ootle.revenue_address` and `ootle.revenue_view_key`, empty). With one set, the server
gets only an address of ours made elsewhere and its view secret (a file of 64 hex characters, `root:drive 0640`). Invoices then pay that address; the chain worker scans for its payments
with the view secret, from their own place in the mirror, and credits one only when the watch-only check says the
owner can spend it (`watchOneTimeKey`, gated by the sidecar's selftest, as the release without the seller is;
[threat-model.md](threat-model.md) "Release without the seller's drive"). A payment that opens with the view key but
keeps its own spend key is rejected, as on our receiving address; the hourly reconcile re-opens credited payments with
both view keys; a view key that isn't the address's own opens nothing and credits nothing. A compromised server could
see our revenue, never spend it. The receiving keys stay for what needs them: opening the view keys of sales addresses
that sellers seal to our checker, and the payments made before the switch. Once revenue has been credited, keep its
keys in the config: the hourly reconcile re-opens credited payments with every view key it has, and one it can no
longer open reads as gone, which freezes pack credits until an operator looks. A view key file that is missing, or
that isn't the address's own, stops invoices (503) until it is right, so nobody pays an address nothing watches.
Tests: `server/tests/test_revenue.py`.

For the mainnet beta it stays empty (decided 2026-11-10): pack revenue stays on our receiving key, the default, and
nothing waits on anyone to make an address. Setting one later takes a wallet that shows an account's view secret
(watch-only accounts, Ootle 0.48+, take one); a hidebox drive doesn't show its keys yet.

## 2. XTM on Tari's base layer

TARI is made only by burning XTM 1:1, so a pack's price in XTM is the same number: no exchange rate, no oracle.

| | (a) A one-sided payment to the owner's L1 address (recommended) | (b) A burn to our Ootle account |
|---|---|---|
| The buyer | sends XTM from any Tari wallet to the invoice's address, with the invoice's reference in the memo (the base layer's payment id) | burns XTM on the base layer with our claim key; our walletd claims it as TARI on the Ootle |
| Custody | none: the money lands in the owner's own wallet | none: it becomes our TARI |
| On our server | a view-only base-layer wallet (`minotari-cli` takes a view private key and a spend public key, and can't spend) that watches that address and reads each payment's amount and memo | the claim, through the walletd we already run |
| What it costs | no money; a new pinned binary built from Tari's source, like walletd; a wallet database of some GB; a connection to Tari's base nodes | no money; nothing new to install |
| Privacy | base-layer amounts are confidential and one-sided payments go to a fresh output; whoever holds the view key (our server) sees each payment's amount and memo | a burn is public on the base layer; the claim links it to our account on the Ootle |
| Against it | a new dependency to vet; base-layer confirmations take minutes | a burn can't be undone, needs a wallet that burns with a given claim key, and a claim takes up to a day |

**Vetted on 2026-11-09, and not built for this MVP.** The conditions were an official release pinned by version,
checksum and signature, an unprivileged user with no spend key, and no inbound network. `minotari-cli` v0.5.2
(2026-10-29, the only release) didn't meet them in time:

| | What we found (github.com/tari-project/minotari-cli, tari.com/lessons/09_adding_tari_to_your_exchange) |
|---|---|
| Signatures | a checksum per binary, no signature on any binary; only the git tag is signed, by a maintainer key that isn't in Tari's published keys |
| View-only | `import-view-key --view-private-key … --spend-public-key …`; it can't sign, but the password is a command-line argument other local users can read |
| Network | a one-shot `scan` opens no port; it asks a base node's HTTP API (`rpc.tari.com` by default), which then sees our server's address and which blocks pay us; a node of our own adds a P2P listener |
| Scanning | two open fixes to the scanner (#173, #174) not in any release; `main` is 59 commits and six breaking changes ahead |
| Deposits that aren't | Tari's own exchange guide (2026-10-22) warns that a wallet shows outputs it can't spend (burns, multisig, scripts the sender can take back) as confirmed deposits, and that the cure is to sweep each deposit to a hot wallet; a view-only server can't sweep, so a payer could take a pack's payment back |

What would make it viable: a release with those fixes and signed binaries; credit only after 10 confirmations, as the
guide recommends; and the owner sweeping revenue from his own device before a pack counts as paid, or a check that
proves an output spendable by the owner's key alone (the Ootle's watch-only check has no base-layer equivalent in the
library yet). Until then, **TARI on the Ootle is the one currency**, and anyone holding XTM can burn it 1:1 for TARI.

## 3. Monero (XMR)

| | |
|---|---|
| How | a view-only `monero-wallet-rpc` wallet made from the owner's address and view key (the spend key left out); one subaddress per invoice, so payments don't link to each other on the chain; credited after 10 confirmations (about 20 minutes) |
| Custody | none: the money lands in the owner's own Monero wallet |
| On our server | `monerod` (a pruned node takes about 70 to 200 GB of disk) and `monero-wallet-rpc`, both pinned and checked like walletd |
| The price | XMR has no fixed rate to TARI. Either the owner sets each pack's XMR price in the config and updates it now and then, or the server reads a public price feed (a free third party: it learns nothing about buyers, but a wrong rate under- or over-charges) |
| What it costs | **money**: a disk upgrade for the node, or a remote node instead (free, but its operator sees our server's address and what it asks, and can hide payments by not answering) |
| Privacy | the strongest of the lot: amounts, sender and receiver are hidden on the chain; the view key on our server sees what arrived at our subaddresses, never what the owner spends |

**Not built:** it needs a pruned node, a disk upgrade on the server, and the beta pays for no service (decided
2026-11-10). The design stays here for when that changes.

## 4. Zcash (ZEC)

Shielded payments (Orchard) to a unified address, watched with an incoming viewing key from a light client
(`zcash-devtool` or `zingo-cli`) against a `lightwalletd` server. A public `lightwalletd` costs nothing but sees our
server's address and could withhold transactions; our own (`zebrad` plus `lightwalletd`, about 300 GB) costs a bigger
disk. Same custody (none) and price question as Monero. **Later**, after Monero.

## 5. What every currency shares

- **One invoice, one currency.** An invoice names its currency and an amount in that currency's smallest unit; the
  pack's size and days don't depend on it.
- **No refunds**, as now. An overpayment credits the pack and the rest is ours; an underpayment waits for the rest
  until the grace ends, then stays `underpaid` (the owner can credit it by hand).
- **Finality.** Each chain gets its own confirmation count before a credit (the Ootle's commit, Monero's 10, the base
  layer's per Tari's guidance), and a reconcile that re-checks credited payments, as the Ootle's hourly reconcile does.
- **What our server learns** from a pack payment in any currency: that the invoice was paid, how much and when. Never
  the payer's wallet, and never anything that can spend.

## Paying sellers in other currencies (later)

A shop's sales are the seller's money, paid straight to the seller's own address. In TARI our checker holds each
seller's sales address's view key, sealed, to release a sale without them. Another currency would need a view key per seller in
that currency, a per-claim address on that chain, and a release check per chain. That is a design of its own, after
packs.
