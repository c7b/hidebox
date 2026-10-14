-- SPDX-License-Identifier: MIT
-- mutis database, schema version 5 (spec §7, plus brand patches P-8 exit receipts, P-12 judge passes,
-- P-25 first_opened_min, the SealLog tables of spec §11 that P-8 needs, and migrations/002 to 005:
-- the drive's folders, Trash, opens per hour, the pay-to-open tables and the owner's check of sales).
-- Deliberately absent: email, name, IP address, user agent, any login public key, a user's locker address,
-- file or folder name, MIME type, plaintext size, any secret key in clear, any grant or recipient table, the
-- drop an item came from, who opened a link, a buyer's identity. Kept on purpose, opt-in and for sales only:
-- a seller's sales address and its view key sealed to the payment checker (sellers), and per-claim addresses.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
-- keys: schema_version, free_quota_bytes, free_quota_updated_at, uploads_frozen, chain_heartbeat, chain_status (json),
--       mirror_cursors (json, per indexer), receiver_address, receiver_scan_seq, credit_freeze, last_reconcile,
--       reconcile_unknown, canary_item_id, canary_n, canary_delivery_tx, canary_sealed_at, canary_log (json),
--       evidence_pay_day, features (json overrides), alerts (json), budget_overrides (json), last_sealed_at,
--       cleanup_hour, cleanup_day, seal_last_at, force (json: canary/evidence_pay/seal requests from mutis-admin)

CREATE TABLE identities (
  id             TEXT PRIMARY KEY,                -- b64u(HKDF(seed,'identity-id')[0:16])
  auth_verifier  BLOB NOT NULL,                   -- SHA-256(authKey)
  created_day    TEXT NOT NULL,                   -- 'YYYY-MM-DD'
  last_seen_day  TEXT NOT NULL,
  distinct_days  INTEGER NOT NULL DEFAULT 1,      -- incremented when last_seen_day changes
  paid_bytes     INTEGER NOT NULL DEFAULT 0,
  paid_until     INTEGER,
  used_bytes     INTEGER NOT NULL DEFAULT 0,
  reserved_bytes INTEGER NOT NULL DEFAULT 0,
  sends_day      TEXT, sends_today INTEGER NOT NULL DEFAULT 0,
  bundle_ct      BLOB,                            -- only if G2a failed
  state          TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','suspended'))
) STRICT;

CREATE TABLE sessions (
  token_hash  BLOB PRIMARY KEY,
  identity_id TEXT NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
  created_at  INTEGER NOT NULL, expires_at INTEGER NOT NULL, last_used_day TEXT NOT NULL
) STRICT;

CREATE TABLE used_nonces (nonce_hash BLOB PRIMARY KEY, expires_at INTEGER NOT NULL) STRICT;

