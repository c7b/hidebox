# SPDX-License-Identifier: MIT
"""A shop's address (docs/shop.md "The address"; shop.py, handlers/shop.py, shop_page.py), behind features.shop.

The username: ASCII a-z, 0-9 and single hyphens, 3 to 30 characters, case-folded; everything else refused before it is
looked at further, never normalized (accents, Cyrillic and Greek look-alikes, width variants, bidirectional and
zero-width marks, control characters, emoji, markup, paths, NUL, 10 KB); reserved words, brand look-alikes and a
look-alike of another shop's name refused; a name given up held for its drive. Private shops answer only to their read
token; public ones to anyone, with their key, and their page is filled in for search engines with every piece of the
owner's text escaped where it lands (HTML, attributes, meta tags, JSON-LD), a canonical address and a sitemap entry.
Going private again takes a new key with every listing sealed again."""
import json
import os
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from harness import Stack
from paid_fixture import V, b64
from mutis import codec, db, shop, shop_page
from test_shop import ShopCase

WEB = Path(__file__).resolve().parents[2] / "web"
ON = {"features": {"shop": True}, "site_dir": str(WEB)}

HOSTILE = [
    "<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', "../admin", "..%2fadmin", "a/b", "a%00b", "ab\x00c",
    "x" * 10_240, "аlice", "alicе", "ɑlice", "ａlice", "ali​ce", "ali‍ce", "‮alice",
    "alice‬", "⁦ali⁩", "ali ce", " alice", "alice ", "alice\n", "ali\tce", "al_ice", "al.ice", "aliçe",
    "émile", "alíce", "\U0001f338shop", "shop\U0001f600", "a--b", "-alice", "alice-", "ab", "", "a" * 31,
    "Klvin", "İstanbul", "ﬁsh", "alice\r", "%3Cscript%3E", "javascript:x", "\\\\server", "x" * 31, "SHOP",
    "@alice", "#alice", "alice?x=1", "名前", "\U000e0061lice", "alice﻿",
]


