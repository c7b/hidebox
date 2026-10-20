#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What each page costs a browser at its first visit, when it comes back, and when it comes back after a release
(docs/review/perf-1.md). Python standard library only.

  python3 -I tests/e2e/perf_probe.py [--host H] [--ref REF] [--json FILE] [--check]

Builds the working tree (or, with --ref, a commit: its own tools/build.py and Caddyfile) onto the production
Caddyfile's throwaway stack on the server (localstack.py: Caddy and `mutis-api --dev`) and loads each page in headless
Chromium there (relay.py, as build), on a computer (1440 x 900) and a phone (390 x 844, 3x), each in a fresh profile:

1. First visit: every request with its status, the bytes Chromium received for it (encodedDataLength: headers and
   body as sent), its Cache-Control and Content-Encoding.
2. Repeat visit: the same address again in the same profile, a new navigation (not a reload): what reaches the
   network (a 200 or a 304) and what the browser's cache answers alone.
3. After a release: every file's modification time moved, as a deploy moves it (deploy.sh copies the built tree,
   and Caddy's ETag is a file's time and size), then the address once more.

--check (for a tree with fingerprinted names) fails when a page asks for a same-origin file that is neither an
entry point (a page, headers_spec.CARDS, the manifest, the API) nor a fingerprinted name, when a fingerprinted answer
isn't `public, max-age=31536000, immutable`, when a text answer of 512 B or more arrives uncompressed, or when a
repeat visit asks the network for a fingerprinted file.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
import headers_spec  # noqa: E402
from harness import REMOTE_DIR, SSH_HOST, Remote  # noqa: E402
from localstack import WEB_PORT, WORK, LocalStack, stub_build  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAGES = ("/", "/how", "/made", "/judges", "/fine-print", "/this-page-does-not-exist", "/drive")
DEVICES = {"1440": "desktop", "390": "iphone"}
HASHED = re.compile(r"\.[0-9a-f]{10}\.[a-z0-9]+$")
TEXT_TYPES = ("text/", "application/javascript", "application/json", "application/manifest+json", "image/svg+xml",
              "application/wasm", "application/xml")
ENTRY = set(headers_spec.CARDS) | {"/manifest.webmanifest"}


def build_ref(ref: str, out: Path) -> tuple[Path, Path]:
    """dist/ and the Caddyfile of commit `ref`, built by its own tools/build.py for the stack's origin."""
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    src = out / "src"
    src.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", sha], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
    subprocess.run([sys.executable, "-I", str(src / "tools" / "build.py"), "--web", str(src / "web"),
                    "--out", str(out / "dist"), "--release", str(out / "release"),
                    "--origin", f"http://127.0.0.1:{WEB_PORT}",
                    "--source", sha, git("describe", "--tags", "--always", sha), git("log", "-1", "--format=%ct", sha)],
                   check=True, stdout=subprocess.DEVNULL)
    return out / "dist", src / "deploy" / "caddy" / "Caddyfile"


def visit(browser: cdp.Browser, page: cdp.Page, url: str, quiet: float = 1.5, limit: float = 25) -> list[dict]:
    """Navigate, wait for the load event and then for the network to be quiet; every request of the visit."""
    for method in ("Network.requestWillBeSent", "Network.responseReceived", "Network.responseReceivedExtraInfo",
                   "Network.loadingFinished", "Network.loadingFailed", "Network.requestServedFromCache",
                   "Page.loadEventFired"):
        browser.take(page.s, method)
    page.cmd("Page.navigate", {"url": url})
    browser.wait_event("Page.loadEventFired", page.s, 45)
    reqs: dict[str, dict] = {}
    last, end = time.monotonic(), time.monotonic() + limit
    while time.monotonic() < end:
        browser.drain(0.25)
        new = False
        for p in browser.take(page.s, "Network.requestWillBeSent"):
            r = reqs.setdefault(p["requestId"], {"url": p["request"]["url"], "type": p.get("type"), "done": False})
            r["url"] = p["request"]["url"]
            new = True
        for p in browser.take(page.s, "Network.responseReceived"):
            res = p["response"]
            r = reqs.setdefault(p["requestId"], {"url": res["url"], "type": p.get("type"), "done": False})
            h = {k.lower(): v for k, v in res.get("headers", {}).items()}
            r.update(status=res["status"], mime=res.get("mimeType", ""), cache_control=h.get("cache-control", ""),
                     encoding=h.get("content-encoding", ""), disk=res.get("fromDiskCache", False),
                     protocol=res.get("protocol", ""), head=int(res.get("encodedDataLength", 0)))
            new = True
        for p in browser.take(page.s, "Network.responseReceivedExtraInfo"):   # the status on the wire: a 304 shows here
            reqs.setdefault(p["requestId"], {"url": "", "done": False})["wire"] = p.get("statusCode")
        for p in browser.take(page.s, "Network.requestServedFromCache"):
            reqs.setdefault(p["requestId"], {"url": "", "done": False})["memory"] = True
        for p in browser.take(page.s, "Network.loadingFinished"):
            reqs.setdefault(p["requestId"], {"url": "", "done": False}).update(bytes=int(p.get("encodedDataLength", 0)), done=True)
            new = True
        for p in browser.take(page.s, "Network.loadingFailed"):
            reqs.setdefault(p["requestId"], {"url": "", "done": False}).update(failed=p.get("errorText"), done=True)
            new = True
        if new:
            last = time.monotonic()
        elif all(r["done"] for r in reqs.values()) and time.monotonic() - last > quiet:
            break
    out = []
    for r in reqs.values():
        if not r["url"].startswith("http"):
            continue
        cached = bool(r.get("memory") or r.get("disk"))
        out.append({"path": re.sub(r"^https?://[^/]+", "", r["url"]), "status": r.get("wire") or r.get("status"), "type": r.get("type"),
                    "mime": r.get("mime", ""), "bytes": 0 if cached else r.get("bytes", 0), "cached": cached,
                    "body": 0 if cached else max(0, r.get("bytes", 0) - r.get("head", 0)),
                    "network": not cached and "status" in r, "cache_control": r.get("cache_control", ""),
                    "encoding": r.get("encoding", ""), "failed": r.get("failed")})
    return sorted(out, key=lambda r: r["path"])


