# SPDX-License-Identifier: MIT
"""The app-ui flows, against the real API (`--dev`) in headless Chromium. Each flow names what it
covers (10-spec §16.2 A-04…A-09, §12.3 states, the golden paths of the task). Selectors come from the
data-testid contract of spec §3.4.9 and brand patch P-6."""
import base64
import fnmatch
import hashlib
import json
import os
import re
import time
import urllib.parse

import qrread  # noqa: E402 (web/app/ui/tests is on the path: run.py puts it there)

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
SCENARIOS = []
VIEW_END = ("opened", "program-warning", "integrity-error", "burned", "expired", "revoked", "removed",
            "not-found", "locked", "error", "needs-locker", "wrong-key", "incomplete")
VIEW_ASK = ("ready", "password", "needs-locker", "wrong-key", "incomplete", "burned", "expired", "revoked",
            "removed", "not-found", "locked", "error")


def scenario(sid, title, **opts):
    def wrap(fn):
        SCENARIOS.append((sid, title, fn, opts))
        return fn
    return wrap


# --- steps shared by the flows -------------------------------------------------------------------

# The build names every asset a page asks for name.<10 hex of its content>.ext (tools/assets.py); checks that name a
# file compare its plain name.
FINGERPRINT = re.compile(r"\.[0-9a-f]{10}(\.[a-z0-9]+)(?=$|[?#])")


def plain(url):
    return FINGERPRINT.sub(r"\1", url)


def sent_bytes(path):
    """(what the server sends for this built file, its gzip -9): the budgets count the first. The build writes a Brotli
    copy beside each text file (deploy/scripts/precompress.py) and Caddy sends it to every browser that takes br, as
    Chromium, Firefox and Safari do; without one, gzip -9 of the file (the budgets' measure before precompression)."""
    import gzip
    with open(path, "rb") as f:
        gz = len(gzip.compress(f.read(), 9))
    br = path + ".br"
    return (min(os.path.getsize(br), gz) if os.path.isfile(br) else gz), gz


def home(t, page, path="/"):
    page.goto(t.origin + path)
    page.wait_for("drop-input", 60)


def wait_link(page, previous="", timeout=120):
    return page.wait("(() => { const e = document.querySelector('[data-testid=\"sealed-link\"]'); const v = e && e.value; "
                     f"return v && v.startsWith('http') && v !== {json.dumps(previous)} ? v : ''; }})()", timeout)


def seal_text(page, text):
    page.click("drop-write")
    page.wait_for("drop-textarea")
    page.fill("drop-textarea", text)
    page.click("drop-seal-text")
    return wait_link(page)


def open_link(page, url, password=None, open_it=True):
    page.goto(url)
    state = page.wait_state("view-root", VIEW_ASK, 60)
    if state == "password" and password is not None:
        page.fill("view-password", password)
        page.click("view-password-submit")
        state = page.wait("(() => { const r = document.querySelector('[data-testid=\"view-root\"]'); const s = r?.dataset.state;"
                          " return s !== 'password' ? s : (/not it/i.test(r.textContent) ? 'password:wrong' : ''); })()", 60)
    if state == "ready" and open_it:
        page.click("view-open")
        state = page.wait_state("view-root", VIEW_END, 120)
    return state


# viral-1: the one quiet line after the value (ui/invite.js), its words and where its one button goes.
INVITE = "Want your own? Private drive. No email. No KYC."
INVITE_TO = {"secret": ("Make your own secret", "/?from=share#share"), "sell": ("Sell your own files", "/drive?make&from=share")}


def invite_check(t, page, kind, where, shot=None, secrets=()):
    """viral-1: after the value, one quiet line: its words, one outline button to where it goes, and a ×; nothing of the
    link in it (`secrets`: the link's id, its file's name or text, its label); nothing sideways. Then × hides it for the
    page view and the focus stays on the page. `shot`: a picture of it first, in view."""
    label, href = INVITE_TO[kind]
    got = page.eval("""(() => { const e = document.querySelector('[data-testid="invite"]'); if (!e) return null;
      const go = e.querySelector('[data-testid="invite-go"]'), x = e.querySelector('[data-testid="invite-x"]');
      return { text: e.innerText.replace(/\\s+/g, ' ').trim(), html: e.outerHTML, say: e.querySelector('.invite-say')?.textContent,
        go: go?.textContent, href: go?.getAttribute('href'), kind: e.dataset.kind, x: x?.getAttribute('aria-label'),
        primary: !!e.querySelector('.a-btn--primary, .btn:not([data-variant])'), links: e.querySelectorAll('a').length,
        buttons: e.querySelectorAll('button').length }; })()""")
    t.check(got is not None and got["say"] == INVITE and got["go"] == label and got["href"] == href and got["kind"] == kind
            and got["x"] == "Close" and got["links"] == 1 and got["buttons"] == 1 and not got["primary"],
            f"{where}: after the value, one quiet line, one outline button {label!r} to {href}, and a × "
            f"({got and {k: got[k] for k in ('say', 'go', 'href', 'x', 'primary')}})")
    if got:
        leaked = [s for s in secrets if s and s in got["html"]]
        t.check(got["text"] == f"{INVITE} {label}" and not leaked, f"{where}: nothing of the link in it ({got['text']!r}, {leaked})")
    t.check(no_hscroll(page), f"{where}: no horizontal scroll with the line")
    if shot:
        page.eval("document.querySelector('[data-testid=\"invite\"]')?.scrollIntoView({ block: 'center' })")
        page.b.drain(0.8)   # its fade-in
        t.shot(page, shot)
    page.click("invite-x")
    page.wait("!document.querySelector('[data-testid=\"invite\"]')", 5)
    t.check(page.eval("document.activeElement?.id") == "main", f"{where}: × hides it for this page view; the focus stays on the page")


def close_preview(page):
    """An opened file shows in the preview (ui/lightbox.js) over the page; Esc puts the page's own controls back."""
    if page.exists("lightbox"):
        page.key("Escape")
        page.wait("!document.getElementById('lightbox')", 10)


def rule_version(page):
    return page.eval("document.querySelector('.md-card')?.dataset.rule ?? ''")


def apply_rules(page, who=None, mode=None, password=None, when=None, views=None, expiry=None):
    """Changes the rule in the Change panel; returns the link (new for a password, the same otherwise)."""
    before_link, before_rule = page.value("sealed-link"), rule_version(page)
    if not page.visible("who"):
        page.click("card-change")
        page.wait_for("who")
    if who:
        page.click("who", who)
    if mode:
        page.click("password-mode", mode)
    if password is not None:
        page.fill("password-input", password)
    if when:
        page.click("when", when)
    if views is not None:
        page.fill("views-input", str(views))
    if expiry:
        page.click("expiry-preset", expiry)
    page.click("apply-rules")
    try:
        page.wait(f"(document.querySelector('.md-card')?.dataset.rule ?? '') !== {json.dumps(before_rule)}", 60)
    except TimeoutError:
        raise TimeoutError("the rule didn't apply: " + page.eval("document.querySelector('.md-change')?.innerText.replace(/\\s+/g, ' ') ?? ''")[-500:]) from None
    return page.value("sealed-link") or before_link


def suggested_names(browser):
    """The file names this browser offered to save (Chromium stores downloads under random names)."""
    return [e["params"]["suggestedFilename"] for e in browser.events if e.get("method") == "Browser.downloadWillBegin"]


def same_origin(t, page):
    return [r["url"] for r in page.requests if not r["url"].startswith((t.origin, "data:", "blob:", "about:", "chrome"))]


def no_hscroll(page):
    return bool(page.eval("document.scrollingElement.scrollWidth <= window.innerWidth"))


def safety_emoji(page, testid):
    return page.eval(f"[...new Intl.Segmenter().segment(document.querySelector('[data-testid=\"{testid}\"]').textContent)]"
                     ".map(s => s.segment).filter(g => /\\p{Extended_Pictographic}/u.test(g))")


class Intercept:
    """Test-only: rewrites some of one page's API traffic (states the dev server can't produce on cue).
    rules: (url pattern, method or None, stage, fn). At the Request stage fn(params) returns None to let
    the request through, or (status, body) to answer it; at the Response stage fn(json body) returns the
    body to deliver."""

    def __init__(self, page):
        self.page, self.rules = page, []
        page.on("Fetch.requestPaused", self._paused)

    def add(self, pattern, stage, fn, method=None):
        self.rules.append((pattern, method, stage, fn))
        self.page.cmd("Fetch.enable", {"patterns": [{"urlPattern": p, "requestStage": st} for p, _, st, _ in self.rules]})
        return self

    def clear(self):
        self.rules = []
        self.page.cmd("Fetch.disable")

    def _paused(self, params):
        req, rid = params["request"], params["requestId"]
        stage = "Response" if "responseStatusCode" in params else "Request"
        for pattern, method, st, fn in self.rules:
            if st == stage and fnmatch.fnmatchcase(req["url"], pattern) and method in (None, req["method"]):
                if stage == "Request":
                    answer_ = fn(params)
                    if answer_ is not None:
                        return self._fulfil(rid, *answer_)
                else:
                    got = self.page.cmd("Fetch.getResponseBody", {"requestId": rid})
                    raw = base64.b64decode(got["body"]) if got.get("base64Encoded") else got["body"].encode()
                    return self._fulfil(rid, params["responseStatusCode"], fn(json.loads(raw)))
                break
        self.page.cmd("Fetch.continueRequest", {"requestId": rid})

    def _fulfil(self, rid, status, body):
        self.page.cmd("Fetch.fulfillRequest", {"requestId": rid, "responseCode": status,
                                               "responseHeaders": [{"name": "Content-Type", "value": "application/json"}],
                                               "body": base64.b64encode(json.dumps(body).encode()).decode()})


def api_error(code, status, retry_after=None):
    return lambda _params: (status, {"error": {"code": code, "message": code, "details": {}, "retry_after": retry_after}})


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def downloaded(page, before=(), timeout=10):
    """The first file this page downloaded that isn't in `before` (Chromium names downloads by guid)."""
    end = time.time() + timeout
    while time.time() < end:
        page.b.drain(0.3)
        new = [f for f in (os.listdir(page.downloads) if os.path.isdir(page.downloads) else []) if f not in before
               and not f.endswith(".crdownload")]
        if new:
            return os.path.join(page.downloads, new[0])
    return None


def make_locker_with_drop(t, page, label):
    """/locker's first screen: Make my drop link (no question first), then Later; the drop's name
    ("people see this") is set afterwards, as the page offers it."""
    page.goto(t.origin + "/locker")
    page.wait_for("locker-root", 60)
    page.wait_for("drop-create", 60)
    t.check(not page.exists("drop-label"), "a drop link asks nothing before it exists")
    page.click("drop-create")
    url = page.wait("(() => { const e = document.querySelector('[data-testid=\"drop-link\"]'); return e?.value?.includes('/d/') ? e.value : ''; })()", 120)
    if label:
        if page.exists("key-later"):
            page.click("key-later")
            page.wait("!document.querySelector('dialog[open]')", 10)
        page.fill("drop-label", label)
        page.click("drop-label-save")
        page.wait(f"document.querySelector('[data-testid=\"drop-label\"]')?.value === {json.dumps(label)} && "
                  "!document.querySelector('[data-testid=\"drop-label-save\"]')?.disabled", 30)
    return url


# --- the anonymous golden path -----------------------------------------------------------------------