class Names(ShopCase):
    def setUp(self):
        self.s = Stack(ON)
        self.s.quiet_chain()
        self.d = self.s.register()
        self.s.graduate(self.d)
        from mutis.fake_chain import fake_keys
        self.sales_keys = fake_keys()
        self.ready_seller()
        self.keys, self.refs = {}, {}

    def put(self, d=None, **fields):
        key = os.urandom(32)
        body = {"title": "A shop", "key_wrap": b64(60), "token_hash": codec.b64u(codec.sha256(shop.read_token(key))),
                **fields}
        status, _, resp = self.s.request("PUT", f"{V}/me/shop", body, headers=(d or self.d)["auth"])
        return status, resp

    def test_hostile_names_are_refused_and_nothing_is_stored(self):
        for name in HOSTILE:
            status, resp = self.put(username=name)
            self.assertEqual(status, 422, repr(name[:40]))
            self.assertEqual(resp["error"]["details"]["field"], "username", repr(name[:40]))
            if len(name) >= 3:                       # the answer never repeats what was sent
                self.assertNotIn(name, json.dumps(resp, ensure_ascii=False), repr(name[:40]))
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0], 0)
        for bad in (5, None, ["alice"], {"a": 1}, True):
            status, _ = self.put(username=bad)
            self.assertEqual(status, 422, bad)

    def test_the_read_token_is_the_one_the_browser_makes(self):
        """web/app/tests/shop.test.js checks lib/shop.js readToken against the same bytes."""
        key = bytes(range(32))
        self.assertEqual(shop.read_token(key).hex(), "0339c9a2a29560feb735e8ecfeb7dc137e09b8e7777c4c6340876195af416fba")
        self.assertEqual(codec.sha256(shop.read_token(key)).hex(),
                         "dff1b3b1d63b66fbb7a5e547470a500d1a1191a864318dd1a0265e9b2da6ce5d")

    def test_capitals_fold_and_the_folded_name_is_unique(self):
        status, resp = self.put(username="Mila-Prints")
        self.assertEqual((status, resp["shop"]["username"], resp["shop"]["path"]), (201, "mila-prints", "/shop/mila-prints"))
        other = self.s.register()
        for taken in ("mila-prints", "MILA-PRINTS", "mi1a-prints", "milaprints", "mila-pr1nts", "m1la-pr1nts"):
            status, resp = self.put(d=other, username=taken)
            self.assertEqual((status, resp["error"]["code"]), (409, "username_taken"), taken)
        self.assertEqual(self.put(d=other, username="mila-zines")[0], 201)

    def test_reserved_words_and_brand_look_alikes(self):
        for name in ("admin", "adm1n", "api", "shop", "static", "www", "hidebox", "h1debox", "hide-box", "myhidebox",
                     "hidebox-official", "mutis", "tari", "tari-support", "official-mila", "support", "fine-print",
                     "well-known", "null", "undefined", "security", "staff-picks"):
            status, resp = self.put(username=name)
            self.assertEqual((status, resp["error"]["code"]), (422, "username_reserved"), name)
        for fine in ("guitarist", "badminton", "mila-shop", "dream-team", "tarim", "s0phie", "abc", "a" * 30):
            status, resp = self.put(username=fine)
            self.assertEqual(status, 201, (fine, resp))
            self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 204)

    def test_a_new_shop_needs_a_name_and_an_old_one_takes_one(self):
        status, resp = self.put()
        self.assertEqual((status, resp["error"]["details"]), (422, {"field": "username"}))
        with db.tx(self.s.conn):                         # a shop made before names, as on staging
            self.s.conn.execute("INSERT INTO shops(id, identity_id, title, key_wrap, created_at, updated_at) "
                                "VALUES (?, ?, 'Old', ?, ?, ?)", ("O" * 22, self.d["id"], os.urandom(60), 1, 1))
        self.assertEqual(self.s.request("GET", f"{V}/shop/{'O' * 22}")[0], 200)   # its id still opens it, as before
        mine = self.s.request("GET", f"{V}/me/shop", headers=self.d["auth"])[2]["shop"]
        self.assertEqual((mine["username"], mine["path"], mine["has_token"]), (None, "/shop/" + "O" * 22, False))
        key_wrap = mine["key_wrap"]
        status, _, resp = self.s.request("PUT", f"{V}/me/shop", {"title": "Old", "key_wrap": key_wrap}, headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["details"]), (422, {"field": "username"}))
        status, resp = self.put(username="old-prints", key_wrap=key_wrap)
        self.assertEqual((status, resp["shop"]["path"], resp["shop"]["has_token"]), (200, "/shop/old-prints", True))
        self.assertEqual(self.s.request("GET", f"{V}/shop/{'O' * 22}")[0], 404)   # now it takes its token

    def test_a_name_given_up_is_held_for_its_drive(self):
        self.assertEqual(self.put(username="mila")[0], 201)
        mine = self.s.request("GET", f"{V}/me/shop", headers=self.d["auth"])[2]["shop"]
        self.assertEqual(self.put(username="mila-two", key_wrap=mine["key_wrap"])[0], 409)    # another token, same key
        other = self.s.register()
        self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 204)
        self.assertEqual(self.put(d=other, username="mila")[1]["error"]["code"], "username_taken")
        self.assertEqual(self.put(d=other, username="m1la")[1]["error"]["code"], "username_taken")
        self.assertEqual(self.put(username="mila")[0], 201)          # its own drive takes it back
        self.assertEqual(self.s.request("DELETE", f"{V}/me/shop", headers=self.d["auth"])[0], 204)
        self.s.now += shop.HOLD_S + 1
        self.assertEqual(self.put(d=self.s.register(), username="mila")[0], 201)

    def test_renaming_holds_the_old_name(self):
        made = self.open_shop(username="mila")
        renamed = self.open_shop(username="mila-zines", expect=200)
        self.assertEqual((renamed["shop_id"], renamed["path"]), (made["shop_id"], "/shop/mila-zines"))
        other = self.s.register()
        self.assertEqual(self.put(d=other, username="mila")[1]["error"]["code"], "username_taken")
        self.assertEqual(self.s.request("GET", f"{V}/shop/mila", headers=self.token("mila-zines"))[0], 404)

    def test_look_alikes_fold_in_any_order(self):
        for a, b in (("clara", "c1ara"), ("cloud", "c1oud"), ("modem", "rnodern"), ("madam", "m4d4m"), ("staff", "st4ff"),
                     ("r-n-x", "mx"), ("toast", "7oa5t"), ("wave", "vvave"), ("bill", "8i1l")):
            self.assertEqual(shop.skeleton(a), shop.skeleton(b), (a, b))
        for name in ("4dmin", "t4ri", "st4ff", "7ari", "h1d3b0x"):
            status, resp = self.put(username=name)
            self.assertEqual((status, resp["error"]["code"]), (422, "username_reserved"), name)
        self.assertEqual(self.put(username="clara")[0], 201)
        self.assertEqual(self.put(d=self.s.register(), username="c1ara")[1]["error"]["code"], "username_taken")

    def test_a_drive_keeps_only_its_newest_holds(self):
        self.assertEqual(self.put(username="name-a")[0], 201)
        wrap = self.s.request("GET", f"{V}/me/shop", headers=self.d["auth"])[2]["shop"]
        token = self.s.conn.execute("SELECT token_hash FROM shops").fetchone()[0]
        for name in ("name-b", "name-c", "name-d", "name-e"):
            self.s.now += 1
            status, _, resp = self.s.request("PUT", f"{V}/me/shop", {"title": "A shop", "key_wrap": wrap["key_wrap"],
                                                                      "token_hash": codec.b64u(token), "username": name},
                                             headers=self.d["auth"])
            self.assertEqual(status, 200, resp)
        held = {r[0] for r in self.s.conn.execute("SELECT skeleton FROM shop_name_holds")}
        self.assertEqual(held, {shop.skeleton(n) for n in ("name-b", "name-c", "name-d")})
        self.assertEqual(self.put(d=self.s.register(), username="name-a")[0], 201)   # its oldest hold lapsed

    def test_a_name_cant_be_another_shops_id(self):
        owner = self.s.register()["id"]
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO shops(id, identity_id, title, key_wrap, created_at, updated_at) "
                                "VALUES (?, ?, 'Old', ?, 1, 1)", ("abcdefghijklmnopqrstuv", owner, os.urandom(60)))
        self.assertEqual(self.put(username="abcdefghijklmnopqrstuv")[1]["error"]["code"], "username_taken")


