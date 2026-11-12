# SPDX-License-Identifier: MIT
"""An instance beside production (deploy/scripts/instance.py): its layout, its units and its Caddy site are
production's own, renamed, and never reach production's files, users, ports or Caddyfile."""
import importlib.util
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "scripts"
spec = importlib.util.spec_from_file_location("instance", SCRIPTS / "instance.py")
instance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(instance)
sys.path.insert(0, str(ROOT / "server"))
from mutis import config  # noqa: E402

HARDENING = re.compile(r"^(NoNewPrivileges|ProtectSystem|ProtectHome|PrivateTmp|PrivateDevices|PrivateNetwork|ProtectProc|"
                       r"ProcSubset|ProtectKernel\w+|ProtectControlGroups|ProtectClock|ProtectHostname|RestrictAddressFamilies|"
                       r"RestrictNamespaces|RestrictRealtime|RestrictSUIDSGID|LockPersonality|MemoryDenyWriteExecute|"
                       r"SystemCallArchitectures|SystemCallFilter|SystemCallErrorNumber|CapabilityBoundingSet|RemoveIPC|UMask|"
                       r"MemoryMax|TasksMax|KillSignal|Restart|RestartSec|TimeoutStopSec|TimeoutStartSec|Type|OnCalendar|"
                       r"OnBootSec|OnUnitActiveSec|AccuracySec|Persistent|Options|WantedBy)=.*$", re.M)


def instance_config(name="mainnet", origin="https://mainnet.example.com", api_port=8788, walletd_port=5102) -> str:
    text = (ROOT / "deploy" / "config" / "instance.toml.example").read_text()
    for key, value in (("NAME", name), ("ORIGIN", origin), ("API_PORT", api_port), ("WALLETD_PORT", walletd_port),
                       ("TESTNET_ORIGIN", "https://testnet.example")):
        text = text.replace(f"@{key}@", str(value))
    return text


def flipped(text: str) -> str:
    """deploy/ootle/mainnet-launch.md §4, as text edits."""
    text = text.replace('network = "esmeralda"', 'network = "mainnet"').replace("staging = true", "staging = false")
    text = text.replace('indexers = ["https://ootle-indexer-b.tari.com", "https://ootle-indexer-a.tari.com"]',
                        'indexers = ["https://indexer-a.ootle.tari.com", "https://indexer-b.ootle.tari.com"]')
    return text.replace("127.0.0.1:5102/json_rpc", "127.0.0.1:5101/json_rpc")


class Layout(unittest.TestCase):
    def test_production_is_the_layout_every_script_had(self):
        env = instance.layout("").env()
        self.assertEqual({k: env[k] for k in ("INST_CONFIG", "INST_APP", "INST_DATA", "INST_STATUS", "INST_MUTIS_USER",
                                              "INST_DRIVE_USER", "INST_KEYS", "INST_LIB", "INST_BACKUPS", "INST_ADMIN",
                                              "INST_API_UNIT", "INST_CHAIN_UNIT", "INST_CADDY_SITE", "INST_WALLET_BACKUPS")},
                         {"INST_CONFIG": "/etc/mutis/mutis.toml", "INST_APP": "/srv/mutis/app", "INST_DATA": "/srv/mutis/data",
                          "INST_STATUS": "/srv/mutis/status", "INST_MUTIS_USER": "mutis", "INST_DRIVE_USER": "drive",
                          "INST_KEYS": "/home/drive/mutis", "INST_LIB": "/usr/local/lib/mutis",
                          "INST_BACKUPS": "/var/backups/mutis", "INST_ADMIN": "/usr/local/sbin/mutis-admin",
                          "INST_API_UNIT": "mutis-api", "INST_CHAIN_UNIT": "mutis-chain", "INST_CADDY_SITE": "",
                          "INST_WALLET_BACKUPS": "/home/drive/wallet/backup"})

    def test_an_instance_has_its_own_names(self):
        env = instance.layout("mainnet").env()
        for key, value in env.items():
            if key in ("MUTIS_INSTANCE", "INST_SUFFIX"):
                continue
            self.assertIn("mainnet", value, key)
        self.assertEqual(env["INST_CADDY_SITE"], "/etc/caddy/mutis.d/mainnet.caddy")

    def test_names(self):
        for bad in ("Main", "a", "main-net", "x" * 17, "1st", "api", "../x"):
            with self.subTest(bad), self.assertRaises(SystemExit):
                instance.layout(bad)

    def test_the_shell_reads_the_same(self):
        out = subprocess.run([sys.executable, "-I", str(SCRIPTS / "instance.py"), "env", "mainnet"], capture_output=True,
                             text=True, check=True).stdout
        self.assertIn("INST_CONFIG=/etc/mutis-mainnet/mutis.toml\n", out)
        self.assertIn("MUTIS_INSTANCE=mainnet\n", out)

    def test_mount_unit_names_are_systemds(self):
        self.assertEqual(instance.mount_unit("/srv/mutis/data"), "srv-mutis-data.mount")
        self.assertEqual(instance.mount_unit("/srv/mutis-mainnet/data"), "srv-mutis\\x2dmainnet-data.mount")


