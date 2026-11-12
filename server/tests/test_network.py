# SPDX-License-Identifier: MIT
"""The network as a config choice (server/mutis/network.py): Esmeralda by default, the mainnet without test money."""
import contextlib
import io
import logging
import unittest

from harness import Stack
from mutis import admin, codec, config, db, logsafe, network, ootle_addr
from mutis.chain_worker import walletd_on_network
from mutis.fake_sidecar import argv as fake_sidecar_argv
from mutis.fake_chain import FAKE_WASM_SHA256
from mutis.sidecar import Sidecar, SidecarError
from mutis.walletd import WalletdError
from test_admin import toml

MAINNET = {"network": "mainnet", "testnet_origin": "https://testnet.example",
           "ootle": {"indexers": list(network.NETWORKS["mainnet"].indexers)},
           "features": {"demo_pay": False, "sponsor": False, "judge_passes": False}}


def mainnet(**over) -> dict:
    raw = {**MAINNET, **over}
    raw["features"] = {**MAINNET["features"], **over.get("features", {})}
    return raw


class Config(unittest.TestCase):
    def test_default_is_esmeralda(self):
        cfg = config.from_dict({})
        self.assertEqual((cfg.net.name, cfg.net.byte, cfg.net.hrp, cfg.net.coin), ("esmeralda", 0x26, "otl_esm_", "tTARI"))
        self.assertFalse(cfg["staging"])
        self.assertTrue(cfg["features"]["judge_passes"])

    def test_mainnet(self):
        cfg = config.from_dict(mainnet())
        self.assertEqual((cfg.net.name, cfg.net.byte, cfg.net.hrp, cfg.net.coin, cfg.net.testnet),
                         ("mainnet", 0, "otl_", "TARI", False))

    def test_unknown_network(self):
        with self.assertRaisesRegex(config.ConfigError, "network must be one of"):
            config.from_dict({"network": "stagenet"})

    def test_mainnet_refuses_test_money(self):
        for feature in network.TEST_MONEY:
            with self.subTest(feature), self.assertRaisesRegex(config.ConfigError, feature):
                config.from_dict(mainnet(features={feature: True}))
        # The defaults hand out test money: a mainnet TOML must switch them off by name.
        with self.assertRaisesRegex(config.ConfigError, "demo_pay, judge_passes"):
            config.from_dict({"network": "mainnet", "ootle": MAINNET["ootle"], "testnet_origin": "https://t.example"})

    def test_staging_is_testnet_only(self):
        self.assertTrue(config.from_dict({"staging": True, "testnet_origin": "https://testnet.example"})["staging"])
        with self.assertRaisesRegex(config.ConfigError, "testnet_origin"):
            config.from_dict({"staging": True})
        with self.assertRaisesRegex(config.ConfigError, "testnet_origin"):
            config.from_dict(mainnet(testnet_origin=""))
        with self.assertRaisesRegex(config.ConfigError, "testnet_origin"):
            config.from_dict({"testnet_origin": "http://x.example"})
        with self.assertRaisesRegex(config.ConfigError, "staging"):
            config.from_dict(mainnet(staging=True))

    def test_indexers_must_be_the_networks(self):
        with self.assertRaisesRegex(config.ConfigError, "another network's indexer"):
            config.from_dict({**mainnet(), "ootle": {"indexers": ["https://ootle-indexer-b.tari.com"]}})
        with self.assertRaisesRegex(config.ConfigError, "another network's indexer"):
            config.from_dict({"ootle": {"indexers": ["https://indexer-a.ootle.tari.com/"]}})
        with self.assertRaisesRegex(config.ConfigError, "at least one"):
            config.from_dict({"ootle": {"indexers": []}})

    def test_forced_features(self):
        self.assertEqual(network.forced_features("esmeralda"), {})
        self.assertEqual(network.forced_features("mainnet"), {"demo_pay": False, "sponsor": False, "judge_passes": False})


class Addresses(unittest.TestCase):
    def tearDown(self):
        ootle_addr.use_network("esmeralda")

    def test_each_network_takes_its_own(self):
        keys = bytes(range(64))
        esm = ootle_addr.encode("otl_esm_", keys)
        main = ootle_addr.encode("otl_", keys)
        self.assertEqual(ootle_addr.classify(esm), "ootle_testnet")
        self.assertEqual(ootle_addr.classify(main), "ootle_other")
        ootle_addr.use_network("mainnet")
        self.assertEqual(ootle_addr.classify(main), "ootle_testnet")      # "this network's", whatever its name
        self.assertEqual(ootle_addr.classify(esm), "ootle_other")
        self.assertEqual(ootle_addr.parse(main), (keys[:32], keys[32:], b""))
        with self.assertRaises(ValueError):
            ootle_addr.parse(esm)
        self.assertEqual(ootle_addr.base_address(ootle_addr.with_pay_ref(main, b"ref")), main)
        self.assertTrue(ootle_addr.with_pay_ref(main, b"ref").startswith("otl_1"))


