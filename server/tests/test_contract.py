# SPDX-License-Identifier: MIT
"""S-02: every endpoint of spec §6.3 answers with the documented shapes and errors."""
import base64
import hashlib
import json
import os
import unittest
from pathlib import Path

from harness import ORIGIN, Stack

import cbor_fixture  # noqa: E402  (harness puts server/ on the path)
from mutis import codec, db, items, ootle_addr, quota
from mutis.fake_chain import FakeChain, FakeIndexer, fake_keys
from mutis.indexer import IndexerError, Indexers

V = "/api/v1"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class System(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Stack()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_health(self):
        status, headers, body = self.s.request("GET", f"{V}/health")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"ok", "version", "time"})
        self.assertTrue(body["ok"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Server", headers)

    def test_config(self):
        status, headers, c = self.s.request("GET", f"{V}/config")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "public, max-age=60")
        for key in ("origin", "memo_origins", "network", "network_byte", "testnet", "send_mode", "amount_proof",
                    "chunk_size", "text_max_chars", "text_max_bytes", "inline_max_stored", "limits", "kdf", "pricing",
                    "features", "courier", "sponsor_grant_ut", "ootle", "security_drop", "repo_url", "judge_demo_gone", "seal_log",
                    "retention", "quota", "password", "invoices", "hosting", "onion"):
            self.assertIn(key, c)
        self.assertEqual(c["origin"], ORIGIN)
        self.assertEqual((c["network"], c["network_byte"], c["testnet"]), ("esmeralda", 38, True))
        self.assertEqual((c["send_mode"], c["amount_proof"]), ("relay", "sidecar"))
        self.assertEqual(c["limits"]["anon"]["max_file_bytes"], 25 << 20)
        self.assertEqual(c["limits"]["anon"]["max_views"], 10)
        self.assertEqual(c["limits"]["drop"], {"max_file_bytes": 25 << 20, "expiry_s": 604800, "views": 3})
        self.assertEqual(c["limits"]["probation"]["quota_bytes"], 64 << 20)
        self.assertEqual(c["limits"]["locker"]["max_file_bytes"], 512 << 20)
        self.assertEqual(c["limits"]["paid"]["max_file_bytes"], 2 << 30)
        self.assertEqual(c["kdf"], {"alg": "PBKDF2-SHA256", "min_iter": 600000, "max_iter": 5000000})
        packs = {p["id"]: p for p in c["pricing"]["packs"]}
        self.assertEqual(packs["s30"], {"id": "s30", "bytes": 2 << 30, "days": 30, "price_ut": "500000"})
        self.assertEqual(packs["m30"]["price_ut"], "2000000")
        self.assertEqual(c["courier"], {"amount_ut": "1000", "max_fee_ut": "30000", "jitter_s": [5, 45]})
        self.assertEqual(c["ootle"]["wasm_version"], "0.46.0")
        self.assertEqual(c["hosting"], {"snapshots": "weekly"})
        self.assertIsNone(c["onion"])
        self.assertEqual(c["retention"]["ticket_s"], 1800)
        self.assertEqual(c["password"]["lock_after"], 5)
        self.assertEqual(c["seal_log"], {"checkpoint_interval_s": 900, "component": None})
        self.assertNotIn("e2e_expiry_s", c)                   # only where the deployment turns it on
        self.assertIsNone(c["judge_demo_gone"])               # until the release burns its demo secret

    def test_e2e_expiry_preset_only_when_configured(self):
        s = Stack({"e2e_expiry_s": 60})
        self.addCleanup(s.close)
        self.assertEqual(s.request("GET", f"{V}/config")[2]["e2e_expiry_s"], 60)
        item = s.upload(1000)
        link = s.share(item, expires_at=s.now + 60)            # the 60-second preset is an ordinary link
        s.now += 61
        status, _, body = s.request("GET", f"{V}/s/{link['share_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "expired"))

    def test_judge_demo_gone(self):
        """14-ghost-design §9: the release's burned demo secret is served for /judges; anything that
        isn't a share id stops the service."""
        from mutis.config import ConfigError, from_dict
        s = Stack({"judge_demo_gone": "A" * 21 + "w"})
        self.addCleanup(s.close)
        self.assertEqual(s.request("GET", f"{V}/config")[2]["judge_demo_gone"], "A" * 21 + "w")
        for bad in ("short", "A" * 23, "A" * 21 + "/", "https://example.com/s/" + "A" * 22):
            with self.assertRaises(ConfigError):
                from_dict({"judge_demo_gone": bad}, dev=True)

    def test_pow(self):
        status, _, body = self.s.request("POST", f"{V}/pow", {"purpose": "upload"})
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"challenge", "difficulty", "expires_at"})
        self.assertEqual(len(body["challenge"]), 48)
        status, _, body = self.s.request("POST", f"{V}/pow", {"purpose": "nope"})
        self.assertEqual((status, body["error"]["code"]), (422, "invalid"))

    def test_stats_and_wall(self):
        status, _, st = self.s.request("GET", f"{V}/stats")
        self.assertEqual(status, 200)
        for key in ("free_quota_bytes", "last_sealed_min", "lockers_active_30d", "disk_used_pct", "uploads_frozen",
                    "chain_ok", "updated_at", "disk_total_bytes", "disk_free_bytes"):
            self.assertIn(key, st)
        self.assertIsNone(st["lockers_active_30d"])
        step = (1 << 30) // 10
        self.assertEqual((st["disk_total_bytes"] % step, st["disk_free_bytes"] % step), (0, 0))   # review M6
        status, headers, wall = self.s.request("GET", f"{V}/stats/wall")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "public, max-age=300")
        self.assertEqual(wall["quiet"], True)
        self.assertEqual(wall["lockers"], [])

    def test_wall_is_shuffled_and_holds_new_items_back(self):
        """Review L3: no newest-first order to pick out a fresh upload, and nothing under an hour old."""
        s = Stack()
        self.addCleanup(s.close)
        for views in (1,) * 8 + (3, 3):
            s.share(s.upload(1000), max_views=views)
        self.assertEqual(s.request("GET", f"{V}/stats/wall")[2]["quiet"], True)
        s.now += 2 * 3600
        orders = set()
        for _ in range(12):
            s.app.cache.clear()
            wall = s.request("GET", f"{V}/stats/wall")[2]
            self.assertEqual(len(wall["lockers"]), 10)
            orders.add(tuple(e["exit"] for e in wall["lockers"]))
        self.assertGreater(len(orders), 1)

    def test_wall_shows_no_opens_and_no_takedowns(self):
        """Site review M15: nothing on the wall says whether or when a link was opened; a takedown (an abuse
        removal, or an E2E run cleaning up after itself) leaves the wall."""
        s = Stack()
        self.addCleanup(s.close)
        uploads = [s.upload(1000) for _ in range(10)]
        links = [s.share(item, max_views=1) for item in uploads]
        s.now += 2 * 3600
        before = s.request("GET", f"{V}/stats/wall")[2]["lockers"]
        for link in links[:5]:
            s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        s.run_cleanup()
        s.app.cache.clear()
        after = s.request("GET", f"{V}/stats/wall")[2]["lockers"]
        self.assertEqual(sorted(map(str, before)), sorted(map(str, after)))
        self.assertEqual({tuple(sorted(e)) for e in after}, {("exit", "size")})
        with db.tx(s.conn):                      # one that already left by its rule, and one still stored
            for item in (uploads[0], uploads[-1]):
                items.remove(s.conn, s.app.blobs, item["item_id"], s.now)
        s.app.cache.clear()
        self.assertEqual(len(s.request("GET", f"{V}/stats/wall")[2]["lockers"]), 8)
        with db.tx(s.conn):
            items.remove(s.conn, s.app.blobs, uploads[1]["item_id"], s.now)
        s.app.cache.clear()
        self.assertEqual(s.request("GET", f"{V}/stats/wall")[2], {"lockers": [], "quiet": True, "canary": None})

    def test_unknown_route_and_malformed_id(self):
        status, _, body = self.s.request("GET", f"{V}/nope")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))
        status, _, body = self.s.request("GET", f"{V}/s/not-an-id")
        self.assertEqual((status, body["error"]["code"]), (400, "bad_request"))


