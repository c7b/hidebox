# SPDX-License-Identifier: MIT
"""The file preview (docs/review/preview-1.md): one lightbox (ui/lightbox.js) for the drive's file names, a folder
link's files, a paid file once it opens, a single-file link (/s/) and a single file in Received, against the real API
in headless Chromium.

Every file is a hostile fixture from web/app/tests/fixtures/preview (make_fixtures.py): a script that ran would set
the global canary `top.__pwned`, write `__pwned` to localStorage and ask for /__canary/<which>. Each flow checks,
for every file: the kind the lightbox chose is the one the bytes say (never the name), the canary is untouched,
nothing asked for /__canary/, no page navigated or opened a window, no console error, and Download saves the same
bytes. run.py adds the CSP and Trusted Types check for every page.

With MUTIS_PREVIEW_SHOTS=<dir> in the environment the flows also write their screenshots there (WebP,
<where>-<width>-<what>[-dark].webp); docs/evidence/2026-10-19/preview-1/ holds the ones in the review."""
import json
import os
import re
import shutil

from flows import VIEW_ASK, VIEW_END, downloaded, home, no_hscroll, open_link, scenario, wait_link
from flows_drive import make_drive, upload_files
from flows_pay import PAY_LINK, PayFake, buyer, seller, sell, wait_pay
from flows_share import close_dialog, drive_page, into, make_link, new_folder, open_share, stranger, to_opens

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "fixtures", "preview")

# name -> (the kind the bytes say, its type or why). The names lie on purpose.
HOSTILE = {
    "script.svg": ("svg", None),
    "svg-named.png": ("svg", None),
    "png-named.svg": ("image", "image/png"),
    "notes.md": ("text", None),
    "page.txt": ("none", "markup"),
    "polyglot.htm": ("image", "image/gif"),
    "big.txt": ("text", None),
    "empty.txt": ("none", "empty"),
    "utf16.txt": ("none", "binary"),
    "tiny.pdf": ("none", "pdf"),
}

# The drive refuses an empty file before it locks anything ("That file is empty."), so empty.txt can't reach a
# drive or a link; the core suite (web/app/tests/preview.test.js) shows the lightbox's answer for it.
STORED = [n for n in HOSTILE if n != "empty.txt"]

# Before the page's own scripts: counts window.open calls (none expected).
GUARD = "window.__opens = 0; { const o = window.open; window.open = function (...a) { window.__opens++; return o.apply(this, a); }; }"
CANARY = """(() => { let stored = null; try { stored = localStorage.getItem('__pwned'); } catch { /* blocked */ }
  return { pwned: window.__pwned ?? null, stored, opens: window.__opens ?? 0, href: location.href }; })()"""
STAGE = "document.querySelector('#lightbox [data-testid=\"lightbox-stage\"]')"


def stock(t):
    for name in HOSTILE:
        shutil.copy(os.path.join(FIXTURES, name), t.fixture(name))


def upload(t, page, names):
    """upload_files, and when a name never shows up: which ones, and what the upload panel says."""
    try:
        upload_files(t, page, names)
    except TimeoutError:
        listed = page.eval("[...document.querySelectorAll('[data-testid=\"file-row\"]')].map((e) => e.dataset.name)")
        panel = page.eval("document.querySelector('[data-testid=\"upload-panel\"]')?.innerText ?? ''")
        raise AssertionError(f"not listed: {sorted(set(names) - set(listed))}; the upload panel: {panel[:600]!r}") from None


def fixture_bytes(t, name):
    with open(t.fixture(name), "rb") as f:
        return f.read()


def shot(t, page, name, dark=False):
    folder = os.environ.get("MUTIS_PREVIEW_SHOTS")
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    if dark:
        page.eval("document.documentElement.dataset.theme = 'dark'")
    page.settle()
    page.screenshot(os.path.join(folder, f"{name}{'-dark' if dark else ''}.webp"))
    if dark:
        page.eval("delete document.documentElement.dataset.theme")


def watch(page):
    """Counts the page's top-level navigations from now on, and guards window.open in documents to come."""
    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": GUARD})
    page.eval(GUARD)
    nav = {"n": 0}
    page.on("Page.frameNavigated", lambda p: None if p["frame"].get("parentId") else nav.__setitem__("n", nav["n"] + 1))
    return nav


