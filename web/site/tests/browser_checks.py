# SPDX-License-Identifier: MIT
"""Checks in headless Chromium against tests/serve.py (fixtures for the API, production CSP headers).
Each check returns a list of problems (empty = pass) and may record notes for ACCEPTANCE.md."""
import gzip
import json
import re
import threading
import urllib.parse
import urllib.request
from contextlib import contextmanager

import serve
from cdp import Browser

ALL_PAGES = ["/", "/how", "/security", "/pricing", "/faq", "/judges", "/terms", "/privacy", "/abuse", "/status"]
ALL_PAGES += ["/es" + ("/" if p == "/" else p) for p in ALL_PAGES] + ["/no-such-page", "/es/no-such-page"]
NOTES: list[str] = []


@contextmanager
def server(*args):
    srv, origin = serve.make_server(serve.options(["--port", "0", *args]))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        srv.shutdown()


def real_errors(page):
    """Console errors other than the 404 of the page we asked for on purpose."""
    out = []
    for line in page.console():
        if not line.startswith(("error", "exception")):
            continue
        missing = {r["url"] for r in page.requests() if r["status"] == 404}
        if "404" in line and missing and all("no-such-page" in u for u in missing):
            continue
        out.append(line)
    return out


def check_fonts(browser):
    """No OTS parsing error; all three Mutis faces load (11-brand §13.3 step 5)."""
    with server() as origin:
        page = browser.page()
        page.goto(origin + "/security")
        states = page.eval("Promise.all([...document.fonts].map(f => f.load().then(() => f.family + ' ' + f.weight + ' ' + f.status, () => f.family + ' failed')))", True)
        problems = [line for line in page.console() if "OTS" in line]
        problems += [s for s in states if not s.endswith("loaded")]
        NOTES.append(f"fonts: {', '.join(states)}; OTS errors: {len([l for l in page.console() if 'OTS' in l])}")
        return problems


def check_pages(browser):
    """Every page, EN and ES, on a 1440 desktop and a 360 phone: no errors, no CSP violation, no sideways scroll."""
    problems = []
    with server() as origin:
        for width, height, mobile in ((1440, 900, False), (360, 740, True)):
            for path in ALL_PAGES:
                page = browser.page(width, height, mobile=mobile)
                page.goto(origin + path, settle=1.2)
                errors = real_errors(page) + [l for l in page.console() if "Content Security Policy" in l]
                problems += [f"{path} @{width}: {e}" for e in errors]
                scroll = page.eval("document.documentElement.scrollWidth")
                if scroll > width:
                    problems.append(f"{path} @{width}: scrolls sideways ({scroll}px)")
                if page.eval("document.querySelectorAll('h1').length") != 1:
                    problems.append(f"{path} @{width}: not exactly one h1")
    return problems


def _body(url):
    with urllib.request.urlopen(url) as res:
        return res.read()


def check_budget(browser):
    """M-01 on /: ≤ 400 KB total, ≤ 60 KB compressed HTML+CSS+JS, ≤ 2 fonts, 0 third-party requests."""
    problems = []
    with server() as origin:
        page = browser.page(1440, 900)
        page.goto(origin + "/", settle=3)
        reqs = [r for r in page.requests() if r["status"] == 200]
        third = [r["url"] for r in page.requests() if not r["url"].startswith((origin, "data:"))]
        text, other, fonts = 0, 0, 0
        for r in reqs:
            if r["method"] != "GET":   # the widget's anti-bot challenge request: counted as it arrived
                other += r["bytes"]
                continue
            body = _body(r["url"])
            if r["url"].endswith(".woff2"):
                fonts += 1
            if r["type"] in ("Document", "Stylesheet", "Script") or r["url"].endswith((".js", ".css")):
                text += len(gzip.compress(body, 9))
            else:
                other += len(body)
        NOTES.append(f"budget on /: {len(reqs)} requests, HTML+CSS+JS {text / 1024:.1f} KB gzip, "
                     f"other {other / 1024:.1f} KB, total {(text + other) / 1024:.1f} KB, {fonts} font files, "
                     f"third-party {len(third)} (with the drop widget's first load)")
        if third:
            problems.append(f"third-party requests: {third}")
        if fonts > 2:
            problems.append(f"{fonts} font files on /")
        if text > 60 * 1024:
            problems.append(f"HTML+CSS+JS is {text / 1024:.1f} KB compressed")
        if text + other > 400 * 1024:
            problems.append(f"total is {(text + other) / 1024:.1f} KB")
    return problems


