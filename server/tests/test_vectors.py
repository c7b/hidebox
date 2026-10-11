# SPDX-License-Identifier: MIT
"""S-12 and the exchanged vectors (spec §3.4.8): addresses, the classifier, PoW, HKDF and encodings.

The committed tests/vectors/*.json must equal what make_vectors.py generates from the current code,
so the app builder's copies can't drift from the server's behaviour.
"""
import hashlib
import json
import unittest
from pathlib import Path

import make_vectors
from harness import Stack
from mutis import codec, db, ootle_addr, pow
from mutis.ratelimit import Recent

VECTORS = Path(__file__).parent / "vectors"


def load(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


class Files(unittest.TestCase):
    def test_committed_vectors_match_the_code(self):
        for name, obj in make_vectors.build().items():
            self.assertEqual((VECTORS / name).read_text(encoding="utf-8"), make_vectors.render(obj), name)


class Addresses(unittest.TestCase):
    def test_valid_round_trip(self):
        for v in load("addr.json")["valid"]:
            owner, view, ref = ootle_addr.parse_testnet(v["address"])
            self.assertEqual((owner.hex(), view.hex(), ref.hex()), (v["owner_pk"], v["view_pk"], v["pay_ref"]))
            self.assertEqual(ootle_addr.encode("otl_esm_", owner + view + ref), v["address"])

    def test_invalid(self):
        for v in load("addr.json")["invalid"]:
            with self.assertRaises(ValueError, msg=v["why"]):
                ootle_addr.parse_testnet(v["input"])

    def test_classifier(self):
        for v in load("addr.json")["classify"]:
            self.assertEqual(ootle_addr.classify(v["input"]), v["class"], v["note"])
            self.assertEqual(ootle_addr.ERROR_FOR_CLASS[v["class"]], v["error"])

    def test_emoji_alphabet(self):
        alphabet = ootle_addr.EMOJI_ALPHABET
        self.assertEqual((len(alphabet), len(set(alphabet))), (256, 256))
        self.assertEqual((alphabet[0], alphabet[64], alphabet[182], alphabet[211]), ("🐢", "🎃", "🔒", "🔑"))


class ProofOfWork(unittest.TestCase):
    def test_vectors(self):
        data = load("pow.json")
        k_pow = bytes.fromhex(data["k_pow"])
        for case in data["cases"]:
            challenge = codec.unb64u(case["challenge"])
            nonce = codec.unb64u(case["nonce"])
            self.assertEqual(pow.parse_challenge(k_pow, challenge), (case["purpose"], case["difficulty"],
                                                                     case["expiry"]))
            self.assertTrue(pow.solved(challenge, nonce, case["difficulty"]))
            self.assertEqual(hashlib.sha256(challenge + nonce).hexdigest(), case["digest"])
        bad = data["invalid"]
        with self.assertRaises(pow.PowError):
            pow.parse_challenge(k_pow, codec.unb64u(bad[0]["challenge"]))
        first = data["cases"][0]
        self.assertFalse(pow.solved(codec.unb64u(bad[1]["challenge"]), codec.unb64u(bad[1]["nonce"]),
                                    first["difficulty"]))

    def test_single_use_expiry_and_purpose(self):
        s = Stack()
        try:
            p = pow.Pow(b"k" * 32, base_override=1)
            mine = p.issue("upload", b"ip", s.now)
            challenge = codec.unb64u(mine["challenge"])
            n = 0
            while not pow.solved(challenge, n.to_bytes(8, "big"), 1):
                n += 1
            solution = {"challenge": mine["challenge"], "nonce": codec.b64u(n.to_bytes(8, "big"))}
            with self.assertRaises(pow.PowError):
                p.verify(s.conn, solution, "register", b"ip", s.now)     # wrong purpose
            p.verify(s.conn, solution, "upload", b"ip", s.now)
            with self.assertRaises(pow.PowError):
                p.verify(s.conn, solution, "upload", b"ip", s.now)       # single use
            late = p.issue("upload", b"ip", s.now)
            with self.assertRaises(pow.PowError):
                p.verify(s.conn, {"challenge": late["challenge"], "nonce": "AAAAAAAAAAA"}, "upload", b"ip",
                         s.now + 301)
            other = s.solve("upload")                                    # made with the server's key, not p's
            with self.assertRaises(pow.PowError):
                p.verify(s.conn, other, "upload", b"ip", s.now)
        finally:
            s.close()

    @staticmethod
    def spend(p: pow.Pow, purpose: str, key: bytes, now: int, times: int) -> None:
        """What a verified solution records (the solving itself is tested above)."""
        for _ in range(times):
            p._spent(purpose, key, now)

    def test_escalation_per_ip_key_and_global_cap(self):
        p = pow.Pow(b"k" * 32)
        now = 1_000_000
        self.spend(p, "upload", b"me", now, 5)
        self.assertEqual(p.difficulty("upload", b"me", now), 16)             # at the hourly average (5 / 10 min)
        self.spend(p, "upload", b"me", now, 10)
        self.assertEqual(p.difficulty("upload", b"me", now), 18)             # 15 = 3 × average → +2
        self.spend(p, "upload", b"me", now, 30)
        self.assertEqual(p.difficulty("upload", b"me", now), 20)             # 45 = 9 × average → +4
        self.spend(p, "upload", b"me", now, 4000)
        self.assertEqual(p.difficulty("upload", b"me", now), 24)             # capped at 24
        self.assertEqual(p.difficulty("upload", b"judge", now), 18)          # global +2 only
        self.assertEqual(p.difficulty("register", b"judge", now), 18)        # other purposes untouched
        self.spend(p, "register", b"x", now, 100)
        self.assertEqual(p.difficulty("register", b"judge", now), 20)        # global never above 20
        self.assertEqual(p.difficulty("upload", b"me", now + 601), 16)       # the window moves on

    def test_a_shared_network_retries_at_base_difficulty(self):
        """Review H2: a phone and a laptop behind one IPv4 address, each retrying, stay at the base."""
        p = pow.Pow(b"k" * 32)
        now = 1_000_000
        for purpose, base in (("demo_pay", 18), ("register", 18), ("drop_create", 18), ("sponsor", 18)):
            seen = []
            for _ in range(3):
                seen.append(p.issue(purpose, b"home", now)["difficulty"])
                self.spend(p, purpose, b"home", now, 1)
            seen.append(p.issue(purpose, b"home", now)["difficulty"])
            self.assertEqual(seen, [base] * 4, purpose)

    def test_asking_for_challenges_never_escalates(self):
        p = pow.Pow(b"k" * 32)
        now = 1_000_000
        for _ in range(5000):
            p.issue("upload", b"asker", now)
        self.assertEqual(p.issue("upload", b"asker", now)["difficulty"], 16)
        self.assertEqual(p.issue("upload", b"judge", now)["difficulty"], 16)
        self.assertNotIn(("upload", b"asker"), p._per_key)                 # asking stores nothing per key

    def test_a_real_flood_still_escalates(self):
        p = pow.Pow(b"k" * 32)
        now = 1_000_000
        self.spend(p, "demo_pay", b"flood", now, 9)
        self.assertEqual(p.difficulty("demo_pay", b"flood", now), 20)        # 9 = 3 × the floor of 3
        self.spend(p, "demo_pay", b"flood", now, 18)
        self.assertEqual(p.difficulty("demo_pay", b"flood", now), 22)


class Memory(unittest.TestCase):
    def test_in_memory_tables_are_bounded(self):
        """Review L16: rotating IPv6 addresses can't grow the password and SMALL-lane tables without end."""
        table = Recent(3)
        for i in range(10):
            table.update(i, lambda v: v + 1, 0)
        self.assertEqual([table.get(i) for i in range(10)], [None] * 7 + [1, 1, 1])
        table.update(7, lambda v: v + 1, 0)
        table.update(10, lambda v: v + 1, 0)                 # 8, the least recently written, goes
        self.assertEqual((table.get(7), table.get(8), table.get(10)), (2, None, 1))


class Codec(unittest.TestCase):
    def test_hkdf_rfc5869(self):
        cases = [
            ("0b" * 22, "000102030405060708090a0b0c", "f0f1f2f3f4f5f6f7f8f9", 42,
             "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"),
            ("".join(f"{i:02x}" for i in range(0x00, 0x50)), "".join(f"{i:02x}" for i in range(0x60, 0xb0)),
             "".join(f"{i:02x}" for i in range(0xb0, 0x100)), 82,
             "b11e398dc80327a1c8e7f78c596a49344f012eda2d4efad8a050cc4c19afa97c59045a99cac7827271cb41c65e590e09"
             "da3275600c2f09b8367793a9aca3db71cc30c58179ec3e87c14c01d5c1f3434f1d87"),
            ("0b" * 22, "", "", 42,
             "8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8"),
        ]
        for ikm, salt, info, length, okm in cases:
            self.assertEqual(codec.hkdf(bytes.fromhex(ikm), bytes.fromhex(salt), bytes.fromhex(info), length).hex(),
                             okm)

    def test_b64u_is_strict(self):
        self.assertEqual(codec.unb64u(codec.b64u(b"\xff\xfe")), b"\xff\xfe")
        for bad in ("AA==", "A", "AB", "a+b/", "AAA\n"):
            with self.assertRaises(ValueError, msg=bad):
                codec.unb64u(bad)
        with self.assertRaises(ValueError):
            codec.unb64u(codec.b64u(b"x" * 31), 32)

    def test_ids(self):
        self.assertRegex(codec.new_id(), r"^[A-Za-z0-9_-]{22}$")
        self.assertRegex(codec.drop_id(), r"^[0-9a-hjkmnp-tv-z]{10}$")
        self.assertRegex(codec.invoice_id(), r"^inv_[a-z2-7]{20}$")
        self.assertRegex(codec.report_id(), r"^rep_[a-z2-7]{16}$")

    def test_migrations_apply_in_order(self):
        s = Stack()
        try:
            migrations = s.tmp / "migrations"
            migrations.mkdir()
            following = db.SCHEMA_VERSION + 1
            (migrations / f"{following:03d}_example.sql").write_text("-- SPDX-License-Identifier: MIT\n"
                                                                    "CREATE TABLE example (x INTEGER) STRICT;\n")
            self.assertEqual(db.migrate(s.cfg.db_path, migrations), following)
            self.assertEqual(db.migrate(s.cfg.db_path, migrations), following)
            self.assertIsNotNone(s.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'example'").fetchone())
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
