# SPDX-License-Identifier: MIT
"""Content-hashed names for the files a build serves (tools/build.py's fingerprint step). Python standard library only.

Every file that a page or the web manifest asks for by a local URL, directly or through the stylesheets, scripts and
SVGs it loads (stylesheets, scripts, images, fonts, sprites, JSON, wasm), gets a copy named
NAME.<10 hex digits of a SHA-256>.EXT beside it, and every reference to it in dist/ is rewritten to that name: a
relative reference stays relative, a query or #fragment stays.
A file's hash covers its bytes after its own references are rewritten, so a change in a file reaches every name that
leads to it. Files that ask for each other (a cycle, or a sprite that names itself) share one hash of their joint
content. Caddy keeps the hashed names a year, immutable (deploy/caddy/Caddyfile, @hashed): a name can only ever hold
the same bytes.

The plain names stay in dist/ with the same rewritten bytes and their shorter caching: an address built at run time,
cached elsewhere or typed by hand still works, and a module loaded under its plain name imports the hashed ones, so
the page keeps one module graph. The entry points keep their names and are never rewritten to another: the pages,
ENTRY_POINTS below and .well-known/. Absolute URLs (https://…, the og:image and JSON-LD addresses) are names other
products keep, and are left alone. In pages only root-relative references count (a page is served at more than one
address); in stylesheets, scripts and SVGs relative ones resolve against the file's own address. Same input, same
names.
"""
import hashlib
import posixpath
import re
from pathlib import Path

HASH_LEN = 10
# NAME.<hash>.EXT: what Caddy's @hashed route matches (the same pattern), and what no source file may be called.
HASHED_NAME = re.compile(r"\.[0-9a-f]{%d}\.[a-z0-9]+$" % HASH_LEN)
ASSET_EXT = {".css", ".js", ".mjs", ".svg", ".png", ".ico", ".webp", ".avif", ".jpg", ".jpeg", ".gif", ".woff2",
             ".wasm", ".json", ".txt", ".webm", ".mp4"}
REWRITTEN_EXT = {".html", ".css", ".js", ".mjs", ".svg", ".webmanifest"}
# Names other products and browsers ask for by themselves, or that pages announce: they never change.
ENTRY_POINTS = {"favicon.ico", "favicon.svg", "apple-touch-icon.png", "og.png", "og-s.png", "manifest.webmanifest",
                "robots.txt", "sitemap.xml", "llms.txt", "llms-full.txt"}

JS_STRING = re.compile(r"""(['"`])((?:\.\.?/|/(?!/))[^'"`\s\\${}<>]*)\1""")
CSS_URL = re.compile(r"""(url\(\s*)(['"]?)([^'")\s]+)\2(\s*\))""")
CSS_IMPORT = re.compile(r"""(@import\s+)(['"])([^'"]+)\2""")
MARKUP_ATTR = re.compile(r"""(\s[A-Za-z_:][-A-Za-z0-9_:.]*)(\s*=\s*)(?:"([^"]*)"|'([^']*)')""")
JSON_STRING = re.compile(r'"((?:\.\.?/|/(?!/))[^"\s\\]*)"')
SRCSET_ATTRS = {"srcset", "imagesrcset"}
CANDIDATE = re.compile(r"^(\s*)(\S+)")


def is_asset(rel: str) -> bool:
    name = rel.rpartition("/")[2]
    return (Path(name).suffix.lower() in ASSET_EXT and name not in ENTRY_POINTS and not rel.startswith(".well-known/")
            and not HASHED_NAME.search(name))


def hashed_name(rel: str, digest: str) -> str:
    head, _, name = rel.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    return f"{head}/{stem}.{digest[:HASH_LEN]}.{ext}" if head else f"{stem}.{digest[:HASH_LEN]}.{ext}"


