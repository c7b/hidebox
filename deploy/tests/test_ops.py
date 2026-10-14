# SPDX-License-Identifier: MIT
"""Operations scripts against temporary data: backups and the restore drill, the healthcheck's
reaction to every D-07 failure, the evidence collector's privacy rule, the walletd start script."""
import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "scripts"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load("backup", SCRIPTS / "backup.py")
health = load("healthcheck", SCRIPTS / "healthcheck.py")
evidence = load("collect_evidence", SCRIPTS / "collect-evidence.py")
demo_gone = load("demo_gone", SCRIPTS / "demo-gone.py")


def mutis_db(path: Path) -> sqlite3.Connection:
    """The tables the ops scripts read (server/mutis/schema.sql defines the real ones)."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE abuse_reports (id TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'new');
        CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT, slice TEXT, evidence INTEGER, payload TEXT, state TEXT,
                           not_before INTEGER, result TEXT, error TEXT, attempts INTEGER, created_at INTEGER, updated_at INTEGER);
        CREATE TABLE chain_utxos (seq INTEGER PRIMARY KEY, id TEXT UNIQUE, nonce BLOB, enc BLOB, tag BLOB, epoch INTEGER,
                                  first_seen INTEGER);
        CREATE TABLE seal_checkpoints (idx INTEGER PRIMARY KEY, tree_size INTEGER, root BLOB, created_at INTEGER,
                                       state TEXT, tx_id TEXT, submitted_at INTEGER, epoch INTEGER, component TEXT,
                                       chain_index INTEGER);""")
    return conn


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value if isinstance(value, str) else json.dumps(value)))


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        (self.data / "db").mkdir(parents=True)
        (self.data / "backup").mkdir()
        conn = mutis_db(self.data / "db" / "mutis.sqlite3")
        conn.execute("PRAGMA journal_mode=WAL")
        set_meta(conn, "schema_version", "1")
        conn.close()
        (Path(self.tmp.name) / "m.toml").write_text(f'data_dir = "{self.data}"\n')
        os.environ["MUTIS_CONFIG"] = str(Path(self.tmp.name) / "m.toml")

    def tearDown(self):
        del os.environ["MUTIS_CONFIG"]
        self.tmp.cleanup()

    def aged(self, name: str, days: float) -> Path:
        path = self.data / "backup" / name
        path.write_bytes(b"old")
        when = time.time() - days * 86400
        os.utime(path, (when, when))
        return path

    def test_db_backup_restores_and_is_one_file(self):
        name = backup.backup_db()[0]
        copy = self.data / "backup" / name
        self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o600)
        result = backup.check_copy(copy)
        self.assertEqual((result["integrity"], result["tables"]), ("ok", 5))
        self.assertEqual(sorted(p.name for p in (self.data / "backup").iterdir()), [name],
                         "no -wal/-shm left beside the copy, even after the restore drill opened it")

    def test_every_copy_goes_after_keep_days(self):
        sys.path.insert(0, str(ROOT / "server"))
        from mutis import cleanup
        self.assertEqual(backup.KEEP_DAYS, cleanup.DB_BACKUP_DAYS,
                         "the retention /privacy publishes (db_backup_days) is the one backup.py applies")
        old = [self.aged("mutis-20261001.sqlite3", 7), self.aged("pre-migrate-20261001-090000.sqlite3", 6.6),
               self.aged("mutis-20261001.sqlite3-shm", 1), self.aged("pre-migrate-20261009-090000.sqlite3.part", 0)]
        kept = [self.aged("mutis-20261005.sqlite3", 3), self.aged("pre-migrate-20261008-090000.sqlite3", 2)]
        os.chmod(kept[1], 0o644)
        backup.backup_db()
        for path in old:
            self.assertFalse(path.exists(), path.name)
        for path in kept:
            self.assertTrue(path.exists(), path.name)
        self.assertEqual(stat.S_IMODE(kept[1].stat().st_mode), 0o600)

    def test_roots_database_copies_go_at_the_same_age_and_nothing_else(self):
        """Claims review item 22: the go-live and pre-migrate copies under /var/backups/mutis keep the
        published retention; wallet tars, balance snapshots and config copies stay whatever their age."""
        root = self.data / "var-backups"
        golive = root / "pre-golive-20261011T233723Z"
        golive.mkdir(parents=True)
        age = lambda path, days: (path.write_bytes(b"x"), os.utime(path, (time.time() - days * 86400,) * 2))
        old = [golive / "mutis.sqlite3", golive / "mutis.sqlite3-wal", golive / "mutis.sqlite3-shm",
               golive / "pre-migrate-20261011-153333.sqlite3", root / "mutis-20261001.sqlite3.part"]
        kept = [root / "wallet-20261011T151744Z-cold.tar", root / "balances-20261011T151744Z-before.json",
                root / "mutis.toml-20261011T184552Z", golive / "evidence.json", root / "wallet-copy.sqlite3",
                golive / "mutis-fresh.sqlite3"]
        for path in old + kept[:-1]:
            age(path, 8)
        age(kept[-1], 6)
        gone = backup.prune_root(folder=root)
        self.assertEqual(sorted(gone), sorted(str(p.relative_to(root)) for p in old))
        for path in old:
            self.assertFalse(path.exists(), path.name)
        for path in kept:
            self.assertTrue(path.exists(), path.name)
        self.assertEqual(backup.prune_root(folder=root), [], "a second run finds nothing")

    def test_never_more_than_keep_days_copies(self):
        for day in range(1, 10):
            self.aged(f"mutis-202610{day:02d}.sqlite3", 0.1 * (10 - day))
        name = backup.backup_db()[0]
        copies = sorted((self.data / "backup").glob("mutis-*.sqlite3"))
        self.assertEqual(len(copies), backup.KEEP_DAYS)
        self.assertIn(name, [c.name for c in copies])


