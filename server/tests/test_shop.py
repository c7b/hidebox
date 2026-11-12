# SPDX-License-Identifier: MIT
"""A drive's shop (docs/shop.md, server/mutis/shop.py), behind features.shop: off by default; turning it on, the title
and bio checked as plain text, a random public id; listing the drive's own pay links (only those, with what our
server already knew filled in by our server); the public page, cached a minute, that shows what sells now; a listing
hidden while its link is paused and gone once the link ends (stopped, deleted, the Trash, its file leaving); unlist,
turn off; the limits; a report of a shop and its takedown; and a buy through a listing's pointer, on the fake chain."""
import contextlib
import io
import logging
import re

from harness import Stack
from paid_fixture import V, PaidCase, b64
from mutis import admin, codec, db, shop
from mutis.fake_chain import fake_keys
from test_admin import toml

ON = {"features": {"shop": True}}


class ShopCase(PaidCase):
    chain = False

    def setUp(self):
        self.s = Stack(ON, chain=self.chain)
        self.s.quiet_chain()
        if self.chain:
            self.s.worker.setup()
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.sales_keys = fake_keys()
        self.ready_seller()

    def open_shop(self, title="Mila's prints", bio="Prints and zines.\nNew ones each month.", d=None, expect=201,
                  key_wrap=None) -> dict:
        body = {"title": title, "bio": bio, "key_wrap": key_wrap or b64(60)}
        status, _, resp = self.s.request("PUT", f"{V}/me/shop", body, headers=(d or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return resp.get("shop", resp)

    def mine(self, d=None) -> dict | None:
        status, _, resp = self.s.request("GET", f"{V}/me/shop", headers=(d or self.d)["auth"])
        self.assertEqual(status, 200, resp)
        return resp["shop"]

    def list_(self, share_id: str, title="Zine no. 3", description="Twelve pages, scanned.", expect=201, d=None,
              link_ct=None) -> dict:
        status, _, resp = self.s.request("PUT", f"{V}/me/shop/listings/{share_id}", {
            "title": title, "description": description, "link_ct": link_ct or b64(60)}, headers=(d or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return resp

    def public(self, shop_id: str, expect=200, ip=None):
        status, headers, resp = self.s.request("GET", f"{V}/shop/{shop_id}", ip=ip)
        self.assertEqual(status, expect, resp)
        return resp, headers

    def titles(self, shop_id: str) -> list:
        return [x["title"] for x in self.public(shop_id)[0]["items"]]


class FeatureFlag(PaidCase):
    chain = False

    def test_off_by_default_everywhere(self):
        self.assertIs(self.s.request("GET", f"{V}/config")[2]["features"]["shop"], False)
        for method, path in (("GET", "/me/shop"), ("PUT", "/me/shop"), ("DELETE", "/me/shop"),
                             ("PUT", "/me/shop/listings/" + "A" * 22), ("GET", "/shop/" + "A" * 22)):
            status, _, resp = self.s.request(method, V + path, {"title": "x"} if method == "PUT" else None,
                                             headers=self.d["auth"])
            self.assertEqual((status, resp["error"]["code"], resp["error"]["details"]), (503, "feature_disabled",
                                                                                         {"feature": "shop"}), path)

    def test_it_needs_pay_to_open_too(self):
        self.s.close()
        self.s = Stack({"features": {"shop": True, "pay_to_open": False}})
        d = self.s.register()
        status, _, resp = self.s.request("GET", f"{V}/me/shop", headers=d["auth"])
        self.assertEqual((status, resp["error"]["details"]), (503, {"feature": "pay_to_open"}))


class TurnOn(ShopCase):
    def test_on_with_a_random_id_and_what_config_publishes(self):
        self.assertIsNone(self.mine())
        made = self.open_shop()
        self.assertRegex(made["shop_id"], r"^[A-Za-z0-9_-]{22}$")
        self.assertEqual(made["path"], f"/shop/{made['shop_id']}")
        self.assertNotEqual(made["shop_id"], self.d["id"])
        self.assertNotIn(self.d["id"], made["shop_id"])
        self.assertEqual((made["title"], made["bio"], made["state"], made["listings"]),
                         ("Mila's prints", "Prints and zines.\nNew ones each month.", "open", []))
        cfg = self.s.request("GET", f"{V}/config")[2]
        self.assertIs(cfg["features"]["shop"], True)
        self.assertEqual(cfg["shop"], shop.config_block())
        page, headers = self.public(made["shop_id"])
        self.assertEqual(page, {"title": "Mila's prints", "bio": "Prints and zines.\nNew ones each month.", "items": []})
        self.assertEqual(headers["Cache-Control"], "public, max-age=60")
        # Off and on again: a new id and a new key, the old address answers 404.
        self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 204)
        self.public(made["shop_id"], expect=404)
        again = self.open_shop()
        self.assertNotEqual(again["shop_id"], made["shop_id"])

    def test_two_drives_get_unrelated_ids(self):
        other = self.s.register()
        a, b = self.open_shop()["shop_id"], self.open_shop(d=other)["shop_id"]
        self.assertNotEqual(a, b)
        rows = self.s.conn.execute("SELECT id, identity_id FROM shops").fetchall()
        self.assertTrue(all(r["id"] != r["identity_id"] for r in rows))

    def test_title_and_bio_change_and_the_key_stays(self):
        made = self.open_shop()
        key = made["key_wrap"]
        changed = self.open_shop(title="  Mila  ", bio="", key_wrap=key, expect=200)
        self.assertEqual((changed["shop_id"], changed["title"], changed["bio"], changed["key_wrap"]),
                         (made["shop_id"], "Mila", "", key))
        self.assertEqual(self.s.request("PUT", f"{V}/me/shop", {"title": "Mila"}, headers=self.d["auth"])[0], 200)
        self.assertEqual(self.open_shop(key_wrap=b64(60), expect=409)["error"]["code"], "conflict")

    def test_plain_text_only(self):
        status, _, resp = self.s.request("PUT", f"{V}/me/shop", {"title": "A shop"}, headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["details"]), (422, {"field": "key_wrap"}))   # a new shop needs its key
        bad = [{"title": ""}, {"title": "   "}, {"title": "x" * (shop.TITLE_MAX + 1)}, {"title": "a\nb"},
               {"title": "a\u202eb"}, {"title": "a\x00b"}, {"title": "a\x85b"}, {"title": 5},
               {"title": "ok", "bio": "x" * (shop.BIO_MAX + 1)}, {"title": "ok", "bio": "1\n2\n3\n4\n5"},
               {"title": "ok", "bio": "tab\there"}, {"title": "ok", "bio": "\u2066hidden\u2069"},
               {"title": "a\u200fb"}, {"title": "a\ud800b"}, {"title": "ok", "bio": "\udfff"},
               {"title": "ok", "key_wrap": b64(59)}]
        for fields in bad:
            body = {"key_wrap": b64(60), **fields}
            self.assertEqual(self.s.request("PUT", f"{V}/me/shop", body, headers=self.d["auth"])[0], 422, fields)
        self.assertEqual(self.s.request("PUT", f"{V}/me/shop", {"title": "x", "key_wrap": b64(60)})[0], 401)
        made = self.open_shop(title="Émile's 🌸 shop", bio="Line one\nLine two")
        self.assertEqual(made["title"], "Émile's 🌸 shop")

    def test_puts_are_limited_per_drive(self):
        key = self.open_shop()["key_wrap"]
        for _ in range(shop.PUTS_PER_DAY - 1):
            self.open_shop(key_wrap=key, expect=200)
        self.assertEqual(self.open_shop(key_wrap=key, expect=429)["error"]["code"], "rate_limited")

    def test_the_public_page_is_rate_limited_per_network(self):
        sid = self.open_shop()["shop_id"]
        for _ in range(shop.READS_PER_MINUTE):
            self.public(sid, ip="203.0.113.7")
        self.public(sid, expect=429, ip="203.0.113.7")
        self.public(sid, ip="198.51.100.9")

    def test_unknown_shops_and_deleting_the_drive(self):
        self.public("Q" * 22, expect=404)
        self.assertEqual(self.s.request("GET", f"{V}/shop/not-an-id")[0], 400)
        sid = self.open_shop()["shop_id"]
        item = self.kept()
        self.list_(self.sell(item["item_id"])["share_id"])
        status, _, _ = self.s.request("DELETE", f"{V}/me", {"auth_key": codec.b64u(self.d["auth_key"])},
                                      headers=self.d["auth"])
        self.assertEqual(status, 204)
        self.public(sid, expect=404)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM shop_listings").fetchone()[0], 0)


class Listings(ShopCase):
    def setUp(self):
        super().setUp()
        self.shop = self.open_shop()
        self.item = self.kept(3000)
        self.link = self.sell(self.item["item_id"], price="250000")

    def test_a_listing_shows_what_the_owner_typed_and_what_we_knew(self):
        ct = b64(60)
        got = self.list_(self.link["share_id"], link_ct=ct)["listing"]
        self.assertEqual((got["title"], got["description"], got["kind"], got["size_stored"], got["price_ut"],
                          got["link_ct"], got["selling"], got["paused"]),
                         ("Zine no. 3", "Twelve pages, scanned.", "file", self.item["size"], "250000", ct, True, False))
        page, _ = self.public(self.shop["shop_id"])
        self.assertEqual(len(page["items"]), 1)
        item = page["items"][0]
        self.assertEqual(set(item), {"share_id", "title", "description", "kind", "size_stored", "price_ut", "link_ct"})
        self.assertEqual((item["share_id"], item["price_ut"], item["link_ct"]), (self.link["share_id"], "250000", ct))
        text = repr(page)
        for secret in (self.d["id"], self.sales_keys["address"][:30], self.item["item_id"],
                       codec.b64u(self.link["half"])):
            self.assertNotIn(secret, text)
        # The pay page it points at answers as before.
        self.assertEqual(self.s.request("GET", f"{V}/p/{item['share_id']}")[0], 200)
        # A change of words keeps its place; the link's facts come from our server again.
        changed = self.list_(self.link["share_id"], title="Zine 3", description="", expect=200)["listing"]
        self.assertEqual((changed["title"], changed["description"], changed["created_at"]), ("Zine 3", "", got["created_at"]))

    def test_a_folder_lists_its_size_and_newest_first(self):
        self.list_(self.link["share_id"], title="First")
        top = self.folder()
        for _ in range(2):
            self.s.upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60), parent_id=top,
                          parent_wrap=b64(60))
        self.s.now += 5
        got = self.list_(self.sell(top)["share_id"], title="Second")["listing"]
        self.assertEqual(got["kind"], "folder")
        self.assertGreater(got["size_stored"], 0)
        self.assertEqual(self.titles(self.shop["shop_id"]), ["Second", "First"])

    def test_only_the_drives_own_live_pay_links(self):
        plain = self.s.share({"item_id": self.item["item_id"]}, headers=self.d["auth"], max_views=1)
        self.assertEqual(self.list_(plain["share_id"], expect=404)["error"]["code"], "not_found")
        self.list_("Q" * 22, expect=404)
        other = self.s.register()
        self.s.graduate(other)
        self.ready_seller_for(other)
        theirs = self.sell(self.kept(d=other)["item_id"], d=other)
        self.list_(theirs["share_id"], expect=404)                 # another drive's pay link
        self.assertEqual(self.list_(theirs["share_id"], expect=404, d=other)["error"]["message"],
                         "This drive has no shop. Turn it on first.")
        self.s.request("DELETE", f"{V}/s/{self.link['share_id']}", headers=self.d["auth"])
        self.assertEqual(self.list_(self.link["share_id"], expect=409)["error"]["code"], "not_selling")
        for fields in ({"title": ""}, {"title": "x" * (shop.ITEM_TITLE_MAX + 1)}, {"description": "a\nb"},
                       {"description": "x" * (shop.DESC_MAX + 1)}, {"link_ct": b64(32)}, {"link_ct": None}):
            body = {"title": "ok", "description": "", "link_ct": b64(60), **fields}
            fresh = self.sell(self.kept()["item_id"])
            self.assertEqual(self.s.request("PUT", f"{V}/me/shop/listings/{fresh['share_id']}", body,
                                            headers=self.d["auth"])[0], 422, fields)

    def ready_seller_for(self, d):
        keys = fake_keys()
        self.assertEqual(self.register_seller(d=d, keys=keys)[0], 204)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE sellers SET state = 'ok'")

    def test_paused_hides_it_and_sell_again_brings_it_back(self):
        self.list_(self.link["share_id"])
        self.s.request("PATCH", f"{V}/s/{self.link['share_id']}", {"paused": True}, headers=self.d["auth"])
        self.assertEqual(self.titles(self.shop["shop_id"]), [])
        listing = self.mine()["listings"][0]
        self.assertEqual((listing["selling"], listing["paused"]), (False, True))
        self.s.request("PATCH", f"{V}/s/{self.link['share_id']}", {"paused": False}, headers=self.d["auth"])
        self.assertEqual(self.titles(self.shop["shop_id"]), ["Zine no. 3"])

    def test_a_link_that_ends_takes_its_listing_with_it(self):
        def listed():
            return self.s.conn.execute("SELECT COUNT(*) FROM shop_listings").fetchone()[0]

        self.list_(self.link["share_id"])
        self.assertEqual(self.s.request("DELETE", f"{V}/s/{self.link['share_id']}", headers=self.d["auth"])[0], 204)
        self.assertEqual((listed(), self.titles(self.shop["shop_id"])), (0, []))           # stopped
        trashed = self.sell(self.kept()["item_id"])
        self.list_(trashed["share_id"])
        item_id = self.s.conn.execute("SELECT item_id FROM shares WHERE id = ?", (trashed["share_id"],)).fetchone()[0]
        self.assertEqual(self.s.request("PATCH", f"{V}/items/{item_id}", {"trashed": True}, headers=self.d["auth"])[0], 200)
        self.assertEqual(listed(), 0)                                                       # the Trash
        deleted = self.sell(self.kept()["item_id"])
        self.list_(deleted["share_id"])
        item_id = self.s.conn.execute("SELECT item_id FROM shares WHERE id = ?", (deleted["share_id"],)).fetchone()[0]
        self.assertEqual(self.s.request("DELETE", f"{V}/items/{item_id}", headers=self.d["auth"])[0], 204)
        self.assertEqual(listed(), 0)                                                       # deleted
        leaving = self.kept()
        status, _, patched = self.s.request("PATCH", f"{V}/items/{leaving['item_id']}", {"expires_at": self.s.now + 7200},
                                            headers=self.d["auth"])
        self.assertEqual(status, 200, patched)
        link = self.sell(leaving["item_id"])
        self.list_(link["share_id"])
        self.assertEqual(self.titles(self.shop["shop_id"]), ["Zine no. 3"])
        self.s.now = patched["expires_at"] + 1                                              # its file leaves
        self.assertEqual(self.titles(self.shop["shop_id"]), [])                             # at once, on the page
        self.s.run_cleanup()
        self.assertEqual(listed(), 0)                                                       # then for good

    def test_unlist_and_turn_off(self):
        self.list_(self.link["share_id"])
        path = f"{V}/me/shop/listings/{self.link['share_id']}"
        self.assertEqual(self.s.request("DELETE", path, headers=self.d["auth"])[0], 204)
        self.assertEqual(self.titles(self.shop["shop_id"]), [])
        self.assertEqual(self.s.request("DELETE", path, headers=self.d["auth"])[0], 404)
        self.assertEqual(self.s.request("DELETE", path, headers=self.s.register()["auth"])[0], 404)
        self.assertEqual(self.s.request("GET", f"{V}/p/{self.link['share_id']}")[2]["state"], "selling")   # still sells
        self.list_(self.link["share_id"])
        self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 204)
        self.public(self.shop["shop_id"], expect=404)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM shop_listings").fetchone()[0], 0)
        self.assertEqual(self.s.request("GET", f"{V}/p/{self.link['share_id']}")[2]["state"], "selling")
        self.assertIsNone(self.mine())

    def test_a_shop_lists_at_most_max_listings(self):
        with db.tx(self.s.conn):
            for i in range(shop.MAX_LISTINGS):
                share_id = codec.new_id()
                self.s.conn.execute("INSERT INTO shares(id, item_id, mode, created_hour, state) VALUES (?, ?, 'link', 0, "
                                    "'revoked')", (share_id, self.item["item_id"]))
                self.s.conn.execute("INSERT INTO shop_listings(share_id, shop_id, title, kind, size_stored, price_ut, "
                                    "link_ct, created_at) VALUES (?, ?, 't', 'file', 1, 1, x'00', 0)",
                                    (share_id, self.shop["shop_id"]))
        got = self.list_(self.link["share_id"], expect=409)
        self.assertEqual((got["error"]["code"], got["error"]["details"]), ("shop_full", {"max_listings": shop.MAX_LISTINGS}))

    def test_listing_writes_are_limited_per_drive(self):
        for _ in range(shop.LISTING_WRITES_PER_HOUR):
            self.s.request("PUT", f"{V}/me/shop/listings/{self.link['share_id']}",
                           {"title": "t", "description": "", "link_ct": b64(60)}, headers=self.d["auth"])
        self.assertEqual(self.list_(self.link["share_id"], expect=429)["error"]["code"], "rate_limited")


