<!-- SPDX-License-Identifier: MIT -->
# Copy pass 1: the owner's findings (2026-10-18)

The owner read the site and the README and found AI tics and repetition. This pass fixes every finding, adds the Say It
Once rule to DESIGN.md and applies it to the home, the README, /how, /judges, `docs/*.md` and the drive's words.
Branch `copy/pass-1`, pushed to `main` commit by commit; **the coordinator deploys it** (no `deploy.sh`, no
production file, no tag moved here). The raw evidence (`docs/evidence/2026-10-18/copy-1/`) was pruned on 2026-10-20; the results it
recorded are below.
`/v2` keeps the copy it was made with, on purpose: only the share card's alt text changed there, because the card did.

## The skills

Three skills were added to `.claude/skills/` (text files and their MIT licences, read before use, nothing run):
**humanizer** (blader/humanizer `8c307f3`, Wikipedia's "Signs of AI writing"), **copy-editing**
(coreyhaines31/marketingskills `365b412`, the seven sweeps: So What cut what a table already said, and Prove It held
every privacy sentence to its registered claim and evidence) and
**better-writing** (boraoztunc/skills `645553c`, from Jakub Krehel: verb-first buttons, errors that say how to fix,
empty states that point forward). The project's **impeccable** skill (`clarify`) set the order for each message:
what happened, what to do next, then context.

## The headline

"Privacy isn't an option. It's the default." is the not-X-it's-Y tic (humanizer §1, the copy-editing AI-tell check's
contrast reveal) and says nothing a reader can check. The second line now says the one fact the product is built on.
Measured in Chromium in the hero's own place and style (`tagline_candidates.py`, `tagline-candidates.json`; the line is
19.5 px at 390 and 34 px at 1440; the shipped line again in `headline.json`):

| Candidate | 390 (box 358 px) | 1440 (box 549 px) | Why |
|---|---|---|---|
| **Files lock in your browser first.** (shipped) | 274 px, one line | 478 px, one line | Where and when, in plain words; the lede's "each file" follows from it |
| Your browser locks every file. | 261 px, one line | 456 px, one line | Says where but not when; three lines of the hero would start with "Your" |
| Each file is locked before upload. | 294 px, one line | 512 px, one line | Says when but not where, in the passive |
| Locked in your browser before upload. (measured, rejected) | 341 px, one line | 594 px, two lines | Fits a phone, but at 1280 and 1440 it leaves "upload." alone on a second line |
| Files lock in this browser before upload. (C32 as it is, rejected) | 355 px, one line | 618 px, two lines | The same, and 3 px from wrapping on a phone |

The shipped line is C32's claim in other words, so the registry records it ("Files lock in your browser first." with
its own marker). It is also the share card's line (`og.png` re-rendered, its alt text on every page), the drive
page's description, the README's title and the film's end card (`tools/film.py`).

## The key statements (DESIGN.md, the Say It Once rule)

Each is said once per page, in its best place and its registered words; elsewhere on that page it is a short answer
or a link.

| # | Statement | On the home |
|---|---|---|
| 1 | The lock: "Files lock in your browser first." (C32 elsewhere: "Files lock in this browser before upload.") | The headline |
| 2 | "Our server gets scrambled noise. Never the key." (C1-n) | The comparison |
| 3 | "Search runs in this browser. Our server can't read your file names." (C43) | The comparison |
| 4 | "Each file or folder gets its own rule. You can stop a link any time." | Share it your way |
| 5 | Pay to open, with the payment line said once for Send by Tari and Pay to open: "The chain shows a payment with a hidden amount and a hidden owner. The fee is public." (C36) | Tari does the private parts |
| 6 | "When a file leaves your drive, we write that on the Tari chain, for anyone to check." (C42) | Tari does the private parts |
| 7 | "No email, no password. Your key is the account." | Under Open your drive |
| 8 | "Save your key. If this browser forgets it, nobody can let you back in, not even us." (C17-k) | The comparison |

The testnet line is the footer's, on every page. /judges' What to check table is the one place a page lists the
claims word for word; its steps say what the app shows. /how's stills are pictures of the app and keep its words.

## Findings

