# SPDX-License-Identifier: MIT
# Where does /v2 at 390 differ between two trees (and between two runs of one)? Tile hashes, 400 px tall, reduced motion.
# python3 -I v2_tiles.py <tree with shots_promote.py> <tree> [<tree> ...]: each tree served and captured twice.
import base64, hashlib, importlib.util, sys
from pathlib import Path
tree = Path(sys.argv[1])
sys.path[:0] = [str(tree / "web/site/tools")]
spec = importlib.util.spec_from_file_location("sp", tree / "docs/evidence/2026-10-18/promote-v3/shots_promote.py")
sp = importlib.util.module_from_spec(spec); spec.loader.exec_module(sp)
from cdp import Browser
out = {}
for name in sys.argv[2:]:
    proc, origin = sp.serve(Path(name))
    try:
        for run in (1, 2):
            with Browser() as b:
                page = sp.new_page(b, 390, 844, True, reduce=True)
                page.goto(origin + "/v2", settle=3.0)
                sp.through(page)
                h = page.eval("document.documentElement.scrollHeight")
                tiles = []
                for y in range(0, 6000, 400):
                    d = sp.capture(page, {"x": 0, "y": y, "width": 390, "height": 400}, "png")
                    tiles.append(hashlib.sha256(d).hexdigest()[:8])
                out[f"{name}#{run}"] = tiles
    finally:
        proc.kill()
keys = list(out)
for i in range(15):
    print(i * 400, " ".join(out[k][i] for k in keys))
