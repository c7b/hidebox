-- SPDX-License-Identifier: MIT
-- Schema 5 → 6: space packs against griefing (server/mutis/packs.py). Additive only.
-- invoices.judge: the invoice was made with a judge pass, so its pack draws from the judges' slice of the
-- paid cap and counts against their daily ceiling, not the public one. identities.paid_pack and
-- paid_judge: which pack a drive holds and which slice it takes (a drive holds one pack at a time).
-- No network, address or pass code is stored.

ALTER TABLE invoices ADD COLUMN judge INTEGER NOT NULL DEFAULT 0 CHECK (judge IN (0,1));
ALTER TABLE identities ADD COLUMN paid_pack TEXT;
ALTER TABLE identities ADD COLUMN paid_judge INTEGER NOT NULL DEFAULT 0 CHECK (paid_judge IN (0,1));