def summary(reqs: list[dict]) -> dict:
    net = [r for r in reqs if r["network"]]
    return {"requests": len(reqs), "network": len(net), "not_modified": sum(r["status"] == 304 for r in net),
            "from_cache": sum(r["cached"] for r in reqs), "bytes": sum(r["bytes"] for r in net)}


def problems_of(reqs: list[dict], visit_name: str) -> list[str]:
    found = []
    for r in reqs:
        path = r["path"].split("?")[0]
        if path.startswith("/api/") or r.get("failed"):
            continue
        hashed = bool(HASHED.search(path))
        page = r["type"] == "Document" or r["mime"] == "text/html"
        if not (hashed or page or path in ENTRY):
            found.append(f"{visit_name}: {path} is neither fingerprinted nor an entry point")
        if hashed and r["network"] and r["status"] == 200 and r["cache_control"] != headers_spec.IMMUTABLE["cache-control"]:
            found.append(f"{visit_name}: {path} answered Cache-Control {r['cache_control']!r}")
        if visit_name != "first" and hashed and r["network"]:
            found.append(f"{visit_name}: {path} went to the network ({r['status']}) instead of the cache")
        if r["network"] and r["status"] == 200 and r["mime"].startswith(TEXT_TYPES) and r["body"] >= 512 \
                and r["encoding"] not in ("br", "gzip", "zstd"):
            found.append(f"{visit_name}: {path} ({r['mime']}, {r['body']} B) arrived uncompressed")
    return found


def main() -> int:
    p = argparse.ArgumentParser(description="first, repeat and after-release visits of every page")
    p.add_argument("--host", default=SSH_HOST)
    p.add_argument("--ref", help="a commit to build and serve instead of the working tree")
    p.add_argument("--json", type=Path, help="write every request of every visit here")
    p.add_argument("--check", action="store_true", help="fail on a file that isn't fingerprinted or cached as it should be")
    args = p.parse_args()
    report, failures = {"ref": args.ref or "working tree", "pages": {}}, []
    with tempfile.TemporaryDirectory(prefix="mutis-probe-") as tmp:
        if args.ref:
            dist, caddyfile = build_ref(args.ref, Path(tmp))
        else:
            dist, caddyfile = stub_build(Path(tmp) / "dist"), None
        with LocalStack(args.host, dist, caddyfile=caddyfile) as stack:
            remote = Remote(args.host, Path(tmp))
            remote.as_build(f"mkdir -p {REMOTE_DIR} && cat > {REMOTE_DIR}/relay.py", (Path(__file__).parent / "relay.py").read_bytes())
            browser = cdp.Browser(remote.browser_command(False))
            try:
                for width, device in DEVICES.items():
                    for path in PAGES:
                        ctx = browser.context()
                        page = ctx.page(device)
                        page.cmd("Network.setCacheDisabled", {"cacheDisabled": False})
                        visits = {"first": visit(browser, page, stack.web + path)}
                        page.cmd("Page.navigate", {"url": "about:blank"})
                        time.sleep(0.5)
                        visits["repeat"] = visit(browser, page, stack.web + path)
                        stack.remote.as_build(f"find {WORK}/dist -type f -exec touch {{}} +")
                        page.cmd("Page.navigate", {"url": "about:blank"})
                        time.sleep(0.5)
                        visits["after_release"] = visit(browser, page, stack.web + path)
                        ctx.close()
                        key = f"{path} @{width}"
                        report["pages"][key] = {name: {"summary": summary(reqs), "requests": reqs} for name, reqs in visits.items()}
                        line = "  ".join(f"{name} {s['bytes']:>9,} B {s['network']:>2} net ({s['not_modified']} 304) {s['from_cache']:>2} cached"
                                         for name, s in ((n, report["pages"][key][n]["summary"]) for n in visits))
                        print(f"{key:<36} {line}", flush=True)
                        if args.check:
                            failures += [f"{key}: {x}" for name, reqs in visits.items() for x in problems_of(reqs, name)]
            finally:
                browser.close()
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    for line in failures:
        print("FAIL", line)
    if args.check:
        print(f"perf_probe: {'PASS' if not failures else f'FAIL ({len(failures)})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
