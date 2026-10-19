# SPDX-License-Identifier: MIT
"""The UX feedback audit (docs/review/ux-feedback-1.md): every flow's waits, measured in a real browser on production.

  python3 -I docs/evidence/2026-10-18/ux-feedback-1/audit.py --origin https://hidebox.app --out DIR \
      [--local] [--candidate DIST] [--only drop,widget,...] [--tag before]

The browser is headless Chromium on the server as `build` (tests/e2e/relay.py); the orchestrator runs on the workstation,
or as the operator on the server with --local. Each page carries a recorder from its first script on: every 120 ms it notes
whether what a person can read in the flow (the page's main column, an open dialog, the upload panel, a toast)
changed, and whether an animation runs on something visible there. A flow's "longest still" is the longest stretch
between two such signs of life, from the person's action to the result: the time someone stares at a screen that
does not move. Phones are the e2e's Android profile (412 x 915, touch, 4x CPU throttling) with DevTools' Slow 4G
(562.5 ms latency, 180,000 B/s down, 84,375 B/s up).

--candidate DIST serves a local build's pages, scripts and styles in place of production's (the CDP Fetch domain,
production's own headers, CSP included; /api/ untouched), so a branch's front end runs against production's API
and chain without a deploy. Nothing else changes on production: the flows make one drive, a drop link, two drops,
two deliveries, links, one pay link and one payment with test money (no judge pass), and the drive is deleted at
the end with Delete my drive. Python stdlib only.
"""
import argparse
import base64
import json
import mimetypes
import os
import secrets
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
import cdp  # noqa: E402
import harness  # noqa: E402

REMOTE = "/home/build/work/ux-feedback-1"
harness.REMOTE_DIR = REMOTE
PASSPHRASE = "tidal amber quiet lantern"
SLOW_4G = {"offline": False, "latency": 562.5, "downloadThroughput": 180000, "uploadThroughput": 84375}

RECORDER = r"""(() => {
  if (window.__ux) return;
  const U = window.__ux = { ev: [], root: 'main', done: null };
  let last = null;
  const vis = (e) => !!e && e.isConnected && e.getClientRects().length > 0
    && (!e.checkVisibility || e.checkVisibility({ opacityProperty: true, visibilityProperty: true }));
  const roots = () => [...document.querySelectorAll(U.root + ', [role="dialog"], [role="alertdialog"], [data-testid="upload-panel"], .toaster, .a-toast')]
    .filter((r, i, all) => vis(r) && !all.some((o) => o !== r && o.contains(r)));
  const words = (r) => {
    let s = r.innerText || '';
    for (const x of r.querySelectorAll('.sr-only')) { const w = x.innerText; if (w) s = s.replace(w, ''); }
    return s.replace(/\s+/g, ' ').trim();
  };
  const tick = () => {
    const now = Math.round(performance.now());
    const rs = roots();
    const text = rs.map(words).join(' | ');
    let anim = 0;
    try {
      anim = document.getAnimations().some((a) => {
        if (a.playState !== 'running') return false;
        const t = a.effect && a.effect.target;
        return !!t && rs.some((r) => r.contains(t)) && vis(t);
      }) ? 1 : 0;
    } catch (e) { anim = 0; }
    U.ev.push(text !== last ? [now, 1, anim, text.slice(0, 260)] : [now, 0, anim]);
    last = text;
  };
  U.until = (f) => {
    U.done = null;
    const iv = setInterval(() => { try { if (f()) { U.done = Math.round(performance.now()); clearInterval(iv); } } catch (e) { /* not yet */ } }, 50);
  };
  setInterval(tick, 120);
})();"""


# --- the analysis --------------------------------------------------------------------------------------