class Reports(ShopCase):
    def setUp(self):
        super().setUp()
        self.shop = self.open_shop()
        self.link = self.sell(self.kept()["item_id"])
        self.list_(self.link["share_id"])
        self.path = self.s.tmp / "mutis.toml"
        self.path.write_text(toml(self.s.cfg.raw))

    def tearDown(self):
        super().tearDown()
        logging.getLogger("mutis").handlers.clear()

    def report(self, link: str, expect=201) -> dict:
        status, _, resp = self.s.request("POST", f"{V}/abuse", {"link": link, "category": "phishing", "details": "fake",
                                                               "pow": self.s.solve("report")})
        self.assertEqual(status, expect, resp)
        return resp

    def admin(self, *args) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admin.main(["--config", str(self.path), *args])
        return out.getvalue()

    def test_a_report_lands_with_the_operator_and_a_takedown_removes_the_page(self):
        origin = self.s.cfg.origin
        sid = self.shop["shop_id"]
        self.report(f"{origin}/shop/{sid}")
        self.report(f"{origin}/shop/{sid}#6{'k' * 43}")
        rows = self.s.conn.execute("SELECT shop_id, share_id, item_id, drop_id, included_key, details FROM abuse_reports "
                                   "ORDER BY created_at, included_key").fetchall()
        self.assertEqual([(r["shop_id"], r["share_id"], r["included_key"]) for r in rows], [(sid, None, 0), (sid, None, 1)])
        self.assertIn("[Reporter included the link key: #6", rows[1]["details"])
        self.report(f"{origin}/shop/not-a-shop-id", expect=422)
        self.report(f"https://elsewhere.invalid/shop/{sid}", expect=422)
        listed = self.admin("reports", "--new")
        self.assertIn(f"shop {sid}", listed)
        self.assertIn("removed", self.admin("takedown", "shop", "--note", "phishing", "--", sid))
        page, _ = self.public(sid, expect=410)
        self.assertEqual(page["error"]["details"]["reason"], "removed")
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM shop_listings").fetchone()[0], 0)
        self.assertEqual({r[0] for r in self.s.conn.execute("SELECT state FROM abuse_reports")}, {"actioned"})
        self.assertEqual(self.mine()["state"], "removed")
        self.assertEqual(self.open_shop(expect=403)["error"]["code"], "shop_removed")
        self.assertEqual(self.list_(self.link["share_id"], expect=403)["error"]["code"], "shop_removed")
        self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 403)
        self.assertEqual(self.s.request("GET", f"{V}/p/{self.link['share_id']}")[0], 200)  # the pay link is its own
        with self.assertRaises(SystemExit):
            self.admin("takedown", "shop", "--", "Q" * 22)


