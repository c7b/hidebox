# SPDX-License-Identifier: MIT
"""No-JavaScript hero contrast at several widths (devil_site.text_contrast), on serve.py or --origin."""
import sys, threading
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent)]
import devil_site as d
from devil_site import serve, Browser

args = [a for a in sys.argv[1:] if a != "--js"]
js = "--js" in sys.argv
origin = args[0] if args else None
srv = None
if not origin:
    srv, origin = serve.make_server(serve.options(["--port", "0", "--mode", "direct", "--seallog", "--pay"]))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
d.OUT = Path("/tmp")
with Browser() as b:
    for w, h, mobile in ((360, 740, True), (390, 844, True), (412, 915, True), (768, 1024, False), (1024, 768, False), (1280, 800, False), (1440, 900, False), (1920, 1080, False)):
        for dark in (False, True):
            p = b.page(w, h, mobile=mobile, dark=dark)
            if not js:
                p.cmd("Emulation.setScriptExecutionDisabled", {"value": True})
            p.goto(origin + "/", settle=0.8)
            if js:
                p.wait_for("document.querySelector('[data-field]').classList.contains('live')", 10)
                b.pump(3)
            tag = f"{'JS' if js else 'no JS'} @{w} {'dark' if dark else 'light'}"
            d.text_contrast(p, tag, [".lede", ".hero-note"])
            d.text_contrast(p, tag + " (large text)", [".h1-2"])
            p.close()
fails = [r for r in d.REPORT if r[0] == "FAIL"]
print(f"nojs: {len(d.REPORT)} lines, {len(fails)} FAIL")
if srv:
    srv.shutdown()
