<!-- SPDX-License-Identifier: MIT -->
# The November MVP (mainnet lane)

The owner's answers of 2026-11-07 for the Tari contest entry due 2026-11-25, as a plan, then what was built. Everything
here goes to the mainnet lane (`launch/mainnet`, the instance at `mainnet.hidebox.app`, a beta). The testnet deployment
(hidebox.app, the October entry) gets no change from it beyond Ootle upgrades and bug fixes until the October winners
are announced.

| # | The owner's answer | What it becomes | Flag (mainnet lane) |
|---|---|---|---|
| 1 | Sellers withdraw earnings on the mainnet | `mvp/withdraw` verified, its gaps closed | `features.withdraw` on |
| 2 | A purchase opens without the seller online | the payment checker runs the ownership check with the view key of the sales address | `features.away_release` on |
| 3 | A readable shop address | `/shop/<username>`, private (default) or public | `features.shop` on |
| 4 | Paid space packs on the mainnet | packs sold in TARI, as a beta | `features.packs` on |
| 5 | hidebox.app unchanged | nothing here reaches it | (none) |

Later, not now (recorded in [overview.md](overview.md#status-and-roadmap)): elastic storage; paying with Monero, Tari
and Zcash.

## Plan

### 1. Withdrawals (rigour: real money)

Read the server's checks, the browser's builder and the tests again against the chain's rules, run every suite, and fix
what doesn't hold. Known before starting: the confirm step's address split assumes an `otl_esm_` address; an input the
chain no longer has (spent elsewhere) blocks every later withdrawal that picks it.

### 2. Release without the seller's drive

Since Ootle 0.48 a stealth output's one-time key is `P = H(network ‖ v·R)·G + K`: the view key `v` and the address's
account key `K` are enough to check it, the check a watch-only wallet runs. The payment checker already holds the view
key of each seller's sales address (sealed, opened only in the chain worker's memory) and the address. With `features.away_release`
on, it checks each sale output's one-time key when it counts the payment: equal releases the claim (`owner_ok = 1`,
checked by `server`), different voids it, as the drive's check does. The official library has no point addition, so
`web/app/lib/ristretto.js` adds the two public points (RFC 9496), checked against the RFC's vectors and against the
library itself. The drive's own check stays for claims counted before the flag, and a drive can still refuse a payment
before it releases. Threat-model delta: the release no longer needs the seller's device; what the server learns doesn't
change (it already read each payment); who decides does.

### 3. A shop's address

`/shop/<username>`, a name the seller picks: ASCII `a`–`z`, `0`–`9` and single hyphens, 3 to 30 characters, no hyphen
at either end, case-folded, not a reserved word, not a look-alike of the brand or of another shop's name. Two modes:

- **Private** (the default): `/shop/<username>#6<shop key>`. The key stays after the `#`; reading the shop takes a
  token derived from it, so knowing the name alone shows nothing; `noindex`.
- **Public**: `/shop/<username>` is a page anyone and any search engine can read: names, lines, prices, server-rendered
  with title, description, canonical, OpenGraph, a sitemap entry and accurate structured data. Buying from it without
  a key means our server serves the shop key, so **our server could open what a public shop lists**. No design keeps
  the files closed to us there: whatever any visitor can fetch to buy, our server can fetch too, and it holds the
  other half of every pay link's key. The owner is told before switching.

Every piece of user text is escaped for the place it lands (HTML text, attributes, JSON-LD, meta tags, URLs); the
page keeps the app's content security policy.

### 4. Packs on the mainnet

Turn `features.packs` on in the mainnet instance's configuration, keep the packs' ids, sizes, days and prices
(docs/review/packs-small.md), and make the mainnet pages say packs are a beta, paid in TARI on the mainnet.

## Process

Plan (this file), then build with tests; run the full suites and the UI flows that run locally; then an independent
review (`code-critic`) and a security audit of the new surfaces (username input, public pages, release rule,
withdraw); fix what blocks.

## What was built (branch `mvp/november`, on `launch/mainnet`)

