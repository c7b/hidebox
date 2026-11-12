-- SPDX-License-Identifier: MIT
-- Schema 11 → 12: an invoice keeps the terms it was made with (docs/pricing.md). Additive only.
-- The packs on sale come from the deployment's config (`packs.catalog`, or the built-in two), so a change of sizes or
-- prices must not change what an open invoice promised: pack_bytes and pack_days are the pack's size and days when
-- the invoice was made (price_ut already was). NULL for an invoice made before this schema: its pack id names one of
-- the built-in packs (quota.PACKS), whose terms never changed after.

ALTER TABLE invoices ADD COLUMN pack_bytes INTEGER;
ALTER TABLE invoices ADD COLUMN pack_days INTEGER;