class Modes(ShopCase):
    def setUp(self):
        super().setUp()
        self.made = self.open_shop(username="mila")
        self.link = self.sell(self.kept()["item_id"])
        self.list_(self.link["share_id"])

    def test_a_private_shop_answers_only_to_its_token(self):
        self.public("mila", token=False, expect=404)
        status, _, resp = self.s.request("GET", f"{V}/shop/mila", headers={"X-Mutis-Shop": b64(32)})
        self.assertEqual(status, 404)
        for junk in ("", "x", b64(31), b64(33), "<script>", "A" * 5000):
            self.assertEqual(self.s.request("GET", f"{V}/shop/mila", headers={"X-Mutis-Shop": junk})[0], 404, junk[:20])
        self.assertEqual(self.public("mila")[0]["title"], "Mila's prints")
        self.assertEqual(self.public(self.made["shop_id"], token=False, expect=404)[0]["error"]["code"], "not_found")
        self.assertNotIn("shop_key", self.public("mila")[0])

    def test_public_never_takes_the_key(self):
        key = self.keys[self.d["id"]][1]
        status, _, resp = self.s.request("PUT", f"{V}/me/shop", {"title": "Mila's prints", "mode": "public",
                                                                  "shop_key": codec.b64u(key)}, headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["details"]), (422, {"field": "shop_key"}))     # not even its own
        public = self.open_shop(mode="public", expect=200)
        self.assertEqual(public["mode"], "public")
        self.assertIsNone(self.s.conn.execute("SELECT published_key FROM shops").fetchone()[0])
        page, headers = self.public("mila", token=False)
        self.assertEqual((page["mode"], len(page["items"])), ("public", 1))
        self.assertNotIn("shop_key", page)
        self.assertEqual(page["items"][0]["link_ct"], self.mine()["listings"][0]["link_ct"])   # sealed, as stored
        self.assertEqual(headers["Cache-Control"], "public, max-age=60")
        self.assertEqual(self.open_shop(title="Mila", expect=200)["mode"], "public")      # edits keep it public

    def test_going_private_again_keeps_the_key(self):
        key = self.keys[self.d["id"]][1]
        self.open_shop(mode="public", expect=200)
        done = self.open_shop(mode="private", expect=200)
        self.assertEqual(done["mode"], "private")
        self.public("mila", token=False, expect=404)
        self.assertEqual(self.s.request("GET", f"{V}/shop/mila", headers={"X-Mutis-Shop": codec.b64u(shop.read_token(key))})[0],
                         200, "the same key still reads it")

    def test_a_new_key_takes_every_listing_sealed_again(self):
        fresh, wrap = os.urandom(32), b64(60)
        self.assertEqual(self.open_shop(key=fresh, key_wrap=wrap, expect=409)["error"]["code"], "relist_needed")
        sealed = b64(60)
        done = self.open_shop(key=fresh, key_wrap=wrap, relisted=[{"share_id": self.link["share_id"], "link_ct": sealed}],
                              expect=200)
        self.assertEqual(done["key_wrap"], wrap)
        self.assertEqual(done["listings"][0]["link_ct"], sealed)
        for bad in ([{"share_id": self.link["share_id"]}], [{"share_id": 5, "link_ct": sealed}], "x",
                    [{"share_id": self.link["share_id"], "link_ct": b64(59)}]):
            status = self.s.request("PUT", f"{V}/me/shop", {"title": "x", "key_wrap": b64(60), "relisted": bad,
                                                           "token_hash": b64(32)}, headers=self.d["auth"])[0]
            self.assertEqual(status, 422, bad)

    def test_a_tab_with_the_old_key_can_list_nothing_after_a_new_key(self):
        stale_wrap = self.keys[self.d["id"]][0]
        self.open_shop(key=os.urandom(32), key_wrap=b64(60), expect=200,
                       relisted=[{"share_id": self.link["share_id"], "link_ct": b64(60)}])
        other = self.sell(self.kept()["item_id"])
        got = self.list_(other["share_id"], key_wrap=stale_wrap, expect=409)
        self.assertEqual(got["error"]["code"], "key_changed")
        self.assertEqual(self.list_(self.link["share_id"], key_wrap=stale_wrap, expect=409)["error"]["code"], "key_changed")
        self.list_(other["share_id"])                                    # with the shop's key as it is now

    def test_a_removed_private_shop_answers_nothing_without_its_token(self):
        with db.tx(self.s.conn):
            shop.takedown(self.s.conn, self.made["shop_id"], self.s.now)
        self.public("mila", token=False, expect=404)
        self.assertEqual(self.public("mila", expect=410)[0]["error"]["details"]["reason"], "removed")

    def test_a_private_shops_key_never_reaches_us(self):
        status, _, resp = self.s.request("PUT", f"{V}/me/shop", {"title": "x", "shop_key": b64(32)}, headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["details"]), (422, {"field": "shop_key"}))


