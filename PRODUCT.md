# Product

<!-- impeccable:product-schema 1 -->

> Rewritten by the Phase 6A design lead on 2026-10-13 (second run, "the drive") from the owner's words of
> 2026-10-13 and his first mandate of 2026-10-11 (`research/15-drive-brief.md`), the behaviour spec
> (`research/10-spec.md`), the live `/api/v1/config` and the code (`server/mutis/quota.py`,
> `server/mutis/cleanup.py`). It replaces the "bye" ghost record. No interview was possible (the brief
> rules out questions to the owner and this run has no question tool), so facts from the brief are
> marked **[brief]**, facts from code or config **[code]**, and inferences **[inferred]**.
> Updated the same day by the fix pass after the critique (`research/16-drive-design.md`, the merged design of
> record, §14): the name, pay to open's release gate, folders as a key tree, activity per hour, Delete it after.

## Platform

web

## Users

- **People who want a private place for their files, and to share them their way** [brief]: they
  upload photos, papers, notes, music and video into a drive, then share one file or a whole folder
  once, a few times, until a time, behind a secret word, for a price in tTARI, to a Tari address, or as
  a public link. They want to see what happened afterwards: who opened, who paid, what was delivered,
  what others sent them. Phones first, then laptops. The bar is a child who gets it at a glance
  [brief: "like google.com or uniswap.org"].
- **Strangers who only want to pass one thing, now** [brief]: no drive, no key, no decisions; today's
  anonymous drop widget, kept as the secondary path on the home ("Just share one thing").
- **People who receive a link** [inferred]: they did not choose the product. They need to know what
  they are about to open, what it costs if it is pay-to-open, and what happens when it is gone.
- **The Tari Council judging the October 2026 contest "Spooky Secrets"** [brief]: "the best
  demonstration of Tari's privacy capabilities". Fox and Kinkajou read claims with a cryptographer's
  precision; Naveen judges pixels and motion; Solix78 wants a real use case; BoredElon votes on the
  first ten seconds; coin_artist values worlds and stories.
- **Self-hosters and reviewers** [brief]: one grown-up page ("How it was made") with the threat model,
  who sees what, the Tari capability map and how to verify.

## Product Purpose

A hosted, privacy-first drive on the Tari Ootle. Your drive opens only with your key (generated in your
browser, no email). Every file is encrypted in the browser before upload; a folder means every file in
it is encrypted and hidden. Sharing is a rule on a file or a folder; Tari does the private parts: pay to
open with stealth payments, the key sent inside a stealth output's encrypted memo, view keys that see
arrivals without spending, payments checked against chain state, and every exit written to SealLog.
Space is a product: a free share of one real disk that adapts as people join, and more space bought with
tTARI [brief].

Success means: a stranger makes a drive and has a link in under a minute, or shares one thing without a
drive in ten seconds; the owner always sees each share's state (opens left, ends, paid, delivered); a
judge finishes each script (one device, two devices) in six steps or fewer; every privacy sentence is
true with its condition [brief].

## Positioning

The only entry that is a finished, hosted drive a non-crypto person can use, where Tari's privacy does
the work behind the simplicity: pay to open with hidden amounts and owners, a file key delivered to an
address inside a stealth output, view keys separate from spending, credits proven against the chain,
receipts on SealLog, and keypair identity [brief]. The rivals are a CLI toolkit (GhostKey), a
sell-a-secret template (Crypt), claimable stealth links (Phantom Drop), a public board (Hauntboard),
a game, and Skydrop (tTARI to a Bluesky handle) [brief].

## Operating Context

- Phones at 390 and 360 wide, laptops at 1440; headless Chromium on the server is the test browser [brief].
- The judge path lives at `/judges`: two tracks of at most six steps, now through the drive; a QR code on
  the computer carries links to the phone [brief].
- Testnet only (Esmeralda); tTARI is worth nothing; Ootle mainnet is due on `{mainnet_date}` [code].
- The chain worker can fail (it did on 2026-10-13); the drive must say so in words, and the anonymous
  path must keep working without it [inferred].

## Capabilities and Constraints

Everything the server and library do today stays reachable; new server work is additive [brief]:

- Today [code]: anonymous drop and link (once, a few opens, a time, a password), lockers (keypair
  identity, kept files, drop links, inbox by chain scan, view key), send to a Tari address (kind 3 and
  kind 4), packs bought with tTARI (s30, m30; one per drive, a few a day) with demo pay, `/verify` of SealLog proofs, abuse reports.
