# SPDX-License-Identifier: MIT
"""Writes tests/vectors/{addr,quota,pow}.json (spec §3.4.8). Deterministic: re-running gives the same bytes.

    python3 -I server/tests/make_vectors.py
The test suite checks that the code still agrees with the committed files.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutis import codec, ootle_addr, pow, quota  # noqa: E402

OUT = Path(__file__).resolve().parent / "vectors"
LIMITS = {"reserve_min_bytes": 10 << 30, "small_lane_bytes": 1 << 30, "drop_lane_bytes": 2 << 30,
          "anon_lane_max_bytes": 6 << 30}
# The 33-emoji example of tari-project/tari base_layer/common_types/src/emoji.rs (commit bf3473b7), BSD-3-Clause.
OFFICIAL_EMOJI_ID = "🌴🦀🔌📌🚑🌰🎓🌴🐊🐌🔒💡🐜📜👛🍵👛🐽🎂🐻🐢🍓👶🐭🐼🏀🎪💔💵🥑🔋🎒🥊"


def key(label: str) -> bytes:
    return hashlib.sha256(b"mutis-vector-" + label.encode()).digest()


def base58_like(seed: str, length: int) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    data = hashlib.sha512(seed.encode()).digest() * 2
    return "".join(alphabet[b % 58] for b in data[:length])


def addr_vectors() -> dict:
    owner, view = key("owner"), key("view")
    base = ootle_addr.encode("otl_esm_", owner + view)
    invoice = ootle_addr.with_pay_ref(base, b"inv_abcdefghijklmnopqrst")
    mainnet = ootle_addr.encode("otl_", owner + view)
    localnet = ootle_addr.encode("otl_loc_", owner + view)
    short = ootle_addr.encode("otl_esm_", owner + view[:16])
    flipped = base[:-1] + ("q" if base[-1] != "q" else "p")
    mixed = base[:12] + base[12:20].upper() + base[20:]
    emoji = list(ootle_addr.EMOJI_ALPHABET)
    cases = [
        (base, "ootle_testnet", "an Esmeralda locker address"),
        (base.upper(), "ootle_testnet", "bech32m allows all-uppercase"),
        (invoice, "ootle_testnet", "an invoice address (pay-ref embedded)"),
        ("  " + base + "\n", "ootle_testnet", "surrounding whitespace is ignored"),
        (mainnet, "ootle_other", "mainnet HRP otl_"),
        (localnet, "ootle_other", "another network's HRP"),
        ("otl_1qqqq", "ootle_other", "otl_ prefix, not Esmeralda, not even valid: still the network message"),
        (flipped, "invalid", "Esmeralda HRP with a bad checksum"),
        (short, "invalid", "payload shorter than 64 bytes"),
        (mixed, "invalid", "mixed case"),
        (OFFICIAL_EMOJI_ID, "l1_emoji", "the official 33-emoji ID example"),
        ("".join(emoji[:20]), "l1_emoji", "20 alphabet emoji"),
        (" ".join(emoji[100:130]), "l1_emoji", "emoji separated by spaces"),
        ("⭐️" * 25, "l1_emoji", "variation selectors are ignored"),
        ("".join(emoji[:19]), "invalid", "only 19 emoji"),
        ("😀" * 30, "invalid", "emoji outside the Tari alphabet"),
        (base58_like("l1", 91), "l1_base58", "base-layer address shape (91 base58 chars)"),
        (base58_like("l1-60", 60), "l1_base58", "60 base58 chars"),
        (base58_like("l1-59", 59), "invalid", "59 chars is too short for an L1 address"),
        ("0" + base58_like("zero", 80), "invalid", "0 is not a base58 character"),
        ("0x" + "ab" * 32, "invalid", "hex"),
        ("hello", "invalid", "text"),
        ("", "invalid", "empty"),
    ]
    return {
        "hrp": "otl_esm_", "network_byte": 38,
        "layout": "bech32m(hrp, owner_pk[32] || view_pk[32] || pay_ref[0..64]); the HRP carries the network",
        "valid": [{"address": base, "owner_pk": owner.hex(), "view_pk": view.hex(), "pay_ref": ""},
                  {"address": invoice, "owner_pk": owner.hex(), "view_pk": view.hex(),
                   "pay_ref": b"inv_abcdefghijklmnopqrst".hex()}],
        "invalid": [{"input": flipped, "why": "bad checksum"}, {"input": short, "why": "too short"},
                    {"input": mainnet, "why": "wrong HRP (mainnet)"}, {"input": mixed, "why": "mixed case"}],
        "classify": [{"input": i, "class": c, "error": ootle_addr.ERROR_FOR_CLASS[c], "note": n} for i, c, n in cases],
        "pending": "Add the owner's real Tari Universe and L1 address samples (spec §0.6) as classify cases.",
    }


def quota_vectors() -> dict:
    gb = 10 ** 9
    cases = []
    for name, d_total, d_avail, stored, paid, n_active in [
        ("99 GB disk, 20 GB used, nothing stored, N=100 (spec §9.2)", 99 * gb, 79 * gb, 0, 0, 0),
        ("same disk, N=300", 99 * gb, 79 * gb, 0, 0, 300),
        ("same disk, N=1000 hits the 256 MiB floor", 99 * gb, 79 * gb, 0, 0, 1000),
        ("2 TB disk, N=100 hits the 5 GiB ceiling", 2000 * gb, 1900 * gb, 0, 0, 0),
        ("99 GB disk with 10 GB stored and 4 GiB rented", 99 * gb, 69 * gb, 10 * gb, 4 << 30, 150),
    ]:
        p = quota.compute(d_total, d_avail, stored, paid, n_active, LIMITS)
        cases.append({"name": name, "in": {"d_total": d_total, "d_avail": d_avail, "stored": stored, "paid": paid,
                                           "n_active": n_active},
                      "out": {"reserve": p.reserve, "pool": p.pool, "anon": p.anon, "free_pool": p.free_pool,
                              "n": p.n, "q_target": p.q_target}})
    padme = [[n, quota.padme(n)] for n in (0, 1, 1000, 1024, 1025, 4097, 1_000_000, 5_000_000, 1 << 22,
                                           (1 << 22) + 1, 1 << 30)]
    stored = [[n, quota.max_stored(n)] for n in (1 << 20, 5 << 20, 25 << 20, 64 << 20, 512 << 20, 2 << 30)]
    smooth = [[q, t, quota.smooth(q, t)] for q, t in ((2 << 30, 3 << 30), (2 << 30, 1 << 30), (2 << 30, 2 << 30))]
    return {"limits": LIMITS, "formula": "spec §9.1–§9.2", "cases": cases, "padme": padme,
            "max_size_stored": stored, "smooth_hourly": smooth}


def pow_vectors() -> dict:
    k_pow = key("k_pow")
    cases = []
    for purpose, bits in (("upload", 8), ("register", 12), ("report", 16)):
        rand = key(purpose)[:12]
        challenge = pow.make_challenge(k_pow, purpose, bits, 1_800_000_000, rand)
        n = 0
        while not pow.solved(challenge, struct.pack(">Q", n), bits):
            n += 1
        nonce = struct.pack(">Q", n)
        cases.append({"purpose": purpose, "difficulty": bits, "expiry": 1_800_000_000, "rand": rand.hex(),
                      "challenge": codec.b64u(challenge), "nonce": codec.b64u(nonce),
                      "digest": hashlib.sha256(challenge + nonce).hexdigest(),
                      "leading_zero_bits": pow.leading_zero_bits(hashlib.sha256(challenge + nonce).digest())})
    first = cases[0]
    tampered = bytearray(codec.unb64u(first["challenge"]))
    tampered[2] = 1      # lower the difficulty byte: the HMAC no longer matches
    return {
        "layout": "ver(1)=1 || purpose(1) || difficulty(1) || 0x00 || u32be(expiry) || rand(12) || "
                  "HMAC-SHA256(k_pow, first 20 bytes)[0:16]; solve SHA-256(challenge || nonce8) >= difficulty "
                  "leading zero bits",
        "purposes": {name: {"code": code, "base_bits": bits} for name, (code, bits) in pow.PURPOSES.items()},
        "k_pow": k_pow.hex(), "cases": cases,
        "invalid": [{"challenge": codec.b64u(bytes(tampered)), "nonce": first["nonce"], "why": "difficulty edited"},
                    {"challenge": first["challenge"], "nonce": codec.b64u(b"\xff" * 8), "why": "nonce doesn't solve"}],
    }


def build() -> dict[str, dict]:
    return {"addr.json": addr_vectors(), "quota.json": quota_vectors(), "pow.json": pow_vectors()}


def render(obj: dict) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, obj in build().items():
        (OUT / name).write_text(render(obj), encoding="utf-8")
        print("wrote", OUT / name)