def analyze(ev, t0, t1):
    """The longest still between t0 (the action) and t1 (the result), and the text timeline in between."""
    alive = [(t0, None)]
    timeline = []
    prev_anim = 0
    for e in ev:
        t, changed, anim = e[0], e[1], e[2]
        if t < t0:
            prev_anim = anim
            continue
        if t > t1:
            break
        if changed:
            timeline.append([round((t - t0) / 1000, 2), e[3]])
        if changed or anim:
            # an animation running at both ends of the gap kept moving on the compositor
            alive.append((t, "anim" if anim and prev_anim and not changed else "text"))
        prev_anim = anim
    alive.append((t1, None))
    worst, at = 0, None
    for (a, _), (b, kind) in zip(alive, alive[1:]):
        gap = b - a
        if kind == "anim":
            continue
        if gap > worst:
            worst, at = gap, a
    still_text = None
    if at is not None:
        before = [x for x in timeline if x[0] <= (at - t0) / 1000 + 0.01]
        still_text = before[-1][1] if before else "(the screen as the action left it)"
    return {"total_s": round((t1 - t0) / 1000, 2), "longest_still_s": round(worst / 1000, 2),
            "still_from_s": round(((at or t0) - t0) / 1000, 2), "still_on": (still_text or "")[:200],
            "timeline": timeline[:60]}


# --- the candidate front end (--candidate) -----------------------------------------------------------

class Override:
    """Production's static responses replaced by a local build's files, production's headers kept."""

    DROP = {"content-length", "content-encoding", "etag", "last-modified", "content-md5"}

    def __init__(self, dist: Path, origin: str):
        self.dist, self.origin = dist, origin
        self.served = 0

    def local(self, path: str, document: bool) -> Path | None:
        if path.startswith("/api/"):
            return None
        if document:
            for prefix, page in (("/d/", "app/app.html"), ("/send", "app/app.html"), ("/watch", "app/app.html"),
                                 ("/verify", "app/app.html"), ("/drive", "app/drive.html"), ("/s/", "app/view.html"),
                                 ("/p/", "app/view.html")):
                if path.startswith(prefix):
                    return self.dist / page
            if path in ("/t",):
                return self.dist / "app/view.html"
            if path == "/":
                return self.dist / "index.html"
            f = self.dist / path.strip("/") / "index.html"
            return f if f.is_file() else None
        f = self.dist / path.lstrip("/")
        return f if f.is_file() else None

    def handle(self, browser, msg):
        p = msg["params"]
        rid, req = p["requestId"], p["request"]
        url = urllib.parse.urlsplit(req["url"])
        status = p.get("responseStatusCode")
        target = None
        document = p.get("resourceType") == "Document"
        if req["url"].startswith(self.origin) and (status == 200 or (status == 404 and not document)):
            target = self.local(url.path, document)
        if target is None:
            browser._write("Fetch.continueRequest", {"requestId": rid}, msg.get("sessionId"))
            return
        # A file the branch adds is a 404 on production: it gets the type its name says, as Caddy would serve it.
        keep = status == 200
        headers = [x for x in p.get("responseHeaders", []) if x["name"].lower() not in self.DROP
                   and (keep or x["name"].lower() not in ("content-type", "cache-control"))]
        if not any(x["name"].lower() == "content-type" for x in headers):
            kind = {".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml"}.get(target.suffix)
            headers.append({"name": "Content-Type", "value": kind or mimetypes.guess_type(str(target))[0] or "application/octet-stream"})
        body = base64.b64encode(target.read_bytes()).decode()
        browser._write("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 200, "responseHeaders": headers, "body": body},
                       msg.get("sessionId"))
        self.served += 1


class Browser(cdp.Browser):
    override: Override | None = None

    def _note(self, msg):
        if msg.get("method") == "Fetch.requestPaused" and self.override:
            self.override.handle(self, msg)
            return
        super()._note(msg)


# --- the run ----------------------------------------------------------------------------------------------

