# SPDX-License-Identifier: MIT
"""tools/check-copy.py (P-20): banned words, digits in i18n values, /config numbers in site pages."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_copy", ROOT / "tools" / "check-copy.py")
check_copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_copy)

HEAD = "<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n"


class CheckCopyTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mutis-copy-test-"))
        (self.root / "web" / "site" / "pages").mkdir(parents=True)
        (self.root / "web" / "app" / "i18n").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def page(self, body: str) -> None:
        (self.root / "web" / "site" / "pages" / "p.html").write_text(HEAD + body)

    def test_banned_words_in_visible_text_only(self):
        self.page('<div class="ghost-card vault"><p>Our seamless, military-grade vault.</p>'
                  '<img alt="Unlock it"><script>const magic = 1;</script></div>')
        fails, _ = check_copy.banned_words(self.root)
        found = sorted({f.split("'")[1].lower() for f in fails})
        self.assertEqual(found, ["military-grade", "seamless", "unlock", "vault"])

    def test_exceptions_and_watch_words(self):
        self.page("<p>Bulletproofs+ range proofs. Magic bytes are checked. Just a test harness. Anonymous drop.</p>")
        fails, warns = check_copy.banned_words(self.root)
        self.assertEqual(fails, [])
        self.assertEqual(len(warns), 2)

    def test_not_promises_and_retired_nouns(self):
        self.page("<h2>Receipts, not promises</h2><p>Someone sent you a sealed file.</p>")
        fails, _ = check_copy.banned_words(self.root)
        self.assertEqual(len(fails), 2)

    def test_i18n_digits(self):
        (self.root / "web" / "app" / "i18n" / "en.json").write_text(json.dumps({
            "a": "Up to {anon_max_file} · AES-256-GCM", "b": {"one": "{n} view", "other": "{n} views"},
            "c": "Compare all 12 with them.", "d": "Leaves in 24 hours"}))
        fails = check_copy.i18n_digits(self.root, check_copy.load_allowlist(ROOT / "tools" / "copy-allowlist.txt"))
        self.assertEqual(len(fails), 1)
        self.assertIn(":d:", fails[0])

    def test_config_numbers_in_site_pages(self):
        config = {"limits": {"anon": {"max_file_bytes": 26214400, "max_expiry_s": 86400, "max_views": 10}},
                  "pricing": {"packs": [{"price_ut": "500000", "bytes": 2147483648, "days": 30}]}}
        self.page("<p>Files up to 25 MB, gone in 24 hours, 0.5 tTARI for 2 GB over 30 days.</p>"
                  '<p>Up to <span data-v="anon_max_file">25 MB</span>.</p><ul><li data-cue="views">10 views</li></ul>'
                  "<p>Nov 11, 2026. 404. Cut into 4 MB chunks.</p>")
        config["chunk_size"] = 4194304
        fails = check_copy.hardcoded_config_numbers(self.root, config, ["4 MB chunks"])
        found = sorted(f.split("'")[1] for f in fails)
        self.assertEqual(found, ["0.5 tTARI", "2 GB", "24 hours", "25 MB", "30 days"])


if __name__ == "__main__":
    unittest.main()