class Uploads(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_anonymous_upload_flow(self):
        n, size = self.s.layout(10 << 20)
        status, up = self.s.start_upload(10 << 20)
        self.assertEqual(status, 201)
        self.assertEqual(set(up), {"upload_id", "item_id", "manage_token", "expires_at"})
        self.assertEqual(len(up["upload_id"]), 22)
        self.s.put_chunks(up["upload_id"], size, n)
        status, _, done = self.s.request("POST", f"{V}/uploads/{up['upload_id']}/complete", {})
        self.assertEqual(status, 200)
        self.assertEqual(set(done), {"item_id", "ct_hash", "size_stored"})
        self.assertEqual(done["size_stored"], size)
        lane = self.s.conn.execute("SELECT lane FROM items WHERE id = ?", (up["item_id"],)).fetchone()[0]
        self.assertEqual(lane, "anon")

    def test_errors(self):
        s = self.s
        status, body = s.start_upload(1000, pow=None)
        self.assertEqual((status, body["error"]["code"]), (428, "pow_required"))
        status, body = s.start_upload(1000, pow={"challenge": "A" * 48, "nonce": "AAAAAAAAAAA"})
        self.assertEqual((status, body["error"]["code"]), (428, "pow_invalid"))
        status, body = s.start_upload(26 << 20)
        self.assertEqual((status, body["error"]["code"]), (413, "too_large"))
        self.assertEqual(body["error"]["details"], {"max_bytes": 25 << 20, "class": "anon"})
        status, body = s.start_upload(1000, size_stored=10)
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["field"]),
                         (422, "invalid", "size_stored"))
        status, body = s.start_upload(1000, expires_at=s.now + 2 * 86400)
        self.assertEqual((status, body["error"]["details"]["field"]), (422, "expires_at"))
        status, body = s.start_upload(1000, drop_id="0000000000")
        self.assertEqual((status, body["error"]["code"]), (404, "drop_not_found"))
        drop = s.drop()
        s.request("DELETE", f"{V}/drops/{drop['drop_id']}", headers=drop["manage"])
        status, body = s.start_upload(1000, drop_id=drop["drop_id"], expires_at=s.now + 604800)
        self.assertEqual((status, body["error"]["code"]), (410, "drop_closed"))
        with db.tx(s.conn):
            db.set_meta(s.conn, "uploads_frozen", "all")
        status, body = s.start_upload(1000)
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]), (503, "uploads_frozen",
                                                                                     {"scope": "all"}))

    def test_chunk_errors_and_complete(self):
        s = self.s
        n, size = s.layout(5 << 20)
        status, up = s.start_upload(5 << 20)
        uid = up["upload_id"]
        status, _, body = s.request("PUT", f"{V}/uploads/{uid}/chunks/9", raw=b"x" * 17)
        self.assertEqual((status, body["error"]["code"]), (400, "bad_index"))
        status, _, body = s.request("PUT", f"{V}/uploads/{uid}/chunks/0", raw=b"x" * 17,
                                    headers={"X-Mutis-Chunk-SHA256": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (400, "bad_length"))
        chunk = os.urandom(quota.chunk_length(size, n, 1))
        status, _, body = s.request("PUT", f"{V}/uploads/{uid}/chunks/1", raw=chunk,
                                    headers={"X-Mutis-Chunk-SHA256": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (422, "hash_mismatch"))
        status, _, body = s.request("POST", f"{V}/uploads/{uid}/complete", {})
        self.assertEqual((status, body["error"]["code"]), (409, "missing_chunks"))
        self.assertEqual(body["error"]["details"]["missing"], [0, 1])
        status, _, body = s.request("PUT", f"{V}/uploads/{'A' * 22}/chunks/0", raw=b"x")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))
        s.put_chunks(uid, size, n)
        self.assertEqual(s.request("POST", f"{V}/uploads/{uid}/complete", {})[0], 200)
        status, _, body = s.request("PUT", f"{V}/uploads/{uid}/chunks/0", raw=chunk)
        self.assertEqual((status, body["error"]["code"]), (409, "already_complete"))

    def test_a_bad_rewrite_of_a_good_chunk_unregisters_it(self):
        """Review L2: the bytes on disk changed, so complete must not accept the earlier hash."""
        s = self.s
        n, size = s.layout(1000)
        status, up = s.start_upload(1000)
        s.put_chunks(up["upload_id"], size, n)
        status, _, body = s.request("PUT", f"{V}/uploads/{up['upload_id']}/chunks/0", raw=os.urandom(size),
                                    headers={"X-Mutis-Chunk-SHA256": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (422, "hash_mismatch"))
        status, _, body = s.request("POST", f"{V}/uploads/{up['upload_id']}/complete", {})
        self.assertEqual((status, body["error"]["details"]["missing"]), (409, [0]))

    def test_upload_expiry_and_abort(self):
        s = self.s
        status, up = s.start_upload(1000)
        s.now += 7201
        status, _, body = s.request("PUT", f"{V}/uploads/{up['upload_id']}/chunks/0", raw=b"x" * 1040,
                                    headers={"X-Mutis-Chunk-SHA256": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (410, "upload_expired"))
        status, up = s.start_upload(1000)
        status, _, _ = s.request("DELETE", f"{V}/uploads/{up['upload_id']}")
        self.assertEqual(status, 204)
        state = s.conn.execute("SELECT state FROM items WHERE id = ?", (up["item_id"],)).fetchone()[0]
        self.assertEqual(state, "deleted")
        self.assertFalse(s.app.blobs.part(up["item_id"]).exists())

    def test_locker_upload_and_quota(self):
        s = self.s
        locker = s.register()
        item = s.upload(1000, headers=locker["auth"], expires_at=s.now + 3600)
        row = s.conn.execute("SELECT lane, owner_id FROM items WHERE id = ?", (item["item_id"],)).fetchone()
        self.assertEqual((row["lane"], row["owner_id"]), ("locker", locker["id"]))
        status, body = s.start_upload(65 << 20, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["class"]),
                         (413, "too_large", "probation"))
        status, body = s.start_upload(40 << 20, headers=locker["auth"])
        self.assertEqual(status, 201)
        status, body = s.start_upload(30 << 20, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (507, "probation_limit"))


class Links(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_expiries_are_whole_hours(self):
        """An expiry at least an hour away is stored rounded up to the hour (an exact one would give the arrival
        second away as expires_at - preset); a link's never passes its item's; the E2E preset stays exact."""
        s = self.s
        whole = lambda at: -(-at // 3600) * 3600   # noqa: E731
        item = s.upload(1000, expires_at=s.now + 7200 + 1234)
        link = s.share(item, expires_at=s.now + 3600 + 5)
        self.assertEqual(link["expires_at"], whole(s.now + 3600 + 5))
        stored = s.conn.execute("SELECT expires_at FROM items WHERE id = ?", (item["item_id"],)).fetchone()[0]
        self.assertEqual(stored % 3600, 0)
        self.assertGreaterEqual(stored, s.now + 7200 + 1234)
        status, _, patched = s.request("PATCH", f"{V}/s/{link['share_id']}", {"expires_at": s.now + 3600},
                                       headers=item["manage"])
        self.assertEqual((status, patched["expires_at"]), (200, whole(s.now + 3600)))
        short = s.share(item, expires_at=s.now + 60)
        self.assertEqual(short["expires_at"], s.now + 60)
        capped = s.share(item, expires_at=stored - 30)
        self.assertEqual(capped["expires_at"], stored)

    def test_a_link_without_an_expiry_takes_the_files_own(self):
        """Security review, finding 6: an anonymous file's default expiry (a day, rounded up to the hour)
        is above the link class's bound plus a minute, so a link that defaults to it was refused."""
        s = self.s
        s.now += 1800                        # off the hour, so the rounding up shows
        item = s.upload(1000)
        file_expiry = s.conn.execute("SELECT expires_at FROM items WHERE id = ?", (item["item_id"],)).fetchone()[0]
        self.assertGreater(file_expiry, s.now + quota.CLASSES["anon"]["max_expiry_s"] + 60)
        link = s.share(item, expires_at=None)
        self.assertEqual(s.conn.execute("SELECT expires_at FROM shares WHERE id = ?", (link["share_id"],)).fetchone()[0],
                         file_expiry)

    def test_create_status_peek_open_once(self):
        s = self.s
        item = s.upload(1000)
        link = s.share(item)
        self.assertEqual(set(link) - {"access", "s"}, {"share_id", "path", "state", "max_views", "expires_at"})
        self.assertEqual(link["path"], f"/s/{link['share_id']}")
        sid = link["share_id"]
        status, _, st = s.request("GET", f"{V}/s/{sid}")
        self.assertEqual((status, st), (200, {"state": "active", "mode": "link", "needs_password": False, "kdf": None}))
        status, _, peek = s.request("POST", f"{V}/s/{sid}/peek", headers=link["access"])
        self.assertEqual(status, 200)
        self.assertEqual(peek["share"]["views_left"], 1)
        self.assertEqual(peek["item"]["owner"], "nobody")
        self.assertEqual(peek["not_known"], ["file_name", "file_type", "file_content", "link_key", "password",
                                             "ip_address_on_disk"])
        status, _, body = s.request("POST", f"{V}/s/{sid}/peek", headers={"X-Mutis-Access": codec.b64u(b"\1" * 32)})
        self.assertEqual((status, body["error"]["code"]), (403, "bad_access"))
        status, _, opened = s.request("POST", f"{V}/s/{sid}/open", headers=link["access"])
        self.assertEqual(status, 200)
        self.assertEqual(set(opened), {"wrapped_key", "header", "meta_ct", "chunk_size", "chunk_count", "size_stored",
                                       "views_left", "burned", "ticket", "ticket_expires_at", "inline_ct"})
        self.assertTrue(opened["burned"])
        self.assertIsNone(opened["ticket"])
        self.assertEqual(codec.unb64u(opened["inline_ct"]), item["blob"])
        status, _, body = s.request("GET", f"{V}/s/{sid}")
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["reason"]), (410, "gone", "burned"))
        self.assertEqual(set(body["error"]["details"]), {"reason", "ended_day"})   # the path holder gets no open count
        status, _, body = s.request("POST", f"{V}/s/{sid}/open", headers=link["access"])
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "burned"))
        row = s.conn.execute("SELECT state, exit_hour FROM items WHERE id = ?", (item["item_id"],)).fetchone()
        self.assertEqual(row["state"], "deleted")          # text-sized: unlinked right after the burn
        self.assertFalse(s.app.blobs.exists(item["item_id"]))
        status, _, body = s.request("GET", f"{V}/s/{'B' * 22}")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))

    def test_ticket_range_download(self):
        s = self.s
        item = s.upload(1 << 20)
        link = s.share(item, max_views=2)
        status, _, opened = s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        self.assertEqual((status, opened["burned"], opened["views_left"]), (200, False, 1))
        ticket = opened["ticket"]
        status, headers, data = s.request("GET", f"{V}/blobs/{ticket}")
        self.assertEqual((status, data), (200, item["blob"]))
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="sealed.bin"')
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        status, headers, data = s.request("GET", f"{V}/blobs/{ticket}", headers={"Range": "bytes=10-19"})
        self.assertEqual((status, data, headers["Content-Range"]), (206, item["blob"][10:20],
                                                                    f"bytes 10-19/{item['size']}"))
        status, _, _ = s.request("GET", f"{V}/blobs/{ticket}", headers={"Range": f"bytes={item['size']}-"})
        self.assertEqual(status, 416)
        s.request("GET", f"{V}/blobs/{ticket}")
        status, _, body = s.request("GET", f"{V}/blobs/{ticket}")
        self.assertEqual((status, body["error"]["code"]), (429, "byte_cap"))
        self.assertEqual(s.request("POST", f"{V}/blobs/{ticket}/done")[0], 204)
        status, _, body = s.request("GET", f"{V}/blobs/{ticket}")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))

    def test_patch_manage_revoke_delete(self):
        s = self.s
        item = s.upload(1000)
        link = s.share(item, max_views=2)
        sid = link["share_id"]
        status, _, body = s.request("PATCH", f"{V}/s/{sid}", {"max_views": 3}, headers=item["manage"])
        self.assertEqual((status, body["max_views"]), (200, 3))
        status, _, body = s.request("PATCH", f"{V}/s/{sid}", {"max_views": 11}, headers=item["manage"])
        self.assertEqual((status, body["error"]["code"]), (422, "invalid"))
        status, _, body = s.request("PATCH", f"{V}/s/{sid}", {"max_views": 3}, headers={})
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))
        s.request("POST", f"{V}/s/{sid}/open", headers=link["access"])
        status, _, body = s.request("PATCH", f"{V}/s/{sid}", {"max_views": 5}, headers=item["manage"])
        self.assertEqual((status, body["error"]["code"]), (409, "already_opened"))
        status, _, body = s.request("PATCH", f"{V}/s/{sid}", {"max_views": 2}, headers=item["manage"])
        self.assertEqual(status, 200)
        status, _, m = s.request("GET", f"{V}/s/{sid}/manage", headers=item["manage"])
        self.assertEqual(status, 200)
        self.assertEqual(m["share"]["views_used"], 1)
        self.assertEqual(m["share"]["first_opened_min"], s.now - s.now % 60)
        status, _, body = s.request("GET", f"{V}/s/{sid}/manage")
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))
        self.assertEqual(s.request("DELETE", f"{V}/s/{sid}", headers=item["manage"])[0], 204)
        status, _, body = s.request("GET", f"{V}/s/{sid}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "revoked"))
        item2 = s.upload(1000)
        link2 = s.share(item2)
        self.assertEqual(s.request("DELETE", f"{V}/items/{item2['item_id']}", headers=item2["manage"])[0], 204)
        status, _, body = s.request("GET", f"{V}/s/{link2['share_id']}")
        self.assertEqual(body["error"]["details"]["reason"], "owner_deleted")

    def test_share_errors_and_class_limits(self):
        s = self.s
        status, up = s.start_upload(1000)
        status, _, body = s.request("POST", f"{V}/items/{up['item_id']}/shares", {
            "mode": "link", "wrapped_key": codec.b64u(b"\0" * 60), "access_verifier": codec.b64u(b"\0" * 32),
            "max_views": 1, "expires_at": None}, headers={"X-Mutis-Manage": up["manage_token"]})
        self.assertEqual((status, body["error"]["code"]), (409, "item_not_ready"))
        item = s.upload(1000)
        base = {"mode": "link", "wrapped_key": codec.b64u(b"\0" * 60), "access_verifier": codec.b64u(b"\0" * 32)}
        for bad in ({"max_views": 11}, {"max_views": None}, {"max_views": 1, "expires_at": s.now + 90000},
                    {"max_views": 1, "kdf": {"alg": "PBKDF2-SHA256", "iter": 600000, "salt": "AAAAAAAAAAAAAAAAAAAAAA"}},
                    {"mode": "password", "max_views": 1}):
            status, _, body = s.request("POST", f"{V}/items/{item['item_id']}/shares", {**base, **bad},
                                        headers=item["manage"])
            self.assertEqual((status, body["error"]["code"]), (422, "invalid"), bad)
        status, _, body = s.request("POST", f"{V}/items/{'C' * 22}/shares", base, headers=item["manage"])
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))
        status, _, body = s.request("POST", f"{V}/items/{item['item_id']}/shares", {**base, "max_views": 1})
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))
        for _ in range(3):
            s.share(item)
        status, _, body = s.request("POST", f"{V}/items/{item['item_id']}/shares", {**base, "max_views": 1},
                                    headers=item["manage"])
        self.assertEqual((status, body["error"]["code"]), (409, "conflict"))

    def test_password_link_status_and_kdf(self):
        s = self.s
        item = s.upload(1000)
        link = s.share(item, mode="link_password")
        status, _, st = s.request("GET", f"{V}/s/{link['share_id']}")
        self.assertEqual((st["mode"], st["needs_password"], st["kdf"]["iter"]), ("link_password", True, 600000))
        status, _, body = s.request("POST", f"{V}/s/{link['share_id']}/peek",
                                    headers={"X-Mutis-Access": link["access"]["X-Mutis-Access"]})
        self.assertEqual((status, body["error"]["code"]), (403, "bad_link"))
        self.assertEqual(s.request("POST", f"{V}/s/{link['share_id']}/peek", headers=link["access"])[0], 200)

    def test_stored_bytes(self):
        s = self.s
        item = s.upload(300 << 10)
        link = s.share(item)
        status, _, data = s.request("GET", f"{V}/s/{link['share_id']}/stored", headers=link["access"])
        self.assertEqual((status, data), (200, item["blob"]))
        status, _, peek = s.request("POST", f"{V}/s/{link['share_id']}/peek", headers=link["access"])
        self.assertEqual(peek["share"]["views_used"], 0)

    def test_adopt(self):
        s = self.s
        locker = s.register()
        item = s.upload(1000)
        status, _, body = s.request("POST", f"{V}/items/{item['item_id']}/adopt", {"expires_at": s.now + 5 * 86400},
                                    headers={**locker["auth"], **item["manage"]})
        self.assertEqual((status, body), (200, {"item_id": item["item_id"], "lane": "locker",
                                                "expires_at": s.now + 5 * 86400}))
        used = s.conn.execute("SELECT used_bytes FROM identities WHERE id = ?", (locker["id"],)).fetchone()[0]
        self.assertEqual(used, item["size"])
        other = s.upload(1000)
        status, _, body = s.request("POST", f"{V}/items/{other['item_id']}/adopt", {"expires_at": s.now + 3600},
                                    headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))

    def test_kept_items(self):
        s = self.s
        locker = s.register()
        item = s.upload(1000, headers=locker["auth"], retention="kept", owner_wrap=codec.b64u(b"\7" * 60))
        status, _, page = s.request("GET", f"{V}/me/items", headers=locker["auth"])
        self.assertEqual(status, 200)
        self.assertEqual([i["item_id"] for i in page["items"]], [item["item_id"]])
        self.assertEqual(page["items"][0]["owner_wrap"], codec.b64u(b"\7" * 60))
        status, _, opened = s.request("POST", f"{V}/me/items/{item['item_id']}/open", headers=locker["auth"])
        self.assertEqual((status, codec.unb64u(opened["inline_ct"])), (200, item["blob"]))

    def test_items_page_cursor(self):
        """Review L11: the cursor names this locker's own last row, not a global row number."""
        s = self.s
        locker = s.register()
        s.graduate(locker)
        made = []
        for hour in range(3):
            for _ in range(2):
                made.append(s.upload(1000, headers=locker["auth"], retention="kept",
                                     owner_wrap=codec.b64u(b"\7" * 60))["item_id"])
            s.now += 3600
        seen, cursor = [], ""
        while True:
            status, _, page = s.request("GET", f"{V}/me/items?limit=4" + (f"&cursor={cursor}" if cursor else ""),
                                        headers=locker["auth"])
            self.assertEqual(status, 200)
            seen += [i["item_id"] for i in page["items"]]
            if page["next"] is None:
                break
            self.assertRegex(page["next"], r"^\d+\.[A-Za-z0-9_-]{22}$")
            cursor = page["next"]
        self.assertEqual(sorted(seen), sorted(made))
        self.assertEqual(seen[:2], sorted(made[4:], reverse=True))           # newest hour first
        self.assertEqual(s.request("GET", f"{V}/me/items?cursor=7", headers=locker["auth"])[0], 400)

    def test_no_server_side_keep(self):
        """Review H4: a recipient can't take over a sender's file; the link ends only on its own rule."""
        s = self.s
        locker = s.register()
        sender = s.upload(1000)
        link = s.share(sender, max_views=1)
        status, _, _ = s.request("POST", f"{V}/s/{link['share_id']}/claim", {"owner_wrap": codec.b64u(b"\5" * 60)},
                                 headers={**locker["auth"], **link["access"]})
        self.assertEqual(status, 404)
        status, _, _ = s.request("POST", f"{V}/items/{sender['item_id']}/claim", {"owner_wrap": codec.b64u(b"\5" * 60)},
                                 headers={**locker["auth"], **link["access"]})
        self.assertEqual(status, 404)
        self.assertEqual(s.request("GET", f"{V}/s/{link['share_id']}/manage", headers=sender["manage"])[0], 200)