def shown(page, name, timeout=60):
    """Waits until the lightbox shows `name` (not loading) -> {kind, why, type, view}."""
    page.wait(f"(() => {{ const s = {STAGE}; return !!s && s.dataset.view !== 'loading'"
              f" && document.querySelector('#lightbox [data-testid=\"lightbox-name\"]')?.textContent === {json.dumps(name)}; }})()", timeout)
    page.b.drain(0.4)   # an <img> decodes or fails; anything that would run, runs
    return page.eval(f"""(() => {{ const s = {STAGE};
      return {{ kind: s.dataset.kind, view: s.dataset.view, why: s.querySelector('[data-testid="lightbox-none"]')?.dataset.why ?? null,
        type: s.querySelector('img')?.dataset.type ?? null, canvas: !!s.querySelector('canvas'),
        live: !!document.querySelector('#lightbox :is(script, iframe, object, embed, foreignObject), #lightbox img[src^="blob:"]:not([data-type])'),
        text: s.querySelector('pre')?.textContent ?? null, nodes: s.querySelector('pre')?.childNodes.length ?? null,
        more: !!s.querySelector('[data-testid="lightbox-more"]'), download: !document.querySelector('[data-testid="lightbox-download"]').disabled }}; }})()""")


def judge(t, page, name, got, nav, where):
    """The checks every hostile file gets, wherever it opened."""
    kind, extra = HOSTILE[name]
    t.check(got["kind"] == kind and (extra is None or extra in (got["type"], got["why"])),
            f"{where}: {name} is shown as its bytes say ({kind} {extra or ''}), not as its name says ({got['kind']} {got['type'] or got['why'] or ''})")
    if kind == "svg":
        t.check(got["canvas"] and not got["live"], f"{where}: {name}: drawn into a canvas, no live SVG, script, frame or object")
    if kind == "text":
        t.check(got["nodes"] == 1, f"{where}: {name}: one text node in the <pre>")
    if name == "notes.md":
        t.check("<script>" in got["text"] and "javascript:" in got["text"], f"{where}: notes.md: its markup and links read as characters")
    if name == "big.txt":
        t.check(got["more"] and len(got["text"]) == 256 * 1024, f"{where}: big.txt shows the first 256 KB and says so")
    c = page.eval(CANARY)
    t.check(c["pwned"] is None and c["stored"] is None and c["opens"] == 0 and nav["n"] == 0,
            f"{where}: {name}: nothing ran, nothing stored, no window, no navigation ({c}, {nav['n']} navigations)")
    t.check(got["download"], f"{where}: {name}: Download is there")


def canary_requests(page):
    return [r["url"] for r in page.requests if "/__canary/" in r["url"]]


def close(page):
    page.key("Escape")
    page.wait("!document.getElementById('lightbox')", 5)


# --- the drive: a file's name opens it ------------------------------------------------------------------

@scenario("preview-drive", "The preview in the drive: every hostile fixture by its name; the bytes pick the kind; nothing runs; "
          "Esc, focus back on the name, arrows through the list; Download saves the same bytes; phones and both themes", features=("folders",))
