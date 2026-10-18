# SPDX-License-Identifier: MIT
# Reproduce E-19's tap on "Or write one" (no seal, nothing stored), from the repository root on the workstation, the browser
# on the server as build through tests/e2e/relay.py (copied to /home/build/work/promote-v3/relay.py):
#   python3 -I docs/evidence/2026-10-18/promote-v3/e19/tap_probe.py ORIGIN [trials] [device ...]
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests" / "e2e"))
import cdp  # noqa: E402

origin = sys.argv[1]
trials = int(sys.argv[2]) if len(sys.argv) > 2 else 3
devices = sys.argv[3:] or ["android", "iphone"]
STATE = """(() => { const e = document.querySelector('[data-testid="drop-write"]'); const r = e.getBoundingClientRect();
  const x = r.x + r.width / 2, y = r.y + r.height / 2, hit = document.elementFromPoint(x, y);
  const q = document.querySelector('.quick-body');
  const path = (n) => n ? (n.dataset?.testid || n.id || (n.tagName + '.' + String(n.className).split(' ').join('.'))) : null;
  return { t: Math.round(performance.now()), y: Math.round(scrollY), rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
           hit: path(hit), hitInside: e.contains(hit), root: document.documentElement.className, quick: q.className,
           quickOpacity: getComputedStyle(q).opacity, quickTransform: getComputedStyle(q).translate + ' ' + getComputedStyle(q).transform,
           pe: getComputedStyle(e).pointerEvents, vis: e.checkVisibility() }; })()"""
browser = cdp.Browser(["ssh", "hidebox", "sudo -iu build python3 -I /home/build/work/promote-v3/relay.py"])
for device in devices:
    for i in range(trials):
        cid = browser.send("Target.createBrowserContext", {"disposeOnDetach": True})["browserContextId"]
        ctx = cdp.Context(browser, cid)
        page = ctx.page(device)
        t0 = time.monotonic()
        page.goto(origin + "/")
        page.wait("!!document.querySelector('[data-testid=\"drop-input\"]')", 60)
        before = page.eval(STATE)
        x, y = page.center("drop-write")
        at = page.eval(STATE)
        for kind, points in (("touchStart", [{"x": x, "y": y}]), ("touchEnd", [])):
            page.cmd("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})
        try:
            page.wait("(() => { const e = document.querySelector('[data-testid=\"drop-textarea\"]'); return !!e && e.getClientRects().length > 0; })()", 8)
            ok = True
        except cdp.CdpError:
            ok = False
        after = page.eval("(() => { const w = document.querySelector('[data-testid=\"drop-write\"]'); return { write: !!w, textarea: !!document.querySelector('[data-testid=\"drop-textarea\"]'), y: Math.round(scrollY) }; })()")
        print(json.dumps({"device": device, "trial": i, "ok": ok, "secs": round(time.monotonic() - t0, 1), "tap": [round(x), round(y)],
                          "before": before, "at": at, "after": after}))
        ctx.close()
browser.close() if hasattr(browser, "close") else None
