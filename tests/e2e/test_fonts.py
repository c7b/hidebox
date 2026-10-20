#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""11-brand P-18, for the drive (DESIGN.md "Typography": one family, Geist, vendored and pinned): the
live hash manifest lists exactly the font files tools/build.py pins (/shared/fonts/geist/Geist-Variable.woff2,
and Geist-Latin.woff2, the home's subset of it), with the hashes it pins, and the bytes the origin serves
have those hashes too; their fingerprinted copies (the manifest's "assets", the names the pages ask for) hold the
same bytes. Each must load in Chromium with no `OTS parsing error`.

  python3 -I tests/e2e/test_fonts.py [--origin URL] [--host H]

The font is loaded with the FontFace API in a page of the origin (so the site CSP applies) by headless
Chromium on the server; a font that fails to load, any other font file, a hash that differs, or any
OTS message fails the test.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
from harness import SSH_HOST, Env, Remote  # noqa: E402

def build_pins() -> dict:
    """URL path → the hash tools/build.py refuses to build without."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import build
    return {f"/shared/fonts/{name}": h for name, h in build.FONTS.items() if name.endswith(".woff2")}


LOAD = """Promise.all(%s.map((u, i) => new FontFace('probe' + i, 'url(' + u + ')').load()
  .then(() => [u, 'ok'], e => [u, String(e)])))"""


def main() -> int:
    p = argparse.ArgumentParser(description="P-18 OTS check")
    p.add_argument("--origin", default="https://hidebox.app")
    p.add_argument("--host", default=SSH_HOST)
    args = p.parse_args()
    origin = args.origin.rstrip("/")
    def get(path):
        with urllib.request.urlopen(urllib.request.Request(origin + path, headers={"User-Agent": "mutis-e2e"}), timeout=20) as res:
            return res.read()
    manifest = json.loads(get("/.well-known/mutis-manifest.json"))
    files, hashed = manifest["files"], manifest.get("assets", {})
    copies = {"/" + hashed[p]: "/" + p for p in hashed if p.endswith((".woff2", ".woff", ".ttf", ".otf"))}
    fonts = sorted("/" + path for path in files if path.endswith((".woff2", ".woff", ".ttf", ".otf")) and "/" + path not in copies)
    pins = build_pins()
    pins.update({copy: pins[plain] for copy, plain in copies.items() if plain in pins})
    fonts = sorted(fonts + [copy for copy, plain in copies.items() if plain in pins])
    if fonts != sorted(pins):
        print(f"FAIL the manifest lists {fonts}, not the pinned {sorted(pins)}")
        print("test_fonts: FAIL (Geist only)")
        return 1
    for path, pinned in pins.items():
        listed = files[path.lstrip("/")]
        served = hashlib.sha256(get(path)).hexdigest()
        if not listed == served == pinned:
            print(f"FAIL {path}: pinned {pinned}, manifest {listed}, served {served}")
            print("test_fonts: FAIL (hash)")
            return 1
        print(f"PASS {path}: pinned Geist, hash matches ({pinned[:12]}…)")
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