def preview_drive(t):
    stock(t)
    a, _ = make_drive(t)
    a.wait_for("drive-empty", 30)
    upload(t, a, STORED)
    a.set_files("upload-files-input", [t.fixture("empty.txt")])
    t.check(bool(a.wait("(document.querySelector('[data-testid=\"upload-panel\"]')?.textContent ?? '').includes('That file is empty.')", 30)),
            "drive: an empty file is refused before upload, so it never reaches a preview")
    nav = watch(a)
    a.errors.clear()
    order = a.eval("[...document.querySelectorAll('[data-testid=\"file-row\"]')].map((e) => e.dataset.name)")
    for name in order:
        a.eval(f"[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === {json.dumps(name)})"
               ".querySelector('[data-testid=\"file-open\"]').click()")
        got = shown(a, name)
        judge(t, a, name, got, nav, "drive")
        close(a)
        t.check(a.eval("document.activeElement?.closest('[data-testid=\"file-row\"]')?.dataset.name") == name,
                f"drive: {name}: Esc closes and focus is back on its name")
    t.check(canary_requests(a) == [], f"drive: nothing asked for /__canary/ ({canary_requests(a)[:3]})")
    t.check(a.errors == [], f"drive: no console error or exception ({a.errors[:3]})")

    # The keyboard: Enter on a name, arrows through the files as listed, focus trapped, Esc.
    a.eval(f"[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === {json.dumps(order[0])})"
           ".querySelector('[data-testid=\"file-open\"]').focus()")
    a.key("Enter", text="\r")
    shown(a, order[0])
    a.key("ArrowRight")
    t.check(shown(a, order[1])["kind"] == HOSTILE[order[1]][0], "ArrowRight: the next file in the list")
    a.key("ArrowLeft")
    a.key("ArrowLeft")
    t.check(shown(a, order[-1])["kind"] == HOSTILE[order[-1]][0], "ArrowLeft past the first: the last one")
    inside = []
    for _ in range(12):
        a.key("Tab")
        inside.append(a.eval("!!document.activeElement?.closest('#lightbox')"))
    t.check(all(inside), f"Tab stays inside the lightbox ({inside})")
    close(a)

    # Download: the same bytes, decrypted here; for text, a picture and a page alike.
    for name in ("big.txt", "polyglot.htm", "page.txt", "svg-named.png"):
        a.eval(f"[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === {json.dumps(name)})"
               ".querySelector('[data-testid=\"file-open\"]').click()")
        shown(a, name)
        before = os.listdir(a.downloads) if os.path.isdir(a.downloads) else []
        a.click("lightbox-download")
        got = downloaded(a, before, 30)
        t.check(got is not None and open(got, "rb").read() == fixture_bytes(t, name), f"Download in the lightbox saves {name}, the same bytes")
        close(a)
    c = a.eval(CANARY)
    t.check(c["href"].endswith("/drive") and nav["n"] == 0 and c["opens"] == 0, f"Download never navigates or opens a window ({c}, {nav['n']})")

    # Pictures of it, in both themes.
    for name, what in (("png-named.svg", "picture"), ("svg-named.png", "svg"), ("notes.md", "text"), ("big.txt", "text-cap"), ("page.txt", "none")):
        a.eval(f"[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === {json.dumps(name)})"
               ".querySelector('[data-testid=\"file-open\"]').click()")
        shown(a, name)
        if what == "text-cap":
            a.eval(f"{STAGE}.querySelector('.lb-sheet').scrollTop = 1e9")
        shot(t, a, f"drive-1440-{what}")
        shot(t, a, f"drive-1440-{what}", dark=True)
        close(a)

    # A phone: the lightbox fits, a swipe moves on, nothing scrolls sideways.
    p, _ = make_drive(t, "iphone")
    p.wait_for("drive-empty", 30)
    upload(t, p, ["png-named.svg", "notes.md", "page.txt"])
    pnav = watch(p)
    names = p.eval("[...document.querySelectorAll('[data-testid=\"file-row\"]')].map((e) => e.dataset.name)")
    i = names.index("png-named.svg")
    after, last = names[(i + 1) % 3], names[(i + 2) % 3]
    p.eval("[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === 'png-named.svg')"
           ".querySelector('[data-testid=\"file-open\"]').click()")
    judge(t, p, "png-named.svg", shown(p, "png-named.svg"), pnav, "phone")
    fits = p.eval("""(() => { const r = (s) => document.querySelector(s).getBoundingClientRect();
      const ok = (x) => x.left >= 0 && x.right <= innerWidth + 0.5 && x.top >= 0 && x.bottom <= innerHeight + 0.5;
      return ok(r('[data-testid="lightbox-download"]')) && ok(r('[data-testid="lightbox-close"]')) && ok(r('[data-testid="lightbox-stage"]'))
        && r('[data-testid="lightbox-close"]').width >= 44; })()""")
    t.check(fits and no_hscroll(p), "phone: Download, Close and the stage fit at 390, 44 px targets, no sideways scroll")
    shot(t, p, "drive-390-picture")
    shot(t, p, "drive-390-picture", dark=True)
    # A person's swipe: about 30 ms between moves, then a short hold before lifting (no fling left to eat the next tap).
    p.cmd("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 330, "y": 420}]})
    for x in range(330, 60, -45):
        p.b.drain(0.03)
        p.cmd("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": 422}]})
    p.b.drain(0.15)
    p.cmd("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": 60, "y": 422}]})
    p.cmd("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    got = shown(p, after)
    t.check(got["kind"] == HOSTILE[after][0], f"phone: a swipe to the left on the picture shows the next file ({after})")
    judge(t, p, after, got, pnav, "phone")
    shot(t, p, f"drive-390-{got['kind']}")
    shot(t, p, f"drive-390-{got['kind']}", dark=True)
    p.click("lightbox-next")
    got = shown(p, last)
    judge(t, p, last, got, pnav, "phone")
    shot(t, p, f"drive-390-{got['kind']}")
    t.check(p.ax_unnamed() == [] and p.errors == [], f"phone: every control named, no console error ({p.errors[:2]})")


# --- a folder link: the visit's files ----------------------------------------------------------------------

@scenario("preview-folder", "The preview in a folder link's visit (the folder viewer the paid folders use too): every hostile fixture; "
          "arrows through the folder; nothing runs; Download", features=("folders",))
def preview_folder(t):
    stock(t)
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    new_folder(a, "Hostile")
    into(a, "Hostile")
    upload(t, a, STORED)
    a.goto(t.origin + "/drive")
    a.wait("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === 'Hostile')", 60)
    open_share(a, "Hostile")
    to_opens(a)
    url = make_link(a)
    close_dialog(a)
    v, state = stranger(t, url)
    t.check(state == "ready", f"a stranger's first screen ({state})")
    v.click("view-open")
    v.wait_for("folder-view", 60)
    nav = watch(v)
    v.errors.clear()
    rows = v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"][data-kind=\"file\"]')].map((e) => e.dataset.name)")
    t.check(sorted(rows) == sorted(STORED), f"the visit lists every file ({rows})")
    for name in rows:
        v.eval(f"[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === {json.dumps(name)})"
               ".querySelector('[data-testid=\"fv-open\"]').click()")
        judge(t, v, name, shown(v, name), nav, "folder link")
        close(v)
        t.check(v.eval("document.activeElement?.closest('[data-testid=\"fv-row\"]')?.dataset.name") == name,
                f"folder link: {name}: focus back on its name")
    v.eval(f"[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === {json.dumps(rows[0])})"
           ".querySelector('[data-testid=\"fv-open\"]').click()")
    shown(v, rows[0])
    v.click("lightbox-next")
    t.check(shown(v, rows[1])["kind"] == HOSTILE[rows[1]][0], "Next file: the next one in the folder")
    v.key("ArrowLeft")
    shown(v, rows[0])
    i = rows.index("svg-named.png")
    for _ in range(i):
        v.key("ArrowRight")
    got = shown(v, "svg-named.png")
    t.check(got["kind"] == "svg", "the arrows reach the SVG named as a picture: drawn, not run")
    shot(t, v, "folder-1440-svg")
    shot(t, v, "folder-1440-svg", dark=True)
    before = os.listdir(v.downloads) if os.path.isdir(v.downloads) else []
    v.click("lightbox-download")
    saved = downloaded(v, before, 30)
    t.check(saved is not None and open(saved, "rb").read() == fixture_bytes(t, "svg-named.png"), "Download in the visit saves the same bytes")
    close(v)
    t.check(canary_requests(v) == [] and v.errors == [], f"folder link: nothing asked for /__canary/, no console error ({v.errors[:2]})")


