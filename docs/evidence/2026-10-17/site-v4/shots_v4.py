# SPDX-License-Identifier: MIT
"""Site v4 screenshots and the sentence audit (docs/review/site-v4.md), as `build` on the server, from the
repository root:

  python3 -I docs/evidence/2026-10-17/site-v4/shots_v4.py [--out DIR] [--tag before|after] [--only home,how,...]

For each page at 1280 (computer) and 390 (phone), light: the first screen and the whole page after scrolling
through it (every reveal has run); on the home also the comparison and the closing, and both widths in dark.
Then the audit: every paragraph-like block with two or more sentences, measured in the page as served: a
sentence that does not start on a new line, and a last line of one short word (an orphan). Prints one line per
finding and a summary; writes audit-<tag>.json beside the shots. WebP from headless Chromium.
"""
import argparse
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "web/site/tests"), str(ROOT / "web/site/tools")]
import serve  # noqa: E402
from cdp import Browser  # noqa: E402

PAGES = {"home": "/", "how": "/how", "judges": "/judges", "made": "/made", "fine-print": "/fine-print", "404": "/no-such-page"}
SIZES = {1280: (1280, 800, False), 390: (390, 844, True)}
# What the rule covers (the brief's list): ledes and section intros, hero notes, step and card text, table cells,
# the footer. Long reading prose on /made and /fine-print is audited for its ledes and intros only.
BLOCKS = "main p, main dd, main li, main li > span, main td, main .see, main .do, main figcaption, footer p"
AUDIT = r"""(() => {
  // Each sentence end in the block's visible text: the next sentence must start lower than the period sits
  // (a new line); a sentence whose last word sits alone on the last line is an orphan.
  const END = /[.!?][”’")]?\s+(?=[“‘"(]?[A-Z])/g;
  const out = [];
  for (const el of document.querySelectorAll(%s)) {
    if (!el.getClientRects().length || el.closest('[hidden], .slice, .share-pic, .still-frame, .ui-card')) continue;
    if (el.querySelector('p, dd, li, td')) continue;
    const nodes = []; let full = '';
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement.closest('[hidden]') ? 2 : 1) });
    for (let n; (n = walk.nextNode());) { nodes.push([n, full.length]); full += n.data; }
    const box = (i) => {
      for (let k = nodes.length - 1; k >= 0; k--) {
        const [n, o] = nodes[k];
        if (o > i) continue;
        if (i - o >= n.data.length) return null;
        const r = document.createRange(); r.setStart(n, i - o); r.setEnd(n, i - o + 1);
        return [...r.getClientRects()].find((x) => x.width > 0) ?? null;
      }
      return null;
    };
    const ends = [...full.matchAll(END)];
    if (!ends.length) continue;
    let inline = 0, orphan = 0;
    const cuts = [...ends.map((m) => m.index), full.trimEnd().length - 1];
    for (const m of ends) {
      const a = box(m.index), b = box(m.index + m[0].length);
      if (a && b && Math.abs(b.top - a.top) < 2) inline++;
    }
    for (const c of cuts) {
      const space = full.lastIndexOf(' ', c);
      const word = full.slice(space + 1, c + 1);
      if (space < 0 || word.length > 10) continue;
      const a = box(space - 1), b = box(space + 1);
      const prev = cuts.filter((x) => x < c).pop() ?? -1;
      if (a && b && b.top - a.top > 2 && full.slice(prev + 1, space).trim().includes(' ')) orphan++;
    }
    out.push({ sel: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ').join('.') : ''),
               text: full.replace(/\s+/g, ' ').trim().slice(0, 90), sentences: ends.length + 1, inline, orphan });
  }
  return out;
})()"""


def through(page):
    h = page.height * 0.6
    for y in range(0, int(page.eval("document.documentElement.scrollHeight")) + int(h), int(h)):
        page.scroll_to(y, 0.2)
    page.b.pump(1.2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--tag", default="after")
    p.add_argument("--only", default=",".join(PAGES))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    srv, origin = serve.make_server(serve.options(["--port", "0", "--mode", "direct", "--seallog", "--pay"]))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    audit, n = {}, 0
    with Browser() as b:
        for w, (width, height, mobile) in SIZES.items():
            for name in args.only.split(","):
                path = PAGES[name]
                for dark in ((False, True) if name == "home" else (False,)):
                    theme = "-dark" if dark else ""
                    page = b.page(width, height, mobile=mobile, dark=dark)
                    page.goto(origin + path, settle=2.5)
                    page.screenshot(str(args.out / f"{args.tag}-{name}-{w}{theme}.webp"))
                    through(page)
                    page.scroll_to(0, 0.5)
                    page.screenshot(str(args.out / f"{args.tag}-{name}-{w}{theme}-full.webp"), full=True)
                    n += 2
                    if name == "home" and not dark:
                        for sel, part in (("#different", "compare"), (".end", "closing"), (".hero-inner", "hero")):
                            page.screenshot_element(sel, str(args.out / f"{args.tag}-{name}-{w}-{part}.webp"))
                            n += 1
                    if not dark:
                        audit[f"{name}@{w}"] = page.eval(AUDIT % json.dumps(BLOCKS))
    srv.shutdown()
    inline = orphans = blocks = 0
    for where, rows in audit.items():
        for r in rows:
            blocks += 1
            if r["inline"]:
                inline += 1
                print(f"INLINE {where}: {r['sel']} {r['inline']} sentence(s) not on a new line: {r['text']!r}")
            if r["orphan"]:
                orphans += 1
                print(f"ORPHAN {where}: {r['sel']} {r['orphan']} one-word last line(s): {r['text']!r}")
    (args.out / f"audit-{args.tag}.json").write_text(json.dumps(audit, indent=1) + "\n")
    print(f"{n} screenshots in {args.out}; audit: {blocks} blocks of two or more sentences, {inline} with a sentence "
          f"not on its own line, {orphans} with a one-word last line")


if __name__ == "__main__":
    main()