@scenario("home-text", "Home: a text secret, Once; copy; open; reload and a second browser see it burned")
def home_text(t):
    a = t.actor("iphone")
    events = []
    home(t, a)
    a.eval("document.addEventListener('mutis:state', e => (window.__states ||= []).push(e.detail.state))")
    t.shot(a, "home-390-idle")
    started = time.time()
    url = seal_text(a, "The office key is under the plant.")
    took = time.time() - started
    t.check(re.match(rf"^{re.escape(t.origin)}/s/[A-Za-z0-9_-]{{22}}#1[A-Za-z0-9_-]{{43}}$", url) is not None, f"the sealed link has the key after # ({url[-50:]})")
    t.check(took < 10, f"from text to link in {took:.1f} s on a 390×844 phone (< 10 s)")
    states = a.eval("window.__states")
    t.check(states[-1] == "sealed" and "sealing" in states, f"mutis:state events {states}")
    live = a.wait("(() => { const s = document.querySelector('.md-live')?.textContent || ''; return /Copied/.test(s) ? s : ''; })()", 10)
    t.check(live == "Link made. Copied.", f"the one live region: {live!r}")
    t.check(a.eval("document.querySelector('[data-testid=\"copy-link\"]').textContent.trim()") == "Copied"
            and a.wait("navigator.clipboard.readText()", 10) == url, "the copy was made the moment the link existed, and the button says so")
    say = a.eval("document.querySelector('.md-say').textContent")
    # the server keeps a link until the hour after its time (spec §5.3), so a day reads 24 or 25 hours
    t.check(re.fullmatch(r"It opens one time in the next 2[45] hours\.\sThen it's gone\.", say) is not None,
            f"one sentence says the rule, with its time ({say!r})")
    t.shot(a, "home-390-sealed")
    a.click("card-change")
    a.wait_for("who")
    t.shot(a, "home-390-change", full_page=True)
    a.click("known-toggle")
    a.wait("(document.querySelector('[data-testid=\"known-panel\"]')?.textContent || '').includes('access_hash')", 30)
    t.check(not a.eval("document.querySelector('[data-testid=\"known-panel\"]').hidden"), "More rules: what our server got opens the glass box")
    noise = a.eval("(() => { const c = document.querySelector('[data-testid=\"noise-canvas\"]'); const d = c.getContext('2d').getImageData(0, 0, 96, 96).data;"
                   " const s = new Set(); for (let i = 0; i < d.length; i += 4) s.add(d[i]); return s.size; })()")
    t.check(noise > 64, f"and the noise strip draws real ciphertext bytes ({noise} grey levels)")
    t.shot(a, "home-390-known", full_page=True)
    a.click("card-change")
    a.eval("navigator.clipboard.writeText('something else')")
    a.click("copy-link")
    copied = a.wait("navigator.clipboard.readText()", 10)
    t.check(copied == url, "Copy link puts the full link on the clipboard")
    t.check(not same_origin(t, a), "the home page made no third-party request")
    stored = a.eval("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))")
    t.check(url.split("#")[1] not in stored and "under the plant" not in stored
            and set(json.loads(stored)) <= {"mutis.recent", "mutis.theme", "mutis.keyAsked", "mutis.drive"},
            f"localStorage holds no key and no text, only the recent-drops list ({sorted(json.loads(stored))})")
    b = t.actor("android")
    t.check(open_link(b, url, open_it=False) == "ready", "B sees the ready state, nothing used yet")
    t.check(re.fullmatch(ONCE_UNTIL, b.text("view-views-left")) is not None, f"the sentence says the rule and its time: once ({b.text('view-views-left')!r})")
    t.check(b.attr("view-root", "data-state") == "ready" and b.eval("document.querySelector('.a-figure')?.dataset.pose") == "once"
            and b.eval("!document.querySelector('svg.ghost')"), "a tile for Once, and no ghost")
    t.shot(b, "view-412-ready")
    b.click("view-open")
    t.check(b.wait_state("view-root", VIEW_END, 60) == "opened", "B opens it")
    t.check(b.text("view-text") == "The office key is under the plant.", "B reads exactly the text")
    t.check(b.eval("location.hash") == "", "the key left the address bar after the open")
    t.shot(b, "view-412-opened-text")
    b.reload()
    t.check(b.wait_state("view-root", VIEW_ASK, 60) == "burned", "B's reload shows burned")
    t.shot(b, "view-412-burned")
    c = t.actor("desktop")
    t.check(open_link(c, url) == "burned", "a second browser sees burned")
    gone_text = c.text("view-root")
    t.check("This link has ended." in gone_text and "Someone opened it already." in gone_text, f"the ended page: This link has ended. ({gone_text[:80]!r})")
    t.check(c.eval("document.querySelector('.a-figure')?.dataset.pose === 'gone' && !document.querySelector('svg.ghost')"), "the ended tile, no ghost")
    t.shot(c, "view-1440-burned")


@scenario("viewer-states", "Viewer: incomplete, not-found, a damaged key, the glass box")
def viewer_states(t):
    a = t.actor()
    home(t, a)
    url = seal_text(a, "glass box check")
    base = url.split("#")[0]
    b = t.actor()
    t.check(open_link(b, base) == "incomplete", "a link without its key: incomplete")
    t.shot(b, "view-1440-incomplete")
    t.check(open_link(b, t.origin + "/s/" + "A" * 22 + "#1" + "A" * 43) == "not-found", "an unknown id: not-found")
    bad = url[:-4] + ("AAAA" if not url.endswith("AAAA") else "BBBB")
    t.check(open_link(b, bad, open_it=False) == "wrong-key", "a changed key: This key doesn't fit, no view used")
    t.check(open_link(b, url, open_it=False) == "ready", "the real link is still ready (no view was used)")
    b.click("view-known")
    b.wait("(document.querySelector('[data-testid=\"known-panel\"]')?.textContent || '').includes('wrapped_key')", 30)
    text = b.text("known-panel")
    t.check(all(w in text for w in ("size_stored", "access_hash", "not known", "That's all we have.")) or "Not stored anywhere" in text,
            "the glass box prints the columns and what is stored nowhere")
    t.shot(b, "view-1440-known", full_page=True)


# --- exit rules, passwords, deleting -------------------------------------------------------------------