class Lockers(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_register_session_me(self):
        s = self.s
        locker = s.register()
        status, _, body = s.request("POST", f"{V}/auth/register", {
            "identity_id": locker["id"], "auth_verifier": codec.b64u(b"\0" * 32), "pow": s.solve("register")})
        self.assertEqual((status, body["error"]["code"]), (409, "identity_exists"))
        status, _, body = s.request("POST", f"{V}/auth/session", {"identity_id": locker["id"],
                                                                  "auth_key": codec.b64u(locker["auth_key"])})
        self.assertEqual((status, set(body)), (201, {"token", "expires_at", "identity_id", "probation"}))
        status, _, body = s.request("POST", f"{V}/auth/session", {"identity_id": locker["id"],
                                                                  "auth_key": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (401, "bad_auth"))
        status, _, body = s.request("POST", f"{V}/auth/session", {"identity_id": "D" * 22,
                                                                  "auth_key": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (404, "unknown_identity"))
        status, _, me = s.request("GET", f"{V}/me", headers=locker["auth"])
        self.assertEqual(status, 200)
        self.assertEqual(set(me), {"identity", "plan", "quota", "limits", "sends_today"})
        self.assertEqual(me["identity"]["probation"], True)
        self.assertEqual(me["quota"]["limit_bytes"], 64 << 20)
        status, _, body = s.request("GET", f"{V}/me")
        self.assertEqual((status, body["error"]["code"]), (401, "auth_required"))
        status, _, body = s.request("GET", f"{V}/me", headers={"Authorization": "Bearer " + codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (401, "invalid_session"))
        s.now += 86400
        status, _, me = s.request("GET", f"{V}/me", headers=locker["auth"])
        self.assertEqual(me["identity"]["probation"], False)
        self.assertEqual(s.request("DELETE", f"{V}/auth/session", headers=locker["auth"])[0], 204)
        self.assertEqual(s.request("GET", f"{V}/me", headers=locker["auth"])[0], 401)

    def test_bundle_and_delete_me(self):
        s = self.s
        locker = s.register()
        self.assertEqual(s.request("GET", f"{V}/me/bundle", headers=locker["auth"])[0], 404)
        self.assertEqual(s.request("PUT", f"{V}/me/bundle", {"bundle_ct": codec.b64u(b"\1" * 100)},
                                   headers=locker["auth"])[0], 204)
        status, _, body = s.request("GET", f"{V}/me/bundle", headers=locker["auth"])
        self.assertEqual((status, body["bundle_ct"]), (200, codec.b64u(b"\1" * 100)))
        item = s.upload(1000, headers=locker["auth"])
        status, _, body = s.request("DELETE", f"{V}/me", {"auth_key": codec.b64u(b"\0" * 32)}, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (401, "bad_auth"))
        status, _, _ = s.request("DELETE", f"{V}/me", {"auth_key": codec.b64u(locker["auth_key"])},
                                 headers=locker["auth"])
        self.assertEqual(status, 204)
        self.assertFalse(s.app.blobs.exists(item["item_id"]))
        self.assertIsNone(s.conn.execute("SELECT 1 FROM identities WHERE id = ?", (locker["id"],)).fetchone())


class Drops(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_drop_lifecycle(self):
        s = self.s
        drop = s.drop("tips for the newsroom")
        self.assertEqual(len(drop["drop_id"]), 10)
        self.assertEqual(drop["url"], f"{ORIGIN}/d/{drop['drop_id']}")
        status, _, body = s.request("GET", f"{V}/drops/{drop['drop_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"drop_id", "state", "address", "tag", "label", "limits", "today"})
        self.assertEqual(body["limits"], {"max_file_bytes": 25 << 20, "expiry_s": 604800, "views": 3})
        self.assertEqual(body["today"], {"left": 50})
        status, _, body = s.request("PATCH", f"{V}/drops/{drop['drop_id']}", {"label": "new"}, headers=drop["manage"])
        self.assertEqual((status, body["label"]), (200, "new"))
        status, _, body = s.request("PATCH", f"{V}/drops/{drop['drop_id']}", {"label": "x"})
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))
        item = s.upload(2000, drop_id=drop["drop_id"], expires_at=s.now + 604800)
        status, _, body = s.request("GET", f"{V}/drops/{drop['drop_id']}")
        self.assertEqual(body["today"], {"left": 49})
        link = s.share(item, max_views=3, expires_at=None)
        self.assertEqual(link["max_views"], 3)
        status, _, body = s.request("PATCH", f"{V}/drops/{drop['drop_id']}", {"state": "closed"},
                                    headers=drop["manage"])
        self.assertEqual((status, body["state"]), (200, "closed"))
        status, _, body = s.request("GET", f"{V}/drops/{drop['drop_id']}")
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]), (410, "drop_closed",
                                                                                     {"reason": "closed"}))
        status, _, body = s.request("GET", f"{V}/drops/zzzzzzzzzz")
        self.assertEqual((status, body["error"]["code"]), (404, "drop_not_found"))

    def test_drop_address_errors(self):
        s = self.s
        manage = codec.b64u(hashlib.sha256(b"m").digest())
        owner, view = os.urandom(32), os.urandom(32)
        for address, code in ((ootle_addr.encode("otl_", owner + view), "mainnet_address"),
                              ("7" * 91, "l1_address"), ("🐢" * 33, "l1_address"), ("hello", "bad_address")):
            status, _, body = s.request("POST", f"{V}/drops", {"address": address, "tag": codec.b64u(b"\0" * 16),
                                                              "label": "", "manage_verifier": manage,
                                                              "pow": s.solve("drop_create")})
            self.assertEqual((status, body["error"]["code"], body["error"]["details"]["field"]),
                             (422, code, "address"))


class CourierAndJobs(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_courier_to_drop_and_address(self):
        s = self.s
        drop = s.drop()
        blob = codec.b64u(os.urandom(125))
        status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                            "blob": blob, "pow": s.solve("courier")})
        self.assertEqual(status, 202)
        self.assertEqual(set(body), {"job_id", "not_before"})
        self.assertTrue(s.now + 5 <= body["not_before"] <= s.now + 45)
        status, _, job = s.request("GET", f"{V}/jobs/{body['job_id']}")
        self.assertEqual((status, job), (200, {"kind": "courier", "state": "queued", "not_before": body["not_before"],
                                               "result": None, "error": None}))
        locker = s.register()
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                            "kind": 4, "blob": blob}, headers=locker["auth"])
        self.assertEqual(status, 202)
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                            "kind": 3, "blob": blob})
        self.assertEqual((status, body["error"]["code"]), (401, "auth_required"))
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": "7" * 91, "kind": 3,
                                                            "blob": blob}, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (422, "l1_address"))
        status, _, body = s.request("POST", f"{V}/courier", {"to": "drop", "drop_id": "zzzzzzzzzz", "kind": 3,
                                                            "blob": blob, "pow": s.solve("courier")})
        self.assertEqual((status, body["error"]["code"]), (404, "drop_not_found"))
        status, _, body = s.request("GET", f"{V}/jobs/{'E' * 22}")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))

    def test_chain_unavailable_and_feature_disabled(self):
        s = self.s
        locker = s.register()
        s.now += 120
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                            "kind": 3, "blob": codec.b64u(os.urandom(125))},
                                    headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (503, "chain_unavailable"))
        with db.tx(s.conn):
            db.set_meta(s.conn, "features", {"relay_send": False})
        s.app._features = (0.0, {})
        s.heartbeat()
        status, _, body = s.request("POST", f"{V}/courier", {"to": "address", "address": fake_keys()["address"],
                                                            "kind": 3, "blob": codec.b64u(os.urandom(125))},
                                    headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (503, "feature_disabled"))


