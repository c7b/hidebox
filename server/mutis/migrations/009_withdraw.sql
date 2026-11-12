-- SPDX-License-Identifier: MIT
-- Schema 8 → 9: withdrawing earnings (server/mutis/withdraw.py, docs/withdraw.md), behind features.withdraw.
-- Additive only. A withdrawal is signed in the seller's browser with keys our server never holds; our server checks
-- that it spends only this drive's settled sales outputs, relays it, and marks what it spent:
-- sale_payments.withdraw_tx / withdraw_at: the withdrawal that spends this payment's output (pending until the
-- drive reports its outcome, or for withdraw.PENDING_S), withdrawn = 1 once it committed.
-- sales_change: what a withdrawal sent back to the drive's sales address (the drive says which output, and its value;
-- the output must be one of that transaction's), withdrawable in turn once its transaction committed.
-- No destination address, ever: it is inside a stealth output, and our server isn't told.

ALTER TABLE sale_payments ADD COLUMN withdraw_tx TEXT;
ALTER TABLE sale_payments ADD COLUMN withdraw_at INTEGER;
ALTER TABLE sale_payments ADD COLUMN withdrawn INTEGER NOT NULL DEFAULT 0 CHECK (withdrawn IN (0,1));

CREATE TABLE sales_change (
  utxo_id     TEXT PRIMARY KEY,
  identity_id TEXT NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
  value_ut    INTEGER NOT NULL CHECK (value_ut > 0),
  from_tx     TEXT NOT NULL,
  committed   INTEGER NOT NULL DEFAULT 0 CHECK (committed IN (0,1)),
  created_at  INTEGER NOT NULL,
  withdraw_tx TEXT,
  withdraw_at INTEGER,
  withdrawn   INTEGER NOT NULL DEFAULT 0 CHECK (withdrawn IN (0,1))
) STRICT;
CREATE INDEX sales_change_owner ON sales_change(identity_id, withdrawn);
