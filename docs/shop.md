<!-- SPDX-License-Identifier: MIT -->
# A drive's shop

"Sell files for TARI" as a storefront: a drive can turn on **My shop**, a page at `/shop/<username>` that lists some of
its pay links with words its owner writes ("The address" below). Buying is the pay link's own page (`/p/<id>`), unchanged. The whole feature
sits behind `features.shop` (off by default; it also needs `features.pay_to_open`), so a deployment that doesn't turn
it on serves none of it: every route answers 503 `feature_disabled` and the app shows no shop.

Routes: [api.md](api.md) ("Shop"). Server: `server/mutis/shop.py`, `server/mutis/handlers/shop.py`,
`server/mutis/shop_page.py` (a public shop's page and the sitemap), migrations `008_shop.sql` and `011_shop_names.sql`. Browser: `web/app/lib/shop.js`, `web/app/ui/shop-page.js` (the public page, `shop.html`),
`web/app/ui/drive-shop.js` (My shop and the listing dialog).

## How it works

1. **Turn it on.** In the drive, My shop asks for a name, an address (the username), an optional bio, and Private or
   Public. The browser draws a random 32-byte shop key and sends it only wrapped under a key from the drive's own key
   (`key_wrap`, 60 bytes), with the SHA-256 of its read token. Our server picks the shop's internal id at random
   (`codec.new_id`): it is never derived from the drive's id or keys. A private shop's link is
   `/shop/<username>#6<shop key>`, a public one's `/shop/<username>`; the drive rebuilds it on any device that opens it.
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

## The address

`https://mainnet.hidebox.app/shop/<username>` on the mainnet lane (the same path anywhere the shop feature runs). The
username is the owner's pick, checked by our server (`shop.username()`), never by the browser alone:

| Rule | Why |
|---|---|
| ASCII `a`–`z`, `0`–`9` and `-` only, 3 to 30 characters, no hyphen at either end and never two together | One readable spelling per name, safe in a URL path, an HTML attribute, a meta tag and JSON-LD without any change |
| The length is checked before anything else; anything not ASCII is refused, never normalized | No Unicode tricks reach the database: accents, Cyrillic or Greek look-alikes (`аlice` with a Cyrillic а), full-width letters (NFKC would fold `ａlice` to `alice`; we refuse it instead), bidirectional overrides, zero-width joiners, control characters, NUL, emoji |
| Capitals fold to lower case; the folded name is unique | `Mila` and `mila` are one shop; `/shop/Mila` answers 301 to `/shop/mila` for a public shop |
| Unique by look-alike too (`skeleton`: first `0`→`o`, `1`/`i`→`l`, `3`→`e`, `4`→`a`, `5`→`s`, `7`→`t`, `8`→`b`, hyphens dropped; then `rn`→`m`, `vv`→`w`, `cl`→`d` until nothing changes) | `mila` blocks `m1la`, `mi-la` and `rnila`, `clara` blocks `c1ara`: nobody can open a shop that reads as someone else's |
| Reserved words refused as a whole name (`admin`, `api`, `shop`, `static`, `www`, `hidebox`, `verify`, `fine-print`, …), and the brand (`hidebox`, `mutis`) anywhere in it; impersonation words (`official`, `support`, `staff`, `security`, `tari`, `ootle`, …) refused as any part between hyphens; all after look-alikes merge | Nothing reads as us, as one of our pages, or as staff |
| A name given up (renamed, or the shop turned off) stays its drive's for 30 days (`shop_name_holds`), the 3 it gave up last at most | Old links and search results to those names don't land on someone else's shop the next day, and no drive can park names; an older one is free again at once |
| Not equal to another shop's id | A shop made before names keeps its `/shop/<id>` link |

Two modes, the owner's choice (Private is the default):

- **Private.** `/shop/<username>#6<shop key>`. The key stays after the `#`, so neither our server nor anyone at hidebox
  can open what is listed. Reading the shop takes its read token, HKDF-SHA256(shop key, `"mutis/v2"`, `"shop-read"`),
  sent as `X-Mutis-Shop`; our server keeps its SHA-256. Without it a private shop answers exactly like a name nobody
  has (404 to the API, the plain page to a browser), removed or not, so the name alone shows nothing of the shop; that the name is taken
  is all anyone can learn, by trying to take it for a shop of their own. `noindex`, and not in the sitemap.
- **Public.** `/shop/<username>` is a page anyone can read, search engines included: the name, bio, titles, lines,
  file or folder and prices. Our server fills them into the page (`shop_page.py`): the title, the description, a
  canonical address, OpenGraph and Twitter card text, structured data that says only what is true (a `CollectionPage`
  whose `ItemList` names the listings, no prices or offers claimed in a currency code we can't vouch for), the listings
  inside `<main>` for readers without JavaScript, and an entry in `/sitemap-shops.xml` (public shops with something for
  sale). Its listings are also in the market (`/market`, [market.md](market.md)). **The shop key still never reaches
  us**: a visitor with the shop's whole link buys at once, as from a private shop; a visitor at the bare address, or
  from the market, asks the seller's drive for a listing's key half, which the drive seals to that visitor alone.
  The listings in `<main>` are the app's own markup in the app's own words (the release's copy deck and icons), and
  `shop.html` starts in the drive's look. So the page's first frame has the layout of its last one: nothing moves
  when the app draws. The market's page works the same way.

Until the market (2026-11-09), a public shop handed its key to our server, which served it to every visitor and so
could open what the shop listed. The market replaced that: whatever a visitor can fetch from us to buy, our server can
fetch too, so the half a buyer needs comes from the seller's drive instead, sealed, and the shopper pays only once it
has arrived ([market.md](market.md) "Ask, then pay"). The release still doesn't wait for the seller.

**Going private again** keeps the key, which was never ours: the shop leaves the market and search engines, and its
open asks end. A seller who posted the whole link too widely can still give the shop a new key (`lib/shop.js`
`newKey`): every listing's `sA` is opened with the old key and sealed with the new one, in one request (`relisted`; 409
`relist_needed` if a listing changed meanwhile), and the old link stops working. Every listing write names the key it
was sealed under (`key_wrap`, 409 `key_changed` otherwise), so a tab that still holds the old key can't list anything
under it.

Escaping: every piece of the owner's text is escaped where it lands: HTML text and attribute values (`&`, `<`, `>`,
`"` and `'`), one line in meta tags, JSON-LD with `<`, `>` and `&` as `\u` escapes and nothing outside ASCII. The
address is built from the stored username, ASCII by construction. If the release's `shop.html` lacks exactly the
anchors this fills, or its copy deck lacks a word the page needs, the page goes out unfilled and `noindex`. The content security policy is the app's, unchanged; the
one inline block is JSON-LD, which no browser runs. On a staging rehearsal every shop page stays `noindex` and the
sitemap is empty.

## What is public, what stays private

| Public, to anyone with the shop's link (a public shop: to anyone) | Kept from the public | Never on our server |
|---|---|---|
| The shop's name, address and bio, as its owner wrote them | Which drive the shop belongs to, its addresses | The shop key, private or public |
| For each listing: the title and line its owner wrote, file or folder, its padded size, its price | File and folder names (unless the pay link's own preview shows one, see below), what is inside | Any `sA` in the clear |
| Each listing's pay link id, so the pay page (`/p/<id>`) answers as it does for anyone with that link | Who looked at the shop, who bought | File keys, names, contents |

Our server stores the shop's name, address (and its look-alike skeleton), mode, bio, `key_wrap` and the hash of its read
token, and for each listing its title, line, kind, padded size, price, `link_ct` and the pay
link's id. It logs none of them (route names and status codes only, as everywhere). `/fine-print`
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
- A private shop is found only through its link; a public one through search engines too.
- No ordering by the owner (newest first), no categories, no per-shop analytics.
- A folder's size on the shop is the one it had when listed (Edit refreshes it); its pay page sums it live.
- A pay link made in the listing dialog is stopped again at once if the listing step then fails (nobody has its link
  yet), so nothing sells unlisted; if stopping fails too, the dialog says so and offers Stop selling.