VISIBLE_NEEDS = "[...document.querySelectorAll('[data-needs]')].filter(e => !e.closest('[hidden]')).length"
HIDDEN_NEEDS = "[...document.querySelectorAll('[data-needs]')].filter(e => e.hidden).length"


def check_live_numbers(browser):
    """M-07: numbers come from /config, /stats, /stats/wall, /canary, /evidence.json, and disappear when those fail."""
    problems = []
    with server() as origin:
        page = browser.page(1440, 900)
        page.goto(origin + "/", settle=2.5)
        _scroll_through(page, "exit-wall", "send", "what-we-store", "try")
        text = page.eval("document.body.innerText")
        for expected in ("No locker? Files up to 25 MB, gone within 24 hours.", "per locker", "Here's a file we locked"):
            if expected not in text:
                problems.append(f"API up: {expected!r} not shown")
        for sel in ("[data-chain-card]", "[data-canary]", "[data-reveal]"):
            if page.eval(f"document.querySelector('{sel}').hidden"):
                problems.append(f"API up: {sel} stays hidden")
        page = browser.page(1440, 900, block=["*/api/*", "*/evidence.json"])
        page.goto(origin + "/", settle=2.5)
        _scroll_through(page, "exit-wall", "send", "what-we-store", "try")
        if page.eval(VISIBLE_NEEDS) != 0:
            problems.append("API blocked: a [data-needs] block is still visible on /")
        for sel in ("[data-chain-card]", "[data-canary]", "[data-reveal]"):
            if not page.eval(f"document.querySelector('{sel}').hidden"):
                problems.append(f"API blocked: {sel} is visible")
        if page.eval("document.querySelector('[data-canary-missing]').hidden"):
            problems.append("API blocked: the 'between takes' line is hidden")
        if not page.eval("document.querySelector('[data-wall-desc]').textContent.startsWith('A scene')"):
            problems.append("API blocked: the wall isn't the scripted scene")
        page.goto(origin + "/pricing", settle=1.5)
        NOTES.append(f"API blocked: /pricing hides {page.eval(HIDDEN_NEEDS)} [data-needs] blocks, shows "
                     f"{page.eval(VISIBLE_NEEDS)}; / shows no live number")
        if page.eval(VISIBLE_NEEDS) != 0:
            problems.append("API blocked: /pricing still shows a number block")
    return problems


WAKE_WALL = "document.getElementById('exit-wall').offsetTop - innerHeight + 40"
GO_TO = "document.getElementById('{}').offsetTop"


def _wall(browser, origin, reduce=False, width=1440, height=900, mobile=False):
    """The home page with the exit wall woken: its top just into view, its lockers still below the fold."""
    page = browser.page(width, height, mobile=mobile, reduce=reduce)
    page.goto(origin + "/", settle=1.5)
    page.scroll_to(page.eval(WAKE_WALL), 1.5)
    return page


def _scroll_through(page, *ids):
    """Each section's code loads when it comes near, as a visitor scrolls down to it."""
    for section in ids:
        page.scroll_to(page.eval(GO_TO.format(section)), 1.2)


