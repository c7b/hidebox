# SPDX-License-Identifier: MIT
"""The abuse controls of the security pass of 2026-11-21: a new drive's public shop sells by its link at once but joins
the market, the sitemap and search engines only once the drive is a week old or has paid; a report holds a shop out of
them at once; a short blocklist for a shop's public text; `mutis-admin suspend`; open claims per network; the
proof of work that hardens as a shared limit fills; and the API's total in-flight cap. (The public status without
the abuse reasons: deploy/tests/test_ops.py.)"""
import contextlib
import io
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutis import admin, api, blocklist, db, sales, shop  # noqa: E402
from mutis.fake_chain import fake_keys  # noqa: E402
from paid_fixture import V  # noqa: E402
from test_admin import toml  # noqa: E402
from test_market import MarketCase  # noqa: E402


class Case(MarketCase):
    """Mila's shop (MarketCase) is listed: her drive is old. A brand-new drive opens its own public shop here."""

    def setUp(self):
        super().setUp()
        self.s.cfg.raw["site_dir"] = str(Path(__file__).resolve().parents[2] / "web")   # the shop page's template
        self.path = self.s.tmp / "mutis.toml"
        self.path.write_text(toml(self.s.cfg.raw))
        self.new = self.s.register()
        self.ready_seller_for(self.new)
        self.new_shop = self.open_shop(title="Fresh shop", d=self.new, mode="public")
        self.new_link = self.sell(self.kept(d=self.new)["item_id"], d=self.new)
        self.list_(self.new_link["share_id"], title="New zine", d=self.new)

    def tearDown(self):
        super().tearDown()
        logging.getLogger("mutis").handlers.clear()

    def ready_seller_for(self, d):
        self.assertEqual(self.register_seller(d=d, keys=fake_keys())[0], 204)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE sellers SET state = 'ok'")

    def admin(self, *args) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admin.main(["--config", str(self.path), *args])
        return out.getvalue()

    def market_titles(self) -> set:
        return {x["title"] for x in self.browse()[0]["items"]}

    def sitemap(self) -> str:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=30)
        conn.request("GET", f"{V}/shops/sitemap.xml")
        body = conn.getresponse().read().decode()
        conn.close()
        return body

    def robots(self, ref: str) -> str:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=30)
        conn.request("GET", f"{V}/page/shop/{ref}")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.getheader("X-Robots-Tag") or ""

    def report(self, link: str) -> None:
        status, _, resp = self.s.request("POST", f"{V}/abuse", {"link": link, "category": "other", "details": "x",
                                                               "pow": self.s.solve("report")})
        self.assertEqual(status, 201, resp)


class NewShops(Case):
    def test_a_new_drives_shop_sells_by_its_link_but_is_not_listed(self):
        name = self.new_shop["username"]
        page, _ = self.public(name)                        # its link works at once, listings and all
        self.assertEqual([x["title"] for x in page["items"]], ["New zine"])
        self.assertEqual(self.market_titles(), {"Zine no. 3"})
        xml = self.sitemap()
        self.assertIn("/shop/mila<", xml)
        self.assertNotIn(f"/shop/{name}<", xml)
        self.assertIn("noindex", self.robots(name))
        self.assertNotIn("noindex", self.robots("mila"))
        mine = self.mine(self.new)
        self.assertEqual((mine["listed"], mine["held"]), (False, False))
        self.assertGreater(mine["listed_from"], self.s.now)
        self.assertTrue(self.mine()["listed"])

    def test_it_joins_after_a_week_or_once_the_drive_has_paid(self):
        name = self.new_shop["username"]
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET paid_until = ? WHERE id = ?", (self.s.now + 86400, self.new["id"]))
        self.assertIn("New zine", self.market_titles())
        self.assertIn(f"/shop/{name}<", self.sitemap())
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET paid_until = NULL, created_day = ? WHERE id = ?",
                                (shop.listed_day(self.s.now), self.new["id"]))
        self.assertIn("New zine", self.market_titles())
        self.assertNotIn("noindex", self.robots(name))


class Holds(Case):
    def test_a_report_of_a_shop_or_of_a_link_it_lists_holds_it_until_review(self):
        origin = self.s.cfg.origin
        self.report(f"{origin}/shop/mila")
        self.assertNotIn("Zine no. 3", self.market_titles())
        self.assertNotIn("/shop/mila<", self.sitemap())
        self.assertIn("noindex", self.robots("mila"))
        page, _ = self.public("mila")                        # its own link still answers, listings and all
        self.assertEqual([x["title"] for x in page["items"]], ["Zine no. 3"])
        self.assertTrue(self.mine()["held"])
        self.assertIn("/shop/mila", self.admin("shop-review", "list"))
        self.assertIn("cleared", self.admin("shop-review", "clear", "--", "mila"))
        self.assertIn("Zine no. 3", self.market_titles())
        self.assertEqual({r[0] for r in self.s.conn.execute("SELECT state FROM abuse_reports")}, {"rejected"})
        self.report(f"{origin}/p/{self.link['share_id']}")  # a pay link the shop lists
        self.assertNotIn("Zine no. 3", self.market_titles())
        self.admin("takedown", "shop", "--", "mila")        # removed: nothing left to hold
        self.assertEqual(shop.held_shops(self.s.conn), {})


