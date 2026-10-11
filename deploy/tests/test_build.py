# SPDX-License-Identifier: MIT
"""tools/build.py: copy layout, includes, placeholders, SRI, vendored hashes, lint gate, sitemap, manifest."""
import base64
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402

SOURCE = ["a" * 40, "v1-test", "1760000000"]
VALUES = {"ORIGIN": "https://example.test", "NETWORK": "Esmeralda", "SECURITY_DROP_URL": "https://example.test/abuse",
          "REPO_URL": "https://code.example/mutis"}
PAGE = """<!doctype html>
<!-- SPDX-License-Identifier: MIT -->
<html lang="en"><head><title>t</title>
<link rel="canonical" href="{{ORIGIN}}/how">
<link rel="stylesheet" href="/site/css/site.css" integrity="{{SRI}}">
<script type="module" src="/site/js/site.js" integrity="{{SRI}}"></script>
</head><body><!--#include header--><p>{{NETWORK}} · {{GIT_SHA}} · {{BUILD_DATE}}</p></body></html>
"""


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-build-test-"))
        web = self.tmp / "web"
        (web / "shared" / "partials").mkdir(parents=True)
        (web / "shared" / "partials" / "header.html").write_text(
            "<!-- SPDX-License-Identifier: MIT -->\n<header><a href=\"{{REPO_URL}}\">code</a></header>\n")
        (web / "shared" / "brand").mkdir()
        (web / "shared" / "brand" / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n')
        for css in ("tokens.css", "base.css"):
            (web / "shared" / css).write_text("/* SPDX-License-Identifier: MIT */\n:root { --x: 1; }\n")
        (web / "site" / "pages" / "es").mkdir(parents=True)
        (web / "site" / "pages" / "how.html").write_text(PAGE)
        (web / "site" / "pages" / "index.html").write_text(PAGE)
        (web / "site" / "pages" / "404.html").write_text(PAGE)
        (web / "site" / "pages" / "es" / "how.html").write_text(PAGE)
        (web / "site" / "pages" / "status.html").write_text(PAGE.replace("<title>", '<meta name="robots" content="noindex"><title>'))
        (web / "site" / "css").mkdir()
        (web / "site" / "css" / "site.css").write_text("/* SPDX-License-Identifier: MIT */\nbody { margin: 0; }\n")
        (web / "site" / "js").mkdir()
        (web / "site" / "js" / "site.js").write_text("// SPDX-License-Identifier: MIT\nexport const x = 1;\n")
        (web / "site" / "static" / ".well-known").mkdir(parents=True)
        (web / "site" / "static" / ".well-known" / "security.txt").write_text("Contact: {{SECURITY_DROP_URL}}\n")
        (web / "app" / "tests").mkdir(parents=True)
        (web / "app" / "tests" / "run.html").write_text("<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n")
        (web / "app" / "README.md").write_text("<!-- SPDX-License-Identifier: MIT -->\n# app\n")
        shutil.copytree(ROOT / "web" / "app" / "vendor", web / "app" / "vendor")
        self.web = web

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, holding: bool = False) -> dict:
        state = build.source_state(SOURCE)
        return build.build(self.web, self.tmp / "dist", self.tmp / "release", VALUES, state, holding=holding)

    def test_layout_includes_placeholders(self):
        self.build()
        dist = self.tmp / "dist"
        how = (dist / "how" / "index.html").read_text()
        self.assertIn('<header><a href="https://code.example/mutis">code</a></header>', how)
        self.assertNotIn("<!--#include", how)
        self.assertEqual(how.count("SPDX"), 1, "the partial's own license comment is not repeated")
        self.assertIn("Esmeralda · " + "a" * 40 + " · 2025-10-09", how)
        for path in ("index.html", "404.html", "es/how/index.html", "status/index.html", "shared/tokens.css",
                     "site/js/site.js", "vendor/ootle-wasm-0.45.0/ootle_wasm_bg.wasm",
                     "app/vendor/ootle-wasm-0.45.0/ootle_wasm_bg.wasm"):
            self.assertTrue((dist / path).is_file(), path)
        for absent in ("app/tests/run.html", "app/README.md", "shared/partials/header.html"):
            self.assertFalse((dist / absent).exists(), absent)
        self.assertEqual((dist / ".well-known" / "security.txt").read_text(), "Contact: https://example.test/abuse\n")

    def test_only_served_types_reach_dist(self):
        for name in ("REVIEW-devil.md", "NOTES-ui.md", "notes.txt.bak", "build.py", "draft.ts"):
            (self.web / "app" / name).write_text("# SPDX-License-Identifier: MIT\n")
        self.build()
        dist = self.tmp / "dist"
        for name in ("REVIEW-devil.md", "NOTES-ui.md", "notes.txt.bak", "build.py", "draft.ts"):
            self.assertFalse((dist / "app" / name).exists(), name)
        markdown = sorted(p.name for p in dist.rglob("*.md"))
        self.assertEqual(markdown, ["PROVENANCE.md", "PROVENANCE.md"], "only the vendored provenance notes")
        for kept in ("LICENSE", "SHA256SUMS", "ootle_wasm.d.ts"):
            self.assertTrue((dist / "vendor" / "ootle-wasm-0.45.0" / kept).is_file(), kept)

    def test_content_id_names_what_is_served(self):
        first = self.build()["content_id"]
        self.assertRegex(first, r"^[0-9a-f]{8}$")
        self.assertEqual(self.build()["content_id"], first, "same commit and config, same release id")
        state = build.source_state(SOURCE)
        moved = build.build(self.web, self.tmp / "dist", self.tmp / "release",
                            VALUES | {"ORIGIN": "https://mutis.example"}, state)["content_id"]
        self.assertNotEqual(moved, first, "same commit with a new origin is a new release")

    def test_sri_is_sha384_of_the_served_file(self):
        self.build()
        how = (self.tmp / "dist" / "how" / "index.html").read_text()
        js = (self.tmp / "dist" / "site" / "js" / "site.js").read_bytes()
        digest = base64.b64encode(hashlib.sha384(js).digest()).decode()
        self.assertIn(f'src="/site/js/site.js" integrity="sha384-{digest}"', how)
        self.assertNotIn("{{SRI}}", how)

    def test_sitemap_skips_404_and_noindex(self):
        self.build()
        sitemap = (self.tmp / "dist" / "sitemap.xml").read_text()
        self.assertIn("<loc>https://example.test/</loc>", sitemap)
        self.assertIn("<loc>https://example.test/how</loc>", sitemap)
        self.assertIn("<loc>https://example.test/es/how</loc>", sitemap)
        self.assertNotIn("404", sitemap)
        self.assertNotIn("/status", sitemap)

    def test_manifest_lists_every_file_and_is_deterministic(self):
        first = json.loads((self.tmp / "dist" / ".well-known" / "mutis-manifest.json").read_text()) if self.build() else None
        files = {p.relative_to(self.tmp / "dist").as_posix() for p in (self.tmp / "dist").rglob("*") if p.is_file()}
        self.assertEqual(set(first["files"]) | {".well-known/mutis-manifest.json"}, files)
        self.build()
        second = json.loads((self.tmp / "dist" / ".well-known" / "mutis-manifest.json").read_text())
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(first["git_sha"], "a" * 40)

    def test_release_sidecar_layout(self):
        (self.web / "app" / "sidecar").mkdir()
        (self.web / "app" / "sidecar" / "sidecar.mjs").write_text("// SPDX-License-Identifier: MIT\n")
        (self.web / "app" / "lib").mkdir()
        (self.web / "app" / "lib" / "format.js").write_text("// SPDX-License-Identifier: MIT\n")
        self.build()
        sidecar = self.tmp / "release" / "sidecar"
        for path in ("sidecar.mjs", "lib/format.js", "vendor/ootle-wasm-shim.js", "vendor/package.json",
                     "vendor/ootle-wasm-0.45.0/ootle_wasm_bg.wasm"):
            self.assertTrue((sidecar / path).is_file(), path)
        self.assertFalse((self.tmp / "dist" / "app" / "sidecar").exists())

    def test_failures(self):
        cases = {
            "unknown include": ("how.html", PAGE.replace("<!--#include header-->", "<!--#include nope-->")),
            "unknown placeholder": ("how.html", PAGE.replace("{{NETWORK}}", "{{NOPE}}")),
            "is not in dist": ("how.html", PAGE.replace("/site/js/site.js", "/site/js/missing.js")),
            "outside an integrity attribute": ("how.html", PAGE + "<p>{{SRI}}</p>"),
            "style attribute": ("how.html", PAGE.replace("<p>", '<p style="color:red">')),
        }
        for expected, (name, text) in cases.items():
            with self.subTest(expected):
                original = (self.web / "site" / "pages" / name).read_text()
                (self.web / "site" / "pages" / name).write_text(text)
                with self.assertRaisesRegex(build.BuildError, expected):
                    self.build()
                (self.web / "site" / "pages" / name).write_text(original)

    def test_vendored_hash_mismatch_stops_the_build(self):
        wasm = self.web / "app" / "vendor" / "ootle-wasm-0.45.0" / "ootle_wasm_bg.wasm"
        wasm.write_bytes(wasm.read_bytes() + b"\0")
        with self.assertRaisesRegex(build.BuildError, "hash mismatch"):
            self.build()

    def test_settings(self):
        config = self.tmp / "m.toml"
        config.write_text('public_origin = "https://h.example"\nsecurity_drop_url = ""\n')
        values = build.settings(config, None)
        self.assertEqual(values["SECURITY_DROP_URL"], "https://h.example/abuse")
        self.assertEqual(build.settings(config, "https://other.example/")["ORIGIN"], "https://other.example")
        with self.assertRaises(build.BuildError):
            build.settings(config, "http://example.test")

    def test_holding_build(self):
        summary = self.build(holding=True)
        dist = self.tmp / "dist"
        self.assertTrue(summary["holding"])
        self.assertTrue((dist / "holding.css").is_file())
        self.assertIn("Esmeralda testnet", (dist / "index.html").read_text())
        self.assertFalse((dist / "how").exists())


if __name__ == "__main__":
    unittest.main()
