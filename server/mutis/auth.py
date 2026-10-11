# SPDX-License-Identifier: MIT
"""Locker sessions (spec §4.8.4) and judge passes (brand patch P-12).

The server keeps only hashes: SHA-256(authKey) as the verifier, SHA-256(session token), and
SHA-256(judge code). Comparisons go through hmac.compare_digest.
"""
import secrets
import sqlite3

from . import codec, db
from .http_util import ApiError

SESSION_TTL_S = 30 * 86400
SESSION_IDLE_DAYS = 7
JUDGE_PREFIX = "judge-"


def bearer(header: str | None) -> bytes | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme != "Bearer":
        raise ApiError(401, "invalid_session", "Sign in again.")
    try:
        return codec.unb64u(value.strip(), 32)
    except ValueError:
        raise ApiError(401, "invalid_session", "Sign in again.") from None


def create_session(conn: sqlite3.Connection, identity_id: str, now: int) -> tuple[bytes, int]:
    token = secrets.token_bytes(32)
    expires = now + SESSION_TTL_S
    conn.execute("INSERT INTO sessions(token_hash, identity_id, created_at, expires_at, last_used_day) "
                 "VALUES (?, ?, ?, ?, ?)", (codec.sha256(token), identity_id, now, expires, codec.day(now)))
    return token, expires


def touch_identity(conn: sqlite3.Connection, identity_id: str, now: int) -> None:
    """Count a new active day (probation ends on the second one, spec §9.2)."""
    today = codec.day(now)
    conn.execute("UPDATE identities SET last_seen_day = ?, distinct_days = distinct_days + 1 "
                 "WHERE id = ? AND last_seen_day <> ?", (today, identity_id, today))


def resolve(conn: sqlite3.Connection, token: bytes, now: int) -> sqlite3.Row:
    """Session token → identity row. Raises 401 invalid_session or 403 forbidden."""
    row = conn.execute("SELECT identity_id, expires_at, last_used_day FROM sessions WHERE token_hash = ?",
                       (codec.sha256(token),)).fetchone()
    if row is None or row["expires_at"] <= now or row["last_used_day"] < codec.day(now - SESSION_IDLE_DAYS * 86400):
        raise ApiError(401, "invalid_session", "Sign in again.")
    today = codec.day(now)
    if row["last_used_day"] != today:
        with db.tx(conn):
            conn.execute("UPDATE sessions SET last_used_day = ? WHERE token_hash = ?", (today, codec.sha256(token)))
            touch_identity(conn, row["identity_id"], now)
    identity = conn.execute("SELECT * FROM identities WHERE id = ?", (row["identity_id"],)).fetchone()
    if identity is None:
        raise ApiError(401, "invalid_session", "Sign in again.")
    if identity["state"] != "active":
        raise ApiError(403, "forbidden", "This locker is suspended.")
    return identity


def end_session(conn: sqlite3.Connection, token: bytes) -> None:
    with db.tx(conn):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (codec.sha256(token),))


# --- judge passes ---------------------------------------------------------------------------------

JUDGE_PASS_DAYS = 30


def new_judge_code() -> str:
    return JUDGE_PREFIX + codec.random_chars(codec.CROCKFORD, 24)


def judge_hash(code: str) -> bytes:
    return codec.sha256(code.strip().lower().encode("ascii", "ignore"))


def _live_after(now: int) -> int:
    return now - JUDGE_PASS_DAYS * 86400


def judge_pass_live(conn: sqlite3.Connection, code: str, now: int) -> bool:
    return conn.execute("SELECT 1 FROM judge_passes WHERE code_hash = ? AND created_at > ?",
                        (judge_hash(code), _live_after(now))).fetchone() is not None


def spend_judge_use(conn: sqlite3.Connection, code: str, now: int) -> bool:
    """One budgeted send, inside the caller's transaction (so a refused send keeps its use)."""
    return conn.execute("UPDATE judge_passes SET uses_left = uses_left - 1 "
                        "WHERE code_hash = ? AND uses_left > 0 AND created_at > ?",
                        (judge_hash(code), _live_after(now))).rowcount == 1


def skip_pow(conn: sqlite3.Connection, code: str, now: int) -> bool:
    """One proof of work the pass stands in for; a leaked pass can't skip them without limit."""
    with db.tx(conn):
        return conn.execute("UPDATE judge_passes SET pow_skips_left = pow_skips_left - 1 "
                            "WHERE code_hash = ? AND pow_skips_left > 0 AND created_at > ?",
                            (judge_hash(code), _live_after(now))).rowcount == 1
