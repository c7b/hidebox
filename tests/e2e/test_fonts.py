#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""11-brand P-18, after the ghost (DESIGN.md: system faces only): the live hash manifest lists no font
file, so a page can't ask for one. Any WOFF2 that comes back still must load in Chromium with no
`OTS parsing error`.

  python3 -I tests/e2e/test_fonts.py [--origin URL] [--host ultron]

The font list is every .woff2 in the live hash manifest. None is the expected state and passes. Each
one listed is loaded with the FontFace API in a page of the origin (so the site CSP applies) by
headless Chromium on the server; any font that fails to load or any OTS message fails the test.
"""
import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
from harness import Env, Remote  # noqa: E402

LOAD = """Promise.all(%s.map((u, i) => new FontFace('probe' + i, 'url(' + u + ')').load()
  .then(() => [u, 'ok'], e => [u, String(e)])))"""


def main() -> int:
    p = argparse.ArgumentParser(description="P-18 OTS check")
    p.add_argument("--origin", default="https://srv2052606.hstgr.cloud")
    p.add_argument("--host", default="ultron")
    args = p.parse_args()
    origin = args.origin.rstrip("/")
    with urllib.request.urlopen(urllib.request.Request(origin + "/.well-known/mutis-manifest.json",
                                                       headers={"User-Agent": "mutis-e2e"}), timeout=20) as res:
        fonts = sorted("/" + path for path in json.load(res)["files"] if path.endswith(".woff2"))
    if not fonts:
        print("test_fonts: PASS (no font files served: system faces only)")
        return 0
    env = Env(origin, Remote(args.host, Path(tempfile.mkdtemp(prefix="mutis-fonts-"))), Path("."))
    env.remote.as_build("mkdir -p /home/build/work/deploy/e2e")
    env.remote.as_build("cat > /home/build/work/deploy/e2e/relay.py", (Path(__file__).parent / "relay.py").read_bytes())
    browser = cdp.Browser(env.remote.browser_command(False))
    try:
        page = browser.context().page("desktop")
        page.goto(origin + "/robots.txt")
        results = page.eval(LOAD % json.dumps(fonts), await_promise=True)
        page.b.drain(2)
        page.collect()
        ots = [e["text"] for e in page.logs if "OTS" in e.get("text", "")]
    finally:
        browser.close()
    failures = 0
    for url, outcome in results:
        print(f"{'PASS' if outcome == 'ok' else 'FAIL'} {url} {'' if outcome == 'ok' else outcome}")
        failures += outcome != "ok"
    for line in ots:
        print(f"FAIL console: {line[:200]}")
    failures += len(ots)
    print(f"test_fonts: {'PASS' if not failures else 'FAIL'} ({len(fonts)} fonts, {len(ots)} OTS messages)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
