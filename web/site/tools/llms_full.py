# SPDX-License-Identifier: MIT
"""Writes static/llms-full.txt: the main text of /how and /security as plain text, exactly as a
reader without JavaScript sees it (hidden variants and live numbers left out), so the file can't
drift from the pages. tools/variants.py writes it again from the built pages of a deployment.
Python standard library only.

Usage: python3 -I web/site/tools/llms_full.py [--check]   (--check exits 1 if the file is stale)
"""
import sys
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
PAGES = (("how", "How mutis works"), ("security", "Security"))
BLOCK = {"p", "li", "h1", "h2", "h3", "dt", "dd", "tr", "pre", "blockquote", "figcaption"}
VOID = {"br", "img", "input", "meta", "link", "hr", "col", "source", "use", "path"}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.line = [], []
        self.depth = 0          # inside <main>
        self.skip = []          # stack of open tags that hide their content
        self.href = []

    def flush(self):
        text = " ".join("".join(self.line).split())
        if text:
            self.lines.append(text)
        self.line = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.depth += 1
        if not self.depth or tag in VOID:
            return
        hides = "hidden" in a or a.get("aria-hidden") == "true" or tag in ("svg", "canvas", "nav", "script")
        if self.skip or hides:
            self.skip.append(tag)
            return
        if tag in BLOCK:
            self.flush()
            if tag in ("h2", "h3"):
                self.lines.append("")
                self.line.append("## " if tag == "h2" else "### ")
            elif tag in ("li", "dt"):
                self.line.append("- ")
        if tag in ("td", "th"):
            self.line.append(" | ")
        self.href.append(a.get("href") if tag == "a" else None)

    def handle_endtag(self, tag):
        if tag == "main":
            self.flush()
            self.depth -= 1
        if not self.depth or tag in VOID:
            return
        if self.skip:
            if self.skip[-1] == tag:
                self.skip.pop()
            return
        href = self.href.pop() if self.href else None
        if href and not href.startswith("#"):
            self.line.append(f" ({href})")
        if tag in BLOCK:
            self.flush()

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.line.append(data)


def render(read=lambda name: (SITE / "pages" / f"{name}.html").read_text()) -> str:
    """read(name) -> the HTML of the page called name ("how", "security")."""
    out = ["# mutis: How it works and Security (full text)", "",
           "Live limits and prices: {{ORIGIN}}/api/v1/config", ""]
    for name, title in PAGES:
        parser = Text()
        parser.feed(read(name))
        out += [f"# {title} ({{{{ORIGIN}}}}/{name})", ""] + parser.lines + [""]
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    target = SITE / "static" / "llms-full.txt"
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if target.read_text() == text else "llms-full.txt is stale: run web/site/tools/llms_full.py")
    target.write_text(text)
    print(f"wrote {target} ({len(text)} bytes)")
