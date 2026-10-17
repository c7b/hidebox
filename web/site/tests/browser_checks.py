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
# /v2 (docs/review/home-v2.md) is the home with the product loops at its own, unlisted address.
ALL_PAGES = ["/", "/how", "/made", "/judges", "/fine-print", "/no-such-page", "/v2"]
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
    """DESIGN.md: one family, Geist, pinned. The home asks for its pinned Latin subset (17-site-brief §1.2) and
    nothing else; a reading page asks for the one pinned Geist file and nothing else. No OTS error."""
    problems = []
    with server() as origin:
        for path, want in (("/", ["/shared/fonts/geist/Geist-Latin.woff2"]), ("/how", ["/shared/fonts/geist/Geist-Variable.woff2"])):
            page = browser.page()
            page.goto(origin + path, settle=1)
            page.eval("document.fonts.ready.then(() => true)", True)
            fonts = page.eval("[...document.fonts].map((f) => f.family.replace(/\"/g, ''))")
            files = [r["url"].replace(origin, "") for r in page.requests() if r["url"].endswith((".woff2", ".woff", ".ttf", ".otf"))]
            problems += [f"{path}: font face {f}" for f in fonts if f != "Geist"]
            if sorted(set(files)) != want:
                problems.append(f"{path}: font files {files}, expected {want}")
            problems += [f"{path}: {line}" for line in page.console() if "OTS" in line]
        NOTES.append(f"fonts: the pinned Geist subset on /, the pinned Geist on /how ({len(problems)} problems)")
    return problems


def check_pages(browser):
    """Every page on a 1440 desktop and on 390 and 360 phones: no errors, no CSP violation, no sideways scroll."""
    problems = []
    with server() as origin:
        for width, height, mobile in ((1440, 900, False), (390, 844, True), (360, 740, True)):
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
        for expected in ("per drive", "Largest file", "budget for sponsor grants is used", "test deliveries"):
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


# Site v2 (17-site-brief §3) adds the comparison, the four sides of a file and What's tTARI? to the home, at
# the owner's request; the fold keeps 14-ghost-design §4.4's 120 words, the whole page gets 800 (689 measured
# at 1440 with pay to open off, the fixture's default).
FOLD_WORDS, HOME_WORDS = 120, 800


def check_word_budget(browser):
    """The home page says at most 120 words above the fold and 800 in all, on a phone (390 × 844) and a
    desktop (1440 × 900); Open your drive is the first thing to press in the page."""
    problems = []
    with server() as origin:
        for width, height, mobile in ((390, 844, True), (1440, 900, False)):
            # with reduced motion, so the words that wait below the fold for their reveal (site v3) count too
            page = browser.page(width, height, mobile=mobile, reduce=True)
            page.goto(origin + "/", settle=2)
            fold, total = page.eval(f"{WORDS}(true)"), page.eval(f"{WORDS}(false)")
            NOTES.append(f"home words at {width}: {fold} above the fold, {total} in all")
            if fold > FOLD_WORDS:
                problems.append(f"home @{width}: {fold} words above the fold (at most {FOLD_WORDS})")
            if total > HOME_WORDS:
                problems.append(f"home @{width}: {total} words in all (at most {HOME_WORDS})")
            first = page.eval("(() => { const b = [...document.querySelectorAll('main button, main a, main input, main textarea')]"
                              ".find((e) => e.checkVisibility() && e.getBoundingClientRect().width > 2); return b ? b.dataset.testid || b.id : ''; })()")
            if first != "home-make":
                problems.append(f"home @{width}: the first control in the page is {first!r}, not Open your drive")
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


FIELD = "document.querySelector('[data-field]')"
FIELD_TIMES = """(() => { const r = performance.getEntriesByType('resource').find((e) => e.name.endsWith('/site/js/field.js'));
  const n = performance.getEntriesByType('navigation')[0]; return r ? [r.startTime, n.loadEventEnd] : null; })()"""


