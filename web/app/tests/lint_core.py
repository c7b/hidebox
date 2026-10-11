#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Lint for the app-core directories (lib, sidecar, vendor shim, tests). Python stdlib only.

  python3 -I web/app/tests/lint_core.py

Spec §0.7 and §3.3 step 8 rules, plus the library-side checks of A-06: the modules an anonymous drop
or open needs never import the Ootle WebAssembly, browser storage is touched only in store.js, and the
library never logs.
"""
import gzip
import os
import re
import sys

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
problems = []
checks = 0


def rel(p):
    return os.path.relpath(p, APP)


def files(*dirs, exts):
    for d in dirs:
        for root, _, names in os.walk(os.path.join(APP, d)):
            if "ootle-wasm-0.45.0" in root:  # official vendored files: hash-pinned, never edited
                continue
            for n in sorted(names):
                if n.endswith(exts):
                    yield os.path.join(root, n)


def flag(path, msg):
    problems.append(f"{rel(path)}: {msg}")


SOURCES = list(files("lib", "sidecar", "vendor", "tests", exts=(".js", ".mjs", ".py", ".html", ".css")))
JS = [p for p in SOURCES if p.endswith((".js", ".mjs"))]

# 1. License header on the first line (after a shebang or doctype).
for p in SOURCES:
    checks += 1
    lines = open(p, encoding="utf-8").read().splitlines()
    head = lines[1] if lines and (lines[0].startswith("#!") or lines[0].lower().startswith("<!doctype")) else lines[0]
    if "SPDX-License-Identifier: MIT" not in head:
        flag(p, "first line lacks SPDX-License-Identifier: MIT")

# 2. Forbidden sinks and string-to-code (§0.7 rule 3), case-sensitive like the build lint.
FORBIDDEN = [r"\binnerHTML\b", r"\bouterHTML\b", r"\binsertAdjacentHTML\b", r"document\.write\b", r"\beval\s*\(",
             r"\bnew\s+Function\b", r"setTimeout\s*\(\s*['\"`]", r"setInterval\s*\(\s*['\"`]"]
for p in JS:
    src = open(p, encoding="utf-8").read()
    for rx in FORBIDDEN:
        checks += 1
        if re.search(rx, src):
            flag(p, f"forbidden token {rx}")

# 3. URLs: no http:// except the SVG namespace identifier; absolute https:// in the library only for
#    the two public indexers behind the explicit "Check directly" button (ootle.js).
for p in JS:
    src = open(p, encoding="utf-8").read()
    checks += 1
    for m in re.findall(r"http://[^\s'\"`)]+", src):
        if m != "http://www.w3.org/2000/svg":
            flag(p, f"http URL {m}")
    if rel(p).startswith(("lib", "sidecar", "vendor")):
        for m in re.findall(r"https://[^\s'\"`)]+", src):
            if not (rel(p) == os.path.join("lib", "ootle.js") and m in ("https://ootle-indexer-a.tari.com", "https://ootle-indexer-b.tari.com")):
                flag(p, f"absolute URL {m}")

# 4. No leftovers, no attribution lines, no inline styles in HTML (this file names the patterns).
for p in (p for p in SOURCES if p != os.path.abspath(__file__)):
    src = open(p, encoding="utf-8").read()
    checks += 1
    if re.search(r"\b(TODO|FIXME|XXX)\b", src):
        flag(p, "TODO/FIXME left in")
    if "Co-Authored-By" in src or "Generated with" in src:
        flag(p, "attribution line")
    if p.endswith(".html") and 'style="' in src:
        flag(p, "inline style attribute")

# 5. Python: standard library only.
for p in (p for p in SOURCES if p.endswith(".py")):
    for m in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w., ]+))", open(p, encoding="utf-8").read(), re.M):
        for name in (m.group(1) or m.group(2)).split(","):
            checks += 1
            top = name.strip().split()[0].split(".")[0]
            if top not in sys.stdlib_module_names:
                flag(p, f"non-stdlib import {top}")

# 6. Library hygiene: storage only in store.js, no console output, no third-party imports (static or
#    dynamic).
for p in files("lib", exts=(".js",)):
    src = open(p, encoding="utf-8").read()
    checks += 1
    if os.path.basename(p) != "store.js" and re.search(r"\b(localStorage|sessionStorage|indexedDB)\b", src):
        flag(p, "browser storage outside store.js")
    if re.search(r"\bconsole\.", src):
        flag(p, "console output in the library")
    for spec in re.findall(r"^import .* from '([^']+)';", src, re.M) + re.findall(r"\bimport\(\s*'([^']+)'\s*\)", src):
        if not spec.startswith(("./", "../vendor/")):
            flag(p, f"import outside the library: {spec}")


# 7. A-06 (library side): what the widget loads before anyone picks a locker action. Static imports
#    only: exif.js, password.js and the locker modules load with import() when they are needed, and
#    the Ootle WebAssembly never loads on this path.
def closure(start):
    seen, todo = set(), [start]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        src = open(p, encoding="utf-8").read()
        for spec in re.findall(r"^import .* from '([^']+)';", src, re.M):
            todo.append(os.path.normpath(os.path.join(os.path.dirname(p), spec)))
    return seen


def gz(paths):
    return sum(len(gzip.compress(open(p, "rb").read(), 9)) for p in paths)


WIDGET = ["seal.js", "open.js", "filetype.js", "pow.js", "pow-worker.js", "preview.js", "download.js", "router.js", "i18n.js", "store.js"]
LAZY = ["exif.js", "password.js"]
LOCKER_ONLY = ["api-locker.js", "identity.js", "session.js", "scan.js", "wallet.js", "drop.js", "courier.js"]
BUDGET = 40 * 1024
anon = set().union(*(closure(os.path.join(APP, "lib", m)) for m in WIDGET))
checks += 1
wasmy = [rel(p) for p in anon if "ootle" in os.path.basename(p) or "vendor" in p]
if wasmy:
    problems.append(f"anonymous path imports {wasmy}")
checks += 1
eager = [m for m in LAZY + LOCKER_ONLY if os.path.join(APP, "lib", m) in anon]
if eager:
    problems.append(f"anonymous path imports, statically, modules meant to load on demand: {eager}")
size = gz(anon)
lazy = {m: gz([os.path.join(APP, "lib", m)]) for m in LAZY}

for line in problems:
    print("LINT", line)
print(f"widget path, library modules: {len(anon)} files, {size:,} bytes gzip-9 (no ootle-wasm in the graph); "
      f"{BUDGET - size:,} bytes of the {BUDGET // 1024} KB A-06 budget left for drop-widget.js, its CSS and strings")
print("on demand: " + ", ".join(f"{m} {n:,} B" for m, n in lazy.items()))
print(f"{'LINT PASS' if not problems else 'LINT FAIL'} {checks - len(problems)}/{checks} checks, {len(SOURCES)} files")
sys.exit(1 if problems else 0)