class Units(unittest.TestCase):
    def setUp(self):
        self.lay = instance.layout("mainnet")
        self.units = instance.render_units(self.lay, [("mainnet", 5101), ("esmeralda", 5102)])

    def test_every_production_unit_has_its_instance_copy(self):
        prod = sorted(p.name for p in (ROOT / "deploy" / "systemd").glob("*") if p.suffix in (".service", ".timer", ".mount"))
        self.assertEqual(len(self.units), len(prod) + 1)          # walletd.service, once per network
        for name in prod:
            if name == "walletd.service":
                continue
            if name.endswith(".mount"):
                expected = name.replace("srv-mutis-", "srv-mutis\\x2dmainnet-")
            else:
                expected = name.replace("mutis-", "mutis-mainnet-", 1)
            self.assertIn(expected, self.units, name)

    def test_the_hardening_is_productions_line_for_line(self):
        for path in (ROOT / "deploy" / "systemd").glob("*"):
            if path.suffix not in (".service", ".timer", ".mount"):
                continue
            prod = HARDENING.findall(path.read_text())
            names = ([f"mutis-mainnet-walletd-{n}.service" for n in ("mainnet", "esmeralda")] if path.name == "walletd.service"
                     else [n for n in self.units if n.endswith(path.suffix) and (
                         n.replace("mutis-mainnet-", "mutis-", 1) == path.name
                         or n.replace("srv-mutis\\x2dmainnet-", "srv-mutis-") == path.name)])
            self.assertTrue(names, path.name)
            for name in names:
                self.assertEqual(HARDENING.findall(self.units[name]), prod, name)
                self.assertEqual(re.findall(r"^\w+=.*$", self.units[name], re.M).__len__() >= len(prod), True)

    def test_nothing_points_at_production(self):
        for name, text in self.units.items():
            body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
            for prod in ("/srv/mutis/", "/etc/mutis/mutis.toml", "/home/drive/", "/usr/local/lib/mutis/", "127.0.0.1:5100",
                         "walletd.service", "/etc/mutis/credentials"):
                self.assertNotIn(prod, body, f"{name}: {prod}")
            for user in re.findall(r"^(?:User|Group|SupplementaryGroups)=(.*)$", body, re.M):
                self.assertIn(user, ("mutis-mainnet", "drive-mainnet"), name)
            # Production's names only ever appear to make them unreachable.
            for line in body.splitlines():
                if "/srv/mutis " in line + " " or "-/etc/mutis " in line + " ":
                    self.assertTrue(line.startswith("InaccessiblePaths="), f"{name}: {line}")

    def test_walletd_per_network(self):
        main = self.units["mutis-mainnet-walletd-mainnet.service"]
        self.assertIn("Environment=WALLETD_NETWORK=mainnet\n", main)
        self.assertIn("Environment=WALLETD_LISTEN=127.0.0.1:5101\n", main)
        self.assertIn("Environment=WALLETD_BASE=/home/drive-mainnet/wallet-mainnet\n", main)
        self.assertIn("LoadCredential=keyring-pass:/etc/mutis-mainnet/credentials/walletd-mainnet-keyring-pass\n", main)
        self.assertIn("BindPaths=/home/drive-mainnet/wallet-mainnet /home/drive-mainnet/.local/share/tari\n", main)
        self.assertIn("InaccessiblePaths=-/srv/mutis -/srv/mutis-mainnet -/etc/mutis ", main)
        staging = self.units["mutis-mainnet-walletd-esmeralda.service"]
        self.assertIn("Environment=WALLETD_LISTEN=127.0.0.1:5102\n", staging)
        self.assertIn("RuntimeDirectory=mutis-mainnet-walletd-esmeralda\n", staging)

    def test_backups_and_chain(self):
        wallet = self.units["mutis-mainnet-backup-wallet.service"]
        self.assertIn("Environment=MUTIS_WALLET_DBS=/home/drive-mainnet/wallet-mainnet/mainnet/data/wallet.sqlite:"
                      "/home/drive-mainnet/wallet-esmeralda/esmeralda/data/wallet.sqlite:l1wallet-mainnet="
                      "/home/drive-mainnet/l1wallet-mainnet/mainnet/data/wallet/db/console_wallet.db\n", wallet)
        self.assertIn("ReadWritePaths=/home/drive-mainnet/wallet-backup -/home/drive-mainnet/l1wallet-mainnet/mainnet/data/wallet/db\n",
                      wallet)
        db = self.units["mutis-mainnet-backup.service"]
        self.assertIn("Environment=MUTIS_ROOT_BACKUPS=/var/backups/mutis-mainnet\n", db)
        self.assertEqual(db.count("Environment=MUTIS_CONFIG="), 1)
        chain = self.units["mutis-mainnet-chain.service"]
        self.assertIn("After=network-online.target mutis-mainnet-walletd-mainnet.service "
                      "mutis-mainnet-walletd-esmeralda.service mutis-mainnet-api.service\n", chain)
        self.assertIn("Wants=network-online.target\n", chain)

    def test_production_units_are_not_rendered(self):
        with self.assertRaises(SystemExit):
            instance.render_units(instance.layout(""), [])