FRAMES = """(async () => {
  const wall = document.getElementById('exit-wall');
  const top = wall.offsetTop, span = wall.offsetHeight - innerHeight;
  scrollTo(0, top - innerHeight + 40);   // wake the wall while its lockers are below the fold
  await new Promise((r) => setTimeout(r, 1500));
  scrollTo(0, top - 10);
  await new Promise((r) => setTimeout(r, 300));
  const deltas = [];
  let last = performance.now();
  const t0 = last;
  await new Promise((done) => {
    const step = (now) => {
      deltas.push(now - last);
      last = now;
      const k = (now - t0) / 4000;
      scrollTo(0, top + Math.min(1, k) * span);
      if (k < 1) requestAnimationFrame(step); else done();
    };
    requestAnimationFrame(step);
  });
  deltas.sort((a, b) => a - b);
  const q = (p) => Math.round(deltas[Math.floor(p * (deltas.length - 1))]);
  return [deltas.length, q(0.5), q(0.95)];
})()"""
FRAME_BUDGET_MS = 1000 / 60
RESTYLE_MAX = 32   # two leaving lockers' worth of elements; restyling the whole stage is about 145
TIMELINE = "devtools.timeline,disabled-by-default-devtools.timeline"


def check_wall(browser):
    """M-02: the wall with quiet data, 8 items and 24, never showing whether a file has left, each box as deep
    as its size class; reduced motion is the static grid; the scene starts without our canary and never
    relabels lockers in view; it plays to its end."""
    problems = []
    lockers = "[...document.querySelectorAll('.locker:not(.centre)')]"
    for scenario, expected in (("quiet", "A scene"), ("8", "A wall of lockers drawn from the last 8"), ("24", "A wall of lockers drawn from the last 24")):
        with server("--wall", scenario) as origin:
            page = _wall(browser, origin)
            desc = page.eval("document.querySelector('[data-wall-desc]').textContent")
            if not desc.startswith(expected):
                problems.append(f"wall {scenario}: description is {desc[:60]!r}")
            empty = page.eval("document.querySelectorAll('.locker[data-cue=\"empty\"]').length")
            want_empty = {"quiet": 0, "8": 9, "24": 0}[scenario]
            if empty != want_empty:
                problems.append(f"wall {scenario}: {empty} empty lockers, expected {want_empty}")
            if scenario == "quiet":
                continue
            unlit = page.eval(f"{lockers}.filter(l => l.dataset.cue !== 'empty' && !l.classList.contains('lit')).length")
            words = page.eval(f"{lockers}.map(l => l.textContent).join(' ')")
            if unlit or "gone" in words or "opened" in words:
                problems.append(f"wall {scenario}: a locker shows whether its file has left")
            depth = page.eval(f"{lockers}.filter(l => l.style.getPropertyValue('--size')).map(l => "
                              "[Number(l.style.getPropertyValue('--size')), parseFloat(getComputedStyle(l.querySelector('.side.l')).width)])")
            by_size = dict(depth)
            if scenario == "8" and not (by_size.get(0, 0) < by_size.get(2, 0) < by_size.get(4, 0)):
                problems.append(f"wall 8: side depth by size class is {sorted(by_size.items())}")
            reduced = _wall(browser, origin, reduce=True)
            faces = reduced.eval(f"{lockers}.filter(l => l.dataset.cue !== 'empty').map(l => getComputedStyle(l.querySelector('.front')).borderStyle)")
            if any(style != "solid" for style in faces):
                problems.append(f"wall {scenario}, reduced motion: data lockers drawn as already gone ({set(faces)})")
    with server() as origin:
        page = _wall(browser, origin, reduce=True)
        if page.eval("document.documentElement.classList.contains('motion')"):
            problems.append("reduced motion: the stage is laid out for the scene")
        if page.eval("getComputedStyle(document.querySelector('.locker .fate')).display") == "none":
            problems.append("reduced motion: fates are hidden")
        page = browser.page(block=["*/api/v1/canary*"])
        page.goto(origin + "/", settle=1)
        page.scroll_to(page.eval("document.getElementById('exit-wall').offsetTop + innerHeight * .1"), 1.5)
        door = page.eval("document.querySelector('.noise-door').width")
        if not page.eval("document.querySelector('[data-wall-direction]').textContent") or door == 48:
            problems.append(f"canary unreachable: the scene doesn't play or its door isn't drawn (width {door})")
        page = _wall(browser, origin)
        top, height = page.eval("(() => { const r = document.getElementById('exit-wall').getBoundingClientRect(); return [r.top + scrollY, r.height]; })()")
        directions = set()
        for f in (0, 0.2, 0.4, 0.55, 0.7, 1):
            page.scroll_to(top + f * (height - 900), 0.5)
            directions.add(page.eval("document.querySelector('[data-wall-direction]').textContent"))
        gone = page.eval("[...document.querySelectorAll('.locker:not(.centre) .front')].filter(e => e.offsetParent).every(e => getComputedStyle(e).opacity === '0')")
        lit = page.eval("getComputedStyle(document.querySelector('.locker.centre .front')).opacity")
        end = page.eval("getComputedStyle(document.querySelector('.wall-end')).opacity")
        cue = page.eval("getComputedStyle(document.querySelector('.wall-direction')).opacity")
        NOTES.append(f"wall scene: {len(directions)} stage directions over the scroll; at the end every other locker gone: "
                     f"{gone}, centre opacity {lit}, closing words opacity {end}, last direction opacity {cue}")
        if not gone or lit != "1" or end != "1" or cue != "0" or len(directions) < 4:
            problems.append("the scene doesn't play to its end frame")
    with server("--wall-delay", "3") as origin:
        page = browser.page()
        page.goto(origin + "/", settle=0.2)
        page.scroll_to(page.eval("document.getElementById('exit-wall').offsetTop + innerHeight * .5"), 4)
        if not page.eval("document.querySelector('[data-wall-desc]').textContent.startsWith('A scene')"):
            problems.append("late wall data relabelled lockers the visitor was looking at")
    return problems


