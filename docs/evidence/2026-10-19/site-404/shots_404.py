# SPDX-License-Identifier: MIT
"""The new 404 page (docs/review/site-404.md): screenshots and what the browser saw, headless Chromium as `build` on the
server, from the repository root:

  python3 -I docs/evidence/2026-10-19/site-404/shots_404.py [--out DIR]

Serves this tree with web/site/tests/serve.py (production's CSP, the API from fixtures). /no-such-page at 1440 x 900 and
390 x 844, in the dark and the light theme (the system's, no stored choice): the first screen. Then the text selected
(as Ctrl+A does) at 1440 in dark and at 390 in light, which shows the hidden line. page.json: per capture, the status,
the art's file and box, the bytes at load, the console's lines (the ghost and its credit) and any error.
"""
import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "web/site/tools")]
from cdp import Browser  # noqa: E402

SIZES = {1440: (1440, 900, False), 390: (390, 844, True)}
NO_THEME = "try { localStorage.removeItem('mutis.theme'); } catch (e) {}"
SEEN = """(() => { const a = document.querySelector('.nf-art').getBoundingClientRect(), i = document.querySelector('.nf-art img');
  return { art: i.currentSrc.split('/').pop(), box: [Math.round(a.left), Math.round(a.top), Math.round(a.width), Math.round(a.height)],
           bottom_of_go_home: Math.round(document.querySelector('.ways .btn').getBoundingClientRect().bottom) }; })()"""


def serve():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-I", str(ROOT / "web/site/tests/serve.py"), "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(origin + "/robots.txt", timeout=1).read()
            return proc, origin
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("serve.py didn't start")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    out = p.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    proc, origin = serve()
    report = {}
    try:
        with Browser() as b:
            for width, (w, h, mobile) in SIZES.items():
                for theme in ("dark", "light"):
                    page = b.page(w, h, mobile=mobile, android=mobile, dark=theme == "dark")
                    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": NO_THEME})
                    page.goto(origin + "/no-such-page", settle=1.5)
                    page.eval("document.fonts.ready.then(() => true)", True)
                    page.wait_for("document.querySelector('.nf-art img').complete", 10)
                    for _ in range(60):   # egg.js prints after the load event, when the browser is idle
                        if sum(1 for l in page.console() if l.startswith("log: ")) >= 2:
                            break
                        b.pump(0.1)
                    name = f"404-{width}-{theme}"
                    page.screenshot(str(out / f"{name}.webp"))
                    doc = [r for r in page.requests() if r["type"] == "Document"]
                    report[name] = {"status": doc[0]["status"] if doc else None, **page.eval(SEEN),
                                    "bytes_at_load": sum(r["bytes"] for r in page.requests()),
                                    "requests": sorted(r["url"].replace(origin, "") for r in page.requests()),
                                    "console": page.console()}
                    if (width, theme) in ((1440, "dark"), (390, "light")):
                        page.eval("getSelection().selectAllChildren(document.body)")
                        b.pump(0.3)
                        page.screenshot(str(out / f"{name}-selected.webp"))
                        report[name]["selected_text_ends"] = page.eval("getSelection().toString().trim().split('\\n').filter(Boolean).slice(-12)")
    finally:
        proc.kill()
    (out / "page.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: {x: v[x] for x in ("status", "art", "box", "bytes_at_load")} for k, v in report.items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