class Walletd(unittest.TestCase):
    def test_walletd_must_name_our_network(self):
        esm, main = network.NETWORKS["esmeralda"], network.NETWORKS["mainnet"]
        self.assertTrue(walletd_on_network({"network": "esmeralda", "network_byte": 38}, esm))
        self.assertTrue(walletd_on_network({"network": "Esmeralda"}, esm))
        self.assertTrue(walletd_on_network({"network": "esme"}, esm))
        self.assertTrue(walletd_on_network({"network": "mainnet", "network_byte": 0}, main))
        self.assertTrue(walletd_on_network({"network": 0}, main))
        self.assertFalse(walletd_on_network({"network": "esmeralda"}, main))
        self.assertFalse(walletd_on_network({"network": "mainnet", "network_byte": 38}, main))
        self.assertFalse(walletd_on_network({"network_byte": 38}, main))
        self.assertTrue(walletd_on_network({}, esm))        # the fake and older walletds name none: testnet only
        self.assertFalse(walletd_on_network({}, main))
        self.assertFalse(walletd_on_network({"network": True}, main))


class WrongNetworkIsSaid(unittest.TestCase):
    """A walletd or a sidecar on another network stops the worker before anything is sent, and says so with its own
    critical event. Neither event was in logsafe's list, so the refusal raised from the logger instead: still nothing
    sent, but the journal only said `chain.loop_error`."""

    def tearDown(self):
        logging.getLogger("mutis").handlers.clear()

    def test_both_events_are_ones_logsafe_writes(self):
        for code in ("chain.walletd_wrong_network", "chain.sidecar_wrong_network"):
            self.assertIn(code, logsafe.EVENTS)

    def test_a_walletd_on_another_network(self):
        s = Stack(network="mainnet")
        try:
            worker = s.start_worker()
            worker.walletd.info = lambda: {"network": "esmeralda", "network_byte": 38}
            with self.assertLogs("mutis", "CRITICAL") as logs, self.assertRaises(WalletdError) as refused:
                worker.setup()
            self.assertEqual(refused.exception.code, "walletd_wrong_network")
            self.assertEqual([r.getMessage() for r in logs.records], ["event=chain.walletd_wrong_network"])
            self.assertIsNone(worker.receiver_base)                 # so no job runs (tick)
        finally:
            s.close()

    def test_a_sidecar_on_another_network(self):
        car = Sidecar(["/usr/bin/env", "MUTIS_NETWORK=esmeralda", *fake_sidecar_argv()], "http://127.0.0.1:9",
                      FAKE_WASM_SHA256, "mainnet")
        try:
            with self.assertLogs("mutis", "CRITICAL") as logs, self.assertRaises(SidecarError) as refused:
                car.request("hello")
            self.assertEqual(refused.exception.code, "wrong_network")
            self.assertEqual([r.getMessage() for r in logs.records], ["event=chain.sidecar_wrong_network"])
        finally:
            car.stop()


class Sidecars(unittest.TestCase):
    def test_sidecar_must_run_on_our_network(self):
        car = Sidecar(fake_sidecar_argv(), "http://127.0.0.1:9", FAKE_WASM_SHA256, "mainnet")
        try:
            self.assertEqual(car.request("hello")["network"], "mainnet")
            self.assertTrue(car.request("newKeys")["address"].startswith("otl_1"))
        finally:
            car.stop()


