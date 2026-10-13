# Product

<!-- impeccable:product-schema 1 -->

> Written by the Phase 6A design lead on 2026-10-13 from the owner's brief
> (`research/13-ghost-brief.md`, owner's words of 2026-10-12 and 2026-10-13), the behaviour spec and
> the live deployment. No interview was possible (the brief rules out questions to the owner), so
> facts taken from the brief are marked **[brief]** and inferences are marked **[inferred]**.

## Platform

web

## Users

- **Anyone who has to pass one secret to one person, now** [brief]: a password, a photo of an ID, a
  note with a door code. On a phone or a laptop, often in the middle of a chat, with no account and no
  wish to learn anything. The bar is an eight-year-old who gets it at a glance [brief].
- **The Tari Council judging the October 2026 contest "Spooky Secrets"** [brief]: seven people who
  vote on "the best demonstration of Tari's privacy capabilities". Some read every claim with a
  cryptographer's precision (Fox, Kinkajou); one votes on the first ten seconds (BoredElon); one judges
  pixels and motion (Naveen); one wants a real use case, "not the theatrical kind" (Solix78).
- **People who receive a link** [inferred]: they did not choose the product. They need to know what
  they are about to open, that it opens once, and what happened when it is gone.
- **Self-hosters and reviewers** [brief]: they need one grown-up page with the threat model, who sees
  what, the Tari capability map and the verification steps.

## Product Purpose

Give the ghost a secret; your friend sees it once; then it's gone, and its goodbye is written on the
Tari chain. The browser encrypts the file before upload, the key travels in the link (or sealed to a
Tari address inside a stealth payment), and the server holds only ciphertext and the clock.

Success means: a stranger gets a copied link within ten seconds of landing, with zero decisions; a
judge finishes the one-device script in about a minute and the two-device Tari script in about five;
nothing on the first screen needs cryptography to be understood [brief].

## Positioning

The only entry in this contest that is a hosted consumer product a non-crypto person can use in ten
seconds, and where Tari's privacy does real work behind that simplicity: the file key can ride to a
Tari address inside a stealth output's encrypted memo, view keys show arrivals without opening
anything, payments are credited only after the chain confirms them, and every exit is notarized in our
own SealLog template on the Ootle [brief]. The rivals are a CLI toolkit, a sell-a-secret template,
claimable stealth links, a public message board and a game [brief].

## Operating Context

- A phone first (390 and 360 wide), then a desktop (1440); headless Chromium on ultron is the test
  browser, real devices are the owner's [brief].
- The judge path: `/judges`, a short script with what each step should show; a QR code next to the
  link on desktop carries the link to the second device [brief].
- Testnet only (Esmeralda); tTARI is worth nothing; Ootle mainnet is due on the date in `/config`.
- The forum post, the film and the share links are how most people first meet the product [inferred
  from 01-contest-strategy §6].

## Capabilities and Constraints

Functionality stays; only the surface changes [brief]:

- Drop a file or text and get a link; rules: once (default), a secret word, a few opens, a time,
  kept in a locker; delete now.
- Send to a Tari address (key in a stealth payment's encrypted memo); a dead drop ("get a file from
  someone"); an inbox found by scanning the chain in the browser; a view key that sees arrivals and
  opens nothing; packs of more room paid in tTARI, with a demo pay; `/verify` of SealLog proofs; abuse
  reports; judge passes.
- Rules that bind every change: English only; no third-party code, requests, fonts, CDN or analytics;
  no npm, pip or new packages; Python standard library for builds; CSP, Trusted Types and SRI as
  today; every privacy sentence comes from the claim registry (`research/11-brand.md` §8 and its
  additions in `research/14-ghost-design.md`); every number in copy is a `{variable}` filled from
  `/api/v1/config` (`tools/check-copy.py`); test ids change only together with their tests [brief].
- The name is decided at the end of Phase 6A and the owner can override it with one word, so the
  public name lives in one brand constant, the logo files and the repository name [brief].

## Brand Commitments

- **The figure is a little ghost** that sits in the middle of the drop zone and acts out the rule:
  finger on its lips for "once", hands over its eyes for a secret word, an hourglass for "a few
  times", an envelope and a Tari coin for a send, an open bag for a dead drop, a dashed outline
  waving bye when the secret is gone [brief, chosen over a bubble, a burning note and a safe in
  `research/14-ghost-design.md` §2].
- **The proposed name is "bye"** [inferred: three finalists with evidence; the owner may override].
- **Google, not Yahoo**: one thing to do on the home page; everything else one deliberate tap away
  [brief].
- **Words an eight-year-old reads in one breath** on the home, the product and "how it works"
  (Flesch-Kincaid grade 4 or lower); grown-up precision lives on "how it was made" (grade 8 or lower)
  [brief].
- **Tari stays visible in the first ten seconds**, in a child's words, with "Tari™" marked on its
  first prominent mention per page [brief].
- **Precision over poetry** in any sentence about what we see, store, delete or prove [brief, from
  `research/11-brand.md` §7].

## Evidence on Hand

- The live deployment: <https://srv2052606.hstgr.cloud> (release 6fa84fd), `/api/v1/config`,
  `/status.json`, `/evidence.json` (our own test transactions).
- Test suites: server 203 tests, site 28, UI 220 flows, app 9 steps, E2E 25 scenarios against
  production [brief].
- The SealLog component on the Ootle (address in `/config`); the public repository with its threat
  model and review records.
- Absent, and never to be invented: user counts, testimonials, press, audits by third parties.

## Product Principles

1. **One thing to do.** The first screen asks for a secret and nothing else; the right default means
   no decision before the link exists.
2. **Pictures for people, text for machines.** Explanations are scenes in motion with one short
   caption; the long text lives on one page for grown-ups.
3. **Say exactly what we do, and what we don't.** Every privacy claim carries its condition and a way
   to check it.
4. **Delete before adding.** A page, option or sentence that repeats another goes; a choice that the
   default already makes right for nine people in ten becomes the default.
5. **Nothing from anyone else.** No third-party code, font, tracker or request, ever.

## Accessibility & Inclusion

WCAG 2.2 AA: every control named, keyboard-only use works (including drop, paste and type-to-start),
`prefers-reduced-motion` turns every animation into a cut that still tells the story, no horizontal
scroll at 360 px, contrast AA in both themes [brief].