class BuyFromTheShop(ShopCase):
    """The visitor's path on the fake chain: the shop's public page, the listing's pointer, the pay link's own
    claim, test money, the release and the open; then the owner takes it off the shop."""
    chain = True

    def test_a_visitor_buys_through_the_pay_link_a_listing_points_at(self):
        made = self.open_shop()
        link = self.sell(self.kept()["item_id"])
        self.list_(link["share_id"])
        page, _ = self.public(made["shop_id"])
        pointer = page["items"][0]["share_id"]
        self.assertEqual(pointer, link["share_id"])
        info = self.s.request("GET", f"{V}/p/{pointer}")[2]
        self.assertEqual((info["state"], info["price_ut"]), ("selling", page["items"][0]["price_ut"]))
        claim = self.claim({"share_id": pointer})
        status, _, _ = self.s.request("POST", f"{V}/p/{pointer}/claims/{claim['claim_id']}/demo-pay",
                                      {"pow": self.s.solve("demo_pay")}, headers=claim["hdr"])
        self.assertEqual(status, 202)
        self.ticks()
        self.assertEqual(self.poll(claim)["status"], "released")
        opened = self.open(link, claim)
        self.assertEqual(opened["kind"], "file")
        status, _, _ = self.s.request("DELETE", f"{V}/me/shop/listings/{pointer}", headers=self.d["auth"])
        self.assertEqual(status, 204)
        self.assertEqual(self.public(made["shop_id"])[0]["items"], [])
        self.assertEqual(self.open(link, claim)["kind"], "file")                    # a buyer keeps their opens
        earned = self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["total"]
        self.assertEqual(earned["payments"], 1)                                     # Earnings as before


