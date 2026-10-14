# SPDX-License-Identifier: MIT
"""Activity: opens counted per link per UTC hour (research 16-drive-design §6, annex §3.2, claim C40: "We
count opens per hour. We never store who opened it or their IP address.").

`share_opens(share_id, hour, n)` is written in the open's own transaction, listed for the last 168 hours
in /me/items and in full in /s/{id}/manage, and goes with the link's tombstone 30 days after it ends.
"""
import os
import struct
import unittest

from harness import Stack
from mutis import cleanup, codec

V = "/api/v1"


class Opens(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.doc = self.s.upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=codec.b64u(os.urandom(60)))

    def tearDown(self):
        self.s.close()

    def link(self, **rule) -> dict:
        return self.s.share(self.doc, headers=self.d["auth"], **{"max_views": 50, "expires_at": None, **rule})

    def open(self, link: dict, expect: int = 200) -> None:
        status, _, body = self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        self.assertEqual(status, expect, body)

    def sign_in(self) -> None:
        body = self.s.request("POST", f"{V}/auth/session", {"identity_id": self.d["id"],
                                                           "auth_key": codec.b64u(self.d["auth_key"])})[2]
        self.d["auth"] = {"Authorization": "Bearer " + body["token"]}

    def manage(self, link: dict) -> list:
        return self.s.request("GET", f"{V}/s/{link['share_id']}/manage", headers=self.d["auth"])[2]["share"]["opens"]

    def listed(self, link: dict) -> list:
        page = self.s.request("GET", f"{V}/me/items", headers=self.d["auth"])[2]
        return next(s for i in page["items"] for s in i["shares"] if s["id"] == link["share_id"])["opens"]

    def test_counted_per_utc_hour(self):
        link = self.link()
        hour = codec.floor_hour(self.s.now)
        self.open(link)
        self.s.now += 60
        self.open(link)
        self.s.now = hour + 3600 + 5
        self.open(link)
        self.assertEqual(self.manage(link), [[hour, 2], [hour + 3600, 1]])
        self.assertEqual(self.listed(link), [[hour, 2], [hour + 3600, 1]])
        self.assertTrue(all(h % 3600 == 0 for h, _ in self.manage(link)))

    def test_the_drive_lists_a_week_and_manage_all(self):
        link = self.link()
        first = codec.floor_hour(self.s.now)
        self.open(link)
        self.s.now += 200 * 3600
        self.open(link)
        later = codec.floor_hour(self.s.now)
        self.sign_in()                                                       # a session idles out after 7 days
        self.assertEqual(self.manage(link), [[first, 1], [later, 1]])
        self.assertEqual(self.listed(link), [[later, 1]])                    # the last 168 hours

    def test_only_opens_that_happened_count(self):
        link = self.link(max_views=1)
        self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers={"X-Mutis-Access": codec.b64u(b"\1" * 32)})
        self.s.request("POST", f"{V}/s/{link['share_id']}/peek", headers=link["access"])
        self.assertEqual(self.manage(link), [])                             # a wrong key or a peek isn't an open
        self.open(link)
        self.open(link, 410)                                                 # a Once link opens once
        self.assertEqual([n for _, n in self.manage(link)], [1])

    def test_a_folder_visit_counts_as_an_open(self):
        header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 1, 0, 0) + os.urandom(16)
        top = self.s.request("POST", f"{V}/folders", {"parent_id": None, "header": codec.b64u(header),
                                                      "meta_ct": codec.b64u(os.urandom(284)),
                                                      "owner_wrap": codec.b64u(os.urandom(60))},
                             headers=self.d["auth"])[2]["item_id"]
        link = self.s.share({"item_id": top}, headers=self.d["auth"], max_views=3)
        self.open(link)
        self.assertEqual([n for _, n in self.manage(link)], [1])

    def test_an_ended_link_keeps_its_counts_until_its_tombstone_goes(self):
        link = self.link()
        self.open(link)
        self.assertEqual(self.s.request("DELETE", f"{V}/s/{link['share_id']}", headers=self.d["auth"])[0], 204)
        self.assertEqual([n for _, n in self.listed(link)], [1])            # "Closed … (opened once)"
        self.s.now += cleanup.TOMBSTONE_DAYS * 86400 + 60
        self.s.run_cleanup()
        rows = self.s.conn.execute("SELECT COUNT(*) FROM share_opens WHERE share_id = ?",
                                   (link["share_id"],)).fetchone()[0]
        self.assertEqual(rows, 0)                                            # gone with the tombstone

    def test_the_table_holds_a_count_and_nothing_about_who(self):
        columns = [c["name"] for c in self.s.conn.execute("PRAGMA table_info(share_opens)")]
        self.assertEqual(columns, ["share_id", "hour", "n"])
        link = self.link()
        self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers={**link["access"],
                                                                           "User-Agent": "Mozilla/5.0 probe"},
                       ip="203.0.113.9")
        dump = "\n".join(self.s.conn.iterdump())
        for needle in ("203.0.113.9", "Mozilla/5.0 probe"):
            self.assertNotIn(needle, dump)


if __name__ == "__main__":
    unittest.main()