Pass: **H** humanizer, **CE** copy-editing (AI-tell check, So What, Prove It), **BW** better-writing, **S1** the Say
It Once rule (the owner's findings are marked **owner**), **TM** the Tari™ trademark rules (research 02 §6).

### Home (`web/site/pages/index.html`, the shared partials)

| Where | Before | After | Pass |
|---|---|---|---|
| h1, second line | `Privacy isn't an option. It's the default.` | `Files lock in your browser first.` | H §1, CE, owner |
| Lede | `Files lock in this browser before upload. You pick how each one opens: once, with a word, or for Tari™.` | `You pick how each file opens: once, with a word, or for Tari™.` | S1 owner (the headline says the lock) |
| What's different, intro | `Your files lock here, in your browser. A usual drive locks them on its own servers, with its own key.` | (removed) | S1, CE So What (rows one and two say both halves) |
| Comparison, where files get locked | `Files lock in this browser before upload.` | `In your browser.` | S1 owner |
| Comparison, a link that opens once | `It opens one time. Then the link ends.` | `Yes, by default.` | S1 (Just share one thing says it) |
| Comparison, a public record | `We write that on the Tari chain.` | `Yes, on the Tari chain.` | S1 owner |
| Who sees what, intro | `Four sides of every file. Here is what each one can see.` | `Four sides of every file.` | H §4, §25, owner |
| Tari, Pay to open row | `Pay to open: they pay your Tari address, then it opens. The chain hides the amount and who got it. The fee is public.` | `Pay to open: they pay your Tari address, then it opens.` | S1 owner (the section's intro says it) |
| What's tTARI? box | the testnet line (`status-line` include) | (removed) | S1 owner: the box and the footer both showed it. Checked in the source: both copies hold the same pre and mainnet pair that `dates.js` `applyPhase` switches on Nov 11, so neither is date-gated against the other and both showed at once. The footer keeps it on every page (`check_partials`) |
| Closing | `One tap, and it's yours. No email, no password.` | `One tap, and it's yours.` | S1 owner (three times on the home) |
| Footer (every page) | `Built on the Tari™ Ootle testnet. Free, with no sign-up.` | `Built on the Tari™ Ootle testnet. Free to use.` | S1 owner (the third time) |
| h2s | `Share it your way.`, `Tari does the private parts.`, `Make your drive.` | the same, no period | BW §8 (one policy per element; /how's h2s have none) |
| Metas | description, `og:description`, `og:image:alt` with the old tagline | the new headline | owner |

### README.md

| Where | Before | After | Pass |
|---|---|---|---|
| Title | `Your private cloud storage. Privacy isn't an option. It's the default.` | `Your private cloud storage. Files lock in your browser first.` | H §1, owner |
| Under it | `A private drive. Files lock in this browser before upload.` then the rules line | the rules line only, "each file" | S1 owner |
| Try it | `One device, no wallet, no sign-up.` | `You need one device and no wallet.` | S1, H §2 (a row of fragments) |
| Step 1 | `... with your Tari address. No email.` | `... No email, no password. Your key is the account.` | S1 (the README's one place for 7) |
| Delete it after | the file leaves your drive, said twice in one cell | `When the link ends, the file leaves your drive too. We write that on the Tari chain, for anyone to check.` | H (repetition), S1 |
| What the server never sees | `We count opens per hour. We never store who opened it or their IP address.` | (removed) | S1, CE So What (two rows of the table above say it) |
| Architecture | `Nothing is installed from npm or pip; one pinned, hash-checked third-party piece (...)` | two sentences with verbs | H §11 |
| Licence | `Built on Tari Ootle™.` and the trademark line | `Built on the Tari™ Ootle testnet.` and `All rights reserved.` | TM (B.6, B.7), as the footer |
| Picture | `docs/media/home.webp` showed the old tagline | re-shot from this tree, 1440 × 900, dark | owner |
| Host | `srv2052606.hstgr.cloud` | `hidebox.app` (also SECURITY.md and `docs/*.md`) | the coordinator's new fact |

### /how and /judges

| Where | Before | After | Pass |
|---|---|---|---|
| /how lede | `Your drive opens with a key that lives in your browser. Everything you add is locked before it leaves, and Tari™ does the private parts.` | `Your drive opens with a key that lives in your browser.` | S1 (the lock is step two's, the Tari line is step four's heading) |
| /how, Open your drive | `Your browser makes a key. The key is the account. No email, no password.` | `The key is the account. No email, no password. Your drive also gets a Tari™ address.` | S1 (the lede says the key); the still shows the address; TM (™ on the first mention) |
| /how, Tari does the private parts | the payment line in text beside the still that shows it (both variants) | Send by Tari, and Pay to open's first sentence | S1 (the still and Who sees what's chain card say it) |
| /how, What's tTARI? | the testnet line | (removed, as on the home) | S1 |
| /how, outro | `Want every detail? Read Under the hood.` | `Every detail: Under the hood.` | CE (self-answered question) |
| /judges lede | `See something else? It's a bug: tell us on ...` | `If a step shows something else, it's a bug: tell us on ...` | CE (self-answered question), BW §4 |
| /judges, track one | `About two minutes. No sign-up.` | `About two minutes.` | S1 (What to check's row says it) |
| /judges, step one | `... with your Tari address. No email.` | `... with your Tari address.` | S1 |

### docs/*.md (12,028 words; humanizer in file mode)

The docs were mostly clean: no dashes in prose, no inflated words, and their contrasts correct real misreadings
("Encryption hides contents, not everything."), so they stay.

| Where | Before | After | Pass |
|---|---|---|---|
| architecture.md, trust boundaries | `The price of that key never touching disk: a restart ...` | `Because that key never touches disk, a restart ...` | CE (colon reveal), H §4 |
| architecture.md, verify | a list of dependencies with no verb | `The project depends on ...` | H §11, §2 |
| api.md, the submit proxy | `... anything else is 422 invalid. The proxy is not a relay for other transactions` | `... anything else is 422 invalid` | H §2 (a closer that repeats the rule; "relay" is also a send mode's name) |
| threat-model.md, limits | `What this does and doesn't do. The per-network counts ...` | `The per-network counts ...` | H §4 (announces) |
| docs/README.md, About | `a drive for your files that opens only with your key, made in your browser` | `a drive that opens only with a key made in your browser` | H (clarity) |
| Every doc | the first Tari mention without ™ | `Tari™` on the first mention (README, privacy, tari, api, architecture, self-host, threat-model) | TM |
| tari.md | the trademark line | ends `All rights reserved.` | TM |

### The drive (`web/app/i18n/en.json`)

| Where | Before | After | Pass |
|---|---|---|---|
| Ten errors and headings | `Oops. ...` (upload broke, upload too long, server, tab, network, didn't open, didn't finish opening, didn't pass its check, page isn't here, no drop) | the sentence without `Oops.` | BW §10, §2 (errors: calm, plain) |
| `error.rate_limited` | `Easy. You can do that again in {wait}.` | `You've hit a limit for now. You can do that again in {wait}.` | BW §2 |
| `error.internal` | `Our server tripped.` | `Our server hit an error.` | BW §4 (no idioms) |
| `error.upload_expired` | `so we let it go` | `so we stopped it` | BW §4 |
| `error.network` | `We couldn't reach our server. Try again.` | `... Check your connection and try again.` | BW §10 |
| `error.bad_link` | `This link is incomplete or was changed.` | `... Copy all of it again, or ask the sender for a new one.` | BW §10 |
| `error.drop_not_found`, `drop.not_found` | `No drop here.` | `There's no drop at this link. Check you copied all of it.` (the heading: the first sentence) | BW §10 |
| `error.wrong_password` | `That's not it. It stays locked.` | `That's not the word. It stays locked.` | BW §4 |
| `error.bad_claim` | `This payment belongs to another browser.` | `... Open the link in the browser you paid from.` | BW §10 |
| `key.pm_failed` | `The password manager didn't take it.` | `The password manager didn't take it, so use Save my key.` | BW §10 |
| `viewer.save_yes` | `Yes, save {name}` | `Save {name}` | BW §5 |
| `rec.drop_new`, `drop.new` | `New drop link`, `New link` | `Make a new drop link`, `Make a new link` | BW §5 |
| `drive.search.none` | `Nothing here has that name.` | `... Clear the search to see all your files.` | BW §11 |
| Nine strings | "room" (`Get more room`, `Extra room`, `Your room is added`, the size errors) | "space", the word on the drive's own Get more space | BW §2 (one term) |
| `error.sold_out` | `Rented room is sold out for now. We'd rather say no than sell room we don't have. Free room still works.` | `Paid space is sold out for now. We only sell space we have. Free space still works.` | H §1 (X rather than Y), BW §2 |
| `upgrade.lede` | `Free room is a fair share of one real disk. Need more? Rent it with test tTARI.` | `Free space is a fair share of one real disk. Rent more with test tTARI.` | CE (self-answered question), BW §2 |

The drive's buttons already started with a verb almost everywhere, and its empty states already said what to do next
(the empty drive, Trash, Shared, Activity, Received); those stay.

### Counts

| Kind | Fixes | Where |
|---|---|---|
| AI tics (humanizer, copy-editing's AI-tell check) | 12 | the tagline (one finding, in the h1, the share card, the metas, the README, the film), "Here is what each one can see.", three self-answered questions (/how, /judges, the upgrade page), a "rather than" contrast, a colon reveal, two verbless lists, a closer that repeats its rule, a paragraph that announces itself, one unclear clause |
| Repetition (the Say It Once rule) | 19 | the home 9, the README 4, /how 4, /judges 2 |
| Interface text (better-writing) | 35 | "Oops" 10, a joke in an error 1, idioms 2, a recovery step added 5, a vague error 1, verb-first buttons 3, an empty search 1, "room" to "space" 9, heading punctuation 3 |
| Tari™ trademark | 11 | ™ on the first mention in seven docs and on /how, the README's attribution line (two), tari.md's "All rights reserved." |
| The new host | 7 files | README, SECURITY.md, five docs; the film's default origin |

## Word counts

Measured by the site suite (visible words, the home at 390 × 844 and 1440 × 900; budgets 120 above the fold and
800 in all), by `shots_copy.py` (`document.body.innerText` at 1440 after the deployment's variants) and by `wc -w`.

| Page | Before (`021039b`) | After |
|---|---|---|
| Home at 390, above the fold / in all | 46 / 650 | 38 / 586 |
| Home at 1440, above the fold / in all | 64 / 666 | 56 / 602 |
| `/`, visible text at 1440 | 759 | 682 |
| `/how`, visible text at 1440 | 625 | 584 |
| `/judges`, visible text at 1440 | 628 | 626 |
| README.md | 1,165 | 1,149 |
| `docs/*.md` | 12,028 | 12,015 |
| `web/app/i18n/en.json` (the drive's words) | 8,584 | 8,629 (recovery steps added) |

How many times each key statement shows (`statements.json`; the pictures of the app count, since a reader sees them):

| Statement | `/` before / after | `/how` before / after | `/judges` before / after |
|---|---|---|---|
| 1 The lock | 3 / 1 | 2 / 1 | 0 / 0 |
| 2 The server | 1 / 1 | 1 / 1 | 0 / 0 |
| 3 The names | 1 / 1 | 0 / 0 | 0 / 0 |
| 4 The exit rules | 1 / 1 | 0 / 0 | 0 / 0 |
| 5 The chain hides the amount | 2 / 1 | 2 / 1 (the still) | 2 / 2 (a step and its row in What to check) |
| 6 The chain record | 2 / 1 | 2 / 2 (step five and the Activity still) | 2 / 2 (a step and its row) |
| 7 No email, no password | 3 / 1 | 2 / 1 | 4 / 1 |
| 8 Losing the key | 1 / 1 | 1 / 1 | 0 / 0 |
| The testnet line | 2 / 1 | 2 / 1 | 1 / 1 |

## Suites and checks

On the server as `build` (Python 3.13, Chromium, Node 20), on this branch's trees; the logs were pruned on 2026-10-20.

| Suite | Result |
|---|---|
| `tools/build.py` (the example config, local) | OK, 203 files, 7 pages |
| Lint, check-copy | PASS, PASS (0 problems) |
| Deploy tests | 84 OK |
| App core (`run_all.py`) | ALL PASS (9 steps) |
| UI (`web/app/ui/tests/run.py`) | 743/744: `drive-delete-account` timed out waiting for Settings' Delete my drive while another session loaded the box (load average 3.4); alone, 15/15 (`ui-rerun-delete.log`). The promote-v3 pass met the same timeout under load; no string it waits for changed |
| Site (`web/site/tests/run.py`) | 42/42, on the home commit and again on the final tree |
| M-01 (HTML+CSS+JS on `/`, gzip, of 60 KB) | 58.4 KB before, 58.3 KB after |
| A-06 (the drop widget) | unchanged: no widget file changed (`widget-en.json`'s keys untouched, `subset.py --check` up to date) |
| Words above the fold at 390 (of 120) | 46 before, 38 after |

## Screenshots

Pruned on 2026-10-20, with the measures: the hero with the new headline before and after at 390 and 1440, the whole
home, /how and /judges, and the headline on one line at 360, 390, 1280 and 1440 (two before). `docs/media/home.webp`
(the README's picture) is the 1440 dark hero.

## Left, and for the coordinator

- **Deploy** is the coordinator's: `deploy.sh`, verify-deploy, D-01, the E2E batch, the film, and the tag if it moves.
- **The site-v4 live probe** (pruned on 2026-10-20) asked production for the old headline and the old
  `og:description`, and for "Files lock in this browser before upload." twice on the home; it failed against this
  release by design. The drive-v3 probe does not read the home's words.
- **The film** (`tools/film.py`): its end card and default origin follow this pass; it needs rendering again.
- **`docs/media/social-preview.png`** still shows the old tagline. GitHub's card is set by hand in the repository's
  settings, so a new one is the owner's to render and upload.
- **`/v2`** keeps its old words on purpose; only its share card's alt text changed. V-01 (`check_v2`) no longer
  compares /v2's words with the home's; it still holds its links, variants and labels equal to the home's.
- **/made and /fine-print** were outside this pass except for the footer and the share card's alt text; /made's
  party-by-party tables still say "no email" where each party is listed.
- **The home's JSON-LD** `featureList` still names "Dead-drop links" (machine-read, not shown); not changed here.
- **Concurrent work:** the drive's strings were pushed before `ux/feedback-1` landed; its first `en.json` hunk sits
  beside `drop.not_found`, which changed here, so a rebase there may need both sides kept.
