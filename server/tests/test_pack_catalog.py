# SPDX-License-Identifier: MIT
"""A deployment's own packs (`packs.catalog`, docs/pricing.md): what /config sells, invoices that keep the terms they
were made with when the catalog changes, the paid slices counting those terms, and the checks on the catalog."""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import GiB, Stack  # noqa: E402
from mutis import config, db, packs, payments, quota  # noqa: E402

CATALOG = [{"id": "p10", "bytes": 10 * GiB, "days": 30, "price_ut": 250_000_000},
           {"id": "p100", "bytes": 100 * GiB, "days": 30, "price_ut": 2_000_000_000}]


class MainnetCatalog(unittest.TestCase):
    def setUp(self):
        self.s = Stack({"packs": {"catalog": CATALOG}, "limits": {"quota_floor_bytes": 1 * GiB,
                                                                 "quota_ceiling_bytes": 10 * GiB}},
                       network="mainnet", chain=True)
        self.s.disk.total = self.s.disk.avail = 4 << 40              # room for the big pack in the paid slice
        self.s.worker.setup()
        self.drive = self.s.register()

    def tearDown(self):
        self.s.close()
        logging.getLogger("mutis").handlers.clear()

    def pay(self, inv: dict) -> dict:
        self.s.chain.balances["service"] += int(inv["amount_ut"])       # a buyer with that much TARI
        self.s.chain.transfer("service", inv["address"], int(inv["amount_ut"]), None, 30000)
        for _ in range(4):
            self.s.now += 10
            self.s.worker.tick()
        return self.s.request("GET", f"/api/v1/invoices/{inv['invoice_id']}", headers=self.drive["auth"])[2]

    def test_config_sells_the_catalog_in_tari(self):
        cfg = self.s.request("GET", "/api/v1/config")[2]
        self.assertEqual(cfg["pricing"]["unit"], "TARI")
        self.assertEqual(cfg["pricing"]["packs"], [
            {"id": "p10", "bytes": 10 * GiB, "days": 30, "price_ut": "250000000"},
            {"id": "p100", "bytes": 100 * GiB, "days": 30, "price_ut": "2000000000"}])
        self.assertEqual((cfg["quota"]["floor_bytes"], cfg["quota"]["ceiling_bytes"]), (1 * GiB, 10 * GiB))
        status, _, body = self.s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=self.drive["auth"])
        self.assertEqual((status, body["error"]["code"]), (422, "unknown_pack"))      # the built-in packs aren't sold here

    def test_a_wallet_payment_credits_the_pack_on_its_invoice_terms(self):
        status, _, inv = self.s.request("POST", "/api/v1/invoices", {"pack": "p10"}, headers=self.drive["auth"])
        self.assertEqual((status, inv["amount_ut"]), (201, "250000000"), inv)
        row = self.s.conn.execute("SELECT pack_bytes, pack_days, price_ut FROM invoices WHERE id = ?",
                                  (inv["invoice_id"],)).fetchone()
        self.assertEqual(tuple(row), (10 * GiB, 30, 250_000_000))
        # The operator re-prices and resizes before the payment lands: the open invoice keeps what it promised.
        self.s.cfg.raw["packs"]["catalog"] = [{"id": "p10", "bytes": 5 * GiB, "days": 7, "price_ut": 900_000_000}]
        got = self.pay(inv)
        self.assertEqual(got["status"], "credited", got)
        self.assertEqual(got["credited"], {"bytes": 10 * GiB, "until": got["credited"]["until"]})
        drive = self.s.conn.execute("SELECT paid_bytes, paid_until, paid_pack FROM identities WHERE id = ?",
                                    (self.drive["id"],)).fetchone()
        self.assertEqual((drive["paid_bytes"], drive["paid_pack"]), (10 * GiB, "p10"))
        self.assertEqual(drive["paid_until"] - got["credited"]["until"], 0)
        me = self.s.request("GET", "/api/v1/me", headers=self.drive["auth"])[2]
        self.assertEqual(me["pack"]["bytes"], 10 * GiB)

    def test_open_invoices_hold_their_own_bytes_in_the_slice(self):
        status, _, inv = self.s.request("POST", "/api/v1/invoices", {"pack": "p100"}, headers=self.drive["auth"])
        self.assertEqual(status, 201, inv)
        pool = quota.measure(self.s.conn, self.s.disk, self.s.cfg.data_dir, self.s.cfg["limits"], self.s.now)
        s = packs.slices(self.s.conn, pool, self.s.cfg["packs"], self.s.now)
        self.assertEqual(s.public_open, 100 * GiB)


class Terms(unittest.TestCase):
    def test_an_invoice_made_before_schema_12_has_its_built_in_pack_s_terms(self):
        self.assertEqual(quota.invoice_terms({"pack": "m30", "pack_bytes": None, "pack_days": None}), (1 * GiB, 30))
        self.assertEqual(quota.invoice_terms({"pack": "s30"}), (256 << 20, 30))
        self.assertEqual(quota.invoice_terms({"pack": "zz", "pack_bytes": 7, "pack_days": 3}), (7, 3))

    def test_grant_without_terms_uses_the_built_in_pack(self):
        s = Stack()
        try:
            drive = s.register()
            with db.tx(s.conn):
                payments.grant_pack(s.conn, drive["id"], "m30", s.now)
            row = s.conn.execute("SELECT paid_bytes FROM identities WHERE id = ?", (drive["id"],)).fetchone()
            self.assertEqual(row[0], 1 * GiB)
        finally:
            s.close()

    def test_the_testnet_still_sells_the_built_in_two(self):
        cfg = config.from_dict({"public_origin": "https://x.example", "memo_origins": ["https://x.example"]})
        self.assertIs(quota.pack_table(cfg["packs"]), quota.PACKS)


class CatalogChecks(unittest.TestCase):
    def cfg(self, catalog):
        return config.from_dict({"public_origin": "https://x.example", "memo_origins": ["https://x.example"],
                                 "packs": {"catalog": catalog}})

    def test_good(self):
        self.assertEqual(list(quota.pack_table(self.cfg(CATALOG)["packs"])), ["p10", "p100"])

    def test_refused(self):
        good = CATALOG[0]
        for bad in ([{**good, "id": "P10"}], [{**good, "id": "1x"}], [good, good], [{**good, "bytes": 1000}],
                    [{**good, "days": 0}], [{**good, "days": 400}], [{**good, "price_ut": 0}],
                    [{**good, "price_ut": "250"}], [{**good, "extra": 1}], [{"id": "p1"}], [good] * 7,
                    [{**good, "price_ut": 10 ** 16}], [{**good, "bytes": True}]):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                self.cfg(bad)


if __name__ == "__main__":
    unittest.main()
