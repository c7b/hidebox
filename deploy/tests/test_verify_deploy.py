# SPDX-License-Identifier: MIT
"""tools/verify-deploy.py compare(): equal sites pass; changed bytes, missing files and a lying
manifest are each reported. A local HTTP server plays the live site. The rebuild's config: the
variant tables the live manifest records, and nothing else a manifest could smuggle in."""
import hashlib
import http.server
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import threading
import tomllib
import unittest
from functools import partial
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify_deploy", ROOT / "tools" / "verify-deploy.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
spec = importlib.util.spec_from_file_location("wasm_check", ROOT / "template" / "wasm_check.py")
wasm_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wasm_check)
# GET /substates answers of tari_indexer 0.47.0, recorded from both Esmeralda indexers (the live SealLog among them).
RECORDED = json.loads((ROOT / "server" / "tests" / "fixtures" / "indexer-substates-0.47.0.json").read_text())
SEALLOG = RECORDED["seallog_component"]
SEALLOG_TEMPLATE = "40c5f1cfccf753613ce99245ed49ebef0b308084a52ad0c5cd48959d90fa0a47"
SERVICE_KEY = "9c686313d4ebe9c442196ccdce78cf802eab4549961cbc69522d967ed8a55420"


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


class SealLogTemplateTest(unittest.TestCase):
    """The SealLog check reads the log's template from the indexer in tari_indexer 0.47.0's shape
    (`state.up.substate`) and the earlier one (`substate`), and runs wasm_check.py on exactly that address."""

    def check(self, body) -> tuple[list[str], list]:
        runs = []

        def run(cmd, **kwargs):
            runs.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "the chain runs seal_log.wasm byte for byte\n", "")
        with mock.patch.object(verify, "fetch", return_value=json.dumps(body).encode()), \
                mock.patch.object(verify.subprocess, "run", run), mock.patch("builtins.print"):
            diffs = verify.seallog_check({"seal_log": {"component": SEALLOG["id"]}}, ROOT)
        return diffs, runs

    def test_the_live_logs_template_is_checked_in_either_shape(self):
        older = {"verified": True, "substate": SEALLOG["body"]["state"]["up"]["substate"]}
        for body in (SEALLOG["body"], older):
            diffs, runs = self.check(body)
            self.assertEqual(diffs, [])
            self.assertEqual(runs[0][-2:], ["onchain", f"template_{SEALLOG_TEMPLATE}"])

    def test_no_live_component_is_a_difference(self):
        for body in (RECORDED["spent_utxo_at_version"]["body"], {"state": {"up": {"substate": {"Utxo": {}}}}},
                     RECORDED["spent_utxo"]["body"], []):
            diffs, runs = self.check(body)
            self.assertEqual((len(diffs), runs), (1, []), body if isinstance(body, list) else list(body))
            self.assertIn("could not read its template", diffs[0])

    def onchain(self, body) -> int:
        reply = io.BytesIO(json.dumps(body).encode())
        with mock.patch.object(wasm_check.urllib.request, "urlopen", return_value=reply), \
                mock.patch("builtins.print"):
            return wasm_check.onchain(SEALLOG_TEMPLATE, "https://indexer.example", ROOT / "template" / "dist" /
                                      "seal_log.wasm", None)

    def test_wasm_check_reads_the_template_in_either_shape(self):
        """The live template holds dist/seal_log.wasm, published by the service key (setup-accounts.md §4)."""
        wasm = (ROOT / "template" / "dist" / "seal_log.wasm").read_bytes()
        value = {"Template": {"template_name": "SealLog", "author": SERVICE_KEY, "binary": wasm.hex(),
                              "at_epoch": 12149, "metadata_hash": None}}
        self.assertEqual(wasm_check.template_address(SERVICE_KEY, wasm), SEALLOG_TEMPLATE)
        self.assertEqual(self.onchain({"version": 0, "state": {"up": {"substate": value}}, "verified": True}), 0)
        self.assertEqual(self.onchain({"verified": True, "substate": value}), 0)
        other = {"Template": {**value["Template"], "binary": (wasm + b"\0").hex()}}
        self.assertEqual(self.onchain({"version": 0, "state": {"up": {"substate": other}}, "verified": True}), 1)
        self.assertEqual(self.onchain({"version": 0, "state": {"down": {}}, "verified": True}), 1)
        self.assertEqual(self.onchain({"version": 0, "state": {"up": {"substate": {"Component": {}}}}}), 1)


if __name__ == "__main__":
    unittest.main()
