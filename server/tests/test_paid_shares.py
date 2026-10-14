# SPDX-License-Identifier: MIT
"""Pay to open, the API (research 16-drive-design §4, annex 16-drive-architecture §1.4, §1.5, §1.8): the
sales address, paid links, the pay page, claims with PoW and caps, the open gate (402/403/410), pausing,
ending a link (our half of the key scrubbed, waiting claims void), the owner's summary, and the guards on
test money. The worker's side is test_sales_worker.py; the release gate, test_release_gate.py.
"""
import hashlib
import secrets

from paid_fixture import V, PaidCase, b64
from mutis import codec, db, ootle_addr, sales


class SalesAddress(PaidCase):
    chain = False

    def test_put_registers_and_replaces_the_sales_address(self):
        self.assertEqual(self.register_seller()[0], 204)
        row = self.s.conn.execute("SELECT * FROM sellers").fetchone()
        self.assertEqual((row["identity_id"], row["address"], row["state"], len(row["view_sealed"])),
                         (self.d["id"], self.sales_keys["address"], "pending", 125))
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE sellers SET state = 'ok', scan_seq = 99")
        self.assertEqual(self.register_seller()[0], 204)       # a replacement is checked again from the start
        row = self.s.conn.execute("SELECT state, scan_seq FROM sellers").fetchone()
        self.assertEqual(tuple(row), ("pending", 0))
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM sellers").fetchone()[0], 1)

    def test_put_refuses_a_reference_a_short_blob_no_session_and_too_many(self):
        keys = self.sales_keys
        with_ref = ootle_addr.with_pay_ref(keys["address"], b"clm_x")
        cases = [({"address": with_ref, "view_sealed": b64(125)}, self.d["auth"], 422),
                 ({"address": keys["address"], "view_sealed": b64(124)}, self.d["auth"], 422),
                 ({"address": "otl_esm_nope", "view_sealed": b64(125)}, self.d["auth"], 422),
                 ({"address": keys["address"], "view_sealed": b64(125)}, {}, 401)]
        for body, headers, expect in cases:
            self.assertEqual(self.s.request("PUT", f"{V}/me/sales", body, headers=headers)[0], expect, body)
        for _ in range(sales.SALES_PUT_PER_DAY):
            self.assertEqual(self.register_seller()[0], 204)
        self.assertEqual(self.register_seller()[0], 429)

    def test_get_sales_shows_the_registration_and_nothing_to_check(self):
        self.register_seller()
        _, _, got = self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])
        self.assertEqual(got, {"seller": {"address": self.sales_keys["address"], "state": "pending"}, "to_check": []})


