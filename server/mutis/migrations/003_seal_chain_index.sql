-- SPDX-License-Identifier: MIT
-- Schema 2 → 3. A SealLog checkpoint records the component it was appended to and that component's own
-- checkpoint number (the `index` of its SealLog.root event), which is what a reader finds on chain.

ALTER TABLE seal_checkpoints ADD COLUMN component TEXT;
ALTER TABLE seal_checkpoints ADD COLUMN chain_index INTEGER;
