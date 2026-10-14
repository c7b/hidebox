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
from pathlib import Path

import serve
from cdp import Browser

# The six pages of the ghost (14-ghost-design §4.1); the old ones are 301s (deploy/caddy/Caddyfile).
ALL_PAGES = ["/", "/how", "/made", "/judges", "/fine-print", "/no-such-page"]
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
    """DESIGN.md: system faces only. No page asks for a font file, none is registered, no OTS error."""
    problems = []
    with server() as origin:
        for path in ("/", "/how"):
            page = browser.page()
            page.goto(origin + path, settle=1)
            fonts = page.eval("[...document.fonts].map((f) => f.family)")
            files = [r["url"] for r in page.requests() if r["url"].endswith((".woff2", ".woff", ".ttf", ".otf"))]
            problems += [f"{path}: font face {f}" for f in fonts] + [f"{path}: requested {u}" for u in files]
            problems += [f"{path}: {line}" for line in page.console() if "OTS" in line]
        NOTES.append(f"fonts: none registered or requested on / and /how ({len(problems)} problems)")
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
    """M-07: numbers come from /config, /stats, /canary, /evidence.json and /status.json, and disappear when
    those fail. They live on /made since the ghost (the limits table, the status line, the test file)."""
    problems = []
    blocks = ("[data-canary]", "[data-evidence]", "[data-status-line]")
    with server() as origin:
        page = browser.page(1440, 900)
        page.goto(origin + "/made", settle=2.5)
        _scroll_through(page, "check", "limits")
        text = page.eval("document.body.innerText")
        for expected in ("per locker", "Largest file", "budget for sponsor grants is used", "test deliveries"):
            if expected.lower() not in text.lower():
                problems.append(f"API up: {expected!r} not shown on /made")
        for sel in blocks:
            if page.eval(f"document.querySelector('{sel}').hidden"):
                problems.append(f"API up: {sel} stays hidden")
        page = browser.page(1440, 900, block=["*/api/*", "*/evidence.json", "*/status.json"])
        page.goto(origin + "/made", settle=2.5)
        _scroll_through(page, "check", "limits")
        if page.eval(VISIBLE_NEEDS) != 0:
            problems.append("API blocked: a [data-needs] block is still visible on /made")
        for sel in blocks:
            if not page.eval(f"document.querySelector('{sel}').hidden"):
                problems.append(f"API blocked: {sel} is visible")
        if page.eval("document.querySelector('[data-canary-missing]').hidden"):
            problems.append("API blocked: the 'between takes' line is hidden")
        NOTES.append(f"API blocked: /made hides {page.eval(HIDDEN_NEEDS)} [data-needs] blocks, shows {page.eval(VISIBLE_NEEDS)}")
    return problems


GO_TO = "document.getElementById('{}').offsetTop"


def _scroll_through(page, *ids):
    """Each section's code loads when it comes near, as a visitor scrolls down to it."""
    for section in ids:
        page.scroll_to(page.eval(GO_TO.format(section)), 1.2)


# Visible words: text nodes inside the page that a visitor can see (not clipped to 1 px, not hidden).
WORDS = """((foldOnly) => {
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let words = 0;
  for (let n; (n = walk.nextNode());) {
    const el = n.parentElement;
    if (!el || el.closest('script, style, template, [aria-hidden="true"], noscript')) continue;
    if (!el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    const r = range.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (foldOnly && (r.top >= innerHeight || r.bottom <= 0)) continue;
    words += (n.nodeValue.match(/[A-Za-z0-9\u00C0-\u024F'’™.#-]+/g) || []).filter((w) => /[A-Za-z0-9]/.test(w)).length;
  }
  return words;
})"""