@scenario("rules", "Change panel: 3 opens on the same link; link + password; password only; Delete now")
def rules(t):
    a = t.actor()
    home(t, a)
    t.shot(a, "home-1440-idle")
    # A slow uplink, so the sealing state stays on screen long enough to be seen and pictured.
    a.cmd("Network.emulateNetworkConditions", {"offline": False, "latency": 80, "downloadThroughput": -1, "uploadThroughput": 256 * 1024})
    a.set_files("drop-input", [t.fixture("report.dat")])
    phase = a.wait("['encrypting', 'uploading'].includes(document.querySelector('[data-testid=\"seal-progress\"]')?.dataset.phase) && document.querySelector('[data-testid=\"seal-progress\"]').dataset.phase", 30)
    t.check(phase in ("encrypting", "uploading"), f"the progress line names its phase ({phase})")
    t.shot(a, "home-1440-sealing")
    url = wait_link(a)
    a.cmd("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    t.shot(a, "home-1440-sealed-file")
    a.click("card-change")
    a.wait_for("who")
    t.shot(a, "home-1440-change")
    same = apply_rules(a, when="views", views=3)
    t.check(same == url, "a count change keeps the same link (PATCH, spec §5.4)")
    t.check(a.eval("document.querySelector('.md-card').dataset.maxViews") == "3", "the card shows 3 opens")
    t.check("up to 3 times" in a.eval("document.querySelector('.md-say').textContent"), "the card's sentence says up to 3 opens")
    for who in "BCD":
        p = t.actor()
        t.check(open_link(p, url) == "opened", f"{who} opens the file")
        close_preview(p)
        p.click("view-save")
        p.b.drain(1.5)
        saved = [f for f in os.listdir(p.downloads)] if os.path.isdir(p.downloads) else []
        t.check(bool(saved), f"{who}'s Save file downloads it")
    t.check(open_link(t.actor(), url) == "burned", "the fourth browser sees burned")

    home(t, a)
    url = seal_text(a, "behind a password")
    new = apply_rules(a, who="password", mode="link_password", password="correct horse battery")
    t.check(new != url and "#2" in new, "a password makes a new link with a #2 key part")
    t.shot(a, "home-1440-password")
    t.check(open_link(t.actor(), url) == "revoked", "the old link no longer works (revoked)")
    b = t.actor("iphone")
    first = open_link(b, new, password="wrong one")
    t.check(first == "password:wrong", "a wrong password: That's not it")
    msg1 = b.eval("document.getElementById('a-view-pw-msg').textContent")
    b.fill("view-password", "wrong two")
    b.click("view-password-submit")
    msg2 = b.wait(f"(() => {{ const m = document.getElementById('a-view-pw-msg').textContent; return /not it/.test(m) && m !== {json.dumps(msg1)} ? m : ''; }})()", 60)
    t.check("left" in msg2, f"the next wrong try says how many are left ({msg2})")
    t.shot(b, "view-390-password-wrong")
    b.fill("view-password", "correct horse battery")
    b.click("view-password-submit")
    t.check(b.wait_state("view-root", ("ready",), 60) == "ready", "the right password reaches ready")
    b.click("view-open")
    t.check(b.wait_state("view-root", VIEW_END, 60) == "opened" and b.text("view-text") == "behind a password", "and opens it")

    home(t, a)
    seal_text(a, "password only")
    only = apply_rules(a, who="password", mode="password", password="four random words here")
    t.check("#" not in only, "password only: the link has no key part")
    c = t.actor()
    t.check(open_link(c, only, password="four random words here") == "opened", "a password-only link opens with the password alone")

    # Our server doesn't confirm that the old link ended: nothing changes, and nothing says it did.
    home(t, a)
    kept_url = seal_text(a, "the old link stays")
    sid = kept_url.split("/s/")[1].split("#")[0]
    cut = Intercept(a).add(f"*/api/v1/s/{sid}", "Request", api_error("internal", 500), method="DELETE")
    a.click("card-change")
    a.wait_for("who")
    a.click("who", "password")
    a.fill("password-input", "correct horse battery")
    a.click("apply-rules")
    a.wait("!!document.querySelector('.md-change [data-testid=\"error-banner\"]')", 60)
    toast = a.eval("document.querySelector('.a-toast:not([hidden])')?.textContent ?? ''")
    t.check(a.value("sealed-link") == kept_url and "no longer works" not in toast,
            "a revoke that fails: the card keeps the old link and no toast says it stopped working")
    cut.clear()
    t.check(open_link(t.actor(), kept_url, open_it=False) == "ready", "the old link still opens, as the card says")

    home(t, a)
    gone = seal_text(a, "to be deleted")
    a.click("card-change")
    a.wait_for("delete-drop")
    a.click("delete-drop")
    a.wait_for("delete-confirm")
    a.click("delete-confirm")
    a.wait_for("drop-input", 30)
    t.check(open_link(t.actor(), gone) == "revoked", "Delete now: the link answers revoked")


@scenario("card-fresh", "A first visit: the card's Tari action and locker rules open a locker in place; errors stay in the card")
def card_fresh(t):
    _, _, address = owner_with_drop(t, "desktop")

    # The locker can't open (a shared address at its sign-up limit): the error shows in the card.
    e = t.actor()
    home(t, e)
    link = seal_text(e, "the link stays on screen")
    Intercept(e).add("*/api/v1/auth/register", "Request", api_error("rate_limited", 429, 1800), method="POST")
    e.click("card-send-address")
    e.wait("!!document.querySelector('.md-result [data-testid=\"error-banner\"]')", 120)
    t.check(e.attr("error-banner", "data-code") == "rate_limited" and e.value("sealed-link") == link and e.visible("copy-link"),
            "a locker that can't open: the error is in the result, with the link and Copy link still there")
    t.shot(e, "home-1440-card-error")

    # "Send it to a Tari address instead" from a browser that has never had a locker.
    a = t.actor("iphone")
    home(t, a)
    old = seal_text(a, "sent instead of linked")
    sid = old.split("/s/")[1].split("#")[0]
    a.click("card-send-address")
    a.wait_for("send-recipient", 120)
    t.check(True, "the locker opens in place and the send step appears")
    a.fill("send-recipient", address)
    a.wait_for("send-safety", 30)
    cut = Intercept(a).add(f"*/api/v1/s/{sid}", "Request", api_error("internal", 500), method="DELETE")
    a.click("send-submit")
    t.check(a.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "Sent")
    a.wait_for("card-close-link", 60)
    t.check(a.value("sealed-link") == old and a.exists("copy-link"), "the old link isn't confirmed closed: the card still shows it, and says so")
    t.check(open_link(t.actor(), old, open_it=False) == "ready", "it still works")
    cut.clear()
    a.click("card-close-link")
    a.wait_for("card-sent", 60)
    t.check(not a.exists("copy-link") and not a.exists("sealed-link"), "once closed, the card drops the link and Copy link")
    sentence = a.text("card-sent")
    t.check(sentence.startswith("Sent to otl_esm_1") and "no longer works" in sentence, f"and says where the file went ({sentence[:70]})")
    t.check(open_link(t.actor(), old) == "revoked", "the old link answers revoked")
    t.shot(a, "home-390-sent-instead", full_page=True)

    # Change → 7 days (a locker's rule) from a browser that has never had a locker.
    c = t.actor()
    home(t, c)
    url = seal_text(c, "a week")
    same = apply_rules(c, expiry="604800")
    left = int(c.eval("document.querySelector('.md-card').dataset.expiresAt")) - time.time()
    t.check(same == url and abs(left - 604800) < 600, f"7 days applies to the same link ({left / 86400:.2f} days)")


@scenario("kept", "P1 kept files: Only me and Until I delete it from a first visit; /locker lists, saves and deletes them")
def kept(t):
    a = t.actor()
    home(t, a)
    a.set_files("drop-input", [t.fixture("notes.txt")])
    wait_link(a)
    a.click("card-change")
    a.wait_for("who")
    a.click("who", "only_me")
    a.click("apply-rules")
    a.wait("!document.querySelector('[data-testid=\"sealed-link\"]') && /only this drive/.test(document.querySelector('.md-kept')?.textContent || '')", 180)
    t.check(True, "Only me: kept in the locker, no link")
    home(t, a)
    a.set_files("drop-input", [t.fixture("report.dat")])
    before = wait_link(a)
    url = apply_rules(a, when="never")
    t.check(url != before and "it stays" in a.eval("document.querySelector('.md-say').textContent"),
            "Until I delete it: a new link whose sentence says it stays")
    t.check(open_link(t.actor(), before) in ("revoked", "not-found"), "the link to the anonymous copy no longer works")
    b = t.actor()
    t.check(open_link(b, url) == "opened", "the kept file's link opens")
    a.goto(t.origin + "/locker")
    a.wait("document.querySelectorAll('[data-testid=\"kept-row\"]').length === 2", 120)
    t.shot(a, "locker-1440-kept", full_page=True)
    rows = a.eval("[...document.querySelectorAll('[data-testid=\"kept-row\"]')].map((r) => r.textContent)")
    t.check(any("notes.txt" in r for r in rows) and any("report.dat" in r for r in rows), "/locker lists both kept files by name")
    a.eval("[...document.querySelectorAll('[data-testid=\"kept-row\"]')].find((r) => r.textContent.includes('notes.txt')).querySelector('[data-testid=\"kept-save\"]').click()")
    saved = downloaded(a)
    t.check(bool(saved) and sha256_file(saved) == sha256_file(t.fixture("notes.txt")), "Save gives back exactly the file that was kept")
    a.eval("[...document.querySelectorAll('[data-testid=\"kept-row\"]')].find((r) => r.textContent.includes('report.dat')).querySelector('[data-testid=\"kept-delete\"]').click()")
    a.wait("document.querySelectorAll('[data-testid=\"kept-row\"]').length === 1", 60)
    a.reload()
    a.wait("!!document.querySelector('[aria-labelledby=\"a-kept-h\"]') && !document.querySelector('.a-kept .a-working')", 120)
    rows = a.eval("[...document.querySelectorAll('[data-testid=\"kept-row\"]')].map((r) => r.textContent)")
    t.check(len(rows) == 1 and "notes.txt" in rows[0], f"Delete removes the kept file on our server: after a reload only notes.txt is listed ({len(rows)})")


# --- recipient safety, limits, photos -------------------------------------------------------------------

@scenario("safety", "Programs refused before upload; a too-big file offers a locker; photos lose their GPS")
def safety(t):
    a = t.actor()
    home(t, a)
    a.set_files("drop-input", [t.fixture("setup.exe")])
    a.wait("document.querySelector('[data-testid=\"error-banner\"]')?.dataset.code === 'program'", 30)
    t.check(not [r for r in a.requests if r["url"].endswith("/api/v1/uploads")], "an anonymous .exe is refused before any upload")
    t.shot(a, "home-1440-program")
    a.set_files("drop-input", [t.fixture("too-big.bin")])
    a.wait("document.querySelector('[data-testid=\"error-banner\"]')?.dataset.code === 'too_large'", 30)
    t.check("free drive" in a.text("error-banner") and a.exists("offer-locker"), "too large: the banner offers a free locker")
    t.check(not [r for r in a.requests if r["url"].endswith("/api/v1/uploads")], "nothing was uploaded")
    # Names whose program extension appears only once invisible or forbidden characters are gone.
    for name, ext in (("invoice.b\u200bat", "bat"), ("run.p|s1", "ps1")):
        a.set_files("drop-input", [t.fixture(name)])
        a.wait(f"(document.querySelector('[data-testid=\"error-banner\"]')?.textContent || '').includes('(.{ext})')", 30)
        t.check(a.attr("error-banner", "data-code") == "program", f"{name!r} is refused as the .{ext} it would be saved as")
    t.check(not [r for r in a.requests if r["url"].endswith("/api/v1/uploads")], "none of them was uploaded")
    a.set_files("drop-input", [t.fixture("setup.exe")])
    a.wait_for("offer-locker", 30)
    a.click("offer-locker")
    url = wait_link(a, timeout=120)
    t.check(bool(url), "with a locker opened in place, the program is locked as the locker's file")
    b = t.actor()
    t.check(open_link(b, url) == "program-warning", "the viewer shows the program warning")
    t.check(b.exists("view-save-anyway") and not b.exists("view-image"), "no preview; Save anyway is offered")
    # A chunk the server (or the web server in front of it) refuses as too large (claims review item 24):
    # its own sentence with the limit, not "our server tripped".
    c = t.actor()
    home(t, c)
    Intercept(c).add("*/api/v1/uploads/*/chunks/*", "Request",
                     lambda _p: (413, {"error": {"code": "too_large", "message": "Request body too large.", "details": {"max_bytes": 5242880}}}))
    c.set_files("drop-input", [t.fixture("notes.txt")])
    c.wait("document.querySelector('[data-testid=\"error-banner\"]')?.dataset.code === 'too_large_request'", 60)
    t.check("5 MB" in c.text("error-banner") and not c.exists("offer-locker"), "a 413 from the server reads as too large, with the server's limit")
    t.shot(b, "view-1440-program")

    # A sender whose client skips the checks: the viewer goes by the name the file would be saved under.
    m = t.actor()
    home(t, m)
    names = {"invoice.b\u200bat": "invoice.bat", "run.p|s1": "run.ps1", "photo\u202egpj.exe": "photogpj.exe"}
    links = m.eval("(async () => { const { sealItem, createLink } = await import('/app/lib/seal.js');"
                   " const now = Math.floor(Date.now() / 1000); const out = [];"
                   f" for (const name of {json.dumps(list(names))}) {{"
                   "   const item = await sealItem({ file: new File(['echo hi'], 'x.txt'), name, type: '', mtime: null, stripped: false },"
                   "     { anonymous: true, expiresAt: now + 3600 });"
                   "   out.push((await createLink(item, { maxViews: 1, expiresAt: now + 3600 })).url); }"
                   " return out; })()", timeout=120)
    v = t.actor()
    for link, (raw, saved) in zip(links, names.items()):
        state = open_link(v, link)
        shown = v.text("view-filename") if v.exists("view-filename") else ""
        t.check(state == "program-warning" and shown == saved, f"stored as {raw!r}: the program warning, named {saved} ({state}, {shown!r})")
    v.click("view-save-anyway")
    v.click("view-save")
    v.b.drain(1.5)
    t.check(suggested_names(t.browser)[-1:] == ["photogpj.exe"], f"Save anyway offers the name it showed ({suggested_names(t.browser)[-1:]})")

    p = t.actor("iphone")
    home(t, p)
    p.set_files("drop-input", [t.fixture("photo-gps.jpg")])
    p.wait("document.querySelector('[data-testid=\"exif-chip\"]')?.dataset.removed === 'true'", 60)
    t.check(True, "the photo chip says location and camera data were removed")
    photo = wait_link(p)
    t.shot(p, "home-390-sealed-photo")
    q = t.actor("iphone")
    t.check(open_link(q, photo) == "opened" and q.exists("view-image"), "the photo opens with a preview")
    t.shot(q, "view-390-opened-photo")


# --- lockers, keys, dead drops, the inbox ---------------------------------------------------------------

@scenario("locker", "Locker: made silently from Leave me a file; key modal; key file with passphrase; restore")
def locker(t):
    a = t.actor("iphone")
    a.goto(t.origin + "/locker")
    a.wait_for("locker-root", 60)
    a.wait_for("drop-create", 60)
    t.check(not a.eval("!!document.querySelector('.a-bottom')"), "no Locker · Inbox · Send tabs before a locker exists")
    first = a.text("locker-root")
    t.check(all(w in first for w in ("Get a file from someone", "See what came", "Send to a Tari address", "It lives in this browser. No email, no password.")),
            "the first screen: what a locker is, and its three things by name")
    t.shot(a, "locker-390-empty", full_page=True)
    drop = make_locker_with_drop(t, a, None)
    t.check(re.match(rf"^{re.escape(t.origin)}/d/[0-9a-hjkmnp-tv-z]{{10}}$", drop) is not None, f"a short drop link ({drop})")
    a.wait_for("key-save-file", 30)
    t.check(a.eval("!!document.querySelector('dialog[open]')"), "the key modal asks once, now that something persistent exists")
    t.shot(a, "locker-390-key-modal")
    a.click("key-save-file")
    t.check("passphrase" in a.text("key-save-file").lower() or a.eval("!!document.activeElement?.matches('[data-testid=\"key-passphrase\"]')"),
            "with the passphrase box ticked (P-15) an empty passphrase stops the download")
    a.fill("key-passphrase", "orchid lantern quiet river")
    a.click("key-save-file")
    a.b.drain(2)
    files = os.listdir(a.downloads) if os.path.isdir(a.downloads) else []
    key_text = open(os.path.join(a.downloads, files[0]), encoding="utf-8").read() if files else ""
    t.check("Locked key:" in key_text and "MUTIS-" not in key_text, "the key file is locked with the passphrase; the plain key isn't in it")
    a.click("key-later")
    a.wait("!document.querySelector('dialog[open]')", 10)
    a.fill("drop-label", "Council")
    a.click("drop-label-save")
    a.wait("document.querySelector('[data-testid=\"drop-label\"]')?.value === 'Council'", 30)
    t.check(a.eval(f"fetch('/api/v1/drops/{drop.rsplit('/', 1)[1]}').then((r) => r.json()).then((j) => j.label)") == "Council",
            "the drop's name is set after the link exists (people see it)")
    a.wait_for("locker-safety", 30)
    safety = safety_emoji(a, "locker-safety")
    address = a.text("locker-address").strip()
    t.check(len(safety) == 12, f"the safety code has 12 emoji ({len(safety)})")
    t.check(address.startswith("otl_esm_1"), "the locker shows its otl_esm_ Tari address")
    t.check(a.exists("key-banner"), "the key banner stays until the key is saved")
    t.check(a.attr("locker-root", "data-probation") == "true", "a new locker is on probation")
    stored = a.eval("JSON.stringify(localStorage)")
    code = a.eval("(async () => { const { loadIdentity, recoveryCode } = await import('/app/lib/identity.js'); return recoveryCode((await loadIdentity()).seed); })()")
    t.check(code.replace("MUTIS-", "")[:20] not in stored, "localStorage holds no key material (the locker's seed lives in IndexedDB, spec §4.8.1)")
    stores = a.eval("new Promise((r) => { const q = indexedDB.open('mutis'); q.onsuccess = () => r([...q.result.objectStoreNames]); })")
    t.check(sorted(stores) == ["identity", "inbox"], f"IndexedDB holds only the locker record and the inbox state ({stores})")
    t.check(int(a.attr("quota-bar", "data-limit") or 0) > 0, "the quota bar shows the locker's limit")
    t.shot(a, "locker-390-full", full_page=True)
    t.shared.update(drop=drop, safety=safety, address=address)
    b = t.actor()
    b.goto(t.origin + "/locker")
    b.wait_for("restore-open", 60)
    b.click("restore-open")
    b.wait_for("restore-text", 10)
    b.fill("restore-text", key_text)
    b.click("restore-submit")
    b.wait_for("restore-passphrase", 20)
    b.fill("restore-passphrase", "orchid lantern quiet river")
    b.click("restore-submit")
    b.wait_for("locker-safety", 120)
    t.check(safety_emoji(b, "locker-safety") == safety and b.text("locker-address").strip() == address,
            "restored elsewhere: the same safety code and address")
    t.shot(b, "locker-1440-restored", full_page=True)


def owner_with_drop(t, device="iphone"):
    a = t.actor(device)
    drop = make_locker_with_drop(t, a, "Council")
    if a.exists("key-later"):
        a.click("key-later")
    a.wait_for("locker-address", 30)
    address = a.text("locker-address").strip()
    t.realizer.addresses.add(address)
    return a, drop, address


@scenario("deaddrop", "Dead drop: a stranger leaves a photo; Delivered; What the chain sees; the inbox opens it")
def deaddrop(t):
    a, drop, address = owner_with_drop(t)
    safety = safety_emoji(a, "locker-safety")
    a.b.drain(1)
    t.check(not a.exists("locker-qr") and not a.exists("drop-qr") and not [r for r in a.requests if plain(r["url"]).endswith("/app/ui/qr.js")],
            "a phone's locker shows no codes to scan (it is the phone that scans)")
    b = t.actor()
    b.goto(drop)
    t.check(b.wait_state("dd-root", ("ready", "closed", "not-found", "error"), 60) == "ready", "the drop page is ready")
    t.check(safety_emoji(b, "dd-safety") == safety, "it shows the owner's drive ID, the same 12 emoji as their Settings")
    t.check("Whose drive is this?" in b.text("dd-root") and b.attr("dd-safety", "aria-label").startswith("Drive ID "),
            "the drive ID, by that name (Whose drive is this?; the grid is named Drive ID for screen readers)")
    t.check(b.eval("document.querySelector('[data-testid=\"dd-label\"] bdi')?.textContent") == "Council",
            "the drop's label, isolated in a <bdi> inside the quotes")
    t.check("The server doesn't check it" in b.text("dd-root"), "the page says the link's owner wrote the label and the server doesn't check it")
    report = b.attr("dd-report", "href") or ""
    t.check(b.eval("!!document.querySelector('main [data-testid=\"dd-report\"]')") and report.startswith("/fine-print#link=")
            and urllib.parse.unquote(report) == f"/fine-print#link={drop}", f"a Report this link in the page, filled in ({report[:60]})")
    t.shot(b, "drop-1440-ready")
    # Compact (the owner's "I have to scroll just to find stuff"): Choose a file and Write a secret, side by side,
    # in the first screen on a computer and on a phone; the native input is never drawn.
    zone = """(() => { const p = document.querySelector('.md-pick').getBoundingClientRect(); const i = document.querySelector('[data-testid="dd-input"]').getBoundingClientRect();
      const [c, w] = document.querySelectorAll('.md-pick > .a-btn');
      return [c.textContent.trim(), w.textContent.trim(), Math.round(c.getBoundingClientRect().top) === Math.round(w.getBoundingClientRect().top),
              p.bottom <= innerHeight, i.width <= 1 && i.height <= 1]; })()"""
    t.check(b.eval(zone) == ["Choose a file", "Write a secret", True, True, True], f"1440: the two buttons side by side, above the fold ({b.eval(zone)})")
    ph = t.actor("iphone")
    ph.goto(drop)
    t.check(ph.wait_state("dd-root", ("ready", "closed", "not-found", "error"), 60) == "ready", "the drop page is ready on a phone")
    t.check(ph.eval(zone) == ["Choose a file", "Write a secret", True, True, True] and no_hscroll(ph),
            f"390: the two buttons side by side, above the fold, no horizontal scroll ({ph.eval(zone)})")
    t.shot(ph, "drop-390-ready")
    b.set_files("dd-input", [t.fixture("setup.exe")])
    b.wait("document.querySelector('[data-testid=\"error-banner\"]')?.dataset.code === 'program_drop'", 30)
    t.check(not [r for r in b.requests if r["url"].endswith("/api/v1/uploads")], "a program can't be left in a drop; nothing was uploaded")
    b.set_files("dd-input", [t.fixture("photo-gps.jpg")])
    b.wait("document.querySelector('[data-testid=\"exif-chip\"]')?.dataset.removed === 'true'", 60)
    t.check(b.wait_state("dd-root", ("delivered", "error"), 180) == "delivered", "Delivered")
    tx = b.attr("dd-tx", "data-tx")
    t.check(bool(re.match(r"^[0-9a-f]{64}$", tx or "")), "the delivery has a transaction id")
    t.shot(b, "drop-1440-delivered")
    b.click("dd-chain-link")
    b.wait_for("tx-root", 60)
    b.wait("document.querySelectorAll('[data-testid=\"tx-output\"]').length > 0", 30)
    t.check(b.eval("[...document.querySelectorAll('[data-testid=\"tx-output\"]')].every(e => ['hidden', 'unknown'].includes(e.dataset.amount))"),
            "What the chain sees: no output amount is shown")
    t.check(b.exists("tx-fee"), "the fee is shown, as public")
    t.shot(b, "verify-1440-tx", full_page=True)
    indexer = lambda: [r["url"] for r in b.requests if "ootle-indexer" in r["url"]]
    t.check(not indexer(), "no request to Tari's indexer before the button is pressed")
    b.eval("[...document.querySelectorAll('button')].find((e) => e.textContent.includes(\"Tari's indexer\")).click()")
    b.wait("!document.querySelector('.a-direct [data-testid=\"tx-asking\"]') && document.querySelector('.a-direct').childElementCount > 0", 30)
    t.check(len(indexer()) >= 1 and all(u.startswith(("https://ootle-indexer-a.tari.com/", "https://ootle-indexer-b.tari.com/")) for u in indexer()),
            f"the explicit button asks Tari's indexer directly ({[u[:60] for u in indexer()]})")

    t.realizer.attach(a)
    a.goto(t.origin + "/inbox")
    a.wait("!!document.querySelector('[data-testid=\"inbox-item\"][data-source=\"drop\"]')", 120)
    t.check(bool(a.wait("Number(document.querySelector('[data-testid=\"inbox-scan\"]')?.dataset.checked || 0) > 0", 30)),
            "the scan line says how many outputs it checked")
    t.shot(a, "inbox-390")
    a.eval("document.querySelector('[data-testid=\"inbox-item\"][data-source=\"drop\"] button').click()")
    t.check(a.wait_state("view-root", VIEW_END, 120) == "opened", "the owner opens what was left")
    t.check(a.exists("view-image") and a.exists("view-chain-saw"), "the photo and What the chain saw")
    amount = a.eval("(async () => { const { config } = await import('/app/lib/api.js'); const { formatTari } = await import('/app/ui/marks.js');"
                    " return formatTari((await config()).courier.amount_ut); })()")
    saw = a.text("view-chain-saw")
    t.check(f"reads {amount} tTARI" in saw, f"What the chain saw: hidden on chain, the locker reads {amount} tTARI ({saw[saw.find('Amount'):][:60]!r})")
    t.shot(a, "inbox-390-opened", full_page=True)
    close_preview(a)
    a.click("view-keep")
    a.wait("!!document.querySelector('.a-item-view .a-done')", 120)
    a.goto(t.origin + "/locker")
    a.wait("document.querySelectorAll('[data-testid=\"kept-row\"]').length >= 1", 120)
    t.check("photo-gps.jpg" in a.text("kept-row"), "Keep a copy in my locker: the photo is listed under Kept in your locker")


@scenario("send", "Send to a Tari address (relay); the locker's codes to scan; a scanned address fills the phone's send step; the recipient's inbox opens it; /watch sees it and opens nothing")
def send(t):
    a, drop, address = owner_with_drop(t, "desktop")
    safety = safety_emoji(a, "locker-safety")
    to_link, _, _ = scan_code(a, "locker-qr")
    drop_link, _, _ = scan_code(a, "drop-qr")
    t.check(to_link == f"{t.origin}/#to={address}" and drop_link == drop,
            f"a computer's locker shows its address and its drop link as codes a phone reads ({to_link and to_link[-30:]}, {drop_link})")
    t.shot(a, "locker-1440-codes", full_page=True)
    b = t.actor("android")
    b.goto(t.origin + "/send")
    b.wait_for("drop-input", 60)
    seal_text_send = "sent to an address"
    b.click("drop-write")
    b.fill("drop-textarea", seal_text_send)
    b.click("drop-seal-text")
    b.wait_for("send-recipient", 120)
    b.fill("send-recipient", address)
    b.wait_for("send-safety", 30)
    t.check(safety_emoji(b, "send-safety") == safety, "the send screen shows the recipient's safety code")
    t.shot(b, "send-412-recipient", full_page=True)
    b.click("send-submit")
    t.check(b.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "Sent")
    tx = b.attr("send-tx", "data-tx")
    t.check(bool(re.match(r"^[0-9a-f]{64}$", tx or "")), "the send has a transaction id")
    t.check("learned the address" in b.text("send-status"), "the relay sentence (C8) follows how this send went")
    t.shot(b, "send-412-sent", full_page=True)
    t.realizer.attach(a)
    a.goto(t.origin + "/inbox")
    a.wait("!!document.querySelector('[data-testid=\"inbox-item\"][data-source=\"send\"]')", 120)
    a.eval("document.querySelector('[data-testid=\"inbox-item\"][data-source=\"send\"] button').click()")
    t.check(a.wait_state("view-root", VIEW_END, 120) == "opened" and a.text("view-text") == seal_text_send, "the recipient opens what was sent")
    # The drive's address scanned by a phone: the home's widget says where it goes, the send step filled in.
    m = t.actor("iphone")
    home(t, m, f"/#to={address}")
    m.wait("!!document.querySelector('[data-testid=\"to-address\"]')", 30)
    t.check(m.text("to-address") == f"To {address[:15]}…{address[-6:]}",
            "the scanned address opens the home's widget with where it goes")
    t.shot(m, "home-390-courier")
    seal_text(m, "scanned and sent")
    m.wait(f"document.querySelector('[data-testid=\"send-recipient\"]')?.value === {json.dumps(address)} && !!document.querySelector('[data-testid=\"send-safety\"]')", 180)
    t.check(safety_emoji(m, "send-safety") == safety and m.eval("document.activeElement?.dataset?.testid") == "send-submit",
            "after the drop the send step is open with the address filled in, its safety code shown, Send focused")
    t.shot(m, "home-390-courier-send", full_page=True)
    m.click("send-submit")
    t.check(m.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "sent from the phone to the scanned address")
    a.goto(t.origin + "/locker")
    a.wait_for("watch-mine", 60)
    a.click("watch-mine")
    a.wait("Number(document.querySelector('[data-testid=\"watch-summary\"]')?.dataset.deliveries || 0) >= 1", 120)
    t.check(a.attr("watch-summary", "data-readable") == "0", "/watch with the locker's view key: deliveries seen, 0 files readable")
    t.shot(a, "watch-1440-mine", full_page=True)
    a.goto(t.origin + "/locker")
    a.wait_for("export-view-key", 30)
    a.click("export-view-key")
    a.wait_for("view-key-value")
    view_key = a.value("view-key-value")
    c = t.actor("iphone")
    t.realizer.attach(c)
    c.goto(t.origin + "/watch")
    c.wait_for("watch-address", 60)
    c.fill("watch-address", address)
    c.fill("watch-viewkey", view_key)
    c.click("watch-run")
    c.wait("Number(document.querySelector('[data-testid=\"watch-summary\"]')?.dataset.deliveries || 0) >= 1", 120)
    t.check(c.attr("watch-summary", "data-readable") == "0", "another browser with the exported view key: 0 files readable")
    t.check(c.eval("document.querySelectorAll('[data-testid=\"watch-row\"]').length") >= 1, "the rows list the arrivals")
    t.shot(c, "watch-390-viewkey", full_page=True)
    d = t.actor()
    d.goto(t.origin + "/watch")
    d.wait_for("watch-address", 60)
    d.fill("watch-address", address)
    d.fill("watch-viewkey", "00" * 32)
    d.click("watch-run")
    d.wait("!!document.querySelector('[data-testid=\"error-banner\"]')", 30)
    t.check(d.attr("error-banner", "data-code") == "address_mismatch", "a view key of another address is refused")


@scenario("kind4", "Kind 4: a /t#4 link opens with the address's view key alone; kind 3 refuses it")
def kind4(t):
    a, _, address = owner_with_drop(t, "desktop")
    a.goto(t.origin + "/locker")
    a.wait_for("export-view-key", 30)
    a.click("export-view-key")
    view_key = a.value("view-key-value")
    b = t.actor()
    b.goto(t.origin + "/send")
    b.wait_for("drop-input", 60)
    b.click("drop-write")
    b.fill("drop-textarea", "for another wallet")
    b.click("drop-seal-text")
    b.wait_for("send-recipient", 120)
    for wrong, words in (("2" * 70, "base-layer"), ("otl_main_1qqqqqqqqqqqq", "not a testnet"), ("hello", "Ootle address")):
        b.fill("send-recipient", wrong)
        b.wait(f"document.getElementById('a-recipient-msg').textContent.includes({json.dumps(words)})", 10)
        t.check(not b.visible("send-safety"), f"the address check explains it: {words}")
    b.fill("send-recipient", address)
    b.wait_for("send-safety", 30)
    b.click("send-kind", "4")
    t.check(b.eval("!document.querySelector('.a-send .a-warn').hidden"), "kind 4 shows its warning")
    b.click("send-submit")
    t.check(b.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "Sent in other-wallet mode")
    t.realizer.attach(a)
    a.goto(t.origin + "/inbox")
    a.wait("!!document.querySelector('[data-testid=\"inbox-item\"]')", 120)
    memo = next((m["Message"] for m in t.realizer.memos if isinstance(m, dict) and "/t#4" in m.get("Message", "")), "")
    t.check(memo.startswith("https://mutis.sh/t#4"), "the delivery's memo is a /t#4 link")
    link = t.origin + "/t#" + memo.split("#", 1)[1]
    c = t.actor("iphone")
    c.goto(link)
    t.check(c.wait_state("view-root", VIEW_ASK, 60) == "needs-locker", "a browser without a locker is asked for a key")
    t.shot(c, "view-390-needs-locker")
    c.fill("t-viewkey", view_key)
    c.click("t-viewkey-submit")
    t.check(c.wait_state("view-root", ("ready", "opened", "error", "wrong-key"), 60) in ("ready", "opened"), "the view key alone unlocks a kind-4 link")
    if c.state("view-root") == "ready":
        c.click("view-open")
        c.wait_state("view-root", VIEW_END, 60)
    t.check(c.text("view-text") == "for another wallet", "and it is the text that was sent")


@scenario("upgrade", "Upgrade: s30 with demo tTARI; Waiting → Seen on chain → Amount proven → Added")
def upgrade(t):
    a = t.actor("iphone")
    make_locker_with_drop(t, a, "pack test")
    if a.exists("key-later"):
        a.click("key-later")
    a.wait_for("quota-bar", 30)
    before = int(a.attr("quota-bar", "data-limit"))
    a.goto(t.origin + "/upgrade")
    a.wait_for("pack-s30", 60)
    plans = a.eval("[...document.querySelectorAll('.a-plan .a-card-h')].map((e) => e.textContent)")
    t.check(plans[1:] == ["+256 MB for 30 days", "+1 GB for 30 days"], f"the packs read +256 MB and +1 GB for 30 days ({plans})")
    t.shot(a, "upgrade-390-plans", full_page=True)
    a.click("pack-s30")
    a.wait_for("invoice-address", 60)
    t.check(a.value("invoice-address").startswith("otl_esm_1"), "the invoice has a Tari address")
    a.click("demo-pay")
    a.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 180)
    steps = a.eval("[...document.querySelectorAll('[data-testid=\"pay-step\"]')].map(e => e.dataset.step + ':' + e.dataset.done)")
    t.check(steps == ["waiting:true", "seen:true", "proven:true", "added:true"], f"the stepper reaches Added ({steps})")
    t.shot(a, "upgrade-390-credited", full_page=True)
    a.goto(t.origin + "/locker")
    a.wait_for("quota-bar", 60)
    t.check(int(a.attr("quota-bar", "data-limit")) >= before + 256 * 1024 ** 2, "the quota grew by the pack's 256 MiB")

    # After Nov 11 the testnet line changes by itself, in step with the footer (D13).
    p = t.actor()
    p.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "Date.now = () => Date.UTC(2026, 10, 12, 12)"})
    p.goto(t.origin + "/upgrade")
    line = p.wait("document.querySelector('.a-testnet')?.textContent", 60)
    footer = p.eval("!document.querySelector('footer [data-phase-show=\"mainnet\"]')?.hidden")
    t.check("mainnet is live" in line and footer, f"on Nov 12 the testnet line says the mainnet is live, like the footer ({line[:80]})")