class Run:
    def __init__(self, args):
        self.args = args
        self.origin = args.origin.rstrip("/")
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        control = Path(os.environ.get("TMPDIR", "/tmp")) / f"uxa-{os.getpid()}"
        control.mkdir(parents=True, exist_ok=True)
        self.remote = harness.Remote(None if args.local else harness.SSH_HOST, control)
        self.remote.as_build(f"mkdir -p {REMOTE}/fixtures {REMOTE}/downloads")
        self.remote.as_build(f"cat > {REMOTE}/relay.py", (ROOT / "tests/e2e/relay.py").read_bytes())
        self.browser = Browser(self.remote.browser_command(False))
        if args.candidate:
            Browser.override = Override(Path(args.candidate).resolve(), self.origin)
        self.results = []
        self.state = {}
        self.photo_app1 = self.exif_headers()
        self.n = 0
        self.photo = f"IMG_{args.tag}.jpg"    # names that differ per run, so a later run in the same drive waits for its own
        self.folder = f"trip-{args.tag}"

    @staticmethod
    def exif_headers() -> str:
        """APP0 to the second comment of the e2e's GPS photo: a phone photo's headers for the generated picture."""
        d = (ROOT / "web/app/tests/fixtures/exif/jpeg-gps.jpg").read_bytes()
        return base64.b64encode(d[2:560]).decode()

    def actor(self, device="desktop", slow=False):
        ctx = self.browser.context()
        dl = f"{REMOTE}/downloads/{self.args.tag}-{self.n}"
        ctx.downloads_to(dl)
        self.n += 1
        page = ctx.page(device)
        page.ctx, page.dl = ctx, dl
        page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": RECORDER})
        if slow:
            page.cmd("Network.emulateNetworkConditions", SLOW_4G)
        if Browser.override:
            page.cmd("Fetch.enable", {"patterns": [{"urlPattern": self.origin + "/*", "requestStage": "Response"}]})
        return page

    def shot(self, page, name, full=False):
        path = self.out / f"{self.args.tag}-{name}.png"
        try:
            page.screenshot(str(path), full_page=full)
        except cdp.CdpError as e:
            print(f"  (no shot {name}: {e})")
        return path.name

    def measure(self, page, flow, device, act, done, timeout, root="main", shots=None, note=""):
        """Run act() (the person's action), wait until done() is true in the page; record what was seen."""
        page.eval(f"window.__ux.root = {json.dumps(root)}")
        page.eval(f"window.__ux.until(() => ({done}))")
        t0 = page.eval("Math.round(performance.now())")
        act()
        taken = set()
        end = time.monotonic() + timeout
        while page.eval("window.__ux.done") is None:
            if shots:
                for name, cond in shots.items():
                    if name not in taken and page.eval(f"!!({cond})"):
                        taken.add(name)
                        self.shot(page, f"{flow}-{device}-{name}")
            if time.monotonic() > end:
                self.shot(page, f"{flow}-{device}-timeout")
                body = page.eval("location.href + ' :: ' + document.body.innerText.replace(/\\s+/g, ' ').slice(0, 600)")
                raise cdp.CdpError(f"{flow}: not done after {timeout} s: {body}")
            self.browser.drain(0.2)
        t1 = page.eval("window.__ux.done")
        ev = page.eval("window.__ux.ev")
        res = {"flow": flow, "device": device, "note": note, **analyze(ev, t0, t1)}
        res["done_shot"] = self.shot(page, f"{flow}-{device}-done")
        self.results.append(res)
        print(f"{flow:14} {device:13} total {res['total_s']:6.2f} s  longest still {res['longest_still_s']:6.2f} s  "
              f"from {res['still_from_s']:.2f} s on: {res['still_on'][:90]!r}", flush=True)
        (self.out / f"{self.args.tag}-results.json").write_text(json.dumps(self.results, indent=1))
        return res

    def page_load(self, page, flow, device, url, done, timeout=90, root="main"):
        """A page's own wait: from navigation to its content (done)."""
        page.goto(self.origin + url if url.startswith("/") else url)
        page.eval(f"window.__ux.root = {json.dumps(root)}")
        page.eval(f"window.__ux.until(() => ({done}))")
        page.wait("window.__ux.done !== null", timeout)
        t1 = page.eval("window.__ux.done")
        ev = page.eval("window.__ux.ev")
        res = {"flow": flow, "device": device, "note": "from navigation", **analyze(ev, 0, t1)}
        res["done_shot"] = self.shot(page, f"{flow}-{device}-done")
        self.results.append(res)
        print(f"{flow:14} {device:13} total {res['total_s']:6.2f} s  longest still {res['longest_still_s']:6.2f} s  "
              f"from {res['still_from_s']:.2f} s on: {res['still_on'][:90]!r}", flush=True)
        (self.out / f"{self.args.tag}-results.json").write_text(json.dumps(self.results, indent=1))
        return res

    def put_photo(self, page, testid, name="IMG_2041.jpg"):
        """A 2000 x 1500 picture with a phone's EXIF (GPS) headers, chosen through the input."""
        js = f"""(async () => {{
          const c = new OffscreenCanvas(2000, 1500), x = c.getContext('2d');
          const g = x.createLinearGradient(0, 0, 2000, 1500); g.addColorStop(0, '#2b4a6f'); g.addColorStop(1, '#d9a35b');
          x.fillStyle = g; x.fillRect(0, 0, 2000, 1500);
          let s = 7; const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
          for (let i = 0; i < 2600; i++) {{ x.fillStyle = `hsla(${{r() * 360}}, 55%, ${{30 + r() * 40}}%, .55)`; x.beginPath(); x.arc(r() * 2000, r() * 1500, 4 + r() * 60, 0, 7); x.fill(); }}
          const img = x.getImageData(0, 0, 2000, 1500), d = img.data;
          for (let i = 0; i < d.length; i += 4) {{ const n = (r() - .5) * 26; d[i] += n; d[i + 1] += n; d[i + 2] += n; }}
          x.putImageData(img, 0, 0);
          const jpg = new Uint8Array(await (await c.convertToBlob({{ type: 'image/jpeg', quality: .9 }})).arrayBuffer());
          let i = 2; while (jpg[i] === 0xFF && jpg[i + 1] >= 0xE0 && jpg[i + 1] <= 0xEF) i += 2 + (jpg[i + 2] << 8 | jpg[i + 3]);
          const head = Uint8Array.from(atob({json.dumps(self.photo_app1)}), (ch) => ch.charCodeAt(0));
          const file = new File([jpg.slice(0, 2), head, jpg.slice(i)], {json.dumps(name)}, {{ type: 'image/jpeg' }});
          window.__uxFile = file; return file.size; }})()"""
        size = page.eval(js, await_promise=True, timeout=120)
        sel = json.dumps(f'[data-testid="{testid}"]')
        return size, (lambda: page.eval(f"(() => {{ const i = document.querySelector({sel}); const dt = new DataTransfer();"
                                        " dt.items.add(window.__uxFile); i.files = dt.files;"
                                        " i.dispatchEvent(new Event('change', { bubbles: true })); return true; })()"))


