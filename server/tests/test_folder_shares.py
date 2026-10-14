# SPDX-License-Identifier: MIT
"""Folder links (research 16-drive-design §5, §15 step 6; annex 16-drive-architecture §2.3, §2.6) and
"Delete it from my drive after" (`then_delete`, design §3).

One open of a folder link is one visit: the tree of what the folder holds (ready, outside the Trash) and a
folder ticket that serves, for 30 minutes and within 3x the tree's bytes, any file that is still inside
the folder when it is asked for. A Once folder link ends after one visit; the files stay in the drive.
"""
import os
import struct
import threading
import unittest

from harness import Stack
from mutis import codec, items, seallog, tree

V = "/api/v1"


def b64(n: int) -> str:
    return codec.b64u(os.urandom(n))


class FolderLinks(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.top = self.folder()
        self.sub = self.folder(self.top)
        self.a = self.file(self.top, 1000)
        self.b = self.file(self.sub, 400_000)
        self.c = self.file(self.top, 2000)
        self.outside = self.file(None, 1000)

    def tearDown(self):
        self.s.close()

    def folder(self, parent: str | None = None) -> str:
        header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 1, 0, 0) + os.urandom(16)
        status, _, resp = self.s.request("POST", f"{V}/folders", {
            "parent_id": parent, "header": codec.b64u(header), "meta_ct": b64(284), "owner_wrap": b64(60),
            "parent_wrap": b64(60) if parent else None}, headers=self.d["auth"])
        self.assertEqual(status, 201, resp)
        return resp["item_id"]

    def file(self, parent: str | None, plaintext: int) -> dict:
        extra = {"parent_id": parent, "parent_wrap": b64(60)} if parent else {}
        return self.s.upload(plaintext, headers=self.d["auth"], retention="kept", owner_wrap=b64(60), **extra)

    def link(self, item_id: str, **rule) -> dict:
        rule = {"max_views": 1, "expires_at": None, **rule}
        return self.s.share({"item_id": item_id}, headers=self.d["auth"], **rule)

    def open(self, link: dict, expect: int = 200) -> dict:
        status, _, body = self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        self.assertEqual(status, expect, body)
        return body

    def fetch(self, ticket: str, item_id: str | None, headers: dict | None = None):
        query = f"?item={item_id}" if item_id is not None else ""
        return self.s.request("GET", f"{V}/blobs/{ticket}{query}", headers=headers)

    def patch(self, item_id: str, body: dict) -> None:
        status, _, resp = self.s.request("PATCH", f"{V}/items/{item_id}", body, headers=self.d["auth"])
        self.assertEqual(status, 200, resp)

    # --- the visit --------------------------------------------------------------------------------------

    def test_open_returns_exactly_the_ready_subtree_outside_the_trash(self):
        trashed = self.file(self.top, 1000)
        self.patch(trashed["item_id"], {"trashed": True})
        doomed = self.file(self.sub, 1000)
        self.s.request("DELETE", f"{V}/items/{doomed['item_id']}", headers=self.d["auth"])
        status, pending = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60),
                                              parent_id=self.top, parent_wrap=b64(60))
        self.assertEqual(status, 201)
        opened = self.open(self.link(self.top))
        self.assertEqual((opened["kind"], opened["size_stored"], opened["chunk_count"]), ("folder", 0, 0))
        self.assertEqual((opened["ticket"], opened["inline_ct"], opened["burned"]), (None, None, True))
        self.assertEqual(len(codec.unb64u(opened["folder_ticket"])), 32)
        self.assertEqual(opened["ticket_expires_at"], self.s.now + items.TICKET_S)
        listed = {e["id"]: e for e in opened["tree"]}
        self.assertEqual(set(listed), {self.sub, self.a["item_id"], self.b["item_id"], self.c["item_id"]})
        self.assertEqual([e["id"] for e in opened["tree"]].index(self.b["item_id"]), 3)    # breadth first
        b = listed[self.b["item_id"]]
        self.assertEqual((b["kind"], b["parent_id"], b["size_stored"], b["chunk_count"]),
                         ("file", self.sub, self.b["size"], self.b["n"]))
        self.assertEqual(set(b), {"id", "kind", "parent_id", "header", "meta_ct", "parent_wrap", "size_stored",
                                  "chunk_count"})
        self.assertEqual(listed[self.sub]["kind"], "folder")
        ticket = self.s.conn.execute("SELECT scope, max_bytes, item_id FROM tickets").fetchone()
        self.assertEqual(tuple(ticket), ("tree", 3 * (self.a["size"] + self.b["size"] + self.c["size"]), self.top))
        self.assertIsNotNone(pending)

    def test_too_many_items_answer_413_before_a_view_is_used(self):
        self.addCleanup(setattr, tree, "MAX_TREE", tree.MAX_TREE)
        tree.MAX_TREE = 3
        link = self.link(self.top)
        self.assertEqual(self.open(link, 413)["error"]["details"], {"max_tree": 3})
        peek = self.s.request("POST", f"{V}/s/{link['share_id']}/peek", headers=link["access"])[2]
        self.assertEqual(peek["share"]["views_left"], 1)
        tree.MAX_TREE = 4
        self.assertEqual(len(self.open(link)["tree"]), 4)

    def test_the_folder_ticket_serves_what_is_inside_and_nothing_else(self):
        ticket = self.open(self.link(self.top, max_views=2))["folder_ticket"]
        status, _, body = self.fetch(ticket, self.b["item_id"])
        self.assertEqual((status, body), (200, self.b["blob"]))
        status, headers, part = self.fetch(ticket, self.b["item_id"], {"Range": "bytes=0-99"})
        self.assertEqual((status, part, headers["Content-Range"]), (206, self.b["blob"][:100],
                                                                    f"bytes 0-99/{self.b['size']}"))
        for other in (self.outside["item_id"], self.top, self.sub, "A" * 22, "not-an-id"):
            status, _, body = self.fetch(ticket, other)
            self.assertEqual((status, body["error"]["code"]), (403, "not_in_folder"), other)
        self.assertEqual(self.fetch(ticket, None)[0], 400)

    def test_a_file_moved_out_mid_visit_is_refused_and_one_moved_in_is_served(self):
        """E-28 (server part): membership is checked when a file is asked for, not when the visit began."""
        ticket = self.open(self.link(self.top, max_views=2))["folder_ticket"]
        self.patch(self.b["item_id"], {"parent_id": None})
        self.assertEqual(self.fetch(ticket, self.b["item_id"])[2]["error"]["code"], "not_in_folder")
        self.patch(self.outside["item_id"], {"parent_id": self.sub, "parent_wrap": b64(60)})
        self.assertEqual(self.fetch(ticket, self.outside["item_id"])[0], 200)
        self.patch(self.a["item_id"], {"trashed": True})
        self.assertEqual(self.fetch(ticket, self.a["item_id"])[2]["error"]["code"], "not_in_folder")
        self.s.request("DELETE", f"{V}/items/{self.c['item_id']}", headers=self.d["auth"])
        self.assertEqual(self.fetch(ticket, self.c["item_id"])[2]["error"]["code"], "not_in_folder")
        self.assertFalse(self.s.app.blobs.exists(self.c["item_id"]))      # a folder visit doesn't hold a file back

    def test_the_byte_cap_counts_across_files(self):
        ticket = self.open(self.link(self.top))["folder_ticket"]
        cap = 3 * (self.a["size"] + self.b["size"] + self.c["size"])
        served = 0
        for _ in range(10):
            status, _, body = self.fetch(ticket, self.b["item_id"])
            if status != 200:
                self.assertEqual((status, body["error"]["code"]), (429, "byte_cap"))
                break
            served += len(body)
        self.assertLessEqual(served, cap)
        self.assertEqual(self.fetch(ticket, self.a["item_id"])[0], 200)    # what's left of the cap still serves
        self.assertEqual(self.s.request("POST", f"{V}/blobs/{ticket}/done")[0], 204)
        self.assertEqual(self.fetch(ticket, self.a["item_id"])[0], 404)

    def test_a_visit_counts_each_files_daily_egress_as_it_is_served(self):
        """A folder bigger than a file's daily egress still opens; each file is counted as it is taken."""
        self.addCleanup(setattr, items, "EGRESS_PER_ITEM_DAY", items.EGRESS_PER_ITEM_DAY)
        items.EGRESS_PER_ITEM_DAY = self.b["size"] + 10
        ticket = self.open(self.link(self.top))["folder_ticket"]
        self.assertEqual(self.fetch(ticket, self.b["item_id"])[0], 200)
        status, headers, body = self.fetch(ticket, self.b["item_id"])
        self.assertEqual((status, body["error"]["code"]), (429, "rate_limited"))
        self.assertIn("Retry-After", headers)
        self.assertEqual(self.fetch(ticket, self.a["item_id"])[0], 200)
        served = self.s.conn.execute("SELECT bytes_served FROM tickets").fetchone()[0]
        self.assertEqual(served, self.b["size"] + self.a["size"])           # a refused read costs no cap

    def test_a_file_ticket_serves_only_its_file(self):
        big = self.file(None, 400_000)
        ticket = self.open(self.link(big["item_id"]))["ticket"]
        self.assertEqual(self.fetch(ticket, self.a["item_id"])[2]["error"]["code"], "not_in_folder")
        self.assertEqual(self.fetch(ticket, big["item_id"])[0], 200)
        self.assertEqual(self.fetch(ticket, None)[0], 200)

    def test_five_concurrent_opens_of_a_once_folder_make_one_visit(self):
        link = self.link(self.top)
        results = []

        def go():
            results.append(self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])[0])
        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [200, 410, 410, 410, 410])
        status, _, body = self.s.request("GET", f"{V}/s/{link['share_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "burned"))
        states = {self.s.conn.execute("SELECT state FROM items WHERE id = ?", (i,)).fetchone()[0]
                  for i in (self.top, self.a["item_id"], self.b["item_id"])}
        self.assertEqual(states, {"ready"})                                  # Once never deletes the files

    def test_a_folder_with_a_secret_word(self):
        link = self.link(self.top, mode="link_password", max_views=3)
        self.assertEqual(self.s.request("POST", f"{V}/s/{link['share_id']}/open",
                                        headers={"X-Mutis-Access": link["access"]["X-Mutis-Access"]})[0], 403)
        self.assertEqual(len(self.open(link)["tree"]), 4)

    def test_peek_says_folder_and_how_many_without_a_view(self):
        link = self.link(self.top)
        status, _, st = self.s.request("GET", f"{V}/s/{link['share_id']}")
        self.assertNotIn("kind", st)                                         # the path alone doesn't say
        peek = self.s.request("POST", f"{V}/s/{link['share_id']}/peek", headers=link["access"])[2]
        self.assertEqual((peek["item"]["kind"], peek["item"]["child_count"], peek["share"]["views_left"]),
                         ("folder", 4, 1))
        status, _, body = self.s.request("GET", f"{V}/s/{link['share_id']}/stored", headers=link["access"])
        self.assertEqual((status, body["error"]["code"]), (409, "conflict"))
        manage = self.s.request("GET", f"{V}/s/{link['share_id']}/manage", headers=self.d["auth"])[2]
        self.assertEqual((manage["item"]["kind"], manage["item"]["child_count"]), ("folder", 4))

    def test_links_of_a_trashed_folder_end_and_new_ones_are_refused(self):
        link = self.link(self.top, max_views=3)
        self.patch(self.top, {"trashed": True})
        self.assertEqual(self.open(link, 410)["error"]["details"]["reason"], "revoked")
        status, _, body = self.s.request("POST", f"{V}/items/{self.top}/shares",
                                         {"mode": "link", "wrapped_key": b64(60), "access_verifier": b64(32)},
                                         headers=self.d["auth"])
        self.assertEqual((status, body["error"]["code"]), (409, "trashed"))


class ThenDelete(unittest.TestCase):
    """"Delete it from my drive after" (C42): the file leaves with its link and gets its exit receipt."""

    def setUp(self):
        self.s = Stack()
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.doc = self.s.upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60))

    def tearDown(self):
        self.s.close()

    def share(self, item_id: str, expect: int = 201, **body) -> dict:
        s = os.urandom(32)
        access = codec.hkdf(s, b"mutis/v1", b"share-access", 32)
        payload = {"mode": "link", "wrapped_key": b64(60), "access_verifier": codec.b64u(codec.sha256(access)),
                   **body}
        status, _, resp = self.s.request("POST", f"{V}/items/{item_id}/shares", payload, headers=self.d["auth"])
        self.assertEqual(status, expect, resp)
        return {**resp, "access": {"X-Mutis-Access": codec.b64u(access)}}

    def row(self):
        return self.s.conn.execute("SELECT * FROM items WHERE id = ?", (self.doc["item_id"],)).fetchone()

    def test_the_file_leaves_with_its_once_link(self):
        link = self.share(self.doc["item_id"], max_views=1, expires_at=self.s.now + 86400, then_delete=True)
        self.assertEqual(link["item_expires_at"], link["expires_at"])
        row = self.row()
        self.assertEqual((row["retention"], row["expires_at"]), ("ephemeral", link["expires_at"]))
        opened = self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])[2]
        self.assertTrue(opened["burned"])
        row = self.row()
        self.assertEqual(row["state"], "deleted")                           # inline: gone with the open
        leaf = seallog.exit_leaf(self.doc["item_id"], row["exit_hour"])
        self.assertIsNotNone(self.s.conn.execute("SELECT 1 FROM seal_leaves WHERE kind = 'exit' AND leaf_hash = ?",
                                                 (leaf,)).fetchone())
        gone = self.s.request("GET", f"{V}/me/items?view=gone", headers=self.d["auth"])[2]["items"]
        self.assertEqual([(g["item_id"], g["reason"]) for g in gone], [(self.doc["item_id"], "link_ended")])

    def test_it_leaves_at_the_links_end_even_unopened(self):
        link = self.share(self.doc["item_id"], max_views=3, expires_at=self.s.now + 86400, then_delete=True)
        self.s.now = link["expires_at"] + 1
        self.s.run_cleanup()
        self.assertEqual(self.row()["state"], "deleted")

    def test_another_live_link_keeps_it_until_the_date(self):
        other = self.share(self.doc["item_id"], max_views=5)                 # a kept file's link with no end
        once = self.share(self.doc["item_id"], max_views=1, expires_at=self.s.now + 7200, then_delete=True)
        self.s.request("POST", f"{V}/s/{once['share_id']}/open", headers=once["access"])
        self.s.run_cleanup()
        self.assertEqual(self.row()["state"], "ready")
        self.s.now = once["expires_at"] + 1
        self.s.run_cleanup()
        self.assertEqual(self.row()["state"], "deleted")
        status, _, body = self.s.request("GET", f"{V}/s/{other['share_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "expired"))

    def test_rules(self):
        header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 1, 0, 0) + os.urandom(16)
        top = self.s.request("POST", f"{V}/folders", {"parent_id": None, "header": codec.b64u(header),
                                                      "meta_ct": b64(284), "owner_wrap": b64(60)},
                             headers=self.d["auth"])[2]["item_id"]
        for item_id, body in ((top, {"max_views": 1, "expires_at": self.s.now + 3600}),     # not on folders
                              (self.doc["item_id"], {"max_views": 1})):                # "When I stop it": no end
            resp = self.share(item_id, 422, then_delete=True, **body)
            self.assertEqual(resp["error"]["details"]["field"], "then_delete")
        self.assertEqual(self.share(self.doc["item_id"], 422, then_delete="yes", max_views=1)["error"]["details"]
                         ["field"], "then_delete")
        anon = self.s.upload(1000)
        status, _, resp = self.s.request("POST", f"{V}/items/{anon['item_id']}/shares", {
            "mode": "link", "wrapped_key": b64(60), "access_verifier": b64(32), "max_views": 1,
            "expires_at": self.s.now + 3600, "then_delete": True}, headers=anon["manage"])
        self.assertEqual((status, resp["error"]["details"]["field"]), (422, "then_delete"))
        self.assertEqual(self.row()["retention"], "kept")                   # nothing changed


if __name__ == "__main__":
    unittest.main()