@scenario("upgrade-wallet", "Upgrade in production's payment mode (amount_proof = wallet): Waiting → Seen by our wallet → Exists on chain → Added",
          amount_proof="wallet")
def upgrade_wallet(t):
    a = t.actor("iphone")
    make_locker_with_drop(t, a, "pack test")
    if a.exists("key-later"):
        a.click("key-later")
    a.goto(t.origin + "/upgrade")
    a.wait_for("pack-s30", 60)
    a.click("pack-s30")
    a.wait_for("invoice-address", 60)
    labels = a.eval("[...document.querySelectorAll('[data-testid=\"pay-step\"]')].map((e) => e.textContent.trim())")
    t.check(labels == ["Waiting", "Seen by our wallet", "Exists on chain", "Added"], f"the stepper names the checks this mode runs ({labels})")
    claim = a.eval("document.querySelector('.a-invoice').textContent")
    t.check("our wallet sees it" in claim and "official Tari library" not in claim, "the claim under it is the wallet variant (C11)")
    a.click("demo-pay")
    a.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 180)
    steps = a.eval("[...document.querySelectorAll('[data-testid=\"pay-step\"]')].map(e => e.dataset.step + ':' + e.dataset.done)")
    t.check(steps == ["waiting:true", "seen_wallet:true", "exists:true", "added:true"], f"paid with demo tTARI, every step is reached ({steps})")
    t.shot(a, "upgrade-390-credited-wallet", full_page=True)