class HealthTest(unittest.TestCase):
    NOW = 1_800_000_000

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = mutis_db(Path(self.tmp.name) / "db.sqlite3")
        set_meta(self.conn, "chain_heartbeat", str(self.NOW - 5))
        set_meta(self.conn, "chain_status", {"updated_at": self.NOW - 30, "walletd_ok": True, "sidecar_ok": True,
                                             "sponsor_balance_ut": 8_000_000_000, "mirror_ok_at": self.NOW - 10,
                                             "payments_unconfirmed": 0})
        set_meta(self.conn, "canary_log", [{"n": 7, "sealed_at": self.NOW - 1800, "verified": True}])
        self.cfg = {"public_origin": "https://h.example", "data_dir": self.tmp.name,
                    "limits": {"reserve_min_bytes": 10 << 30}, "ootle": {"mainnet_date": "2026-11-11"}}
        self.probes = {"https": lambda o: ("green", "ok"), "api": lambda o: ("green", "ok"),
                       "disk": lambda path, reserve: health.disk_check(path, reserve, self.statvfs)}
        self.free = 60 << 30

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def statvfs(self, _path):
        return SimpleNamespace(f_blocks=(100 << 30) // 4096, f_frsize=4096, f_bavail=self.free // 4096)

    def report(self) -> dict:
        return health.evaluate(self.cfg, self.conn, self.NOW, self.probes)

    def test_all_green(self):
        r = self.report()
        self.assertEqual(r["overall"], "green", r)
        self.assertFalse(r["attention"])
        self.assertEqual(health.public_subset(r)["checks"]["canary"], "green")

    def test_each_simulated_failure_turns_red(self):
        failures = {
            "api": lambda: self.probes.update(api=lambda o: ("red", "api_down")),
            "chain_worker": lambda: set_meta(self.conn, "chain_heartbeat", str(self.NOW - 600)),
            "walletd": lambda: set_meta(self.conn, "chain_status", {**json.loads(self.conn.execute(
                "SELECT value FROM meta WHERE key = 'chain_status'").fetchone()[0]), "walletd_ok": False}),
            "chain_worker:sidecar_down": lambda: self.status(sidecar_ok=False),
            "canary": lambda: set_meta(self.conn, "canary_log", [{"n": 7, "sealed_at": self.NOW - 5 * 3600, "verified": True}]),
            "disk": lambda: self.cfg["limits"].update(reserve_min_bytes=200 << 30),
            "credits": lambda: set_meta(self.conn, "credit_freeze", "1"),
        }
        for name, simulate in failures.items():
            check, _, detail = name.partition(":")
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                simulate()
                r = self.report()
                self.assertEqual(r["checks"][check]["state"], "red", r["checks"][check])
                if detail:
                    self.assertEqual(r["checks"][check]["detail"], detail)
                self.assertEqual(r["overall"], "red")

    def status(self, **changes):
        current = json.loads(self.conn.execute("SELECT value FROM meta WHERE key = 'chain_status'").fetchone()[0])
        set_meta(self.conn, "chain_status", current | changes)

    def test_check_names_are_the_ones_status_labels(self):
        labels = {"https", "api", "chain_worker", "walletd", "sponsor_balance", "mirror", "canary", "credits", "disk",
                  "budgets", "packs"}
        self.assertEqual(set(self.report()["checks"]), labels)
        self.assertEqual(set(health.evaluate(self.cfg, None, self.NOW, self.probes)["checks"]) - labels, set())

    def test_payments_the_indexers_cant_confirm_are_amber(self):
        self.status(reconcile_unknown=2)
        self.assertEqual(self.report()["checks"]["credits"]["state"], "green")
        self.status(reconcile_unknown=3)
        self.assertEqual(self.report()["checks"]["credits"], {"state": "amber", "detail": "indexers_unreachable"})
        self.status(reconcile_unknown=0, payments_unconfirmed=1)
        self.assertEqual(self.report()["checks"]["credits"], {"state": "amber", "detail": "payments_unconfirmed"})

    def test_a_budget_slice_at_90_is_amber(self):
        set_meta(self.conn, "alerts", {"budgets": {"courier:public": 90}})
        self.assertEqual(self.report()["checks"]["budgets"], {"state": "amber", "detail": "budget_90"})

    def test_budget_slice_at_half_raises_attention(self):
        set_meta(self.conn, "alerts", {"budgets": {"courier:public": 50}})
        r = self.report()
        self.assertTrue(r["attention"])
        self.assertEqual(r["reasons"], ["budget.courier.public.50"])
        self.assertEqual(r["overall"], "green")

    def test_packs_turn_amber_when_the_public_slice_is_80_percent_taken_or_the_ceiling_is_hit(self):
        day = time.strftime("%Y-%m-%d", time.gmtime(self.NOW))
        set_meta(self.conn, "packs", {"day": day, "updated_at": self.NOW, "public_80": False, "ceiling_hit": False})
        self.assertEqual(self.report()["checks"]["packs"], {"state": "green", "detail": "on sale"})
        set_meta(self.conn, "packs", {"day": day, "updated_at": self.NOW, "public_80": True, "ceiling_hit": False})
        r = self.report()
        self.assertEqual(r["checks"]["packs"], {"state": "amber", "detail": "packs_public_80"})
        self.assertEqual((r["overall"], r["reasons"]), ("amber", ["packs.public_80"]))
        set_meta(self.conn, "packs", {"day": day, "updated_at": self.NOW, "public_80": False, "ceiling_hit": True})
        self.assertEqual(self.report()["reasons"], ["packs.ceiling"])
        set_meta(self.conn, "packs", {"day": "2000-01-01", "updated_at": self.NOW, "public_80": False, "ceiling_hit": True})
        self.assertEqual(self.report()["checks"]["packs"]["state"], "green")       # yesterday's ceiling
        set_meta(self.conn, "packs", {"day": day, "updated_at": self.NOW - 3600, "public_80": True, "ceiling_hit": True})
        self.assertEqual(self.report()["checks"]["packs"]["state"], "green")       # a stale note says nothing

    def test_unverified_canary_is_amber_then_red(self):
        set_meta(self.conn, "canary_log", [{"n": 8, "sealed_at": self.NOW - 300, "verified": False}])
        self.assertEqual(self.report()["checks"]["canary"]["state"], "amber")
        set_meta(self.conn, "canary_log", [{"n": 8, "sealed_at": self.NOW - 1500, "verified": False}])
        self.assertEqual(self.report()["checks"]["canary"]["state"], "red")

    def test_phase(self):
        self.assertEqual(health.phase(int(time.mktime((2026, 11, 10, 23, 0, 0, 0, 0, 0))) - time.timezone, "2026-11-11"), "pre")
        self.assertEqual(health.phase(1_800_000_000, "2026-11-11"), "mainnet")


class EvidenceTest(unittest.TestCase):
    def test_only_evidence_jobs_are_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = mutis_db(Path(tmp) / "db.sqlite3")
            now = int(time.time())
            rows = [("canary", "courier", 1, {"tx_id": "a" * 64, "utxo_ids": ["utxo_x"]}),
                    ("user", "courier", 0, {"tx_id": "b" * 64}),
                    ("pay", "demo_pay", 1, {"tx_id": "c" * 64}),
                    ("decoy", "decoy", 0, {"tx_id": "d" * 64})]
            for jid, kind, ev, result in rows:
                conn.execute("INSERT INTO jobs (id, kind, slice, evidence, state, result, updated_at) VALUES (?, ?, 'reserved', ?, 'done', ?, ?)",
                             (jid, kind, ev, json.dumps(result), now))
            conn.execute("INSERT INTO chain_utxos (id, epoch) VALUES ('utxo_x', 12400)")
            set_meta(conn, "receiver_address", "otl_esm_1receiver")
            robot = Path(tmp) / "robot.json"
            robot.write_text(json.dumps({"address": "otl_esm_1robot", "owner_sk": "secret"}))
            evidence.STATUS = Path(tmp)
            import datetime
            doc = evidence.collect({"network": "esmeralda"}, conn, robot, datetime.datetime.now(datetime.UTC))
            text = json.dumps(doc)
            self.assertEqual([d["tx_id"] for d in doc["deliveries"]], ["a" * 64])
            self.assertEqual(doc["deliveries"][0]["epoch"], 12400)
            self.assertEqual([p["tx_id"] for p in doc["payments"]], ["c" * 64])
            self.assertNotIn("b" * 64, text)
            self.assertNotIn("d" * 64, text)
            self.assertNotIn("secret", text)
            self.assertFalse([k for k in doc if "decoy" in k], "no decoy count (it would reveal real volume)")
            self.assertIsNone(doc["wasm_sha256"], "no sidecar has reported a hash yet")
            set_meta(conn, "chain_status", {"sidecar": {"wasm_sha256": "e" * 64}})
            doc = evidence.collect({"network": "esmeralda"}, conn, robot, datetime.datetime.now(datetime.UTC))
            self.assertEqual(doc["wasm_sha256"], "e" * 64)
            conn.close()

    def test_seallog_names_the_live_log_its_chain_index_and_the_retired_ones(self):
        live, old = "component_" + "1" * 64, "component_" + "2" * 64
        with tempfile.TemporaryDirectory() as tmp:
            conn = mutis_db(Path(tmp) / "db.sqlite3")
            cfg = {"features": {"seallog": False}, "ootle": {"seallog_component": live}}
            self.assertIsNone(evidence.seallog(conn, cfg), "nothing while SealLog is off")
            cfg["features"]["seallog"] = True
            self.assertIsNone(evidence.seallog(conn, cfg)["latest_checkpoint"])
            rows = [(1, old, 9, "committed"), (2, live, 3, "committed"), (3, live, None, "failed")]
            for idx, component, chain_index, state in rows:
                conn.execute("INSERT INTO seal_checkpoints (idx, tree_size, root, created_at, state, tx_id, epoch, "
                             "component, chain_index) VALUES (?, 64, x'00', 0, ?, ?, 12200, ?, ?)",
                             (idx, state, f"{idx}" * 64, component, chain_index))
            doc = evidence.seallog(conn, cfg)
            conn.close()
        self.assertEqual(doc["latest_checkpoint"], {"index": 3, "component": live, "tree_size": 64,
                                                    "tx_id": "2" * 64, "epoch": 12200})
        self.assertEqual(doc["retired"], list(evidence.RETIRED_LOGS))
        self.assertNotIn(live, doc["retired"])


class RunWalletdTest(unittest.TestCase):
    def test_password_reaches_walletd_only_through_a_private_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "cred").mkdir()
            (tmp / "run").mkdir()
            (tmp / "wallet" / "esmeralda" / "config").mkdir(parents=True)
            password = "pa55+word/with=SYMBOLS_ok"
            (tmp / "cred" / "keyring-pass").write_text(password + "\n")
            (tmp / "wallet" / "esmeralda" / "config" / "config.toml").write_text(
                "[a]\nx = 1\n[esmeralda.ootle_wallet_daemon]\nindexer_api_url = [\"u\"]\n")
            fake = tmp / "walletd"
            fake.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
            fake.chmod(0o755)
            env = {"PATH": os.environ["PATH"], "CREDENTIALS_DIRECTORY": str(tmp / "cred"), "RUNTIME_DIRECTORY": str(tmp / "run"),
                   "WALLETD_BASE": str(tmp / "wallet"), "WALLETD_BIN": str(fake)}
            out = subprocess.run(["bash", str(ROOT / "deploy" / "ootle" / "run-walletd.sh")], env=env,
                                 capture_output=True, text=True, check=True).stdout
            self.assertNotIn(password, out)
            self.assertIn("--authentication\nnone", out)
            config = tmp / "run" / "config.toml"
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            import tomllib
            stored = tomllib.loads(config.read_text())["esmeralda"]["ootle_wallet_daemon"]["override_keyring_password"]
            self.assertEqual(bytes(stored).decode(), password)

    def test_a_password_with_unexpected_characters_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "cred").mkdir()
            (tmp / "cred" / "keyring-pass").write_text('bad"quote;$(x)')
            env = {"PATH": os.environ["PATH"], "CREDENTIALS_DIRECTORY": str(tmp / "cred"), "RUNTIME_DIRECTORY": str(tmp)}
            res = subprocess.run(["bash", str(ROOT / "deploy" / "ootle" / "run-walletd.sh")], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertNotIn("bad", res.stderr)


if __name__ == "__main__":
    unittest.main()


class DemoGone(unittest.TestCase):
    """14-ghost-design §9: the release writes the burned demo secret's id into mutis.toml, at the top
    level, replacing an older one, and the server's own validation accepts the result."""

    EXAMPLE = (ROOT / "deploy" / "config" / "mutis.toml.example").read_text()

    def test_the_key_lands_at_the_top_level_and_reads_back(self):
        import tomllib
        sid = "A" * 21 + "w"
        out = demo_gone.set_key(self.EXAMPLE, sid)
        cfg = tomllib.loads(out)
        self.assertEqual(cfg["judge_demo_gone"], sid)
        self.assertEqual({k: v for k, v in cfg.items() if k != "judge_demo_gone"},
                         {k: v for k, v in tomllib.loads(self.EXAMPLE).items() if k != "judge_demo_gone"})
        again = demo_gone.set_key(out, "B" * 22)
        self.assertEqual(tomllib.loads(again)["judge_demo_gone"], "B" * 22)
        self.assertEqual(again.count("judge_demo_gone ="), 1)
        sys.path.insert(0, str(ROOT / "server"))
        from mutis.config import from_dict
        from_dict(tomllib.loads(again), dev=True)

    def test_without_repo_url_it_goes_before_the_first_table(self):
        import tomllib
        out = demo_gone.set_key('network = "esmeralda"\n\n[gates]\nsend_mode = "relay"\n', "C" * 22)
        self.assertEqual(tomllib.loads(out)["judge_demo_gone"], "C" * 22)
        self.assertNotIn("judge_demo_gone", tomllib.loads(out)["gates"])

    def test_only_a_share_id(self):
        for bad in ("", "short", "A" * 23, 'A" injected = "x'):
            with self.assertRaises(ValueError):
                demo_gone.set_key(self.EXAMPLE, bad)

    def test_write_keeps_owner_and_mode(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mutis.toml"
            path.write_text(self.EXAMPLE)
            os.chmod(path, 0o640)
            demo_gone.write_config(path, demo_gone.set_key(self.EXAMPLE, "D" * 22))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
            self.assertIn('judge_demo_gone = "DDDDDDDDDDDDDDDDDDDDDD"', path.read_text())