class Payments(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "receiver_address", self.s.receiver["address"])

    def tearDown(self):
        self.s.close()

    def test_invoice_and_demo_pay(self):
        s = self.s
        locker = s.register()
        status, _, inv = s.request("POST", f"{V}/invoices", {"pack": "s30"}, headers=locker["auth"])
        self.assertEqual(status, 201)
        self.assertEqual(set(inv), {"invoice_id", "address", "amount_ut", "expires_at", "status"})
        self.assertEqual((inv["amount_ut"], inv["status"]), ("500000", "pending"))
        ref = ootle_addr.parse_testnet(inv["address"])[2]
        self.assertEqual(ref, inv["invoice_id"].encode())
        self.assertEqual(ootle_addr.base_address(inv["address"]), s.receiver["address"])
        status, _, body = s.request("POST", f"{V}/invoices", {"pack": "x"}, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (422, "unknown_pack"))
        status, _, got = s.request("GET", f"{V}/invoices/{inv['invoice_id']}", headers=locker["auth"])
        self.assertEqual((status, got["status"], got["payments"], got["credited"]), (200, "pending", [], None))
        other = s.register()
        self.assertEqual(s.request("GET", f"{V}/invoices/{inv['invoice_id']}", headers=other["auth"])[0], 404)
        status, _, body = s.request("POST", f"{V}/invoices/{inv['invoice_id']}/demo-pay",
                                    {"pow": s.solve("demo_pay")}, headers=locker["auth"])
        self.assertEqual((status, set(body)), (202, {"job_id"}))

    def test_sold_out_and_sponsor_disabled(self):
        s = self.s
        locker = s.register()
        s.disk.total, s.disk.avail = 20 * (1 << 30), 11 * (1 << 30)
        status, _, body = s.request("POST", f"{V}/invoices", {"pack": "s30"}, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (409, "sold_out"))
        status, _, body = s.request("POST", f"{V}/sponsor", {"wallet_address": fake_keys()["address"]},
                                    headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (503, "feature_disabled"))


class ChainReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Stack()
        cls.tx = cls.s.chain.transfer("sponsor", fake_keys()["address"], 1000, {"Message": "hi"}, 30000)
        with db.tx(cls.s.conn):
            for i, epoch in enumerate((10, 11, 12)):
                cls.s.conn.execute("INSERT INTO chain_utxos(id, nonce, enc, tag, epoch, first_seen) "
                                   "VALUES (?, ?, ?, ?, ?, 0)", (f"utxo_{'01' * 32}_{i:064x}", b"\1" * 32, b"\2" * 80,
                                                                 b"\0\0\0\7", epoch))

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_utxos_and_seq(self):
        status, headers, page = self.s.request("GET", f"{V}/chain/utxos?after=1&limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "public, max-age=5")
        self.assertEqual((page["next"], page["head"], len(page["items"])), (2, 3, 1))
        self.assertEqual(set(page["items"][0]), {"seq", "id", "nonce", "enc", "tag", "epoch"})
        self.assertEqual(page["items"][0]["tag"], "00000007")
        self.assertEqual(self.s.request("GET", f"{V}/chain/seq?epoch=12")[2], {"seq": 2})
        self.assertEqual(self.s.request("GET", f"{V}/chain/utxos?limit=1001")[0], 400)

    def test_proxy_allowlist(self):
        status, _, body = self.s.request("GET", f"{V}/chain/ix/network")
        self.assertEqual((status, body["network"], body["_source"]), (200, "esmeralda", "indexer-1"))
        status, _, body = self.s.request("GET", f"{V}/chain/ix/utxos")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))
        status, _, body = self.s.request("POST", f"{V}/chain/ix/transactions", {"x": 1})
        self.assertEqual((status, body["error"]["code"]), (503, "feature_disabled"))

    def test_submitting_takes_a_locker_session_and_relays_only_our_sends(self):
        """Claims review item 21: the submit proxy is no address-hiding relay for any Esmeralda user.
        It wants a session, and the envelope must be shaped like wallet.js's send() (fixture: real
        envelopes from the official library), fee included; the dry-run path gets the same checks."""
        s = self.s
        with db.tx(s.conn):
            db.set_meta(s.conn, "features", {"direct_send": True})
        s.app._features = (0.0, {})
        self.addCleanup(setattr, s.app, "_features", (0.0, {}))
        self.addCleanup(db.set_meta, s.conn, "features", {})
        envelopes = json.loads((FIXTURES / "stealth-envelopes.json").read_text())
        auth = s.register()["auth"]
        post = lambda body, headers=auth, path="transactions": s.request("POST", f"{V}/chain/ix/{path}", body, headers=headers)
        status, _, body = post({"transaction": envelopes["two_outputs"]}, headers={})
        self.assertEqual((status, body["error"]["code"]), (401, "auth_required"))
        for name in ("one_output", "two_outputs", "two_inputs"):
            status, _, body = post({"transaction": envelopes[name]})
            self.assertEqual((status, set(body)), (200, {"transaction_id", "_source"}), name)
        self.assertEqual(post({"transaction": envelopes["one_output"]}, path="transactions/dry-run")[0], 200)
        refused = {"not an object": {"x": 1}, "a second field": {"transaction": envelopes["one_output"], "x": 1},
                   "not base64": {"transaction": "!!"}, "not CBOR": {"transaction": "AAAA"},
                   "over the size cap": {"transaction": base64.b64encode(b"\x82\x00" + b"\xa0" * 9000).decode()}}
        envelope = cbor_fixture.decode(envelopes["two_inputs"])
        unsigned = envelope[1][0][0][0]
        statement = unsigned[1][0][1][1]
        tampered = {"fee above the limit": (lambda: statement[1][1].__setitem__(0, 30001)),
                    "a third output": (lambda: statement[1][0].append(statement[1][0][0])),
                    "five inputs": (lambda: unsigned[3].extend([unsigned[3][1]] * 3)),
                    "an instruction after the fee phase": (lambda: unsigned[2].append(unsigned[1][1])),
                    "a fourth fee instruction": (lambda: unsigned[1].append(unsigned[1][1])),
                    "another version": (lambda: envelope.__setitem__(0, 1))}
        for name, change in tampered.items():
            fresh = cbor_fixture.decode(envelopes["two_inputs"])
            envelope, unsigned = fresh, fresh[1][0][0][0]
            statement = unsigned[1][0][1][1]
            change()
            refused[name] = {"transaction": base64.b64encode(cbor_fixture.encode(fresh)).decode()}
        for name, body in refused.items():
            status, _, resp = post(body)
            self.assertEqual((status, resp["error"]["code"]), (422, "invalid"), name)
        self.assertEqual(s.request("POST", f"{V}/chain/ix/transactions", headers=auth, raw=b"{" * 13000)[0], 413)
        # Untouched, a re-encoded fixture still passes: the checks read the structure, not the bytes.
        again = base64.b64encode(cbor_fixture.encode(cbor_fixture.decode(envelopes["two_inputs"]))).decode()
        self.assertEqual(post({"transaction": again})[0], 200)

    def test_tx_view(self):
        status, _, view = self.s.request("GET", f"{V}/chain/tx/{self.tx}/view")
        self.assertEqual(status, 200)
        self.assertEqual(view["status"], "Commit")
        self.assertEqual(view["fee_ut"], "30000")
        self.assertEqual(len(view["outputs"]), 2)
        self.assertEqual({o["amount"] for o in view["outputs"]}, {"hidden"})
        self.assertEqual({o["owner"] for o in view["outputs"]}, {"one-time key"})
        self.assertTrue(all(o["sealed_bytes"] for o in view["outputs"]))
        self.assertEqual(self.s.request("GET", f"{V}/chain/tx/{'0' * 64}/view")[0], 404)

    def test_tx_view_reads_each_output_before_calling_it_hidden(self):
        """Review M7: "hidden" only where the output was read and reveals nothing."""
        chain = self.s.chain
        tx = chain.transfer("sponsor", fake_keys()["address"], 5000, None, 30000, promise=4000)
        view = self.s.request("GET", f"{V}/chain/tx/{tx}/view")[2]
        self.assertEqual([(o["amount"], o.get("min_value_ut")) for o in view["outputs"]],
                         [("lower_bound", "4000"), ("hidden", None)])
        tx = chain.transfer("sponsor", fake_keys()["address"], 1000, None, 30000)
        out_id = chain.transfers[-1]["outputs"][0]
        with chain.lock:
            next(o for o in chain.outputs if out_id.endswith(o["commitment"]))["spent"] = True
        first = self.s.request("GET", f"{V}/chain/tx/{tx}/view")[2]["outputs"][0]
        self.assertEqual((first["amount"], first["owner"], first["sealed_bytes"]), ("unknown", "unknown", None))
        with db.tx(self.s.conn):                  # what the mirror recorded while the output was live still counts
            self.s.conn.execute("INSERT INTO chain_utxos(id, nonce, enc, first_seen, promise, viewable, auth) "
                                "VALUES (?, x'00', ?, 0, 0, 0, 'key')", (out_id, b"\0" * 201))
        self.addCleanup(self.s.conn.execute, "DELETE FROM chain_utxos WHERE id = ?", (out_id,))
        self.s.app.cache.clear()
        first = self.s.request("GET", f"{V}/chain/tx/{tx}/view")[2]["outputs"][0]
        self.assertEqual((first["amount"], first["owner"], first["sealed_bytes"]), ("hidden", "one-time key", 201))

    def test_a_committed_transaction_polled_through_the_proxy_is_mirrored(self):
        """Direct mode: a browser polls its own transaction's result through the proxy; once it has
        committed, its outputs are in the mirror without waiting for the indexers' stream."""
        tx = self.s.chain.transfer("sponsor", fake_keys()["address"], 1000, None, 30000)
        outputs = self.s.chain.transfers[-1]["outputs"]
        self.addCleanup(self.s.conn.execute, f"DELETE FROM chain_utxos WHERE id IN ({','.join('?' * len(outputs))})",
                        outputs)
        status, _, body = self.s.request("GET", f"{V}/chain/ix/transactions/{tx}/result")
        self.assertEqual((status, body["result"]["Finalized"]["final_decision"]), (200, "Commit"))
        mirrored = {r[0] for r in self.s.conn.execute("SELECT id FROM chain_utxos")}
        self.assertTrue(set(outputs) <= mirrored)

    def test_tx_view_asks_every_indexer_and_caches_no_miss(self):
        """A transaction committed seconds ago can reach one indexer before the other: the view asks each,
        and "not known yet" isn't cached, so the next request asks again."""
        stale = FakeIndexer(FakeChain())
        self.addCleanup(stale.server_close)
        self.addCleanup(stale.shutdown)
        app, live = self.s.app, self.s.indexer
        self.addCleanup(setattr, app, "indexers", app.indexers)
        app.cache.clear()
        app.indexers = Indexers([stale.url, live.url], rate=1000)
        view = self.s.request("GET", f"{V}/chain/tx/{self.tx}/view")[2]
        self.assertEqual((view["status"], view["_source"]), ("Commit", "indexer-2"))
        app.cache.clear()
        app.indexers = Indexers([stale.url], rate=1000)
        self.assertEqual(self.s.request("GET", f"{V}/chain/tx/{self.tx}/view")[0], 404)
        stale.chain = self.s.chain                # the stale indexer catches up
        self.assertEqual(self.s.request("GET", f"{V}/chain/tx/{self.tx}/view")[0], 200)

    def test_unknown_ids_have_a_budget_of_their_own_and_never_empty_the_send_lane(self):
        """Security review, finding 2: an unknown transaction id costs the indexers up to four calls and
        is never cached, so one network gets ten of them a minute, then a 429 (never a 503), and the
        indexer client submits transactions on a lane no read can empty."""
        s, app = self.s, self.s.app
        self.addCleanup(setattr, app, "indexers", app.indexers)
        app.indexers = Indexers([s.indexer.url], rate=1000)
        ip = "203.0.113.9"
        for i in range(10):
            self.assertEqual(s.request("GET", f"{V}/chain/tx/{i:064x}/view", ip=ip)[0], 404)
        status, _, body = s.request("GET", f"{V}/chain/tx/{10:064x}/view", ip=ip)
        self.assertEqual((status, body["error"]["code"]), (429, "rate_limited"))
        self.assertEqual(s.request("GET", f"{V}/chain/tx/{self.tx}/view", ip="203.0.113.10")[0], 200)
        ix = Indexers([s.indexer.url], rate=5)
        ix.upstreams[0][2]["read"].tokens = -10          # reads owed for seconds to come
        self.assertEqual(ix.call("GET", "/epoch-manager/stats", lane="send")[0], 200)
        with self.assertRaises(IndexerError):
            ix.call("GET", "/epoch-manager/stats")

    def test_tx_view_before_the_receipt_is_filed(self):
        """Indexers file a transaction's receipt minutes after it is final; until then the view comes from
        its result, with the same outputs, fee and epoch."""
        live = self.s.indexer
        self.s.app.cache.clear()
        want = self.s.request("GET", f"{V}/chain/tx/{self.tx}/view")[2]
        self.s.app.cache.clear()
        live.receipts_ready = False
        self.addCleanup(setattr, live, "receipts_ready", True)
        self.assertEqual(self.s.request("GET", f"{V}/chain/tx/{self.tx}/view")[2], want)