def b64u(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@scenario("receipts", "P1 /verify: the locked file's own hash is kept; proofs are checked against the SealLog state on chain; a log with an owner is refused")
def receipts(t):
    a = t.actor()
    home(t, a)
    seal_text(a, "a receipt for this")
    mine = a.eval("JSON.parse(localStorage.getItem('mutis.recent'))[0]")
    served = a.eval(f"fetch('/api/v1/s/{mine['share_id']}/manage', {{ headers: {{ 'X-Mutis-Manage': {json.dumps(mine['manage_token'])} }} }})"
                    ".then((r) => r.json()).then((j) => j.item.ct_hash)")
    t.check(bool(mine.get("ct_hash")) and mine["ct_hash"] == served, "this device keeps the ciphertext hash it computed when locking (equal to our server's)")

    # The template builder's vectors: the 2.0.0 component state on chain, and leaves with their proofs.
    vectors = os.path.join(REPO, "template", "seal_log", "tests", "vectors")
    state = json.load(open(os.path.join(vectors, "seallog-state-v1.json"), encoding="utf-8"))
    v = json.load(open(os.path.join(vectors, "seallog-v1.json"), encoding="utf-8"))
    research = json.load(open(os.path.join(REPO, "web", "app", "tests", "vectors", "seallog-component.json"), encoding="utf-8"))
    stored, exited = v["leaves"][0], v["leaves"][64]
    cp = next(c for c in v["checkpoints"] if int(c["tree_size"]) == 128)
    path = {int(p["leaf_index"]): p["path"] for p in cp["proofs"]}
    component = "component_" + "fd" * 32
    checkpoint = {"index": 9, "component": component, "tree_size": 128, "epoch": 12128, "root": cp["root"]}  # /verify prints the log's own number
    good, altered = "receipts" + "A" * 14, "altered" + "A" * 15
    recent = [{"share_id": good, "item_id": stored["item_id_b64u"], "ct_hash": b64u(bytes.fromhex(stored["ct_hash"])), "expires": int(time.time()) + 3600},
              {"share_id": altered, "item_id": stored["item_id_b64u"], "ct_hash": b64u(os.urandom(32)), "expires": int(time.time()) + 3600}]

    def page(substate):
        p = t.actor()
        (Intercept(p)
         .add("*/api/v1/config", "Response", lambda cfg: {**cfg, "features": {**cfg["features"], "seallog": True},
                                                           "seal_log": {**cfg["seal_log"], "component": component}})
         .add("*/api/v1/chain/ix/substates/component_*", "Request", lambda _p: (200, substate))
         .add(f"*/api/v1/s/{good}/exit", "Request", lambda _p: (200, {"reason": "burned", "item_id": exited["item_id_b64u"],
                                                                   "exit_hour": int(exited["exit_hour_unix"]), "leaf_hash": exited["leaf_hash"],
                                                                   "leaf_index": 64, "proof": path[64], "checkpoint": checkpoint}))
         .add(f"*/api/v1/s/{altered}/exit", "Request", api_error("conflict", 409))
         .add(f"*/api/v1/seallog/proof/{stored['item_id_b64u']}", "Request", lambda _p: (200, {"item_id": stored["item_id_b64u"], "kind": "stored",
                                                                                           "leaf_hash": stored["leaf_hash"], "leaf_index": 0,
                                                                                           "proof": path[0], "checkpoint": checkpoint})))
        p.goto(t.origin + "/")
        p.eval(f"localStorage.setItem('mutis.recent', {json.dumps(json.dumps(recent))})")
        p.goto(t.origin + "/verify")
        return p

    b = page(state)
    b.wait("document.querySelectorAll('[data-testid=\"verify-stored\"]').length === 2 && "
           "![...document.querySelectorAll('[data-testid=\"verify-stored\"]')].some((e) => /Checking/.test(e.textContent))", 60)
    lines = b.eval("[...document.querySelectorAll('[data-testid=\"verify-item\"]')].map((e) => e.textContent)")
    t.check("Stored: included at checkpoint #1 (epoch 12128)" in lines[0], f"the file's own hash is in the tree on chain, at the log's checkpoint #1 ({lines[0][:120]})")
    t.check("Exit: included at checkpoint #1 (epoch 12128)" in lines[0], "its exit too, from the hour our server reports")
    t.check("doesn't match" in lines[1] and "Exit:" not in lines[1], "a hash this file didn't have doesn't verify against the same root")
    about = b.text("verify-log")
    t.check("has no owner" in about and "d884dd886cc746" in about, f"the page says the log has no owner and names its one writer key ({about[:90]})")
    t.shot(b, "verify-1440-receipts", full_page=True)
    c = page(research)
    c.wait_for("error-banner", 60)
    t.check("trustworthy" in c.text("error-banner") and not c.exists("verify-item"),
            "the research log on Esmeralda (it has an owner) is refused; nothing is checked against it")


# --- accessibility, keyboard, layout, no-WebAssembly -----------------------------------------------------

@scenario("keyboard", "Keyboard only: drop and copy; open; make a drop link; leave a file; send; buy; watch")
def keyboard(t):
    a = t.actor()
    home(t, a)
    t.check(not a.ax_unnamed(), f"home: every control has an accessible name ({a.ax_unnamed()[:5]})")
    t.check(a.tab_to("a.dataset.testid === 'drop-write'"), "Tab reaches Write a secret")
    a.key("Enter", text="\r")
    a.wait_for("drop-textarea")
    a.type_text("typed with the keyboard")
    a.key("Enter", modifiers=2)
    url = wait_link(a)
    t.check(a.eval("document.activeElement?.dataset?.testid") == "copy-link", "focus lands on Copy link")
    a.key("Enter", text="\r")
    t.check(a.wait("navigator.clipboard.readText()", 10) == url, "Enter copies the link")
    t.check(not a.ax_unnamed(), f"the locked card: every control named ({a.ax_unnamed()[:5]})")
    b = t.actor()
    b.goto(url)
    b.wait_state("view-root", ("ready",), 60)
    t.check(b.eval("document.activeElement?.dataset?.testid") == "view-open", "the viewer focuses Open it")
    b.key("Enter", text="\r")
    t.check(b.wait_state("view-root", VIEW_END, 60) == "opened", "Enter opens it")
    try:   # the preview's module loads after the file opens, then takes the focus
        lit = bool(b.wait("!!document.activeElement?.closest('#lightbox')", 10))
    except TimeoutError:
        lit = False
    t.check(lit, "it shows in the preview, which takes the focus")
    b.key("Escape")
    b.wait("!document.getElementById('lightbox')", 10)
    t.check(b.eval("document.activeElement?.dataset?.testid") == "view-show", "Esc closes it; focus is on the card that opens it again")
    o = t.actor()
    o.goto(t.origin + "/locker")
    o.wait_for("drop-create", 60)
    t.check(not o.ax_unnamed(), f"/locker: every control named ({o.ax_unnamed()[:5]})")
    t.check(o.tab_to("a.dataset.testid === 'drop-create'"), "Tab reaches Make my drop link (nothing is asked first)")
    o.key("Enter", text="\r")
    drop = o.wait("(() => { const e = document.querySelector('[data-testid=\"drop-link\"]'); return e?.value?.includes('/d/') ? e.value : ''; })()", 120)
    o.wait("!!document.querySelector('dialog[open]')", 30)
    t.check(o.eval("document.querySelector('dialog[open]').contains(document.activeElement)"), "the key modal takes the focus")
    o.key("Escape")
    o.wait("!document.querySelector('dialog[open]')", 10)
    t.check(True, "Escape closes the key modal")
    t.check(not o.ax_unnamed(), f"the locker: every control named ({o.ax_unnamed()[:5]})")
    s = t.actor()
    s.goto(drop)
    s.wait_state("dd-root", ("ready",), 60)
    t.check(not s.ax_unnamed(), f"the drop page: every control named ({s.ax_unnamed()[:5]})")
    t.check(s.tab_to("a.dataset.testid === 'drop-write'"), "Tab reaches Write a secret on the drop page")
    s.key("Enter", text="\r")
    s.wait_for("drop-textarea")
    s.type_text("left with the keyboard")
    s.key("Enter", modifiers=2)
    t.check(s.wait_state("dd-root", ("delivered", "error"), 180) == "delivered", "left in the drop with the keyboard")
    address = o.text("locker-address").strip() if o.exists("locker-address") else ""
    o.goto(t.origin + "/send")
    o.wait_for("drop-input", 60)
    o.tab_to("a.dataset.testid === 'drop-write'")
    o.key("Enter", text="\r")
    o.wait_for("drop-textarea")
    o.type_text("sent with the keyboard")
    o.key("Enter", modifiers=2)
    o.wait_for("send-recipient", 120)
    t.check(o.eval("document.activeElement?.dataset?.testid") == "send-recipient", "focus moves to the recipient field")
    o.type_text(address)
    o.wait_for("send-safety", 30)
    t.check(o.tab_to("a.dataset.testid === 'send-submit'"), "Tab reaches Send")
    o.key("Enter", text="\r")
    t.check(o.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "sent with the keyboard")
    t.check(not o.ax_unnamed(), f"/send: every control named ({o.ax_unnamed()[:5]})")
    o.goto(t.origin + "/upgrade")
    o.wait_for("pack-s30", 60)
    t.check(o.tab_to("a.dataset.testid === 'pack-s30'"), "Tab reaches the s30 pack")
    o.key("Enter", text="\r")
    o.wait_for("demo-pay", 60)
    t.check(o.tab_to("a.dataset.testid === 'demo-pay'"), "Tab reaches Pay with demo tTARI")
    o.key("Enter", text="\r")
    o.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 180)
    t.check(True, "a pack bought with the keyboard")
    t.check(not o.ax_unnamed(), f"/upgrade: every control named ({o.ax_unnamed()[:5]})")
    o.goto(t.origin + "/watch")
    o.wait_for("watch-address", 60)
    t.check(o.tab_to("a.textContent.trim() === \"Use my drive's view key\""), "Tab reaches Use my drive's view key")
    o.key("Enter", text="\r")
    t.check(o.tab_to("a.dataset.testid === 'watch-run'"), "Tab reaches Look")
    o.key("Enter", text="\r")
    o.wait_for("watch-summary", 120)
    t.check(True, "watched with the keyboard")
    t.check(not o.ax_unnamed(), f"/watch: every control named ({o.ax_unnamed()[:5]})")


