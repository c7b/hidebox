-- SPDX-License-Identifier: MIT
-- Schema 7 → 8: a drive's shop (server/mutis/shop.py, docs/shop.md), behind features.shop. Additive only.
-- shops: one per drive that turns it on. Its public id is random (never from the drive's id or keys), its title and
-- bio are what the owner chose to publish, and key_wrap is the shop's own key wrapped under the drive's key, which
-- only the owner's browser opens; the shop's key rides after the # of the shop's link and never reaches us.
-- shop_listings: one per listed pay link: the public title and line the owner typed, what our server already knew of
-- the link (kind, padded size, price), and link_ct, the pay link's own half of its key sealed with the shop's key.
-- A listing goes with its pay link (items.end_share) and with its shop. abuse_reports.shop_id: a report of a shop.

CREATE TABLE shops (
  id          TEXT PRIMARY KEY,
  identity_id TEXT NOT NULL UNIQUE REFERENCES identities(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  bio         TEXT NOT NULL DEFAULT '',
  key_wrap    BLOB NOT NULL,
  state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','removed')),
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
) STRICT;

CREATE TABLE shop_listings (
  share_id    TEXT PRIMARY KEY REFERENCES shares(id) ON DELETE CASCADE,
  shop_id     TEXT NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  kind        TEXT NOT NULL CHECK (kind IN ('file','folder')),
  size_stored INTEGER NOT NULL,
  price_ut    INTEGER NOT NULL,
  link_ct     BLOB NOT NULL,
  created_at  INTEGER NOT NULL
) STRICT;
CREATE INDEX shop_listings_shop ON shop_listings(shop_id, created_at);

ALTER TABLE abuse_reports ADD COLUMN shop_id TEXT;
