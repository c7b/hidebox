# SPDX-License-Identifier: MIT
"""A small Chrome DevTools Protocol client over --remote-debugging-pipe. Python stdlib only.

One Chromium process; each actor is a fresh browser context (its own storage) with one page.
Responses are matched by id, so an event handler may send commands while another command waits.
Everything the browser reports back is data for the tests, never instructions.
"""
import base64
import fcntl
import json
import os
import select
import shutil
import subprocess
import tempfile
import time

DEVICES = {
    "desktop": {"width": 1440, "height": 900, "dpr": 1, "mobile": False},
    "iphone": {"width": 390, "height": 844, "dpr": 3, "mobile": True,
               "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"},
    "android": {"width": 412, "height": 915, "dpr": 2.625, "mobile": True,
                "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"},
    "narrow": {"width": 360, "height": 740, "dpr": 2, "mobile": True},
}

# Records CSP and Trusted Types violations in the page, before any of its own scripts run.
WATCH_CSP = ("window.__csp = []; document.addEventListener('securitypolicyviolation', e => "
             "window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || '') + ' ' + (e.sample || '').slice(0, 80)));")


class CdpError(Exception):
    pass


class Browser:
    def __init__(self, extra_args=()):
        self.udd = tempfile.mkdtemp(prefix="mutis-ui-")
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        r1h = fcntl.fcntl(r1, fcntl.F_DUPFD_CLOEXEC, 20)
        w2h = fcntl.fcntl(w2, fcntl.F_DUPFD_CLOEXEC, 20)
        os.close(r1)
        os.close(w2)

        def wire():
            os.dup2(r1h, 3)
            os.dup2(w2h, 4)

        args = ["chromium", "--headless", "--remote-debugging-pipe", f"--user-data-dir={self.udd}", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--mute-audio", "--hide-scrollbars", "--font-render-hinting=none", *extra_args, "about:blank"]
        self.proc = subprocess.Popen(args, preexec_fn=wire, close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(r1h)
        os.close(w2h)
        self.w, self.r, self.buf, self.mid = w1, r2, b"", 0
        self.results, self.handlers, self.events = {}, {}, []

    def _read(self, timeout):
        end = time.time() + timeout
        while b"\0" not in self.buf:
            left = end - time.time()
            if left <= 0 or not select.select([self.r], [], [], left)[0]:
                return None
            chunk = os.read(self.r, 1 << 20)
            if not chunk:
                raise CdpError("browser closed")
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def _dispatch(self, msg):
        if "id" in msg:
            self.results[msg["id"]] = msg
            return
        self.events.append(msg)
        handler = self.handlers.get((msg.get("sessionId"), msg.get("method")))
        if handler:
            handler(msg["params"])

    def pump(self, timeout=0.05):
        msg = self._read(timeout)
        if msg is not None:
            self._dispatch(msg)

    def send(self, method, params=None, session=None, timeout=60):
        self.mid += 1
        mid = self.mid
        m = {"id": mid, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        os.write(self.w, json.dumps(m).encode() + b"\0")
        end = time.time() + timeout
        while mid not in self.results:
            if time.time() > end:
                raise TimeoutError(method)
            msg = self._read(min(1.0, max(0.01, end - time.time())))
            if msg is not None:
                self._dispatch(msg)
        res = self.results.pop(mid)
        if "error" in res:
            raise CdpError(f"{method}: {res['error'].get('message')}")
        return res.get("result", {})

    def drain(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.pump(0.05)

    def close(self):
        try:
            self.send("Browser.close", timeout=5)
        except (CdpError, TimeoutError, OSError):
            pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.udd, ignore_errors=True)


class Page:
    """One actor: a browser context with one tab, emulating a device."""

    def __init__(self, browser, device="desktop", dark=False, reduced_motion=False, downloads=None, client_ip=None):
        self.b = browser
        self.device = DEVICES[device]
        self.ctx = browser.send("Target.createBrowserContext", {"disposeOnDetach": True})["browserContextId"]
        target = browser.send("Target.createTarget", {"url": "about:blank", "browserContextId": self.ctx})["targetId"]
        self.session = browser.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.requests, self.loaded, self.downloads = [], False, downloads
        self.on("Network.requestWillBeSent", lambda p: self.requests.append({"url": p["request"]["url"], "method": p["request"]["method"],
                                                                             "headers": p["request"].get("headers", {})}))
        self.on("Page.loadEventFired", lambda p: setattr(self, "loaded", True))
        self.errors = []
        self.on("Runtime.exceptionThrown", lambda p: self.errors.append(p["exceptionDetails"].get("exception", {}).get("description", p["exceptionDetails"].get("text", ""))[:300]))
        self.on("Runtime.consoleAPICalled", lambda p: p["type"] == "error" and self.errors.append(
            " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"])[:300]))
        for domain in ("Page", "Runtime", "Network"):
            self.cmd(f"{domain}.enable")
        self.cmd("Emulation.setFocusEmulationEnabled", {"enabled": True})  # clipboard calls need a focused page
        if client_ip:
            # The dev server, like Caddy in production, takes the client's address from X-Real-IP when the
            # connection is from loopback: each actor is then a separate person for the rate limits.
            self.cmd("Network.setExtraHTTPHeaders", {"headers": {"X-Real-IP": client_ip}})
        self.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": WATCH_CSP})
        d = self.device
        self.cmd("Emulation.setDeviceMetricsOverride", {"width": d["width"], "height": d["height"], "deviceScaleFactor": d["dpr"], "mobile": d["mobile"]})
        if d["mobile"]:
            self.cmd("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        if d.get("ua"):
            self.cmd("Emulation.setUserAgentOverride", {"userAgent": d["ua"]})
        features = [{"name": "prefers-color-scheme", "value": "dark" if dark else "light"},
                    {"name": "prefers-reduced-motion", "value": "reduce" if reduced_motion else "no-preference"}]
        self.cmd("Emulation.setEmulatedMedia", {"features": features})
        browser.send("Browser.grantPermissions", {"permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
                                                  "browserContextId": self.ctx})
        if downloads:
            os.makedirs(downloads, exist_ok=True)
            browser.send("Browser.setDownloadBehavior", {"behavior": "allowAndName", "browserContextId": self.ctx,
                                                         "downloadPath": downloads, "eventsEnabled": True})

    def on(self, method, fn):
        self.b.handlers[(self.session, method)] = fn

    def cmd(self, method, params=None, timeout=60):
        return self.b.send(method, params, session=self.session, timeout=timeout)

    def close(self):
        self.b.send("Target.disposeBrowserContext", {"browserContextId": self.ctx})

    # --- navigation and evaluation -------------------------------------------------------------

    def goto(self, url, timeout=60):
        self.loaded = False
        self.cmd("Page.navigate", {"url": url})  # a #fragment-only change: the viewer reloads itself
        end = time.time() + timeout
        while not self.loaded and time.time() < end:
            self.b.pump(0.05)

    def reload(self):
        self.loaded = False
        self.cmd("Page.reload")
        end = time.time() + 60
        while not self.loaded and time.time() < end:
            self.b.pump(0.05)

    def eval(self, expr, timeout=60):
        res = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
        if "exceptionDetails" in res:
            raise CdpError(res["exceptionDetails"].get("exception", {}).get("description", "evaluation failed")[:300])
        return res["result"].get("value")

    # What an evaluation can meet while the page is navigating (a click that opens another page):
    # the old document is gone and the new one isn't there yet. A wait asks again; a plain eval doesn't.
    NAVIGATING = ("navigated or closed", "Execution context was destroyed", "Cannot find context")

    def wait(self, expr, timeout=30, interval=0.1):
        end = time.time() + timeout
        while time.time() < end:
            try:
                value = self.eval(expr)
            except CdpError as e:
                if not any(n in str(e) for n in self.NAVIGATING):
                    raise
                value = None
            if value:
                return value
            self.b.pump(interval)
        raise TimeoutError(f"waited {timeout}s for {expr[:120]}")

    @staticmethod
    def sel(testid, value=None):
        base = f'[data-testid="{testid}"]'
        return json.dumps(base if value is None else f'{base}[value="{value}"], {base}[data-value="{value}"]')

    def exists(self, testid, value=None):
        return bool(self.eval(f"!!document.querySelector({self.sel(testid, value)})"))

    def visible(self, testid, value=None):
        return bool(self.eval(f"(() => {{ const e = document.querySelector({self.sel(testid, value)}); return !!e && e.getClientRects().length > 0; }})()"))

    def wait_for(self, testid, timeout=30, value=None):
        self.wait(f"(() => {{ const e = document.querySelector({self.sel(testid, value)}); return !!e && e.getClientRects().length > 0; }})()", timeout)

    def attr(self, testid, name):
        return self.eval(f"document.querySelector({self.sel(testid)})?.getAttribute({json.dumps(name)}) ?? null")

    def text(self, testid):
        return self.eval(f"document.querySelector({self.sel(testid)})?.textContent ?? ''")

    def value(self, testid):
        return self.eval(f"document.querySelector({self.sel(testid)})?.value ?? ''")

    def state(self, testid):
        return self.attr(testid, "data-state")

    def wait_state(self, testid, states, timeout=60):
        want = json.dumps(list(states))
        return self.wait(f"(() => {{ const s = document.querySelector({self.sel(testid)})?.dataset.state; return {want}.includes(s) ? s : ''; }})()", timeout)

    # --- input ----------------------------------------------------------------------------------

    def click(self, testid, value=None, timeout=10):
        """A real press at the element's centre (touch on phones), so user-activation rules apply. Waits
        until the element itself is what a press there would hit (no transition or overlay on top)."""
        probe = (f"(() => {{ const e = document.querySelector({self.sel(testid, value)}); if (!e) return null;"
                 " e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();"
                 " const x = r.x + r.width / 2, y = r.y + r.height / 2; const hit = document.elementFromPoint(x, y);"
                 " return hit && (hit === e || e.contains(hit) || hit.contains(e) && hit.tagName === 'LABEL') ? [x, y] : null; })()")
        x, y = self.wait(probe, timeout, interval=0.05)
        if self.device["mobile"]:
            for kind, points in (("touchStart", [{"x": x, "y": y}]), ("touchEnd", [])):
                self.cmd("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})
        else:
            for kind in ("mousePressed", "mouseReleased"):
                self.cmd("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def fill(self, testid, text):
        self.eval(f"(() => {{ const e = document.querySelector({self.sel(testid)}); e.focus(); e.select?.(); }})()")
        self.cmd("Input.insertText", {"text": text})

    def key(self, key, modifiers=0, text=None):
        codes = {"Tab": 9, "Enter": 13, "Escape": 27, " ": 32, "ArrowDown": 40, "ArrowRight": 39}
        base = {"key": key, "code": "Space" if key == " " else key, "windowsVirtualKeyCode": codes.get(key, 0), "modifiers": modifiers}
        down = {"type": "keyDown", **base}
        if text is not None:
            down["text"] = text
        self.cmd("Input.dispatchKeyEvent", down)
        self.cmd("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def type_text(self, text):
        self.cmd("Input.insertText", {"text": text})

    def focused(self):
        return self.eval("document.activeElement?.dataset?.testid ?? document.activeElement?.textContent?.trim().slice(0, 40) ?? ''")

    def tab_to(self, predicate_js, limit=80, shift=False):
        """Presses Tab until `predicate_js` (an expression over `a` = document.activeElement) holds."""
        for _ in range(limit):
            self.key("Tab", modifiers=8 if shift else 0)
            if self.eval(f"(() => {{ const a = document.activeElement; return !!a && ({predicate_js}); }})()"):
                return True
        return False

    def set_files(self, testid, paths):
        root = self.cmd("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = self.cmd("DOM.querySelector", {"nodeId": root, "selector": json.loads(self.sel(testid))})["nodeId"]
        if not node:
            raise CdpError(f"no element {testid}")
        self.cmd("DOM.setFileInputFiles", {"nodeId": node, "files": paths})

    # --- evidence ---------------------------------------------------------------------------------

    def csp_violations(self):
        return self.eval("window.__csp || []")

    def settle(self, timeout=10):
        """Fonts loaded and no View Transition running: what a person would see after a moment."""
        self.wait("document.fonts.ready.then(() => !document.getAnimations().some((a) => "
                  "String(a.effect?.pseudoElement || '').includes('view-transition')))", timeout)
        self.b.drain(0.6)  # the icon sprite and late images

    def screenshot(self, path, full_page=False, quality=72):
        params = {"format": "webp", "quality": quality, "captureBeyondViewport": full_page}
        if full_page:
            self.eval("window.scrollTo(0, 0)")  # sticky parts then sit where a reader first sees them
            # Phones are pictured at 1.5× rather than their full density, and every picture stays under
            # WebP's 16,383-pixel side.
            w, h = self.eval("[document.documentElement.clientWidth, Math.min(document.documentElement.scrollHeight, 6000)]")
            dpr = self.device["dpr"]
            scale = min(1.5 / dpr if dpr > 1.5 else 1, 16000 / (h * dpr))
            params["clip"] = {"x": 0, "y": 0, "width": w, "height": h, "scale": scale}
        data = self.cmd("Page.captureScreenshot", params, timeout=90)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def ax_unnamed(self):
        """Interactive controls without an accessible name, from the Accessibility tree."""
        self.cmd("Accessibility.enable")
        nodes = self.cmd("Accessibility.getFullAXTree")["nodes"]
        roles = {"button", "link", "textbox", "checkbox", "radio", "combobox", "switch", "tab", "menuitem", "searchbox", "spinbutton"}
        out = []
        for n in nodes:
            role = (n.get("role") or {}).get("value")
            name = (n.get("name") or {}).get("value", "")
            if role in roles and not n.get("ignored") and not str(name).strip():
                out.append(role)
        return out
