# SPDX-License-Identifier: MIT
"""tools/verify-deploy.py compare(): equal sites pass; changed bytes, missing files, a lying manifest and a
precompressed copy that decodes to other bytes are each reported. A local HTTP server plays the live site (serving
NAME.gz with Content-Encoding: gzip to a client that takes it, as Caddy does). The rebuild's config: the variant tables
the live manifest records, and nothing else a manifest could smuggle in."""
import base64
import gzip
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
WASM_CHECK = ROOT / "template" / "wasm_check.py"
wasm_check = None
if WASM_CHECK.is_file():          # deploy.sh's gate copies only server, tools, web, deploy and tests
    spec = importlib.util.spec_from_file_location("wasm_check", WASM_CHECK)
    wasm_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wasm_check)
# GET /substates answers of tari_indexer 0.47.0, recorded from both Esmeralda indexers (the live SealLog among them).
RECORDED = json.loads((ROOT / "server" / "tests" / "fixtures" / "indexer-substates-0.47.0.json").read_text())
SEALLOG = RECORDED["seallog_component"]
SEALLOG_TEMPLATE = "5932ee9ba5a969f59eac0cddc8fae7112b22dfc85abdaa751911d11ce533145c"   # since the 2026-11-02 reset
RECORDED_047_TEMPLATE = "40c5f1cfccf753613ce99245ed49ebef0b308084a52ad0c5cd48959d90fa0a47"   # the log before it
# the live log after the reset, as tari_indexer 0.49.1 serves it (an Encoded value)
LIVE_049 = json.loads((ROOT / "server" / "tests" / "fixtures" / "indexer-0.49.json").read_text())
# Esmeralda's SealLog since the 2026-11-02 reset (the 0.37 build, a V1 definition), and a stand-in for its successor.
LIVE_LOG = "component_6a3eae198ed483565abf978f7c5289263f13b2edf3ef3900a9924dd41141bd65"
NEXT_LOG = "component_" + "5e" * 32
SERVICE_KEY = "78c215f87db6afcc916cb20cb032f9989ccf7f54905bdf5e9e64cca69260ac06"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        sidecar = Path(self.translate_path(self.path) + ".gz")
        if "gzip" in self.headers.get("Accept-Encoding", "") and sidecar.is_file():
            body = sidecar.read_bytes()
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


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

    def test_precompressed_copies_are_checked(self):
        """A browser that takes gzip gets app/a.js.gz: it must decode to the built file."""
        (self.site / "app" / "a.js.gz").write_bytes(gzip.compress(b"export {};", mtime=0))
        notes = []
        self.assertEqual(verify.compare(self.origin, {"files": self.files}, {"git_sha": "abc", "files": self.files}, "abc",
                                        {"app/a.js"}, notes), [])
        self.assertTrue(notes and notes[0].startswith("compressed answers checked: 2 gzip"), notes)
        (self.site / "app" / "a.js.gz").write_bytes(gzip.compress(b"export const evil = 1;", mtime=0))
        diffs = verify.compare(self.origin, {"files": self.files}, {"git_sha": "abc", "files": self.files}, "abc", {"app/a.js"})
        self.assertEqual(diffs, ["app/a.js: the gzip answer to Accept-Encoding: gzip decodes to other bytes",
                                 "app/a.js: the gzip answer to Accept-Encoding: br, gzip decodes to other bytes"])
        (self.site / "app" / "a.js.gz").write_bytes(b"not gzip at all")
        self.assertEqual(len(verify.compare(self.origin, {"files": self.files}, {"git_sha": "abc", "files": self.files}, "abc",
                                            {"app/a.js"})), 2)

    def test_compressed_paths_come_from_the_builds_gz_copies(self):
        dist = Path(tempfile.mkdtemp(prefix="mutis-verify-dist-"))
        try:
            (dist / "site").mkdir()
            for name in ("site/a.css", "site/a.css.gz", "site/b.js"):
                (dist / name).write_bytes(b"x")
            self.assertEqual(verify.compressed_paths(dist), {"site/a.css"})
        finally:
            shutil.rmtree(dist)

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

    def test_config_values_that_could_add_markup_are_refused(self):
        """security-audit-1: the deployment being verified supplies repo_url and security_drop; a value that
        could close an attribute or open a tag is a difference, never something to rebuild with."""
        honest = {"network": "esmeralda", "security_drop": "https://h.example/d/0123456789",
                  "repo_url": "https://github.com/c7b/hidebox"}
        self.assertEqual(verify.unsafe_settings(honest), [])
        self.assertEqual(verify.unsafe_settings({}), [])
        self.assertEqual(verify.unsafe_settings({**honest, "network": "mainnet"}), [])
        for key, value in (("repo_url", 'https://github.com/c7b/hidebox"><script src="/x.js"></script>'),
                           ("security_drop", "https://h.example/<svg onload=x>"), ("repo_url", "http://code.example"),
                           ("network", "esmeralda\"><script>"), ("network", "stagenet"), ("repo_url", ["https://x.example"])):
            with self.subTest(key=key):
                self.assertEqual(len(verify.unsafe_settings({**honest, key: value})), 1)
        evil = {**honest, "repo_url": 'https://github.com/c7b/hidebox"><script src="/x.js"></script>'}
        out = io.StringIO()
        with mock.patch.object(verify, "fetch", lambda url: json.dumps({"files": {}}).encode()), \
                mock.patch.object(verify, "live_config", lambda origin: evil), \
                mock.patch.object(verify, "build_tag", side_effect=AssertionError("built with a hostile value")), \
                mock.patch("sys.argv", ["verify-deploy.py", "https://h.example", "v1"]), \
                mock.patch("sys.stdout", out):
            self.assertEqual(verify.main(), 1)
        self.assertIn("DIFF /api/v1/config repo_url is not a plain https URL", out.getvalue())

    def test_a_tag_whose_build_refuses_the_settings_is_a_difference_not_a_traceback(self):
        """A tag from before the mainnet builds Esmeralda only; asked to rebuild a mainnet deployment its build.py
        stops, and verify-deploy says so as a difference."""
        mainnet = {"network": "mainnet", "repo_url": "https://github.com/c7b/hidebox",
                   "testnet_origin": "https://testnet.example"}
        refused = subprocess.CompletedProcess([], 1, "", "Traceback…\nBuildError: network must be one of esmeralda: 'mainnet'\n")
        real_run = subprocess.run

        def run(cmd, **kwargs):
            if any(str(part).endswith("build.py") for part in cmd):
                return refused
            if cmd[0] == "tar":
                return real_run(["true"])
            return subprocess.CompletedProcess(cmd, 0, b"" if "archive" in cmd else "0123456789abcdef\n", "")

        out = io.StringIO()
        with mock.patch.object(verify, "fetch", lambda url: json.dumps({"files": {}}).encode()), \
                mock.patch.object(verify, "live_config", lambda origin: mainnet), \
                mock.patch.object(verify.subprocess, "run", run), \
                mock.patch("sys.argv", ["verify-deploy.py", "https://h.example", "v1"]), \
                mock.patch("sys.stdout", out):
            self.assertEqual(verify.main(), 1)
        self.assertIn("DIFF v1's tools/build.py did not build with this deployment's settings: BuildError: network must "
                      "be one of esmeralda: 'mainnet'", out.getvalue())

    def test_no_seallog_no_check(self):
        self.assertEqual(verify.seallog_check({"seal_log": {"component": None}}, ROOT), [])

    def test_a_component_that_isnt_an_address_is_a_difference(self):
        diffs = verify.seallog_check({"seal_log": {"component": "component_../../evil?x="}}, ROOT)
        self.assertEqual(len(diffs), 1)
        self.assertIn("no valid component", diffs[0])