def _main_thread(events):
    """Per-task CPU time (ms) on the page's main thread, and the element count of every style recalc."""
    main = {(e["pid"], e["tid"]) for e in events if e.get("name") == "thread_name" and e["args"]["name"] == "CrRendererMain"}
    cpu = [e.get("tdur", 0) / 1000 for e in events if e.get("ph") == "X" and e.get("name") == "RunTask" and (e["pid"], e["tid"]) in main]
    restyled = sorted(e["args"].get("elementCount", 0) for e in events if e.get("ph") == "X" and e.get("name") == "UpdateLayoutTree")
    return sum(cpu), restyled


def check_wall_frames(_):
    """12-integration §1: the scene on an Android-class phone (412x915, touch) scrolled through in 4 s, in a
    browser of its own. With the CPU slowed 4x this records frame times (notes only: this box draws with
    software GL on two shared cores, so they say more about the box than about a phone). Unthrottled it
    measures the main thread's CPU time per frame, which must fit one 60 Hz frame four times over, and a
    scroll frame may restyle only the lockers leaving at that moment (review M9)."""
    problems = []
    with Browser() as browser:
        for wall in ("quiet", "24"):
            with server("--wall", wall) as origin:
                for rate in (4, 1):
                    page = browser.page(412, 915, mobile=True, android=True, cpu_throttle=rate)
                    page.goto(origin + "/", settle=3)
                    result = {}
                    events = browser.trace(TIMELINE, lambda: result.update(frames=page.eval(FRAMES, True)))
                    page.close()
                    frames, median, p95 = result["frames"]
                    if rate == 4:
                        NOTES.append(f"wall frames ({wall}, 412x915, 4x CPU): {frames} frames, median {median} ms, p95 {p95} ms")
                        continue
                    cpu, restyled = _main_thread(events)
                    per_frame = cpu / frames
                    typical = restyled[len(restyled) // 2] if restyled else 0
                    NOTES.append(f"wall main thread ({wall}, 412x915): {per_frame:.2f} ms of CPU per frame "
                                 f"({4 * per_frame:.1f} ms at 4x); {typical} elements restyled per frame (median)")
                    if 4 * per_frame > FRAME_BUDGET_MS:
                        problems.append(f"wall {wall}: {4 * per_frame:.1f} ms of main-thread CPU per frame at 4x (budget {FRAME_BUDGET_MS:.1f})")
                    if typical > RESTYLE_MAX:
                        problems.append(f"wall {wall}: a scroll frame restyles {typical} elements (median; limit {RESTYLE_MAX})")
    return problems


def check_variants(browser):
    """Copy variants follow /config: relay or direct sends, SealLog off or on."""
    problems = []
    probes = {"relay": "[data-when=\"send_mode=relay\"]", "direct": "[data-when=\"send_mode=direct\"]",
              "seallog": "[data-when=\"seallog=on\"]"}
    for args, shown, hidden in ((("--mode", "relay"), ["relay"], ["direct", "seallog"]),
                                (("--mode", "direct", "--seallog"), ["direct", "seallog"], ["relay"])):
        with server(*args) as origin:
            page = browser.page()
            page.goto(origin + "/", settle=2)
            for key in shown:
                if page.eval(f"[...document.querySelectorAll('{probes[key]}')].some(e => e.hidden)"):
                    problems.append(f"{args}: a {key} variant stays hidden")
            for key in hidden:
                if page.eval(f"[...document.querySelectorAll('{probes[key]}')].some(e => !e.hasAttribute('hidden'))"):
                    problems.append(f"{args}: a {key} variant is shown")
            page.goto(origin + "/judges", settle=1.5)
            steps = "Seen on chain → Amount proven" if "direct" in args else "Seen by our wallet → Exists on chain"
            if f"Waiting → {steps} → Added" not in page.eval("document.body.innerText"):
                problems.append(f"{args}: /judges B6 doesn't show the app's payment steps for this mode ({steps})")
            if "direct" in args:   # review H2: the sponsor grant's on-chain linkage is disclosed where sends are explained
                for path in ("/", "/how", "/security", "/es/", "/es/how", "/es/security"):
                    page.goto(origin + path, settle=1.5)
                    if not re.search(r"sponsor wallet|cartera patrocinadora", page.eval("document.body.innerText")):
                        problems.append(f"direct mode: {path} doesn't say sends link back to our sponsor wallet")
    return problems


def check_phase(browser):
    """M-08 in the page: the status line switches at mainnet."""
    with server() as origin:
        page = browser.page()
        page.goto(origin + "/how")
        flipped = page.eval("import('/shared/dates.js').then(m => { m.applyPhase(document, m.MAINNET); "
                            "return [...document.querySelectorAll('[data-phase-show]')].map(e => e.dataset.phaseShow + ':' + e.hidden).join(' '); })", True)
        return [] if "pre:true" in flipped and "mainnet:false" in flipped and "mainnet:true" not in flipped else [f"phase flip: {flipped}"]


def _type_and_enter(page, selector, text):
    """A visitor's keystrokes, which work with scripts off: focus the field, type, press Enter."""
    doc = page.cmd("DOM.getDocument")["root"]["nodeId"]
    node = page.cmd("DOM.querySelector", {"nodeId": doc, "selector": selector})["nodeId"]
    try:
        page.cmd("DOM.focus", {"nodeId": node})
    except RuntimeError:
        return False   # not focusable: the field isn't on screen
    page.cmd("Input.insertText", {"text": text})
    for kind in ("keyDown", "keyUp"):
        page.cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                            **({"text": "\r"} if kind == "keyDown" else {})})
    page.b.pump(2)
    return True