# --- the flows --------------------------------------------------------------------------------------------

def q(testid, extra=""):
    return f"document.querySelector('[data-testid=\"{testid}\"]{extra}')"


def flow_owner(r: Run):
    """Make my drive (or, with --key, open the one an earlier run made), then Received → Make my drop link."""
    a = r.actor("desktop")
    ready = (f"!!{q('drive-root')} && !document.querySelector('[data-testid=\"locker-root\"] .working')"
             " && !!document.querySelector('[data-testid=\"drive-empty\"], [data-testid=\"file-table\"], [data-testid=\"folder-card\"]')")
    if r.args.key:
        key = Path(r.args.key).read_text()
        a.goto(r.origin + "/drive?open")
        a.wait_for("open-dialog", 90)
        a.fill("restore-text", key)
        a.click("restore-submit")
        a.wait("!document.getElementById('open-pass')?.closest('.field')?.hidden", 30)
        a.fill("restore-passphrase", PASSPHRASE)
        r.measure(a, "open-drive", "desktop", lambda: a.click("restore-submit"), ready, 180, root="body",
                  note="the earlier run's drive, its key file locked with a passphrase")
    else:
        a.goto(r.origin + "/drive")
        a.wait_for("drive-make", 60)
        r.measure(a, "make-drive", "desktop", lambda: a.click("drive-make"), ready, 120, shots={"wait": "!!document.querySelector('.spinner')"})
    if a.exists("key-later"):
        a.click("key-later")
    r.state.update(owner=a)
    if "drop" not in r.args.only.split(","):
        return
    a.goto(r.origin + "/drive/received")
    has = f"(({q('drop-link')}?.value || {q('drop-link')}?.textContent || '').includes('/d/'))"
    a.wait(f"{has} || !!{q('drop-create')}", 90)
    if not a.eval(has):
        r.measure(a, "drop-link", "desktop", lambda: a.click("drop-create"), has, 120,
                  shots={"wait": "!!document.querySelector('.spinner')"})
    link = a.eval(f"({q('drop-link')}?.value || {q('drop-link')}?.textContent).trim()")
    r.state.update(owner=a, drop=link)
    print("  drop link", link[:60] + "…")


