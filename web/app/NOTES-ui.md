<!-- SPDX-License-Identifier: MIT -->
# NOTES from the app-ui builder

What I need from other directories, and every decision I made where the documents disagreed or were
silent. Evidence for each acceptance id is in `ACCEPTANCE.md`.

## 1. Requests

**Deploy builder (`tests/e2e/`).** The E2E flows were written before the UI existed; four places need
the UI as built (all inside the §3.4.9 contract):

1. `flows.set_rules`: a change of count or expiry keeps **the same link** (`PATCH /s/{id}`, spec §5.4:
   tightening is always allowed, loosening only before the first open), so `wait_link(page, before)`
   never returns for E-02 and E-05. Wait instead for the card's `data-rule` counter to change
   (`.md-card[data-rule]` increments on every applied rule; `data-max-views` and `data-expires-at`
   carry the result). A password, password-only or "Until I delete it" does make a new link.
2. E-08 (brand P-15, accepted in 12-integration §2): "Protect the file with a passphrase" is **on by
   default**, so `key-save-file` with an empty passphrase only asks for one. Fill `key-passphrase`
   first (or untick `key-protect`); the restore then needs `restore-passphrase` (it appears when the
   pasted text is a locked key, after a first `restore-submit`). P-15 also removes the copy button,
   so `key-copy` doesn't exist; the key can still be shown and selected ("Show the key to write it
   down").
3. E-11: the view-key form on `/t#4…` is shown directly (`t-viewkey`, `t-viewkey-submit`), as the
   E2E expected.
