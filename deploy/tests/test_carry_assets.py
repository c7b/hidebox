# SPDX-License-Identifier: MIT
"""deploy/scripts/carry-assets.py: the live release's fingerprinted files, and only its own, reach the next release."""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("carry_assets", ROOT / "deploy" / "scripts" / "carry-assets.py")
carry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(carry)
sys.path.insert(0, str(ROOT / "tools"))
import assets  # noqa: E402


class CarryAssetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-carry-test-"))
        self.old, self.new = self.tmp / "old", self.tmp / "new"
        files = {"site/js/site.0123456789.js": b"old site", "site/js/site.js": b"old plain", "index.html": b"<p>",
                 "app/ui/view.aaaaaaaaaa.js": b"same name in both"}
        for rel, data in files.items():
            (self.old / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.old / rel).write_bytes(data)
        (self.old / "site/js/site.0123456789.js.gz").write_bytes(b"gz")
        (self.old / "site/js/carried.bbbbbbbbbb.js").write_bytes(b"carried by the old release itself, not in its manifest")
        (self.old / ".well-known").mkdir()
        (self.old / ".well-known" / "mutis-manifest.json").write_text(json.dumps({"files": {k: "x" for k in files}}))
        (self.new / "app/ui").mkdir(parents=True)
        (self.new / "app/ui/view.aaaaaaaaaa.js").write_bytes(b"new bytes")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_only_the_old_releases_own_hashed_names_and_their_copies(self):
        self.assertEqual(carry.carry(self.old, self.new), 1)
        self.assertEqual((self.new / "site/js/site.0123456789.js").read_bytes(), b"old site")
        self.assertEqual((self.new / "site/js/site.0123456789.js.gz").read_bytes(), b"gz")
        self.assertFalse((self.new / "site/js/site.js").exists(), "plain names are the new build's")
        self.assertFalse((self.new / "index.html").exists())
        self.assertFalse((self.new / "site/js/carried.bbbbbbbbbb.js").exists(), "one release back only")
        self.assertEqual((self.new / "app/ui/view.aaaaaaaaaa.js").read_bytes(), b"new bytes", "never overwritten")

    def test_no_manifest_carries_nothing(self):
        (self.old / ".well-known" / "mutis-manifest.json").unlink()
        self.assertEqual(carry.carry(self.old, self.new), 0)

    def test_the_pattern_is_the_builds(self):
        self.assertEqual(carry.HASHED_NAME.pattern, assets.HASHED_NAME.pattern)


if __name__ == "__main__":
    unittest.main()