def flow_drop(r: Run, device, slow):
    """A stranger leaves a photo at the drop link: pick → lock → upload → chain → Delivered; then What the chain sees."""
    b = r.actor(device, slow=slow)
    r.page_load(b, "drop-page", device + ("-slow4g" if slow else ""), r.state["drop"],
                "['ready', 'closed', 'not-found', 'error'].includes(document.querySelector('[data-testid=\"dd-root\"]')?.dataset.state)", 150)
    size, pick = r.put_photo(b, "dd-input")
    rec = None
    if r.args.film and device == "desktop":
        rec = b.record(r.out / f"{r.args.tag}-film-drop", 1440, 900)
    res = r.measure(b, "drop", device + ("-slow4g" if slow else ""), pick,
                    f"['delivered', 'error'].includes({q('dd-root')}?.dataset.state)", 420, root='[data-testid="dd-root"]',
                    shots={"locking": f"{q('dd-root')}?.dataset.state === 'sealing'",
                           "sending": f"{q('dd-root')}?.dataset.state === 'sending'"},
                    note=f"a {size:,} B photo with GPS")
    if rec:
        time.sleep(1.5)
        frames = b.stop_recording()
        (r.out / f"{r.args.tag}-film-drop" / "frames.json").write_text(json.dumps(frames.frames))
    state = b.state("dd-root")
    res["end_state"] = state
    if state == "delivered":
        tx = b.attr("dd-tx", "data-tx")
        r.state.setdefault("txs", []).append(tx)
        r.shot(b, f"drop-{device}-delivered-full", full=True)
        r.page_load(b, "verify-tx", device + ("-slow4g" if slow else ""), f"/verify/tx/{tx}",
                    "!!document.querySelector('[data-testid=\"tx-fee\"], [data-testid=\"error-banner\"]')", 120)
        r.shot(b, f"verify-tx-{device}-full", full=True)
    b.ctx.close()


def flow_widget(r: Run, device, slow):
    """The home's quick share: pick a photo → its link."""
    c = r.actor(device, slow=slow)
    c.goto(r.origin + "/")
    c.wait("!!document.querySelector('[data-testid=\"drop-input\"]')", 90)
    size, pick = r.put_photo(c, "drop-input")
    r.measure(c, "widget", device + ("-slow4g" if slow else ""), pick,
              f"((({q('sealed-link')})?.value || '').startsWith('http')) || !!{q('error-banner')}", 300, root=".md-root",
              shots={"locking": "!!document.querySelector('.md-sealing')"}, note=f"a {size:,} B photo with GPS")
    url = c.value("sealed-link")
    r.state.setdefault("widget_links", []).append(url)
    c.ctx.close()


