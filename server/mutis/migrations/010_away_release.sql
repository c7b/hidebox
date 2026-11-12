-- SPDX-License-Identifier: MIT
-- Schema 9 → 10: release without the seller's drive (docs/mvp-november.md §2), behind features.away_release.
-- Additive only. owner_ok (schema 5) says whether a sale payment is the seller's to spend; checked_by says who checked:
-- 'server', our payment checker, from the sales view key and the address's account key (the watch-only check, Ootle
-- 0.48+), when it counted the payment; 'drive', the seller's own drive (POST /me/sales/claims/{id}/confirm). NULL
-- while nobody has. Nothing new is stored about the payment or the buyer.

ALTER TABLE sale_payments ADD COLUMN checked_by TEXT CHECK (checked_by IN ('server','drive'));