APP_PAGES = ["/", "/locker", "/inbox", "/send", "/watch", "/upgrade", "/verify", "/t", "/verify/tx/" + "0" * 64,
             "/s/" + "A" * 22, "/d/" + "2" * 10]


@scenario("layout", "Every app page: no horizontal scroll at 360 px, only same-origin requests, no violations")
def layout(t):
    for device in ("narrow", "iphone", "desktop"):
        p = t.actor(device)
        wide = []
        for path in APP_PAGES:
            p.goto(t.origin + path)
            p.b.drain(1.5)
            if not no_hscroll(p):
                wide.append(path)
        t.check(not wide, f"{device}: no horizontal scroll ({wide})")
        t.check(not same_origin(t, p), f"{device}: no third-party request ({same_origin(t, p)[:3]})")


@scenario("nowasm", "Without WebAssembly (--jitless): anonymous drop and open work; locker pages say needs_wasm",
          args=("--js-flags=--jitless",))
def nowasm(t):
    a = t.actor()
    home(t, a)
    url = seal_text(a, "no wasm here")
    b = t.actor()
    t.check(open_link(b, url) == "opened" and b.text("view-text") == "no wasm here", "an anonymous drop opens without WebAssembly")
    for path in ("/locker", "/d/" + "2" * 10, "/inbox", "/watch"):
        a.goto(t.origin + path)
        a.wait("!!document.querySelector('[data-code=\"needs_wasm\"]')", 30)
        t.check(True, f"{path} shows needs_wasm")
    t.shot(a, "watch-1440-needs-wasm")


@scenario("dark", "Dark theme and reduced motion: the card, the viewer, the locker")
def dark(t):
    a = t.actor("desktop", dark=True, reduced_motion=True)
    home(t, a)
    url = seal_text(a, "in the dark")
    t.check(a.eval("getComputedStyle(document.body).backgroundColor") == "rgb(10, 10, 10)", "the drive's dark background in dark mode")
    t.shot(a, "home-1440-dark-sealed")
    b = t.actor("iphone", dark=True, reduced_motion=True)
    t.check(open_link(b, url) == "opened", "opens in dark mode with reduced motion")
    t.shot(b, "view-390-dark-opened")
    b.goto(t.origin + "/locker")
    b.wait_for("drop-create", 60)
    t.shot(b, "locker-390-dark-empty", full_page=True)


# A-06's 40 KB holds for a first drop of text on a phone, counted as the server sends it (sent_bytes: the Brotli copy;
# docs/review/perf-1.md; gzip -9 of each file is printed beside it). A file also loads lib/filetype.js,
# lib/download.js and, for a photo, lib/exif.js (recipient safety and metadata removal); this ceiling
# keeps that honest. On a fine pointer the result also shows the link as a code to scan, and the
# encoder (ui/qr.js) loads then: QR_CEILING is that waiver (14-ghost-design §17 step 0, A06.md), so a
# phone's first drop stays at 40,960 B and never loads the encoder.
PHOTO_CEILING = 48 * 1024
QR_CEILING = 42.5 * 1024


@scenario("budget", "A-06: what the home page loads for the widget, before and after a drop (phone; computer with the code to scan)")
def budget(t):
    dist = os.path.join(t.work, "dist")

    gz9 = {}

    def size(page):
        total, gz, files = 0, 0, []
        for u in sorted({r["url"] for r in page.requests if r["url"].startswith((t.origin + "/app/", t.origin + "/vendor/"))}):
            path = os.path.join(dist, u[len(t.origin) + 1:].split("?")[0])
            if os.path.isfile(path):
                sent, g = sent_bytes(path)
                total, gz = total + sent, gz + g
                files.append(plain(u[len(t.origin):]))
        gz9[id(page)] = gz
        return total, files
    a = t.actor("iphone")
    home(t, a)
    a.b.drain(2)
    at_load, files = size(a)
    t.check(not any("ootle_wasm" in f for f in files), "no ootle-wasm on the home page before a locker action")
    seal_text(a, "budget")
    a.b.drain(1)
    after, files = size(a)
    t.check(after <= 40 * 1024 and "/app/ui/qr.js" not in files,
            f"phone: widget payload compressed: {at_load} B at load, {after} B after a drop (≤ 40 KB; gzip -9: {gz9[id(a)]} B), no code encoder")
    t.check(not any("ootle_wasm" in f for f in files), "still no ootle-wasm after an anonymous drop")
    d = t.actor("desktop")
    home(t, d)
    seal_text(d, "budget")
    d.wait_for("link-qr", 30)
    desk, files = size(d)
    t.check(desk <= QR_CEILING and "/app/ui/qr.js" in files,
            f"computer: {desk} B after a drop with the code to scan (≤ {int(QR_CEILING)} B, the QR waiver)")
    print(f"  A-06 measured: computer {desk} B as sent (gzip -9 of the same files: {gz9[id(d)]} B), files: {', '.join(files)}")
    p = t.actor("iphone")
    home(t, p)
    p.set_files("drop-input", [t.fixture("photo-gps.jpg")])
    wait_link(p)
    p.b.drain(1)
    photo, _ = size(p)
    t.check(photo <= PHOTO_CEILING, f"phone, after a photo: {photo} B (≤ {PHOTO_CEILING} B; A-06 waiver: the file-type check and "
                                   "the metadata stripper load for files, P-14 and §4.13)")


@scenario("ten-seconds", "A first visit on a phone (4× slower CPU): landing to a copied link of a photo in under 10 s")
def ten_seconds(t):
    a = t.actor("android")
    a.cmd("Emulation.setCPUThrottlingRate", {"rate": 4})
    started = time.time()
    home(t, a)
    ready = time.time() - started
    a.set_files("drop-input", [t.fixture("photo-gps.jpg")])
    wait_link(a)
    a.click("copy-link")
    copied = a.wait("navigator.clipboard.readText().then((x) => x.includes('/s/'))", 10)
    total = time.time() - started
    t.check(copied and total < 10, f"landing {ready:.1f} s, then photo to copied link: {total:.1f} s in all (< 10 s, no human pauses)")


def flip_a_bit(data):
    """One flipped bit in the stored ciphertext of an /open answer."""
    raw = bytearray(base64.urlsafe_b64decode(data["inline_ct"] + "=" * (-len(data["inline_ct"]) % 4)))
    raw[10] ^= 1
    return {**data, "inline_ct": base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")}


@scenario("states", "Every remaining state: expired (a real 60-second link), removed, locked, integrity-error; drop closed and not found; empty inbox")
def states(t):
    # A test deployment's /config offers a 60-second preset (spec §17.1, E-05); this run's /config
    # gets the field the way such a deployment would send it.
    x = t.actor()
    Intercept(x).add("*/api/v1/config", "Response", lambda cfg: {**cfg, "e2e_expiry_s": 60})
    home(t, x)
    seal_text(x, "leaves in a minute")
    short = apply_rules(x, expiry="60")
    short_at = time.time()
    t.check(0 < int(x.eval("document.querySelector('.md-card').dataset.expiresAt")) - short_at <= 62, "the 60-second preset sets the link to leave within a minute")

    a = t.actor()
    home(t, a)
    url = seal_text(a, "states")
    sid = url.split("/s/")[1].split("#")[0]
    # States the dev server can't reach on cue (an abuse takedown, a permanent password lock) are its
    # own answers, replayed.
    for reason, state in (("expired", "expired"), ("removed", "removed"), ("owner_deleted", "revoked")):
        p = t.actor()
        gone = {"error": {"code": "gone", "message": "This link has ended.", "details": {"reason": reason, "ended_day": "2026-10-31", "views": 0}}}
        Intercept(p).add(f"*/api/v1/s/{sid}", "Request", lambda _params, body=gone: (410, body))
        t.check(open_link(p, url) == state, f"a link that ended as {reason}: {state}")
        if reason == "expired":
            t.shot(p, "view-1440-expired")
    p = t.actor("iphone")
    Intercept(p).add(f"*/api/v1/s/{sid}/peek", "Request", lambda _params: (423, {"error": {"code": "locked", "message": "Locked.", "details": {"permanent": True}}}))
    t.check(open_link(p, url, open_it=False) == "locked", "a link locked after too many wrong passwords: locked")
    t.shot(p, "view-390-locked")
    q = t.actor()
    q.goto(url)
    q.wait_state("view-root", ("ready",), 60)
    Intercept(q).add(f"*/api/v1/s/{sid}/open", "Response", flip_a_bit)
    q.click("view-open")
    t.check(q.wait_state("view-root", VIEW_END, 60) == "integrity-error", "one flipped bit in the stored bytes: integrity-error, nothing shown")
    t.check(not q.exists("view-text") and not q.exists("view-save"), "no plaintext and no Save after an integrity failure")
    t.shot(q, "view-1440-integrity")

    o = t.actor()
    drop = make_locker_with_drop(t, o, "to be closed")
    if o.exists("key-later"):
        o.click("key-later")
    o.click("drop-close")
    o.wait_for("drop-create", 60)
    c = t.actor()
    c.goto(drop)
    t.check(c.wait_state("dd-root", ("ready", "closed", "not-found", "error"), 60) == "closed", "a closed drop: This drop is closed.")
    c.goto(t.origin + "/d/" + "2" * 10)
    t.check(c.wait_state("dd-root", ("ready", "closed", "not-found", "error"), 60) == "not-found", "an unknown drop: No drop here.")
    home(t, a)
    a.wait("!!document.querySelector('.md-recent')", 30)
    a.eval("document.querySelector('.md-recent').open = true")
    state = a.wait("(() => { const s = document.querySelector('.md-recent-state'); return s && !/checking/.test(s.textContent) ? s.textContent : ''; })()", 30)
    t.check(bool(state) and str(time.localtime().tm_year) in state, f"recent drops on this device list the links with their state ({state})")
    o.goto(t.origin + "/inbox")
    o.wait_for("inbox-empty", 120)
    t.check(o.exists("inbox-root") and o.visible("inbox-empty"), "a new locker's inbox: Nothing for you yet")
    t.shot(o, "inbox-1440-empty")

    time.sleep(max(0, short_at + 65 - time.time()))
    e = t.actor()
    t.check(open_link(e, short) == "expired", "65 seconds later the real server answers: expired")
    t.check("Its time ran out." in e.text("view-root"), "This link has ended. Its time ran out.")


# 16-drive-design §0 (no ghost): the link and task pages carry no ghost and set their words in Geist,
# with a Lucide tile as each screen's icon.
@scenario("no-ghost", "No ghost: /send and the link page carry no ghost template or figure; Geist; a Lucide tile")
def no_ghost(t):
    for dark in (False, True):
        a = t.actor("desktop", dark=dark)
        for path in ("/send", "/watch", "/s/AAAAAAAAAAAAAAAAAAAAAA#1" + "A" * 43):
            a.goto(t.origin + path)
            a.wait("!!document.querySelector('.a-scene-h, [data-testid=\"view-root\"][data-state]:not([data-state=\"loading\"])')", 60)
            t.check(a.eval("!document.getElementById('ghost-tpl') && !document.querySelector('svg.ghost, [data-ghost]')"),
                    f"{path.split('#')[0]}: no ghost template and no ghost")
            t.check(a.eval("![...document.styleSheets].some((x) => (x.href || '').includes('ghost'))"), f"{path.split('#')[0]}: no ghost.css")
            font = a.eval("getComputedStyle(document.querySelector('.a-scene-h') || document.body).fontFamily")
            t.check("Geist" in font, f"{path.split('#')[0]}: Geist ({font[:40]})")
            tile = a.eval("document.querySelector('.a-figure use')?.getAttribute('href') ?? ''")
            t.check(plain(tile).startswith("/shared/ui/icons.svg#i-"), f"{path.split('#')[0]}: a Lucide tile ({tile})")
        t.shot(a, f"no-ghost-{'dark' if dark else 'light'}")


# --- the window drop and the wow (14-ghost-design §5, §6) ----------------------------------------------

WOW_WATCH = r"""(() => {
  window.__anims = []; window.__clip = []; window.__marks = [];
  const animate = Element.prototype.animate;
  Element.prototype.animate = function (k, o) {
    const a = animate.call(this, k, o);
    const cls = this.className?.baseVal ?? this.className ?? this.tagName;
    const rec = { cls: String(cls), start: performance.now(), dur: o?.duration ?? o };
    window.__anims.push(rec);
    a.finished.then(() => { rec.end = performance.now(); }, () => { rec.end = -1; });
    return a;
  };
  const write = navigator.clipboard.writeText.bind(navigator.clipboard);
  navigator.clipboard.writeText = (s) => write(s).then(() => { window.__clip.push(['ok', performance.now()]); },
    (e) => { window.__clip.push(['fail:' + e.name, performance.now()]); throw e; });
  addEventListener('drop', () => { window.__drop = performance.now(); }, true);
  addEventListener('DOMContentLoaded', () => new MutationObserver(() => window.__marks.push(['phase:' + document.body.dataset.phase, performance.now()]))
    .observe(document.body, { attributes: true, attributeFilter: ['data-phase'] }));
})();"""
# A share sheet for the phone actor (headless Chromium on Linux has none): it records what it was given.
FAKE_SHARE = "Object.defineProperty(Navigator.prototype, 'share', { configurable: true, value: async (d) => { window.__shared = d; } });"
PHASE = "document.body.dataset.phase"


def _png(w=8, h=8):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes([200, 40, 90] * w) for _ in range(h))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


