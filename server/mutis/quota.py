# SPDX-License-Identifier: MIT
"""Sizes, per-class limits and the adaptive free quota (spec §4.4.2, §9.1, §9.2, §9.4, §9.7)."""
import sqlite3
from dataclasses import dataclass

from . import codec, db

KiB, MiB, GiB = 1 << 10, 1 << 20, 1 << 30
CHUNK = 4 * MiB
TAG = 16
INLINE_MAX_STORED = 256 * KiB
TEXT_MAX_CHARS = 10_000
TEXT_MAX_BYTES = 64 * KiB

SMALL_PLAINTEXT_MAX = 5 * MiB
DEMO_RESERVE = 128 * MiB          # the SMALL lane's last 128 MiB only takes files of at most 1 MiB
DEMO_FILE_MAX = 1 * MiB

QUOTA_FLOOR = 256 * MiB
QUOTA_CEILING = 5 * GiB
QUOTA_STEP = 64 * MiB
OVERCOMMIT = 4
ACTIVE_DAYS = 30
N_MIN = 100
RESERVE_FRACTION = 0.10
ANON_FRACTION = 0.08
FREEZE_FREE_MARGIN = 2 * GiB
FREEZE_ALL_MARGIN = 256 * MiB

# Spec §9.4. Durations in seconds.
CLASSES = {
    "anon": {"max_file_bytes": 25 * MiB, "small_lane_max_bytes": SMALL_PLAINTEXT_MAX, "max_expiry_s": 86400,
             "default_expiry_s": 86400, "max_views": 10, "links_per_item": 3},
    "drop": {"max_file_bytes": 25 * MiB, "expiry_s": 7 * 86400, "views": 3, "links_per_item": 1},
    "probation": {"max_file_bytes": 64 * MiB, "quota_bytes": 64 * MiB, "max_expiry_s": 7 * 86400,
                  "default_expiry_s": 7 * 86400, "max_views": 50, "sends_per_day": 3, "links_per_item": 10},
    "locker": {"max_file_bytes": 512 * MiB, "max_expiry_s": 30 * 86400, "default_expiry_s": 7 * 86400,
               "max_views": 50, "sends_per_day": 20, "links_per_item": 50},
    "paid": {"max_file_bytes": 2 * GiB, "max_expiry_s": 30 * 86400, "default_expiry_s": 7 * 86400,
             "max_views": 50, "sends_per_day": 50, "links_per_item": 50},
}
CANARY_MAX_EXPIRY_S = 2 * 86400
# Send by Tari (16-drive-design §3): the link sealed to an address opens this many times within this long
# (a first-day drive's links last at most its own max_expiry_s).
SEND_VIEWS = 3
SEND_EXPIRY_S = 30 * 86400

# Against griefing: the big pack is 5 GiB, so a few purchases can't take the paid share at once.
PACKS = {"s30": {"bytes": 2 * GiB, "days": 30, "price_ut": 500_000},
         "m30": {"bytes": 5 * GiB, "days": 30, "price_ut": 1_000_000}}


def padme(length: int) -> int:
    """Padmé padding (Nikitin et al., PETS 2019), with a 1 KiB minimum (spec §4.4.2)."""
    if length <= 1024:
        return 1024
    e = length.bit_length() - 1
    s = e.bit_length()
    mask = (1 << (e - s)) - 1
    return (length + mask) & ~mask


def stored_size(padded: int) -> int:
    chunks = max(1, -(-padded // CHUNK))
    return padded + TAG * chunks


def max_stored(plaintext_max: int) -> int:
    """The largest size_stored a file of at most `plaintext_max` bytes can have (Padmé is monotonic)."""
    return stored_size(padme(plaintext_max))


def valid_layout(size_stored: int, chunk_count: int) -> bool:
    """size_stored = (n-1)(CS+16) + last with 17 <= last <= CS+16 (spec §6.3 POST /uploads)."""
    if not isinstance(size_stored, int) or not isinstance(chunk_count, int) or chunk_count < 1:
        return False
    last = size_stored - (chunk_count - 1) * (CHUNK + TAG)
    return TAG + 1 <= last <= CHUNK + TAG


def chunk_length(size_stored: int, chunk_count: int, index: int) -> int:
    if index < chunk_count - 1:
        return CHUNK + TAG
    return size_stored - (chunk_count - 1) * (CHUNK + TAG)


@dataclass(frozen=True)
class Pool:
    d_total: int
    d_avail: int
    stored: int          # B: stored + reserved ciphertext bytes
    paid: int
    n: int
    reserve: int
    pool: int
    small: int
    drop: int
    anon: int
    free_pool: int
    q_target: int


def compute(d_total: int, d_avail: int, stored: int, paid: int, n_active: int, limits: dict) -> Pool:
    """The §9.1–§9.2 formulas. `limits` is the [limits] config table."""
    reserve = max(limits["reserve_min_bytes"], int(RESERVE_FRACTION * d_total))
    pool = max(0, stored + d_avail - reserve)
    small, drop = limits["small_lane_bytes"], limits["drop_lane_bytes"]
    anon = min(int(ANON_FRACTION * pool), limits["anon_lane_max_bytes"])
    free_pool = max(0, pool - paid - small - drop - anon)
    n = max(N_MIN, n_active)
    target = min(max(OVERCOMMIT * free_pool // n, QUOTA_FLOOR), QUOTA_CEILING)
    target -= target % QUOTA_STEP
    return Pool(d_total, d_avail, stored, paid, n, reserve, pool, small, drop, anon, free_pool, target)


def smooth(q_old: int, q_target: int) -> int:
    """Hourly step toward the target: at most -0.4 % / +0.8 % of the old value (≈ -10 % / +20 % a day)."""
    step = min(max(q_target - q_old, -int(0.004 * q_old)), int(0.008 * q_old))
    return q_old + step


def measure(conn: sqlite3.Connection, statvfs, data_dir, limits: dict, now: int) -> Pool:
    st = statvfs(data_dir)
    d_total, d_avail = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    stored = conn.execute("SELECT COALESCE(SUM(size_stored), 0) FROM items "
                          "WHERE state IN ('uploading','ready','doomed')").fetchone()[0]
    paid = conn.execute("SELECT COALESCE(SUM(paid_bytes), 0) FROM identities WHERE paid_until > ?",
                        (now,)).fetchone()[0]
    # N counts lockers active on two or more days that store something: a locker made only to be
    # counted would have to hold files too.
    since = codec.day(now - ACTIVE_DAYS * 86400)
    n_active = conn.execute("SELECT COUNT(*) FROM identities WHERE distinct_days >= 2 AND last_seen_day >= ? "
                            "AND used_bytes > 0", (since,)).fetchone()[0]
    return compute(d_total, d_avail, stored, paid, n_active, limits)


def free_quota(conn: sqlite3.Connection, pool: Pool) -> int:
    """The current free quota Q (meta.free_quota_bytes; the target on first boot)."""
    value = db.get_meta(conn, "free_quota_bytes")
    return int(value) if value is not None else pool.q_target


def class_of(identity: sqlite3.Row, now: int) -> str:
    if identity["paid_until"] and identity["paid_until"] > now and identity["paid_bytes"] > 0:
        return "paid"
    return "probation" if identity["distinct_days"] < 2 else "locker"


def locker_limit(identity: sqlite3.Row, q: int, now: int) -> int:
    cls = class_of(identity, now)
    if cls == "probation":
        return CLASSES["probation"]["quota_bytes"]
    return q + (identity["paid_bytes"] if cls == "paid" else 0)
