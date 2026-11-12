# SPDX-License-Identifier: MIT
"""deploy/scripts/cutover.py: the config and caddy.env edits of the cut-over (docs/cutover.md)."""
import importlib.util
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cutover", ROOT / "deploy" / "scripts" / "cutover.py")
cutover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cutover)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_instance import config, instance_config  # noqa: E402

PRODUCTION = (ROOT / "deploy" / "config" / "mutis.toml.example").read_text()


class Edits(unittest.TestCase):
    def test_the_testnet_moves_and_keeps_its_memo_origins(self):
        text = cutover.set_key(PRODUCTION, "public_origin", '"https://hidebox.app"')
        text = cutover.set_key(text, "memo_origins", '["https://old.example", "https://hidebox.app"]')
        text = cutover.set_key(text, "security_drop_url", '"https://old.example/d/3w7m8k2v5t"')
        out = tomllib.loads(cutover.testnet_config(text, "hidebox.app", "testnet.hidebox.app"))
        self.assertEqual(out["public_origin"], "https://testnet.hidebox.app")
        self.assertEqual(out["memo_origins"], ["https://old.example", "https://hidebox.app", "https://testnet.hidebox.app"])
        self.assertEqual(out["security_drop_url"], "https://testnet.hidebox.app/d/3w7m8k2v5t")
        config.from_dict(out)
        with self.assertRaises(cutover.Stop):                    # not where the move starts from
            cutover.testnet_config(text, "other.example", "testnet.hidebox.app")

    def test_the_mainnet_instance_takes_the_host(self):
        text = instance_config(origin="https://mainnet.hidebox.app")
        out = tomllib.loads(cutover.mainnet_config(text, "hidebox.app", "testnet.hidebox.app", "mainnet.hidebox.app"))
        self.assertEqual((out["public_origin"], out["memo_origins"], out["testnet_origin"], out["legacy_origin"],
                          out["redirect_hosts"]),
                         ("https://hidebox.app", ["https://hidebox.app", "https://mainnet.hidebox.app"],
                          "https://testnet.hidebox.app", "https://testnet.hidebox.app", ["mainnet.hidebox.app"]))
        config.from_dict(out)
        self.assertEqual(out["ootle"], tomllib.loads(text)["ootle"])      # only top-level keys move
        with self.assertRaises(cutover.Stop):
            cutover.mainnet_config(text, "hidebox.app", "testnet.hidebox.app", "elsewhere.example")

    def test_a_key_is_set_once_in_the_top_level(self):
        text = 'public_origin = "https://a.example"\n[x]\nlegacy_origin = "keep"\n'
        out = cutover.set_key(text, "legacy_origin", '"https://b.example"')
        self.assertEqual(tomllib.loads(out)["legacy_origin"], "https://b.example")
        self.assertEqual(tomllib.loads(out)["x"]["legacy_origin"], "keep")
        with self.assertRaises(cutover.Stop):
            cutover.set_key('a = 1\na = 2\npublic_origin = "x"\n', "a", "3")

    def test_caddy_env(self):
        self.assertEqual(cutover.caddy_env("# x\nMUTIS_HOST=hidebox.app\n", "hidebox.app", "testnet.hidebox.app"),
                         "# x\nMUTIS_HOST=testnet.hidebox.app\n")
        with self.assertRaises(cutover.Stop):
            cutover.caddy_env("MUTIS_HOST=other.example\n", "hidebox.app", "testnet.hidebox.app")


if __name__ == "__main__":
    unittest.main()
