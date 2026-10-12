# SPDX-License-Identifier: MIT
"""Encodings, HKDF, random ids and time helpers shared by every module (spec §4.2, §6.1)."""
import base64
import hashlib
import hmac
import re
import secrets
import time

_B64U = re.compile(r"^[A-Za-z0-9_-]*$")
CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"   # lowercase Crockford base32 (no i, l, o, u)
RFC4648_LOWER = "abcdefghijklmnopqrstuvwxyz234567"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text: str, length: int | None = None) -> bytes:
    """Strict base64url without padding; rejects non-canonical encodings. Raises ValueError."""
    if not isinstance(text, str) or not _B64U.match(text) or len(text) % 4 == 1:
        raise ValueError("not base64url")
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if b64u(data) != text:
        raise ValueError("non-canonical base64url")
    if length is not None and len(data) != length:
        raise ValueError("wrong length")
    return data


def sha256(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.digest()


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256 (RFC 5869)."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def equal(a: bytes | None, b: bytes | None) -> bool:
    """Constant-time comparison that treats a missing value as a mismatch."""
    return a is not None and b is not None and hmac.compare_digest(a, b)


def new_id() -> str:
    """22-character random id (16 bytes, b64u) for items, shares, uploads, jobs."""
    return b64u(secrets.token_bytes(16))


def random_chars(alphabet: str, n: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def drop_id() -> str:
    return random_chars(CROCKFORD, 10)


def invoice_id() -> str:
    return "inv_" + random_chars(RFC4648_LOWER, 20)


def report_id() -> str:
    return "rep_" + random_chars(RFC4648_LOWER, 16)


def now() -> int:
    return int(time.time())


def day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def floor_hour(ts: int) -> int:
    return ts - ts % 3600


def coarse_expiry(expires_at: int, now: int) -> int:
    """An expiry at least an hour away is rounded up to the next whole hour, so `expires_at - preset`
    can't give away the second a file arrived (arrival is stored to the hour). Shorter expiries (the
    E2E preset) stay exact."""
    return -(-expires_at // 3600) * 3600 if expires_at - now >= 3600 else expires_at


def floor_minute(ts: int) -> int:
    return ts - ts % 60


def next_utc_midnight(ts: int) -> int:
    return ts - ts % 86400 + 86400
