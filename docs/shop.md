<!-- SPDX-License-Identifier: MIT -->
# A drive's shop

"Sell files for TARI" as a storefront: a drive can turn on **My shop**, a public page at `/shop/<id>` that lists some of
its pay links with words its owner writes. Buying is the pay link's own page (`/p/<id>`), unchanged. The whole feature
sits behind `features.shop` (off by default; it also needs `features.pay_to_open`), so a deployment that doesn't turn
it on serves none of it: every route answers 503 `feature_disabled` and the app shows no shop.

Routes: [api.md](api.md) ("Shop"). Server: `server/mutis/shop.py`, `server/mutis/handlers/shop.py`, migration
`008_shop.sql`. Browser: `web/app/lib/shop.js`, `web/app/ui/shop-page.js` (the public page, `shop.html`),
`web/app/ui/drive-shop.js` (My shop and the listing dialog).

## How it works

1. **Turn it on.** In the drive, My shop asks for a name and an optional bio. The browser draws a random 32-byte shop
   key and sends it only wrapped under a key from the drive's own key (`key_wrap`, 60 bytes). Our server picks the
   shop's id at random (`codec.new_id`): it is never derived from the drive's id or keys. The shop's link is
   `/shop/<id>#6<shop key>`; the drive rebuilds it on any device that opens it.
2. **List.** From My shop (List something) or a row's menu (List in my shop): a file or folder that already sells, or
   one the owner prices there (its pay link is made as the share dialog makes it, with no name in its preview). The
   owner types the title and one line buyers see; the title field starts empty, so a file's name is never published by
   default. The browser seals the pay link's own key half (`sA`, the part after a `/p/` link's `#`) with the shop key,
   bound to that link's id (`link_ct`). Our server fills in what it already knew of the link: file or folder, its
   padded size, its price.
3. **The page.** Anyone with the shop's link sees its name, its bio and what sells now, each with Buy and open. The
   visitor's browser opens each `link_ct` with the shop key after the page's `#` and links to
   `/p/<share id>#5<sA>`: the pay page, the claim, the payment and the open are exactly those of the pay link.
4. **Control.** Take a listing off; edit its words; turn the shop off (the page answers 404; the pay links keep
   selling). A paused pay link (Stop selling) hides its listing until Sell again; a pay link that ends (stopped,
   deleted, the Trash, its file leaving, a takedown) deletes its listing at once (`items.end_share`). Earnings are
   unchanged: a sale through a shop is a sale of its pay link.

Limits: 50 listings a shop; a name of 60 characters, a bio of 280 in up to 4 lines, a title of 80 and a line of 140;
plain text only (no control characters, no bidirectional overrides or marks; shown as text, never markup or a link). Writes:
30 shop changes a day and 120 listing writes an hour per drive. The public read: 120 a minute per network,
`Cache-Control: public, max-age=60`.

## What is public, what stays private