def check_word_budget(browser):
    """16-drive-design §11 (the word budget of 14-ghost-design §4.4 kept): the home page says at most 120 words
    above the fold and 400 in all, on a phone (390 × 844) and a desktop (1440 × 900); Make my drive is the
    first thing to press in the page."""
    problems = []
    with server() as origin:
        for width, height, mobile in ((390, 844, True), (1440, 900, False)):
            page = browser.page(width, height, mobile=mobile)
            page.goto(origin + "/", settle=2)
            fold, total = page.eval(f"{WORDS}(true)"), page.eval(f"{WORDS}(false)")
            NOTES.append(f"home words at {width}: {fold} above the fold, {total} in all")
            if fold > 120:
                problems.append(f"home @{width}: {fold} words above the fold (at most 120)")
            if total > 400:
                problems.append(f"home @{width}: {total} words in all (at most 400)")
            first = page.eval("(() => { const b = [...document.querySelectorAll('main button, main a, main input, main textarea')]"
                              ".find((e) => e.checkVisibility() && e.getBoundingClientRect().width > 2); return b ? b.dataset.testid || b.id : ''; })()")
            if first != "home-make":
                problems.append(f"home @{width}: the first control in the page is {first!r}, not Make my drive")
    return problems


def check_variants(browser):
    """Copy variants follow /config: relay or direct sends, SealLog off or on, the payment proof."""
    problems = []
    probes = {"relay": "[data-when=\"send_mode=relay\"]", "direct": "[data-when=\"send_mode=direct\"]",
              "seallog": "[data-when=\"seallog=on\"]"}
    for args, shown, hidden in ((("--mode", "relay"), ["relay"], ["direct", "seallog"]),
                                (("--mode", "direct", "--seallog"), ["direct", "seallog"], ["relay"])):
        with server(*args) as origin:
            page = browser.page()
            page.goto(origin + "/made", settle=2)
            for key in shown:
                if page.eval(f"[...document.querySelectorAll('{probes[key]}')].some(e => e.hidden)"):
                    problems.append(f"{args}: a {key} variant stays hidden")
            for key in hidden:
                if page.eval(f"[...document.querySelectorAll('{probes[key]}')].some(e => !e.hasAttribute('hidden'))"):
                    problems.append(f"{args}: a {key} variant is shown")
            text = page.eval("document.body.innerText")
            proof = "the official Tari library opens" if "direct" in args else "our wallet sees it"
            if proof not in text:
                problems.append(f"{args}: /made doesn't say how this deployment checks a payment ({proof!r})")
            # review H2: the sponsor grant's on-chain linkage is disclosed where sends are explained
            if "direct" in args and "sponsor wallet" not in text:
                problems.append("direct mode: /made doesn't say sends link back to our sponsor wallet")
            page.goto(origin + "/judges", settle=1.5)
            pay = "Pay from my drive" if "direct" in args else "Pay with test money"
            if pay not in page.eval("document.body.innerText"):
                problems.append(f"{args}: /judges doesn't name this mode's way to pay ({pay})")
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
            page.goto(origin + "/fine-print")
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
        page.goto(origin + "/fine-print")
        typed = _type_and_enter(page, "#abuse-link", link)
        leaks = [r["url"] for r in page.requests() if "SECRET" in r["url"] or "%23" in r["url"]]
        if typed or leaks:
            problems.append(f"scripts off: the form takes input ({typed}) or a request carries the key: {leaks}")
        page = browser.page(block=["*/site/js/abuse.js"])
        page.goto(origin + "/fine-print")
        typed = _type_and_enter(page, "#abuse-link", link)
        leaks = [r["url"] for r in page.requests() if "SECRET" in r["url"] or "%23" in r["url"]]
        if typed or leaks or "SECRET" in page.eval("location.href"):
            problems.append(f"abuse.js not loaded: the form takes input ({typed}) or the key left the page: {leaks}")
        # The app's "Report this link" opens /fine-print#link=<the link without its key>: the field is filled
        # through cleanLink (our origins only, never a key) and the fragment leaves the address bar.
        for reported, expected in ((f"{origin}/d/0123456789", f"{origin}/d/0123456789"),
                                   (f"{origin}/s/AAAAAAAAAAAAAAAAAAAAAA#3SECRET", f"{origin}/s/AAAAAAAAAAAAAAAAAAAAAA"),
                                   ("https://elsewhere.example/s/AAAAAAAAAAAAAAAAAAAAAA", "")):
            page = browser.page()
            page.goto(origin + "/fine-print#link=" + urllib.parse.quote(reported, safe=""), settle=1)
            field, hash_ = page.eval("[document.getElementById('abuse-link').value, location.hash]")
            if field != expected or hash_:
                problems.append(f"prefill {reported!r}: field {field!r}, fragment {hash_!r}")
    return problems