class CanaryAbuseSeal(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_canary_absent_then_present(self):
        s = self.s
        self.assertEqual(s.request("GET", f"{V}/canary")[0], 404)
        token = {"X-Mutis-Canary": codec.b64u(s.app.canary_token)}
        item = s.upload(4000, headers=token, expires_at=s.now + 172800 - 60)
        with db.tx(s.conn):
            for k, v in (("canary_item_id", item["item_id"]), ("canary_n", "7"), ("canary_sealed_at", str(s.now))):
                db.set_meta(s.conn, k, v)
        status, headers, c = s.request("GET", f"{V}/canary")
        self.assertEqual(status, 200)
        self.assertEqual(set(c), {"n", "sealed_at", "size_stored", "header", "meta_ct", "ct_hash", "raw",
                                  "delivery_tx", "revealed"})
        self.assertEqual(c["n"], 7)
        status, headers, raw = s.request("GET", f"{V}/canary/raw")
        self.assertEqual((status, raw), (200, item["blob"]))
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="mutis-canary-7.bin"')
        self.assertEqual(headers["Cache-Control"], "public, max-age=60")
        status, _, body = s.request("POST", f"{V}/uploads", {"retention": "ephemeral"},
                                    headers={"X-Mutis-Canary": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))

    def test_abuse(self):
        s = self.s
        item = s.upload(1000)
        link = s.share(item)
        status, _, body = s.request("POST", f"{V}/abuse", {"link": f"{ORIGIN}/s/{link['share_id']}", "category":
                                                          "phishing", "details": "fake bank page", "contact": None,
                                                          "pow": s.solve("report")})
        self.assertEqual(status, 201)
        self.assertRegex(body["report_id"], r"^rep_[a-z2-7]{16}$")
        row = s.conn.execute("SELECT * FROM abuse_reports").fetchone()
        self.assertEqual((row["item_id"], row["included_key"]), (item["item_id"], 0))
        status, _, body = s.request("POST", f"{V}/abuse", {"link": "https://evil.example/s/x", "category": "other",
                                                          "details": "", "pow": s.solve("report")})
        self.assertEqual((status, body["error"]["details"]["field"]), (422, "link"))

    def test_seallog_endpoints(self):
        s = Stack({"features": {"seallog": True}, "ootle": {"seallog_component": "component_" + "ab" * 32}})
        self.addCleanup(s.close)
        item = s.upload(1000)
        status, _, proof = s.request("GET", f"{V}/seallog/proof/{item['item_id']}")
        self.assertEqual(status, 200)
        self.assertEqual((proof["proof"]["pending"], proof["leaf_index"]), (True, None))
        status, _, page = s.request("GET", f"{V}/seallog/checkpoints")
        self.assertEqual((status, page), (200, {"checkpoints": [], "next": None}))
        link = s.share(item)
        self.assertEqual(s.request("GET", f"{V}/s/{link['share_id']}/exit")[0], 409)
        s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        status, _, receipt = s.request("GET", f"{V}/s/{link['share_id']}/exit")
        self.assertEqual((status, receipt["reason"], receipt["item_id"]), (200, "burned", item["item_id"]))
        self.assertEqual(receipt["exit_hour"], s.now - s.now % 3600)
        self.assertEqual((receipt["proof"]["pending"], receipt["leaf_index"]), (True, None))


if __name__ == "__main__":
    unittest.main()