TINY_PNG = _png()
LINK = "(document.querySelector('[data-testid=\"sealed-link\"]')?.value ?? '')"
RESULT_CONTROLS = r"""[...document.querySelectorAll('.md-result :is(a[href], button, input, summary)')]
  .filter((e) => e.checkVisibility() && !e.closest('[hidden]'))
  .map((e) => { const r = e.getBoundingClientRect(); return [e.dataset.testid || e.textContent.trim().slice(0, 24) || e.tagName, Math.round(r.height)]; })"""


def wow_page(t, device="desktop", reduced=False, share=False):
    p = t.actor(device, reduced_motion=reduced)
    p.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": WOW_WATCH + (FAKE_SHARE if share else "")})
    home(t, p)
    p.wait("!!document.querySelector('.md-root')", 30)
    return p


def drag(p, kind, path, x=210, y=610):
    p.cmd("Input.dispatchDragEvent", {"type": kind, "x": x, "y": y, "data": {"items": [], "files": [path], "dragOperationsMask": 1}})


def tap(p, css):
    x, y = p.eval(f"(() => {{ const r = document.querySelector({json.dumps(css)}).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
    if p.device["mobile"]:
        for kind, points in (("touchStart", [{"x": x, "y": y}]), ("touchEnd", [])):
            p.cmd("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})
    else:
        p.cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            p.cmd("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})


def wow_times(p):
    tl = p.eval("({drop: window.__drop ?? null, marks: window.__marks, anims: window.__anims, clip: window.__clip})")
    d = tl["drop"] or 0
    done = next((at for m, at in tl["marks"] if m == "phase:done"), None)
    clip = next((at for m, at in tl["clip"]), None)
    card = [a for a in tl["anims"] if "md-card" in a["cls"]]
    settled = max((a.get("end") or 0) for a in card) if card else done
    rnd = lambda at: round(at - d) if at else None  # noqa: E731
    return {"copied_ms": rnd(clip), "result_ms": rnd(done), "settled_ms": rnd(settled),
            "anims": sorted({(a["cls"].split()[0], a["dur"]) for a in tl["anims"]})}


# The viewer's rule with its time (share-simple): "Opens one time, until Oct 22, 9:00 PM. Then it's gone."
WHEN = r"[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2}\s[AP]M"
ONCE_UNTIL = rf"Opens one time, until {WHEN}\. Then it's gone\."


def scan_code(p, testid):
    """Reads the code the page drew (testid on its <figure>) the way a phone would, correcting what Reed-Solomon
    corrects (the modules under the mark): (payload, px per module, the read-back)."""
    d, view, px = p.wait(f"(() => {{ const s = document.querySelector('[data-testid=\"{testid}\"] svg'); return s ? [s.querySelector('path').getAttribute('d'),"
                         " s.viewBox.baseVal.width, s.getBoundingClientRect().width] : null; })()", 30)
    got = qrread.scan(d, view)
    ok = got["format_ok_both_copies"] and got["rs_ok_all_blocks"] and got["mode"] == 4
    return (got["payload"] if ok else None), px / view, got


def press_paste(p):
    p.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "v", "code": "KeyV", "windowsVirtualKeyCode": 86, "modifiers": 2, "commands": ["paste"]})
    p.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "v", "code": "KeyV", "windowsVirtualKeyCode": 86, "modifiers": 2})


# --- the rule on the figure (14-ghost-design §5, §17 step 6) --------------------------------------------

SAY = "document.querySelector('.md-say')?.textContent ?? ''"
POSE = "document.querySelector('.md-result svg.ghost')?.dataset.state ?? ''"


def rule_state(p):
    return p.eval(f"[{LINK}, document.querySelector('.md-card').dataset.maxViews, {POSE},"
                  " document.querySelector('.md-counts input:checked')?.value ?? '', document.querySelector('.md-live').textContent]")


# --- 14-ghost-design §17 step 8: every app screen on the ghost, at 390 and 1440 ---------------------------

def seallog_on(t, p, share_id, receipt):
    """Test-only: this page's /config turns receipts on, and the exit receipt of `share_id` is
    `receipt` ("done": in checkpoint #1 of the template builder's vectors; "pending": waits)."""
    vectors = os.path.join(REPO, "template", "seal_log", "tests", "vectors")
    state = json.load(open(os.path.join(vectors, "seallog-state-v1.json"), encoding="utf-8"))
    v = json.load(open(os.path.join(vectors, "seallog-v1.json"), encoding="utf-8"))
    exited = v["leaves"][64]
    cp = next(c for c in v["checkpoints"] if int(c["tree_size"]) == 128)
    path = {int(x["leaf_index"]): x["path"] for x in cp["proofs"]}
    component = "component_" + "fd" * 32
    checkpoint = {"index": 9, "component": component, "tree_size": 128, "epoch": 12128, "root": cp["root"]}
    body = ({"reason": "burned", "item_id": exited["item_id_b64u"], "exit_hour": int(exited["exit_hour_unix"]),
             "leaf_hash": exited["leaf_hash"], "leaf_index": 64, "proof": path[64], "checkpoint": checkpoint}
            if receipt == "done" else
            {"reason": "burned", "item_id": exited["item_id_b64u"], "exit_hour": None, "leaf_hash": None, "leaf_index": None,
             "checkpoint": None, "proof": {"pending": True, "next_checkpoint_eta": int(time.time()) + 600}})
    (Intercept(p)
     .add("*/api/v1/config", "Response", lambda cfg: {**cfg, "features": {**cfg["features"], "seallog": True},
                                                       "seal_log": {**cfg["seal_log"], "component": component}})
     .add("*/api/v1/chain/ix/substates/component_*", "Request", lambda _p: (200, state))
     .add(f"*/api/v1/s/{share_id}/exit", "Request", lambda _p: (200, body)))


@scenario("ghost-screens", "Step 8 at 390 and 1440 (no ghost): the viewer, the gone page (on chain and pending), the locker (first screen, key, with a locker), the inbox, send, /watch, /upgrade, /verify")
def ghost_screens(t):
    for device, w in (("iphone", 390), ("desktop", 1440)):
        maker = t.actor()
        home(t, maker)
        url = seal_text(maker, "The office key is under the plant.")
        sid = url.split("/s/")[1].split("#")[0]
        v = t.actor(device)
        t.check(open_link(v, url, open_it=False) == "ready", f"{w}: the viewer is ready")
        pose = v.eval("document.querySelector('.a-figure')?.dataset.pose")
        t.check(pose == "once" and re.fullmatch(ONCE_UNTIL, v.text("view-views-left")) is not None
                and "Someone shared something with you." in v.text("view-root") and v.eval("document.activeElement?.dataset?.testid") == "view-open",
                f"{w}: the viewer's first screen: the Once tile, one sentence, C18, Open it focused ({pose})")
        t.shot(v, f"viewer-{w}-ready", full_page=True)
        v.click("view-open")
        t.check(v.wait_state("view-root", VIEW_END, 60) == "opened" and "This was its only look." in v.text("view-root"), f"{w}: opened, its only look")
        t.shot(v, f"viewer-{w}-opened", full_page=True)
        for receipt in ("done", "pending"):
            g = t.actor(device)
            seallog_on(t, g, sid, receipt)
            g.goto(url.split("#")[0])
            t.check(g.wait_state("view-root", VIEW_ASK, 60) == "burned", f"{w}: the gone page ({receipt})")
            g.wait(f"document.querySelector('[data-testid=\"gone-receipt\"]')?.dataset.receipt === {json.dumps(receipt)}", 30)
            text, href = g.text("view-root"), g.attr("gone-see", "href")
            want = ("The file left the server, which wrote that on the Tari™ chain.", "Check it in this browser", f"/verify#{sid}") if receipt == "done" else \
                   ("The file left the server. That goes on the Tari™ chain within 15 minutes.", "Check an older one", "/verify#latest")
            t.check("This link has ended." in text and "Someone opened it already." in text and want[0] in text
                    and g.text("gone-see") == want[1] and href == want[2] and g.eval("document.querySelector('.a-figure')?.dataset.pose") == "gone",
                    f"{w}: ended, {receipt}: the receipt says {want[0]!r} and links {href}")
            t.shot(g, f"gone-{w}-{receipt}", full_page=True)
        lo = t.actor(device)
        lo.goto(t.origin + "/locker")
        lo.wait_for("drop-create", 60)
        t.shot(lo, f"locker-{w}-first", full_page=True)
        lo.click("drop-create")
        lo.wait_for("key-later", 120)
        t.check("Save your key. If this browser forgets it, nobody can let you back in, not even us." in lo.eval("document.querySelector('dialog[open]').textContent"),
                f"{w}: the key question, with Later")
        t.shot(lo, f"locker-{w}-key")
        lo.click("key-later")
        lo.wait("!document.querySelector('dialog[open]')", 10)
        lo.wait_for("locker-safety", 60)
        address = lo.text("locker-address").strip()
        t.check(lo.exists("c15") and "For files sent to your drive: you see that something came, and how much. Not the file." in lo.text("locker-root"),
                f"{w}: the locker's view key section: C15-k and C15")
        t.shot(lo, f"locker-{w}-full", full_page=True)
        lo.goto(t.origin + "/inbox")
        lo.wait_for("inbox-empty", 120)
        t.check(lo.exists("watch-mine") and (w == 1440 or lo.eval("!!document.querySelector('.a-bottom')")),
                f"{w}: See what came, with See what a view key sees (and, on a phone, the tabs once a locker exists)")
        t.shot(lo, f"inbox-{w}", full_page=True)
        lo.goto(t.origin + "/send")
        lo.wait_for("drop-input", 60)
        lo.click("drop-write")
        lo.fill("drop-textarea", "Stage door, nine o'clock.")
        lo.click("drop-seal-text")
        lo.wait_for("send-recipient", 120)
        lo.fill("send-recipient", address)
        lo.wait_for("send-safety", 30)
        t.check("It goes by Tari. Only they can open it." in lo.eval("document.querySelector('main').textContent")
                and lo.eval("document.querySelector('.a-figure')?.dataset.pose") == "courier", f"{w}: send: the courier tile and C25")
        t.shot(lo, f"send-{w}", full_page=True)
        lo.goto(t.origin + "/watch#mine")
        lo.wait("!!document.querySelector('[data-testid=\"watch-summary\"]')", 120)
        t.check(lo.exists("c15") and lo.eval("document.querySelector('.a-figure')?.dataset.pose") == "peek",
                f"{w}: /watch: the peek tile, C15-k and C15")
        t.shot(lo, f"watch-{w}", full_page=True)
        lo.goto(t.origin + "/upgrade")
        lo.wait_for("pack-s30", 60)
        t.shot(lo, f"upgrade-{w}", full_page=True)
        vf = t.actor(device)
        seallog_on(t, vf, sid, "done")
        vf.goto(t.origin + f"/verify#{sid}")
        line = vf.wait("(() => { const s = document.querySelector('.a-item--this [data-testid=\"verify-exit\"]')?.textContent || ''; return /included|match/.test(s) ? s : ''; })()", 60)
        t.check("Exit: included at checkpoint" in line and "Its exit on the Tari™ chain, checked by your browser." in vf.eval("document.querySelector('main').textContent"),
                f"{w}: See the goodbye: /verify checks this link's exit ({line[:60]})")
        t.shot(vf, f"verify-{w}", full_page=True)