class PaidLinks(PaidCase):
    chain = False

    def setUp(self):
        super().setUp()
        self.ready_seller()
        self.item = self.kept()

    def test_a_paid_link_is_a_plain_link_row_plus_its_price_and_our_half(self):
        link = self.sell(self.item["item_id"], price="250000")
        self.assertEqual(link["path"], f"/p/{link['share_id']}")
        self.assertEqual((link["max_views"], link["expires_at"]), (None, None))
        share = self.s.conn.execute("SELECT * FROM shares WHERE id = ?", (link["share_id"],)).fetchone()
        paid = self.s.conn.execute("SELECT * FROM paid_shares WHERE share_id = ?", (link["share_id"],)).fetchone()
        self.assertEqual(share["mode"], "link")
        self.assertEqual((paid["price_ut"], paid["server_half"], paid["buyer_views"], paid["buyer_window_s"]),
                         (250000, link["half"], sales.BUYER_VIEWS, sales.BUYER_WINDOW_S))
        _, _, st = self.s.request("GET", f"{V}/s/{link['share_id']}")
        self.assertIs(st["paid"], True)                        # the viewer moves to /p/{id}

    def test_create_refuses_what_cant_be_sold(self):
        item = self.item["item_id"]
        self.sell(item, price="123456", expect=422)            # only the prices /config offers
        self.sell(item, max_views=3, expect=422)               # a paid link has no rule of its own
        self.sell(item, then_delete=True, expect=422)
        anon = self.s.upload(1000)                              # not a drive's kept file
        self.sell(anon["item_id"], expect=422, d={"auth": anon["manage"]})
        other = self.s.register()
        theirs = self.kept(d=other)
        self.sell(theirs["item_id"], expect=409, d=other)      # no sales address registered: seller_not_registered
        self.sell(theirs["item_id"], expect=403)               # not ours at all
        self.sell(item)
        self.sell(item, expect=409)                            # one paid link per item at a time

    def test_create_needs_the_feature_and_sidecar_proofs(self):
        self.s.close()
        for overrides in ({"features": {"pay_to_open": False}}, {"gates": {"amount_proof": "wallet"}}):
            self.s = self.s.__class__(overrides)
            d = self.s.register()
            item = self.s.upload(1000, headers=d["auth"], retention="kept", owner_wrap=b64(60))
            status, _, resp = self.s.request("POST", f"{V}/items/{item['item_id']}/shares", {
                "mode": "pay", "wrapped_key": b64(60), "access_verifier": b64(32), "server_half": b64(32),
                "price_ut": "100000"}, headers=d["auth"])
            self.assertEqual((status, resp["error"]["code"]), (503, "feature_disabled"))
            self.s.close()
        self.s = self.s.__class__()

    def test_the_pay_page_shows_only_what_a_buyer_needs(self):
        link = self.sell(self.item["item_id"])
        status, _, page = self.s.request("GET", f"{V}/p/{link['share_id']}", headers={"Authorization": "Bearer junk"})
        self.assertEqual(status, 200, page)                    # a session header on /p/* is ignored
        self.assertEqual(set(page), {"state", "price_ut", "fee_ut", "buyer_views", "buyer_window_s", "kind",
                                     "size_stored", "child_count", "teaser_ct", "seller", "testnet"})
        self.assertEqual((page["state"], page["price_ut"], page["kind"], page["seller"], page["testnet"]),
                         ("selling", "100000", "file", {"ready": True}, True))
        self.assertNotIn(self.sales_keys["address"][:30], repr(page))   # never the seller's base address
        plain = self.s.share({"item_id": self.item["item_id"]}, headers=self.d["auth"], max_views=1)
        self.assertEqual(self.s.request("GET", f"{V}/p/{plain['share_id']}")[0], 404)

    def test_a_folder_page_counts_its_files(self):
        top = self.folder()
        for _ in range(3):
            self.s.upload(1000, headers=self.d["auth"], retention="kept", owner_wrap=b64(60), parent_id=top,
                          parent_wrap=b64(60))
        page = self.s.request("GET", f"{V}/p/{self.sell(top)['share_id']}")[2]
        self.assertEqual((page["kind"], page["child_count"]), ("folder", 3))
        self.assertGreater(page["size_stored"], 0)

    def test_a_claim_needs_pow_and_gets_its_own_address(self):
        link = self.sell(self.item["item_id"])
        status, _, resp = self.s.request("POST", f"{V}/p/{link['share_id']}/claims", {"claim_verifier": b64(32)})
        self.assertEqual((status, resp["error"]["code"]), (428, "pow_required"))
        claim = self.claim(link)
        self.assertRegex(claim["claim_id"], r"^clm_[a-z2-7]{20}$")
        self.assertEqual(claim["address"], ootle_addr.with_pay_ref(self.sales_keys["address"], claim["claim_id"].encode()))
        self.assertEqual((claim["amount_ut"], claim["status"], claim["expires_at"]),
                         ("100000", "pending", self.s.now + sales.CLAIM_TTL_S))
        cols = [r[1] for r in self.s.conn.execute("PRAGMA table_info(claims)")]
        self.assertFalse({"identity_id", "ip", "ip64", "owner_id"} & set(cols))   # never a drive, never an IP

    def test_claims_are_capped_per_link_and_refused_when_not_for_sale(self):
        link = self.sell(self.item["item_id"])
        with db.tx(self.s.conn):
            for i in range(sales.MAX_OPEN_CLAIMS_PER_SHARE):
                self.s.conn.execute("INSERT INTO claims(id, share_id, token_hash, address, price_ut, status, created_at, "
                                    "created_seq, expires_at) VALUES (?, ?, ?, 'a', 100000, 'pending', ?, 0, ?)",
                                    (f"clm_{i:020d}", link["share_id"], secrets.token_bytes(32), self.s.now,
                                     self.s.now + 3600))
        self.assertEqual(self.claim(link, expect=409)["error"]["code"], "busy")
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE claims SET status = 'expired'")
        self.s.request("PATCH", f"{V}/s/{link['share_id']}", {"paused": True}, headers=self.d["auth"])
        self.assertEqual(self.claim(link, expect=409)["error"]["code"], "not_for_sale")
        self.s.request("PATCH", f"{V}/s/{link['share_id']}", {"paused": False}, headers=self.d["auth"])
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE sellers SET state = 'bad_key'")
        self.assertEqual(self.claim(link, expect=409)["error"]["code"], "seller_not_ready")

    def test_the_claim_token_is_the_only_way_to_read_a_claim(self):
        link = self.sell(self.item["item_id"])
        claim = self.claim(link)
        self.assertEqual(self.poll(claim)["status"], "pending")
        for hdr in ({}, {"X-Mutis-Claim": codec.b64u(secrets.token_bytes(32))}, {"X-Mutis-Claim": "short"}):
            status, _, resp = self.s.request("GET", f"{V}/p/{link['share_id']}/claims/{claim['claim_id']}", headers=hdr)
            self.assertEqual((status, resp["error"]["code"]), (403, "bad_claim"))
        missing = "clm_" + "a" * 20
        self.assertEqual(self.s.request("GET", f"{V}/p/{link['share_id']}/claims/{missing}", headers=claim["hdr"])[0], 404)

    def released(self, link: dict, views: int = 3, until: int | None = None) -> dict:
        claim = self.claim(link)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE claims SET status = 'released', received_ut = price_ut, released_at = ?, "
                                "views_left = ?, open_until = ? WHERE id = ?",
                                (self.s.now, views, until or self.s.now + 3600, claim["claim_id"]))
        return claim

    def test_open_gate_402_403_410_and_each_open_spends_one(self):
        link = self.sell(self.item["item_id"])
        self.assertEqual(self.open(link, None, 402)["error"]["code"], "payment_required")
        waiting = self.claim(link)
        self.assertEqual(self.open(link, waiting, 402)["error"]["code"], "payment_required")
        stranger = {"hdr": {"X-Mutis-Claim": codec.b64u(secrets.token_bytes(32))}}
        self.assertEqual(self.open(link, stranger, 403)["error"]["code"], "bad_claim")
        claim = self.released(link, views=2)
        self.assertEqual(self.open(link, {"hdr": {}}, 402)["error"]["code"], "payment_required")
        self.open(link, claim)
        self.assertEqual(self.row(claim)["views_left"], 1)
        self.open(link, claim)
        used = self.open(link, claim, 410)
        self.assertEqual((used["error"]["code"], used["error"]["details"]["reason"]), ("claim_used", "no_opens_left"))
        late = self.released(link, until=self.s.now + 5)
        self.s.now += 10
        self.assertEqual(self.open(link, late, 410)["error"]["details"]["reason"], "window_over")

    def test_a_link_without_its_key_still_needs_the_key(self):
        link = self.sell(self.item["item_id"])
        claim = self.released(link)
        status, _, resp = self.s.request("POST", f"{V}/s/{link['share_id']}/open",
                                         headers={"X-Mutis-Access": b64(32), **claim["hdr"]})
        self.assertEqual((status, resp["error"]["code"]), (403, "bad_access"))
        self.assertEqual(self.row(claim)["views_left"], 3)      # a refused open spends nothing

    def test_peek_and_stored_bytes_need_the_claim_too(self):
        link = self.sell(self.item["item_id"])
        self.assertEqual(self.s.request("POST", f"{V}/s/{link['share_id']}/peek", {}, headers=link["access"])[0], 402)
        self.assertEqual(self.s.request("GET", f"{V}/s/{link['share_id']}/stored", headers=link["access"])[0], 402)
        claim = self.released(link)
        hdr = {**link["access"], **claim["hdr"]}
        self.assertEqual(self.s.request("POST", f"{V}/s/{link['share_id']}/peek", {}, headers=hdr)[0], 200)
        self.assertEqual(self.s.request("GET", f"{V}/s/{link['share_id']}/stored", headers=hdr)[0], 200)
        self.assertEqual(self.row(claim)["views_left"], 3)

    def test_pausing_stops_new_claims_and_keeps_released_opens(self):
        link = self.sell(self.item["item_id"])
        claim = self.released(link)
        status, _, resp = self.s.request("PATCH", f"{V}/s/{link['share_id']}", {"paused": True}, headers=self.d["auth"])
        self.assertEqual((status, resp["paused"]), (200, True))
        self.assertEqual(self.s.request("GET", f"{V}/p/{link['share_id']}")[2]["state"], "paused")
        self.claim(link, expect=409)
        self.open(link, claim)
        plain = self.s.share({"item_id": self.item["item_id"]}, headers=self.d["auth"], max_views=1)
        self.assertEqual(self.s.request("PATCH", f"{V}/s/{plain['share_id']}", {"paused": True},
                                        headers=self.d["auth"])[0], 422)
        self.assertEqual(self.s.request("PATCH", f"{V}/s/{link['share_id']}", {"max_views": 2},
                                        headers=self.d["auth"])[0], 422)

    def test_ending_the_link_scrubs_our_half_and_voids_waiting_claims(self):
        link = self.sell(self.item["item_id"])
        waiting, released = self.claim(link), self.released(link)
        self.assertEqual(self.s.request("DELETE", f"{V}/s/{link['share_id']}", headers=self.d["auth"])[0], 204)
        paid = self.s.conn.execute("SELECT server_half FROM paid_shares WHERE share_id = ?", (link["share_id"],)).fetchone()
        self.assertIsNone(paid["server_half"])
        self.assertEqual(self.row(waiting)["status"], "void")
        self.assertEqual((self.row(released)["status"], self.row(released)["views_left"]), ("released", 0))
        self.assertNotIn("server_half", self.poll(released))
        self.assertEqual(self.open(link, released, 410)["error"]["code"], "gone")
        self.assertEqual(self.s.request("GET", f"{V}/p/{link['share_id']}")[0], 410)

    def test_deleting_the_item_ends_its_paid_link(self):
        link = self.sell(self.item["item_id"])
        waiting = self.claim(link)
        self.s.request("DELETE", f"{V}/items/{self.item['item_id']}", headers=self.d["auth"])
        self.assertEqual(self.row(waiting)["status"], "void")
        self.assertIsNone(self.s.conn.execute("SELECT server_half FROM paid_shares").fetchone()[0])

    def test_the_owner_sees_counts_and_earnings_never_who(self):
        link = self.sell(self.item["item_id"])
        self.claim(link)
        claim = self.released(link)
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO sale_payments(utxo_id, claim_id, value_ut, seen_at, committed, status) "
                                "VALUES ('utxo_x', ?, 100000, ?, 1, 'counted')", (claim["claim_id"], self.s.now))
        _, _, m = self.s.request("GET", f"{V}/s/{link['share_id']}/manage", headers=self.d["auth"])
        paid = m["share"]["paid"]
        self.assertEqual((paid["price_ut"], paid["paused"], paid["seller_state"], paid["earned_ut"]),
                         ("100000", False, "ok", "100000"))
        self.assertEqual((paid["counts"]["pending"], paid["counts"]["released"]), (1, 1))
        self.assertEqual(set(paid["recent"][0]), {"ref4", "status", "received_ut", "paid_hour", "released_hour",
                                                  "demo", "owner_check"})
        self.assertEqual(len(paid["recent"][0]["ref4"]), 4)
        _, _, listing = self.s.request("GET", f"{V}/me/items", headers=self.d["auth"])
        entry = next(i for i in listing["items"] if i["item_id"] == self.item["item_id"])
        self.assertEqual(entry["shares"][0]["paid"]["counts"]["released"], 1)
        self.assertNotIn("recent", entry["shares"][0]["paid"])


