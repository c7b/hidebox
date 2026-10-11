# SPDX-License-Identifier: MIT
"""Proof of work (spec §4.12): stateless HMAC'd challenges, single use, per-IP-key escalation."""
import hashlib
import hmac
import math
import secrets
import sqlite3
import struct
import threading
from collections import defaultdict, deque

from . import codec, db

VERSION = 1
CHALLENGE_LEN = 36
NONCE_LEN = 8
VALID_S = 300
MAX_BITS = 24
GLOBAL_MAX_BITS = 20

PURPOSES = {"upload": (1, 16), "register": (2, 18), "courier": (3, 18), "demo_pay": (4, 18), "report": (5, 16),
            "drop_create": (6, 18), "sponsor": (7, 18), "password": (8, 16)}
_BY_CODE = {code: name for name, (code, _) in PURPOSES.items()}

# The per-ip64 hourly limit of each purpose's endpoint (spec §6.2); escalation compares a key's
# 10-minute count of solutions used with a sixth of it, but never with less than ESCALATE_FLOOR, so a
# phone and a laptop behind one address can each retry a few times before anything gets harder.
HOURLY = {"upload": 30, "register": 5, "courier": 10, "demo_pay": 2 / 24, "report": 10, "drop_create": 5,
          "sponsor": 1 / 24, "password": 20}
ESCALATE_FLOOR = 3
# Solutions used per 10 minutes, across everyone, above which every client gets +2 bits (never past 20).
GLOBAL_10MIN = {"upload": 600, "register": 60, "courier": 120, "demo_pay": 30, "report": 60, "drop_create": 60,
                "sponsor": 30, "password": 300}


class PowError(Exception):
    def __init__(self, code: str, difficulty: int = 0):
        super().__init__(code)
        self.code = code
        self.difficulty = difficulty


def leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        return bits + 8 - byte.bit_length()
    return bits


def make_challenge(k_pow: bytes, purpose: str, difficulty: int, expiry: int, rand: bytes | None = None) -> bytes:
    code = PURPOSES[purpose][0]
    head = struct.pack(">BBBBI", VERSION, code, difficulty, 0, expiry) + (rand or secrets.token_bytes(12))
    return head + hmac.new(k_pow, head, hashlib.sha256).digest()[:16]


def parse_challenge(k_pow: bytes, challenge: bytes) -> tuple[str, int, int]:
    """Authenticate a challenge and return (purpose, difficulty, expiry). Raises PowError."""
    if len(challenge) != CHALLENGE_LEN:
        raise PowError("pow_invalid")
    head, tag = challenge[:20], challenge[20:]
    if not hmac.compare_digest(hmac.new(k_pow, head, hashlib.sha256).digest()[:16], tag):
        raise PowError("pow_invalid")
    version, code, difficulty, zero, expiry = struct.unpack(">BBBBI", head[:8])
    if version != VERSION or zero != 0 or code not in _BY_CODE:
        raise PowError("pow_invalid")
    return _BY_CODE[code], difficulty, expiry


def solved(challenge: bytes, nonce: bytes, difficulty: int) -> bool:
    return leading_zero_bits(hashlib.sha256(challenge + nonce).digest()) >= difficulty


class Pow:
    """Issues and verifies challenges. Rate memory lives only in this process (spec §6.2).

    Escalation counts solutions spent, not challenges issued: asking for a challenge costs nothing,
    so counting those would let anyone make the next one harder without doing any work.
    """

    def __init__(self, k_pow: bytes, base_override: int | None = None):
        self.k_pow = k_pow
        self.base_override = base_override
        self._lock = threading.Lock()
        self._per_key: dict[tuple[str, bytes], deque] = defaultdict(deque)
        self._global: dict[str, deque] = defaultdict(deque)

    def base(self, purpose: str) -> int:
        return self.base_override if self.base_override is not None else PURPOSES[purpose][1]

    @staticmethod
    def _count(window: deque, now: int) -> int:
        while window and window[0] <= now - 600:
            window.popleft()
        return len(window)

    def difficulty(self, purpose: str, ip64: bytes, now: int) -> int:
        """Base bits, +2 per factor of 3 over the key's own hourly average (cap 24), global +2 (cap 20).

        A fixed override (tests, --dev --pow-bits) turns escalation off.
        """
        base = self.base(purpose)
        if self.base_override is not None:
            return base
        with self._lock:
            mine = self._count(self._per_key.get((purpose, ip64), deque()), now)   # asking must not add a key
            everyone = self._count(self._global[purpose], now)
        average = max(HOURLY[purpose] / 6, ESCALATE_FLOOR)
        extra = 2 * int(math.log(mine / average, 3) + 1e-9) if mine > average else 0
        bits = min(MAX_BITS, base + extra)
        if everyone > GLOBAL_10MIN[purpose]:
            bits = max(bits, min(bits + 2, GLOBAL_MAX_BITS))
        return bits

    def issue(self, purpose: str, ip64: bytes, now: int, min_difficulty: int = 0) -> dict:
        bits = max(self.difficulty(purpose, ip64, now), min(min_difficulty, MAX_BITS))
        expiry = now + VALID_S
        challenge = make_challenge(self.k_pow, purpose, bits, expiry)
        return {"challenge": codec.b64u(challenge), "difficulty": bits, "expires_at": expiry}

    def _spent(self, purpose: str, ip64: bytes, now: int) -> None:
        with self._lock:
            window = self._per_key[(purpose, ip64)]
            self._count(window, now)
            if len(window) < 5000:
                window.append(now)
            everyone = self._global[purpose]
            self._count(everyone, now)
            if len(everyone) < 100000:
                everyone.append(now)

    def verify(self, conn: sqlite3.Connection, solution, purpose: str, ip64: bytes, now: int,
               min_difficulty: int = 0) -> None:
        """Check a {challenge, nonce} solution and burn it. Raises PowError(pow_required|pow_invalid)."""
        needed = max(self.base(purpose), min_difficulty)
        if not isinstance(solution, dict):
            raise PowError("pow_required", needed)
        try:
            challenge = codec.unb64u(solution.get("challenge"), CHALLENGE_LEN)
            nonce = codec.unb64u(solution.get("nonce"), NONCE_LEN)
        except (ValueError, TypeError):
            raise PowError("pow_invalid", needed) from None
        got_purpose, difficulty, expiry = parse_challenge(self.k_pow, challenge)
        if got_purpose != purpose or expiry < now or difficulty < needed or not solved(challenge, nonce, difficulty):
            raise PowError("pow_invalid", needed)
        try:
            with db.tx(conn):
                conn.execute("INSERT INTO used_nonces(nonce_hash, expires_at) VALUES (?, ?)",
                             (codec.sha256(challenge), expiry))
        except sqlite3.IntegrityError:
            raise PowError("pow_invalid", needed) from None
        self._spent(purpose, ip64, now)

    def reset(self) -> None:
        with self._lock:
            self._per_key.clear()
            self._global.clear()