class SealLogTemplateTest(unittest.TestCase):
    """The SealLog check reads the log's template from the indexer in tari_indexer 0.47.0's shape
    (`state.up.substate`), the earlier one (`substate`) and 0.48's Encoded value, and runs wasm_check.py on exactly
    that address against one build: template/dist-v2/, or template/dist/ for the one V1 log (Esmeralda's since the
    2026-11-02 reset, until /api/v1/config names its successor)."""

    @classmethod
    def setUpClass(cls):
        """A tag's tree as the check reads it: both builds (stand-in bytes; wasm_check.py is replaced below) and the
        tag's own server/mutis/cbor.py, so the tests don't depend on template/ being in this tree (the deploy gate
        copies server, tools, web, deploy and tests only)."""
        cls._tmp = tempfile.TemporaryDirectory()
        cls.src = Path(cls._tmp.name)
        for build in ("dist", "dist-v2"):
            (cls.src / "template" / build).mkdir(parents=True)
            (cls.src / "template" / build / "seal_log.wasm").write_bytes(b"\0asm\x01\0\0\0")
        (cls.src / "server" / "mutis").mkdir(parents=True)
        shutil.copy(ROOT / "server" / "mutis" / "cbor.py", cls.src / "server" / "mutis" / "cbor.py")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def check(self, body, network: str | None = None, matches: str | None = "dist", component: str = LIVE_LOG,
              src: Path | None = None) -> tuple[list[str], list]:
        """`matches`: the tag's build (template/<matches>/seal_log.wasm) the stand-in wasm_check.py says the chain
        runs; None for none. Returns the differences and every wasm_check.py command line, with the URLs fetched."""
        src = self.src if src is None else src
        runs, urls = [], []

        def run(cmd, **kwargs):
            runs.append(cmd)
            same = matches is not None and cmd[cmd.index("--wasm") + 1].endswith(f"/{matches}/seal_log.wasm")
            return subprocess.CompletedProcess(cmd, 0 if same else 1, "the chain runs seal_log.wasm byte for byte\n"
                                               if same else "FAIL: the chain runs different bytes\n", "")

        def fetch(url):
            urls.append(url)
            return json.dumps(body).encode()
        cfg = {"seal_log": {"component": component}, **({"network": network} if network else {})}
        with mock.patch.object(verify, "fetch", fetch), \
                mock.patch.object(verify.subprocess, "run", run), mock.patch("builtins.print"):
            diffs = verify.seallog_check(cfg, src)
        return diffs, runs + [urls]

    @staticmethod
    def onchain_args(cmd: list) -> list:
        """What a wasm_check.py command line asks: the address, the indexer and the local build."""
        at = cmd.index("onchain")
        return [cmd[at + 1], cmd[cmd.index("--indexer") + 1], Path(cmd[cmd.index("--wasm") + 1]).parent.name]

    def test_the_live_logs_template_is_checked_in_either_shape(self):
        older = {"verified": True, "substate": SEALLOG["body"]["state"]["up"]["substate"]}
        for body in (SEALLOG["body"], older):
            diffs, runs = self.check(body)
            self.assertEqual(diffs, [])
            self.assertEqual(self.onchain_args(runs[0]),
                             [f"template_{RECORDED_047_TEMPLATE}", "https://ootle-indexer-a.tari.com", "dist"])
        # 0.48+: an Encoded component, read with the tag's server/mutis/cbor.py
        diffs, runs = self.check(LIVE_049["seallog_component_answer"])
        self.assertEqual(diffs, [])
        self.assertEqual(self.onchain_args(runs[0]), [f"template_{SEALLOG_TEMPLATE}", "https://ootle-indexer-a.tari.com", "dist"])
        self.assertEqual(runs[-1], [f"https://ootle-indexer-a.tari.com/substates/{LIVE_LOG}"])

    def test_only_the_named_v1_log_may_run_the_v1_build(self):
        self.assertEqual(verify.V1_LOGS, {("esmeralda", LIVE_LOG.removeprefix("component_")): "dist"})
        # The live V1 log is held to template/dist/ alone: the V2 bytes under its address are a difference.
        diffs, runs = self.check(LIVE_049["seallog_component_answer"], matches="dist-v2")
        self.assertEqual([self.onchain_args(r)[2] for r in runs[:-1]], ["dist"])
        self.assertEqual(len(diffs), 1)
        self.assertIn("template/dist/seal_log.wasm", diffs[0])
        # Any other log, its successor included, must run template/dist-v2/; the V1 build is not tried for it.
        diffs, runs = self.check(LIVE_049["seallog_component_answer"], matches="dist-v2", component=NEXT_LOG)
        self.assertEqual(diffs, [])
        self.assertEqual([self.onchain_args(r)[2] for r in runs[:-1]], ["dist-v2"])
        diffs, runs = self.check(LIVE_049["seallog_component_answer"], matches="dist", component=NEXT_LOG)
        self.assertEqual([self.onchain_args(r)[2] for r in runs[:-1]], ["dist-v2"])
        self.assertEqual(len(diffs), 1)
        self.assertIn("template/dist-v2/seal_log.wasm", diffs[0])
        # The exception is Esmeralda's: the same address on the mainnet is held to the V2 build.
        diffs, runs = self.check(LIVE_049["seallog_component_answer"], "mainnet", matches="dist")
        self.assertEqual([self.onchain_args(r)[2] for r in runs[:-1]], ["dist-v2"])
        self.assertEqual(len(diffs), 1)

    def test_a_tag_without_the_logs_build_is_a_difference_and_nothing_is_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            (src / "template" / "dist").mkdir(parents=True)
            (src / "template" / "dist" / "seal_log.wasm").write_bytes(b"\0asm\x01\0\0\0")
            older = {"verified": True, "substate": SEALLOG["body"]["state"]["up"]["substate"]}
            diffs, runs = self.check(older, component=NEXT_LOG, src=src)
            self.assertEqual(runs[:-1], [])
            self.assertEqual(len(diffs), 1)
            self.assertIn("no template/dist-v2/seal_log.wasm", diffs[0])
            diffs, runs = self.check(older, src=src)       # the V1 log in an older tag: template/dist/ is there
            self.assertEqual((diffs, [self.onchain_args(r)[2] for r in runs[:-1]]), ([], ["dist"]))

    def test_a_mainnet_log_is_read_from_a_mainnet_indexer_and_checked_against_the_v2_build(self):
        diffs, runs = self.check(LIVE_049["seallog_component_answer"], "mainnet", matches="dist-v2", component=NEXT_LOG)
        self.assertEqual(diffs, [])
        self.assertEqual(runs[-1], [f"https://indexer-a.ootle.tari.com/substates/{NEXT_LOG}"])
        self.assertEqual(self.onchain_args(runs[0]), [f"template_{SEALLOG_TEMPLATE}", "https://indexer-a.ootle.tari.com", "dist-v2"])
        self.assertEqual(len(runs), 2, "one wasm_check.py run, then the URLs")
        diffs, runs = self.check(LIVE_049["seallog_component_answer"], "mainnet", matches=None, component=NEXT_LOG)
        self.assertEqual(len(diffs), 1)
        self.assertIn("template/dist-v2", diffs[0])

    def test_an_unknown_network_is_refused_before_any_request(self):
        diffs, runs = self.check(SEALLOG["body"], "stagenet")
        self.assertEqual((len(diffs), runs), (1, [[]]))

    def test_no_live_component_is_a_difference(self):
        for body in (RECORDED["spent_utxo_at_version"]["body"], {"state": {"up": {"substate": {"Utxo": {}}}}},
                     RECORDED["spent_utxo"]["body"], []):
            diffs, runs = self.check(body)
            self.assertEqual((len(diffs), runs[:-1]), (1, []), body if isinstance(body, list) else list(body))
            self.assertIn("could not read its template", diffs[0])


