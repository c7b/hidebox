#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the served site and app (dist/) and the sidecar release (release/sidecar/) from web/ (spec §3.3).

  python3 -I tools/build.py [--config mutis.toml] [--origin https://…] [--with-tests]

Python standard library only. Deterministic: the same commit and config give byte-identical files
(the manifest's built_at is the one timestamp), which is what tools/verify-deploy.py relies on.
Steps: copy; includes; placeholders; SRI; vendored artifact hashes; lint; sitemap; hash manifest.
Any error stops the build with exit status 1.
"""
import argparse
import base64
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "deploy" / "config" / "mutis.toml.example"
HOLDING = ROOT / "deploy" / "holding"

# spec §3.3 step 7 (verified in 03 §6.1): the two files of the official ootle-wasm 0.45.0 build.
PINNED = {
    "ootle-wasm-0.45.0/ootle_wasm_bg.wasm": "57de0088e9b96ecdd47daad41f1c48fcfbf1773358244a4663c1f40766d6d4df",
    "ootle-wasm-0.45.0/ootle_wasm_bg.js": "2a338a3c8ef81b314c41487c9e2dc3d1f77942ea9f47c672fd971ab40d3ac36b",
}
# Only these are ever copied into dist/ (an allow-list: notes, reviews, sources and tests never leak).
SERVED_EXT = {".html", ".js", ".mjs", ".css", ".wasm", ".svg", ".png", ".webp", ".jpg", ".woff2",
              ".webmanifest", ".txt", ".xml", ".json"}
SERVED_NAMES = re.compile(r"(LICENSE|NOTICE|SHA256SUMS|PROVENANCE\.md|[^/]+\.d\.ts)")
NEVER_SERVED = re.compile(r"(^|/)package\.json$")
INCLUDE = re.compile(r"<!--#include ([a-z0-9-]+)-->")
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
SRI_TAG = re.compile(r"<(script|link)\b[^>]*integrity=\"\{\{SRI\}\}\"[^>]*>", re.I)
FILLED_EXT = {".html", ".txt", ".webmanifest", ".xml"}
SPDX_PARTIAL = re.compile(r"\A<!-- SPDX-License-Identifier: MIT -->\n")
NOINDEX = re.compile(r"<meta\s+name=\"robots\"\s+content=\"[^\"]*noindex", re.I)


class BuildError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def source_state(given: list[str] | None = None) -> dict:
    """The commit being built. A tree with uncommitted changes builds as `<sha>-dirty`.
    `given` = [sha, version, unix time] when building an exported tree (git archive) with no .git."""
    if given:
        sha, version, commit_time = given
        return {"sha": sha, "version": version,
                "date": datetime.datetime.fromtimestamp(int(commit_time), datetime.UTC).strftime("%Y-%m-%d")}
    sha = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=normal", "--", "web", "tools"))
    commit_time = int(git("log", "-1", "--format=%ct"))
    version = git("describe", "--tags", "--always") + ("-dirty" if dirty else "")
    return {"sha": sha + ("-dirty" if dirty else ""), "version": version,
            "date": datetime.datetime.fromtimestamp(commit_time, datetime.UTC).strftime("%Y-%m-%d")}


def settings(config_path: Path, origin: str | None) -> dict:
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)
    origin = (origin or cfg["public_origin"]).rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9.-]+(:\d+)?|http://127\.0\.0\.1:\d+", origin):
        raise BuildError(f"origin must be https://host (or http://127.0.0.1:port for development): {origin}")
    network = cfg.get("network", "esmeralda")
    return {
        "ORIGIN": origin,
        "NETWORK": network.capitalize(),
        "SECURITY_DROP_URL": cfg.get("security_drop_url") or origin + "/abuse",
        "REPO_URL": cfg.get("repo_url", "https://github.com/c7b/mutis").rstrip("/"),
    }


def served(rel: str) -> bool:
    name = rel.rpartition("/")[2]
    return (Path(name).suffix in SERVED_EXT or bool(SERVED_NAMES.fullmatch(name))) and not NEVER_SERVED.search(rel)


def copy_tree(src: Path, dst: Path, skip=()) -> None:
    if not src.is_dir():
        return
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src).as_posix()
        if path.is_dir() or not served(rel) or any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out)


def page_target(rel: str) -> str:
    """pages/<name>.html → <name>/index.html; index → index.html; 404 → 404.html (also in es/)."""
    stem, _, name = rel.removesuffix(".html").rpartition("/")
    prefix = stem + "/" if stem else ""
    if name in ("index", "404"):
        return f"{prefix}{name}.html"
    return f"{prefix}{name}/index.html"


def copy_site(web: Path, dist: Path, with_tests: bool) -> list[str]:
    copy_tree(web / "shared", dist / "shared", skip=("partials",))
    copy_tree(web / "app", dist / "app", skip=("sidecar",) if with_tests else ("sidecar", "tests"))
    copy_tree(web / "app" / "vendor", dist / "vendor")
    copy_tree(web / "site" / "static", dist)
    copy_tree(web / "site" / "js", dist / "site" / "js")
    copy_tree(web / "site" / "css", dist / "site" / "css")
    pages = []
    for page in sorted((web / "site" / "pages").rglob("*.html")):
        target = page_target(page.relative_to(web / "site" / "pages").as_posix())
        (dist / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(page, dist / target)
        pages.append(target)
    return pages


def copy_holding(web: Path, dist: Path) -> list[str]:
    """The holding page (deploy/holding/) on the shared tokens, served until the full site builds."""
    copy_tree(web / "shared", dist / "shared", skip=("partials",))
    for target in ("index.html", "404.html"):
        shutil.copyfile(HOLDING / "index.html", dist / target)
    shutil.copyfile(HOLDING / "holding.css", dist / "holding.css")
    shutil.copyfile(web / "shared" / "brand" / "favicon.svg", dist / "favicon.svg")
    return ["index.html", "404.html"]


def copy_sidecar(web: Path, release: Path) -> None:
    """release/sidecar/ in the layout of web/app/sidecar/README.md (never served)."""
    sidecar = release / "sidecar"
    copy_tree(web / "app" / "sidecar", sidecar)
    copy_tree(web / "app" / "lib", sidecar / "lib")
    for rel in ("lib/package.json", "vendor/package.json", "vendor/ootle-wasm-shim.js"):
        if (web / "app" / rel).is_file():
            (sidecar / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(web / "app" / rel, sidecar / rel)
    for vendored in sorted((web / "app" / "vendor").glob("ootle-wasm-*")):
        copy_tree(vendored, sidecar / "vendor" / vendored.name)


def expand_includes(text: str, partials: Path, where: str, depth: int = 0) -> str:
    def one(m: re.Match) -> str:
        path = partials / f"{m.group(1)}.html"
        if not path.is_file():
            raise BuildError(f"{where}: unknown include {m.group(1)!r}")
        if depth >= 3:
            raise BuildError(f"{where}: includes nested too deeply")
        body = SPDX_PARTIAL.sub("", path.read_text(encoding="utf-8")).rstrip("\n")
        return expand_includes(body, partials, where, depth + 1)
    return INCLUDE.sub(one, text)


def fill(text: str, values: dict, where: str) -> str:
    def one(m: re.Match) -> str:
        if m.group(1) == "SRI":
            return m.group(0)
        if m.group(1) not in values:
            raise BuildError(f"{where}: unknown placeholder {m.group(0)}")
        return values[m.group(1)]
    return PLACEHOLDER.sub(one, text)


def add_sri(text: str, dist: Path, where: str) -> str:
    def one(m: re.Match) -> str:
        a = lint.attrs(m.group(0)[1:-1])
        url = a.get("src") if m.group(1).lower() == "script" else a.get("href")
        if not url or not url.startswith("/") or url.startswith("//"):
            raise BuildError(f"{where}: integrity=\"{{{{SRI}}}}\" needs a local src/href, got {url!r}")
        target = dist / url.split("?")[0].split("#")[0].lstrip("/")
        if not target.is_file():
            raise BuildError(f"{where}: {url} is not in dist/")
        digest = base64.b64encode(hashlib.sha384(target.read_bytes()).digest()).decode()
        return m.group(0).replace("{{SRI}}", "sha384-" + digest)
    text = SRI_TAG.sub(one, text)
    if "{{SRI}}" in text:
        raise BuildError(f"{where}: {{{{SRI}}}} outside an integrity attribute of a script or stylesheet tag")
    return text


def process_files(dist: Path, partials: Path, values: dict) -> None:
    files = sorted(p for p in dist.rglob("*") if p.is_file() and p.suffix in FILLED_EXT)
    for path in files:
        where = path.relative_to(dist).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            text = expand_includes(text, partials, where)
        text = fill(text, values, where)
        path.write_text(text, encoding="utf-8", newline="\n")
    for path in files:
        if path.suffix == ".html":
            where = path.relative_to(dist).as_posix()
            path.write_text(add_sri(path.read_text(encoding="utf-8"), dist, where), encoding="utf-8", newline="\n")


def verify_vendored(web: Path) -> list[str]:
    vendor = web / "app" / "vendor"
    checked = []
    for rel, expected in PINNED.items():
        path = vendor / rel
        if not path.is_file():
            raise BuildError(f"vendored artifact missing: {path.relative_to(web.parent)}")
        if sha256(path) != expected:
            raise BuildError(f"vendored artifact hash mismatch: {path.relative_to(web.parent)}")
        checked.append(rel)
    for sums in sorted(vendor.glob("*/SHA256SUMS")):
        for line in sums.read_text().splitlines():
            if not line.strip():
                continue
            digest, name = line.split(maxsplit=1)
            path = sums.parent / name.strip().lstrip("*")
            if not path.is_file() or sha256(path) != digest:
                raise BuildError(f"{path.relative_to(web.parent)} does not match {sums.relative_to(web.parent)}")
            checked.append(f"{sums.parent.name}/{name.strip()}")
    return checked


def sitemap(dist: Path, pages: list[str], origin: str) -> None:
    urls = []
    for target in pages:
        if target.endswith("404.html") or NOINDEX.search((dist / target).read_text(encoding="utf-8")):
            continue
        path = "/" + target.removesuffix("index.html").removesuffix("/")
        urls.append(origin + (path if path != "/" else "/"))
    body = "".join(f"  <url><loc>{u}</loc></url>\n" for u in sorted(urls))
    (dist / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      f"{body}</urlset>\n", encoding="utf-8", newline="\n")


def manifest(dist: Path, state: dict) -> dict:
    files = {p.relative_to(dist).as_posix(): sha256(p) for p in sorted(dist.rglob("*")) if p.is_file()}
    doc = {"version": state["version"], "git_sha": state["sha"],
           "built_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": files}
    out = dist / ".well-known" / "mutis-manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return doc


def content_id(files: dict) -> str:
    """Eight hex digits naming what a build serves; the release id is <commit>-c<content id>, so one commit
    built with another origin or drop URL is another release (deploy.sh, activate-release.sh)."""
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:8]


def build(web: Path, dist: Path, release: Path, values: dict, state: dict, with_tests: bool = False,
          holding: bool = False) -> dict:
    for out in (dist, release / "sidecar"):
        if out.exists():
            shutil.rmtree(out)
    dist.mkdir(parents=True)
    problems = lint.lint(web.parent, ("web/", "deploy/holding/"))
    if problems:
        raise BuildError("lint:\n  " + "\n  ".join(problems))
    vendored = verify_vendored(web)
    pages = copy_holding(web, dist) if holding else copy_site(web, dist, with_tests)
    copy_sidecar(web, release)
    process_files(dist, web / "shared" / "partials", values | {
        "GIT_SHA": state["sha"], "VERSION": state["version"], "BUILD_DATE": state["date"]})
    sitemap(dist, pages, values["ORIGIN"])
    doc = manifest(dist, state)
    return {"pages": len(pages), "files": len(doc["files"]), "content_id": content_id(doc["files"]),
            "vendored_checked": len(vendored), "holding": holding,
            "version": state["version"], "git_sha": state["sha"], "origin": values["ORIGIN"]}


def main() -> int:
    p = argparse.ArgumentParser(description="build dist/ and release/sidecar/ from web/")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="mutis.toml for origin, network, URLs")
    p.add_argument("--origin", help="override public_origin from the config")
    p.add_argument("--web", type=Path, default=ROOT / "web")
    p.add_argument("--out", type=Path, default=ROOT / "dist")
    p.add_argument("--release", type=Path, default=ROOT / "release")
    p.add_argument("--with-tests", action="store_true", help="also serve web/app/tests (staging only)")
    p.add_argument("--holding", action="store_true", help="serve deploy/holding/ instead of the site")
    p.add_argument("--source", nargs=3, metavar=("SHA", "VERSION", "UNIX_TIME"),
                   help="the commit an exported tree (git archive, no .git) was made from")
    args = p.parse_args()
    try:
        summary = build(args.web.resolve(), args.out.resolve(), args.release.resolve(),
                        settings(args.config, args.origin), source_state(args.source), args.with_tests, args.holding)
    except (BuildError, OSError, KeyError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as e:
        print(f"build: FAIL: {e}", file=sys.stderr)
        return 1
    print("build: OK " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
