#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Repository lint (spec §0.7, §3.3 step 8, §3.5). Python standard library only.

  python3 -I tools/lint.py [--root DIR]

Checks, with the file sets they apply to:
  - Python (everywhere): every import is the standard library or a module of this repository.
  - JavaScript under web/ (not the vendored official files): no HTML sinks or string-to-code.
  - What the browser loads (web/shared, web/site/{js,css,pages,static}, web/app minus tests and
    sidecar): no http:// URLs; absolute https:// only in <a href> and for the two public Tari
    indexers and the indexer's own page; no remote src, stylesheet, CSS url(), import or fetch; no {{PLACEHOLDER}} in JS or CSS
    (the build fills placeholders only in HTML and text files).
  - Served HTML and partials: no style="…", no on…= handlers, no inline <script> except JSON-LD,
    and integrity="{{SRI}}" on every local script and stylesheet tag.
  - Source files: SPDX-License-Identifier: MIT in the first lines; no TODO/FIXME comments; no
    attribution trailers.
  - Every text file: no public IP address but the server's own (an operator's address in an
    evidence log would name a machine of the owner's; private, loopback, link-local and
    documentation ranges, and x.0.0.0 network literals, are fine).
Exit status 1 when anything is found.
"""
import argparse
import ast
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".git", "dist", "release", "__pycache__", "node_modules", "target"}
DATA_PARTS = ("/tests/evidence/", "/fixtures/", "/template/dist/")
VENDORED = re.compile(r"(^|/)web/app/vendor/ootle-wasm-[^/]+/")
CODE_EXT = {".py", ".js", ".mjs", ".css", ".html", ".sh", ".rs"}
INDEXERS = ("https://ootle-indexer-a.tari.com", "https://ootle-indexer-b.tari.com",
            "https://indexer.esme.tari.com")    # the indexer's own page, a link target only (/verify/tx)
XML_NAMESPACES = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink",
                  "http://www.w3.org/XML/1998/namespace")
SERVED_ROOTS = ("web/shared/", "web/site/js/", "web/site/css/", "web/site/pages/", "web/site/static/", "web/app/",
                "deploy/holding/")
NOT_SERVED = ("web/app/tests/", "web/app/sidecar/", "web/shared/partials/")

FORBIDDEN_JS = [
    (re.compile(r"\binnerHTML\b"), "innerHTML"),
    (re.compile(r"\bouterHTML\b"), "outerHTML"),
    (re.compile(r"\binsertAdjacentHTML\b"), "insertAdjacentHTML"),
    (re.compile(r"\bdocument\.write(ln)?\b"), "document.write"),
    (re.compile(r"\beval\s*\("), "eval("),
    (re.compile(r"\bFunction\s*\("), "Function("),
    (re.compile(r"\b(setHTMLUnsafe|parseHTMLUnsafe)\b"), "setHTMLUnsafe/parseHTMLUnsafe"),
    (re.compile(r"\bcreateContextualFragment\b"), "createContextualFragment"),
    (re.compile(r"\.srcdoc\b|setAttribute\s*\(\s*['\"`]srcdoc"), "srcdoc"),
    (re.compile(r"\bset(Timeout|Interval)\s*\(\s*['\"`]"), "setTimeout/setInterval with a string"),
    (re.compile(r"\.setAttribute\s*\(\s*['\"`]style['\"`]"), "setAttribute('style')"),
]
REMOTE_JS = re.compile(r"""(\bfetch|\bimport|\bimportScripts|\bnew\s+(Worker|SharedWorker|EventSource|WebSocket))\s*\(\s*['"`](https?:)?//"""
                       r"""|\bfrom\s*['"`](https?:)?//|\bimport\s*['"`](https?:)?//""")
REMOTE_CSS = re.compile(r"""(url\(\s*['"]?|@import\s+['"])(https?:)?//""", re.I)
PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
HTTP_URL = re.compile(r"http://[^\s'\"`)<>]+")
HTTPS_URL = re.compile(r"https://[A-Za-z0-9.-]+")
TAG = re.compile(r"<(script|link|img|iframe|audio|video|source|track|embed|object|input|a)\b([^>]*)>", re.I)
ATTR = re.compile(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")
STYLE_ATTR = re.compile(r"<[a-zA-Z][^>]*\sstyle\s*=", re.S)
HANDLER_ATTR = re.compile(r"<[a-zA-Z][^>]*\son[a-z]+\s*=", re.S)
INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.I | re.S)
COMMENT_TODO = re.compile(r"(#|//|/\*|<!--)\s*(TO" + r"DO|FIX" + r"ME|XXX)\b")
ATTRIBUTION = re.compile(r"^\s*Co-Authored-By:|Generated with \[?Claude", re.I | re.M)
# The deployment's own addresses (deploy/README.md): the only public ones a file may name.
OWN_ADDRESSES = {"179.236.70.195", "2a02:4780:95:64c5::1"}
IPV4_LITERAL = re.compile(r"(?<![\w.§])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6_LITERAL = re.compile(r"(?<![\w:.])(?=[0-9a-fA-F:]*::|(?:[0-9a-fA-F]{1,4}:){7})[0-9a-fA-F:]{3,39}(?![\w:.])")


def attrs(tag_body: str) -> dict:
    return {m.group(1).lower(): next(g for g in m.groups()[2:] if g is not None) for m in ATTR.finditer(tag_body)}


def repo_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                             capture_output=True, check=True).stdout.decode()
        names = [n for n in out.split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        names = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            names += [os.path.relpath(os.path.join(dirpath, f), root) for f in files]
    keep = []
    for n in sorted(set(names)):
        parts = n.split("/")
        if any(p in SKIP_DIRS for p in parts) or VENDORED.search(n) or any(d in "/" + n for d in DATA_PARTS):
            continue
        if (root / n).is_file():
            keep.append(n)
    return keep


def is_python(path: Path, name: str) -> bool:
    if name.endswith(".py"):
        return True
    if Path(name).suffix:
        return False
    try:
        with open(path, "rb") as f:
            first = f.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def local_modules(names: list[str]) -> set[str]:
    mods = set()
    for n in names:
        p = Path(n)
        if p.suffix == ".py":
            mods.add(p.stem if p.name != "__init__.py" else p.parent.name)
    return mods


def python_problems(name: str, text: str, local: set[str]) -> list[str]:
    try:
        tree = ast.parse(text, filename=name)
    except SyntaxError as e:
        return [f"{name}:{e.lineno}: syntax error"]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            tops = [node.module.split(".")[0]]
        else:
            continue
        for top in tops:
            if top not in sys.stdlib_module_names and top not in local and top != "__future__":
                found.append(f"{name}:{node.lineno}: import of non-standard module {top!r}")
    return found


def is_served(name: str) -> bool:
    return name.startswith(SERVED_ROOTS) and not name.startswith(NOT_SERVED)


def js_problems(name: str, text: str) -> list[str]:
    found = [f"{name}: forbidden {label}" for rx, label in FORBIDDEN_JS if rx.search(text)]
    if is_served(name):
        found += url_problems(name, text)
        found += [f"{name}: remote module, worker or fetch target" for _ in REMOTE_JS.finditer(text)]
        found += [f"{name}: build placeholder {m} in a file the build does not fill"
                  for m in PLACEHOLDER.findall(text)]
        found += [f"{name}: absolute URL {m}" for m in HTTPS_URL.findall(text) if m not in INDEXERS]
    return found


def url_problems(name: str, text: str) -> list[str]:
    return [f"{name}: http:// URL {m}" for m in HTTP_URL.findall(text) if m not in XML_NAMESPACES]


def css_problems(name: str, text: str) -> list[str]:
    if not is_served(name):
        return []
    found = url_problems(name, text)
    found += [f"{name}: remote resource in CSS" for _ in REMOTE_CSS.finditer(text)]
    found += [f"{name}: build placeholder {m} in a file the build does not fill" for m in PLACEHOLDER.findall(text)]
    return found


def html_problems(name: str, text: str) -> list[str]:
    served = is_served(name) or name.startswith("web/shared/partials/")
    if not served:
        return []
    found = url_problems(name, text)
    if STYLE_ATTR.search(text):
        found.append(f"{name}: style attribute")
    if HANDLER_ATTR.search(text):
        found.append(f"{name}: inline event handler attribute")
    for m in INLINE_SCRIPT.finditer(text):
        a = attrs(m.group(1))
        if "src" not in a and a.get("type", "").lower() != "application/ld+json" and m.group(2).strip():
            found.append(f"{name}: inline script")
    for m in TAG.finditer(text):
        tag, a = m.group(1).lower(), attrs(m.group(2))
        if tag == "a":
            continue
        rel = a.get("rel", "").lower().split()
        if tag == "link" and set(rel) & {"canonical", "alternate"}:
            continue
        for key in ("src", "href", "srcset", "data"):
            value = a.get(key, "")
            if re.match(r"(https?:)?//", value.strip(), re.I):
                found.append(f"{name}: remote {key} on <{tag}>: {value}")
        local = lambda v: v.startswith("/") and not v.startswith("//")  # noqa: E731
        needs_sri = (tag == "script" and local(a.get("src", ""))) or \
                    (tag == "link" and "stylesheet" in rel and local(a.get("href", "")))
        if needs_sri and "integrity" not in a:
            found.append(f"{name}: <{tag}> without integrity=\"{{{{SRI}}}}\"")
    return found


def address_problems(name: str, text: str) -> list[str]:
    """Public IP literals other than the server's own. A literal that isn't an address (a version, a
    time) never parses; x.0.0.0 is a network, not a host."""
    found = []
    for m in IPV4_LITERAL.finditer(text):
        try:
            ip = ipaddress.IPv4Address(m.group(0))
        except ValueError:
            continue
        if ip.is_global and not str(ip).endswith(".0.0.0") and str(ip) not in OWN_ADDRESSES:
            found.append(f"{name}: public address {ip}")
    for m in IPV6_LITERAL.finditer(text):
        try:
            ip = ipaddress.IPv6Address(m.group(0))
        except ValueError:
            continue
        if ip.is_global and str(ip) not in OWN_ADDRESSES:
            found.append(f"{name}: public address {ip}")
    return found


def header_problems(name: str, text: str) -> list[str]:
    head = text.splitlines()[:3]
    if not any("SPDX-License-Identifier: MIT" in line for line in head):
        return [f"{name}: no SPDX-License-Identifier: MIT in the first lines"]
    return []


def lint(root: Path, only: str | tuple[str, ...] = "") -> list[str]:
    names = [n for n in repo_files(root) if n.startswith(only)]
    local = local_modules(repo_files(root))
    problems = []
    for name in names:
        path = root / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        ext = path.suffix
        python = is_python(path, name)
        if python:
            problems += python_problems(name, text, local)
        if name.startswith("web/") and ext in (".js", ".mjs"):
            problems += js_problems(name, text)
        elif ext == ".css":
            problems += css_problems(name, text)
        elif ext == ".html":
            problems += html_problems(name, text)
        elif name.startswith(("web/site/static/",)) and is_served(name):
            problems += url_problems(name, text)
        if ext in CODE_EXT or python:
            problems += header_problems(name, text)
            problems += [f"{name}: {m.group(2)} comment" for m in COMMENT_TODO.finditer(text)]
        if ATTRIBUTION.search(text):
            problems.append(f"{name}: attribution line")
        problems += address_problems(name, text)
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description="mutis repository lint")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--only", default="", help="lint only paths starting with this prefix (e.g. web/)")
    args = p.parse_args()
    problems = lint(args.root.resolve(), args.only)
    for line in problems:
        print("LINT", line)
    print(f"lint: {'FAIL' if problems else 'PASS'} ({len(problems)} problems)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