# --- share-simple: the link page says less, Make your own secret, the box at #share, Copy, the mark ----------

FEW_UNTIL = rf"Opens 3 more times, until {WHEN}\. Then it's gone\."
SCAN = "The server can't see inside to scan it, so open only what you expected."
SHARE_BOX = """(() => { const z = document.querySelector('#mutis-drop .md-zone'); if (!z) return null; const b = z.getBoundingClientRect();
  const s = getComputedStyle(z); const root = document.getElementById('mutis-drop');
  return { top: b.top, bottom: b.bottom, head: document.querySelector('.site-header').getBoundingClientRect().bottom, vh: innerHeight,
           glow: root.classList.contains('share-glow'), anim: s.animationName, ring: s.boxShadow,
           focus: document.activeElement?.dataset?.testid ?? document.activeElement?.tagName }; })()"""
LIME = "rgb(188, 254, 0)"   # --brand-solid, #BCFE00
EDGE = "rgb(89, 128, 11)"   # --brand-edge on light pages, #59800B


@scenario("share-simple-link", "share-simple: the link page in few lines (rule and time in one, the scan line, Open it), "
          "Make your own secret to /?from=share#share in the foot of every state, What the server knows, no we or our")
def share_simple_link(t):
    m = t.actor()
    home(t, m)
    few = seal_text(m, "The office key is under the plant.")
    m.click("count", "few")
    m.wait("document.querySelector('.md-card').dataset.maxViews === '3'", 30)
    o = t.actor()
    home(t, o)
    once = seal_text(o, "Stage door, nine o'clock.")
    for device, w in (("iphone", 390), ("desktop", 1440)):
        v = t.actor(device)
        t.check(open_link(v, few, open_it=False) == "ready", f"{w}: ready")
        shown = v.eval("document.querySelector('[data-testid=\"view-root\"]').innerText")
        rows = [r.strip() for r in shown.split("\n") if r.strip()]
        rule = v.text("view-views-left").split(". ", 1)
        t.check(re.fullmatch(FEW_UNTIL, v.text("view-views-left")) is not None,
                f"{w}: the opens left and the time in one sentence, then Then it's gone ({v.text('view-views-left')!r})")
        t.check(v.text("view-scan") == SCAN, f"{w}: the warning is one line: the server can't scan it, open only what you expected")
        t.check(rows == ["Someone shared something with you.", rule[0] + ".", rule[-1], SCAN, "Open it", "Make your own secret",
                         "What the server knows", "Report this link"], f"{w}: eight lines, in this order ({rows})")
        t.check(not re.search(r"\b(we|our|us)\b", shown, re.I) and "Not now" not in shown, f"{w}: no we, our or us; no Not now")
        t.check(v.attr("view-own", "href") == "/?from=share#share" and v.text("view-own") == "Make your own secret"
                and v.eval("!document.querySelector('[data-testid=\"view-own\"]').classList.contains('a-btn--primary')")
                and v.eval("!!(document.querySelector('[data-testid=\"view-open\"]').compareDocumentPosition("
                           "document.querySelector('[data-testid=\"view-own\"]')) & Node.DOCUMENT_POSITION_FOLLOWING)"),
                f"{w}: Make your own secret goes to /?from=share#share, an outline button after Open it")
        t.check(v.eval("document.querySelectorAll('[data-testid=\"view-root\"] .a-btn--primary').length") == 1
                and v.eval("document.activeElement?.dataset?.testid") == "view-open", f"{w}: Open it is the one primary, and it has the focus")
        t.check(no_hscroll(v), f"{w}: no horizontal scroll")
        v.click("view-known")
        v.wait("(document.querySelector('[data-testid=\"known-panel\"]')?.textContent || '').includes('wrapped_key')", 30)
        t.check(v.text("view-known") == "What the server knows" and v.eval("!!document.querySelector('.a-view-foot [data-testid=\"known-panel\"]')"),
                f"{w}: What the server knows opens the glass box under the foot's links")
        t.shot(v, f"view-{w}-ready-few", full_page=True)
    v = t.actor("iphone")
    open_link(v, once, open_it=False)
    t.check(re.fullmatch(ONCE_UNTIL, v.text("view-views-left")) is not None, f"Once: {v.text('view-views-left')!r} (C26)")
    v.click("view-open")
    t.check(v.wait_state("view-root", VIEW_END, 60) == "opened" and v.attr("view-own", "href") == "/?from=share#share", "opened: the foot has Make your own secret")
    v.reload()
    t.check(v.wait_state("view-root", VIEW_ASK, 60) == "burned", "burned")
    t.check(v.attr("view-own", "href") == "/?from=share#share" and v.eval("!document.querySelector('[data-testid=\"view-root\"] .a-btn--primary')")
            and "Someone opened it already." in v.text("view-root"), "the ended page: Make your own secret in the foot, nothing primary")
    t.shot(v, "view-390-burned")
    sid = few.split("/s/")[1].split("#")[0]
    e = t.actor("iphone")
    gone = {"error": {"code": "gone", "message": "This link has ended.", "details": {"reason": "removed", "ended_day": "2026-10-31", "views": 0}}}
    Intercept(e).add(f"*/api/v1/s/{sid}", "Request", lambda _params: (410, gone))
    t.check(open_link(e, few) == "removed" and "It was taken down after a report." in e.text("view-root")
            and e.attr("view-own", "href") == "/?from=share#share", "taken down: It was taken down after a report, and Make your own secret")
    n = t.actor()
    t.check(open_link(n, t.origin + "/s/" + "A" * 22 + "#1" + "A" * 43) == "not-found", "not found")
    shown = n.eval("document.querySelector('[data-testid=\"view-root\"]').innerText")
    t.check("This link isn't here." in shown and "The server remembers an ended link for 30 days." in shown
            and not re.search(r"\b(we|our|us)\b", shown, re.I), f"not found, in the server's words ({shown[:120]!r})")


@scenario("share-simple-home", "share-simple: /#share brings the box fully under the header, a lime ring breathes and settles, "
          "the first button takes the focus; in-page too; still with reduced motion; the first use ends it")
def share_simple_home(t):
    for device, w in (("desktop", 1440), ("iphone", 390)):
        for dark in (False, True):
            p = t.actor(device, dark=dark)
            if not dark:   # the home is dark first: light is the switch's choice
                p.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('mutis.theme', 'light'); } catch {}"})
            p.goto(t.origin + "/#share")
            p.wait("!!document.querySelector('#mutis-drop.share-glow .md-zone')", 60)
            p.b.drain(0.6)
            box = p.eval(SHARE_BOX)
            theme = p.eval("document.documentElement.dataset.theme")
            t.check(theme == ("dark" if dark else "light") and box["glow"] and box["anim"] == "share-breathe" and LIME in box["ring"]
                    and (dark or EDGE in box["ring"]), f"{w} {theme}: the box glows in lime{'' if dark else ', its darker edge outside'} ({box['ring'][:90]})")
            t.check(box["head"] <= box["top"] and box["bottom"] <= box["vh"], f"{w}: the whole box under the sticky header ({box})")
            t.check(box["focus"] == "drop-input", f"{w}: Choose a file has the focus ({box['focus']})")
            t.shot(p, f"home-{w}-{'dark' if dark else 'light'}-share")
    r = t.actor("desktop", reduced_motion=True)
    r.goto(t.origin + "/#share")
    r.wait("!!document.querySelector('#mutis-drop.share-glow .md-zone')", 60)
    box = r.eval(SHARE_BOX)
    t.check(box["anim"] == "none" and LIME in box["ring"], f"reduced motion: the ring, still ({box['anim']})")
    q = t.actor()
    home(t, q)
    t.check(not q.eval("document.getElementById('mutis-drop').classList.contains('share-glow')"), "the home without #share: no glow")
    q.eval("location.hash = '#share'")
    q.wait("document.getElementById('mutis-drop').classList.contains('share-glow')", 10)
    t.check(q.eval(SHARE_BOX)["top"] >= q.eval(SHARE_BOX)["head"], "in-page navigation to #share: the glow, the box in view")
    q.click("drop-write")
    q.wait_for("drop-textarea")
    t.check(not q.eval("document.getElementById('mutis-drop').classList.contains('share-glow')"), "writing a secret ends the glow")


@scenario("share-simple-result", "share-simple: Copy link is always there (Copied for two seconds, then Copy link), Share with the "
          "link alone where the browser has one, the mark in the code (level Q) and the code still reads back")
def share_simple_result(t):
    label = "document.querySelector('[data-testid=\"copy-link\"]').textContent.trim()"
    glyph = "document.querySelector('[data-testid=\"copy-link\"] use').getAttribute('href').split('#')[1]"
    for device, w in (("desktop", 1440), ("iphone", 390)):
        a = t.actor(device)
        a.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": FAKE_SHARE})
        home(t, a)
        url = seal_text(a, "The office key is under the plant.")
        t.check(a.eval(label) == "Copied" and a.eval(glyph) == "i-check", f"{w}: the copy made at once says Copied, with a check")
        t.check(a.wait(f"{label} === 'Copy link'", 4) and a.eval(glyph) == "i-copy", f"{w}: two seconds later it says Copy link again, with the copy icon")
        a.eval("navigator.clipboard.writeText('something else')")
        a.click("copy-link")
        t.check(a.wait(f"{label} === 'Copied'", 3) and a.wait("navigator.clipboard.readText()", 10) == url, f"{w}: Copy link copies again and says Copied")
        t.check(a.wait(f"{label} === 'Copy link'", 4), f"{w}: and back to Copy link")
        primary = a.eval("document.querySelector('.md-acts .a-btn--primary')?.dataset.testid")
        t.check(primary == ("copy-link" if device == "desktop" else "share-link"), f"{w}: one primary: {primary}")
        a.click("share-link")
        t.check(json.loads(a.eval("JSON.stringify(window.__shared ?? null)")) == {"url": url}, f"{w}: Share hands the share sheet the link alone")
        t.check(no_hscroll(a), f"{w}: no horizontal scroll")
        t.shot(a, f"home-{w}-result-copy")
        if device == "desktop":
            a.wait_for("link-qr", 30)
            payload, px, got = scan_code(a, "link-qr")
            mark = a.eval("!!document.querySelector('[data-testid=\"link-qr\"] [data-testid=\"qr-mark\"]')")
            t.check(mark and a.attr("link-qr", "data-level") == "Q" and got["ecl"] == "Q", f"the code carries the mark, at level {got['ecl']}")
            t.check(payload == url and not got["clean"] and all(e is not None and e <= 9 for e in got["errors_per_block"]),
                    f"read back as drawn, correcting the modules under the mark ({got['errors_per_block']} per block, version {got['version']})")
    b = t.actor()
    home(t, b)
    seal_text(b, "no share sheet here")
    t.check(not b.exists("share-link") and b.exists("copy-link"), "a browser without a share sheet: Copy link alone")