class Blocklist(unittest.TestCase):
    def test_plain_adverts_are_caught_and_ordinary_words_are_not(self):
        for text in ("PTHC pack", "p.t.h.c", "ch1ld-p0rn", "Child Porn", "13yo nude", "underage sexy", "jailbait pics",
                     "lolicon art", "Pédophile"):
            self.assertTrue(blocklist.banned(text), text)
        for text in ("Child portraits", "Kids art, ages 5-10", "Teen fiction", "Lolita (Nabokov) essay",
                     "Sex education guide", "Photo pack", "Pedometer data", "18 years old and up", "Zine no. 3"):
            self.assertFalse(blocklist.banned(text), text)


class Refusals(Case):
    def test_the_shop_refuses_them_with_a_neutral_message(self):
        got = self.open_shop(title="pthc shop", expect=422)
        self.assertEqual(got["error"]["code"], "text_refused")
        self.assertNotIn("pthc", got["error"]["message"].lower())
        link = self.sell(self.kept()["item_id"])
        got = self.list_(link["share_id"], title="ok", description="child porn", expect=422)
        self.assertEqual(got["error"]["code"], "text_refused")


class Suspend(Case):
    def test_suspend_ends_sign_in_links_and_the_shop(self):
        out = self.admin("suspend", "--", self.new["id"])
        self.assertIn("suspended: 1 links ended, shop removed", out)
        status, _, resp = self.s.request("GET", f"{V}/me/shop", headers=self.new["auth"])
        self.assertIn(status, (401, 403), resp)
        self.public(self.new_shop["shop_id"], expect=410, token=False)
        state = self.s.conn.execute("SELECT state FROM shares WHERE id = ?", (self.new_link["share_id"],)).fetchone()[0]
        self.assertNotEqual(state, "active")
        self.assertEqual(self.s.conn.execute("SELECT state FROM identities WHERE id = ?", (self.new["id"],)).fetchone()[0],
                         "suspended")
        self.assertIn("active", self.admin("unsuspend", "--", self.new["id"]))


class Claims(Case):
    def test_one_network_holds_at_most_a_few_waiting_claims(self):
        links = [self.link, self.new_link, self.sell(self.kept()["item_id"])]
        made, n = 0, 0
        while made < sales.MAX_OPEN_CLAIMS_48:      # 3 a link from one /24 an hour, 2 from one address: spread them
            self.claim(links[made // 3], ip=f"198.51.100.{n + 1}")
            made, n = made + 1, n + 1
        got = self.claim(links[2], expect=429, ip="198.51.100.250")          # the same /24: its open claims are full
        self.assertIn("payments open", got["error"]["message"])
        self.claim(links[2], ip="203.0.113.9")                               # another network is fine

    def test_proof_of_work_hardens_as_open_claims_fill(self):
        from types import SimpleNamespace
        ctx = lambda: api.Ctx(self.s.app, SimpleNamespace(ip="127.0.0.1"), self.s.now)   # noqa: E731
        self.assertEqual((ctx().pow_floor("claim"), ctx().pow_floor("upload")), (0, 0))
        base = self.s.app.pow.base("claim")
        real = sales.MAX_OPEN_CLAIMS
        try:
            sales.MAX_OPEN_CLAIMS = 4
            self.claim(self.link, ip="198.18.1.1")
            self.claim(self.link, ip="198.18.2.1")
            self.assertEqual(ctx().pow_floor("claim"), base + 2)
            self.claim(self.link, ip="198.18.3.1")                           # solved at the harder level, as the app does
            self.assertEqual(ctx().pow_floor("claim"), base + 4)
        finally:
            sales.MAX_OPEN_CLAIMS = real


class InFlight(unittest.TestCase):
    def test_the_total_is_capped_and_says_so(self):
        flight = api.InFlight()
        caps = lambda n: ((bytes([n]), 32), (bytes([n, 0]), 128))   # noqa: E731
        for n in range(3):
            self.assertEqual(flight.take(caps(n), total=3), "ok")
        self.assertEqual(flight.take(caps(9), total=3), "total")
        self.assertEqual(flight.take(caps(9), total=None), "ok")             # the health route isn't counted against it
        for _ in range(31):
            flight.take(caps(1))
        self.assertEqual(flight.take(caps(1)), "network")


if __name__ == "__main__":
    unittest.main()
