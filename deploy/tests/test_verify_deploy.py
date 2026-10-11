# SPDX-License-Identifier: MIT
"""tools/verify-deploy.py compare(): equal sites pass; changed bytes, missing files and a lying
manifest are each reported. A local HTTP server plays the live site. The rebuild's config: the
variant tables the live manifest records, and nothing else a manifest could smuggle in."""
import hashlib
import http.server
import importlib.util
import shutil
import tempfile
import threading
import tomllib
import unittest
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify_deploy", ROOT / "tools" / "verify-deploy.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class VerifyDeployTest(unittest.TestCase):
    def setUp(self):
        self.site = Path(tempfile.mkdtemp(prefix="mutis-verify-test-"))
        (self.site / "app").mkdir()
        (self.site / "index.html").write_bytes(b"<p>home</p>")
        (self.site / "app" / "a.js").write_bytes(b"export {};")
        self.files = {p: hashlib.sha256((self.site / p).read_bytes()).hexdigest() for p in ("index.html", "app/a.js")}
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(self.site)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.site)

    def compare(self, local_files: dict, live_files: dict) -> list[str]:
        return verify.compare(self.origin, {"files": local_files}, {"git_sha": "abc", "files": live_files}, "abc")

    def test_identical(self):
        self.assertEqual(self.compare(dict(self.files), dict(self.files)), [])

    def test_served_bytes_differ(self):
        (self.site / "app" / "a.js").write_bytes(b"export const evil = 1;")
        self.assertEqual(self.compare(dict(self.files), dict(self.files)), ["app/a.js: served bytes differ from the build"])

    def test_lying_manifest_is_caught(self):
        live = dict(self.files) | {"app/a.js": "0" * 64}
        self.assertEqual(self.compare(dict(self.files), live), ["app/a.js: the live manifest's hash is wrong"])

    def test_missing_and_extra_files_and_commit(self):
        local = dict(self.files) | {"new.html": "1" * 64}
        live = dict(self.files) | {"old.html": "2" * 64}
        diffs = verify.compare(self.origin, {"files": local}, {"git_sha": "other", "files": live}, "abc")
        self.assertIn("missing on the live site: new.html", diffs)
        self.assertIn("on the live site but not in the build: old.html", diffs)
        self.assertTrue(any("commit other" in d for d in diffs))


class BuildConfigTest(unittest.TestCase):
    def test_the_variant_tables_of_the_live_build_are_used(self):
        cfg = {"network": "esmeralda", "security_drop": None, "repo_url": "https://code.example/mutis"}
        recorded = {"gates": {"send_mode": "direct", "amount_proof": "sidecar"}, "features": {"seallog": True},
                    "hosting": {"snapshots": "off"}}
        doc = tomllib.loads(verify.build_config("https://h.example", cfg, recorded))
        self.assertEqual(doc["public_origin"], "https://h.example")
        self.assertEqual(doc["security_drop_url"], "")
        self.assertEqual({t: doc[t] for t in ("gates", "features", "hosting")}, recorded)

    def test_a_manifest_cannot_add_keys_or_tables(self):
        recorded = {"gates": {"send_mode": "relay", 'x = 1\n[evil]\ny': True, "nested": {"a": 1}},
                    "secrets": {"key": "value"}}
        doc = tomllib.loads(verify.build_config("https://h.example", {}, recorded))
        self.assertEqual(doc["gates"], {"send_mode": "relay"})
        self.assertNotIn("secrets", doc)
        self.assertNotIn("evil", doc)

    def test_no_seallog_no_check(self):
        self.assertEqual(verify.seallog_check({"seal_log": {"component": None}}, ROOT), [])

    def test_a_component_that_isnt_an_address_is_a_difference(self):
        diffs = verify.seallog_check({"seal_log": {"component": "component_../../evil?x="}}, ROOT)
        self.assertEqual(len(diffs), 1)
        self.assertIn("no valid component", diffs[0])


if __name__ == "__main__":
    unittest.main()