def flow_drive(r: Run):
    """In the owner's drive: upload a photo and a folder, share the photo Once, copy the link."""
    a = r.state["owner"]
    a.goto(r.origin + "/drive")
    a.wait_for("drive-root", 90)
    a.wait("!!document.querySelector('[data-testid=\"upload-files-input\"]')", 30)
    size, pick = r.put_photo(a, "upload-files-input", r.photo)
    r.measure(a, "upload-file", "desktop", pick,
              "[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === '" + r.photo + "')"
              " && !!document.querySelector('[data-testid=\"upload-row\"][data-done]')", 180,
              shots={"uploading": "!!document.querySelector('[data-testid=\"upload-panel\"]')"}, note=f"a {size:,} B photo")
    base = f"{REMOTE}/fixtures/{r.args.tag}-trip"
    files = {f"{r.folder}/notes.txt": b"Bring the map.\n", f"{r.folder}/plan.txt": b"Day one: the coast.\n", f"{r.folder}/days/day2.txt": b"Day two.\n"}
    for rel, data in files.items():
        path = f"{base}/{rel}"
        r.remote.as_build(f"mkdir -p {path.rsplit('/', 1)[0]} && cat > {path}", data)
    r.measure(a, "upload-folder", "desktop", lambda: a.set_files("upload-dir-input", [f"{base}/{r.folder}"]),
              "[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === '" + r.folder + "')"
              " && ![...document.querySelectorAll('[data-testid=\"upload-row\"]')].some((e) => !e.hasAttribute('data-done'))", 180,
              note="3 files, 1 subfolder")
    # Share the photo: Anyone with the link → Once → Make link → Copy link
    open_menu = ("(() => { const el = [...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === '" + r.photo + "');"
                 " el.querySelector('[data-testid=\"row-kebab\"]').click(); })()")
    a.eval(open_menu)
    a.wait("!document.getElementById('row-menu').hidden", 10)
    a.click("menu-share")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
    r.measure(a, "make-link", "desktop", lambda: a.click("share-make"),
              "document.getElementById('share-dialog')?.dataset.step === 'result'", 90, root="#share-dialog",
              shots={"making": "!!document.querySelector('#share-dialog .spinner')"})
    r.state["once_link"] = a.value("share-link")
    r.measure(a, "copy-link", "desktop", lambda: a.click("share-copy"),
              "/copied/i.test(document.body.innerText)", 20, root="#share-dialog")
    a.key("Escape")
    a.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 10)
    # the folder, Once, for the folder viewer
    a.eval("(() => { const el = [...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === '" + r.folder + "');"
           " el.querySelector('[data-testid=\"row-kebab\"]').click(); })()")
    a.wait("!document.getElementById('row-menu').hidden", 10)
    a.click("menu-share")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
    a.click("share-make")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
    r.state["folder_link"] = a.value("share-link")
    a.key("Escape")


def flow_links(r: Run):
    """A stranger opens the Once photo link (computer) and the folder link (phone, Slow 4G)."""
    s = r.actor("desktop")
    s.goto(r.state["once_link"])
    s.wait_state("view-root", ("ready", "password", "gone", "error", "incomplete", "not-found"), 90)
    r.measure(s, "link-open", "desktop", lambda: s.click("view-open"),
              f"['opened', 'gone', 'error', 'integrity-error'].includes({q('view-root')}?.dataset.state)", 120,
              shots={"opening": f"{q('view-root')}?.dataset.state === 'opening'"})
    s.ctx.close()
    p = r.actor("android", slow=True)
    r.page_load(p, "folder-open", "android-slow4g", r.state["folder_link"],
                "!!document.querySelector('[data-testid=\"fv-row\"], [data-testid=\"view-open\"], [data-testid=\"error-banner\"]')", 150)
    if p.exists("view-open") and not p.exists("fv-row"):
        r.measure(p, "folder-list", "android-slow4g", lambda: p.click("view-open"),
                  "document.querySelectorAll('[data-testid=\"fv-row\"]').length >= 3 || !!document.querySelector('[data-testid=\"error-banner\"]')", 150)
    p.ctx.close()