- New, decided at architecture and settled in the merge [code-checked]: folders as a key tree (each file's
  key wrapped under its folder's; the server sees the tree's shape, never a name); pay to open as a split key
  with a per-buyer claim (the money goes to the owner's sales address; our server holds half the key and
  releases it once the chain shows the payment; only test money our wallet built releases at once, any other
  payment waits for the owner's drive to check it is the owner's to spend, because a view key can't prove
  that); activity as opens per hour per link (never who or an IP); a trash; "Delete it after…" per file
  (the owner's "deleted after X time"). Refunds are not promised: the locked payment (an Ootle HTLC) is the
  named next step.
- Space rules, true to the code [code]: the free quota is `clamp(overcommit x free pool / active
  drives, floor, ceiling)`, smoothed hourly; a drive inactive for `{inactive_days}` days loses its files;
  after a pack lapses, nothing is deleted for `{lapse_grace_days}` days, then the oldest kept files go
  until the drive fits (files in the trash first). Any file can be set to delete itself after a day, a
  week or `{max_days}` days; that is the only time rule per file. Deleting files nobody opened in X days is
  not built: it needs a last-read day per file, and it is the owner's call [open].
- **A receipt on the Tari chain only when a file leaves** [code]: an exit leaf is written when a file's
  ciphertext is deleted (`items.unlink`); a link that ends on a file kept in the drive gets none, and no
  sentence may say otherwise.
- Rules that bind every change [brief]: English only; no third-party code, requests, fonts, CDN or
  analytics; no npm, pip, React or Tailwind at runtime; Python standard library for builds; CSP,
  Trusted Types, SRI and the no-innerHTML rule; every privacy sentence from the claim registry
  (`research/11-brand.md` §8, `research/14-ghost-design.md` §10.3, `research/16-drive-design.md` §9.3:
  C32 to C47; C12 and the old C7-d retired);
  every number in copy is a `{variable}` from `/api/v1/config`; test ids change only with their tests.
- The public name lives in one brand constant; the codename mutis stays in code and paths [brief].
- The repository is `https://github.com/c7b/hidebox` (renamed from `c7b/mutis` on 2026-10-14; GitHub redirects the old URL). The SealLog template's `Cargo.toml` keeps the old URL: it was published that way, and the field feeds its metadata hash.

## Brand Commitments

- **The name is "hidebox"** [recommended in the fix pass on evidence; the owner can override it with one
  word]. "shushbox", the earlier pick, is not to be published: shushbox.com is a live wellness platform for
  survivors of sexual trauma and abuse. "snugbox" is a cannabis lockbox brand. Tagline: "Locked here.
  Shared your way." Copy says "locked", never "hidden" alone, because the files are encrypted, not merely
  hidden. The ghost and the name "bye" are retired [brief].
- **No mascot** [brief]. The ghost's one good idea survives as the rule badge: every file and folder
  shows its rule as a named badge with an icon.
- **Google Drive's layout, shadcn/ui's clothes** [brief]: the owner's reference is Google Drive's web app;
  the components are a faithful vanilla port of shadcn/ui (new-york), with Lucide icons and Geist.
- **Words a child reads in one breath** [brief]: product strings at Flesch-Kincaid grade 5 or lower; how
  it was made at grade 8 or lower; three named choices at most per decision; one primary action per
  screen; no numeric field where names do.
- **Tari visible, in a child's words**, with "Tari™" on its first prominent mention per page [brief].
- **Precision over poetry** in any sentence about what we see, store, delete or prove [brief].

## Evidence on Hand

- The live deployment <https://srv2052606.hstgr.cloud> (still the ghost release until the drive ships),
  `/api/v1/config`, `/status.json`, `/evidence.json` [code].
- Test suites: server 204, site 29, UI flows, app 9 steps, deploy 77, E2E 25 scenarios [brief].
- The SealLog component on the Ootle (address in `/config`); the public repository with its threat model.
- The drive prototype and its screenshots (kept outside this repository, `research/design/drive/`, `drive-shots/`).
- Absent, and never to be invented: user counts, testimonials, press, third-party audits.

## Product Principles

1. **It's a drive first.** Your things live in one place; sharing is a rule you put on a thing, never a
   separate product.
2. **You always see what happened.** Every share shows its state; nothing leaves silently.
3. **Say exactly what we do, and what we don't.** Every privacy claim carries its condition and a way to
   check it on the chain or in the code.
4. **Delete before adding.** A screen, option or sentence that repeats another goes; the right default
   replaces a question.
5. **Nothing from anyone else.** No third-party code, font, tracker or request, ever.

## Accessibility & Inclusion

WCAG 2.2 AA: named controls, keyboard-only use (including drag-and-drop alternatives, menus, dialogs and
the command palette), `prefers-reduced-motion`, contrast AA in both themes, 44 px touch targets, no
horizontal scroll at 360 px [brief].
