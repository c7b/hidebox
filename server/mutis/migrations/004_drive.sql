-- SPDX-License-Identifier: MIT
-- Schema 3 → 4: the drive (research 16-drive-design §15 step 1, annex 16-drive-architecture §1.4, §2.1, §3.2).
-- Additive only: every existing row keeps working, and new behaviour stays behind features.folders and
-- features.pay_to_open. Folders are items without ciphertext; a child carries its parent and its file key
-- wrapped under the folder's key. A ticket can serve one item or a folder's tree. Opens are counted per
-- link per hour, never per person. Pay to open adds a seller's sales address and sealed view key, paid
-- links, buyer claims (never an identity or an IP) and the payments found for them.

ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT 'file' CHECK (kind IN ('file','folder'));
ALTER TABLE items ADD COLUMN parent_id TEXT REFERENCES items(id) ON DELETE SET NULL;
ALTER TABLE items ADD COLUMN parent_wrap BLOB;
ALTER TABLE items ADD COLUMN trashed_at INTEGER;
CREATE INDEX items_parent ON items(owner_id, parent_id, state);
CREATE INDEX items_child ON items(parent_id) WHERE parent_id IS NOT NULL;

ALTER TABLE tickets ADD COLUMN scope TEXT NOT NULL DEFAULT 'item' CHECK (scope IN ('item','tree'));

CREATE TABLE share_opens (
  share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  hour     INTEGER NOT NULL,
  n        INTEGER NOT NULL,
  PRIMARY KEY (share_id, hour)
) STRICT, WITHOUT ROWID;

CREATE TABLE sellers (
  identity_id  TEXT PRIMARY KEY REFERENCES identities(id) ON DELETE CASCADE,
  address      TEXT NOT NULL,
  view_sealed  BLOB NOT NULL,
  state        TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','ok','bad_key')),
  scan_seq     INTEGER NOT NULL DEFAULT 0,
  scanned_at   INTEGER,
  created_at   INTEGER NOT NULL
) STRICT;

CREATE TABLE paid_shares (
  share_id       TEXT PRIMARY KEY REFERENCES shares(id) ON DELETE CASCADE,
  price_ut       INTEGER NOT NULL,
  server_half    BLOB,
  teaser_ct      BLOB,
  buyer_views    INTEGER NOT NULL,
  buyer_window_s INTEGER NOT NULL,
  paused         INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE claims (
  id           TEXT PRIMARY KEY,
  share_id     TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  token_hash   BLOB NOT NULL UNIQUE,
  address      TEXT NOT NULL,
  price_ut     INTEGER NOT NULL,
  received_ut  INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL CHECK (status IN ('pending','seen','underpaid','paid','released','expired','void')),
  owner_check  TEXT NOT NULL DEFAULT 'none' CHECK (owner_check IN ('none','pending','ok','bad')),
  created_at   INTEGER NOT NULL,
  created_seq  INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  paid_at      INTEGER,
  released_at  INTEGER,
  views_left   INTEGER,
  open_until   INTEGER,
  demo         INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX claims_open ON claims(status, expires_at);
CREATE INDEX claims_share ON claims(share_id, status);

CREATE TABLE sale_payments (
  utxo_id    TEXT PRIMARY KEY,
  claim_id   TEXT REFERENCES claims(id) ON DELETE SET NULL,
  value_ut   INTEGER NOT NULL,
  seen_at    INTEGER NOT NULL,
  epoch      INTEGER,
  committed  INTEGER NOT NULL DEFAULT 0,
  status     TEXT NOT NULL CHECK (status IN ('pending_check','counted','extra'))
) STRICT;
