-- SPDX-License-Identifier: MIT
-- Schema 6 → 7: two numbers a day (viral-1, C60; server/mutis/counts.py). Additive only.
-- How many one-off links (the home's share box, no drive) and how many drives were made by a browser tab that
-- arrived through Make your own secret or Sell your own files: the UTC day, which of the two, and a count.
-- No id, no link, no drive, no network, no time finer than the day. Rows older than cleanup.COUNT_DAYS go.

CREATE TABLE daily_counts (
  day  TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('secret_from_share','drive_from_share')),
  n    INTEGER NOT NULL CHECK (n > 0),
  PRIMARY KEY (day, kind)
) STRICT, WITHOUT ROWID;