class Shape(ShopCase):
    def test_both_listing_queries_start_from_the_shops_own_listings(self):
        """However many listings other shops hold, a shop's page and the owner's list read this shop's rows first,
        through their index (an EXPLAIN of the statements as they ran)."""
        sid = self.open_shop()["shop_id"]
        for read in (shop.public_listings, shop.owner_listings):
            ran = []
            self.s.conn.set_trace_callback(ran.append)
            read(self.s.conn, sid, self.s.now)
            self.s.conn.set_trace_callback(None)
            sql = next(q for q in ran if q.lstrip().startswith("SELECT l."))
            plan = [r[3] for r in self.s.conn.execute("EXPLAIN QUERY PLAN " + sql)]
            self.assertRegex(plan[0], r"SEARCH l USING INDEX shop_listings_shop", (read.__name__, plan))


    def test_the_tables_hold_only_what_the_owner_published(self):
        cols = {t: [r[1] for r in self.s.conn.execute(f"PRAGMA table_info({t})")] for t in ("shops", "shop_listings")}
        self.assertEqual(cols["shops"], ["id", "identity_id", "title", "bio", "key_wrap", "state", "created_at",
                                         "updated_at"])
        self.assertEqual(cols["shop_listings"], ["share_id", "shop_id", "title", "description", "kind", "size_stored",
                                                 "price_ut", "link_ct", "created_at"])
        for col in cols["shops"] + cols["shop_listings"]:                 # never a name, an address, a key in clear
            self.assertFalse(re.fullmatch(r".*(name|meta|address)\b.*|ip|key|.*_key", col), col)
