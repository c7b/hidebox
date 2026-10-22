# SPDX-License-Identifier: MIT
"""Two numbers a day (viral-1, C60): whether the share link brings people back.

A browser tab that arrived through Make your own secret or Sell your own files (`?from=share`) keeps a flag in its
own sessionStorage; its next one-off link (the home's share box, no drive) or its next new drive says so once, with
`from_share: true` in the create request. The create handler adds one to that UTC day's row, in its own transaction.
The table holds the day, which of the two, and a count: no id, no link to the link or drive it made, no network, no
time finer than the day. `mutis-admin counts` prints it; cleanup deletes rows older than `cleanup.COUNT_DAYS`.
"""
import sqlite3

from . import codec

KINDS = ("secret_from_share", "drive_from_share")


def add(conn: sqlite3.Connection, kind: str, now: int) -> None:
    """One more for `kind` on today's UTC row; call it inside the transaction that made the link or the drive."""
    if kind not in KINDS:
        raise ValueError(kind)
    conn.execute("INSERT INTO daily_counts(day, kind, n) VALUES (?, ?, 1) "
                 "ON CONFLICT(day, kind) DO UPDATE SET n = n + 1", (codec.day(now), kind))


def recent(conn: sqlite3.Connection, days: int, now: int) -> list[sqlite3.Row]:
    """The rows of the last `days` UTC days, today included, newest first."""
    return conn.execute("SELECT day, kind, n FROM daily_counts WHERE day > ? ORDER BY day DESC, kind DESC",
                        (codec.day(now - days * 86400),)).fetchall()


def purge(conn: sqlite3.Connection, keep_days: int, now: int) -> int:
    return conn.execute("DELETE FROM daily_counts WHERE day <= ?", (codec.day(now - keep_days * 86400),)).rowcount
