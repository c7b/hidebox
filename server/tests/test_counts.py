# SPDX-License-Identifier: MIT
"""viral-1 (C60): the two daily counts. A one-off link made without a drive and a new drive each add one to their
UTC day's number when the request says `from_share: true`; anything but a boolean is refused before anything is
written; the table holds the day, which of the two and a count, nothing else; cleanup keeps COUNT_DAYS days; and
`mutis-admin counts` prints them."""
import contextlib
import hashlib
import io
import logging
import os
import secrets
import sqlite3
import unittest

from harness import Stack
from mutis import admin, cleanup, codec, counts, db
from test_admin import toml


def b64(n: int) -> str:
    return codec.b64u(os.urandom(n))


class Counts(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def rows(self) -> dict:
        return {(r["day"], r["kind"]): r["n"] for r in self.s.conn.execute("SELECT * FROM daily_counts")}

    def link(self, item: dict, status: int = 201, headers: dict | None = None, **extra):
        access = codec.hkdf(secrets.token_bytes(32), b"mutis/v1", b"share-access", 32)
        body = {"mode": "link", "wrapped_key": b64(60), "access_verifier": codec.b64u(hashlib.sha256(access).digest()),
                "link_verifier": None, "kdf": None, "max_views": 1, "expires_at": None, **extra}
        got, _, resp = self.s.request("POST", f"/api/v1/items/{item['item_id']}/shares", body, headers=headers or item["manage"])
        self.assertEqual(got, status, resp)
        return resp

    def register(self, status: int = 201, ip: str | None = None, **extra):
        auth_key = secrets.token_bytes(32)
        body = {"identity_id": codec.b64u(secrets.token_bytes(16)), "auth_verifier": codec.b64u(hashlib.sha256(auth_key).digest()),
                "pow": self.s.solve("register", ip), **extra}
        got, _, resp = self.s.request("POST", "/api/v1/auth/register", body, ip=ip)
        self.assertEqual(got, status, resp)
        return resp

    def test_a_one_off_link_from_share_adds_one_to_its_day(self):
        today = codec.day(self.s.now)
        self.link(self.s.upload(), from_share=True)
        self.assertEqual(self.rows(), {(today, "secret_from_share"): 1})
        self.link(self.s.upload(), from_share=True)
        self.link(self.s.upload())                                   # no flag: not counted
        self.link(self.s.upload(), from_share=False)                 # false: not counted
        self.assertEqual(self.rows(), {(today, "secret_from_share"): 2})
        self.s.now += 86400                                          # the next UTC day starts its own row
        self.link(self.s.upload(), from_share=True)
        self.assertEqual(self.rows(), {(today, "secret_from_share"): 2, (codec.day(self.s.now), "secret_from_share"): 1})

    def test_only_a_link_without_a_drive_counts_as_a_secret(self):
        drive = self.s.register()
        kept = self.s.upload(headers=drive["auth"], retention="kept", owner_wrap=b64(60))
        self.link(kept, headers=drive["auth"], from_share=True)      # a drive's own link: never a one-off secret
        self.assertEqual(self.rows(), {})

    def test_a_drive_from_share_adds_one_to_its_day(self):
        today = codec.day(self.s.now)
        self.register(from_share=True)
        self.register()
        self.register(from_share=False)
        self.register(from_share=True)
        self.assertEqual(self.rows(), {(today, "drive_from_share"): 2})

    def test_anything_but_a_boolean_is_refused_and_nothing_is_written(self):
        item = self.s.upload()
        for i, bad in enumerate(("true", 1, 0, None, [], {}, "yes")):
            resp = self.link(item, 422, from_share=bad)
            self.assertEqual(resp["error"]["details"]["field"], "from_share", bad)
            resp = self.register(422, ip=f"10.0.{i}.1", from_share=bad)    # a network each: five drives an hour per /64
            self.assertEqual(resp["error"]["details"]["field"], "from_share", bad)
        self.assertEqual(self.rows(), {})
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0], 0)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM identities").fetchone()[0], 0)

    def test_the_table_holds_the_day_the_kind_and_a_count_and_nothing_else(self):
        cols = [(c["name"], c["type"], c["pk"]) for c in self.s.conn.execute("PRAGMA table_info(daily_counts)")]
        self.assertEqual(cols, [("day", "TEXT", 1), ("kind", "TEXT", 2), ("n", "INTEGER", 0)])
        self.assertEqual(counts.KINDS, ("secret_from_share", "drive_from_share"))
        with self.assertRaises(sqlite3.IntegrityError):              # only the two kinds, and only counts
            with db.tx(self.s.conn):
                self.s.conn.execute("INSERT INTO daily_counts(day, kind, n) VALUES ('2026-10-22', 'opens', 1)")
        with self.assertRaises(ValueError):
            counts.add(self.s.conn, "opens", self.s.now)
        # The create requests leave nothing beside the count: the link row and the drive row are the same as without it.
        self.link(self.s.upload(), from_share=True)
        self.register(from_share=True)
        self.assertEqual(sum(r["n"] for r in self.s.conn.execute("SELECT n FROM daily_counts")), 2)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM daily_counts").fetchone()[0], 2)

    def test_cleanup_keeps_count_days(self):
        old, kept = self.s.now - cleanup.COUNT_DAYS * 86400, self.s.now - (cleanup.COUNT_DAYS - 1) * 86400
        with db.tx(self.s.conn):
            counts.add(self.s.conn, "drive_from_share", old)
            counts.add(self.s.conn, "drive_from_share", kept)
            counts.add(self.s.conn, "secret_from_share", self.s.now)
        self.s.run_cleanup()
        self.assertEqual(set(self.rows()), {(codec.day(kept), "drive_from_share"), (codec.day(self.s.now), "secret_from_share")})
        self.assertEqual(self.s.request("GET", "/api/v1/config")[2]["retention"]["count_days"], cleanup.COUNT_DAYS)

    def test_admin_counts_prints_day_kind_and_n(self):
        path = self.s.tmp / "mutis.toml"
        path.write_text(toml(self.s.cfg.raw))
        now = codec.now()
        with db.tx(self.s.conn):
            for _ in range(3):
                counts.add(self.s.conn, "secret_from_share", now)
            counts.add(self.s.conn, "drive_from_share", now)
            counts.add(self.s.conn, "drive_from_share", now - 40 * 86400)

        def run(*args) -> list[str]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                admin.main(["--config", str(path), "counts", *args])
            logging.getLogger("mutis").handlers.clear()
            return [line.split() for line in out.getvalue().splitlines()]

        today = codec.day(now)
        self.assertEqual(run(), [[today, "secret_from_share", "3"], [today, "drive_from_share", "1"]])
        self.assertEqual(run("--days", "41")[-1], [codec.day(now - 40 * 86400), "drive_from_share", "1"])
        with self.assertRaises(SystemExit):
            run("--days", "0")


if __name__ == "__main__":
    unittest.main()