def check_field(browser):
    """A-06h (17-site-brief §1.2), the loading half: on the home, field.js is requested after the load event,
    its canvas fades in over the static grid and ripples start from Open your drive (desktop and phone); with
    reduced motion it is never requested and the static grid stays; no other page asks for it."""
    problems = []
    with server() as origin:
        for width, height, mobile in ((1440, 900, False), (390, 844, True)):
            page = browser.page(width, height, mobile=mobile)
            page.goto(origin + "/", settle=0.2)
            rippled = page.wait_for(f"{FIELD}.dataset.ripples >= 1 && {FIELD}.classList.contains('live')", 10)
            times = page.eval(FIELD_TIMES)
            if not times:
                problems.append(f"/ @{width}: field.js never requested")
            elif times[0] < times[1]:
                problems.append(f"/ @{width}: field.js requested at {times[0]:.0f} ms, before the load event ended ({times[1]:.0f} ms)")
            if not rippled:
                problems.append(f"/ @{width}: no ripple, or the canvas never took over from the static grid")
            # the button's own ripple: the pointer entering it starts one at once (at most one per 1.5 s)
            page.b.pump(1.6)
            before = int(page.eval(f"{FIELD}.dataset.ripples") or 0)
            page.eval("document.querySelector('[data-testid=\"home-make\"]').dispatchEvent(new PointerEvent('pointerenter'))")
            if int(page.eval(f"{FIELD}.dataset.ripples") or 0) != before + 1:
                problems.append(f"/ @{width}: the pointer entering Open your drive started no ripple")
            NOTES.append(f"A-06h @{width}: field.js at {times[0]:.0f} ms, load event ended {times[1]:.0f} ms; "
                         f"{page.eval(FIELD + '.dataset.ripples')} ripples" if times else f"A-06h @{width}: no field")
        page = browser.page(1440, 900, reduce=True)
        page.goto(origin + "/", settle=4)
        if page.eval(FIELD_TIMES) or page.eval(f"!!{FIELD}.querySelector('canvas')"):
            problems.append("reduced motion: field.js was requested")
        if page.eval(f"getComputedStyle({FIELD}, '::before').opacity") != "1":
            problems.append("reduced motion: the static grid isn't shown")
        page = browser.page(1440, 900)
        page.goto(origin + "/how", settle=3)
        if page.eval(FIELD_TIMES):
            problems.append("/how asked for field.js")
    return problems


SHOWN = "(t) => { const e = document.querySelector(`[data-testid=\"${t}\"]`); const s = getComputedStyle(e); return s.display !== 'none' && s.visibility === 'visible'; }"