def cbor_array(*items) -> bytes:
    """Just enough CBOR for the test: definite arrays of unsigned ints, text and bytes."""
    def head(major: int, n: int) -> bytes:
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise ValueError(n)
    out = head(4, len(items))
    for item in items:
        if isinstance(item, int):
            out += head(0, item)
        elif isinstance(item, str):
            out += head(3, len(item.encode())) + item.encode()
        elif isinstance(item, CborArray):
            out += bytes(item)
        else:
            out += head(2, len(item)) + item
    return CborArray(out)


class CborArray(bytes):
    """An already encoded array, nested as is."""


@unittest.skipUnless(wasm_check, "template/ is not in this tree")
class WasmCheckTest(unittest.TestCase):
    """template/wasm_check.py, which verify-deploy runs from the tag, reads the template in either shape."""

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
        # tari_indexer 0.48+: the value is an Encoded<SubstateValue> (base64 CBOR), here written by hand as
        # minicbor writes a PublishedTemplate: [6, [[name, author, binary, at_epoch]]]
        encoded = base64.b64encode(cbor_array(6, cbor_array(cbor_array("SealLog", bytes.fromhex(SERVICE_KEY), wasm, 12814)))).decode()
        self.assertEqual(self.onchain({"version": 0, "state": {"up": {"substate": encoded}}, "verified": True}), 0)

    @unittest.skipUnless((ROOT / "template" / "dist-v2" / "seal_log.wasm").is_file(), "no template/dist-v2 in this tree")
    def test_the_mainnet_build_is_checked_against_dist_v2(self):
        """dist-v2/seal_log.wasm (tari_template_lib 0.38, V2 definitions): the address a publish by a key creates, and
        the chain's copy compared with it, as Ootle 0.50 encodes a PublishedTemplate (the same layout as 0.49)."""
        v2 = ROOT / "template" / "dist-v2" / "seal_log.wasm"
        wasm = v2.read_bytes()
        address = wasm_check.template_address(SERVICE_KEY, wasm)
        self.assertNotEqual(address, SEALLOG_TEMPLATE)
        self.assertNotEqual(wasm_check.abi_hash(wasm), wasm_check.abi_hash((ROOT / "template" / "dist" / "seal_log.wasm").read_bytes()))
        encoded = base64.b64encode(cbor_array(6, cbor_array(cbor_array("SealLog", bytes.fromhex(SERVICE_KEY), wasm, 12951)))).decode()
        body = {"version": 0, "state": {"up": {"substate": encoded}}, "verified": True}
        for local, expected in ((v2, 0), (ROOT / "template" / "dist" / "seal_log.wasm", 1)):
            with mock.patch.object(wasm_check.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(body).encode())), \
                    mock.patch("builtins.print"):
                self.assertEqual(wasm_check.onchain(address, wasm_check.INDEXERS["mainnet"], local, None), expected, local.parent.name)


if __name__ == "__main__":
    unittest.main()