| Public, to anyone with the shop's link | Kept from the public | Never on our server |
|---|---|---|
| The shop's name and bio, as its owner wrote them | Which drive the shop belongs to, its addresses | The shop key |
| For each listing: the title and line its owner wrote, file or folder, its padded size, its price | File and folder names (unless the pay link's own preview shows one, see below), what is inside | Any `sA` in the clear |
| Each listing's pay link id, so the pay page (`/p/<id>`) answers as it does for anyone with that link | Who looked at the shop, who bought | File keys, names, contents |

Our server stores the shop's name, bio and `key_wrap`, and for each listing its title, line, kind, padded size, price,
`link_ct` and the pay link's id. It logs none of them (route names and status codes only, as everywhere). `/fine-print`
lists both tables.

**A pay link's preview.** When a pay link was made with "Show the name before they pay", its encrypted preview names the
file, and anyone who holds `sA` can read it. A listing hands `sA` to everyone with the shop's link, so the listing dialog
says so before it lists such a link ("Its pay page shows its name, …"), and its button reads List it with its name. Pay
links made from the shop dialog carry no name.

## Threat-model delta

What changes against [threat-model.md](threat-model.md):

- **The split key, for listed links (the design choice).** A pay link's secret is HKDF(`sA` ‖ `sB`); `sB` is ours,
  `sA` rides in the link. Publishing a listing's `/p/` link in full on a page we serve would put both halves on our
  server, and "if the link leaks, our server could open it" would become "our server can open everything listed". We
  don't: `sA` is stored and served only as `link_ct`, sealed with the shop key, which lives after the shop link's `#`
  and in the owner's drive (wrapped). A copy of our database, or our server on its own, holds `sB` and `link_ct` but
  can't open `link_ct`, so it opens no listed item. This still sells to strangers: anyone with the shop's whole link
  opens every `link_ct` in the browser and buys through the pay page.
- **What remains.** A shop is meant to be shared, and its link is a key: whoever holds it holds every listed link's
  `sA`. Someone who obtains a shop's link (it was posted in public, or a chat app previewed it) and also holds `sB` (us,
  or a copy of our database) can open what is listed without paying. That is the existing boundary of a leaked pay
  link, widened to every listed link at once. The owner sees it when listing ("Post that link in public and our server
  could read it there and open what you list, so list only what you would sell to anyone"). Strangers with the shop's
  link alone still open nothing: `sB` is released per claim, after payment, as before.
- **Owner text on our origin.** The shop's name, bio, titles and lines are a stranger's words on a page we serve. They
  are plain text (no markup, no links, no bidirectional overrides), rendered as text nodes under the same content
  security policy; the page says its owner wrote it and that the server doesn't check it, and it is `noindex` and
  disallowed in `robots.txt` like a pay page. Phishing in words remains possible; **Report this shop** goes to the
  same report form and queue as a link (`POST /abuse` takes `/shop/<id>`, `shop_id` in `abuse_reports`), and
  `mutis-admin takedown shop -- <id>` removes the page (410, listings deleted, the drive can't open another until an
  operator clears the row). Its pay links are their own and are taken down as links. A reporter who ticks "Include the
  key" sends the shop's key with the report, as for a link: with it, and the `sB` we hold, the operator can open what
  the shop lists to check it. That is the reporter's choice, and the report says it was made.
- **Linking.** The public now learns that the listed pay links belong to one seller; our server already knew which
  drive owns which link. The shop's id is random and unrelated to the drive.
- **Swapping.** A listing's `link_ct` is bound to its pay link's id, so a server that moves a `link_ct` to another
  listing makes it fail to open in the visitor's browser (shown without Buy and open), instead of sending the buyer to
  another link. A server can still drop, hide or reorder listings, or serve an old page for up to a minute (the cache).
- **Griefing.** Shops cost a drive (whose creation is already braked) and at most 50 rows; their writes and the public
  read are rate-limited per drive and per network.

Tests: `server/tests/test_shop.py` (the flag, the routes, the limits, the lifecycle, a report and takedown, a buy
through a listing on the fake chain), `web/app/tests/shop.test.js` (the keys, the seals and that no secret leaves the
browser), `web/app/ui/tests/flows_shop.py` (the owner turns the shop on and lists, a visitor sees it and buys through
`/p/`, the owner takes it off and turns the shop off; phone and desktop).

## Not yet

- The shop's own card is the same for every shop (`og-shop.png`), like every link card: no shop's name in a preview.
- Search engines don't index shops (`noindex`, `robots.txt`); a shop is found through its link.
- No ordering by the owner (newest first), no categories, no per-shop analytics.
- A folder's size on the shop is the one it had when listed (Edit refreshes it); its pay page sums it live.
- A pay link made in the listing dialog is stopped again at once if the listing step then fails (nobody has its link
  yet), so nothing sells unlisted; if stopping fails too, the dialog says so and offers Stop selling.
