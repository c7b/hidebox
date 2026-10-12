# SPDX-License-Identifier: MIT
"""Proof of work: a challenge is bound to the network key it was issued to, and a solution counts only
at the difficulty that key is asked for now, so a stockpile can't skip the escalation (security
review, finding 3)."""
import struct
import tempfile
import unittest
from pathlib import Path

import harness  # noqa: F401  (puts server/ on the path)
from mutis import codec, db, pow

NOW = 1_800_000_000
A, B = b"A" * 8, b"B" * 8


def solve(issued: dict) -> dict:
    challenge = codec.unb64u(issued["challenge"])
    n = 0
    while not pow.solved(challenge, struct.pack(">Q", n), issued["difficulty"]):
        n += 1
    return {"challenge": issued["challenge"], "nonce": codec.b64u(struct.pack(">Q", n))}


class Escalation(unittest.TestCase):
    def setUp(self):
        path = Path(tempfile.mkdtemp(prefix="mutis-pow-")) / "mutis.sqlite3"
        db.migrate(path)
        self.conn = db.connect(path)
        self.addCleanup(self.conn.close)
        self.pow = pow.Pow(b"k" * 32)

    def test_a_challenge_is_bound_to_the_network_it_was_issued_to(self):
        issued = self.pow.issue("report", B, NOW)
        with self.assertRaises(pow.PowError) as e:
            self.pow.verify(self.conn, solve(issued), "report", A, NOW)
        self.assertEqual(e.exception.code, "pow_invalid")
        self.pow.verify(self.conn, solve(issued), "report", B, NOW)      # the network it was issued to, once
        with self.assertRaises(pow.PowError):
            self.pow.verify(self.conn, solve(issued), "report", B, NOW)

    def test_a_stockpile_cant_skip_the_escalation(self):
        base = pow.PURPOSES["report"][1]
        stock = [self.pow.issue("report", A, NOW) for _ in range(2)]
        self.assertEqual([c["difficulty"] for c in stock], [base, base])
        for _ in range(9):                                              # nine solutions in ten minutes: one step up
            self.pow._spent("report", A, NOW)
        self.assertEqual(self.pow.difficulty("report", A, NOW), base + 2)
        self.pow.verify(self.conn, solve(stock[0]), "report", A, NOW)   # within the two-bit slack
        for _ in range(17):                                             # twenty-seven: two steps up
            self.pow._spent("report", A, NOW)
        self.assertEqual(self.pow.difficulty("report", A, NOW), base + 4)
        with self.assertRaises(pow.PowError) as e:
            self.pow.verify(self.conn, solve(stock[1]), "report", A, NOW)
        self.assertEqual((e.exception.code, e.exception.difficulty), ("pow_invalid", base + 4))
        self.assertEqual(self.pow.issue("report", A, NOW)["difficulty"], base + 4)
        self.assertEqual(self.pow.issue("report", B, NOW)["difficulty"], base)   # another network isn't


if __name__ == "__main__":
    unittest.main()
