# SPDX-License-Identifier: MIT
"""Pay to open, the release gate (research 16-drive-design §4; annex 16-drive-architecture §1.1, §1.9), on the
fake chain only (the bug-hunt rule keeps forged outputs off the public testnet).

R2: a view key proves an output's amount and memo, never who can spend it, so a payer can build an
output the seller's view key opens while keeping its one-time key (the trick R1 closed for packs). We
hold no owner key of the seller's, so we can't check. Hence: test money our demo wallet built for the
whole price releases at `paid`; every other payment waits at `owner_check = 'pending'` until the
owner's drive compares the outputs' one-time keys with its own and confirms (`ok` releases, `bad`
voids). The gate must hold however often the buyer polls, and only the owner may answer.
"""
from paid_fixture import V, PaidCase
from mutis import codec
from mutis.fake_chain import fake_keys


class ReleaseGate(PaidCase):
    def setUp(self):
        super().setUp()
        self.ready_seller()
        self.link = self.sell(self.kept()["item_id"])
        self.c = self.claim(self.link)
        self.utxo = "utxo_" + "0" * 64

    def confirm(self, check: str, headers: dict | None = None, utxo: str | None = None, expect: int = 200) -> dict:
        utxo = utxo or self.utxo
        status, _, resp = self.s.request("POST", f"{V}/me/sales/claims/{self.c['claim_id']}/confirm",
                                         {"utxo_id": utxo, "spendable": check == "ok"},
                                         headers=self.d["auth"] if headers is None else headers)
        self.assertEqual(status, expect, resp)
        return resp

    def to_check(self) -> list:
        return self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["to_check"]

    def test_a_payment_from_a_wallet_never_releases_before_the_owners_check(self):
        utxo = self.utxo = self.pay(self.c)
        self.ticks()
        for _ in range(5):
            got = self.poll(self.c)
            self.assertEqual((got["status"], got["owner_check"]), ("paid", "pending"))
            self.assertNotIn("server_half", got)
        self.assertEqual(self.open(self.link, self.c, 402)["error"]["code"], "payment_required")
        self.assertEqual(self.to_check(), [{"claim_id": self.c["claim_id"], "share_id": self.link["share_id"],
                                            "paid_at": self.row(self.c)["paid_at"], "amount_ut": "100000",
                                            "received_ut": "100000", "utxo_ids": [utxo]}])

    def test_payments_list_for_received(self):
        """§10 track two step 5: GET /me/sales lists this drive's payments with their link, the
        test money mark, the chain check and the owner's answer; only the owner sees it."""
        utxo = self.pay(self.c)
        self.ticks()
        paid = self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["paid"]
        self.assertEqual(len(paid), 1)
        self.assertEqual({k: paid[0][k] for k in ("utxo_id", "share_id", "value_ut", "demo", "owner_ok", "tx_id")},
                         {"utxo_id": utxo, "share_id": self.link["share_id"], "value_ut": "100000", "demo": False,
                          "owner_ok": None, "tx_id": None})
        self.confirm("ok", utxo=utxo)
        self.assertTrue(self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["paid"][0]["owner_ok"])
        self.assertEqual(self.s.request("GET", f"{V}/me/sales")[0], 401)

    def test_earnings_totals_by_link(self):
        """Earnings: GET /me/sales adds what each paid link took in, and the drive's total, over every payment we can
        vouch for: test money our demo wallet paid, and payments the owner's drive checked are its own. A payment still
        waiting for that check counts once it is checked; one the payer kept counts nowhere, though the list shows it."""
        def sales():
            return self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]

        empty = sales()
        self.assertEqual((empty["total"], empty["links"]), ({"received_ut": "0", "test_ut": "0", "payments": 0, "links": 0}, []))
        self.utxo = self.pay(self.c)                             # 0.1 tTARI from a wallet, checked by the drive
        self.ticks()
        self.confirm("ok")
        self.poll(self.c)
        self.open(self.link, self.c)
        test = self.claim(self.link)                             # test money, from our demo wallet
        status, _, _ = self.s.request("POST", f"{V}/p/{self.link['share_id']}/claims/{test['claim_id']}/demo-pay",
                                      {"pow": self.s.solve("demo_pay")}, headers=test["hdr"])
        self.assertEqual(status, 202)
        self.ticks()
        forged = self.claim(self.link)                           # the payer keeps the key: the drive says bad
        kept = self.pay(forged, spender=fake_keys()["address"])
        self.ticks()
        status, _, _ = self.s.request("POST", f"{V}/me/sales/claims/{forged['claim_id']}/confirm",
                                      {"utxo_id": kept, "spendable": False}, headers=self.d["auth"])
        self.assertEqual(status, 200)
        other = self.sell(self.kept()["item_id"], price="250000")
        waiting = self.claim(other)
        late = self.pay(waiting)                                 # paid, not checked yet
        self.ticks()
        self.assertEqual(sales()["total"], {"received_ut": "200000", "test_ut": "100000", "payments": 2, "links": 1})
        status, _, _ = self.s.request("POST", f"{V}/me/sales/claims/{waiting['claim_id']}/confirm",
                                      {"utxo_id": late, "spendable": True}, headers=self.d["auth"])
        self.assertEqual(status, 200)
        got = sales()
        self.assertEqual(got["total"], {"received_ut": "450000", "test_ut": "100000", "payments": 3, "links": 2})
        self.assertEqual([{k: x[k] for k in ("share_id", "received_ut", "test_ut", "payments", "views_used")}
                          for x in got["links"]],
                         [{"share_id": other["share_id"], "received_ut": "250000", "test_ut": "0", "payments": 1,
                           "views_used": 0},
                          {"share_id": self.link["share_id"], "received_ut": "200000", "test_ut": "100000", "payments": 2,
                           "views_used": 1}])
        self.assertTrue(all(isinstance(x["last_at"], int) for x in got["links"]))
        self.assertEqual(len(got["paid"]), 4)                    # the list still shows the kept one, marked
        self.assertIs(next(p for p in got["paid"] if p["utxo_id"] == kept)["owner_ok"], False)
        part = self.claim(other)                                 # a part of the price: the check never reaches it
        self.pay(part, 40000)
        self.ticks()
        self.assertEqual(sales()["total"]["received_ut"], "450000")
        self.assertEqual(len(sales()["paid"]), 5)

    def test_the_owners_ok_releases_on_the_next_poll(self):
        self.utxo = self.pay(self.c)
        self.ticks()
        self.assertEqual(self.confirm("ok"), {"claim_id": self.c["claim_id"], "status": "paid", "owner_check": "ok"})
        got = self.poll(self.c)
        self.assertEqual((got["status"], codec.unb64u(got["server_half"])), ("released", self.link["half"]))
        self.open(self.link, self.c)
        self.assertEqual(self.to_check(), [])

    def test_a_forgery_the_owner_marks_bad_is_void(self):
        """The R2 forgery on the fake chain: the seller's view key opens it, the payer keeps the spend key."""
        payer = fake_keys()
        self.utxo = self.pay(self.c, spender=payer["address"])
        self.ticks()
        self.assertEqual(self.row(self.c)["status"], "paid")    # amount proven and committed: we can't tell
        self.assertEqual(self.confirm("bad"), {"claim_id": self.c["claim_id"], "status": "void", "owner_check": "bad"})
        got = self.poll(self.c)
        self.assertEqual((got["status"], "server_half" in got), ("void", False))
        self.assertEqual(self.open(self.link, self.c, 402)["error"]["code"], "payment_required")
        self.confirm("ok", expect=409)                          # a void claim can't come back

    def test_two_outputs_release_only_when_both_are_the_owners(self):
        first = self.pay(self.c, 40000)
        self.ticks()
        second = self.pay(self.c, 60000)
        self.ticks()
        self.assertEqual([c["utxo_ids"] for c in self.to_check()], [[first, second]])
        self.assertEqual(self.confirm("ok", utxo=first)["owner_check"], "pending")
        self.assertNotIn("server_half", self.poll(self.c))
        self.assertEqual([c["utxo_ids"] for c in self.to_check()], [[second]])
        self.assertEqual(self.confirm("ok", utxo=second)["owner_check"], "ok")
        self.assertEqual(self.poll(self.c)["status"], "released")

    def test_test_money_releases_at_paid_without_a_check(self):
        status, _, _ = self.s.request("POST", f"{V}/p/{self.link['share_id']}/claims/{self.c['claim_id']}/demo-pay",
                                      {"pow": self.s.solve("demo_pay")}, headers=self.c["hdr"])
        self.assertEqual(status, 202)
        self.ticks()
        self.assertEqual(self.poll(self.c)["status"], "released")
        self.assertEqual(self.to_check(), [])
        self.confirm("bad", expect=409)                         # nothing to check on money we built

    def test_only_the_owner_answers_and_only_for_a_paid_claim(self):
        early = self.confirm("ok", expect=409)                  # still pending: nothing paid yet (the drive retries)
        self.assertEqual(early["error"]["details"], {"status": "pending"})
        self.utxo = self.pay(self.c)
        self.ticks()
        other = self.s.register()
        self.confirm("ok", headers={}, expect=401)
        self.confirm("ok", headers=other["auth"], expect=404)
        self.confirm("ok", utxo="utxo_" + "1" * 64, expect=409)   # not an output that paid this claim
        status, _, _ = self.s.request("POST", f"{V}/me/sales/claims/{self.c['claim_id']}/confirm",
                                      {"utxo_id": self.utxo, "spendable": "yes"}, headers=self.d["auth"])
        self.assertEqual(status, 422)
        self.assertEqual(self.row(self.c)["owner_check"], "pending")

    def test_the_owner_ending_the_link_before_the_check_voids_the_claim(self):
        self.utxo = self.pay(self.c)
        self.ticks()
        self.s.request("DELETE", f"{V}/s/{self.link['share_id']}", headers=self.d["auth"])
        self.assertEqual(self.row(self.c)["status"], "void")
        self.confirm("ok", expect=409)


del PaidCase