| # | Built | Where |
|---|---|---|
| 1 | Withdrawals checked again end to end; two gaps closed: an output spent elsewhere leaves the withdrawable list once an indexer proves it spent and none serves it live (from 2026-11-10: a 404 is never proof) (`POST /me/sales/outputs/{id}/gone`; the drive's word alone changes nothing), and the confirm step splits a mainnet address after `otl_1` | [withdraw.md](withdraw.md) |
| 2 | `features.away_release`: the chain worker runs the watch-only check when it counts a sale payment (`chain_worker._sale_owns`, `sales.count`); equal releases with no drive online, different voids, can't tell (no plain key, no nonce, no view key, a changed address, a sidecar refusal, a selftest that didn't pass) leaves it to the drive. `lib/ristretto.js` adds the points; the sidecar's `watchOneTimeKey` and selftest; migration 010 (`checked_by`) | [threat-model.md](threat-model.md) "Release without the seller's drive" |
| 3 | `/shop/<username>`: the name rules, Private (token-gated reads) and Public (the page filled in for search engines, `/sitemap-shops.xml`, the key on our server), private again with a new key; migration 011 | [shop.md](shop.md) "The address" |
| 4 | `features.packs` on in `deploy/config/instance.toml.example`; the mainnet pages already say TARI on the mainnet, a beta, small amounts | [review/packs-small.md](review/packs-small.md) |
| 5 | Nothing for hidebox.app; the mainnet lane's switches for an instance already provisioned are in `deploy/ootle/mainnet-launch.md` §4b | |

**The review line.** [overview.md](overview.md#status-and-roadmap) scopes "paid features open only after that review" to
hidebox.app, and says the mainnet beta sells space packs in TARI; "hidebox stays on the testnet until its code is reviewed"
stays the testnet deployment's line, which the owner keeps unchanged for now. The mainnet lane's own pages say the same:
paid features there are a beta, paid in TARI on the mainnet ("Ootle mainnet" notes on `/made`, `/fine-print` and every
money screen).

## Review

Two independent reviews of `git diff 96260d5..HEAD`: a code critic (the suites, plus its own probes: 60 hostile
usernames, 14 hostile payloads through the public page, the real sidecar's selftest on both networks) and a focused,
source-only security review of the four new surfaces.

| Finding | Severity | Fix |
|---|---|---|
| The sidecar's selftest failed on a mainnet sidecar (its frozen outputs are Esmeralda's), so the worker's new gate would never have trusted the watch-only check there: `away_release` dead on the lane it was built for, and its copy wrong | blocking (both reviewers) | the frozen outputs run on Esmeralda only, fresh ones on every network; `sidecar_test.py` runs the real selftest with `MUTIS_NETWORK=mainnet` |
| A tab holding the old key could list under it after the shop went private again | low | every listing write names its key (`key_wrap`, 409 `key_changed`) |
| A removed private shop answered 410 to its name alone | low | the token is checked open or removed |
| The docs said a private shop's name shows nothing; taking it shows it is taken | low | reworded |
| Look-alikes folded in the wrong order (`c1ara` beside `clara`), `4` and `7` not folded | low | single characters first, then pairs to a fixpoint |
| The sitemap: one query per public shop, no rate limit | low | one query, 10 a minute per network |
| Gone counted "can't prove it is there" as gone | low (the seller's own money) | only a JSON 404 or a spent state; from 2026-11-10 only a verified spent state ([withdraw.md](withdraw.md)) |
| A refused selftest stopped every sale from counting | low | treated as not passed; sales count for the drive |
| Going private could reuse the published key; holds uncapped; HEAD on a shop page answered 501; a report of a free name tied to its next holder; a takedown kept the published key; a failed selftest cached until a restart; any JSON 404 read as gone | informational / nits | all fixed |

Left as they are: migration 011 recomputes no stored skeletons, because it has never run anywhere (it is new in this branch); names joined without a hyphen (`tariofficial`) pass the per-part check, as the rule says.

After the fixes: server 479 tests (5 skipped, the opt-in ones), deploy 151, site 31/31, app core 184/184 in Node and headless Chromium, the
sidecar on both networks, and the UI flows for the shop, withdrawals, pay links, the owner's check, packs and the
Upgrade dialog all pass on this machine. Not run here: the end-to-end scenarios (they run against a deployment) and the
sidecar test's Node 20 version check (this machine has Node 22).