def check_header(browser):
    """Site v3 (docs/review/site-v3.md): the header's Open your drive is always on, on the home at the top, in the
    middle and at the end, and on every other page; one label, two targets: /drive?make without a drive, /drive with
    one (and the hero's one button follows, in the brand fill). The drive is detected by counting the drive's key
    record, never creating its database."""
    problems = []
    with server() as origin:
        page = browser.page(1440, 900)
        page.goto(origin + "/", settle=1.5)
        shown = lambda t: page.eval(f"({SHOWN})('{t}')")
        label = lambda t: page.eval(f"document.querySelector('[data-testid=\"{t}\"]').textContent.trim()")
        for where in ("top", "who", "end"):
            if where == "who":
                page.scroll_to(page.eval("document.getElementById('who').offsetTop"), 0.8)
            elif where == "end":
                page.scroll_to(page.eval("document.documentElement.scrollHeight"), 0.8)
            if not shown("head-make") or shown("head-open") or label("head-make") != "Open your drive":
                problems.append(f"/ ({where}): the header doesn't show Open your drive (to /drive?make), and only it")
        if page.eval("[...document.querySelectorAll('main a, header a')].some((a) => /Make my drive/.test(a.textContent))"):
            problems.append("/: a link still says Make my drive")
        if page.eval("indexedDB.databases().then((l) => l.some((d) => d.name === 'mutis'))", True):
            problems.append("/: a visit without a drive created the drive's database")
        page.goto(origin + "/judges", settle=1)
        if not shown("head-make") or shown("head-open"):
            problems.append("/judges: the header doesn't show Open your drive (and only it)")
        # a drive in this browser: the drive's record exists, so Open your drive goes to /drive
        page.eval("""new Promise((ok) => { const r = indexedDB.open('mutis', 1);
          r.onupgradeneeded = () => { r.result.createObjectStore('identity'); r.result.createObjectStore('inbox'); };
          r.onsuccess = () => { const tx = r.result.transaction('identity', 'readwrite'); tx.objectStore('identity').put({ v: 2 }, 'current');
            tx.oncomplete = () => { r.result.close(); ok(true); }; }; })""", True)
        page.goto(origin + "/judges", settle=1.5)
        if not shown("head-open") or shown("head-make") or label("head-open") != "Open your drive":
            problems.append("/judges with a drive: the header's Open your drive doesn't go to /drive")
        if page.eval("localStorage.getItem('mutis.drive')") != "1":
            problems.append("/judges with a drive: the flag theme.js paints from isn't kept")
        page.goto(origin + "/", settle=1.5)
        hero = page.eval("""[...document.querySelectorAll('.hero .cta-row a')].filter((a) => a.checkVisibility())
          .map((a) => [a.dataset.testid, a.textContent.trim(), getComputedStyle(a).backgroundColor !== 'rgba(0, 0, 0, 0)'])""")
        if hero != [["home-open", "Open your drive", True]]:
            problems.append(f"/ with a drive: the hero's one button isn't Open your drive to /drive?open in the brand fill ({hero})")
        page.eval("""new Promise((ok) => { const r = indexedDB.open('mutis'); r.onsuccess = () => { const tx = r.result.transaction('identity', 'readwrite');
          tx.objectStore('identity').delete('current'); tx.oncomplete = () => { r.result.close(); ok(true); }; }; })""", True)
        page.goto(origin + "/how", settle=1.5)
        if page.eval("document.documentElement.hasAttribute('data-has-drive') || localStorage.getItem('mutis.drive') !== null"):
            problems.append("/how after the drive was deleted: still goes to the drive")
        if page.eval("document.querySelector('.top-nav a[aria-current=\"page\"]')?.getAttribute('href')") != "/how":
            problems.append("/how: the header doesn't mark How it works as the page you're on")
    return problems


LOADED = "(n) => { const r = performance.getEntriesByType('resource').find((e) => e.name.endsWith('/site/js/' + n)); return r ? r.startTime : null; }"
HIDDEN = "document.querySelectorAll('.mo-h:not(.mo-in), .dc-c:not(.dc-ok), .mo-w').length"
SLICE = "document.querySelector('.hero .slice').innerHTML"