class Refs:
    """Finds and rewrites the local references of one file. `targets` is the set of dist paths that may be referred to;
    `names` maps a dist path to its hashed path when rewriting."""

    def __init__(self, rel: str, targets: set[str]):
        self.rel, self.targets = rel, targets
        self.suffix = Path(rel).suffix.lower()
        # A page is served at more than one address (/how and /how/, the 404 at any path): root-relative only.
        self.base = None if self.suffix == ".html" else "/" + posixpath.dirname(rel)

    def resolve(self, ref: str) -> tuple[str, str, str] | None:
        """(dist path, the reference before its file name, its query or fragment), or None for anything else."""
        cut = min([i for i in (ref.find("?"), ref.find("#")) if i >= 0], default=len(ref))
        path, rest = ref[:cut], ref[cut:]
        if path.startswith("/") and not path.startswith("//"):
            url = posixpath.normpath(path)
        elif path.startswith(("./", "../")) and self.base is not None:
            url = posixpath.normpath(posixpath.join(self.base, path))
        else:
            return None
        target = url.lstrip("/")
        if target not in self.targets:
            return None
        return target, path[:path.rfind("/") + 1], rest

    def _one(self, ref: str, names: dict | None, found: set) -> str:
        hit = self.resolve(ref)
        if not hit:
            return ref
        target, head, rest = hit
        found.add(target)
        if names is None or target not in names:
            return ref
        return head + names[target].rpartition("/")[2] + rest

    def _attr(self, name: str, value: str, names, found) -> str:
        if name.lower() in SRCSET_ATTRS:   # "url 480w, url 720w": each candidate's URL
            return ",".join(CANDIDATE.sub(lambda m: m.group(1) + self._one(m.group(2), names, found), c)
                            for c in value.split(","))
        return self._one(value, names, found)

    def apply(self, text: str, names: dict | None = None) -> tuple[str, set[str]]:
        """The text with every reference in `names` rewritten, and the set of every dist path it refers to."""
        found: set[str] = set()
        if self.suffix in (".js", ".mjs"):
            text = JS_STRING.sub(lambda m: m.group(1) + self._one(m.group(2), names, found) + m.group(1), text)
        elif self.suffix == ".css":
            text = CSS_URL.sub(lambda m: m.group(1) + m.group(2) + self._one(m.group(3), names, found) + m.group(2) + m.group(4), text)
            text = CSS_IMPORT.sub(lambda m: m.group(1) + m.group(2) + self._one(m.group(3), names, found) + m.group(2), text)
        elif self.suffix == ".webmanifest":
            text = JSON_STRING.sub(lambda m: '"' + self._one(m.group(1), names, found) + '"', text)
        elif self.suffix in (".html", ".svg"):
            def attr(m: re.Match) -> str:
                quote, value = ('"', m.group(3)) if m.group(3) is not None else ("'", m.group(4))
                return m.group(1) + m.group(2) + quote + self._attr(m.group(1).strip(), value, names, found) + quote
            text = MARKUP_ATTR.sub(attr, text)
            text = CSS_URL.sub(lambda m: m.group(1) + m.group(2) + self._one(m.group(3), names, found) + m.group(2) + m.group(4), text)
        return text, found


def components(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected components (Tarjan, without recursion), each one after every component it leads to."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on.add(root)
        work = [(root, iter(sorted(edges.get(root, ()))))]
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(edges.get(w, ())))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    out.append(sorted(comp))
    return out


def fingerprint(dist: Path) -> dict[str, str]:
    """Hash, copy and rewrite in place; returns {plain dist path: hashed dist path}. Raises ValueError for a source
    file whose name already looks hashed (Caddy would keep it a year whatever it holds)."""
    files = sorted(p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file())
    clash = [f for f in files if HASHED_NAME.search(f.rpartition("/")[2])]
    if clash:
        raise ValueError(f"a served file is named like a fingerprinted one: {clash[:3]}")
    assets = {f for f in files if is_asset(f)}
    texts = {}
    for f in files:
        if Path(f).suffix.lower() in REWRITTEN_EXT:
            try:
                texts[f] = (dist / f).read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise ValueError(f"{f}: not UTF-8 text ({e.reason})") from e
    refs = {f: Refs(f, assets) for f in texts}
    edges = {f: refs[f].apply(texts[f])[1] for f in texts}
    # What the pages and the web manifest reach, through every stylesheet, script and SVG on the way: a file only an
    # unreached script names (a test module, the old /vendor/ copy of the shim) keeps its plain name only.
    hashed: set[str] = set()
    todo = [f for f in texts if f not in assets]
    while todo:
        for target in edges.get(todo.pop(), ()):
            if target not in hashed:
                hashed.add(target)
                todo.append(target)
    names: dict[str, str] = {}
    final: dict[str, bytes] = {}
    for comp in components(sorted(hashed), {f: edges.get(f, set()) & hashed for f in hashed}):
        cyclic = len(comp) > 1 or comp[0] in edges.get(comp[0], ())
        if cyclic:
            joint = hashlib.sha256()
            for f in comp:
                joint.update(f.encode() + b"\0" + refs[f].apply(texts[f], names)[0].encode() + b"\0")
            for f in comp:
                names[f] = hashed_name(f, hashlib.sha256(joint.digest() + f.encode()).hexdigest())
            for f in comp:
                final[f] = refs[f].apply(texts[f], names)[0].encode()
        else:
            f = comp[0]
            final[f] = refs[f].apply(texts[f], names)[0].encode() if f in texts else (dist / f).read_bytes()
            names[f] = hashed_name(f, hashlib.sha256(final[f]).hexdigest())
    for f in texts:
        if f not in final:
            final[f] = refs[f].apply(texts[f], names)[0].encode()
    for f, data in final.items():
        if f in texts:
            (dist / f).write_bytes(data)
        if f in names:
            (dist / names[f]).write_bytes(data)
    return dict(sorted(names.items()))