def flow_views(r: Run):
    """The owner's Received (the drop's deliveries), Activity, and Save key file."""
    a = r.state["owner"]
    r.page_load(a, "received", "desktop", "/drive/received",
                "!!document.querySelector('[data-testid=\"received-row\"] [data-testid=\"received-open-button\"], [data-testid=\"inbox-empty\"]')"
                " && !document.querySelector('[data-testid=\"inbox-scan\"] .spinner')", 300)
    if a.exists("received-open-button"):
        r.measure(a, "received-open", "desktop", lambda: a.eval(f"{q('received-open-button')}.click()"),
                  "!!document.querySelector('[data-testid=\"inbox-opened\"], #rec-open [data-testid=\"error-banner\"]')", 180)
    r.page_load(a, "activity", "desktop", "/drive/activity",
                "!!document.querySelector('[data-testid=\"activity-feed\"] li, [data-testid=\"activity-event\"]')", 90)
    a.goto(r.origin + "/drive")
    a.wait_for("drive-root", 90)
    a.eval(f"{q('acct-key')}.click()")
    a.wait_for("key-dialog", 15)
    a.fill("key-passphrase", PASSPHRASE)
    r.measure(a, "key-file", "desktop", lambda: a.click("key-save-file"),
              "(document.querySelector('[data-testid=\"key-dialog\"] p[aria-live=\"polite\"]')?.textContent || '').length > 0",
              60, root='[data-testid="key-dialog"]', shots={"locking": "document.querySelector('[data-testid=\"key-save-file\"]').disabled"})
    a.key("Escape")
    got = r.browser.wait_event("Browser.downloadProgress", None, 60, lambda p: p.get("state") == "completed")
    key = r.remote.as_build(f"cat {a.dl}/{got['guid']}")
    if r.args.keep_key:
        Path(r.args.keep_key).write_text(key)   # a testnet drive's key, for the next run's --key (never committed)
    # Open my drive with that key file, in a clean phone browser on Slow 4G
    o = r.actor("android", slow=True)
    o.goto(r.origin + "/drive?open")
    o.wait_for("open-dialog", 90)
    o.fill("restore-text", key)
    o.click("restore-submit")
    o.wait("!document.getElementById('open-pass')?.closest('.field')?.hidden", 30)
    o.fill("restore-passphrase", PASSPHRASE)
    r.measure(o, "open-drive", "android-slow4g", lambda: o.click("restore-submit"),
              "!!document.querySelector('[data-testid=\"drive-root\"]') && !document.querySelector('[data-testid=\"locker-root\"] .working')"
              " && !!document.querySelector('[data-testid=\"file-row\"], [data-testid=\"folder-card\"], [data-testid=\"drive-empty\"]')",
              180, root="body", shots={"opening": "document.querySelector('[data-testid=\"restore-submit\"]')?.disabled"}, note="a key file locked with a passphrase")
    o.ctx.close()


def flow_pay(r: Run):
    """Pay to open: the owner sells the photo (Make pay link); a stranger's computer pays with test money and opens it."""
    a = r.state["owner"]
    a.goto(r.origin + "/drive")
    a.wait_for("drive-root", 90)
    if r.args.sell:
        r.photo = r.args.sell
    a.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === '" + r.photo + "')", 90)
    a.eval("(() => { const el = [...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === '" + r.photo + "');"
           " el.querySelector('[data-testid=\"row-kebab\"]').click(); })()")
    a.wait("!document.getElementById('row-menu').hidden", 10)
    a.click("menu-share")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    a.click("share-choice", "pay")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'pay'", 10)
    r.measure(a, "make-pay-link", "desktop", lambda: a.click("pay-make"),
              "document.getElementById('share-dialog')?.dataset.step === 'result' || !!document.querySelector('#share-dialog [data-testid=\"error-banner\"]')",
              180, root="#share-dialog", shots={"making": "!!document.querySelector('#share-dialog .spinner')"})
    url = a.value("share-link")
    a.key("Escape")
    if "/p/" not in url:
        print("  no pay link:", a.text("share-dialog")[-200:])
        return
    b = r.actor("desktop")
    r.page_load(b, "pay-page", "desktop", url,
                "['wait', 'closed', 'expired', 'void', 'error'].includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)", 120)
    if b.exists("pay-closed") and not b.exists("pay-test"):
        # The seller's sales key is not open yet. Production before this pass said "Try again in a few minutes" and
        # never asked again (a person reloads); with --candidate the page asks again by itself. Time it either way.
        started = time.monotonic()
        r.shot(b, "pay-not-ready")
        while not b.exists("pay-test") and time.monotonic() - started < 900:
            r.browser.drain(15)
            if not r.args.candidate and not b.exists("pay-test"):
                b.reload()
                b.wait("['wait', 'closed', 'expired', 'void', 'error'].includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)", 120)
        waited = round(time.monotonic() - started)
        r.results.append({"flow": "pay-not-ready", "device": "desktop", "total_s": waited, "longest_still_s": None,
                          "note": "until the seller could take payments" + (" (the page asked again by itself)" if r.args.candidate else " (reloaded every 15 s, as a person would have to)"),
                          "still_from_s": 0, "still_on": "", "timeline": []})
        print(f"pay-not-ready  desktop       {waited} s until Pay showed", flush=True)
    if b.attr("pay-page", "data-state") == "wait" and b.exists("pay-test"):
        res = r.measure(b, "pay-test", "desktop", lambda: b.click("pay-test"),
                        "['open', 'expired', 'void', 'error'].includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)"
                        " || !!document.querySelector('[data-testid=\"pay-failed\"]')", 600,
                        shots={"steps": "!!document.querySelector('[data-testid=\"pay-claim-step\"]')"})
        res["end_state"] = b.attr("pay-page", "data-state")
        if b.exists("pay-open"):
            r.measure(b, "pay-open", "desktop", lambda: b.click("pay-open"),
                      "!!document.querySelector('[data-testid=\"view-image\"], [data-testid=\"view-save\"], [data-testid=\"folder-view\"], [data-testid=\"pay-final\"]')"
                      " || document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state === 'opened'", 120)
    else:
        print("  pay page state", b.attr("pay-page", "data-state"), b.text("pay-page")[:200])
    b.ctx.close()
    # the owner's side: Received lists the payment
    if r.results and r.results[-1]["flow"] in ("pay-open", "pay-test"):
        r.page_load(a, "owner-sale", "desktop", "/drive/received",
                    "!!document.querySelector('[data-testid=\"sales-row\"]') && !document.querySelector('[data-testid=\"inbox-scan\"] .spinner')", 180)