class Caddy(unittest.TestCase):
    def cfg(self, **over):
        cfg = tomllib.loads(instance_config())
        cfg.update(over)
        return cfg

    def test_the_site_is_self_contained_and_renamed(self):
        site = instance.render_caddy(instance.layout("mainnet"), self.cfg())
        defined = set(re.findall(r"^\((\w+)\) \{$", site, re.M))
        imported = set(re.findall(r"^\s*import (\S+)$", site, re.M))
        self.assertEqual(imported, defined)
        self.assertTrue(all(name.startswith("mutis_mainnet_") for name in defined))
        main = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
        self.assertFalse(defined & set(re.findall(r"^\((\w+)\) \{$", main, re.M)))
        self.assertIn("\nmainnet.example.com {\n", site)
        self.assertIn("\nhttp://mainnet.example.com {\n", site)
        self.assertIn("reverse_proxy 127.0.0.1:8788 {", site)
        self.assertIn("root * /srv/mutis-mainnet/app/current/dist", site)
        self.assertIn("root * /srv/mutis-mainnet/status", site)
        self.assertIn("connect-src 'self' https://ootle-indexer-a.tari.com https://ootle-indexer-b.tari.com;", site)
        for prod in ("{$MUTIS_HOST}", "/srv/mutis/", "127.0.0.1:8787", "hidebox.app", "https:// {", "admin unix"):
            self.assertNotIn(prod, site)
        self.assertIn('header X-Robots-Tag "noindex, nofollow"\n', site.split("\nmainnet.example.com {\n")[1][:200])

    def test_the_mainnet_csp_names_the_mainnet_indexers_and_no_staging_noindex(self):
        cfg = tomllib.loads(flipped(instance_config()))
        site = instance.render_caddy(instance.layout("mainnet"), cfg)
        self.assertIn("connect-src 'self' https://indexer-a.ootle.tari.com https://indexer-b.ootle.tari.com;", site)
        self.assertNotIn("ootle-indexer-", site)
        head = site.split("\nmainnet.example.com {\n")[1].split("\n\t@old_security")[0]
        self.assertNotIn("X-Robots-Tag", head)

    def test_every_route_of_production_is_kept(self):
        site = instance.render_caddy(instance.layout("mainnet"), self.cfg(staging=False))
        main = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
        block = re.search(r"^\{\$MUTIS_HOST\} \{\n(.*?)\n\}$", main, re.M | re.S).group(1)
        ours = re.search(r"^mainnet\.example\.com \{\n(.*?)\n\}$", site, re.M | re.S).group(1)
        normalize = lambda text: re.sub(r"import mutis_mainnet_", "import ", text.replace("/srv/mutis-mainnet/", "/srv/mutis/")
                                        .replace("127.0.0.1:8788", "127.0.0.1:8787"))
        self.assertEqual(normalize(ours), block)

    def test_refuses_productions_port_and_plain_http(self):
        with self.assertRaises(SystemExit):
            instance.render_caddy(instance.layout("mainnet"), self.cfg(listen="127.0.0.1:8787"))
        with self.assertRaises(SystemExit):
            instance.render_caddy(instance.layout("mainnet"), self.cfg(public_origin="http://x.example"))


