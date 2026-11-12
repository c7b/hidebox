-- SPDX-License-Identifier: MIT
-- Schema 12 → 13: the market (docs/market.md), behind features.market. Additive only.
-- A public shop no longer hands its key to our server: shops.published_key stays NULL from here on (it was the shop
-- key itself, which let our server open what a public shop listed). A shopper who found a listing in the market asks
-- the seller's drive for the listing's half of its pay link's key instead.
-- market_asks: one per ask. id and token_hash come from a secret only the shopper's browser holds; owner_pk and view_pk
-- are a key pair made for this ask alone; answer is the listing's half of the key (sA) sealed to those keys by the
-- seller's drive (125 bytes), which our server can't open. An ask goes with its listing, its shop, or its time.

UPDATE shops SET published_key = NULL;

CREATE TABLE market_asks (
  id          TEXT PRIMARY KEY,
  share_id    TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  shop_id     TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
  owner_pk    BLOB NOT NULL,
  view_pk     BLOB NOT NULL,
  token_hash  BLOB NOT NULL,
  answer      BLOB,
  created_at  INTEGER NOT NULL,
  answered_at INTEGER,
  expires_at  INTEGER NOT NULL
) STRICT;
CREATE INDEX market_asks_shop ON market_asks(shop_id, answered_at, created_at);
CREATE INDEX market_asks_share ON market_asks(share_id);
