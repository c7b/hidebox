# SPDX-License-Identifier: MIT
"""The market (docs/market.md, server/mutis/market.py), behind features.market: what public shops sell, searchable and
paged; asks for a listing's key half, answered by the seller's drive with something sealed our server can't open;
asks that end with their listing, their shop's mode, the shop or their time; the limits."""
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Stack  # noqa: E402
from mutis import codec, db, market, shop, shop_page  # noqa: E402
from paid_fixture import V, b64  # noqa: E402
from test_shop import ShopCase  # noqa: E402

ON = {"features": {"shop": True, "market": True}}
WEB = Path(__file__).resolve().parents[2] / "web"


class MarketCase(ShopCase):
    def setUp(self):
        self.s = Stack(ON)
        self.s.quiet_chain()
        self.d = self.s.register()
        self.s.graduate(self.d)
        from mutis.fake_chain import fake_keys
        self.sales_keys = fake_keys()
        self.ready_seller()
        self.keys, self.refs = {}, {}
        self.made = self.open_shop(title="Mila's prints", username="mila", mode="public")
        self.link = self.sell(self.kept()["item_id"])
        self.list_(self.link["share_id"], title="Zine no. 3", description="Twelve pages, scanned.")

    def browse(self, expect=200, **query):
        q = "&".join(f"{k}={v}" for k, v in query.items())
        status, headers, body = self.s.request("GET", f"{V}/market" + (f"?{q}" if q else ""))
        self.assertEqual(status, expect, body)
        return body, headers

    def new_ask(self, share_id=None, expect=201, ip=None, **over):
        secret = os.urandom(32)
        token = codec.hkdf(secret, b"mutis/v2", b"market-ask", 32)
        body = {"ask_id": codec.b64u(codec.hkdf(secret, b"mutis/v2", b"market-ask-id", 16)),
                "share_id": share_id or self.link["share_id"], "owner_pk": b64(32), "view_pk": b64(32),
                "token_hash": codec.b64u(codec.sha256(token)), "pow": self.s.solve("ask", ip=ip), **over}
        status, _, resp = self.s.request("POST", f"{V}/market/asks", body, ip=ip)
        self.assertEqual(status, expect, resp)
        return {"id": body["ask_id"], "token": {"X-Mutis-Ask": codec.b64u(token)}, "body": body, "resp": resp}

    def state(self, ask, expect=200):
        status, headers, resp = self.s.request("GET", f"{V}/market/asks/{ask['id']}", headers=ask["token"])
        self.assertEqual(status, expect, resp)
        return resp

    def waiting(self, d=None):
        status, _, resp = self.s.request("GET", f"{V}/me/market/asks", headers=(d or self.d)["auth"])
        self.assertEqual(status, 200, resp)
        return resp["asks"]

    def answer(self, ask_id, expect=204, d=None, **body):
        body = body or {"answer": b64(125)}
        status, _, resp = self.s.request("PUT", f"{V}/me/market/asks/{ask_id}", body, headers=(d or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return resp


class Flag(MarketCase):
    def test_off_by_default(self):
        self.s.close()
        self.s = Stack({"features": {"shop": True}})
        d = self.s.register()
        for method, path in (("GET", "/market"), ("POST", "/market/asks"), ("GET", "/market/asks/" + "A" * 22),
                             ("GET", "/me/market/asks"), ("PUT", "/me/market/asks/" + "A" * 22)):
            status, _, resp = self.s.request(method, V + path, {} if method != "GET" else None, headers=d["auth"])
            self.assertEqual((status, resp["error"]["details"]), (503, {"feature": "market"}), path)
        self.assertFalse(self.s.request("GET", f"{V}/config")[2]["features"]["market"])


class Browse(MarketCase):
    def test_a_public_shops_listing_is_in_the_market_without_its_sealed_half(self):
        body, headers = self.browse()
        self.assertEqual(headers["Cache-Control"], "public, max-age=60")
        (it,) = body["items"]
        self.assertEqual((it["title"], it["description"], it["kind"], it["price_ut"], it["shop"]),
                         ("Zine no. 3", "Twelve pages, scanned.", "file", "100000",
                          {"username": "mila", "title": "Mila's prints", "path": "/shop/mila"}))
        self.assertNotIn("link_ct", it)
        self.assertIsNone(body["next"])
        page, _ = self.public("mila", token=False)
        self.assertTrue(page["market"])

    def test_private_shops_and_paused_links_stay_out(self):
        self.open_shop(mode="private", expect=200)
        self.assertEqual(self.browse()[0]["items"], [])
        self.open_shop(mode="public", expect=200)
        self.assertEqual(len(self.browse()[0]["items"]), 1)
        self.s.request("PATCH", f"{V}/me/shares/{self.link['share_id']}", {"paused": True}, headers=self.d["auth"])
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE paid_shares SET paused = 1")
        self.assertEqual(self.browse()[0]["items"], [])

    def test_search_folds_ascii_only_as_the_database_does(self):
        other = self.sell(self.kept()["item_id"])
        self.list_(other["share_id"], title="Étude de couleur", description="")
        self.assertEqual([x["title"] for x in self.browse(q=quote("Étude"))[0]["items"]], ["Étude de couleur"])
        self.assertEqual([x["title"] for x in self.browse(q=quote("ÉTUDE"))[0]["items"]], ["Étude de couleur"])   # ASCII folds
        self.assertEqual([x["title"] for x in self.browse(q=quote("étude"))[0]["items"]], [])   # é and É don't, as in SQLite

    def test_search_kind_and_pages(self):
        self.s.now += 10
        other = self.sell(self.kept()["item_id"])
        self.list_(other["share_id"], title="Photo pack", description="50% off, 30 shots")
        self.s.now += 10
        third = self.sell(self.kept()["item_id"])
        self.list_(third["share_id"], title="Preset_one", description="")
        titles = lambda **q: [x["title"] for x in self.browse(**q)[0]["items"]]    # noqa: E731
        self.assertEqual(titles(q="zine"), ["Zine no. 3"])
        self.assertEqual(titles(q="MILA"), ["Preset_one", "Photo pack", "Zine no. 3"])     # the shop's name, any case
        self.assertEqual(titles(q="photo%20shots"), ["Photo pack"])                        # every word
        self.assertEqual(titles(q="%25"), ["Photo pack"])                                  # % is a character, not a wildcard
        self.assertEqual(titles(q="_"), ["Preset_one"])
        self.assertEqual(titles(kind="folder"), [])
        with mock.patch.object(market, "PAGE", 2):
            first = self.browse()[0]
            self.assertEqual(len(first["items"]), 2)
            rest = self.browse(cursor=first["next"])[0]
        self.assertEqual([x["title"] for x in first["items"] + rest["items"]], ["Preset_one", "Photo pack", "Zine no. 3"])
        self.assertIsNone(rest["next"])

    def test_bad_queries(self):
        for query in ({"q": "x" * 61}, {"q": "%01"}, {"kind": "zip"}, {"cursor": "nope"}, {"cursor": "1.short"}):
            self.browse(expect=422, **query)

    def test_rate_limited_per_network(self):
        with mock.patch.object(market, "READS_PER_MINUTE", 3):
            for _ in range(3):
                self.assertEqual(self.s.request("GET", f"{V}/market", ip="203.0.113.7")[0], 200)
            self.assertEqual(self.s.request("GET", f"{V}/market", ip="203.0.113.7")[0], 429)
            self.assertEqual(self.s.request("GET", f"{V}/market", ip="198.51.100.9")[0], 200)


class Asks(MarketCase):
    def test_ask_answer_and_read(self):
        ask = self.new_ask()
        self.assertEqual(ask["resp"]["expires_at"], self.s.now + market.ASK_S)
        self.assertEqual(self.state(ask), {"ask_id": ask["id"], "share_id": self.link["share_id"], "state": "waiting",
                                           "expires_at": self.s.now + market.ASK_S})
        (w,) = self.waiting()
        self.assertEqual((w["ask_id"], w["share_id"], w["owner_pk"], w["view_pk"]),
                         (ask["id"], self.link["share_id"], ask["body"]["owner_pk"], ask["body"]["view_pk"]))
        sealed = b64(125)
        self.answer(ask["id"], answer=sealed)
        got = self.state(ask)
        self.assertEqual((got["state"], got["answer"], got["expires_at"]),
                         ("answered", sealed, self.s.now + market.ANSWER_KEEP_S))
        self.assertEqual(self.waiting(), [])
        self.answer(ask["id"], answer=sealed)                         # the same answer again: fine
        self.answer(ask["id"], answer=b64(125), expect=409)
        row = self.s.conn.execute("SELECT answer FROM market_asks").fetchone()
        self.assertEqual(row[0], codec.unb64u(sealed))                  # opaque: our server stores what it was given

    def test_only_its_token_reads_an_ask(self):
        ask = self.new_ask()
        for headers in ({}, {"X-Mutis-Ask": b64(32)}, {"X-Mutis-Ask": "x"}):
            status, _, resp = self.s.request("GET", f"{V}/market/asks/{ask['id']}", headers=headers)
            self.assertEqual((status, resp["error"]["code"]), (404, "not_found"))

    def test_what_can_be_asked(self):
        self.new_ask(share_id="Q" * 22, expect=404)
        self.new_ask(view_pk=b64(31), expect=422)
        same = b64(32)
        self.new_ask(owner_pk=same, view_pk=same, expect=422)
        self.new_ask(token_hash=b64(31), expect=422)
        self.new_ask(ask_id=b64(16) + "\n", expect=422)          # never stored: its drive couldn't answer it
        self.new_ask(share_id=self.link["share_id"] + "\n", expect=422)
        ask = self.new_ask()
        status, _, resp = self.s.request("POST", f"{V}/market/asks", {**ask["body"], "pow": self.s.solve("ask")})
        self.assertEqual((status, resp["error"]["code"]), (409, "conflict"))
        body = {**ask["body"], "ask_id": b64(16)}
        body.pop("pow")
        self.assertEqual(self.s.request("POST", f"{V}/market/asks", body)[0], 428)          # proof of work
        self.open_shop(mode="private", expect=200)
        self.new_ask(expect=404)                                                            # not in the market

    def test_only_its_shop_answers(self):
        ask = self.new_ask()
        other = self.s.register()
        self.answer(ask["id"], d=other, expect=404)
        self.assertEqual(self.waiting(d=other), [])
        self.answer("Q" * 22, expect=404)
        self.answer(ask["id"], answer=b64(124), expect=422)

    def test_a_refusal_ends_the_ask(self):
        ask = self.new_ask()
        self.answer(ask["id"], refused=True)
        self.state(ask, expect=404)

    def test_limits(self):
        with mock.patch.object(market, "MAX_WAITING", 2):
            self.new_ask()
            self.new_ask()
            self.assertEqual(self.new_ask(expect=429)["resp"]["error"]["code"], "asks_full")
        with mock.patch.object(market, "ASKS_PER_HOUR", 2):
            self.new_ask(ip="203.0.113.7")
            self.new_ask(ip="203.0.113.7")
            self.new_ask(ip="203.0.113.7", expect=429)


class Endings(MarketCase):
    def test_it_ends_with_its_time(self):
        waiting, answered = self.new_ask(), self.new_ask()
        self.s.now += 86400
        self.answer(answered["id"])                                   # answered a day later
        self.s.now += market.ASK_S - 86400
        self.state(waiting, expect=404)
        self.state(answered)                                          # its answer is kept from when it came
        self.assertEqual(self.waiting(), [])
        self.s.now += 86400
        self.state(answered, expect=404)
        self.s.run_cleanup()
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM market_asks").fetchone()[0], 0)

    def test_it_ends_with_its_listing_its_link_its_shop_and_a_takedown(self):
        def count():
            return self.s.conn.execute("SELECT COUNT(*) FROM market_asks").fetchone()[0]
        self.new_ask()
        self.s.request("DELETE", f"{V}/me/shop/listings/{self.link['share_id']}", headers=self.d["auth"])
        self.assertEqual(count(), 0)
        self.list_(self.link["share_id"])
        self.new_ask()
        self.open_shop(mode="private", expect=200)
        self.assertEqual(count(), 0)
        self.open_shop(mode="public", expect=200)
        self.new_ask()
        with db.tx(self.s.conn):
            from mutis import items
            items.end_share(self.s.conn, self.link["share_id"], "revoked", self.s.now)
        self.assertEqual(count(), 0)
        other = self.sell(self.kept()["item_id"])
        self.list_(other["share_id"])
        self.new_ask(share_id=other["share_id"])
        with db.tx(self.s.conn):
            shop.takedown(self.s.conn, self.made["shop_id"], self.s.now)
        self.assertEqual(count(), 0)

    def test_turning_the_shop_off_ends_its_asks(self):
        self.new_ask()
        self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 204)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM market_asks").fetchone()[0], 0)


class Shape(MarketCase):
    def test_the_table_holds_no_secret_in_the_clear(self):
        cols = [r[1] for r in self.s.conn.execute("PRAGMA table_info(market_asks)")]
        self.assertEqual(cols, ["id", "share_id", "shop_id", "owner_pk", "view_pk", "token_hash", "answer",
                                "created_at", "answered_at", "expires_at"])

    def test_config(self):
        cfg = self.s.request("GET", f"{V}/config")[2]
        self.assertEqual(cfg["market"], {"page": 24, "q_max": 60, "ask_days": 7, "answer_keep_days": 7,
                                         "max_waiting": 200})
        self.assertTrue(cfg["features"]["market"])


class Page(MarketCase):
    """/market and a public shop's page as served, while the market is on: ui/market-page.js's and ui/shop-page.js's
    markup in the app's words, so the app's first frame is its last one's layout (the market flickered, Nov 2026;
    web/app/ui/tests/flows_shop.py measures it in a browser)."""
    def setUp(self):
        super().setUp()
        self.s.cfg.raw["site_dir"] = str(WEB)
        self.deck = json.loads((WEB / "app" / "i18n" / "en.json").read_text())

    def page(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=30)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        self.assertEqual(resp.status, 200, body[:200])
        return resp.getheader("X-Robots-Tag"), re.search(r'(?s)<main id="main"[^>]*>(.*)</main>', body)[1]

    def test_the_market_as_the_app_draws_it_before_any_search(self):
        robots, main = self.page(f"{V}/page/market")
        self.assertEqual(robots, "index, follow")
        e = shop_page.esc
        for key in ("market.page_title", "market.h", "market.search", "shop.ask"):
            self.assertIn(e(self.deck[key]), main, key)
        for key in ("market.desc", "market.owner_wrote"):            # paragraphs: one sentence a line (ui/lines.js)
            self.assertIn(f">{shop_page.prose(self.deck[key])}</p>", main, key)
        self.assertIn('<form class="market-search" role="search"><input class="input" id="market-q" type="search" name="q" '
                      f'maxlength="60" autocomplete="off" aria-label="{e(self.deck["market.search_label"])}">', main)
        self.assertIn('<li class="card shop-item market-item">', main)
        self.assertIn('<a class="link-plain shop-own-text" href="/shop/mila">from Mila&#x27;s prints</a>', main)
        self.assertIn('<div class="shop-item-buy market-item-buy"><span class="shop-price">0.1 tTARI</span>'
                      '<div class="market-ask-slot"><div class="stack-sm"><button class="btn" type="button" '
                      'aria-label="Ask for Zine no. 3">', main)
        self.assertNotIn("data-testid", main)
        self.assertNotIn(e(self.deck["market.empty"]), main)

    def test_an_empty_market_says_so_as_the_app_does(self):
        status, _, _ = self.s.request("DELETE", f"{V}/me/shop/listings/{self.link['share_id']}", headers=self.d["auth"])
        self.assertIn(status, (200, 204))
        _, main = self.page(f"{V}/page/market")
        self.assertIn('<ul class="shop-items" role="list"></ul><div><div class="empty">', main)
        self.assertIn(shop_page.esc(self.deck["market.empty"]), main)
        self.assertIn(f'<p class="empty-description">{shop_page.prose(self.deck["market.empty_d"])}</p>', main)

    def test_a_public_shop_offers_ask_for_it_as_the_app_does_without_its_key(self):
        _, main = self.page(f"{V}/page/shop/mila")
        e = shop_page.esc
        for key in ("shop.label", "shop.ask"):
            self.assertIn(e(self.deck[key]), main, key)
        for key in ("shop.owner_wrote", "shop.keyless"):
            self.assertIn(f">{shop_page.prose(self.deck[key])}</p>", main, key)
        self.assertNotIn(shop_page.prose(self.deck["shop.no_key"]), main)
        self.assertIn('aria-label="Ask for Zine no. 3"', main)


if __name__ == "__main__":
    unittest.main()