CREATE TABLE items (
  id           TEXT PRIMARY KEY,
  owner_id     TEXT REFERENCES identities(id) ON DELETE CASCADE,   -- NULL = anonymous
  manage_hash  BLOB NOT NULL,
  retention    TEXT NOT NULL CHECK (retention IN ('ephemeral','kept')),
  lane         TEXT NOT NULL CHECK (lane IN ('small','anon','drop','locker')),
  canary       INTEGER NOT NULL DEFAULT 0,
  state        TEXT NOT NULL CHECK (state IN ('uploading','ready','doomed','deleted','removed')),
  header       BLOB NOT NULL,
  meta_ct      BLOB NOT NULL,
  owner_wrap   BLOB,
  chunk_count  INTEGER NOT NULL,
  size_stored  INTEGER NOT NULL,
  ct_hash      BLOB,
  created_hour INTEGER NOT NULL,
  expires_at   INTEGER,
  doomed_at    INTEGER,
  egress_day   TEXT, egress_bytes INTEGER NOT NULL DEFAULT 0,
  exit_hour    INTEGER,                         -- P-8: hour the blob was unlinked (recomputes the exit leaf)
  kind         TEXT NOT NULL DEFAULT 'file' CHECK (kind IN ('file','folder')),   -- a folder has no ciphertext
  parent_id    TEXT REFERENCES items(id) ON DELETE SET NULL,                    -- NULL = the drive's root
  parent_wrap  BLOB,                            -- 60 B: this item's key wrapped under its folder's; iff parent_id
  trashed_at   INTEGER                          -- in the Trash since (its links ended when it went there)
) STRICT;
CREATE INDEX items_owner  ON items(owner_id, state);
CREATE INDEX items_lane   ON items(lane, state);
CREATE INDEX items_doomed ON items(state, doomed_at);
CREATE INDEX items_expiry ON items(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX items_recent ON items(created_hour) WHERE canary = 0;
CREATE INDEX items_parent ON items(owner_id, parent_id, state);
CREATE INDEX items_child ON items(parent_id) WHERE parent_id IS NOT NULL;

CREATE TABLE uploads (
  id TEXT PRIMARY KEY, item_id TEXT NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
  owner_id TEXT, lane TEXT NOT NULL, reserved INTEGER NOT NULL, expires_at INTEGER NOT NULL
) STRICT;

CREATE TABLE chunks (
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE, idx INTEGER NOT NULL, sha256 BLOB NOT NULL,
  PRIMARY KEY (item_id, idx)
) STRICT, WITHOUT ROWID;

CREATE TABLE shares (
  id              TEXT PRIMARY KEY,
  item_id         TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  mode            TEXT NOT NULL CHECK (mode IN ('link','link_password','password')),
  wrapped_key     BLOB,                           -- NULL once ended
  access_hash     BLOB,                           -- NULL once ended
  link_hash       BLOB,                           -- link_password only; NULL once ended
  kdf             TEXT,                           -- JSON
  max_views       INTEGER,
  views_used      INTEGER NOT NULL DEFAULT 0,
  expires_at      INTEGER,
  state           TEXT NOT NULL DEFAULT 'active'
                  CHECK (state IN ('active','exhausted','expired','revoked','removed','owner_deleted')),
  created_hour    INTEGER NOT NULL,
  ended_at        INTEGER,
  pw_fail_count   INTEGER NOT NULL DEFAULT 0,     -- link_password with a valid link proof only
  pw_backoff_until INTEGER,
  pw_locked       INTEGER NOT NULL DEFAULT 0,
  pw_fails_day    TEXT, pw_fails_today INTEGER NOT NULL DEFAULT 0,   -- password-only global counter
  opens_hour      INTEGER, opens_in_hour INTEGER NOT NULL DEFAULT 0,
  first_opened_min INTEGER                        -- P-25: unix seconds floored to the minute; owner-only
) STRICT;
CREATE INDEX shares_item   ON shares(item_id, state);
CREATE INDEX shares_expiry ON shares(state, expires_at);

CREATE TABLE tickets (
  token_hash BLOB PRIMARY KEY, share_id TEXT,
  item_id    TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL, max_bytes INTEGER NOT NULL,
  bytes_served INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
  scope      TEXT NOT NULL DEFAULT 'item' CHECK (scope IN ('item','tree'))   -- tree: any ready descendant of item_id
) STRICT;
CREATE INDEX tickets_item ON tickets(item_id, done, expires_at);

CREATE TABLE drops (
  id            TEXT PRIMARY KEY,                 -- 10 Crockford base32 chars
  address       TEXT NOT NULL,                    -- the owner's locker address (public intake)
  tag           BLOB NOT NULL,                    -- 16
  label         TEXT NOT NULL DEFAULT '',
  manage_hash   BLOB NOT NULL,
  state         TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','closed','removed')),
  created_day   TEXT NOT NULL, ended_day TEXT,
  day           TEXT, files_today INTEGER NOT NULL DEFAULT 0, bytes_today INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE jobs (
  id         TEXT PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('courier','decoy','demo_pay','sponsor')),
  slice      TEXT NOT NULL CHECK (slice IN ('public','reserved','evidence')),
  evidence   INTEGER NOT NULL DEFAULT 0,
  payload    TEXT,                                -- JSON; scrubbed to NULL when done/failed
  state      TEXT NOT NULL CHECK (state IN ('queued','sending','done','failed')),
  not_before INTEGER NOT NULL,
  result     TEXT,                                -- {"pending_tx"} once submitted, then {"tx_id"[, "utxo_ids"]}
  error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
) STRICT;
CREATE INDEX jobs_queue ON jobs(state, not_before);

CREATE TABLE budgets (day TEXT NOT NULL, kind TEXT NOT NULL, slice TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
                      PRIMARY KEY (day, kind, slice)) STRICT;

CREATE TABLE invoices (
  id TEXT PRIMARY KEY, identity_id TEXT REFERENCES identities(id) ON DELETE SET NULL,
  pack TEXT NOT NULL, price_ut INTEGER NOT NULL, address TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','seen','proven','credited','underpaid','expired')),
  received_ut INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, credited_at INTEGER
) STRICT;

CREATE TABLE payments (                           -- one row per on-chain UTXO (idempotency)
  utxo_id    TEXT PRIMARY KEY,
  invoice_id TEXT REFERENCES invoices(id) ON DELETE SET NULL,
  value_ut   INTEGER NOT NULL,                    -- from the sidecar's proven opening
  seen_at    INTEGER NOT NULL, epoch INTEGER,
  proven     INTEGER NOT NULL DEFAULT 0,          -- unblindOutput opened the commitment (G4)
  committed  INTEGER NOT NULL DEFAULT 0,          -- independent indexer read OK
  status     TEXT NOT NULL CHECK (status IN ('pending_check','credited','unattributed','rejected'))
) STRICT;

CREATE TABLE chain_utxos (                        -- mirror of TARI UTXOs for in-browser scanning
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
  nonce BLOB NOT NULL, enc BLOB NOT NULL, tag BLOB, epoch INTEGER, first_seen INTEGER NOT NULL,
  promise INTEGER,                                -- minimum_value_promise: a public lower bound on the amount
  viewable INTEGER,                               -- 1 when a viewable_balance (resource view key) is attached
  auth TEXT                                       -- 'key' (a stealth one-time key) or the other auth variant
) STRICT;

CREATE TABLE abuse_reports (
  id TEXT PRIMARY KEY, share_id TEXT, item_id TEXT, drop_id TEXT, category TEXT NOT NULL, details TEXT NOT NULL,
  contact TEXT, included_key INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'new' CHECK (state IN ('new','actioned','rejected')), action_note TEXT
) STRICT;

-- SealLog storage receipts (spec §11) with exit receipts (P-8). Leaves hold hashes only; the item a leaf
-- belongs to can be recomputed only by someone who knows the item id. A leaf gets its index at the
-- checkpoint that commits it, in a random order within that checkpoint's batch (spec §11.3).
CREATE TABLE seal_leaves (
  idx       INTEGER UNIQUE,                       -- 0-based leaf index; NULL until a checkpoint places it
  kind      TEXT NOT NULL CHECK (kind IN ('stored','exit','pad')),
  leaf_hash BLOB NOT NULL UNIQUE                  -- RFC 9162 leaf hash SHA-256(0x00 || leaf_data)
) STRICT;

CREATE TABLE seal_checkpoints (                   -- submitted by the chain worker itself, never through jobs
  idx          INTEGER PRIMARY KEY,
  tree_size    INTEGER NOT NULL,
  root         BLOB NOT NULL,
  created_at   INTEGER NOT NULL,
  state        TEXT NOT NULL CHECK (state IN ('pending','committed','failed')),
  tx_id        TEXT, submitted_at INTEGER, epoch INTEGER,
  component    TEXT,                              -- the SealLog component it was appended to
  chain_index  INTEGER                            -- that component's checkpoint number (its root event)
) STRICT;

CREATE TABLE judge_passes (                       -- P-12: passes for the Council
  code_hash  BLOB PRIMARY KEY,                    -- SHA-256 of the normalized code
  uses_left  INTEGER NOT NULL,                    -- budgeted sends (courier, demo-pay, sponsor)
  created_at INTEGER NOT NULL,                    -- a pass works for auth.JUDGE_PASS_DAYS after this
  pow_skips_left INTEGER NOT NULL DEFAULT 100     -- proofs of work it may stand in for
) STRICT;

-- Opens per link per UTC hour (the owner's Activity): a count, never who opened it. Gone with the link's
-- tombstone (the cascade).
CREATE TABLE share_opens (
  share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  hour     INTEGER NOT NULL,
  n        INTEGER NOT NULL,
  PRIMARY KEY (share_id, hour)
) STRICT, WITHOUT ROWID;

-- Pay to open (annex §1.4). A drive's sales address, registered with its first paid link; its view key
-- arrives sealed (kind 3) to the payment checker's keys, which only the chain worker holds.
CREATE TABLE sellers (
  identity_id  TEXT PRIMARY KEY REFERENCES identities(id) ON DELETE CASCADE,
  address      TEXT NOT NULL,                    -- sales address (base, no pay-ref)
  view_sealed  BLOB NOT NULL,                    -- 125 B
  state        TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','ok','bad_key')),
  scan_seq     INTEGER NOT NULL DEFAULT 0,       -- the worker's mirror cursor for this seller
  scanned_at   INTEGER,
  created_at   INTEGER NOT NULL
) STRICT;

CREATE TABLE paid_shares (                       -- one row per paid link (shares.mode stays 'link')
  share_id       TEXT PRIMARY KEY REFERENCES shares(id) ON DELETE CASCADE,
  price_ut       INTEGER NOT NULL,
  server_half    BLOB,                           -- 32 B; NULL once the link ends
  teaser_ct      BLOB,
  buyer_views    INTEGER NOT NULL,
  buyer_window_s INTEGER NOT NULL,
  paused         INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE claims (                            -- one per buyer attempt; never an identity, never an IP
  id           TEXT PRIMARY KEY,                 -- "clm_" + 20 [a-z2-7]; it is the pay-ref
  share_id     TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  token_hash   BLOB NOT NULL UNIQUE,             -- SHA-256 of the buyer's claim token
  address      TEXT NOT NULL,                    -- the sales address with this claim's pay-ref
  price_ut     INTEGER NOT NULL,
  received_ut  INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL CHECK (status IN ('pending','seen','underpaid','paid','released','expired','void')),
  owner_check  TEXT NOT NULL DEFAULT 'none' CHECK (owner_check IN ('none','pending','ok','bad')),   -- release gate
  created_at   INTEGER NOT NULL,
  created_seq  INTEGER NOT NULL,                 -- mirror head when made (where its scan starts)
  expires_at   INTEGER NOT NULL,
  paid_at      INTEGER,
  released_at  INTEGER,
  views_left   INTEGER,
  open_until   INTEGER,
  demo         INTEGER NOT NULL DEFAULT 0        -- paid by our demo wallet
) STRICT;
CREATE INDEX claims_open ON claims(status, expires_at);
CREATE INDEX claims_share ON claims(share_id, status);

CREATE TABLE sale_payments (                     -- one row per UTXO ever; apart from pack payments
  utxo_id    TEXT PRIMARY KEY,
  claim_id   TEXT REFERENCES claims(id) ON DELETE SET NULL,
  value_ut   INTEGER NOT NULL,
  seen_at    INTEGER NOT NULL,
  epoch      INTEGER,
  committed  INTEGER NOT NULL DEFAULT 0,
  status     TEXT NOT NULL CHECK (status IN ('pending_check','counted','extra')),
  owner_ok   INTEGER CHECK (owner_ok IN (0,1))       -- the seller's drive: 1 its to spend, 0 the payer kept it
) STRICT;
