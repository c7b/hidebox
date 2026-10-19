#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the served site and app (dist/) and the sidecar release (release/sidecar/) from web/ (spec §3.3).

  python3 -I tools/build.py [--config mutis.toml] [--origin https://…] [--with-tests]

Python standard library only. Deterministic: the same commit and config give byte-identical files
(the manifest's built_at is the one timestamp), which is what tools/verify-deploy.py relies on.
Steps: copy; the deployment's copy variants; includes; placeholders; SRI; vendored artifact hashes;
lint; sitemap; hash manifest. Any error stops the build with exit status 1.
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
# The public name (14-ghost-design §2). The owner can swap it here, in one word; the internal codename
# mutis stays in code, paths, services, the CLI and the database. Pages read it as {{BRAND}}; the app's
# strings read it as {brand} from web/app/lib/i18n.js, which must say the same (the build checks).
BRAND = "hidebox"
DEFAULT_CONFIG = ROOT / "deploy" / "config" / "mutis.toml.example"
HOLDING = ROOT / "deploy" / "holding"

# spec §3.3 step 7 (verified in 03 §6.1): the two files of the official ootle-wasm 0.46.0 build.
PINNED = {
    "ootle-wasm-0.46.0/ootle_wasm_bg.wasm": "2856d86b688959fc6620ac8cf2cb4629ee554c94bd81a6baaa2a71a7e7a393f2",
    "ootle-wasm-0.46.0/ootle_wasm_bg.js": "2a338a3c8ef81b314c41487c9e2dc3d1f77942ea9f47c672fd971ab40d3ac36b",
}
# Only these are ever copied into dist/ (an allow-list: notes, reviews, sources and tests never leak).
SERVED_EXT = {".html", ".js", ".mjs", ".css", ".wasm", ".svg", ".png", ".ico", ".webp", ".avif", ".jpg", ".woff2",
              ".webmanifest", ".txt", ".xml", ".json", ".webm", ".mp4"}
SERVED_NAMES = re.compile(r"(LICENSE|NOTICE|SHA256SUMS|PROVENANCE\.md|[^/]+\.d\.ts)")
NEVER_SERVED = re.compile(r"(^|/)package\.json$")
INCLUDE = re.compile(r"<!--#include ([a-z0-9-]+(?:\.svg)?)-->")   # name → partials/name.html; name.svg → partials/name.svg
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
SRI_TAG = re.compile(r"<(script|link)\b[^>]*integrity=\"\{\{SRI\}\}\"[^>]*>", re.I)
FILLED_EXT = {".html", ".txt", ".webmanifest", ".xml"}
SPDX_PARTIAL = re.compile(r"\A<!-- SPDX-License-Identifier: MIT -->\n")
NOINDEX = re.compile(r"<meta\s+name=\"robots\"\s+content=\"[^\"]*noindex", re.I)
# Under web/app: test evidence (screenshots show dev links with their keys) and test runners.
APP_NEVER_SERVED = ("sidecar", "shots", "ui/tests")
# The config tables the site's copy variants read (web/site/tools/variants.py). The manifest records
# them, so verify-deploy rebuilds with the values this build used, whatever an admin flips later.
VARIANT_TABLES = ("gates", "features", "hosting")


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


def load_config(config_path: Path) -> dict:
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def settings(cfg: dict, origin: str | None) -> dict:
    origin = (origin or cfg["public_origin"]).rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9.-]+(:\d+)?|http://127\.0\.0\.1:\d+", origin):
        raise BuildError(f"origin must be https://host (or http://127.0.0.1:port for development): {origin}")
    network = cfg.get("network", "esmeralda")
    return {
        "ORIGIN": origin,
        "NETWORK": network.capitalize(),
        "SECURITY_DROP_URL": cfg.get("security_drop_url") or origin + "/fine-print#report",
        "REPO_URL": cfg.get("repo_url", "https://github.com/c7b/hidebox").rstrip("/"),
        "BRAND": BRAND,
    }


def check_brand(web: Path) -> None:
    """The app fills {brand} from lib/i18n.js's BRAND; it must be the build's (a tree without the app has none)."""
    source = web / "app" / "lib" / "i18n.js"
    if not source.is_file():
        return
    m = re.search(r"^export const BRAND = '([^']*)';", source.read_text(encoding="utf-8"), re.M)
    if not m or m.group(1) != BRAND:
        raise BuildError(f"web/app/lib/i18n.js BRAND is {m.group(1) if m else None!r}, tools/build.py BRAND is {BRAND!r}")


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
    """pages/<name>.html → <name>/index.html; index → index.html; 404 → 404.html."""
    name = rel.removesuffix(".html")
    return f"{name}.html" if name in ("index", "404") else f"{name}/index.html"


def page_url(rel: str) -> str:
    """The path a page is served at: index → /, <name> → /<name>."""
    return "/" + rel.removesuffix(".html").removesuffix("index")


# Never copied from web/shared: the partials are inlined, and no page uses the Mutis Script fonts kept in
# web/shared/fonts (NOTICE lists them).
SHARED_SKIP = ("partials", "fonts")
# The drive's one family (DESIGN.md "Typography"): Geist, vendored from Vercel's repository with its
# licence and pinned like ootle-wasm (a font can't carry SRI, so the build refuses any other bytes). The
# home sets its words in Geist-Latin.woff2, a subset of the same file (web/site/tools/subset-geist.sh,
# reproducible: 400 to 700, Latin-1; 17-site-brief §1.2), pinned the same way.
FONTS = {"geist/Geist-Variable.woff2": "2ffebe993e969069a9789d15164b7715d42491b5835516c5e3b935d5f81b05f1",
         "geist/Geist-Latin.woff2": "7e1491511dafabbbef951b7f7c96fe6de94a87efe6c2343443cd4167c86b07f3",
         "geist/OFL.txt": None}


def copy_fonts(web: Path, dist: Path) -> None:
    """A tree with the drive (web/app/drive.html) serves its font, and only these exact bytes."""
    if not (web / "app" / "drive.html").is_file():
        return
    for name, expected in FONTS.items():
        src = web / "shared" / "fonts" / name
        if not src.is_file():
            raise BuildError(f"font file missing: web/shared/fonts/{name}")
        if expected and sha256(src) != expected:
            raise BuildError(f"font hash mismatch: web/shared/fonts/{name}")
        (dist / "shared" / "fonts" / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dist / "shared" / "fonts" / name)


def copy_site(web: Path, dist: Path, with_tests: bool) -> list[str]:
    """Returns the pages copied, as paths under web/site/pages."""
    copy_tree(web / "shared", dist / "shared", skip=SHARED_SKIP)
    copy_fonts(web, dist)
    copy_tree(web / "app", dist / "app", skip=APP_NEVER_SERVED + (() if with_tests else ("tests",)))
    copy_tree(web / "app" / "vendor", dist / "vendor")
    copy_tree(web / "site" / "static", dist)
    copy_tree(web / "site" / "js", dist / "site" / "js")
    copy_tree(web / "site" / "css", dist / "site" / "css")
    # /v2's product loops (docs/review/home-v2.md) and the home's stills (media/v3, docs/review/home-v3.md and
    # promote-v3.md): committed like every other served file, so the manifest lists them and verify-deploy checks their
    # bytes; no other page asks for them.
    copy_tree(web / "site" / "media", dist / "site" / "media")
    pages = []
    for page in sorted((web / "site" / "pages").glob("*.html")):
        (dist / page_target(page.name)).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(page, dist / page_target(page.name))
        pages.append(page.name)
    return pages


def set_variants(web: Path, dist: Path, cfg: dict) -> None:
    """Give every data-when variant of the site pages its `hidden` attribute from this deployment's
    config and write llms-full.txt again from the result (the site's tool), so readers without
    JavaScript and crawlers get the sentences that are true here. Before includes and placeholders."""
    tools = web / "site" / "tools"
    if not (tools / "variants.py").is_file():
        raise BuildError(f"{tools / 'variants.py'} is missing: the site's copy variants can't be set")
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import variants
    variants.apply(dist, cfg)


def copy_holding(web: Path, dist: Path) -> list[str]:
    """The holding page (deploy/holding/) on the shared tokens, served until the full site builds."""
    copy_tree(web / "shared", dist / "shared", skip=SHARED_SKIP)
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
        name = m.group(1)
        path = partials / (name if name.endswith(".svg") else f"{name}.html")
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
    for rel in pages:
        target = page_target(rel)
        if target.endswith("404.html") or NOINDEX.search((dist / target).read_text(encoding="utf-8")):
            continue
        urls.append(origin + page_url(rel))
    body = "".join(f"  <url><loc>{u}</loc></url>\n" for u in sorted(urls))
    (dist / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      f"{body}</urlset>\n", encoding="utf-8", newline="\n")


def manifest(dist: Path, state: dict, variant_config: dict) -> dict:
    files = {p.relative_to(dist).as_posix(): sha256(p) for p in sorted(dist.rglob("*")) if p.is_file()}
    doc = {"version": state["version"], "git_sha": state["sha"],
           "built_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "variant_config": variant_config, "files": files}
    out = dist / ".well-known" / "mutis-manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return doc


def content_id(files: dict) -> str:
    """Eight hex digits naming what a build serves; the release id is <commit>-c<content id>, so one commit
    built with another origin or drop URL is another release (deploy.sh, activate-release.sh)."""
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:8]


def build(web: Path, dist: Path, release: Path, cfg: dict, values: dict, state: dict, with_tests: bool = False,
          holding: bool = False) -> dict:
    """`cfg` is the deployment's mutis.toml; `values` fill the {{PLACEHOLDERS}} (settings())."""
    for out in (dist, release / "sidecar"):
        if out.exists():
            shutil.rmtree(out)
    dist.mkdir(parents=True)
    problems = lint.lint(web.parent, ("web/", "deploy/holding/"))
    if problems:
        raise BuildError("lint:\n  " + "\n  ".join(problems))
    vendored = verify_vendored(web)
    check_brand(web)
    if holding:
        pages, variant_config = copy_holding(web, dist), {}
    else:
        pages = copy_site(web, dist, with_tests)
        set_variants(web, dist, cfg)
        variant_config = {t: cfg[t] for t in VARIANT_TABLES if t in cfg}
    copy_sidecar(web, release)
    process_files(dist, web / "shared" / "partials", values | {
        "GIT_SHA": state["sha"], "VERSION": state["version"], "BUILD_DATE": state["date"]})
    sitemap(dist, pages, values["ORIGIN"])
    doc = manifest(dist, state, variant_config)
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
        cfg = load_config(args.config)
        summary = build(args.web.resolve(), args.out.resolve(), args.release.resolve(), cfg,
                        settings(cfg, args.origin), source_state(args.source), args.with_tests, args.holding)
    except (BuildError, OSError, KeyError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as e:
        print(f"build: FAIL: {e}", file=sys.stderr)
        return 1
    print("build: OK " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
