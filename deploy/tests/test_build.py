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
CFG = {"public_origin": "https://example.test", "gates": {"send_mode": "relay", "amount_proof": "wallet"},
       "features": {"seallog": False, "kept": True}, "hosting": {"snapshots": "weekly"}}
VALUES = {"ORIGIN": "https://example.test", "NETWORK": "Esmeralda", "SECURITY_DROP_URL": "https://example.test/fine-print#report",
          "REPO_URL": "https://code.example/mutis", "BRAND": "hidebox"}
PAGE = """<!doctype html>
<!-- SPDX-License-Identifier: MIT -->
<html lang="en"><head><title>t</title>
<link rel="canonical" href="{{ORIGIN}}/how">
<link rel="stylesheet" href="/site/css/site.css" integrity="{{SRI}}">
<script type="module" src="/site/js/site.js" integrity="{{SRI}}"></script>
</head><body><!--#include header--><main><p>{{BRAND}} · {{NETWORK}} · {{GIT_SHA}} · {{BUILD_DATE}}</p>
<p data-when="send_mode=relay">Our relay posts it.</p><p data-when="send_mode=direct" hidden>Your browser posts it.</p>
</main></body></html>
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
        (web / "site" / "pages").mkdir(parents=True)
        (web / "site" / "pages" / "how.html").write_text(PAGE)
        (web / "site" / "pages" / "index.html").write_text(PAGE)
        (web / "site" / "pages" / "404.html").write_text(PAGE)
        (web / "site" / "pages" / "made.html").write_text(PAGE)
        (web / "site" / "pages" / "fine-print.html").write_text(PAGE)
        (web / "site" / "pages" / "status.html").write_text(PAGE.replace("<title>", '<meta name="robots" content="noindex"><title>'))
        (web / "site" / "css").mkdir()
        (web / "site" / "css" / "site.css").write_text("/* SPDX-License-Identifier: MIT */\nbody { margin: 0; }\n")
        (web / "site" / "js").mkdir()
        (web / "site" / "js" / "site.js").write_text("// SPDX-License-Identifier: MIT\nexport const x = 1;\n")
        (web / "site" / "static" / ".well-known").mkdir(parents=True)
        (web / "site" / "static" / ".well-known" / "security.txt").write_text("Contact: {{SECURITY_DROP_URL}}\n")
        (web / "site" / "tools").mkdir()
        for tool in ("variants.py", "llms_full.py"):
            shutil.copyfile(ROOT / "web" / "site" / "tools" / tool, web / "site" / "tools" / tool)
        (web / "app" / "tests").mkdir(parents=True)
        (web / "app" / "tests" / "run.html").write_text("<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n")
        (web / "app" / "README.md").write_text("<!-- SPDX-License-Identifier: MIT -->\n# app\n")
        shutil.copytree(ROOT / "web" / "app" / "vendor", web / "app" / "vendor")
        self.web = web

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, holding: bool = False, cfg: dict = CFG) -> dict:
        state = build.source_state(SOURCE)
        return build.build(self.web, self.tmp / "dist", self.tmp / "release", cfg, VALUES, state, holding=holding)

    def test_the_drive_font_is_pinned(self):
        """A tree with the drive serves Geist, the pinned bytes only (a font can't carry SRI)."""
        (self.web / "app" / "drive.html").write_text(PAGE)
        with self.assertRaisesRegex(build.BuildError, "font file missing"):
            self.build()
        fonts = self.web / "shared" / "fonts" / "geist"
        fonts.mkdir(parents=True)
        shutil.copyfile(ROOT / "web" / "shared" / "fonts" / "geist" / "OFL.txt", fonts / "OFL.txt")
        shutil.copyfile(ROOT / "web" / "shared" / "fonts" / "geist" / "Geist-Latin.woff2", fonts / "Geist-Latin.woff2")
        data = bytearray((ROOT / "web" / "shared" / "fonts" / "geist" / "Geist-Variable.woff2").read_bytes())
        (fonts / "Geist-Variable.woff2").write_bytes(data)
        self.build()
        self.assertEqual((self.tmp / "dist" / "shared" / "fonts" / "geist" / "Geist-Variable.woff2").read_bytes(), data)
        data[100] ^= 1
        (fonts / "Geist-Variable.woff2").write_bytes(data)
        with self.assertRaisesRegex(build.BuildError, "font hash mismatch"):
            self.build()

    def test_layout_includes_placeholders(self):
        self.build()
        dist = self.tmp / "dist"
        how = (dist / "how" / "index.html").read_text()
        self.assertIn('<header><a href="https://code.example/mutis">code</a></header>', how)
        self.assertNotIn("<!--#include", how)
        self.assertEqual(how.count("SPDX"), 1, "the partial's own license comment is not repeated")
        self.assertIn("hidebox · Esmeralda · " + "a" * 40 + " · 2025-10-09", how)
        for path in ("index.html", "404.html", "how/index.html", "status/index.html", "shared/tokens.css",
                     "site/js/site.js", "vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm",
                     "app/vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm"):
            self.assertTrue((dist / path).is_file(), path)
        for absent in ("app/tests/run.html", "app/README.md", "shared/partials/header.html"):
            self.assertFalse((dist / absent).exists(), absent)
        self.assertEqual((dist / ".well-known" / "security.txt").read_text(), "Contact: https://example.test/fine-print#report\n")

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
            self.assertTrue((dist / "vendor" / "ootle-wasm-0.46.0" / kept).is_file(), kept)

    def test_the_preview_and_its_loops_are_served_and_kept_out_of_the_sitemap(self):
        """/v2 (docs/review/home-v2.md): pages/v2.html builds to v2/index.html, its loops under web/site/media reach
        dist/site/media with their bytes (and the manifest), anything else there stays out, and noindex keeps it out
        of the sitemap."""
        (self.web / "site" / "pages" / "v2.html").write_text(PAGE.replace("<title>", '<meta name="robots" content="noindex"><title>'))
        motion = self.web / "site" / "media" / "motion"
        motion.mkdir(parents=True)
        loops = {"loop.webm": b"\x1aE\xdf\xa3webm", "loop.mp4": b"\0\0\0 ftypisom", "loop_poster.png": b"\x89PNG\r\n"}
        for name, data in loops.items():
            (motion / name).write_bytes(data)
        (motion / "loop.mov").write_bytes(b"not served")
        summary = self.build()
        dist = self.tmp / "dist"
        self.assertTrue((dist / "v2" / "index.html").is_file())
        manifest = json.loads((dist / ".well-known" / "mutis-manifest.json").read_text())["files"]
        for name, data in loops.items():
            self.assertEqual((dist / "site" / "media" / "motion" / name).read_bytes(), data, name)
            self.assertIn(f"site/media/motion/{name}", manifest)
        self.assertFalse((dist / "site" / "media" / "motion" / "loop.mov").exists())
        self.assertNotIn("/v2", (dist / "sitemap.xml").read_text())
        self.assertGreater(summary["files"], 3)

    def test_the_homes_stills_are_served_and_the_home_is_in_the_sitemap(self):
        """The home (the v3 design, docs/review/promote-v3.md): its AVIF and WebP stills under web/site/media/v3 reach
        dist/site/media/v3 byte for byte (and the manifest), and the sitemap lists / (indexable, canonical) and no
        /v3, which is a redirect, not a page."""
        stills = self.web / "site" / "media" / "v3"
        stills.mkdir(parents=True)
        files = {"hero-480.avif": b"\0\0\0\x1cftypavif", "hero-480.webp": b"RIFF\0\0\0\0WEBPVP8 "}
        for name, data in files.items():
            (stills / name).write_bytes(data)
        self.build()
        dist = self.tmp / "dist"
        manifest = json.loads((dist / ".well-known" / "mutis-manifest.json").read_text())["files"]
        for name, data in files.items():
            self.assertEqual((dist / "site" / "media" / "v3" / name).read_bytes(), data, name)
            self.assertIn(f"site/media/v3/{name}", manifest)
        sitemap = (dist / "sitemap.xml").read_text()
        self.assertIn("<loc>https://example.test/</loc>", sitemap)
        self.assertNotIn("/v3", sitemap)
        self.assertFalse((dist / "v3").exists())

    def test_the_favicon_ico_is_served(self):
        """/favicon.ico, which Bing, feed readers and old browsers ask for by name, reaches dist/ (render-images.py
        writes it; before promote-v3 the build left .ico out and production answered 404)."""
        data = b"\0\0\1\0\1\0" + b"\x89PNG\r\n"
        (self.web / "site" / "static" / "favicon.ico").write_bytes(data)
        self.build()
        self.assertEqual((self.tmp / "dist" / "favicon.ico").read_bytes(), data)
        manifest = json.loads((self.tmp / "dist" / ".well-known" / "mutis-manifest.json").read_text())["files"]
        self.assertIn("favicon.ico", manifest)

    def test_test_evidence_is_never_served(self):
        (self.web / "app" / "shots").mkdir()
        (self.web / "app" / "shots" / "home-390.webp").write_bytes(b"RIFF")
        (self.web / "app" / "ui" / "tests").mkdir(parents=True)
        (self.web / "app" / "ui" / "tests" / "fixture.json").write_text("{}\n")
        self.build()
        self.assertFalse((self.tmp / "dist" / "app" / "shots").exists(), "screenshots show dev links with keys")
        self.assertFalse((self.tmp / "dist" / "app" / "ui" / "tests").exists())

    def test_copy_variants_follow_the_config(self):
        self.build()
        how = (self.tmp / "dist" / "how" / "index.html").read_text()
        self.assertIn('<p data-when="send_mode=relay">Our relay posts it.</p>', how)
        self.assertIn('<p data-when="send_mode=direct" hidden>', how)
        direct = CFG | {"gates": {"send_mode": "direct", "amount_proof": "sidecar"}}
        self.build(cfg=direct)
        how = (self.tmp / "dist" / "how" / "index.html").read_text()
        self.assertIn('<p data-when="send_mode=relay" hidden>', how)
        self.assertIn('<p data-when="send_mode=direct">Your browser posts it.</p>', how)
        llms = (self.tmp / "dist" / "llms-full.txt").read_text()
        self.assertIn("Your browser posts it.", llms, "llms-full.txt is written from the built pages")
        self.assertNotIn("Our relay posts it.", llms)
        self.assertIn("https://example.test/how", llms, "its placeholders are filled")
        manifest = json.loads((self.tmp / "dist" / ".well-known" / "mutis-manifest.json").read_text())
        self.assertEqual(manifest["variant_config"]["gates"], direct["gates"], "verify-deploy rebuilds with these")
        self.assertNotIn("public_origin", manifest["variant_config"])

    def test_a_site_build_needs_the_variants_tool(self):
        (self.web / "site" / "tools" / "variants.py").unlink()
        with self.assertRaisesRegex(build.BuildError, "variants"):
            self.build()

    def test_content_id_names_what_is_served(self):
        first = self.build()["content_id"]
        self.assertRegex(first, r"^[0-9a-f]{8}$")
        self.assertEqual(self.build()["content_id"], first, "same commit and config, same release id")
        state = build.source_state(SOURCE)
        moved = build.build(self.web, self.tmp / "dist", self.tmp / "release", CFG,
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
                     "vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm"):
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

    def test_the_app_names_the_same_brand(self):
        lib = self.web / "app" / "lib"
        lib.mkdir(parents=True)
        (lib / "i18n.js").write_text(f"// SPDX-License-Identifier: MIT\nexport const BRAND = '{build.BRAND}';\n")
        self.build()
        (lib / "i18n.js").write_text("// SPDX-License-Identifier: MIT\nexport const BRAND = 'mutis';\n")
        with self.assertRaisesRegex(build.BuildError, "BRAND"):
            self.build()
        self.assertEqual(build.settings({"public_origin": "https://h.example"}, None)["BRAND"], build.BRAND)

    def test_vendored_hash_mismatch_stops_the_build(self):
        wasm = self.web / "app" / "vendor" / "ootle-wasm-0.46.0" / "ootle_wasm_bg.wasm"
        wasm.write_bytes(wasm.read_bytes() + b"\0")
        with self.assertRaisesRegex(build.BuildError, "hash mismatch"):
            self.build()

    def test_settings(self):
        config = self.tmp / "m.toml"
        config.write_text('public_origin = "https://h.example"\nsecurity_drop_url = ""\n')
        cfg = build.load_config(config)
        values = build.settings(cfg, None)
        self.assertEqual(values["SECURITY_DROP_URL"], "https://h.example/fine-print#report")
        self.assertEqual(build.settings(cfg, "https://other.example/")["ORIGIN"], "https://other.example")
        with self.assertRaises(build.BuildError):
            build.settings(cfg, "http://example.test")

    def test_holding_build(self):
        summary = self.build(holding=True)
        dist = self.tmp / "dist"
        self.assertTrue(summary["holding"])
        self.assertTrue((dist / "holding.css").is_file())
        self.assertIn("Esmeralda testnet", (dist / "index.html").read_text())
        self.assertFalse((dist / "how").exists())


if __name__ == "__main__":
    unittest.main()