4. Rate limits: every actor in `ui/tests/run.py` sends its own `X-Real-IP` (the dev server trusts it
   from loopback, as Caddy does), so a run that makes a dozen lockers isn't throttled by `POST
   /drops` and `/auth/register` (5 an hour per address). E-J on staging makes its lockers from two
   real devices, so it doesn't need this.
5. E-05 (`scenarios.py`): choose `expiry-preset` `60` and leave the count alone (or `when=once`), not
   `when=expires`. In this UI `when=expires` is "No limit" on opens, which only a locker past its
   first day may choose, so an anonymous E-05 can never pick it. The `60` preset is offered when
   `/config` carries `e2e_expiry_s` (server request below); the UI flow `states` drives exactly this
   path against the real dev server and gets `expired` after 65 s.
6. "Send it to a Tari address instead" (P-6, judge step B3) now ends the card's link once the file is
   sent, and only then drops it from the card (`data-testid="card-sent"` replaces `sealed-link` and
   `copy-link`). If our server doesn't confirm the revoke, the card keeps the link and offers
   `card-close-link`.

**Deploy builder (`tools/build.py`).** Please skip `web/app/shots` (and `web/site/shots`) when copying
into `dist/`: `SERVED_EXT` includes `.webp`, so today the 47 evidence screenshots are published at
`/app/shots/*.webp` and listed in the hash manifest. They are test evidence, not part of the product
(they also show dev-server links with their keys after `#`). For example
`copy_tree(web / "app", dist / "app", skip=("sidecar", "shots") if with_tests else ("sidecar", "tests", "shots"))`.
`web/app/ui/tests/` holds only Python, which the build doesn't serve.

**Server builder.** Spec §17.1 says "the E2E config allows a 60 s expiry option". Please add it as
`/config` → `"e2e_expiry_s": 60`, sent only when the deployment's config turns it on (staging), absent
in production. `ui/rules.js` adds that preset to "Gone after" when the field is there; the server
already accepts a 60-second link (`link_rules` needs only `expires_at > now`).

**Site builder.**
1. Please add `<link rel="stylesheet" href="/app/css/widget.css" integrity="{{SRI}}">` to the head of
   `pages/index.html` and `pages/es/index.html` (after `home.css`). `drop-widget.js` adds it itself when
   it's missing, but a static link lets the browser fetch it with the page and gets SRI.
2. `mutis:state` with `state: 'sealed'` carries `detail.preview = {name, size, sizeStored, noise}` as you
   asked (`noise` = the first 9,216 bytes of the real chunk-0 ciphertext). `name` is `''` for a text.
3. The widget renders no heading in `data-variant="hero"`; your H1 and line 2 stay the hero. Once the
   card shows, "Drop a file." / "Choose a file." sits above "Locked." (`shots/home-390-sealed.webp`).
   Please hide line 2 on `mutis:state` `sealed` and show it again on `idle`, so the hero reads as the
   page's title and the card as the result.
4. **`/judges` B6 in wallet mode (blocking for the Council guide).** Production runs
   `amount_proof = "wallet"` (server default, `deploy/config/mutis.toml.example`). In that mode the app
   shows **Waiting → Seen by our wallet → Exists on chain → Added** (spec §12.3.3 fallback labels,
   brand §10.5), but B6 reads "Waiting → Seen on chain → Added". The UI flow `upgrade-wallet` runs the
   dev server in wallet mode and asserts the app's four labels. Suggested B6 markup:
   `<strong>Waiting → <span data-when="proof=proven" hidden>Seen on chain → Amount proven → </span><span data-when="proof=wallet">Seen by our wallet → Exists on chain → </span>Added</strong>`
   (the same in `es/judges.html` with `upgrade.step.*` from `es.json`). Please also make the check
   "/judges quotes the app's words" resolve the page per mode and compare the arrow sequence with
   `upgrade.step.{waiting,seen,proven,added}` (proven) or `upgrade.step.{waiting,seen_wallet,exists,added}`
   (wallet), so a phrase that exists somewhere in the app but not in that mode fails.
5. **`/abuse` prefill.** The viewer's "Report this link" and the drop page's "Report this drop" now
   link to `/abuse#link=<the link without its key, URL-encoded>`. Please fill `form.elements.link` from
   that fragment (through your `cleanLink`, so only `/s/` and `/d/` links of our origins are taken)
   and clear the fragment with `history.replaceState`. Until then the fragment is ignored and the form
   works as before.

**App-core builder.**
1. The noise strip needs the first stored chunk's ciphertext. `sealItem()` doesn't return it, so
   `ui/sealing.js` chooses the file key and salt itself and hands them to `sealItem()` through
   `resume` (which, without an `upload` in it, starts a new upload with them), then encrypts chunk 0 a
   second time with the same key and salt. Please add an explicit `{fk, salt}` option or return the
   first `NOISE_BYTES` of chunk 0, and I'll switch to it.
2. `i18n.useStrings()` is documented as "for tests"; the home widget uses it to install its first,
   smaller dictionary (`i18n/widget-<lang>.json`). Please keep it exported.
3. `api.js` has no wrapper for `GET /s/{id}/stored` (the P1 "Download the stored bytes"); `ui/known.js`
   calls `request()` directly.
4. `filetype.checkRisky(name, head)` checks the name as given, while `download.saveFile` saves
   `sanitizeFileName(name)`, which drops control and format characters and `\/:*?"<>|`. A name like
   `invoice.b\u200Bat` or `run.p|s1` passes the check and is saved as `invoice.bat` / `run.ps1`. The UI
   now checks the sanitized name everywhere (the stored name is sanitized in `sealing.fileSource`,
   and the viewer sanitizes again before its check). Please sanitize inside `checkRisky` too, so any
   other caller gets the same answer.

**Integrator (copy and claims).**
1. Brand v2 wins on words, so the UI says "Locked." / "a locked file" / "Opening in your browser"
   where spec §12.3 still says "Sealed" / "a sealed file" / "Unlocking" ("unlock" and "sealed file"
   are on brand §7.4's banned list). "Sealed" survives only for the key inside a payment ("memo:
   sealed (n bytes)").
2. View-key copy follows the site's correction of C15 (kind-3 files can't be opened with a view key;
   kind 4 is the labelled exception), and the direct-mode C8 sentence follows the site's §4.2 wording.
   The send result shows the sentence for the mode that send actually used (`wallet.deliver()`).
3. "Delivered" and "Sent" are written without a period because `/judges` quotes them as whole strings.

## 2. Decisions

| Topic | Decision | Why |
|---|---|---|
| Count and expiry changes | `PATCH` the same link; a new link only for passwords and kept files | spec §5.4; a link already shared keeps working under the stricter rule |
| A link's expiry | never later than its file's: "24 hours" chosen an hour after locking means 23 | the server refuses a link that outlives its item |
| Locker on visit | `/inbox`, `/watch` and `/upgrade` never create a locker by being opened; `/inbox` offers "Open my locker", `/upgrade` opens one at Buy, `/send` at the first lock | conservative: no server record and no PoW for a page view (spec §4.8.6 lists the page opens; the actions are what need one) |
| Key saving | one modal holds the save options (the locker page's "Save my key" opens the same modal), so each control exists once per page | duplicate test ids and duplicate focus targets otherwise |
| Key file | locked with a passphrase by default (P-15), plain only if the box is unticked; no copy button | 12-integration §2 accepts P-15 |
| Inbox | scans on open, then every 15 s while the page is visible, and on "Check again" | deliveries arrive by themselves; every browser asks for the same mirror pages |
| What the chain saw (inbox) | built only from the mirror row this browser already has (commitment from the output id, amount hidden, one-time owner, sealed memo); no per-output request | a request for one output would tell our server which outputs this locker can open (spec §1.4 "never sees") |
| `/t` with a locker that can't open it | shows this locker's safety code only | a blob doesn't say which address it was sealed to (app-core note) |
| "Tonight at midnight" | offered Oct 24 to Nov 1 (local) | brand §13.11 |
| "No limit" opens | only for lockers past day one | the server allows unlimited views only for `locker` and `paid` |
| Home payload | the zone and the PoW prefetch at load; sealing code on the first reach for the zone; the card with the first link; the rest (and its strings and `parts.css`) when first shown | A-06 and the site's M-01 page budget |
| Strings | `en.json`/`es.json` are the canonical dictionaries; `widget-<lang>.json` is generated from them by `i18n/subset.py` and checked by the test run | one source of truth; the home page doesn't download the whole app's copy |
| Recipient safety | anonymous senders can't send programs (name or magic bytes): on the home page they're offered a free locker, on a drop page they're refused outright; the viewer's program warning has a two-step save; active documents and archives get a notice | brand P-14; a drop's owner never chose to receive programs |
| File names | a file is stored under the name a browser will save it as (`sanitizeFileName` in `sealing.fileSource`); the viewer sanitizes again and checks, shows, previews and saves only that name | the check must see the extension that lands on disk; a modified client can store any name |
| "Instead" and new links | the old link is ended before the screen says so: a password or kept-file change rolls back (deletes the new link or copy) when the revoke isn't confirmed; after "Send it to a Tari address instead" the card keeps the link, with "Close the link", until it is | a privacy claim about a live link has to be true when it's shown (spec §3.5, no silent catch) |
| Card errors | errors from the card's own actions (Send instead, Change, Delete now) show inside the card | spec §12.3.1: the visitor's link is never lost on a recoverable error |
| `/send` rule | Once by default; a retry with the same choices reuses the same link and sealed key | spec §12.3.3; no orphan link per retry |
| Short addresses | first and last 6 characters counted after the network prefix (`otl_esm_1abcdef…uvwxyz`) | the first 9 characters are the same on every testnet address |
| Viewer error headings | "This link didn't open." / "The file didn't finish opening.", with the error's own sentence and Try again in the banner below | the heading says what happened; the banner says why and what to do (brand §10.8), and keeps `data-code` for support |
| Drop label | quoted, inside `<bdi>`, with "The person who made this link wrote this name. mutis doesn't check it." and a Report this drop link | the label is written by whoever made the link, not by us |
| Card tile | the left tile shows a note's first lines or the file's extension (a raster image as itself); the heading carries the name and size | the name and size were printed twice |
| Testnet line | switches with `/shared/dates.js` `phase()` to the footer's "the Ootle mainnet is live" wording | D13: judging happens after Nov 11 |
| Report link | every viewer state links `/abuse` | brand §10.6 |
| `/verify` (P1 receipts) | built on `lib/seallog.js`; shows "Receipts are off on this deployment" while `features.seallog` is false, as in the dev server and in `deploy/config/mutis.toml.example` | `/judges` step B7 quotes "Verify"; it works once the integrator turns SealLog on |
