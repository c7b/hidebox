# SPDX-License-Identifier: MIT
"""Pack payments to the owner's own address (ootle.revenue_address, docs/currencies.md §1): the server holds only that
address's view secret; invoices pay it; the chain worker finds the payments with the view secret and credits them only
once the watch-only check says they are the owner's to spend; a forgery that opens with the view key but keeps its own
spend key is rejected; the hourly reconcile re-opens them; a view key that isn't the address's own credits nothing.
On the fake chain only."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import GiB, Stack  # noqa: E402
from mutis import codec, config, db, ootle_addr, payments  # noqa: E402
from mutis.fake_chain import fake_keys  # noqa: E402

CATALOG = [{"id": "p10", "bytes": 10 * GiB, "days": 30, "price_ut": 250_000_000}]


class Revenue(unittest.TestCase):
    view_key = None              # None: the revenue address's own; a test may put another there

    def setUp(self):
        ootle_addr.use_network("mainnet")
        self.owner = fake_keys()                         # made on the owner's device: the server gets the view secret only
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-revenue-"))
        vk = self.tmp / "revenue.view"
        vk.write_text((self.view_key or self.owner["view_sk"]) + "\n")
        self.s = Stack({"ootle": {"revenue_address": self.owner["address"], "revenue_view_key": str(vk)},
                        "packs": {"catalog": CATALOG}}, network="mainnet", chain=True)
        self.s.disk.total = self.s.disk.avail = 4 << 40
        self.w = self.s.worker
        self.w.setup()
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "evidence_pay_day", codec.day(self.s.now))
        self.drive = self.s.register()

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ticks(self, n: int = 4) -> None:
        for _ in range(n):
            self.s.now += 10
            self.w.tick()

    def invoice(self) -> dict:
        status, _, inv = self.s.request("POST", "/api/v1/invoices", {"pack": "p10"}, headers=self.drive["auth"])
        self.assertEqual(status, 201, inv)
        return inv

    def get(self, inv: dict) -> dict:
        return self.s.request("GET", f"/api/v1/invoices/{inv['invoice_id']}", headers=self.drive["auth"])[2]


class Credits(Revenue):
    def test_invoices_pay_the_owners_address_and_a_payment_credits(self):
        inv = self.invoice()
        self.assertEqual(ootle_addr.base_address(inv["address"]), ootle_addr.base_address(self.owner["address"]))
        self.assertNotEqual(ootle_addr.base_address(inv["address"]), self.s.meta("receiver_address"))
        self.assertEqual(self.s.meta("invoice_address"), ootle_addr.base_address(self.owner["address"]))
        self.s.chain.balances["service"] += int(inv["amount_ut"])
        self.s.chain.transfer("service", inv["address"], int(inv["amount_ut"]), None, 30000)
        self.ticks()
        got = self.get(inv)
        self.assertEqual(got["status"], "credited", got)
        self.assertEqual(got["credited"]["bytes"], 10 * GiB)
        # The hourly reconcile re-opens the credited output with the revenue view key and finds it all there.
        self.assertEqual(payments.reconcile(self.s.conn, lambda rows: {f["id"]: f["value_ut"] for k in
                                                                       (self.w.receiver["view_sk"], self.w.revenue["view_sk"])
                                                                       for f in self.w._scan(k, rows)},
                                            lambda uid: True, self.s.now), "ok")

    def test_a_forgery_that_keeps_its_own_spend_key_is_rejected(self):
        inv = self.invoice()
        payer = fake_keys()
        forged = self.s.chain.add_output(inv["address"], int(inv["amount_ut"]), None, spender=payer["address"])
        self.ticks()
        row = self.s.conn.execute("SELECT status, proven FROM payments WHERE utxo_id = ?", (forged,)).fetchone()
        self.assertEqual(tuple(row), ("rejected", 1))
        self.assertNotEqual(self.get(inv)["status"], "credited")

    def test_the_server_holds_no_key_that_spends_revenue(self):
        self.assertEqual(set(self.w.revenue), {"address", "view_sk"})
        self.assertNotIn(self.owner["owner_sk"], (self.tmp / "revenue.view").read_text())


class WrongViewKey(Revenue):
    view_key = fake_keys()["view_sk"]                 # another address's view key in the file

    def setUp(self):
        with self.assertRaises(Exception):            # setup checks the key against the address, and stops there
            super().setUp()

    def tearDown(self):
        pass

    def test_no_invoice_while_the_key_isnt_the_addresss(self):
        s, w = self.s, self.w
        try:
            self.assertIsNone(w.revenue)
            self.assertEqual(s.meta("invoice_address"), "")
            status, _, body = s.request("POST", "/api/v1/invoices", {"pack": "p10"}, headers=s.register()["auth"])
            self.assertEqual((status, body["error"]["code"]), (503, "chain_unavailable"))   # nobody pays an unwatched address
        finally:
            s.close()
            shutil.rmtree(self.tmp, ignore_errors=True)


class BadKeyLogged(unittest.TestCase):
    def test_a_key_the_sidecar_refuses_logs_critical_and_makes_no_invoice(self):
        from mutis.sidecar import SidecarError
        ootle_addr.use_network("mainnet")
        owner = fake_keys()
        tmp = Path(tempfile.mkdtemp(prefix="mutis-revenue-"))
        (tmp / "revenue.view").write_text(owner["view_sk"])
        s = Stack({"ootle": {"revenue_address": owner["address"], "revenue_view_key": str(tmp / "revenue.view")},
                   "packs": {"catalog": CATALOG}}, network="mainnet", chain=True)
        try:
            real = s.worker.sidecar.request
            s.worker.sidecar.request = lambda cmd, **kw: (_ for _ in ()).throw(SidecarError("bad_key")) \
                if cmd == "watchOneTimeKey" else real(cmd, **kw)
            with self.assertLogs("mutis", "CRITICAL") as logs, self.assertRaises(SidecarError):
                s.worker.setup()
            self.assertIn("event=chain.revenue_bad_key", [r.getMessage() for r in logs.records])
            self.assertEqual(s.meta("invoice_address"), "")
        finally:
            s.close()
            shutil.rmtree(tmp, ignore_errors=True)


class MissingKeyFile(unittest.TestCase):
    def test_fails_closed_then_recovers_once_the_file_is_there(self):
        ootle_addr.use_network("mainnet")
        owner = fake_keys()
        tmp = Path(tempfile.mkdtemp(prefix="mutis-revenue-"))
        vk = tmp / "revenue.view"
        s = Stack({"ootle": {"revenue_address": owner["address"], "revenue_view_key": str(vk)},
                   "packs": {"catalog": CATALOG}}, network="mainnet", chain=True)
        try:
            with self.assertRaises(FileNotFoundError):
                s.worker.setup()
            self.assertEqual((s.worker.invoice_base, s.meta("invoice_address")), (None, ""))
            drive = s.register()
            self.assertEqual(s.request("POST", "/api/v1/invoices", {"pack": "p10"}, headers=drive["auth"])[0], 503)
            vk.write_text(owner["view_sk"])
            s.now += 120
            s.worker.tick()                                # the worker tries the revenue address again
            self.assertEqual(s.meta("invoice_address"), ootle_addr.base_address(owner["address"]))
            status, _, inv = s.request("POST", "/api/v1/invoices", {"pack": "p10"}, headers=drive["auth"])
            self.assertEqual(status, 201, inv)
        finally:
            s.close()
            shutil.rmtree(tmp, ignore_errors=True)


class Settings(unittest.TestCase):
    def test_the_address_is_this_networks_and_the_key_file_comes_with_it(self):
        base = {"public_origin": "https://x.example", "memo_origins": ["https://x.example"]}
        ootle_addr.use_network("esmeralda")
        address = fake_keys()["address"]
        config.from_dict({**base, "ootle": {"revenue_address": address, "revenue_view_key": "/etc/x.view"}})
        for ootle in ({"revenue_address": address}, {"revenue_view_key": "/etc/x.view"},
                      {"revenue_address": "otl_1" + address[9:], "revenue_view_key": "/etc/x.view"},
                      {"revenue_address": address, "revenue_view_key": "x.view"}):
            with self.subTest(ootle=ootle), self.assertRaises(config.ConfigError):
                config.from_dict({**base, "ootle": ootle})


if __name__ == "__main__":
    unittest.main()
