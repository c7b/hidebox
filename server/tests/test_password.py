# SPDX-License-Identifier: MIT
"""S-06: the online-guessing policy of spec §4.7.

Link + password: only failures that carry a valid link proof count; 5 failures start a doubling pause,
50 lock the link for good. Password only: per (link, IP key) PoW and waiting after 3 failures, a 20-bit
PoW for everyone after 100 failures in a day, and never a permanent lock.
"""
import struct
import unittest

from harness import Stack
from mutis import codec, db, pow as pow_mod

WRONG = {"X-Mutis-Access": codec.b64u(b"\x01" * 32)}


def locker_item(s: Stack) -> dict:
    """A file in a graduated locker, so its links can outlive the hours these tests skip."""
    locker = s.register()
    s.graduate(locker)
    return s.upload(1000, headers=locker["auth"], expires_at=s.now + 30 * 86400)


class LinkPassword(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.item = locker_item(self.s)
        self.link = self.s.share(self.item, mode="link_password", max_views=1, expires_at=self.s.now + 30 * 86400)
        self.path = f"/api/v1/s/{self.link['share_id']}/peek"
        self.proof = {"X-Mutis-Link": self.link["access"]["X-Mutis-Link"]}

    def tearDown(self):
        self.s.close()

    def fails(self) -> int:
        return self.s.conn.execute("SELECT pw_fail_count FROM shares WHERE id = ?",
                                   (self.link["share_id"],)).fetchone()[0]

    def test_missing_link_proof_is_never_counted(self):
        for i in range(60):
            status, _, body = self.s.request("POST", self.path, headers=WRONG, ip=f"192.0.2.{i}")
            self.assertEqual((status, body["error"]["code"]), (403, "bad_link"))
        self.assertEqual(self.fails(), 0)
        status, _, _ = self.s.request("POST", self.path, headers=self.link["access"])
        self.assertEqual(status, 200)

    def test_backoff_then_permanent_lock(self):
        s, headers = self.s, {**self.proof, **WRONG}
        for i in range(1, 5):
            status, _, body = s.request("POST", self.path, headers=headers)
            self.assertEqual((status, body["error"]["details"]["tries_left"]), (403, 5 - i))
        status, _, body = s.request("POST", self.path, headers=headers)      # the 5th failure starts a pause
        self.assertEqual(status, 403)
        status, _, body = s.request("POST", self.path, headers=self.link["access"])
        self.assertEqual((status, body["error"]["code"], body["error"]["retry_after"]), (423, "locked", 60))
        self.assertFalse(body["error"]["details"]["permanent"])
        delays = []
        while self.fails() < 50:
            s.now += 3601
            status, _, _ = s.request("POST", self.path, headers=headers)
            self.assertEqual(status, 403)
            _, _, body = s.request("POST", self.path, headers=self.link["access"])
            if self.fails() < 50:
                delays.append(body["error"]["retry_after"])
        self.assertEqual(delays[:3], [120, 240, 480])
        self.assertEqual(max(delays), 3600)
        s.now += 86400
        status, _, body = s.request("POST", self.path, headers=self.link["access"])
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["permanent"]), (423, "locked", True))
        status, _, _ = s.request("PATCH", f"/api/v1/s/{self.link['share_id']}", {"unlock": True},
                                 headers=self.item["manage"])
        self.assertEqual(status, 200)
        self.assertEqual(s.request("POST", self.path, headers=self.link["access"])[0], 200)


class PasswordOnly(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.item = locker_item(self.s)
        self.link = self.s.share(self.item, mode="password", max_views=5, expires_at=self.s.now + 30 * 86400)
        self.path = f"/api/v1/s/{self.link['share_id']}/peek"

    def tearDown(self):
        self.s.close()

    def test_backoff_and_pow_per_ip_key_never_permanent(self):
        s = self.s
        for _ in range(3):
            self.assertEqual(s.request("POST", self.path, headers=WRONG)[0], 403)
        status, _, body = s.request("POST", self.path, headers=WRONG)
        self.assertEqual((status, body["error"]["code"], body["error"]["retry_after"]), (428, "pow_required", 60))
        s.now += 61
        status, _, body = s.request("POST", self.path, headers=WRONG)
        self.assertEqual((status, body["error"]["code"]), (428, "pow_required"))
        status, _, _ = s.request("POST", self.path, {"pow": s.solve("password")}, headers=WRONG)
        self.assertEqual(status, 403)                         # a counted guess, now with PoW
        status, _, body = s.request("POST", self.path, {"pow": s.solve("password")}, headers=WRONG)
        self.assertEqual((status, body["error"]["retry_after"]), (428, 120))    # 2^(4-3) minutes
        self.assertEqual(s.request("POST", self.path, headers=self.link["access"], ip="198.51.100.9")[0], 200)
        for _ in range(30):
            s.now += 3601
            s.request("POST", self.path, {"pow": s.solve("password")}, headers=WRONG)
        s.now += 3601
        status, _, _ = s.request("POST", self.path, {"pow": s.solve("password")}, headers=self.link["access"])
        self.assertEqual(status, 200)
        locked = s.conn.execute("SELECT pw_locked, pw_fail_count FROM shares WHERE id = ?",
                                (self.link["share_id"],)).fetchone()
        self.assertEqual(tuple(locked), (0, 0))

    def test_busy_day_needs_twenty_bits(self):
        s = self.s
        with db.tx(s.conn):
            s.conn.execute("UPDATE shares SET pw_fails_day = ?, pw_fails_today = 100 WHERE id = ?",
                           (codec.day(s.now), self.link["share_id"]))
        status, _, body = s.request("POST", self.path, headers=self.link["access"], ip="198.51.100.20")
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["difficulty"]),
                         (428, "pow_required", 20))
        status, _, body = s.request("POST", self.path, {"pow": s.solve("password", ip="198.51.100.20")},
                                    headers=self.link["access"], ip="198.51.100.20")
        self.assertEqual((status, body["error"]["code"]), (428, "pow_invalid"))     # a 1-bit solution isn't enough
        _, _, ch = s.request("POST", "/api/v1/pow", {"purpose": "password", "min_difficulty": 20}, ip="198.51.100.20")
        self.assertEqual(ch["difficulty"], 20)
        challenge = codec.unb64u(ch["challenge"])
        n = 0
        while not pow_mod.solved(challenge, struct.pack(">Q", n), 20):
            n += 1
        solution = {"challenge": ch["challenge"], "nonce": codec.b64u(struct.pack(">Q", n))}
        status, _, _ = s.request("POST", self.path, {"pow": solution}, headers=self.link["access"],
                                 ip="198.51.100.20")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