class MainnetStack(unittest.TestCase):
    def setUp(self):
        self.s = Stack(network="mainnet")

    def tearDown(self):
        self.s.close()
        logging.getLogger("mutis").handlers.clear()

    def test_config_says_mainnet(self):
        status, _, cfg = self.s.request("GET", "/api/v1/config")
        self.assertEqual(status, 200)
        self.assertEqual({k: cfg[k] for k in ("network", "network_byte", "testnet", "coin", "address_prefix", "staging")},
                         {"network": "mainnet", "network_byte": 0, "testnet": False, "coin": "TARI",
                          "address_prefix": "otl_", "staging": False})
        self.assertEqual(cfg["pricing"]["unit"], "TARI")
        for feature in network.TEST_MONEY:
            self.assertFalse(cfg["features"][feature], feature)

    def test_overrides_cannot_turn_test_money_on(self):
        path = self.s.tmp / "mutis.toml"
        path.write_text(toml(self.s.cfg.raw))
        for feature in network.TEST_MONEY:
            with self.subTest(feature), self.assertRaises(SystemExit):
                admin.main(["--config", str(path), "feature", feature, "on"])
        with self.assertRaises(SystemExit):
            admin.main(["--config", str(path), "judge-pass", "new", "--uses", "1"])
        # Even an override written straight into the database changes nothing.
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "features", {"demo_pay": True, "sponsor": True, "judge_passes": True})
        self.s.app._features = (0.0, {})
        _, _, cfg = self.s.request("GET", "/api/v1/config")
        self.assertFalse(any(self.s.app.features(self.s.conn)[f] for f in network.TEST_MONEY))

    def test_no_daily_evidence_payment_is_queued(self):
        """The testnet's daily evidence payment is test money from our demo wallet. On the mainnet the worker queued
        its invoice and job all the same, every day, and the job failed on an empty budget."""
        worker = self.s.start_worker()
        worker.setup()
        with db.tx(self.s.conn):
            db.del_meta(self.s.conn, "evidence_pay_day")
        self.assertGreaterEqual(self.s.now % 86400, 12 * 3600)              # past the hour it is due at
        worker.evidence_payment(self.s.now)
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "force", {"evidence_pay": True})        # mutis-admin evidence-pay-now
        worker.evidence_payment(self.s.now)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_a_judge_header_is_ignored(self):
        status, _, resp = self.s.request("POST", "/api/v1/sponsor", {"wallet_address": self.s.receiver["address"]},
                                         headers={"X-Mutis-Judge": "judge-" + "a" * 24})
        self.assertEqual((status, resp["error"]["code"]), (503, "feature_disabled"))

    def test_addresses_are_mainnet_ones(self):
        self.assertTrue(self.s.receiver["address"].startswith("otl_1"))
        esm = ootle_addr.encode("otl_esm_", bytes(64))
        status, _, resp = self.s.request("POST", "/api/v1/drops", {"address": esm, "tag": codec.b64u(b"\0" * 16),
                                                                    "label": "", "manage_verifier": codec.b64u(b"\0" * 32)})
        self.assertEqual(status, 422)
        self.assertEqual(resp["error"]["code"], "mainnet_address")
        self.assertIn("the Ootle mainnet", resp["error"]["message"])


class MainnetPacks(unittest.TestCase):
    """Space packs on the mainnet lane (docs/mvp-november.md §4): sold for TARI to our mainnet receiving address, the
    same packs and prices as on the testnet, no test money to pay them, and a wallet payment credits as on the testnet
    (amount proven, committed, the one-time key ours)."""

    def setUp(self):
        self.s = Stack(network="mainnet", chain=True)
        self.s.worker.setup()
        self.drive = self.s.register()

    def tearDown(self):
        self.s.close()
        logging.getLogger("mutis").handlers.clear()

    def test_a_pack_is_sold_for_tari_and_a_wallet_payment_credits_it(self):
        from mutis import quota
        cfg = self.s.request("GET", "/api/v1/config")[2]
        self.assertTrue(cfg["features"]["packs"])
        self.assertEqual((cfg["pricing"]["unit"], [p["id"] for p in cfg["pricing"]["packs"]]), ("TARI", list(quota.PACKS)))
        status, _, inv = self.s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=self.drive["auth"])
        self.assertEqual(status, 201, inv)
        self.assertTrue(inv["address"].startswith("otl_1"), inv["address"])
        status, _, resp = self.s.request("POST", f"/api/v1/invoices/{inv['invoice_id']}/demo-pay",
                                         {"pow": self.s.solve("demo_pay")}, headers=self.drive["auth"])
        self.assertEqual((status, resp["error"]["code"]), (503, "feature_disabled"))     # no test money on the mainnet
        self.s.chain.transfer("service", inv["address"], int(inv["amount_ut"]), None, 30000)
        for _ in range(4):
            self.s.now += 10
            self.s.worker.tick()
        got = self.s.request("GET", f"/api/v1/invoices/{inv['invoice_id']}", headers=self.drive["auth"])[2]
        self.assertEqual(got["status"], "credited", got)
        self.assertEqual(got["credited"]["bytes"], 256 << 20)

    def test_the_kill_switch_pauses_them(self):
        from mutis import db
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "features", {"packs": False})
        self.s.app._features = (0.0, {})
        status, _, resp = self.s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=self.drive["auth"])
        self.assertEqual(status, 503)


class StagingStack(unittest.TestCase):
    def test_staging_is_served(self):
        s = Stack(overrides={"staging": True, "testnet_origin": "https://testnet.example"})
        try:
            _, _, cfg = s.request("GET", "/api/v1/config")
            self.assertEqual((cfg["network"], cfg["staging"], cfg["testnet"], cfg["coin"]), ("esmeralda", True, True, "tTARI"))
        finally:
            s.close()


class Quiet(unittest.TestCase):
    def test_admin_output_lists_forced_features(self):
        s = Stack(network="mainnet")
        try:
            path = s.tmp / "mutis.toml"
            path.write_text(toml(s.cfg.raw))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                admin.main(["--config", str(path), "feature", "decoys", "off"])
            self.assertIn('"demo_pay": false', out.getvalue())
        finally:
            s.close()
            logging.getLogger("mutis").handlers.clear()


if __name__ == "__main__":
    unittest.main()