# --- a paid link: the file shows itself once it opens ---------------------------------------------------------

@scenario("preview-pay", "The preview on a paid link (/p/): the SVG named as a picture, sold, paid with test money; Open it shows it "
          "drawn in a canvas, nothing runs; Esc, the name opens it again; Download; a phone", features=("folders", "pay_to_open"))
def preview_pay(t):
    stock(t)
    fake = PayFake(t)
    a = seller(t, fake)
    upload(t, a, ["svg-named.png"])
    url = sell(a, "svg-named.png", price="100000")
    sid = re.search(PAY_LINK, url)[1]
    fake.links[sid]["seller_state"] = "ok"
    close_dialog(a)
    for device in ("desktop", "iphone"):
        b = buyer(t, fake, url, device=device)
        nav = watch(b)
        b.errors.clear()
        b.click("pay-test")
        t.check(wait_pay(b, ("open",), 90) == "open", f"{device}: paid with test money, ready to open")
        b.click("pay-open")
        got = shown(b, "svg-named.png", 90)
        judge(t, b, "svg-named.png", got, nav, f"/p/ on {device}")
        width = 1440 if device == "desktop" else 390
        shot(t, b, f"pay-{width}-svg")
        shot(t, b, f"pay-{width}-svg", dark=True)
        close(b)
        t.check(b.focused() == "pay-file-open", f"{device}: Esc, and focus is on the file's name")
        b.click("pay-file-open")
        shown(b, "svg-named.png", 30)
        before = os.listdir(b.downloads) if os.path.isdir(b.downloads) else []
        b.click("lightbox-download")
        saved = downloaded(b, before, 30)
        t.check(saved is not None and open(saved, "rb").read() == fixture_bytes(t, "svg-named.png"), f"{device}: Download saves the same bytes")
        close(b)
        t.check(canary_requests(b) == [] and b.errors == [] and nav["n"] == 0,
                f"/p/ on {device}: nothing asked for /__canary/, no console error, no navigation ({b.errors[:2]})")


# --- a single-file link (/s/): the file shows itself once Open it opens it ------------------------------------------

@scenario("preview-link", "The preview on a single-file link (/s/): every hostile fixture dropped from the home page and opened by a "
          "stranger; the bytes pick the kind, nothing runs; Esc, the card opens it again, Download; a phone")