class TestMoneyGuards(PaidCase):
    chain = False

    def setUp(self):
        super().setUp()
        self.ready_seller()
        self.link = self.sell(self.kept()["item_id"])
        self.c = self.claim(self.link)

    def demo(self, claim: dict, expect: int, headers: dict | None = None) -> dict:
        status, _, resp = self.s.request("POST", f"{V}/p/{claim['share_id']}/claims/{claim['claim_id']}/demo-pay",
                                         {"pow": self.s.solve("demo_pay")}, headers={**claim["hdr"], **(headers or {})})
        self.assertEqual(status, expect, resp)
        return resp

    def test_demo_pay_queues_one_job_to_the_claim_address(self):
        job = self.demo(self.c, 202)
        row = self.s.conn.execute("SELECT * FROM jobs WHERE id = ?", (job["job_id"],)).fetchone()
        import json
        self.assertEqual(json.loads(row["payload"]), {"address": self.c["address"], "amount_ut": "100000",
                                                      "ref": self.c["claim_id"]})
        self.assertEqual(row["slice"], "public")
        self.demo(self.c, 409)                                  # one on its way per claim

    def test_demo_pay_refuses_without_the_token_when_paid_or_when_off(self):
        self.demo({**self.c, "hdr": {"X-Mutis-Claim": b64(32)}}, 403)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE claims SET status = 'paid'")
        self.demo(self.c, 409)
        self.s.close()
        self.s = self.s.__class__({"features": {"demo_pay": False}})
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.ready_seller()
        claim = self.claim(self.sell(self.kept()["item_id"]))
        self.assertEqual(self.demo(claim, 503)["error"]["code"], "feature_disabled")

    def test_a_confirm_from_someone_else_is_refused(self):
        other = self.s.register()
        for headers, expect in (({}, 401), (other["auth"], 404), (self.d["auth"], 409)):
            status, _, _ = self.s.request("POST", f"{V}/me/sales/claims/{self.c['claim_id']}/confirm",
                                          {"utxo_id": "utxo_" + "0" * 64, "spendable": True}, headers=headers)
            self.assertEqual(status, expect)
        self.assertEqual(self.row(self.c)["owner_check"], "none")


class Expiry(PaidCase):
    chain = False

    def test_cleanup_expires_waiting_claims_and_ends_underpaid_ones_after_grace(self):
        self.ready_seller()
        link = self.sell(self.kept()["item_id"])
        nothing, partial = self.claim(link), self.claim(link)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE claims SET status = 'seen', received_ut = 40000 WHERE id = ?",
                                (partial["claim_id"],))
        self.s.now += sales.CLAIM_TTL_S
        self.s.run_cleanup()
        self.assertEqual((self.row(nothing)["status"], self.row(partial)["status"]), ("expired", "underpaid"))
        self.s.now += sales.LATE_GRACE_S
        self.s.run_cleanup()
        self.assertEqual(self.row(partial)["status"], "expired")


del PaidCase