class Parser(HTMLParser):
    """Collects what a browser would see: start tags with attributes, text, and script blocks with their type."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.scripts, self._in = [], [], [], None

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "script":
            self._in = dict(attrs).get("type", "")
            self.scripts.append([self._in, ""])

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = None

    def handle_data(self, data):
        if self._in is not None:
            self.scripts[-1][1] += data
        else:
            self.text.append(data)


EVIL = '</script><script>alert(1)</script>"\'><img src=x onerror=alert(2)>&amp; {{x}}'


class Page(ShopCase):
    def setUp(self):
        self.s = Stack(ON)
        self.s.quiet_chain()
        self.d = self.s.register()
        self.s.graduate(self.d)
        from mutis.fake_chain import fake_keys
        self.sales_keys = fake_keys()
        self.ready_seller()
        self.keys, self.refs = {}, {}
        self.open_shop(title="Mila " + EVIL[:40], bio="Zines " + EVIL[:200].replace(" ", ""), username="mila")
        self.link = self.sell(self.kept()["item_id"])
        self.list_(self.link["share_id"], title="Zine " + EVIL[:70], description="Line " + EVIL[:120])

    def page(self, ref: str, expect=200):
        status, headers, raw = self.s.request("GET", f"{V}/page/shop/{ref}")
        self.assertEqual(status, expect, raw)
        return headers, raw if isinstance(raw, str) else raw

    def go_public(self):
        self.open_shop(title="Mila " + EVIL[:40], mode="public", expect=200)

    def raw(self, ref: str):
        return self.raw_path(f"{V}/page/shop/{ref}")

    def raw_path(self, path: str):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=30)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body

    def test_a_private_or_unknown_shop_gets_the_template_untouched_and_noindex(self):
        template = (WEB / "app" / "shop.html").read_text()
        for ref in ("mila", "no-such-shop", "MILA", self.made_id()):
            status, headers, body = self.raw(ref)
            self.assertEqual((status, body), (200, template), ref)
            self.assertEqual(headers["x-robots-tag"], "noindex, nofollow")
            self.assertNotIn("Mila", body)

    def made_id(self):
        return self.s.conn.execute("SELECT id FROM shops").fetchone()[0]

    def test_a_public_page_escapes_every_piece_of_the_owners_text(self):
        self.go_public()
        status, headers, body = self.raw("mila")
        self.assertEqual(status, 200)
        self.assertEqual(headers["x-robots-tag"], "index, follow")
        p = Parser()
        p.feed(body)
        scripts = [(t, s) for t, s in p.scripts]
        # Only the template's own scripts and one JSON-LD block: nothing the owner wrote made a script.
        self.assertEqual([t for t, _ in scripts].count("application/ld+json"), 1)
        self.assertFalse(any("alert" in s for t, s in scripts if t != "application/ld+json"))
        self.assertNotIn("<script>alert", body)
        self.assertNotIn("<img src=x", body)
        self.assertFalse(any(tag == "img" for tag, _ in p.tags))
        self.assertFalse(any(k.startswith("on") for _, a in p.tags for k in a))
        ld = json.loads(next(s for t, s in scripts if t == "application/ld+json"))
        self.assertEqual(ld["@type"], "CollectionPage")
        self.assertEqual(ld["url"], f"{self.s.cfg.origin}/shop/mila")
        self.assertTrue(ld["name"].startswith("Mila </script>"))          # the text survives, as data
        self.assertEqual(ld["mainEntity"]["itemListElement"][0]["name"][:5], "Zine ")
        block = body.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
        self.assertNotRegex(block, r"[<>&  ]|[^\x00-\x7f]")
        metas = {a.get("name") or a.get("property"): a.get("content") for tag, a in p.tags if tag == "meta"}
        self.assertTrue(metas["og:title"].startswith("Mila </script><script>"))   # an attribute value, decoded
        self.assertEqual(metas["og:url"], f"{self.s.cfg.origin}/shop/mila")
        self.assertEqual(metas["robots"], "index, follow")
        self.assertNotIn("\n", metas["description"])
        canon = [a for tag, a in p.tags if tag == "link" and a.get("rel") == "canonical"]
        self.assertEqual(canon, [{"rel": "canonical", "href": f"{self.s.cfg.origin}/shop/mila"}])
        title = re.search(r"<title>(.*?)</title>", body).group(1)
        self.assertTrue(title.startswith("Mila &lt;/script&gt;"))
        text = "".join(p.text)
        self.assertIn("Zine </script><script>alert(1)</script>", text)       # shown as text
        self.assertIn("Line ", text)
        self.assertIn("0.1 tTARI", text)
        self.assertNotIn(self.keys[self.d["id"]][1].hex(), body)
        self.assertNotIn(codec.b64u(self.keys[self.d["id"]][1]), body)      # the page itself never carries the key

    def test_a_public_page_is_drawn_as_the_app_draws_it(self):
        """The shop in <main> is ui/shop-page.js's markup in the app's words (the copy deck the release serves) and
        icons, in the drive's look: the app's draw moves nothing (web/app/ui/tests/flows_shop.py measures it)."""
        self.go_public()
        _, _, body = self.raw("mila")
        deck = json.loads((WEB / "app" / "i18n" / "en.json").read_text())
        opening, main = re.search(r'(?s)(<main id="main"[^>]*>)(.*)</main>', body).groups()
        self.assertEqual(opening, '<main id="main" class="fv-page shop-main" data-page-class="container a-main" tabindex="-1">')
        self.assertIn('<body class="a-page" data-look="drive">', body)
        e = shop_page.esc
        badge = ('<span class="badge" data-variant="secondary"><svg class="icon" aria-hidden="true" focusable="false">'
                 f'<use href="/shared/ui/icons.svg#i-store"></use></svg>{e(deck["shop.label"])}</span>')
        self.assertIn(badge, main)
        for key in ("shop.owner_wrote", "shop.how", "shop.no_key"):      # the market is off here: no Ask for it
            self.assertIn(f">{shop_page.prose(deck[key])}</p>", main, key)
        self.assertNotIn(e(deck["shop.ask"]), main)
        self.assertIn(f'<h2 class="h4" id="shop-list-h">{deck["shop.count"]["one"].replace("{count}", "1")}</h2>', main)
        self.assertIn('<span class="shop-item-icon" aria-hidden="true"><svg class="icon"', main)
        self.assertRegex(main, r'<div class="shop-item-meta">File · About \d+ [KMG]?B</div>')
        self.assertIn('<span class="shop-price">0.1 tTARI</span>', main)
        self.assertNotIn("data-testid", main)          # what the tests find is the app's own drawing

    def test_a_deck_without_a_word_the_page_needs_goes_out_unfilled(self):
        self.go_public()
        site = self.s.tmp / "deck-site"
        (site / "app" / "i18n").mkdir(parents=True)
        (site / "app" / "shop.html").write_text((WEB / "app" / "shop.html").read_text())
        deck = json.loads((WEB / "app" / "i18n" / "en.json").read_text())
        del deck["shop.owner_wrote"]
        (site / "app" / "i18n" / "en.json").write_text(json.dumps(deck))
        self.s.cfg.raw["site_dir"] = str(site)
        shop_page._template.clear()
        try:
            status, headers, body = self.raw("mila")
            self.assertEqual((status, headers["x-robots-tag"]), (200, "noindex, nofollow"))
            self.assertNotIn("Mila", body)
        finally:
            self.s.cfg.raw["site_dir"] = str(WEB)
            shop_page._template.clear()

    def test_one_address_per_public_shop(self):
        self.go_public()
        for ref in ("MILA", "Mila", self.made_id()):
            status, headers, _ = self.raw(ref)
            self.assertEqual((status, headers["location"]), (301, "/shop/mila"), ref)

    def test_staging_never_asks_to_be_indexed(self):
        self.go_public()
        self.s.cfg.raw["staging"] = True
        try:
            status, headers, body = self.raw("mila")
            self.assertEqual(headers["x-robots-tag"], "noindex, nofollow")
            self.assertIn('<meta name="robots" content="noindex, nofollow">', body)
            self.assertNotIn("<loc>", self.raw_path(f"{V}/shops/sitemap.xml")[2])
        finally:
            self.s.cfg.raw["staging"] = False

    def test_a_template_without_its_anchors_goes_out_unfilled(self):
        self.go_public()
        broken = self.s.tmp / "site" / "app"
        broken.mkdir(parents=True)
        (broken / "shop.html").write_text("<html><head><title>x</title></head><body><main>…</main></body></html>")
        self.s.cfg.raw["site_dir"] = str(broken.parent)
        shop_page._template.clear()
        try:
            status, headers, body = self.raw("mila")
            self.assertEqual((status, headers["x-robots-tag"]), (200, "noindex, nofollow"))
            self.assertNotIn("Mila", body)
        finally:
            self.s.cfg.raw["site_dir"] = str(WEB)
            shop_page._template.clear()

    def test_the_sitemap_lists_public_shops_with_something_for_sale(self):
        status, _, xml = self.raw_path(f"{V}/shops/sitemap.xml")
        self.assertEqual(status, 200)
        self.assertNotIn("<loc>", xml)
        self.go_public()
        status, headers, xml = self.raw_path(f"{V}/shops/sitemap.xml")
        self.assertEqual(headers["content-type"], "application/xml; charset=utf-8")
        self.assertIn(f"<loc>{self.s.cfg.origin}/shop/mila</loc>", xml)
        self.assertEqual(xml.count("<url>"), 1)


class Words(unittest.TestCase):
    """The app's words, sizes and prices, as the server writes them (lib/i18n.js, lib/network.js, lib/pay.js,
    ui/drive-parts.js)."""
    def test_the_deck_as_the_mainnet_says_it(self):
        test, main = shop_page.words(str(WEB), "esmeralda"), shop_page.words(str(WEB), "mainnet")
        raw = json.loads((WEB / "app" / "i18n" / "en.json").read_text())
        self.assertEqual(test, raw)
        self.assertEqual(shop_page.say(main, "testnet"), raw["testnet@mainnet"].replace("{brand}", "hidebox"))
        self.assertEqual((shop_page.say(test, "earn.unit"), shop_page.say(main, "earn.unit")), ("tTARI", "TARI"))
        self.assertFalse(any(k.endswith("@mainnet") for k in main))
        self.assertFalse(any("tTARI" in json.dumps(v) for v in main.values()))
        self.assertIsNone(shop_page.words(str(WEB / "nowhere"), "mainnet"))

    def test_say_fills_and_counts_as_the_app_does(self):
        deck = {"n": {"one": "{count} thing", "other": "{count} things"}, "b": "{brand} and {x}", "s": "{gone}"}
        self.assertEqual([shop_page.say(deck, "n", count=c) for c in (0, 1, 2, 1200)],
                         ["0 things", "1 thing", "2 things", "1,200 things"])
        self.assertEqual(shop_page.say(deck, "b", x="<y>"), "hidebox and <y>")     # the caller escapes
        self.assertEqual(shop_page.say(deck, "s"), "{gone}")
        with self.assertRaises(shop_page.TemplateError):
            shop_page.say(deck, "missing")

    def test_on_the_mainnet_the_page_ends_as_the_app_draws_it(self):
        """The network line under the list (and Report this shop on a shop's page), so the first frame is as tall as
        the last; on the testnet the line depends on the browser's dates, and the app adds it."""
        page = (WEB / "app" / "shop.html").read_text()
        main, test = shop_page.words(str(WEB), "mainnet"), shop_page.words(str(WEB), "esmeralda")
        line = shop_page.prose(shop_page.say(main, "testnet"))
        out = shop_page.render_market(page, [], "https://hidebox.app", "TARI", main, "mainnet")
        self.assertIn(f'</section><footer class="shop-foot"><p class="a-testnet">{line}</p></footer></div></main>', out)
        self.assertNotIn("shop-foot", shop_page.render_market(page, [], "https://example.org", "tTARI", test, "esmeralda"))
        row = {"title": "Mila", "bio": "", "username": "mila"}
        out = shop_page.render_public(page, row, [], "https://hidebox.app", "TARI", main, True, "mainnet")
        self.assertIn(f'<footer class="shop-foot"><p class="a-testnet">{line}</p><a class="link-plain small" '
                      'href="/fine-print#link=https%3A%2F%2Fhidebox.app%2Fshop%2Fmila">Report this shop</a></footer>', out)

    def test_the_icons_are_the_templates_whatever_the_owner_wrote(self):
        page = (WEB / "app" / "shop.html").read_text()
        deck = shop_page.words(str(WEB), "esmeralda")
        row = {"title": "/shared/ui/icons.deadbeef.svg#x", "bio": "/shared/ui/icons.0badc0de.svg#y", "username": "mila"}
        out = shop_page.render_public(page, row, [], "https://example.org", "tTARI", deck, True)
        self.assertNotIn('href="/shared/ui/icons.deadbeef', out)
        self.assertNotIn('href="/shared/ui/icons.0badc0de', out)
        self.assertIn('<use href="/shared/ui/icons.svg#i-store"></use>', out)

    def test_a_deck_word_that_isnt_text_leaves_the_page_unfilled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as site:
            (Path(site) / "app" / "i18n").mkdir(parents=True)
            (Path(site) / "app" / "i18n" / "en.json").write_text('{"a": null, "b": "5 tTARI", "c": 3, "c@mainnet": "x"}')
            deck = shop_page.words(site, "mainnet")
        self.assertEqual(deck, {"a": None, "b": "5 TARI", "c": "x"})
        with self.assertRaises(shop_page.TemplateError):
            shop_page.say(deck, "a")

    def test_a_paragraph_has_one_sentence_a_line_as_the_app_writes_it(self):
        prose = shop_page.prose
        self.assertEqual(prose("Each seller wrote their own words. The server doesn't check them."),
                         "Each seller wrote their own words. <br>The server doesn&#x27;t check them.")
        self.assertEqual(prose("One. “Two.” (Three?) four. Five! Six"), "One. <br>“Two.” <br>(Three?) four. <br>Five! <br>Six")
        self.assertEqual(prose("v0.53.2 and e.g. this. <b>"), "v0.53.2 and e.g. this. &lt;b&gt;")
        self.assertEqual(prose(""), "")

    def test_sizes_and_prices(self):
        mib = 1024 * 1024
        self.assertEqual([shop_page.size_bucket(n) for n in (0, mib, mib + 1, 600 * mib, 99 * 1024 * mib)],
                         [mib, mib, 5 * mib, 1024 * mib, 10240 * mib])
        self.assertEqual([shop_page.format_bytes(n) for n in (0, 512, 1536, 1024 * 1023, mib, 5 * mib, 1024 * mib, 10240 * mib)],
                         ["0 B", "512 B", "1.5 KB", "1,023 KB", "1 MB", "5 MB", "1 GB", "10 GB"])
        self.assertEqual([shop_page.tari(n) for n in (100000, 1000000, 1234567, 1000, 999, "2500000")],
                         ["0.1", "1", "1.234", "0.001", "0", "2.5"])


del ShopCase