def check_motion(browser):
    """Site v3 (docs/review/site-v3.md): motion.js and pixel.js load after the load event, only where asked for;
    things below the fold wait unseen and arrive as they scroll in, and once a page has been scrolled through
    nothing is left hidden; the hero's picture decodes behind an aria-hidden layer and ends with the same DOM it
    started with; the pixel field draws only while on screen. With reduced motion neither file loads and every
    word shows at once; without JavaScript every word shows."""
    problems = []
    with server() as origin:
        quiet = browser.page(1440, 900, reduce=True)
        quiet.goto(origin + "/", settle=3)
        still = quiet.eval(SLICE)
        for n in ("motion.js", "pixel.js"):
            if quiet.eval(f"({LOADED})('{n}')") is not None:
                problems.append(f"reduced motion: {n} was requested")
        _scroll_through(quiet, "who")
        if quiet.eval("document.querySelectorAll('.mo-h, .dc-c, .dc-layer, .px-field canvas').length"):
            problems.append("reduced motion: something waits to be revealed")
        if quiet.eval("getComputedStyle(document.querySelector('.hero .slice .name')).opacity") != "1":
            problems.append("reduced motion: the picture's words aren't shown at once")
        for width, height, mobile in ((1440, 900, False), (390, 844, True)):
            page = browser.page(width, height, mobile=mobile)
            page.goto(origin + "/", settle=0.1)
            mid = page.wait_for("!!document.querySelector('.hero .slice .dc-layer')", 6)
            if not mid and width == 1440:
                problems.append(f"/ @{width}: the picture never decoded")
            elif mid and page.eval("document.querySelector('.dc-layer').getAttribute('aria-hidden')") != "true":
                problems.append(f"/ @{width}: the decode's noise isn't hidden from screen readers")
            if mid and "passport-scan.pdf" not in page.eval("document.querySelector('.hero .slice').textContent"):
                problems.append(f"/ @{width}: the picture's real words left the page while it decoded")
            times = page.eval(f"[({LOADED})('motion.js'), performance.getEntriesByType('navigation')[0].loadEventEnd]")
            if times[0] is None or times[0] < times[1]:
                problems.append(f"/ @{width}: motion.js requested at {times[0]} ms, before the load event ended ({times[1]:.0f} ms)")
            if page.eval(f"({LOADED})('pixel.js')") is not None:
                problems.append(f"/ @{width}: pixel.js was requested before the closing came near")
            step = height * 0.6
            for y in range(0, int(page.eval("document.documentElement.scrollHeight")) + int(step), int(step)):
                page.scroll_to(y, 0.25)
            page.b.pump(1.5)
            left = page.eval(HIDDEN)
            if left:
                problems.append(f"/ @{width}: {left} things still hidden after scrolling through")
            if page.eval(SLICE) != still:
                problems.append(f"/ @{width}: the picture's DOM after the decode differs from the page's")
            live = page.wait_for("document.querySelector('[data-pixel]').classList.contains('live')", 5)
            if not live:
                problems.append(f"/ @{width}: the pixel field never took over from the CSS pixels")
            else:
                a = page.eval("document.querySelector('[data-pixel]').frames")
                page.b.pump(0.5)
                if page.eval("document.querySelector('[data-pixel]').frames") <= a:
                    problems.append(f"/ @{width}: the pixel field doesn't move while on screen")
                page.scroll_to(0, 0.6)
                a = page.eval("document.querySelector('[data-pixel]').frames")
                page.b.pump(0.6)
                if page.eval("document.querySelector('[data-pixel]').frames") != a:
                    problems.append(f"/ @{width}: the pixel field keeps drawing off screen")
            NOTES.append(f"motion @{width}: motion.js at {times[0]:.0f} ms (load event {times[1]:.0f} ms), decode seen: {bool(mid)}, "
                         f"pixel field live: {live}" if times[0] is not None else f"motion @{width}: no motion.js")
        for path in ("/how", "/judges"):
            page = browser.page(1440, 900)
            page.goto(origin + path, settle=1.5)
            if page.eval(f"({LOADED})('motion.js')") is None:
                problems.append(f"{path}: motion.js never loaded")
            if page.eval(f"({LOADED})('pixel.js')") is not None:
                problems.append(f"{path}: pixel.js was requested")
            for y in range(0, int(page.eval("document.documentElement.scrollHeight")) + 540, 540):
                page.scroll_to(y, 0.25)
            page.b.pump(1.5)
            if page.eval(HIDDEN):
                problems.append(f"{path}: {page.eval(HIDDEN)} things still hidden after scrolling through")
        for path in ("/fine-print", "/made"):
            page = browser.page(1440, 900)
            page.goto(origin + path, settle=1.5)
            if page.eval(f"({LOADED})('motion.js')") is not None:
                problems.append(f"{path}: motion.js loaded where nothing asks for it")
        page = browser.page(390, 844, mobile=True)
        page.cmd("Emulation.setScriptExecutionDisabled", {"value": True})
        page.goto(origin + "/", settle=1.5)
        page.scroll_to(page.eval("document.documentElement.scrollHeight"), 0.5)
        hidden = page.eval("""[...document.querySelectorAll('main h1, main h2, main p, main li, main td, main .badge')]
          .filter((e) => e.checkVisibility() && getComputedStyle(e).opacity !== '1').length""")
        if hidden:
            problems.append(f"no JavaScript: {hidden} words on / are not fully shown")
    return problems


