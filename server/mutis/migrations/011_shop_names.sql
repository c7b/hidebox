-- SPDX-License-Identifier: MIT
-- Schema 10 → 11: a shop's address (docs/shop.md "The address"), behind features.shop. Additive only.
-- shops.username: the readable name in /shop/<username>, ASCII a-z, 0-9 and single hyphens, 3 to 30 characters, stored
-- case-folded; skeleton: the same name with look-alike characters merged (0/o, 1/l/i, rn/m, …) and hyphens dropped,
-- unique too, so no shop can take a name that reads as another's. NULL for a shop made before names (its id still
-- opens it). mode: 'private' (the default: the shop key stays after the link's #, reading it takes token_hash's token)
-- or 'public' (anyone, and search engines, can read the page; published_key is then the shop key itself, which our
-- server serves to every visitor so they can buy, and with which it could open what the shop lists).
-- token_hash: SHA-256 of the read token, HKDF(shop key, "mutis/v2", "shop-read"), which only a holder of the key makes.
-- shop_name_holds: a name a shop gave up (renamed, turned off) stays its drive's for a while, so nobody else can
-- answer at an address its old visitors and search engines still know.

ALTER TABLE shops ADD COLUMN username TEXT;
ALTER TABLE shops ADD COLUMN skeleton TEXT;
ALTER TABLE shops ADD COLUMN mode TEXT NOT NULL DEFAULT 'private' CHECK (mode IN ('private','public'));
ALTER TABLE shops ADD COLUMN token_hash BLOB;
ALTER TABLE shops ADD COLUMN published_key BLOB;
CREATE UNIQUE INDEX shops_username ON shops(username) WHERE username IS NOT NULL;
CREATE UNIQUE INDEX shops_skeleton ON shops(skeleton) WHERE skeleton IS NOT NULL;

CREATE TABLE shop_name_holds (
  skeleton    TEXT PRIMARY KEY,
  identity_id TEXT NOT NULL,
  until       INTEGER NOT NULL
) STRICT;