class InstanceConfig(unittest.TestCase):
    def test_the_example_is_a_valid_staging_config(self):
        cfg = config.from_dict(tomllib.loads(instance_config()))
        self.assertEqual((cfg["network"], cfg["staging"]), ("esmeralda", True))
        self.assertFalse(any(cfg["features"][f] for f in ("demo_pay", "sponsor", "judge_passes")))
        self.assertEqual(cfg["listen"], "127.0.0.1:8788")

    def test_the_flip_is_a_valid_mainnet_config(self):
        cfg = config.from_dict(tomllib.loads(flipped(instance_config())))
        self.assertEqual((cfg["network"], cfg["staging"], cfg.net.coin), ("mainnet", False, "TARI"))
        self.assertEqual(cfg["ootle"]["walletd_url"], "http://127.0.0.1:5101/json_rpc")

    def test_no_placeholder_left(self):
        self.assertNotRegex(instance_config(), r"@[A-Z_]+@")


class Flip(unittest.TestCase):
    """deploy/ootle/flip-to-mainnet.sh's own config edit (its Python block), run on the example and on a staging
    config that already runs its own log, as staging has since its V2 log (2026-11-08)."""
    LOG = "component_" + "ab" * 32

    def edit(self, text: str) -> subprocess.CompletedProcess:
        script = (ROOT / "deploy" / "ootle" / "flip-to-mainnet.sh").read_text()
        block = re.search(r"<<'PY'\n(.*?)\nPY\n", script, re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "mutis.toml", Path(tmp) / "new.toml"
            src.write_text(text)
            run = subprocess.run([sys.executable, "-I", "-", str(src), str(dst), "5101", "4321", self.LOG], input=block,
                                 capture_output=True, text=True)
            run.new = dst.read_text() if dst.is_file() else ""
            return run

    def check(self, run: subprocess.CompletedProcess) -> None:
        self.assertEqual(run.returncode, 0, run.stderr)
        cfg = config.from_dict(tomllib.loads(run.new))
        self.assertEqual((cfg["network"], cfg["staging"], cfg.net.coin), ("mainnet", False, "TARI"))
        self.assertEqual(cfg["ootle"]["walletd_url"], "http://127.0.0.1:5101/json_rpc")
        self.assertEqual(cfg["ootle"]["seallog_component"], self.LOG)
        self.assertTrue(cfg["features"]["seallog"])
        self.assertIn("\nmirror_start_epoch = 4321\n", run.new)

    def test_the_example(self):
        self.check(self.edit(instance_config()))

    def test_a_staging_config_with_its_own_log(self):
        staging = instance_config().replace("\nseallog = false\n", "\nseallog = true\n").replace(
            'seallog_component = ""', f'seallog_component = "component_{"cd" * 32}"')
        self.assertIn("\nseallog = true\n", staging)
        self.check(self.edit(staging))

    def test_refuses_a_config_that_names_the_mainnet(self):
        run = self.edit(flipped(instance_config()))
        self.assertEqual(run.returncode, 1)
        self.assertIn("already names the mainnet", run.stderr)


class Scripts(unittest.TestCase):
    def test_backup_reads_an_instances_wallets(self):
        code = ("import importlib.util, json, sys; s = importlib.util.spec_from_file_location('b', sys.argv[1]); "
                "b = importlib.util.module_from_spec(s); s.loader.exec_module(b); "
                "print(json.dumps([[p, str(d), r] for p, d, r in b.wallet_dbs()] + [str(b.WALLET_BACKUPS), str(b.ROOT_BACKUPS)]))")
        env = {"PATH": os.environ["PATH"]}
        out = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPTS / "backup.py")], env=env, capture_output=True,
                             text=True, check=True).stdout
        self.assertEqual(out.strip(), '[["wallet", "/home/drive/wallet/esmeralda/data/wallet.sqlite", true], '
                                      '"/home/drive/wallet/backup", "/var/backups/mutis"]')
        env |= {"MUTIS_WALLET_DBS": "/h/wallet-mainnet/mainnet/data/wallet.sqlite:/h/wallet-esmeralda/esmeralda/data/wallet.sqlite"
                                    ":l1=/h/l1/console_wallet.db",
                "MUTIS_WALLET_BACKUPS": "/h/wallet-backup", "MUTIS_ROOT_BACKUPS": "/var/backups/mutis-x"}
        out = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPTS / "backup.py")], env=env, capture_output=True,
                             text=True, check=True).stdout
        self.assertEqual(out.strip(), '[["wallet-mainnet", "/h/wallet-mainnet/mainnet/data/wallet.sqlite", false], '
                                      '["wallet-esmeralda", "/h/wallet-esmeralda/esmeralda/data/wallet.sqlite", false], '
                                      '["l1", "/h/l1/console_wallet.db", false], '
                                      '"/h/wallet-backup", "/var/backups/mutis-x"]')

    def test_admin_wrapper_finds_its_instance_in_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            (bin_dir / "runuser").write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            (bin_dir / "runuser").chmod(0o755)
            for name, user, conf in (("mutis-admin", "mutis", "/etc/mutis/mutis.toml"),
                                     ("mutis-admin-mainnet", "mutis-mainnet", "/etc/mutis-mainnet/mutis.toml")):
                wrapper = bin_dir / name
                wrapper.write_text((SCRIPTS / "mutis-admin").read_text())
                wrapper.chmod(0o755)
                out = subprocess.run([str(wrapper), "stats"], env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
                                     capture_output=True, text=True, check=True).stdout.split("\n")
                self.assertEqual(out[:3], ["-u", user, "--"], name)
                self.assertIn(f"MUTIS_CONFIG={conf}", out)
                out = subprocess.run([str(wrapper), "notarize", "00"], env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
                                     capture_output=True, text=True, check=True).stdout.split("\n")
                self.assertEqual(out[1], user.replace("mutis", "drive"), name)

    def test_run_walletd_takes_the_network_and_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "cred").mkdir()
            (tmp / "run").mkdir()
            (tmp / "wallet" / "mainnet" / "config").mkdir(parents=True)
            (tmp / "cred" / "keyring-pass").write_text("a" * 32 + "\n")
            (tmp / "wallet" / "mainnet" / "config" / "config.toml").write_text("[mainnet.ootle_wallet_daemon]\n")
            fake = tmp / "walletd"
            fake.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
            fake.chmod(0o755)
            env = {"PATH": os.environ["PATH"], "CREDENTIALS_DIRECTORY": str(tmp / "cred"), "RUNTIME_DIRECTORY": str(tmp / "run"),
                   "WALLETD_BASE": str(tmp / "wallet"), "WALLETD_BIN": str(fake), "WALLETD_NETWORK": "mainnet",
                   "WALLETD_LISTEN": "127.0.0.1:5101"}
            run = ROOT / "deploy" / "ootle" / "run-walletd.sh"
            out = subprocess.run(["bash", str(run), "seed-words"], env=env, capture_output=True, text=True, check=True).stdout
            self.assertTrue(out.startswith("--network\nmainnet\n"), out)
            self.assertTrue(out.endswith("--authentication\nnone\nseed-words\n"), out)
            self.assertIn("127.0.0.1:5101", out)
            stored = tomllib.loads((tmp / "run" / "config.toml").read_text())["mainnet"]["ootle_wallet_daemon"]
            self.assertEqual(bytes(stored["override_keyring_password"]).decode(), "a" * 32)
            self.assertEqual(stat.S_IMODE((tmp / "run" / "config.toml").stat().st_mode), 0o600)
            out = subprocess.run(["bash", str(run)], env=env, capture_output=True, text=True, check=True).stdout
            self.assertTrue(out.endswith("none\nrun\n"), out)
            bad = subprocess.run(["bash", str(run)], env=env | {"WALLETD_NETWORK": "igor"}, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)


if __name__ == "__main__":
    unittest.main()