# V-01 (docs/review/home-v2.md), the loading half: what /v2 may fetch before anyone scrolls (the page, the drop
# widget's first load and the hero's loop with its poster) and after scrolling through every loop. The test server
# caches nothing, so the closing's loop (the hero's file again) is fetched twice here; production's Caddy lets the
# browser keep it for a day.
V2_AT_LOAD, V2_AT_LOAD_WEBKIT, V2_SCROLLED = 3 * 1024 * 1024, 1024 * 1024, 14 * 1024 * 1024
V2_CLIPS = ("hidebox-A-hero", "hidebox-B-sides", "hidebox-C-encrypt", "hidebox-D-pay")
V2_STATE = """[...document.querySelectorAll('video[data-clip]')].map((v) => { const r = v.getBoundingClientRect();
  return { stage: v.parentElement.classList[1], live: !!v.dataset.live, src: v.currentSrc.split('/').pop(), paused: v.paused,
           t: v.currentTime, poster: (v.getAttribute('poster') || '').split('/').pop(), out: r.bottom <= 0 || r.top >= innerHeight,
           whole: r.top >= 0 && r.bottom <= innerHeight }; })"""
NO_THEME = "try { localStorage.removeItem('mutis.theme'); localStorage.removeItem('mutis.loops'); } catch (e) {}"


def _v2_page(browser, *, light=False, **kw):
    page = browser.page(**kw)
    page.cmd("Page.addScriptToEvaluateOnNewDocument",
             {"source": NO_THEME + (" try { localStorage.setItem('mutis.theme', 'light'); } catch (e) {}" if light else "")})
    return page


def _v2_files(page, ext=(".webm", ".mp4", ".png")):
    return sorted({r["url"].rsplit("/", 1)[-1] for r in page.requests() if "/site/media/" in r["url"] and r["url"].endswith(ext)})


