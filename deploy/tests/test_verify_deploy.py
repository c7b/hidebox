# SPDX-License-Identifier: MIT
"""tools/verify-deploy.py compare(): equal sites pass; changed bytes, missing files and a lying
manifest are each reported. A local HTTP server plays the live site."""
import hashlib
import http.server
import importlib.util
import shutil
import tempfile
import threading
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


if __name__ == "__main__":
    unittest.main()
