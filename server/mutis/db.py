# SPDX-License-Identifier: MIT
"""SQLite access: connection settings, transactions, meta helpers and forward-only migrations (spec §7)."""
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
MIGRATIONS = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 3
# Threads of one process queue here instead of spinning in SQLite's busy handler; other processes
# (worker, cleanup) still wait on SQLite's own lock.
_WRITERS = threading.Lock()


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Ended links lose their wrapped key with an UPDATE; this makes SQLite overwrite the freed bytes in
    # the database file with zeros. Debian builds turn it on by default; other builds may not.
    conn.execute("PRAGMA secure_delete=ON")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """One write transaction. BEGIN IMMEDIATE takes the lock up front, so check-then-act code can't race."""
    with _WRITERS:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def get_meta_json(conn: sqlite3.Connection, key: str, default=None):
    value = get_meta(conn, key)
    return json.loads(value) if value is not None else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"), sort_keys=True)
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (key, text))


def del_meta(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM meta WHERE key = ?", (key,))


def version(path: Path | str) -> int:
    """The schema version of an existing database file (0 before the schema exists)."""
    conn = connect(path)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
            return 0
        return int(get_meta(conn, "schema_version", "0"))
    finally:
        conn.close()


def _migration_files(directory: Path) -> list[tuple[int, Path]]:
    found = []
    if directory.is_dir():
        for path in directory.glob("*.sql"):
            m = re.match(r"^(\d{3})_[a-z0-9_]+\.sql$", path.name)
            if m:
                found.append((int(m.group(1)), path))
    return sorted(found)


def migrate(path: Path | str, migrations: Path = MIGRATIONS) -> int:
    """Create the schema on an empty database, then apply numbered migrations above schema_version.

    Returns the resulting schema version. Each migration runs in its own transaction.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        if not has_meta:
            with tx(conn):
                for statement in _statements(SCHEMA.read_text()):
                    conn.execute(statement)
                set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        version = int(get_meta(conn, "schema_version"))
        for number, file in _migration_files(migrations):
            if number <= version:
                continue
            with tx(conn):
                for statement in _statements(file.read_text()):
                    conn.execute(statement)
                set_meta(conn, "schema_version", str(number))
            version = number
        return version
    finally:
        conn.close()


def _statements(sql: str) -> list[str]:
    """Split a schema file into statements (our SQL has no '--' or ';' inside string literals)."""
    text = "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())
    return [s.strip() for s in text.split(";") if s.strip()]