def check_abuse(browser):
    """The report leaves without the link's key unless the box is ticked; the proof of work is the app's.
    Without JavaScript, or before abuse.js runs, the form can't be seen or sent, so the browser never
    submits it by itself with the key in the URL (review H1)."""
    problems = []
    with server() as origin:
        for include in (False, True):
            page = browser.page()
            page.goto(origin + "/abuse")
            page.eval(f"document.getElementById('abuse-link').value = '{origin}/s/AAAAAAAAAAAAAAAAAAAAAA#1SECRET'")
            page.eval(f"document.getElementById('abuse-key').checked = {str(include).lower()}")
            page.eval("document.querySelector('[data-abuse] [type=submit]').click()")
            if not page.wait_for("document.getElementById('abuse-status').textContent.startsWith('Thanks.')", 20):
                problems.append(f"report (key {include}): {page.eval('document.getElementById(\"abuse-status\").textContent')!r}")
                continue
            body = json.loads(next(b for u, b in page.posts() if u.endswith("/api/v1/abuse")))
            if ("#1SECRET" in body["link"]) != include or not body.get("pow", {}).get("nonce"):
                problems.append(f"report (key {include}) sent {body['link']!r}")
        link = f"{origin}/s/AAAAAAAAAAAAAAAAAAAAAA#2SECRET"
        page = browser.page()
        page.cmd("Emulation.setScriptExecutionDisabled", {"value": True})
        page.goto(origin + "/abuse")
        typed = _type_and_enter(page, "#abuse-link", link)
        leaks = [r["url"] for r in page.requests() if "SECRET" in r["url"] or "%23" in r["url"]]
        if typed or leaks:
            problems.append(f"scripts off: the form takes input ({typed}) or a request carries the key: {leaks}")
        page = browser.page(block=["*/site/js/abuse.js"])
        page.goto(origin + "/abuse")
        typed = _type_and_enter(page, "#abuse-link", link)
        leaks = [r["url"] for r in page.requests() if "SECRET" in r["url"] or "%23" in r["url"]]
        if typed or leaks or "SECRET" in page.eval("location.href"):
            problems.append(f"abuse.js not loaded: the form takes input ({typed}) or the key left the page: {leaks}")
        # The app's "Report this link" opens /abuse#link=<the link without its key>: the field is filled
        # through cleanLink (our origins only, never a key) and the fragment leaves the address bar.
        for reported, expected in ((f"{origin}/d/0123456789", f"{origin}/d/0123456789"),
                                   (f"{origin}/s/AAAAAAAAAAAAAAAAAAAAAA#3SECRET", f"{origin}/s/AAAAAAAAAAAAAAAAAAAAAA"),
                                   ("https://elsewhere.example/s/AAAAAAAAAAAAAAAAAAAAAA", "")):
            page = browser.page()
            page.goto(origin + "/abuse#link=" + urllib.parse.quote(reported, safe=""), settle=1)
            field, hash_ = page.eval("[document.getElementById('abuse-link').value, location.hash]")
            if field != expected or hash_:
                problems.append(f"prefill {reported!r}: field {field!r}, fragment {hash_!r}")
    return problems