def check_v2(browser):
    """V-01, /v2: dark first; at load only the hero's loop and its poster are asked for (no other loop, no other
    poster) and the hero plays; scrolling down, each loop is asked for as it comes near and plays only while on
    screen, every one playing once wholly in view; the bytes stay in V-01. Reduced motion: posters only, nothing
    plays. WebKit (an iPhone's Safari): the MP4s, never a WebM, its stage without light (a black card in light mode).
    Light mode: every loop on a dark stage. Pause motion (WCAG 2.2.2) stops every loop, asks for no more of them and
    is remembered; pressed again, the loops in view play. No console error and no CSP violation."""
    problems = []
    with server("--mode", "direct", "--seallog", "--pay") as origin:
        for width, height, mobile in ((1440, 900, False), (390, 844, True)):
            page = _v2_page(browser, width=width, height=height, mobile=mobile, android=mobile)
            page.goto(origin + "/v2", settle=2.5)
            at = f"/v2 @{width}"
            if page.eval("document.documentElement.dataset.theme") != "dark" or \
                    page.eval("getComputedStyle(document.body).backgroundColor") != "rgb(10, 10, 10)":
                problems.append(f"{at}: not dark first")
            files = _v2_files(page)
            if files != ["hidebox-A-hero.webm", "hidebox-A-hero_poster.png"]:
                problems.append(f"{at}: at load asked for {files}, expected the hero's WebM and poster only")
            if not page.wait_for("(() => { const v = document.querySelector('.stage-a video'); return v.currentTime > .5 && !v.paused; })()", 12):
                problems.append(f"{at}: the hero's loop doesn't play")
            loaded = sum(r["bytes"] for r in page.requests())
            if loaded > V2_AT_LOAD:
                problems.append(f"{at}: {loaded:,} B at load (V-01: at most {V2_AT_LOAD:,})")
            step = height * 0.5
            for y in range(0, int(page.eval("document.documentElement.scrollHeight")) + int(step), int(step)):
                page.scroll_to(y, 0.4)
                for i, c in enumerate(page.eval(V2_STATE)):
                    if c["out"] and not c["paused"]:
                        problems.append(f"{at} y={y}: {c['stage']} plays off screen")
                    if c["whole"] and not page.wait_for(f"!document.querySelectorAll('video[data-clip]')[{i}].paused", 6):
                        problems.append(f"{at} y={y}: {c['stage']} is wholly on screen and doesn't play")
            files = _v2_files(page)
            want = sorted(f"{c}.webm" for c in V2_CLIPS) + sorted(f"{c}_poster.png" for c in V2_CLIPS)
            if sorted(files) != sorted(want):
                problems.append(f"{at}: after scrolling asked for {files}")
            scrolled = sum(r["bytes"] for r in page.requests())
            if scrolled > V2_SCROLLED:
                problems.append(f"{at}: {scrolled:,} B after scrolling through (V-01: at most {V2_SCROLLED:,})")
            problems += [f"{at}: {e}" for e in real_errors(page) + [l for l in page.console() if "Content Security Policy" in l]]
            NOTES.append(f"V-01 /v2 @{width}: {loaded:,} B at load (the hero's loop and poster), {scrolled:,} B after "
                         f"scrolling through, uncached")
        quiet = _v2_page(browser, width=1440, height=900, reduce=True)
        quiet.goto(origin + "/v2", settle=2.5)
        for y in range(0, int(quiet.eval("document.documentElement.scrollHeight")) + 450, 450):
            quiet.scroll_to(y, 0.3)
        quiet.b.pump(1.0)
        state = quiet.eval(V2_STATE)
        if _v2_files(quiet, (".webm", ".mp4")):
            problems.append(f"reduced motion: asked for {_v2_files(quiet, ('.webm', '.mp4'))}")
        if any(c["live"] or not c["paused"] or c["t"] or not c["poster"] for c in state):
            problems.append(f"reduced motion: a loop isn't its still poster: {state}")
        iphone = _v2_page(browser, width=390, height=844, mobile=True)
        iphone.goto(origin + "/v2", settle=2.5)
        if not iphone.wait_for("document.querySelector('.stage-a video').currentSrc.endsWith('.mp4')", 8):
            problems.append("WebKit: the hero isn't the MP4")
        if _v2_files(iphone, (".webm",)) or not iphone.eval("document.querySelector('.stage-a').classList.contains('is-opaque')"):
            problems.append(f"WebKit: asked for {_v2_files(iphone)} or the stage isn't black under the MP4")
        if sum(r["bytes"] for r in iphone.requests()) > V2_AT_LOAD_WEBKIT:
            problems.append(f"WebKit: {sum(r['bytes'] for r in iphone.requests()):,} B at load (V-01: at most {V2_AT_LOAD_WEBKIT:,})")
        lit = _v2_page(browser, light=True, width=390, height=844, mobile=True)
        lit.goto(origin + "/v2", settle=2.5)
        lit.wait_for("document.querySelector('.stage-a').classList.contains('is-opaque')", 8)
        card = lit.eval("(() => { const s = getComputedStyle(document.querySelector('.stage-a')); return [s.backgroundColor, s.backgroundImage]; })()")
        if card != ["rgb(0, 0, 0)", "none"]:
            problems.append(f"WebKit, light mode: the MP4's stage is {card}, not its black")
        loops = browser.page(1440, 900)   # no init script: the stored choice must survive a reload
        loops.goto(origin + "/v2", settle=0.5)
        loops.eval("localStorage.removeItem('mutis.loops'); localStorage.removeItem('mutis.theme')")
        loops.goto(origin + "/v2", settle=2.5)
        loops.wait_for("!document.querySelector('.stage-a video').paused", 8)
        switch = "document.querySelector('[data-loops]')"
        if loops.eval(f"{switch}.hidden") or loops.eval(f"{switch}.getAttribute('aria-pressed')") != "false":
            problems.append("Pause motion: the switch isn't shown, unpressed, with motion allowed")
        loops.eval(f"{switch}.click()")
        loops.b.pump(0.5)
        if loops.eval(f"{switch}.getAttribute('aria-pressed')") != "true" or \
                not loops.eval("[...document.querySelectorAll('video[data-clip]')].every((v) => v.paused)"):
            problems.append("Pause motion: pressed, a loop still plays")
        before = _v2_files(loops, (".webm", ".mp4"))
        for y in range(0, int(loops.eval("document.documentElement.scrollHeight")) + 450, 450):
            loops.scroll_to(y, 0.3)
        if _v2_files(loops, (".webm", ".mp4")) != before or \
                not loops.eval("[...document.querySelectorAll('video[data-clip]')].every((v) => v.paused)"):
            problems.append(f"Pause motion: scrolling while paused asked for {_v2_files(loops)} or played a loop")
        loops.goto(origin + "/v2", settle=2.5)
        if loops.eval(f"{switch}.getAttribute('aria-pressed')") != "true" or not loops.eval("document.querySelector('.stage-a video').paused") \
                or _v2_files(loops, (".webm", ".mp4")):
            problems.append("Pause motion: not remembered on the next visit (the loops played or were fetched)")
        loops.eval(f"{switch}.click()")
        if not loops.wait_for("!document.querySelector('.stage-a video').paused", 8):
            problems.append("Pause motion: pressed again, the hero's loop doesn't play")
        loops.eval("localStorage.removeItem('mutis.loops')")
        if quiet.eval("!document.querySelector('[data-loops]').hidden"):
            problems.append("reduced motion: the Pause motion switch shows (nothing moves)")
        light = _v2_page(browser, light=True, width=1440, height=900)
        light.goto(origin + "/v2", settle=1.5)
        stages = light.eval("[...document.querySelectorAll('.stage')].map((s) => getComputedStyle(s).backgroundImage)")
        if light.eval("document.documentElement.dataset.theme") != "light" or not stages or any("gradient" not in s for s in stages):
            problems.append(f"light mode: a loop without its dark stage: {stages}")
    return problems


CHECKS = [("fonts: the pinned Geist subset on the home, pinned Geist on reading pages", check_fonts), ("every page, desktop, 390 and 360 px", check_pages),
          ("home page budget (M-01)", check_budget), ("live numbers and their failure (M-07)", check_live_numbers),
          ("home words: 120 above the fold, 800 in all, Open your drive first", check_word_budget),
          ("A-06h: the field loads after the load event, ripples, never with reduced motion", check_field),
          ("header: Open your drive always on, to /drive?make or /drive", check_header),
          ("motion: reveals, the decode, the pixel field; reduced motion and no JavaScript", check_motion),
          ("copy variants from /config", check_variants), ("status line phase (M-08)", check_phase),
          ("abuse form: key stripped, never sent without JavaScript", check_abuse),
          ("canary reveal (P1)", check_reveal), ("theme, judge pass", check_interactions),
          ("V-01: /v2's loops, asked for as they come near, playing only on screen; reduced motion, WebKit, light", check_v2)]


def run_all():
    results = []
    with Browser() as browser:
        for name, fn in CHECKS:
            try:
                results.append((name, fn(browser)))
            except Exception as e:   # a crashed check is a failed check, with its reason
                results.append((name, [f"{type(e).__name__}: {e}"]))
    return results

