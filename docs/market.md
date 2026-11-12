<!-- SPDX-License-Identifier: MIT -->
# The market: shops anyone can browse

`/market` lists what public shops sell: a shopper searches across every public shop, opens one, and buys, without a
link from the seller. A shop is in the market only if its owner makes it **Public**; Private stays the default and is
never listed. Behind `features.market` (it needs `features.shop` and `features.pay_to_open`).

The rule the market keeps, as the shop does ([shop.md](shop.md)): **our server never stores both halves of a file's
key, and a shop's key stays after the `#` of its link.** A pay link's key is HKDF(`sA` ‖ `sB`); our server holds `sB`
and releases it per claim after payment. `sA` reaches a buyer only from the seller: in the shop's link, or, for a
shopper who found the shop in the market, from the seller's drive, sealed so that only that shopper can open it. Since
the drive answers anyone who asks, our server could ask too ("Threat-model delta" below).

## What changes in Public

Before this, a public shop handed its key to our server, which served it to every visitor so anyone could buy, and
our server could then open what the shop listed (shop.md said so). Public no longer works that way:

| | Private (default) | Public (in the market) |
|---|---|---|
| Who sees the shop's page | whoever has its whole link | anyone, search engines included |
| Listed in `/market` | no | yes |
| What the page shows | name, bio, and per listing its title, line, file or folder, size, price | the same |
| The shop key | after the `#` of its link, and wrapped in the owner's drive | the same: **never on our server** |
| Buying with the shop's whole link | at once, as before | at once, as before |
| Buying from the market or the bare address | | **Ask for it**, then pay (below) |
| Going back to Private | | drops it from the market; no new key needed, since ours never had it |

## Ask, then pay

A shopper without the shop's key can't build the pay link alone, and our server can't give it to them without
holding both halves. So the shopper asks the seller's drive for its half, and pays only once it has arrived:

1. **Ask.** The shopper's browser draws a 32-byte secret for this ask. From it come a fresh Ootle key pair
   (`deriveOotleKeys(secret, "ask")`), the ask's id and a token (HKDF). It sends the listing, the two public keys and
   the token's hash, with a proof of work (`POST /market/asks`). The browser keeps the secret; the page also shows a
   link with it after the `#` (`/shop/<name>#8<secret>`), to come back from another device.
2. **The seller's drive answers.** Whenever the owner's drive is open, it fetches the asks waiting for its listings
   (`GET /me/market/asks`), opens each listing's `sA` with the shop key, and seals it to the shopper's keys with the
   address wrap the app already uses for Send by Tari (`sealToKeys`, kind 3: both of the shopper's keys are needed to
   open it), bound to the ask and the listing (`PUT /me/market/asks/{id}`). It takes no click: listing in a public
   shop is the decision to sell to anyone. Our server stores the 125-byte answer, which it can't open.
3. **Pay.** The shopper's page opens the answer, checks it is for this ask and this listing, and goes to the pay link
   (`/p/<id>#5<sA>`): the claim, the payment and the open are exactly a pay link's. With `features.away_release` the
   file opens as soon as the payment checks out, whether or not the seller is online.

Nobody pays before the seller's half has arrived, so a seller who never comes back costs a shopper nothing but the
wait. The page says the seller's drive answers when it is open, and the shop's own link opens at once.

Limits: an ask waits up to 7 days; an answered one is deleted 7 days after its answer; 200 waiting asks a listing;
30 asks an hour per network, each with a proof of work. A listing that ends (its pay link stopped, taken off the
shop, the shop private or off) ends its asks, and the shopper is told.

## The directory

`GET /market?q=&kind=&cursor=`: listings of public shops that sell now, newest first, 24 a page. Each has the title,
the line, file or folder, the size and the price, and the shop's name and address. `q` matches words in titles, lines
and shop names (plain text, ASCII case folded); `kind` is `file` or `folder`. Public, rate-limited per network,
cached for a minute. Nothing in it is new to the public: it is what the shops' own pages already show.

The page `/market` (the app's `market.html`) lists the same, with a search box and a filter, and each listing's Get
it. It is indexable, as public shops' pages are, and in the sitemap.

## Threat-model delta

- **Both halves stay apart, at rest and in transit.** Our server holds `sB`, a public shop's words, `link_ct` sealed with
  a key it never has, and asks' answers sealed to shoppers' keys it never has. What it stores opens no listed file, and
  neither does a copy of our database on its own. This replaces the old public mode, in which our server held the shop
  key and could open what a public shop listed from its own data at any time.
- **But a market listing's `sA` goes to whoever asks.** That is what lets a stranger buy without the shop's link, and it
  is the same as posting the shop's link in public. So whoever holds `sB` could open a public listing by asking for it,
  as a shopper would, without paying: our server, or someone with a copy of our database or its backups (which keep
  `sB` for `retention.db_backup_days`) while the seller's drive still answers. The seller is told when making the shop
  public ("our server holds the other half, so it could ask too; list only what you'd sell to anyone"). What the
  market keeps from strangers is what a pay link does: without `sB`, `sA` opens nothing, and `sB` comes only after
  payment. A private shop's listings are never asked for.
- **Asks are anonymous to the seller.** The seller's drive can't tell a shopper from our server, or from someone
  running a copy of our database; it answers every ask for a listing in the market, by design.
- **What our server learns from an ask:** which listing was asked about, when, and a pair of public keys made for that
  ask alone; the shopper's address while connected, never written down. Not who the shopper is. A claim that follows
  looks like any other.
- **A public shop's page and the market are public text on our origin,** written by sellers: plain text only,
  escaped where it lands, reportable (Report this shop) and removable (`mutis-admin takedown shop`), as before.
- **Griefing.** Asks cost a proof of work and are capped per network and per listing; answering one costs the
  seller's drive one seal, done in the background. They cost nobody money.

## Not yet

- **Pay, then deliver** (a possible later option, not built): the shopper claims and pays first, and the seller's drive
  seals `sA` only once its own check of the chain shows that claim paid. Our server could then no longer get a public
  listing's `sA` by asking without paying the seller, but a buyer would pay before the half arrives, and wait for the
  seller's drive to open. Ask, then pay keeps the release from needing the seller online and never asks a buyer to pay
  for something that hasn't arrived; a public listing is sold to anyone by definition. Decided 2026-11-09.
- No reviews, ratings or seller profiles beyond the shop's own words.
- No categories or tags: search is by words.
- The market shows listings, not shops; a shop's own page shows the rest.
