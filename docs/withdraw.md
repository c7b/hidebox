<!-- SPDX-License-Identifier: MIT -->
# Withdrawing earnings

People who pay to open a drive's files pay the drive's **sales address** directly: their money sits there in stealth
outputs, and only the drive's key can spend them. Until now nothing could: Earnings said "Not yet". With
`features.withdraw` on (off by default; it needs `features.pay_to_open` too), the drive sends its earnings to any Ootle
address the owner types, from Earnings.

Code: `web/app/lib/withdraw.js` (the rules, the transaction, the receipts), `web/app/ui/drive-withdraw.js` (the block in
Earnings and the dialog), `server/mutis/withdraw.py` and `server/mutis/handlers/withdraw.py` (what may be withdrawn, the
relay), migration `009_withdraw.sql`. Routes: [api.md](api.md) ("Withdraw").

## How it works

1. **The keys.** The sales address is `deriveOotleKeys(seed, 'sales')` (lib/pay.js `salesKeys`): an owner key and a
   view key, derived in the browser from the drive's seed. A payment to it is a stealth output whose one-time key is
   the owner key's public key plus `c·G`, with `c = H(network ‖ v·R)` from the view key `v` and the output's nonce `R`
   (Ootle 0.48+). The browser spends an output with the secret `k + c` (`stealthDhSecret`), exactly as wallet.js's
   `send()` spends the drive wallet's outputs for **Pay from my drive**.
2. **The plan.** Earnings lists what is ready (`GET /me/sales/outputs`), what is still being checked and what is on
   its way out. The owner types an address and an amount, or taps All. The browser picks the fewest payments that
   cover it, biggest first.
3. **Confirm.** The confirm step shows what arrives, the network fee, what leaves the earnings, and the address with
   the 6 characters after its network prefix and its last 6 set apart (the parts people compare, as wallets show
   them). Send is pressed once.
4. **Build, sign, send.** The browser reads each input from an indexer (through our read proxy) and opens it with the
   view key of the sales address. It builds one stealth transfer: an output for the amount minus the fee to the address, and the change
   back to the sales address. It balances it with the official library (`buildStealthTransferStatement`,
   `validateStealthTransfer`), signs each input with its one-time key, seals it, and posts it to
   `POST /me/withdrawals`. Our server checks it and relays it to the network. The browser waits for the chain's
   decision and reports it (`POST /me/withdrawals/{tx}`). The receipt links **What the chain sees** (`/verify/tx/…`).

## The rules

The same on both sides: `server/mutis/withdraw.py`, served in `/config` as `withdraw`, and `lib/withdraw.js`.

| Rule | Value | Why |
|---|---|---|
| Network fee | `0.03` (`FEE_UT`, the same flat fee as every send) | It comes **out of the amount withdrawn**: what arrives is the amount minus the fee. Pay from my drive pays its fee from the spender's own outputs too; nothing is sponsored. The confirm step shows the exact fee before Send. |
| Minimum | `0.06` | At least as much as the fee arrives. |
| Dust | change below `0.03` goes along | Change smaller than the fee would cost more to move than it is worth. The confirm step says how much more goes along ("… more goes along"). |
| Inputs | at most 8 payments per withdrawal | Each sale is its own output. All takes the 8 biggest and says so; the rest needs another withdrawal. |
| Settled money only | counted, and paid by test money for a whole price or checked by the owner's drive; or change of an earlier withdrawal | The payment checker can only count an output that is still on the chain. Spending a payment that is still being counted, or that waits for the owner's check, would leave its buyer without the open they paid for. It is the same rule Earnings' totals use. |
| One at a time | the button is off from the press on; the library refuses a second run; our server marks the inputs before it relays and refuses them while a withdrawal of them is on its way | No double submit, and no double spend of the same payment. |
| On its way | marked for 10 minutes (`PENDING_S`), or until the drive reports the outcome | A withdrawal whose tab closed before the chain answered is settled the next time Earnings opens: the drive asks the chain how it ended and tells our server. |
| The address | an Ootle address on this deployment's network, its checksum and keys checked by the official library (`parseAddress`); no payment reference; not the drive's own sales address | Another network's address is refused with the same words as everywhere in the app ("That's not a testnet address…"); the network is a configuration choice, so this follows it. |

## What our server learns, what it never holds

- **Never a spend key.** The sales owner key and every one-time secret stay in the browser that opened the drive; the
  transaction arrives signed. Our server can't move the money, and a copy of its database can't either. That is the
  same as before: it holds the sales **view** key, sealed to the payment checker, which sees payments and can't spend.
- **Never the destination.** It is inside a stealth output (a one-time key, an encrypted amount). The address stays in
  the browser, in its receipts list.
- **What it learns:** that a withdrawal happened and when; which payments it spent (their ids and values, which it
  already knew); the change the drive sends back (its output id, and the value the drive tells it, so the drive can
  withdraw it later from any device). So it can work out about how much left: the inputs minus the change minus the
  fee. `sales_change` and three columns of `sale_payments` hold this; `/fine-print` lists them.
- **What it checks:** the shape (one stealth transfer paying its own fee of at most the network fee, one or two outputs,
  at most 8 inputs), that every input is a settled output of this drive, that none is already on its way, and that
  the change it is told about is one of the transaction's outputs. The network checks the signatures and the balance.

## Threat-model delta

- **Withdrawal is signed only in the browser; the server never holds spend keys.** A compromised server can refuse
  to relay a withdrawal, delay it, or lie about what is ready. It can't move a payment or redirect a withdrawal: the
  outputs are bound to the address in the browser before signing, and any change to the transaction breaks its
  signatures. A malicious build of the app could, which is the existing "a malicious version of this website" risk
  (threat-model.md, "Verify"): the drive's seed is in the browser that runs it.
- **The owner could bypass our relay.** The drive's key can spend any output it owns, through any indexer. An owner who
  spends a payment before it is counted harms their own buyer. That is a dishonest seller, as in the existing table.
  The app and our relay only spend settled money.
- **Metadata:** our server now sees when a seller withdraws, from which payments, and the change. It never sees the
  destination or the amount that arrives, except as that difference. On chain, a withdrawal looks like any other
  stealth transfer: hidden amounts, one-time owners, a public fee.
- **Griefing:** withdrawals take a session, are rate-limited (12 an hour per drive, 30 per network) and draw on the
  indexer client's send lane, as direct sends do.

## Tests

- `server/tests/test_withdraw.py`: the flag, settled money only, the marks and the pending window, the outcome reports,
  shape and change checks, a relay that fails, the limits, and deleting the drive.
- `web/app/tests/withdraw.test.js`: the amounts, the plan (fee, minimum, dust, cap), the address checks (another
  network, checksum, payment reference, the drive's own), and whole withdrawals built from genuine outputs. No key or
  address leaves the browser, and a second press is refused.
- `web/app/ui/tests/flows_withdraw.py`: Earnings → Withdraw on a phone and a computer: refused addresses, the confirm
  step, one submission however often Send is pressed, the receipt and What the chain sees. Our real server checks and
  relays the withdrawal.

## Not yet

- A payment reference on the destination (exchanges that need a tag): refused for now, with its own message.
- More than 8 payments in one withdrawal.
- The amount that arrives is shown before Send. The receipt in this browser keeps it; other devices see only what
  left the earnings.
