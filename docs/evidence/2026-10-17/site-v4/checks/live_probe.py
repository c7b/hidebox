# SPDX-License-Identifier: MIT
"""Site v4 on production (as `build` on ultron): python3 -I live_probe.py [origin]
The headline and its descriptions; the comparison with one column beside hidebox (a table on a computer, stacked
cards on a phone), its intro not repeating the hero's sentence; one sentence a line on the home (measured: the next
sentence starts below the period); the share card; /drive's start screen with one lime action and no CSP
violation. Reads pages only: it makes no drive, link or file."""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
sys.path[:0] = [str(Path.home() / "work/site-v4/web/site/tools")]
from cdp import Browser  # noqa: E402

O = sys.argv[1] if len(sys.argv) > 1 else "https://srv2052606.hstgr.cloud"
H1 = "Your private cloud storage. Privacy isn't an option. It's the default."
TEXT = "(s) => document.querySelector(s)?.textContent.replace(/\\s+/g, ' ').trim()"
INLINE = r"""(() => { const END = /[.!?][”’")]?\s+(?=[“‘"(]?[A-Z])/g; const out = [];
  for (const el of document.querySelectorAll('main p, main dd, main li, main td, footer p')) {
    if (!el.getClientRects().length || el.closest('[hidden], .slice, .share-pic') || el.querySelector('p, dd, li, td')) continue;
    const nodes = []; let full = '';
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement.closest('[hidden]') ? 2 : 1) });
    for (let n; (n = w.nextNode());) { nodes.push([n, full.length]); full += n.data; }
    const box = (i) => { for (let k = nodes.length - 1; k >= 0; k--) { const [n, o] = nodes[k]; if (o > i) continue;
      if (i - o >= n.data.length) return null; const r = document.createRange(); r.setStart(n, i - o); r.setEnd(n, i - o + 1);
      return [...r.getClientRects()].find((x) => x.width > 0) ?? null; } return null; };
    for (const m of full.matchAll(END)) { const a = box(m.index), b = box(m.index + m[0].length);
      if (a && b && Math.abs(b.top - a.top) < 2) out.push(full.replace(/\s+/g, ' ').trim().slice(0, 60)); } }
  return out; })()"""
LIMES = """[...document.querySelectorAll('button, a')].filter((e) => e.getClientRects().length
  && getComputedStyle(e).backgroundColor === 'rgb(188, 254, 0)').map((e) => e.dataset.testid || e.textContent.trim())"""
fails = 0


def ok(cond, text):
    global fails
    fails += not cond
    print(("PASS " if cond else "FAIL ") + text, flush=True)


with Browser() as b:
    for w, h, m in ((1280, 800, False), (390, 844, True)):
        p = b.page(w, h, mobile=m)
        p.goto(O + "/", settle=2.5)
        ok(p.eval(f"({TEXT})('#hero-h')") == H1, f"/ @{w}: the headline reads {H1!r}")
        ok(p.eval("document.querySelectorAll('#hero-h br, .hero .lede br, .hero-note br').length") == 3,
           f"/ @{w}: the headline's second line, the lede and the note break after each sentence")
        heads = p.eval("[...document.querySelectorAll('.compare thead th')].map((e) => e.textContent.trim())")
        labels = p.eval("[...new Set([...document.querySelectorAll('.compare tbody td')].map((e) => e.dataset.label))]")
        ok(heads == ["Question", "hidebox", "A popular cloud drive"] and labels == ["hidebox", "A popular cloud drive"],
           f"/ @{w}: the comparison: hidebox and A popular cloud drive ({heads[1:]}, {labels})")
        intro = p.eval(f"({TEXT})('#different .sec-head p')")
        body = p.eval("document.querySelector('main').textContent.replace(/\\s+/g, ' ')")
        ok(intro.startswith("Your files lock here, in your browser.") and body.count("Files lock in this browser before upload.") == 2,
           f"/ @{w}: the intro no longer repeats the hero's sentence (it stays in the hero and the first cell)")
        cells = p.eval("(() => { const r = document.querySelector('.compare tbody tr'); const [us, other] = r.querySelectorAll('td');"
                       " return [us.getBoundingClientRect().top < other.getBoundingClientRect().top, us.getBoundingClientRect().left === other.getBoundingClientRect().left]; })()")
        ok(cells == ([True, True] if m else [False, False]), f"/ @{w}: {'stacked cards' if m else 'a two-column table'} ({cells})")
        for y in range(0, int(p.eval("document.documentElement.scrollHeight")) + int(h * .6), int(h * .6)):
            p.scroll_to(y, 0.2)
        p.b.pump(1.2)
        inline = p.eval(INLINE)
        ok(not inline, f"/ @{w}: every sentence of a paragraph starts on its own line ({inline[:3]})")
        bad = [c for c in p.console() if "Content Security Policy" in c or "Trusted Type" in c]
        ok(not bad, f"/ @{w}: no CSP or Trusted Types violation {bad[:2]}")
    meta = p.eval("[...document.querySelectorAll('meta[name=description], meta[property^=\"og:\"]')].map((e) => [e.getAttribute('name') || e.getAttribute('property'), e.content])")
    meta = dict(meta)
    ld = json.loads(p.eval("document.querySelector('script[type=\"application/ld+json\"]').textContent"))
    ok(meta["description"].startswith("Your private cloud storage.") and meta["og:title"] == "Your private cloud storage."
       and meta["og:description"].startswith("Privacy isn't an option. It's the default.")
       and ld["@graph"][1]["description"].startswith("Your private cloud storage:"), "/: the description, og:title, og:description and JSON-LD follow the headline")
    with urllib.request.urlopen(O + "/og.png") as res:
        served = hashlib.sha256(res.read()).hexdigest()
    ok(served == hashlib.sha256((Path.home() / "work/site-v4/web/site/static/og.png").read_bytes()).hexdigest(), f"/og.png is the new card ({served[:12]})")
    d = b.page(390, 844, mobile=True)
    d.goto(O + "/drive", settle=3)
    ok(d.eval(LIMES) == ["drive-make"], f"/drive @390 without a drive: one lime action, Make my drive ({d.eval(LIMES)})")
    bad = [c for c in d.console() if "Content Security Policy" in c or "Trusted Type" in c]
    ok(not bad, f"/drive: no CSP or Trusted Types violation {bad[:2]}")
print(f"live probe: {'PASS' if not fails else 'FAIL'} ({fails} failures)")
sys.exit(1 if fails else 0)