def check_reveal(browser):
    """P1 canary reveal: yesterday's test file opens in the browser with its published key (app format code)."""
    with server() as origin:
        page = browser.page()
        page.goto(origin + "/", settle=1.5)
        _scroll_through(page, "try")
        page.eval("document.querySelector('[data-reveal-open]').click()")
        ok = page.wait_for("document.querySelector('[data-reveal-out]').textContent.includes('mutis canary #788')", 15)
        out = page.eval("document.querySelector('[data-reveal-out]').textContent").split("\n")[0]
        missed = page.eval("(e => e.hidden ? '' : e.textContent)(document.querySelector('[data-reveal-missed]'))")
        NOTES.append(f"canary reveal: {out[:90]}; {missed}")
        problems = [] if ok else [f"reveal shows {out!r}"]
        if missed != "Test file #789: missed (the verifier restarted).":
            problems.append(f"a missed reveal reads {missed!r}")
        return problems


def check_interactions(browser):
    """Lights off persists across a reload; EN · ES points at this page's translation; the judge pass is
    validated, lower-cased and kept where the app reads it (localStorage 'mutis.judge' with its expiry, app-core
    store.js), and a /judges#pass=… link saves it on opening;
    the hero's line 2 steps aside while the widget's card shows (NOTES-ui, site 3)."""
    problems = []
    with server() as origin:
        page = browser.page()
        page.goto(origin + "/", settle=1)
        line2 = "document.querySelector('.hero-line2').hidden"
        page.eval("document.dispatchEvent(new CustomEvent('mutis:state', {detail: {state: 'sealed'}}))")
        sealed = page.eval(line2)
        page.eval("document.dispatchEvent(new CustomEvent('mutis:state', {detail: {state: 'idle'}}))")
        if not sealed or page.eval(line2):
            problems.append(f"hero line 2: hidden while sealed {sealed}, back on idle {not page.eval(line2)}")
        page = browser.page()
        page.goto(origin + "/how")
        page.eval("document.querySelector('[data-theme-toggle]').click()")
        page.goto(origin + "/how")
        if page.eval("document.documentElement.dataset.theme") != "dark":
            problems.append("Lights off didn't persist")
        if page.eval("document.querySelector('a[data-lang=\"es\"]').getAttribute('href')") != "/es/how":
            problems.append("ES link doesn't point at /es/how")
        page.goto(origin + "/judges")
        if page.eval("document.querySelector('[data-judge-pass]').hidden"):
            problems.append("the judge pass box stays hidden")
        page.eval("document.getElementById('judge-code').value = 'nope'; document.querySelector('[data-judge-pass] [type=submit]').click()")
        if "judge pass" not in page.eval("document.getElementById('judge-status').textContent"):
            problems.append("an invalid judge pass isn't refused")
        page.eval("document.getElementById('judge-code').value = ' JUDGE-0123456789ABCDEFGHJKMNPQ '; document.querySelector('[data-judge-pass] [type=submit]').click()")
        saved = "JSON.parse(localStorage.getItem('mutis.judge') || 'null')"
        if page.eval(f"{saved}?.code") != "judge-0123456789abcdefghjkmnpq":
            problems.append("a valid judge pass isn't saved for the app, lower-cased")
        if not page.eval(f"{saved}?.until > Date.now() + 6 * 86400000"):
            problems.append("the saved judge pass doesn't expire about a week on")
        page.goto(origin + "/judges")
        if page.eval("document.getElementById('judge-code').value") != "judge-0123456789abcdefghjkmnpq":
            problems.append("the saved judge pass isn't shown again on this device")
        page.goto(origin + "/judges#pass=judge-zzzzzzzzzzzzzzzzzzzzzzzz", settle=1)
        if page.eval(f"{saved}?.code") != "judge-zzzzzzzzzzzzzzzzzzzzzzzz" or page.eval("location.hash") != "":
            problems.append("a /judges#pass=… link doesn't save the pass and clear the hash")
    return problems


CHECKS = [("fonts load, no OTS error", check_fonts), ("every page, desktop and 360 px", check_pages),
          ("home page budget (M-01)", check_budget), ("live numbers and their failure (M-07)", check_live_numbers),
          ("the exit wall (M-02)", check_wall), ("the exit wall at 4x CPU on a phone", check_wall_frames),
          ("copy variants from /config", check_variants), ("status line phase (M-08)", check_phase),
          ("abuse form: key stripped, never sent without JavaScript", check_abuse),
          ("canary reveal (P1)", check_reveal), ("theme, language, judge pass", check_interactions)]


def run_all():
    results = []
    with Browser() as browser:
        for name, fn in CHECKS:
            try:
                results.append((name, fn(browser)))
            except Exception as e:   # a crashed check is a failed check, with its reason
                results.append((name, [f"{type(e).__name__}: {e}"]))
    return results