def preview_link(t):
    stock(t)
    for name in STORED:
        maker = t.actor()
        home(t, maker)
        maker.set_files("drop-input", [t.fixture(name)])
        url = wait_link(maker)
        device = "iphone" if name in ("notes.md", "svg-named.png") else "desktop"
        v = t.actor(device)
        nav = watch(v)
        t.check(open_link(v, url, open_it=False) == "ready", f"/s/: {name}: the stranger's first screen")
        nav["n"] = 0
        v.errors.clear()
        v.click("view-open")
        t.check(v.wait_state("view-root", VIEW_END, 120) == "opened", f"/s/: {name}: Open it opens it")
        got = shown(v, name)
        judge(t, v, name, got, nav, f"/s/ ({device})")
        if name in ("svg-named.png", "notes.md", "png-named.svg", "page.txt"):
            width = 390 if device == "iphone" else 1440
            shot(t, v, f"link-{width}-{got['kind']}")
            shot(t, v, f"link-{width}-{got['kind']}", dark=True)
        close(v)
        t.check(v.focused() == "view-show", f"/s/: {name}: Esc, and focus is on the card that opens it again")
        if name in ("svg-named.png", "page.txt"):
            v.click("view-show")
            shown(v, name)
            before = os.listdir(v.downloads) if os.path.isdir(v.downloads) else []
            v.click("lightbox-download")
            saved = downloaded(v, before, 30)
            t.check(saved is not None and open(saved, "rb").read() == fixture_bytes(t, name), f"/s/: {name}: Download saves the same bytes")
            close(v)
        t.check(canary_requests(v) == [] and v.errors == [] and nav["n"] == 0,
                f"/s/: {name}: nothing asked for /__canary/, no console error, no navigation ({v.errors[:2]})")


# --- Received: a single file sent by Tari shows itself over the dialog that keeps Save to my drive ----------------------

@scenario("preview-received", "The preview in Received: hostile files sent by Tari to a drive; each opens over its dialog, the bytes pick "
          "the kind, nothing runs; Esc keeps the dialog (Save to my drive, Save), focus on the file's name", features=("folders",))
def preview_received(t):
    stock(t)
    sent = ["svg-named.png", "page.txt", "notes.md"]   # a new drive sends three a day
    b = drive_page(t)
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    address = b.wait("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]'); return e && e.textContent.startsWith('otl_esm_1') ? e.textContent : ''; })()", 90)
    t.realizer.addresses.add(address)
    upload(t, a, sent)
    for name in sent:
        open_share(a, name)
        a.click("share-choice", "tari")
        a.click("share-next")
        a.wait("document.getElementById('share-dialog')?.dataset.step === 'tari'", 10)
        a.fill("send-recipient", address)
        a.wait_for("send-safety", 60)
        a.click("send-submit")
        t.check(a.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", f"Received: {name} sent by Tari to another drive")
        close_dialog(a)
    t.realizer.attach(b)
    nav = watch(b)
    b.goto(t.origin + "/drive/received")
    b.wait(f"document.querySelectorAll('[data-testid=\"received-row\"]').length >= {len(sent)}", 240)
    nav["n"] = 0
    b.errors.clear()
    seen = []
    for _ in sent:
        b.eval("[...document.querySelectorAll('[data-testid=\"received-row\"]')].find((r) => r.dataset.state === 'new')"
               ".querySelector('[data-testid=\"received-open-button\"]').click()")
        b.wait("document.querySelector('[data-testid=\"received-open\"]')?.dataset.state === 'opened'", 120)
        name = b.eval("document.querySelector('#lightbox [data-testid=\"lightbox-name\"]')?.textContent ?? ''")
        t.check(name in sent, f"Received: a delivery opens in the preview ({name!r})")
        if name not in sent:
            break
        seen.append(name)
        got = shown(b, name)
        judge(t, b, name, got, nav, "Received")
        if name == "svg-named.png":
            shot(t, b, "received-1440-svg")
            shot(t, b, "received-1440-svg", dark=True)
        close(b)
        t.check(b.focused() == "received-show" and b.exists("received-keep") and b.exists("received-save-file"),
                f"Received: {name}: Esc closes the preview; the dialog keeps Save to my drive and Save, focus on the name")
        b.key("Escape")
        b.wait("!document.querySelector('#rec-open') || document.querySelector('#rec-open').hidden", 10)
    t.check(sorted(seen) == sorted(sent), f"Received: every delivery opened ({seen})")
    t.check(canary_requests(b) == [] and b.errors == [] and nav["n"] == 0,
            f"Received: nothing asked for /__canary/, no console error, no navigation ({b.errors[:2]})")