def flow_delete(r: Run):
    """Delete my drive (the owner's, last)."""
    a = r.state["owner"]
    a.goto(r.origin + "/drive")
    a.wait_for("drive-root", 90)
    a.eval(f"{q('acct-settings')}.click()")
    a.wait_for("settings", 30)
    a.click("delete-locker")
    a.wait_for("delete-drive", 10)
    a.wait(f"!!{q('wipe-count')}?.textContent", 30)
    a.click("wipe-sure")
    a.wait(f"{q('delete-locker-confirm')}.disabled === false", 5)
    r.measure(a, "delete-drive", "desktop", lambda: a.click("delete-locker-confirm"), f"!!{q('wipe-done')}", 180,
              root='[data-testid="delete-drive"]', shots={"run": f"!!{q('wipe-progress')}"})


def flow_tx(r: Run, tx):
    """/verify/tx of a known transaction (a release's notarization, committed long ago): the page's own wait."""
    for device, slow in (("desktop", False), ("android", True)):
        p = r.actor(device, slow=slow)
        r.page_load(p, "verify-known", device + ("-slow4g" if slow else ""), f"/verify/tx/{tx}",
                    "!!document.querySelector('[data-testid=\"tx-fee\"], [data-testid=\"error-banner\"]')", 120)
        r.shot(p, f"verify-known-{device}-full", full=True)
        p.ctx.close()


FLOWS = ["owner", "drop", "widget", "drive", "links", "views", "pay", "delete"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="https://hidebox.app")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="before")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--candidate", help="a local build's dist/ to serve in place of production's front end")
    ap.add_argument("--only", default=",".join(FLOWS))
    ap.add_argument("--film", action="store_true", help="screencast the computer's drop")
    ap.add_argument("--key", help="open this key file's drive instead of making one (an earlier run's --keep-key)")
    ap.add_argument("--keep-key", help="write the drive's key file here")
    ap.add_argument("--tx", help="also time /verify/tx for this known transaction")
    ap.add_argument("--sell", help="the pay flow sells this file of the drive (default: this run's photo)")
    args = ap.parse_args()
    only = args.only.split(",")
    r = Run(args)
    try:
        if "owner" in only:
            flow_owner(r)
        if "drop" in only:
            flow_drop(r, "desktop", False)
            flow_drop(r, "android", True)
        if "widget" in only:
            flow_widget(r, "desktop", False)
            flow_widget(r, "android", True)
        if "drive" in only:
            flow_drive(r)
        if "links" in only:
            flow_links(r)
        if "views" in only:
            flow_views(r)
        if "pay" in only:
            flow_pay(r)
        if "delete" in only:
            flow_delete(r)
        if args.tx:
            flow_tx(r, args.tx)
    finally:
        (r.out / f"{args.tag}-results.json").write_text(json.dumps(r.results, indent=1))
        if Browser.override:
            print(f"candidate files served: {Browser.override.served}")
        r.browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
