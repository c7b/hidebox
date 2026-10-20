<!-- SPDX-License-Identifier: MIT -->
# Earnings and Activity at scale (2026-10-19)

Two requests from the owner for the drive (`/drive`):

- **P3, "Where's my money?"** A visitor paid to open the owner's folder, and nothing in the drive showed that the
  owner got paid or what the balance is.
- **P4, Activity doesn't scale.** One upload of 22 files made 22 rows, "Locked and uploaded · file · size · 4:00 PM",
  all in the same minute; and the folders of that upload ("hidebox-brand", "snippets") read "Locked and uploaded"
  too.

Branch `drive/earnings-activity`, rebased on `main` and pushed to it commit by commit. Not deployed.
Evidence: [`docs/evidence/2026-10-19/drive-earnings-activity/`](../evidence/2026-10-19/drive-earnings-activity/).
Kept: DESIGN.md's v3 look and its budgets; one lime per view (Earnings has none: nothing there is a next step, like
Activity); one sentence a line; Say It Once (the only claim sentences on the new view are registered ones: C33 and
C19-k). No library, install, font or icon was added; the Lucide sprite already had every glyph used.

## P3: where the money lands

**The answer.** Every drive has a **sales address**, separate from its own Tari address (the one Received scans) and
from its browser wallet (the one that pays "Pay from my drive" and direct sends). It is an Ootle stealth address whose
two secret keys are made in the browser from the drive's key: `lib/ootle.js` `deriveOotleKeys(seed, 'sales')`,
HKDF-SHA-256 over the drive's seed with the labels `sales-owner` and `sales-view`, reduced to Ristretto scalars.
A buyer's claim is that address with the claim id as its payment reference; the buyer's payment, or our demo wallet's
test money (built for the full price to the claim's address), is a **stealth output to the sales address on the
Esmeralda testnet**. Our server holds only the sales address's **view** key, sealed to the payment checker (`PUT /me/sales`): the
chain worker finds each payment, proves its amount and sees it committed; it can't spend it. The drive's owner check
(`lib/pay.js` `auditOutput`) compares each output's one-time key with the one its sales owner key derives, so the
money counted is money only the drive's key can spend. Nothing ever spends it: the drive has no code that does, and
its owner check takes a sales output that is gone for one the payer kept control of.

So the balance is the sum of those outputs, and it stays at the sales address until someone with the drive's key
spends it.

**Can a Tari wallet take it?** No, not today. What we checked (the Ootle wallet daemon, `tari_walletd`, in
`tari-project/tari-ootle` on its development branch as of today):

| A wallet could take | What it would need from us | What Ootle's wallet does |
|---|---|---|
| A seed (seed words) | the drive's seed as a Tari CipherSeed | Accounts come only from the wallet's own CipherSeed, at derived indexes (`accounts.create` takes a `key_index`; an account is the Account branch's key plus the ViewOnlyKey branch's key at that index). The drive's seed is 32 random bytes and the sales keys are our own HKDF labels, so no seed words would make the same address. |
| A view key (watch only) | the sales address's view key | There is no view-key import and no watch-only account. |
| A secret key | the sales owner key, or each output's one-time key `c + k` | `keys.import` stores a raw secret key in the key manager, but it makes no account and no address: the wallet doesn't scan stealth outputs for it, and its transfers spend only the outputs of its accounts. A one-time key per output would also need the output's value and mask registered as the wallet's own UTXO; no call does that. |

So there is no safe, honest import. Showing the sales owner key would put a spending key on the clipboard with nowhere
to use it; we didn't. The app says exactly what a person can do today, under **Where the money is**: the sales address
with Copy, "The money goes straight to your Tari address. We never hold it." (C33), "Only your drive's key controls it. Keep your key file safe.", and under **Can I move it out?**: "Not yet. Tari's wallets can't use this key today,
and your drive can't send it on. It stays at this address." Each test-money payment's transaction opens on
`/verify/tx/<id>` from its row; a payment from another wallet has no transaction id on our side (only its output), so
it shows none.

**What a withdrawal would take (next, not built).** A "Send it on" from the drive: a stealth transfer whose inputs are
the sales outputs, unblinded with the sales address's view key and each signed with `stealthDhSecret(sales owner key, nonce)`,
the same transaction shape `lib/wallet.js` `send()` already builds for the browser wallet, to an address the owner
types (their Ootle wallet's). It is not small: the owner check must first learn which sales outputs the drive spent
itself (today a sales output that is gone means the payer kept control, and voids the claim), and the release gate
needs its review again. The view says "Not yet" until then.

## P3: what Earnings shows

`/drive/earnings`, in the sidebar after Shared wherever pay to open is on (`features.pay_to_open`). Built on the data
Received → Payments had (`GET /me/sales`, `ui/sales.js`), which moves here: Received keeps what was sent to the drive.

| Part | What | From |
|---|---|---|
| Paid to you | the total in violet (an amount of tTARI), "N payments to your pay links.", Test money (what our demo wallet paid) beside Paid from a wallet, and the testnet line (C19-k) | `GET /me/sales` `total`, new: every payment we can vouch for, not only the newest 50 |
| By link | each paid link, paid last first: its name (opens its activity sheet), what it took in, Test money when part of it was, when it was last paid, its opens, the newest transaction we know | `GET /me/sales` `links`, new; names from the drive's index, decrypted here |
| Payments | the newest 50 payments with Test money, Checked, the tx, and the owner check (Yours to spend, Checking, The payer kept control of this payment) | as before; on a phone the check sits under the name |
| Where the money is | the sales address this browser derives from the drive's key, with Copy; the two lines above | `lib/pay.js` `salesKeys` (ootle-wasm, loaded on this view); without WebAssembly, the address the drive registered |
| No payments yet | "Share a file with Someone who pays you. What they pay shows up here." | |

The server's new fields (`server/mutis/handlers/pay.py` `get_sales`, `docs/api.md`): `total: {received_ut, test_ut,
payments, links}` and `links: [{share_id, received_ut, test_ut, payments, last_at, views_used}]` (at most 200 links).
Counted: what we can vouch for is the owner's. Test money our demo wallet paid for a claim's whole price (it built
the output to the owner's address), and payments the drive's owner check found are its own (`owner_ok` 1). Not
counted: a payment still waiting for that check (Earnings runs it as it opens, then asks our server again, so it
counts a moment later), a part of a price (the check only reaches paid claims), and a payment the payer kept
(`owner_ok` 0). A view key proves an amount, never who can spend it (R2), so "it reached the address" isn't enough.
The Payments table still lists every one with its check. `paid_summary`'s `earned_ut` (the share list's badge data,
not shown anywhere) keeps its looser sum.

**Checking the totals in the browser (asked: worth it later?).** Yes, later. The owner check already walks the chain
mirror with the sales address's view key and reads each output's one-time key from the indexer, so this browser holds every
sales output it found and whether it is the drive's to spend (`lib/pay.js` `salesState`). Summing those gives the
address's balance without our server's word. It is small in code, but it needs its own words before it ships: it
can differ from our count for honest reasons (money sent to the sales address without a claim, outputs from before
this browser's walk starts) and on a phone the walk takes a while. A "Check it in this browser" line under the total
is the shape; not built now.

## P4: the grouping rules

The Activity rows are written in the browser (`ui/activity.js`) from the drive's index: each item's created hour,
each link's created hour and its opens counted by the hour, the files that left (`view=gone`), and now the payments our server
counted. Pure logic in `lib/feed.js`, tested under Node and Chromium (`web/app/tests/feed.test.js`).

- **Together** means the same kind, in the same folder, in the same hour. Our server keeps uploads, links and opens to
  the hour, never the minute (C40), so the hour is the finest window there is; a payment's exact time falls in its
  hour. One event alone is its own row, as before.
- **Kinds and their rows of several:** "Locked and uploaded 20 files to hidebox-brand" (its padded size and hour),
  "Created 2 folders in hidebox-brand", "Made 3 links in snippets", "4 files in snippets opened 9 times", "Paid 3
  times" (the amount), "2 links ended in My drive", "3 files left your drive". The folder is the parent's name,
  decrypted here; the top level is My drive. Files that left keep no folder on our server, so their rows stay apart
  ("2 files that left opened 5 times").
- **Folded:** a row of several shows "Show all 20" (`aria-expanded`), which opens the list of its files: name (opens the
  file's sheet), size, opens, amount or chain line. It stays open while the list redraws.
- **Order:** newest first; in one hour, what happened last first (left, ended, opened and paid, made, uploaded, a folder
  made), then the bigger row.
- **Days:** Today, Yesterday, then the weekday and date, each with the whole day's count of events ("Today 33 events"),
  even before Show more reaches its last rows. Events with no time (a link that ended: our server keeps no end time on
  the link it lists) sit under Earlier.
- **The newest 25 rows, then Show more** (25 more each time, focus on the first new row). Not virtualized: grouping
  keeps the rows few (that upload is one row), 25 rows is a light page, and `activity.js` isn't part of the drive's
  first screen, so A-06d doesn't move with it.
- **Chips:** All, Uploads (uploads and folders made), Links (made and ended), Opens, Payments (where pay to open is on).
  Files that left are under All. Search filters the list by name, in place, like My drive.
- **Download the list:** every event, whatever the chips show, as CSV (`time_utc` in ISO 8601, `event` in words, `name`,
  `folder`, `size_bytes` padded, `opens`, `amount_ttari`, `demo_wallet`, `tx_id`), made in the browser as a Blob and
  saved through a download link as `application/octet-stream` (`lib/download.js`; the page never navigates). A cell
  that starts with `=`, `+`, `-` or `@` gets an apostrophe first, so a file named `=SUM(1,2).svg` never runs in a
  spreadsheet. A byte order mark first, so spreadsheets read names as UTF-8.

**The bug.** `itemEvents` gave every item an `uploaded` event, folders included. A folder now gets `folder`, "Folder
created" with the folder-plus icon, in the feed, the file's sheet and the CSV. The server already sent each item's
`kind`; nothing changed there.

## Budgets

| Budget | Before (`main`) | After |
|---|---|---|
| A-06d, `/drive` until the table renders (of 131,072 B) | 125,555 B, 38 files (`main` at `c842fcc`) | **126,662 B**, 38 files (+1,107 B) |
| What changed in those files (gzip -9) | | `drive.css` +459 B, `en.json` +508 B, `drive-shell.js` +95 B, `drive.js` +59 B |
| Loaded only on their views | | `activity.js` 6,074 B (was 3,259), `drive-earnings.js` 2,969 B (new), `lib/feed.js` 1,813 B (new), `sales.js` 2,675 B (was 2,332) |

A-06 (the home's widget) and M-01 are untouched: no file of theirs changed.

## Suites

All on the server as `build` (Python 3.13.5, Node 20.19.2, Chromium 155), on a copy of the rebased branch; logs in
the evidence's `suites/`.

| Suite | Result |
|---|---|
| App UI (`web/app/ui/tests/run.py --shots`) | 1115/1115 on the branch rebased onto `c842fcc`. The new scenarios: `activity-groups` 24 checks, `drive-earnings` 22; `owner-check` (now in Earnings) 12, `seller-activity` and `activity-gone` 8 each. On earlier rebases `share-rules` (the share dialog, not touched here) timed out once in the full run and passed alone, the flake `owner-5.md` records on `main` |
| App core (`web/app/tests/run_all.py`) | ALL PASS, 9 steps (the new `feed` suite under Node and in Chromium). On the previous rebase its phone scan benchmark timed out once under the server's load and passed when run again |
| Server (`unittest discover -s server/tests`) | 356 OK, 5 skipped (`test_release_gate` has the totals; `test_paid_shares` the new answer's shape) |
| Site (`web/site/tests/run.py`) | 44 of 44 (`/judges` now says Earnings, then Payments) |
| Deploy (`unittest discover -s deploy/tests`) | 100 OK |
| `tools/lint.py`, `tools/check-copy.py` | PASS, PASS |
| `tools/build.py` | OK, 218 files |
| `tools/check-seo.py --dist` (on the workstation, a fresh build) | PASS, 13 checks (`/drive/earnings` among the private routes) |

An independent review (a second agent, read-only) found the e2e chain scenarios, the film and `/judges` still sent
people to Received for Payments, and that the first count trusted payments nobody had checked; both are fixed (the
commits after `Earnings in the drive`), with its two nits: the newer answer from our server always wins on the page,
and Where the money is says the key controls the money rather than that it can spend it. The chain e2e itself
(`tests/e2e/scenarios_chain.py`) needs the live testnet and was not run here.

## Left for later

- Moving the money out (above), and the client-side balance check (above).
- Activity lists the payments `GET /me/sales` lists, the newest 50 (the totals on Earnings count every one).
- A link's end time: `shares.ended_at` exists, but the drive's item list doesn't send it, so ended links sit under
  Earlier.
- The UI flows fake the pay routes (`PayFake`, now with the server's `total` and `links`); the server's own totals are
  checked by `server/tests/test_release_gate.py` on the fake chain.