def check_reveal(browser):
    """P1 canary reveal: yesterday's test file opens in the browser with its published key (app format code)."""
    with server() as origin:
        page = browser.page()
        page.goto(origin + "/made", settle=1.5)
        _scroll_through(page, "check", "try")
        page.eval("document.querySelector('[data-reveal-open]').click()")
        ok = page.wait_for("document.querySelector('[data-reveal-out]').textContent.includes('canary #788')", 15)
        out = page.eval("document.querySelector('[data-reveal-out]').textContent").split("\n")[0]
        missed = page.eval("(e => e.hidden ? '' : e.textContent)(document.querySelector('[data-reveal-missed]'))")
        NOTES.append(f"canary reveal: {out[:90]}; {missed}")
        problems = [] if ok else [f"reveal shows {out!r}"]
        if missed != "Test file #789: missed (the verifier restarted).":
            problems.append(f"a missed reveal reads {missed!r}")
        return problems


def check_interactions(browser):
    """The light switch: named "Lights", aria-pressed follows the theme, lights off persists across a
    reload; the judge pass is validated, lower-cased and kept where the app reads it (localStorage
    'mutis.judge' with its expiry, app-core store.js), and a /judges#pass=… link saves it on opening; the
    home's widget opens the note and comes back from it."""
    problems = []
    with server() as origin:
        # The drive's home (16-drive-design §11): the anonymous widget sits in its card; Or write one opens
        # the note and Cancel brings the zone back (the drop itself is the app's UI flow home-text).
        page = browser.page()
        page.goto(origin + "/", settle=1.5)
        page.eval("document.querySelector('[data-testid=\"drop-write\"]').click()")
        page.b.pump(0.3)
        wrote = page.eval("document.activeElement?.dataset?.testid")
        page.eval("[...document.querySelectorAll('.md-compose button')].find((b) => b.textContent === 'Cancel').click()")
        page.b.pump(0.3)
        back = page.eval("!!document.querySelector('[data-testid=\"drop-write\"]')")
        if (wrote, back) != ("drop-textarea", True):
            problems.append(f"the home's widget: Or write one focuses the note ({wrote}); Cancel brings the zone back ({back})")
        page = browser.page()
        page.goto(origin + "/how")
        switch = "document.querySelector('[data-theme-toggle]')"
        label, before = page.eval(f"[{switch}.getAttribute('aria-label'), {switch}.getAttribute('aria-pressed')]")
        page.eval(f"{switch}.click()")
        after = page.eval(f"{switch}.getAttribute('aria-pressed')")
        if label != "Lights" or (before, after) != ("true", "false"):
            problems.append(f"the light switch: name {label!r}, pressed {before} then {after}")
        page.goto(origin + "/how")
        if page.eval("document.documentElement.dataset.theme") != "dark" or page.eval(f"{switch}.getAttribute('aria-pressed')") != "false":
            problems.append("Lights off didn't persist")
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


CHECKS = [("no web fonts (system faces only)", check_fonts), ("every page, desktop and 360 px", check_pages),
          ("home page budget (M-01)", check_budget), ("live numbers and their failure (M-07)", check_live_numbers),
          ("home words: 120 above the fold, 400 in all, Make my drive first", check_word_budget),
          ("copy variants from /config", check_variants), ("status line phase (M-08)", check_phase),
          ("abuse form: key stripped, never sent without JavaScript", check_abuse),
          ("canary reveal (P1)", check_reveal), ("theme, judge pass", check_interactions)]


def run_all():
    results = []
    with Browser() as browser:
        for name, fn in CHECKS:
            try:
                results.append((name, fn(browser)))
            except Exception as e:   # a crashed check is a failed check, with its reason
                results.append((name, [f"{type(e).__name__}: {e}"]))
    return results

