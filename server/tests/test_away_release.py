# SPDX-License-Identifier: MIT
"""Release without the seller's drive (features.away_release, docs/mvp-november.md §2), on the fake chain only.

Since Ootle 0.48 a stealth output's one-time key is H(network ‖ v·R)·G + K: the sales view key, which our payment
checker already holds, and the account key K in the seller's address are enough to tell whether the seller can spend
a payment, as a watch-only wallet tells. With the flag on, the chain worker runs that check when it counts each sale
payment: the seller's to spend releases the claim with no drive online; the payer's own key (the R2 forgery) voids it,
and it never counts toward the claim. With the flag off, or when the check can't tell, nothing changes: the claim
waits for the owner's drive (test_release_gate.py). The real check (the official library and lib/ristretto.js) is in
web/app/tests/ristretto.test.js and the sidecar's selftest; here the fake sidecar stands in for it.
"""
from unittest import mock

from paid_fixture import V, PaidCase
from mutis import codec, db, sales, withdraw
from mutis.fake_chain import fake_keys


class AwayRelease(PaidCase):
    def setUp(self):
        super().setUp()
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "features", {"away_release": True, "withdraw": True})
        self.ready_seller()
        self.link = self.sell(self.kept()["item_id"])
        self.c = self.claim(self.link)

    def pays(self, claim=None) -> list:
        return [tuple(r) for r in self.s.conn.execute(
            "SELECT value_ut, status, owner_ok, checked_by FROM sale_payments WHERE claim_id = ? ORDER BY seen_at, value_ut",
            ((claim or self.c)["claim_id"],))]

    def to_check(self) -> list:
        return self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["to_check"]

    def test_a_wallet_payment_releases_with_no_drive_online(self):
        utxo = self.pay(self.c)
        self.ticks()
        row = self.row(self.c)
        self.assertEqual((row["status"], row["owner_check"], row["demo"]), ("paid", "ok", 0))
        self.assertEqual(self.pays(), [(100000, "counted", 1, "server")])
        self.assertEqual(self.to_check(), [])                       # nothing waits for the owner's drive
        got = self.poll(self.c)
        self.assertEqual((got["status"], codec.unb64u(got["server_half"])), ("released", self.link["half"]))
        self.open(self.link, self.c)
        paid = self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["paid"]
        self.assertEqual([(p["utxo_id"], p["owner_ok"], p["checked_by"]) for p in paid], [(utxo, True, "server")])
        # Checked money is settled: withdrawable at once, and counted in Earnings.
        outs = self.s.request("GET", f"{V}/me/sales/outputs", headers=self.d["auth"])[2]["outputs"]
        self.assertEqual([o["utxo_id"] for o in outs], [utxo])
        self.assertEqual(self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["total"]["received_ut"], "100000")

    def test_the_r2_forgery_is_void_at_once_and_never_counts(self):
        """The seller's view key opens it and proves the amount; the payer kept the one-time key."""
        payer = fake_keys()
        self.pay(self.c, spender=payer["address"])
        self.ticks()
        row = self.row(self.c)
        self.assertEqual((row["status"], row["owner_check"], row["received_ut"]), ("void", "bad", 0))
        self.assertEqual(self.pays(), [(100000, "counted", 0, "server")])
        got = self.poll(self.c)
        self.assertEqual((got["status"], "server_half" in got), ("void", False))
        self.assertEqual(self.open(self.link, self.c, 402)["error"]["code"], "payment_required")
        self.assertEqual(self.s.request("GET", f"{V}/me/sales/outputs", headers=self.d["auth"])[2]["outputs"], [])
        self.assertEqual(self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]["total"]["received_ut"], "0")

    def test_a_condition_tree_never_releases_on_our_word(self):
        """Whoever meets a condition tree can spend the output, not the seller alone: our checker can't vouch for it,
        so it waits for the owner's drive, as every payment did before."""
        self.s.chain.add_output(self.c["address"], 100000, None, auth={"Conditions": {"root": "00" * 32}})
        self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["owner_check"]), ("paid", "pending"))
        self.assertEqual(self.pays(), [(100000, "counted", None, None)])
        self.assertNotIn("server_half", self.poll(self.c))

    def test_a_selftest_that_fails_leaves_every_sale_to_the_drive(self):
        real = self.s.worker.sidecar.request

        def failing(cmd, **kw):
            if cmd == "selftest":
                return {"passed": False, "cases": [{"name": "ristretto255: a·G + b·G = (a + b)·G (1)", "passed": False}]}
            return real(cmd, **kw)

        self.s.worker._watch_selftest = None
        with mock.patch.object(self.s.worker.sidecar, "request", side_effect=failing):
            self.pay(self.c)
            self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["owner_check"]), ("paid", "pending"))
        self.assertIs(self.s.worker._watch_selftest, False)

    def test_a_selftest_the_sidecar_refuses_is_not_trusted_and_sales_still_count(self):
        from mutis.sidecar import SidecarError
        real = self.s.worker.sidecar.request

        def refuses(cmd, **kw):
            if cmd == "selftest":
                raise SidecarError("internal")
            return real(cmd, **kw)

        self.s.worker._watch_selftest = None
        with mock.patch.object(self.s.worker.sidecar, "request", side_effect=refuses):
            self.pay(self.c)
            self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["owner_check"]), ("paid", "pending"))
        self.assertIs(self.s.worker._watch_selftest, False)

    def test_a_selftest_that_didnt_pass_runs_again_later(self):
        from mutis import chain_worker
        self.s.worker._watch_selftest, self.s.worker._watch_checked_at = False, 0.0
        with mock.patch.object(chain_worker.time, "monotonic", return_value=chain_worker.WATCH_RETRY_S - 1):
            self.assertFalse(self.s.worker._watch_check_ok())                 # not yet
        with mock.patch.object(chain_worker.time, "monotonic", return_value=chain_worker.WATCH_RETRY_S + 1):
            self.assertTrue(self.s.worker._watch_check_ok())                  # ran again, and passed

    def test_a_sidecar_without_the_watch_cases_is_not_trusted(self):
        """An older sidecar passes its selftest without the watch-only cases: not enough."""
        real = self.s.worker.sidecar.request
        old = {"passed": True, "cases": [{"name": "real output 1 opens", "passed": True}]}
        for reply in ({"passed": True, "cases": 0}, {"passed": True}):         # no list of cases: not trusted either
            self.s.worker._watch_selftest = None
            with mock.patch.object(self.s.worker.sidecar, "request", side_effect=lambda cmd, r=reply, **kw: r if cmd == "selftest" else real(cmd, **kw)):
                self.assertFalse(self.s.worker._watch_check_ok())
        self.s.worker._watch_selftest = None
        with mock.patch.object(self.s.worker.sidecar, "request", side_effect=lambda cmd, **kw: old if cmd == "selftest" else real(cmd, **kw)):
            self.pay(self.c)
            self.ticks()
        self.assertEqual(self.row(self.c)["owner_check"], "pending")

    def test_a_partial_forgery_voids_the_claim_and_the_honest_part_stays_the_sellers(self):
        honest = self.pay(self.c, 40000)
        self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["received_ut"]), ("seen", 40000))
        self.pay(self.c, 60000, spender=fake_keys()["address"])
        self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["received_ut"]), ("void", 40000))
        outs = self.s.request("GET", f"{V}/me/sales/outputs", headers=self.d["auth"])[2]["outputs"]
        self.assertEqual([o["utxo_id"] for o in outs], [honest])     # the seller's own money, withdrawable

    def test_two_honest_outputs_release_when_the_second_completes_the_price(self):
        self.pay(self.c, 40000)
        self.ticks()
        self.assertNotIn("server_half", self.poll(self.c))
        self.pay(self.c, 60000)
        self.ticks()
        self.assertEqual(self.pays(), [(40000, "counted", 1, "server"), (60000, "counted", 1, "server")])
        self.assertEqual(self.poll(self.c)["status"], "released")

    def test_an_extra_payment_is_checked_too_and_becomes_withdrawable(self):
        self.pay(self.c, 100000)
        self.ticks()
        self.claim(self.link)                                       # keeps the seller scanned
        extra = self.pay(self.c, 70000)
        self.ticks()
        self.assertEqual(self.pays()[-1], (70000, "extra", 1, "server"))
        outs = self.s.request("GET", f"{V}/me/sales/outputs", headers=self.d["auth"])[2]["outputs"]
        self.assertIn(extra, [o["utxo_id"] for o in outs])

    def test_the_drive_can_still_refuse_a_payment_before_its_buyer_opens(self):
        utxo = self.pay(self.c)
        self.ticks()
        status, _, resp = self.s.request("POST", f"{V}/me/sales/claims/{self.c['claim_id']}/confirm",
                                         {"utxo_id": utxo, "spendable": False}, headers=self.d["auth"])
        self.assertEqual((status, resp["status"], resp["owner_check"]), (200, "void", "bad"))
        self.assertEqual(self.pays(), [(100000, "counted", 0, "drive")])
        self.assertEqual(self.poll(self.c)["status"], "void")

    def test_when_the_check_cant_tell_the_owners_drive_decides_as_before(self):
        from mutis.sidecar import SidecarError
        utxo = self.pay(self.c)
        real = self.s.worker.sidecar.request

        def refuses(cmd, **kw):                                      # the library refuses: can't tell
            if cmd == "watchOneTimeKey":
                raise SidecarError("failed")
            return real(cmd, **kw)

        with mock.patch.object(self.s.worker.sidecar, "request", side_effect=refuses):
            self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["owner_check"]), ("paid", "pending"))
        self.assertEqual(self.pays(), [(100000, "counted", None, None)])
        self.assertEqual([c["utxo_ids"] for c in self.to_check()], [[utxo]])
        status, _, resp = self.s.request("POST", f"{V}/me/sales/claims/{self.c['claim_id']}/confirm",
                                         {"utxo_id": utxo, "spendable": True}, headers=self.d["auth"])
        self.assertEqual((status, resp["owner_check"]), (200, "ok"))
        self.assertEqual(self.pays(), [(100000, "counted", 1, "drive")])
        self.assertEqual(self.poll(self.c)["status"], "released")

    def test_a_payment_to_an_address_that_isnt_the_claims_is_left_to_the_drive(self):
        """The seller registered another sales address since this claim was made: the view key in memory is the new
        address's, so our checker doesn't judge a payment to the old one."""
        seller = self.s.conn.execute("SELECT address FROM sellers").fetchone()[0]
        row = {"utxo_id": "utxo_" + "0" * 64, "claim_id": self.c["claim_id"], "owner_id": self.d["id"],
               "seller_address": seller, "claim_address": self.c["address"]}
        nonce, key = "22" * 32, "33" * 32
        self.assertIs(self.s.worker._sale_owns(row, nonce, key), False)          # judged: the key isn't the seller's
        self.assertIsNone(self.s.worker._sale_owns({**row, "claim_address": fake_keys()["address"]}, nonce, key))
        self.assertIsNone(self.s.worker._sale_owns({**row, "claim_id": None}, nonce, key))
        self.assertIsNone(self.s.worker._sale_owns(row, None, key))
        self.assertIsNone(self.s.worker._sale_owns(row, nonce, None))

    def test_the_sidecar_down_stops_the_step_and_the_payment_waits(self):
        from mutis.sidecar import SidecarError
        self.pay(self.c)
        self.s.worker.mirror(self.s.now)
        with mock.patch.object(sales, "check_pending"):
            self.s.worker.verify_sales(self.s.now)               # found and seen
        real = self.s.worker.sidecar.request

        def down(cmd, **kw):
            if cmd == "watchOneTimeKey":
                raise SidecarError("timeout")
            return real(cmd, **kw)

        with mock.patch.object(self.s.worker.sidecar, "request", side_effect=down):
            with self.assertRaises(SidecarError):
                self.s.worker.verify_sales(self.s.now)
        self.assertEqual(self.pays(), [(100000, "pending_check", None, None)])
        self.ticks()
        self.assertEqual(self.row(self.c)["owner_check"], "ok")

    def test_off_means_the_drive_checks_as_before(self):
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "features", {"away_release": False})
        self.pay(self.c)
        self.ticks()
        self.assertEqual((self.row(self.c)["status"], self.row(self.c)["owner_check"]), ("paid", "pending"))
        self.assertEqual(self.pays(), [(100000, "counted", None, None)])

    def test_config_says_so(self):
        cfg = self.s.request("GET", f"{V}/config")[2]
        self.assertIn("away_release", cfg["features"])


del PaidCase, withdraw
