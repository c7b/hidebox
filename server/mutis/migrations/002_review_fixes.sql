-- SPDX-License-Identifier: MIT
-- Schema 1 → 2. Jobs get an `evidence` budget slice and lose the `seal` kind (the chain worker submits
-- SealLog checkpoints itself); a SealLog leaf gets its index only at the checkpoint that commits it;
-- judge passes get a count of PoW skips; mirrored outputs record what they reveal.
-- SQLite can't change a CHECK constraint in place, so `jobs` and the SealLog tables are rebuilt.

CREATE TABLE jobs_v2 (
  id         TEXT PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('courier','decoy','demo_pay','sponsor')),
  slice      TEXT NOT NULL CHECK (slice IN ('public','reserved','evidence')),
  evidence   INTEGER NOT NULL DEFAULT 0,
  payload    TEXT,
  state      TEXT NOT NULL CHECK (state IN ('queued','sending','done','failed')),
  not_before INTEGER NOT NULL,
  result     TEXT,
  error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
) STRICT;
INSERT INTO jobs_v2 SELECT * FROM jobs WHERE kind <> 'seal';
DROP TABLE jobs;
ALTER TABLE jobs_v2 RENAME TO jobs;
CREATE INDEX jobs_queue ON jobs(state, not_before);

-- Leaves keep an index only where a committed checkpoint already covers it.
CREATE TABLE seal_leaves_v2 (
  idx       INTEGER UNIQUE,
  kind      TEXT NOT NULL CHECK (kind IN ('stored','exit','pad')),
  leaf_hash BLOB NOT NULL UNIQUE
) STRICT;
INSERT INTO seal_leaves_v2(rowid, idx, kind, leaf_hash)
  SELECT idx + 1,
         CASE WHEN idx < (SELECT COALESCE(MAX(tree_size), 0) FROM seal_checkpoints WHERE state = 'committed')
              THEN idx END,
         kind, leaf_hash
  FROM seal_leaves;
DROP TABLE seal_leaves;
ALTER TABLE seal_leaves_v2 RENAME TO seal_leaves;

-- A checkpoint that never committed is failed; the next one commits its leaves.
CREATE TABLE seal_checkpoints_v2 (
  idx          INTEGER PRIMARY KEY,
  tree_size    INTEGER NOT NULL,
  root         BLOB NOT NULL,
  created_at   INTEGER NOT NULL,
  state        TEXT NOT NULL CHECK (state IN ('pending','committed','failed')),
  tx_id        TEXT, submitted_at INTEGER, epoch INTEGER
) STRICT;
INSERT INTO seal_checkpoints_v2(idx, tree_size, root, created_at, state, tx_id, submitted_at, epoch)
  SELECT idx, tree_size, root, created_at, CASE WHEN state = 'committed' THEN 'committed' ELSE 'failed' END,
         tx_id, NULL, epoch
  FROM seal_checkpoints;
DROP TABLE seal_checkpoints;
ALTER TABLE seal_checkpoints_v2 RENAME TO seal_checkpoints;

ALTER TABLE judge_passes ADD COLUMN pow_skips_left INTEGER NOT NULL DEFAULT 100;

ALTER TABLE chain_utxos ADD COLUMN promise INTEGER;
ALTER TABLE chain_utxos ADD COLUMN viewable INTEGER;
ALTER TABLE chain_utxos ADD COLUMN auth TEXT;
