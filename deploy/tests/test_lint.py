# SPDX-License-Identifier: MIT
"""tools/lint.py: each rule finds what it should and nothing else."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import lint  # noqa: E402

HEAD_JS = "// SPDX-License-Identifier: MIT\n"
HEAD_HTML = "<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n"


class LintTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mutis-lint-test-"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def problems(self) -> list[str]:
        return lint.lint(self.root)

    def test_clean_tree_passes(self):
        self.write("server/mutis/__init__.py", "# SPDX-License-Identifier: MIT\n")
        self.write("server/app.py", "# SPDX-License-Identifier: MIT\nimport json\nfrom mutis import x\n")
        self.write("web/app/lib/a.js", HEAD_JS + "const u = 'https://ootle-indexer-b.tari.com';\n"
                   "document.createElementNS('http://www.w3.org/2000/svg', 'svg');\n")
        self.write("web/site/pages/index.html", HEAD_HTML + '<link rel="canonical" href="https://mutis.sh/">'
                   '<script type="module" src="/x.js" integrity="{{SRI}}"></script><a href="https://ok.example">x</a>\n')
        self.assertEqual(self.problems(), [])

    def test_python_third_party_import(self):
        self.write("tools/x.py", "# SPDX-License-Identifier: MIT\nimport requests\n")
        self.assertTrue(any("requests" in p for p in self.problems()))

    def test_forbidden_js(self):
        for snippet in ("el.innerHTML = s", "document.write(s)", "eval(s)", "new Function('a')", "setTimeout('x()', 1)",
                        "el.setAttribute('style', 'x')", "el.outerHTML", "el.insertAdjacentHTML('x', y)",
                        "Function('return 1')()", "globalThis.Function('a')", "el.setHTMLUnsafe(s)",
                        "Document.parseHTMLUnsafe(s)", "range.createContextualFragment(s)", "frame.srcdoc = s",
                        "frame.setAttribute('srcdoc', s)"):
            with self.subTest(snippet):
                self.write("web/app/lib/a.js", HEAD_JS + snippet + "\n")
                self.assertTrue(any("forbidden" in p for p in self.problems()), snippet)

    def test_urls_in_served_js(self):
        for snippet, needle in (("fetch('https://evil.example/x')", "remote module"),
                                ("import('//cdn.example/m.js')", "remote module"),
                                ("const a = 'https://evil.example';", "absolute URL"),
                                ("const a = 'http://plain.example';", "http:// URL"),
                                ("const a = '{{ORIGIN}}';", "placeholder")):
            with self.subTest(snippet):
                self.write("web/site/js/a.js", HEAD_JS + snippet + "\n")
                self.assertTrue(any(needle in p for p in self.problems()), snippet)

    def test_test_files_may_use_urls_but_not_sinks(self):
        self.write("web/app/tests/t.js", HEAD_JS + "const o = 'https://mutis.sh/t#3';\n")
        self.assertEqual(self.problems(), [])
        self.write("web/app/tests/t.js", HEAD_JS + "el.innerHTML = 1;\n")
        self.assertTrue(self.problems())

    def test_html_rules(self):
        cases = {'<p style="x">': "style attribute", '<p onclick="x()">': "event handler",
                 "<script>alert(1)</script>": "inline script", '<script src="/a.js"></script>': "without integrity",
                 '<img src="https://cdn.example/a.png">': "remote src",
                 '<link rel="stylesheet" href="//cdn.example/a.css" integrity="x">': "remote href"}
        for snippet, needle in cases.items():
            with self.subTest(snippet):
                self.write("web/site/pages/p.html", HEAD_HTML + snippet + "\n")
                self.assertTrue(any(needle in p for p in self.problems()), snippet)
        self.write("web/site/pages/p.html", HEAD_HTML + '<script type="application/ld+json">{"a": 1}</script>\n')
        self.assertEqual(self.problems(), [])

    def test_css_remote_resource(self):
        self.write("web/shared/a.css", "/* SPDX-License-Identifier: MIT */\n@font-face { src: url(https://fonts.example/a.woff2); }\n")
        self.assertTrue(any("remote resource" in p for p in self.problems()))

    def test_headers_todos_attribution(self):
        self.write("deploy/a.sh", "#!/bin/bash\necho hi\n")
        self.assertTrue(any("SPDX" in p for p in self.problems()))
        self.write("deploy/a.sh", "#!/bin/bash\n# SPDX-License-Identifier: MIT\n# TO" "DO later\n")
        self.assertTrue(any("comment" in p for p in self.problems()))
        self.write("deploy/a.sh", "#!/bin/bash\n# SPDX-License-Identifier: MIT\n")
        self.write("docs/x.md", "text\n\nCo-" "Authored-By: someone\n")
        self.assertTrue(any("attribution" in p for p in self.problems()))


if __name__ == "__main__":
    unittest.main()
