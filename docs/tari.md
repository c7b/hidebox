<!-- SPDX-License-Identifier: MIT -->
# Where Tari™ comes in

**hidebox** runs on the [Tari™ Ootle](https://ootle.tari.com) testnet (Esmeralda). Tari does the private parts:
a file's key travels to an address inside a stealth payment, more space is paid in tTARI and checked on the
chain, and every file that leaves gets a receipt in a public log on the Ootle. Each row says where to check it.

| Tari capability | What it does in **hidebox** | How you check it |
|---|---|---|
| Stealth outputs (amount and owner hidden) | Send by Tari, dead-drop deliveries, more space, pay to open | `/verify/tx/<id>`: amount hidden, owner a one-time key, memo encrypted, fee public |
| Encrypted memo | Carries a file's key, sealed to one Tari address's owner and view keys (125 bytes) | Only the recipient's keys open it; any other key fails |
| View keys, separate from spending | Received scans the chain in your browser; `/watch` shows what a view key sees; for pay links, a seller's view key, sealed on our server, sees payments and never spends them | A view key reads arrivals and amounts, can't spend and can't open files sealed to a drive |
| Invoice addresses with a reference | Matching a payment to its invoice or pay-link claim without accounts | The payment's memo carries the reference; nothing on chain links it to you |
| Payments checked against chain state | Crediting more space; releasing a pay link's key half | The official Tari library (ootle-wasm, in a sandboxed sidecar) opens the commitment to the exact amount; a Tari-run indexer shows it committed; a payment counts only if its one-time key is ours ([code](../server/mutis/payments.py)) |
| A template: SealLog | A public Merkle log of the ciphertext hash of every stored file, a receipt for every file that leaves, and release notarizations | `/verify`: inclusion proofs against the component's state on the Ootle; `template/check.sh --onchain` |
| Keypair identity | Your drive and its Tari address, made in your browser | There is no email field anywhere |

Why not an escrow template: TARI held by a template reveals its amount on the Ootle, while native
stealth outputs keep it hidden, so **hidebox** uses those.

Where each part lives in the code: [architecture.md, "The Tari parts"](architecture.md#the-tari-parts). The
judges' walk-through of the same claims, step by step: [/judges](https://hidebox.app/judges).

**hidebox** is an independent project, not affiliated with, endorsed by, or sponsored by Tari Labs, the Tari
Council, or the Tari project. "Tari" is a trademark of Tari Labs. All rights reserved.
