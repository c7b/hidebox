-- SPDX-License-Identifier: MIT
-- Schema 4 → 5: the owner's check of each sale payment (research 16-drive-design §4, the release gate).
-- Additive only. A view key proves a payment's amount, not who can spend it, so a payment that isn't our
-- own test money waits until the seller's drive compares each output's one-time key with its own:
-- owner_ok is NULL until it answers, 1 when the output is the drive's to spend, 0 when the payer kept it.
-- A claim releases once every output that counted for it is 1; one 0 voids the claim.

ALTER TABLE sale_payments ADD COLUMN owner_ok INTEGER CHECK (owner_ok IN (0,1));
