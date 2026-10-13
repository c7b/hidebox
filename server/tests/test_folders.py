# SPDX-License-Identifier: MIT
"""The drive's folders, moves, renames, the Trash and "Delete it after…" (research 16-drive-design §5, §7,
§15 step 4; annex 16-drive-architecture §2.1, §2.4, §2.6, §4.4).

A folder is an item without ciphertext; a child carries its parent and its key wrapped under the folder's
key (random bytes stand in for both here). The server checks the tree's shape and never sees a name.
"""
import os
import struct
import unittest

from harness import Stack
from mutis import cleanup, codec, db, items, seallog, tree
from mutis.handlers import uploads

V = "/api/v1"


def b64(n: int) -> str:
    return codec.b64u(os.urandom(n))


def folder_header(flags: int = 1, count: int = 0) -> str:
    return codec.b64u(struct.pack(">4sBBHII", b"MTS1", 1, 22, flags, count, 0) + os.urandom(16))


class Drive(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.d = self.s.register()
        self.s.graduate(self.d)

    def tearDown(self):
        self.s.close()

    # --- helpers --------------------------------------------------------------------------------------

    def folder(self, parent: str | None = None, drive: dict | None = None, expect: int = 201, **fields) -> dict:
        body = {"parent_id": parent, "header": folder_header(), "meta_ct": b64(284), "owner_wrap": b64(60),
                "parent_wrap": b64(60) if parent else None, **fields}
        status, _, resp = self.s.request("POST", f"{V}/folders", body, headers=(drive or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return resp

    def file(self, parent: str | None = None, plaintext: int = 1000, drive: dict | None = None) -> dict:
        extra = {"parent_id": parent, "parent_wrap": b64(60)} if parent else {}
        return self.s.upload(plaintext, headers=(drive or self.d)["auth"], retention="kept", owner_wrap=b64(60),
                             **extra)

    def patch(self, item_id: str, body: dict, expect: int = 200) -> dict:
        status, _, resp = self.s.request("PATCH", f"{V}/items/{item_id}", body, headers=self.d["auth"])
        self.assertEqual(status, expect, resp)
        return resp

    def listing(self, query: str = "") -> list[dict]:
        status, _, page = self.s.request("GET", f"{V}/me/items{query}", headers=self.d["auth"])
        self.assertEqual(status, 200, page)
        return page["items"]

    def ids(self, query: str = "") -> set[str]:
        return {i["item_id"] for i in self.listing(query)}

    def sign_in(self) -> None:
        """A new session after weeks of test time (a session lasts 7 idle days)."""
        status, _, body = self.s.request("POST", f"{V}/auth/session", {"identity_id": self.d["id"],
                                                                      "auth_key": codec.b64u(self.d["auth_key"])})
        self.assertEqual(status, 201, body)
        self.d["auth"] = {"Authorization": "Bearer " + body["token"]}

    def me(self) -> dict:
        return self.s.request("GET", f"{V}/me", headers=self.d["auth"])[2]

    def row(self, item_id: str):
        return self.s.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()

    def exit_leaves(self) -> int:
        return self.s.conn.execute("SELECT COUNT(*) FROM seal_leaves WHERE kind = 'exit'").fetchone()[0]

    # --- folders ----------------------------------------------------------------------------------------

    def test_header_flag_rules(self):
        """Flags 1 with no chunks only on POST /folders; flags 0 with chunks only on uploads."""
        for header in (folder_header(flags=0), folder_header(count=1), codec.b64u(b"MTS2" + os.urandom(28))):
            self.assertEqual(self.folder(header=header, expect=422)["error"]["details"]["field"], "header")
        n, size = self.s.layout(1000)
        body = {"retention": "kept", "header": folder_header(count=n), "meta_ct": b64(284), "chunk_count": n,
                "size_stored": size, "owner_wrap": b64(60)}
        status, _, resp = self.s.request("POST", f"{V}/uploads", body, headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["details"]["field"]), (422, "header"))
        self.assertEqual(self.folder(meta_ct=b64(100), expect=422)["error"]["details"]["field"], "meta_ct")
        self.assertEqual(self.folder(owner_wrap=None, expect=422)["error"]["details"]["field"], "owner_wrap")

    def test_create_at_root_and_nested(self):
        top = self.folder()["item_id"]
        inner = self.folder(top)["item_id"]
        doc = self.file(inner)
        self.assertEqual(self.ids("?parent=root"), {top})
        self.assertEqual(self.ids(f"?parent={top}"), {inner})
        self.assertEqual(self.ids(f"?parent={inner}"), {doc["item_id"]})
        self.assertEqual(self.ids(), {top, inner, doc["item_id"]})                 # view=all: flat, as before
        entry = next(i for i in self.listing(f"?parent={top}"))
        self.assertEqual((entry["kind"], entry["parent_id"], entry["size_stored"], entry["chunk_count"]),
                         ("folder", top, 0, 0))
        self.assertEqual(len(codec.unb64u(entry["parent_wrap"])), 60)
        self.assertIsNone(entry["trashed_at"])
        row = self.row(top)
        self.assertEqual((row["retention"], row["lane"], row["ct_hash"], row["state"]), ("kept", "locker", None, "ready"))
        self.assertEqual(self.s.request("GET", f"{V}/me/items?parent={'A' * 22}", headers=self.d["auth"])[0], 404)
        self.assertEqual(self.s.request("GET", f"{V}/me/items?parent={doc['item_id']}", headers=self.d["auth"])[0],
                         404)                                                        # a file isn't a folder
        self.assertEqual(self.s.request("GET", f"{V}/me/items?view=trash&parent=root", headers=self.d["auth"])[0],
                         400)
        self.assertEqual(self.s.request("GET", f"{V}/me/items?view=everything", headers=self.d["auth"])[0], 400)
        me = self.me()
        self.assertEqual((me["files"], me["folders"]), (1, 2))
        self.assertEqual(me["quota"]["used_bytes"], doc["size"])                      # folders count 0 bytes
        status, _, body = self.s.request("POST", f"{V}/me/items/{top}/open", headers=self.d["auth"])
        self.assertEqual((status, body["error"]["code"]), (409, "conflict"))         # nothing to download

    def test_feature_off(self):
        s = Stack({"features": {"folders": False}})
        self.addCleanup(s.close)
        d = s.register()
        status, _, body = s.request("POST", f"{V}/folders", {"parent_id": None, "header": folder_header(),
                                                             "meta_ct": b64(284), "owner_wrap": b64(60)},
                                    headers=d["auth"])
        self.assertEqual((status, body["error"]["code"]), (503, "feature_disabled"))
        for query in ("?view=trash", "?view=gone", "?parent=root"):
            self.assertEqual(s.request("GET", f"{V}/me/items{query}", headers=d["auth"])[0], 503)
        item = s.upload(1000, headers=d["auth"], retention="kept", owner_wrap=b64(60))
        self.assertEqual(s.request("GET", f"{V}/me/items", headers=d["auth"])[2]["items"][0]["item_id"],
                         item["item_id"])                                            # the locker list as today
        status, _, body = s.request("PATCH", f"{V}/items/{item['item_id']}", {"meta_ct": b64(284)},
                                    headers=d["auth"])
        self.assertEqual((status, body["error"]["code"]), (503, "feature_disabled"))

    def test_another_drives_folder_is_forbidden(self):
        other = self.s.register()
        theirs = self.folder(drive=other)["item_id"]
        mine = self.file()
        self.assertEqual(self.folder(theirs, expect=403)["error"]["code"], "forbidden")
        n, size = self.s.layout(1000)
        status, resp = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60),
                                           parent_id=theirs, parent_wrap=b64(60))
        self.assertEqual((status, resp["error"]["code"]), (403, "forbidden"))
        self.assertEqual(self.patch(mine["item_id"], {"parent_id": theirs, "parent_wrap": b64(60)}, 403)
                         ["error"]["code"], "forbidden")
        self.assertEqual(self.patch(theirs, {"meta_ct": b64(284)}, 404)["error"]["code"], "not_found")
        self.assertEqual(self.s.request("DELETE", f"{V}/items/{theirs}", headers=self.d["auth"])[0], 403)
        self.assertEqual(self.folder(mine["item_id"], expect=422)["error"]["details"]["field"], "parent_id")

    def test_depth_limit(self):
        parent = None
        for _ in range(tree.MAX_DEPTH):
            parent = self.folder(parent)["item_id"]
        self.assertEqual(self.folder(parent, expect=409)["error"]["code"], "too_deep")
        self.file(parent)                                     # files don't add depth

    def test_children_and_drive_limits(self):
        self.addCleanup(setattr, tree, "MAX_CHILDREN", tree.MAX_CHILDREN)
        self.addCleanup(setattr, tree, "MAX_ITEMS", tree.MAX_ITEMS)
        tree.MAX_CHILDREN = 2
        top = self.folder()["item_id"]
        self.folder(top)
        self.file(top)
        self.assertEqual(self.folder(top, expect=409)["error"]["code"], "folder_full")
        status, resp = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60),
                                           parent_id=top, parent_wrap=b64(60))
        self.assertEqual((status, resp["error"]["code"]), (409, "folder_full"))
        loose = self.file()
        self.assertEqual(self.patch(loose["item_id"], {"parent_id": top, "parent_wrap": b64(60)}, 409)
                         ["error"]["code"], "folder_full")
        tree.MAX_ITEMS = 4
        self.assertEqual(self.folder(expect=413)["error"]["code"], "too_many")
        status, resp = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60))
        self.assertEqual((status, resp["error"]["code"]), (413, "too_many"))

    def test_move_cycle_and_root(self):
        a = self.folder()["item_id"]
        b = self.folder(a)["item_id"]
        doc = self.file()
        moved = self.patch(doc["item_id"], {"parent_id": b, "parent_wrap": b64(60)})
        self.assertEqual(moved["parent_id"], b)
        self.assertEqual(self.ids(f"?parent={b}"), {doc["item_id"]})
        for target in (a, b):
            self.assertEqual(self.patch(a, {"parent_id": target, "parent_wrap": b64(60)}, 409)["error"]["code"],
                             "cycle")
        self.assertEqual(self.patch(doc["item_id"], {"parent_id": a}, 422)["error"]["details"]["field"],
                         "parent_wrap")
        back = self.patch(doc["item_id"], {"parent_id": None})
        self.assertEqual((back["parent_id"], back["parent_wrap"]), (None, None))
        self.assertEqual(self.patch(doc["item_id"], {"parent_id": None, "parent_wrap": b64(60)}, 422)
                         ["error"]["details"]["field"], "parent_wrap")
        self.assertEqual(self.patch(doc["item_id"], {"name": "x"}, 422)["error"]["details"]["field"], "name")
        self.assertEqual(self.patch(doc["item_id"], {}, 422)["error"]["code"], "invalid")

    def test_move_keeps_the_depth_limit(self):
        parent = None
        for _ in range(tree.MAX_DEPTH - 1):
            parent = self.folder(parent)["item_id"]
        pair = self.folder()["item_id"]
        self.folder(pair)
        self.assertEqual(self.patch(pair, {"parent_id": parent, "parent_wrap": b64(60)}, 409)["error"]["code"],
                         "too_deep")
        single = self.folder()["item_id"]
        self.patch(single, {"parent_id": parent, "parent_wrap": b64(60)})

    def test_rename_keeps_ct_hash_and_the_stored_leaf(self):
        doc = self.file()
        before = self.row(doc["item_id"])
        leaves = self.s.conn.execute("SELECT COUNT(*) FROM seal_leaves").fetchone()[0]
        new_meta = b64(540)
        renamed = self.patch(doc["item_id"], {"meta_ct": new_meta})
        self.assertEqual(renamed["meta_ct"], new_meta)
        after = self.row(doc["item_id"])
        self.assertEqual((after["ct_hash"], after["header"]), (before["ct_hash"], before["header"]))
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM seal_leaves").fetchone()[0], leaves)
        self.assertEqual(self.patch(doc["item_id"], {"meta_ct": b64(100)}, 422)["error"]["details"]["field"],
                         "meta_ct")

    def test_pages_in_a_folder_and_in_the_trash(self):
        top = self.folder()["item_id"]
        made = []
        for _ in range(5):
            made.append(self.file(top)["item_id"])
            self.s.now += 3600
        seen, cursor = [], ""
        while True:
            page = self.s.request("GET", f"{V}/me/items?parent={top}&limit=2" + (f"&cursor={cursor}" if cursor else ""),
                                  headers=self.d["auth"])[2]
            seen += [i["item_id"] for i in page["items"]]
            if page["next"] is None:
                break
            cursor = page["next"]
        self.assertEqual(seen, made[::-1])                                         # newest first
        for item_id in made:
            self.patch(item_id, {"trashed": True})
            self.s.now += 60
        page = self.s.request("GET", f"{V}/me/items?view=trash&limit=3", headers=self.d["auth"])[2]
        rest = self.s.request("GET", f"{V}/me/items?view=trash&limit=3&cursor={page['next']}",
                              headers=self.d["auth"])[2]
        self.assertEqual([i["item_id"] for i in page["items"] + rest["items"]], made[::-1])   # latest put there first
        self.assertIsNone(rest["next"])

    def test_the_public_wall_shows_files_not_folders(self):
        for _ in range(8):
            self.file(self.folder()["item_id"])
        self.s.now += 3 * 3600
        wall = self.s.request("GET", f"{V}/stats/wall")[2]
        self.assertEqual(len(wall["lockers"]), 8)

    # --- the Trash --------------------------------------------------------------------------------------

    def test_trash_ends_links_below_and_still_counts(self):
        top = self.folder()["item_id"]
        doc = self.file(top)
        link = self.s.share(doc, max_views=3, headers=self.d["auth"])
        self.patch(top, {"trashed": True})
        status, _, body = self.s.request("GET", f"{V}/s/{link['share_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "revoked"))
        self.assertEqual(self.ids(), set())                                         # view=all leaves the Trash out
        self.assertEqual(self.ids("?parent=root"), set())
        self.assertEqual(self.ids("?view=trash"), {top})                            # only what was put there
        self.assertEqual(self.ids(f"?parent={top}"), {doc["item_id"]})              # a trashed folder shows its files
        me = self.me()
        self.assertEqual((me["files"], me["folders"], me["quota"]["trash_bytes"], me["quota"]["used_bytes"]),
                         (0, 0, doc["size"], doc["size"]))
        self.assertEqual(self.row(doc["item_id"])["trashed_at"], self.row(top)["trashed_at"])
        # In the Trash nothing changes but a restore.
        self.assertEqual(self.patch(doc["item_id"], {"meta_ct": b64(284)}, 409)["error"]["code"], "trashed")
        self.assertEqual(self.folder(top, expect=409)["error"]["code"], "trashed")
        status, resp = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60),
                                           parent_id=top, parent_wrap=b64(60))
        self.assertEqual((status, resp["error"]["code"]), (409, "trashed"))
        status, _, body = self.s.request("POST", f"{V}/items/{doc['item_id']}/shares",
                                         {"mode": "link", "wrapped_key": b64(60), "access_verifier": b64(32)},
                                         headers=self.d["auth"])
        self.assertEqual((status, body["error"]["code"]), (409, "trashed"))
        self.assertEqual(self.patch(top, {"trashed": True, "meta_ct": b64(284)}, 422)["error"]["code"], "invalid")

    def test_restore(self):
        top = self.folder()["item_id"]
        doc = self.file(top)
        link = self.s.share(doc, max_views=3, headers=self.d["auth"])
        self.s.now += 60
        early = self.file(top)
        self.patch(early["item_id"], {"trashed": True})                            # on its own, first
        self.s.now += 60
        self.patch(top, {"trashed": True})
        self.assertEqual(self.ids("?view=trash"), {top, early["item_id"]})
        restored = self.patch(top, {"trashed": False})
        self.assertIsNone(restored["trashed_at"])
        self.assertEqual(self.ids(f"?parent={top}"), {doc["item_id"]})              # what went in with it
        self.assertEqual(self.ids("?view=trash"), {early["item_id"]})
        self.assertEqual(self.s.request("GET", f"{V}/s/{link['share_id']}")[0], 410)   # links stay ended
        # A file whose folder is in the Trash, or gone, comes back at the root without its wrap.
        self.patch(top, {"trashed": True})
        back = self.patch(doc["item_id"], {"trashed": False})
        self.assertEqual((back["parent_id"], back["parent_wrap"], back["trashed_at"]), (None, None, None))
        self.assertEqual(self.s.request("DELETE", f"{V}/items/{top}", headers=self.d["auth"])[0], 204)
        self.assertEqual(self.row(early["item_id"])["state"], "deleted")            # inside the deleted folder

    def test_trash_empties_after_its_days_with_exit_receipts(self):
        top = self.folder()["item_id"]
        doc = self.file(top)
        self.patch(top, {"trashed": True})
        leaves = self.exit_leaves()
        self.s.now += cleanup.TRASH_DAYS * 86400 - 60
        self.s.run_cleanup()
        self.assertEqual(self.row(doc["item_id"])["state"], "ready")
        self.s.now += 120
        self.assertEqual(self.s.run_cleanup()["trash_emptied"], 2)
        self.assertEqual((self.row(top)["state"], self.row(doc["item_id"])["state"]), ("deleted", "deleted"))
        self.assertFalse(self.s.app.blobs.exists(doc["item_id"]))
        self.assertEqual(self.exit_leaves(), leaves + 1)                            # one per file, none per folder
        self.sign_in()
        me = self.me()
        self.assertEqual((me["quota"]["trash_bytes"], me["quota"]["used_bytes"]), (0, 0))
        gone = {g["item_id"]: g for g in self.listing("?view=gone")}
        self.assertEqual((gone[doc["item_id"]]["reason"], gone[doc["item_id"]]["exit_receipt"]), ("trash", True))
        self.assertEqual((gone[top]["kind"], gone[top]["exit_receipt"]), ("folder", False))

    # --- delete -----------------------------------------------------------------------------------------

    def test_delete_folder_dooms_the_subtree(self):
        top = self.folder()["item_id"]
        inner = self.folder(top)["item_id"]
        files = [self.file(top), self.file(inner, plaintext=400_000)]
        link = self.s.share(files[1], max_views=3, headers=self.d["auth"])
        opened = self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])[2]
        self.assertIsNotNone(opened["ticket"])                                      # a download in progress
        leaves = self.exit_leaves()
        self.assertEqual(self.s.request("DELETE", f"{V}/items/{top}", headers=self.d["auth"])[0], 204)
        self.assertEqual({self.row(i)["state"] for i in (top, inner, files[0]["item_id"])}, {"deleted"})
        self.assertEqual(self.row(files[1]["item_id"])["state"], "doomed")          # leaves when the download ends
        self.assertEqual(self.s.request("GET", f"{V}/s/{link['share_id']}")[2]["error"]["details"]["reason"],
                         "owner_deleted")
        self.s.now += items.TICKET_S + 1
        self.s.run_cleanup()
        self.assertEqual(self.row(files[1]["item_id"])["state"], "deleted")
        self.assertEqual(self.exit_leaves(), leaves + 2)
        self.assertEqual(self.me()["quota"]["used_bytes"], 0)
        self.assertEqual(self.ids(), set())

    def test_gone_lists_what_left_for_the_tombstone_days(self):
        doc = self.file()
        self.assertEqual(self.s.request("DELETE", f"{V}/items/{doc['item_id']}", headers=self.d["auth"])[0], 204)
        gone = self.listing("?view=gone")
        self.assertEqual([(g["item_id"], g["reason"]) for g in gone], [(doc["item_id"], "deleted")])
        self.assertEqual(gone[0]["exit_hour"], codec.floor_hour(self.s.now))
        self.assertEqual(set(gone[0]), {"item_id", "kind", "created_hour", "exit_hour", "reason", "exit_receipt",
                                        "header", "meta_ct", "owner_wrap"})
        self.s.now += cleanup.TOMBSTONE_DAYS * 86400 + 3600
        self.s.run_cleanup()
        self.sign_in()
        self.assertEqual(self.listing("?view=gone"), [])

    def test_takedown_of_a_folder_removes_what_it_holds(self):
        top = self.folder()["item_id"]
        doc = self.file(self.folder(top)["item_id"])
        with db.tx(self.s.conn):
            items.remove(self.s.conn, self.s.app.blobs, top, self.s.now)
        self.assertEqual(self.row(doc["item_id"])["state"], "removed")
        self.assertEqual(self.listing("?view=gone")[0]["reason"], "removed")

    def test_deleting_the_drive_with_folders(self):
        top = self.folder()["item_id"]
        self.file(self.folder(top)["item_id"])
        status = self.s.request("DELETE", f"{V}/me", {"auth_key": codec.b64u(self.d["auth_key"])},
                                headers=self.d["auth"])[0]
        self.assertEqual(status, 204)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM items WHERE owner_id IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(self.s.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    # --- uploads into folders ---------------------------------------------------------------------------

    def test_uploads_with_a_parent_are_validated(self):
        top = self.folder()["item_id"]
        cases = [({"parent_id": top}, "parent_wrap"), ({"parent_wrap": b64(60)}, "parent_wrap"),
                 ({"parent_id": top, "parent_wrap": b64(59)}, "parent_wrap"),
                 ({"parent_id": "short", "parent_wrap": b64(60)}, "parent_id")]
        for extra, field in cases:
            status, resp = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60),
                                               **extra)
            self.assertEqual((status, resp["error"]["details"]["field"]), (422, field), extra)
        status, resp = self.s.start_upload(1000, headers=self.d["auth"], parent_id=top, parent_wrap=b64(60))
        self.assertEqual((status, resp["error"]["details"]["field"]), (422, "parent_id"))   # ephemeral: no folder
        status, resp = self.s.start_upload(1000, parent_id=top, parent_wrap=b64(60))
        self.assertEqual((status, resp["error"]["details"]["field"]), (422, "parent_id"))   # no drive: no folder
        doc = self.file(top)
        row = self.row(doc["item_id"])
        self.assertEqual((row["parent_id"], len(row["parent_wrap"]), row["kind"]), (top, 60, "file"))

    def test_drive_upload_limits(self):
        """Folder uploads need more than the locker's 60 an hour: 600 per drive (100 on its first day),
        1,200 per network; files that aren't kept keep the locker's limits."""
        self.addCleanup(setattr, uploads, "DRIVE_PER_HOUR", uploads.DRIVE_PER_HOUR)
        uploads.DRIVE_PER_HOUR = 2
        for _ in range(2):
            self.assertEqual(self.s.start_upload(1000, headers=self.d["auth"], retention="kept",
                                                 owner_wrap=b64(60))[0], 201)
        status, resp = self.s.start_upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60))
        self.assertEqual((status, resp["error"]["code"]), (429, "rate_limited"))
        self.assertEqual(self.s.start_upload(1000, headers=self.d["auth"])[0], 201)     # an ephemeral file
        self.addCleanup(setattr, uploads, "DRIVE_PER_HOUR_PROBATION", uploads.DRIVE_PER_HOUR_PROBATION)
        uploads.DRIVE_PER_HOUR_PROBATION = 1
        first_day = self.s.register()
        for expect in (201, 429):
            self.assertEqual(self.s.start_upload(1000, headers=first_day["auth"], retention="kept",
                                                 owner_wrap=b64(60))[0], expect)

    # --- Delete it after… -------------------------------------------------------------------------------

    def test_delete_after_dooms_a_kept_file_and_writes_its_exit_leaf(self):
        s = Stack({"features": {"seallog": True}, "ootle": {"seallog_component": "component_" + "ab" * 32}})
        self.addCleanup(s.close)
        d = s.register()
        doc = s.upload(1000, headers=d["auth"], retention="kept", owner_wrap=b64(60))
        link = s.share(doc, max_views=1, headers=d["auth"])
        status, _, entry = s.request("PATCH", f"{V}/items/{doc['item_id']}", {"expires_at": s.now + 86400},
                                     headers=d["auth"])
        self.assertEqual(status, 200, entry)
        self.assertEqual((entry["expires_at"] % 3600, entry["retention"]), (0, "kept"))
        s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])  # its only link ends
        s.run_cleanup()
        self.assertEqual(s.conn.execute("SELECT state FROM items WHERE id = ?", (doc["item_id"],)).fetchone()[0],
                         "ready")                                                    # kept: it stays until the date
        status, _, body = s.request("GET", f"{V}/seallog/proof/{doc['item_id']}?kind=exit")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))
        s.now = entry["expires_at"] + 1
        s.run_cleanup()
        row = s.conn.execute("SELECT state, exit_hour FROM items WHERE id = ?", (doc["item_id"],)).fetchone()
        self.assertEqual(row["state"], "deleted")
        leaf = s.conn.execute("SELECT 1 FROM seal_leaves WHERE kind = 'exit' AND leaf_hash = ?",
                              (seallog.exit_leaf(doc["item_id"], row["exit_hour"]),))
        self.assertIsNotNone(leaf.fetchone())
        gone = s.request("GET", f"{V}/me/items?view=gone", headers=d["auth"])[2]["items"]
        self.assertEqual([(g["item_id"], g["reason"], g["exit_receipt"]) for g in gone],
                         [(doc["item_id"], "expired", True)])
        status, _, body = s.request("GET", f"{V}/seallog/proof/{doc['item_id']}?kind=exit")
        self.assertEqual((status, body["kind"], body["exit_hour"]), (200, "exit", row["exit_hour"]))
        self.assertEqual(s.request("GET", f"{V}/seallog/proof/{doc['item_id']}?kind=both")[0], 400)

    def test_delete_after_limits(self):
        doc = self.file()
        top = self.folder()["item_id"]
        ephemeral = self.s.upload(1000, headers=self.d["auth"])
        too_far = self.s.now + items.MAX_DELETE_AFTER_DAYS * 86400 + 3600
        for item_id, value in ((doc["item_id"], too_far), (doc["item_id"], self.s.now - 1), (top, self.s.now + 3600),
                               (ephemeral["item_id"], self.s.now + 3600), (doc["item_id"], "tomorrow")):
            self.assertEqual(self.patch(item_id, {"expires_at": value}, 422)["error"]["details"]["field"],
                             "expires_at", (item_id, value))
        latest = self.patch(doc["item_id"], {"expires_at": self.s.now + items.MAX_DELETE_AFTER_DAYS * 86400})
        self.assertLessEqual(latest["expires_at"], self.s.now + items.MAX_DELETE_AFTER_DAYS * 86400 + 3600)
        cleared = self.patch(doc["item_id"], {"expires_at": None})
        self.assertIsNone(cleared["expires_at"])
        self.s.now += items.MAX_DELETE_AFTER_DAYS * 86400 + 7200
        self.s.run_cleanup()
        self.assertEqual(self.row(doc["item_id"])["state"], "ready")                 # cleared: it stays

    # --- space ------------------------------------------------------------------------------------------

    def test_lapse_deletes_the_trash_first(self):
        old = self.file(plaintext=300_000)
        self.s.now += 3600
        newer = self.file(plaintext=300_000)
        self.patch(newer["item_id"], {"trashed": True})
        keep = self.file(plaintext=300_000)
        self.folder()
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET paid_until = ? WHERE id = ?",
                                (self.s.now - cleanup.LAPSE_GRACE_DAYS * 86400 - 1, self.d["id"]))
        used = self.me()["quota"]["used_bytes"]
        cleanup.daily(self.s.conn, self.s.app.blobs, used - 1, self.s.now)          # one file over
        self.assertEqual(self.row(newer["item_id"])["state"], "deleted")             # the Trash went first
        self.assertEqual({self.row(i["item_id"])["state"] for i in (old, keep)}, {"ready"})
        self.assertEqual(self.me()["folders"], 1)                                    # folders hold no bytes


if __name__ == "__main__":
    unittest.main()
