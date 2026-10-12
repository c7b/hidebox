# SPDX-License-Identifier: MIT
"""A small Chrome DevTools Protocol client over a pipe (stdlib only), for the E2E suite.

The browser is headless Chromium 154 on the server, run as `build` by relay.py; this side may sit on the
workstation (the pipe goes through ssh) or on the server itself. Everything the page sends back is data:
values are compared, never executed.

  browser = Browser(command)              # e.g. ["ssh", "hidebox", "sudo -iu build python3 -I …/relay.py"]
  ctx = browser.context()                 # a fresh profile-less context per actor (cookies, storage)
  page = ctx.page("iphone")               # device emulation incl. touch, UA and 4× CPU throttle
  page.goto(origin + "/"); page.click("drop-write"); page.screenshot(path)
"""
import base64
import json
import os
import select
import subprocess
import time
from pathlib import Path

DEVICES = {
    # 12-integration §1: iPhone-class and Android-class phones with touch, a mobile UA and 4× CPU throttle.
    "iphone": {"width": 390, "height": 844, "scale": 3, "mobile": True, "throttle": 4,
               "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
                     "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"},
    "android": {"width": 412, "height": 915, "scale": 2.625, "mobile": True, "throttle": 4,
                "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 7a) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/154.0.0.0 Mobile Safari/537.36"},
    "desktop": {"width": 1440, "height": 900, "scale": 1, "mobile": False, "throttle": 1,
                "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/154.0.0.0 Safari/537.36"},
    "narrow": {"width": 360, "height": 740, "scale": 2, "mobile": True, "throttle": 1,
               "ua": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/154.0.0.0 Mobile Safari/537.36"},
}


class CdpError(RuntimeError):
    pass


class Browser:
    def __init__(self, command: list[str]):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.fd = self.proc.stdout.fileno()
        self.buf = b""
        self.last_id = 0
        self.events: list[dict] = []
        self.recordings: dict[str, "Recording"] = {}      # session → where its screencast frames go
        self.send("Target.setDiscoverTargets", {"discover": False}, timeout=60)

    def _read(self, timeout: float) -> dict | None:
        end = time.monotonic() + timeout
        while b"\0" not in self.buf:
            left = end - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                return None
            chunk = os.read(self.fd, 1 << 20)
            if not chunk:
                raise CdpError("the browser pipe closed")
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\0", 1)
        return json.loads(raw)

    def _write(self, method: str, params: dict | None, session: str | None) -> int:
        self.last_id += 1
        msg = {"id": self.last_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.proc.stdin.write(json.dumps(msg).encode() + b"\0")
        self.proc.stdin.flush()
        return self.last_id

    def _note(self, msg: dict) -> None:
        """An event: kept for take()/wait_event(), except screencast frames, which are saved and
        acknowledged at once (Chromium sends the next frame only after the ack). Stale replies are dropped."""
        if msg.get("method") == "Page.screencastFrame" and msg.get("sessionId") in self.recordings:
            p = msg["params"]
            self.recordings[msg["sessionId"]].add(p["metadata"]["timestamp"], base64.b64decode(p["data"]))
            self._write("Page.screencastFrameAck", {"sessionId": p["sessionId"]}, msg["sessionId"])
        elif "id" not in msg:
            self.events.append(msg)

    def send(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 60) -> dict:
        wanted = self._write(method, params, session)
        end = time.monotonic() + timeout
        while True:
            reply = self._read(max(0.0, end - time.monotonic()))
            if reply is None:
                raise CdpError(f"{method}: no answer in {timeout} s")
            if reply.get("id") == wanted:
                if "error" in reply:
                    raise CdpError(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})
            self._note(reply)

    def drain(self, timeout: float = 0.0) -> None:
        while (msg := self._read(timeout)) is not None:
            self._note(msg)
            timeout = 0.0

    def take(self, session: str | None, method: str) -> list[dict]:
        self.drain()
        found = [e for e in self.events if e.get("method") == method and e.get("sessionId") == session]
        self.events = [e for e in self.events if e not in found]
        return [e["params"] for e in found]

    def wait_event(self, method: str, session: str | None = None, timeout: float = 30, match=lambda p: True) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for e in self.events:
                if e.get("method") == method and e.get("sessionId") == session and match(e["params"]):
                    self.events.remove(e)
                    return e["params"]
            msg = self._read(min(0.5, max(0.0, end - time.monotonic())))
            if msg is not None:
                self._note(msg)
        raise CdpError(f"no {method} in {timeout} s")

    def context(self) -> "Context":
        return Context(self, self.send("Target.createBrowserContext", {"disposeOnDetach": True})["browserContextId"])

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=10)
        except (CdpError, OSError, ValueError):
            pass
        try:
            self.proc.stdin.close()
            self.proc.wait(20)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


class Recording:
    """Screencast frames of one page, written as numbered JPEGs with their timestamps (the film)."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.frames: list[tuple[float, str]] = []         # (page-clock seconds, file name)
        folder.mkdir(parents=True, exist_ok=True)

    def add(self, timestamp: float, jpeg: bytes) -> None:
        name = f"{len(self.frames):06d}.jpg"
        (self.folder / name).write_bytes(jpeg)
        self.frames.append((timestamp, name))


class Context:
    def __init__(self, browser: Browser, cid: str):
        self.browser, self.id = browser, cid
        self.pages: list[Page] = []

    def page(self, device: str = "desktop", reduced_motion: bool = False, throttle: float | None = None) -> "Page":
        target = self.browser.send("Target.createTarget", {"url": "about:blank", "browserContextId": self.id})["targetId"]
        session = self.browser.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        page = Page(self.browser, session, target, device, reduced_motion, throttle)
        self.pages.append(page)
        return page

    def downloads_to(self, path: str) -> None:
        """Save downloads under `path` (on the browser's machine) as <guid>; Browser.downloadProgress reports them."""
        self.browser.send("Browser.setDownloadBehavior", {"behavior": "allowAndName", "downloadPath": path,
                                                          "browserContextId": self.id, "eventsEnabled": True})

    def close(self) -> None:
        try:
            self.browser.send("Target.disposeBrowserContext", {"browserContextId": self.id}, timeout=20)
        except CdpError:
            pass


class Page:
    def __init__(self, browser: Browser, session: str, target: str, device: str, reduced_motion: bool,
                 throttle: float | None):
        self.b, self.s, self.target, self.device = browser, session, target, DEVICES[device]
        self.requests: list[dict] = []
        self.responses: list[dict] = []
        self.logs: list[dict] = []
        self.issues: list[dict] = []
        for domain in ("Page", "Runtime", "Log", "Audits", "DOM"):
            self.cmd(f"{domain}.enable")
        self.cmd("Network.enable", {"maxPostDataSize": 65536})
        d = self.device
        self.cmd("Emulation.setDeviceMetricsOverride", {"width": d["width"], "height": d["height"],
                                                        "deviceScaleFactor": d["scale"], "mobile": d["mobile"]})
        if d["mobile"]:
            self.cmd("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        self.cmd("Emulation.setUserAgentOverride", {"userAgent": d["ua"], "acceptLanguage": "en-US,en"})
        rate = throttle if throttle is not None else d["throttle"]
        if rate > 1:
            self.cmd("Emulation.setCPUThrottlingRate", {"rate": rate})
        if reduced_motion:
            self.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def cmd(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        return self.b.send(method, params, session=self.s, timeout=timeout)

    def collect(self) -> None:
        """Move this page's pending events into its request/response/log lists."""
        for p in self.b.take(self.s, "Network.requestWillBeSent"):
            r = p["request"]
            self.requests.append({"url": r["url"], "method": r["method"], "headers": r.get("headers", {}),
                                  "body": r.get("postData", ""), "type": p.get("type")})
        for p in self.b.take(self.s, "Network.responseReceived"):
            r = p["response"]
            self.responses.append({"url": r["url"], "status": r["status"], "headers": r.get("headers", {})})
        self.logs += [p["entry"] for p in self.b.take(self.s, "Log.entryAdded")]
        self.logs += [{"level": "error", "source": "exception", "text": json.dumps(p["exceptionDetails"])[:2000]}
                      for p in self.b.take(self.s, "Runtime.exceptionThrown")]
        self.logs += [{"level": p["type"], "source": "console",
                       "text": " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))}
                      for p in self.b.take(self.s, "Runtime.consoleAPICalled")]
        self.issues += [p["issue"] for p in self.b.take(self.s, "Audits.issueAdded")]

    def csp_violations(self) -> list[str]:
        self.collect()
        found = [e["text"] for e in self.logs if e.get("source") == "security" or
                 any(k in e.get("text", "") for k in ("Content Security Policy", "Trusted Type", "TrustedScript"))]
        found += [json.dumps(i)[:500] for i in self.issues if i.get("code") == "ContentSecurityPolicyIssue"]
        return found

    def goto(self, url: str, timeout: float = 45) -> None:
        """Load `url` as a new document. A URL that differs from the current one only after the # is a
        same-document navigation (no loaderId, no load event), so that case reloads."""
        self.collect()
        self.b.take(self.s, "Page.loadEventFired")
        if "loaderId" not in self.cmd("Page.navigate", {"url": url}, timeout=timeout):
            self.cmd("Page.reload", {"ignoreCache": True})
        self.b.wait_event("Page.loadEventFired", self.s, timeout)

    def reload(self, timeout: float = 45) -> None:
        self.b.take(self.s, "Page.loadEventFired")
        self.cmd("Page.reload", {"ignoreCache": True})
        self.b.wait_event("Page.loadEventFired", self.s, timeout)

    def eval(self, expression: str, await_promise: bool = False, timeout: float = 60):
        res = self.cmd("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                            "awaitPromise": await_promise, "userGesture": True}, timeout=timeout)
        if "exceptionDetails" in res:
            raise CdpError("page script failed: " + json.dumps(res["exceptionDetails"])[:300])
        return res.get("result", {}).get("value")

    def wait(self, expression: str, timeout: float = 30, interval: float = 0.25):
        end = time.monotonic() + timeout
        while True:
            value = self.eval(expression)
            if value:
                return value
            if time.monotonic() > end:
                raise CdpError(f"timed out after {timeout} s waiting for: {expression[:160]}")
            self.b.drain(interval)

    @staticmethod
    def sel(testid: str, value: str | None = None) -> str:
        base = f'[data-testid="{testid}"]'
        return json.dumps(base if value is None else f'{base}[value="{value}"], {base}[data-value="{value}"]')

    def exists(self, testid: str, value: str | None = None) -> bool:
        return bool(self.eval(f"!!document.querySelector({self.sel(testid, value)})"))

    def wait_for(self, testid: str, timeout: float = 30) -> None:
        self.wait(f"(() => {{ const e = document.querySelector({self.sel(testid)}); "
                  f"return !!e && e.getClientRects().length > 0; }})()", timeout)

    def attr(self, testid: str, name: str) -> str | None:
        return self.eval(f"document.querySelector({self.sel(testid)})?.getAttribute({json.dumps(name)}) ?? null")

    def text(self, testid: str) -> str:
        return self.eval(f"document.querySelector({self.sel(testid)})?.textContent ?? ''")

    def value(self, testid: str) -> str:
        return self.eval(f"document.querySelector({self.sel(testid)})?.value ?? ''")

    def state(self, testid: str) -> str | None:
        return self.attr(testid, "data-state")

    def wait_state(self, testid: str, states: tuple[str, ...], timeout: float = 60) -> str:
        want = json.dumps(list(states))
        return self.wait(f"(() => {{ const s = document.querySelector({self.sel(testid)})?.dataset.state; "
                         f"return {want}.includes(s) ? s : ''; }})()", timeout)

    def center(self, testid: str, value: str | None = None, timeout: float = 30) -> tuple[float, float]:
        """The element's centre in the viewport, once it is on the page and hit testing finds it there:
        right after a scroll, Chromium can still hit-test the old position (seen on the home page's long
        sticky scene). A missing element fails after `timeout` s; one that stays covered is pressed anyway
        after 5 s."""
        probe = (f"(() => {{ const e = document.querySelector({self.sel(testid, value)}); if (!e) return null;"
                 " e.scrollIntoView({block: 'center'});"
                 " const r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;"
                 " return [x, y, e.contains(document.elementFromPoint(x, y))]; })()")
        end, settle = time.monotonic() + timeout, None
        while True:
            found, now = self.eval(probe), time.monotonic()
            if found:
                settle = settle or now + 5
                if found[2] or now > settle:
                    return found[0], found[1]
            elif now > end:
                raise CdpError(f"no element {self.sel(testid, value)} after {timeout} s")
            self.b.drain(0.1)

    def click(self, testid: str, value: str | None = None) -> None:
        """A real pointer (or touch) press at the element's centre, so user-activation rules apply."""
        x, y = self.center(testid, value)
        if self.device["mobile"]:
            for kind, points in (("touchStart", [{"x": x, "y": y}]), ("touchEnd", [])):
                self.cmd("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})
        else:
            for kind in ("mousePressed", "mouseReleased"):
                self.cmd("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def choose(self, testid: str, value: str) -> None:
        """Pick `value` in a control named by testid: a <select>, or one of several radios/buttons."""
        kind = self.eval(f"document.querySelector({self.sel(testid)})?.tagName ?? ''")
        if kind == "SELECT":
            self.eval(f"(() => {{ const e = document.querySelector({self.sel(testid)}); e.value = {json.dumps(value)};"
                      f" e.dispatchEvent(new Event('change', {{bubbles: true}})); }})()")
        else:
            self.click(testid, value)

    def fill(self, testid: str, text: str) -> None:
        self.eval(f"(() => {{ const e = document.querySelector({self.sel(testid)}); e.focus(); e.select?.(); }})()")
        self.cmd("Input.insertText", {"text": text})

    def key(self, key: str, code: str | None = None, shift: bool = False) -> None:
        vk = {"Tab": 9, "Enter": 13, "Escape": 27, " ": 32}.get(key, 0)
        base = {"key": key, "code": code or key, "windowsVirtualKeyCode": vk, "modifiers": 8 if shift else 0}
        self.cmd("Input.dispatchKeyEvent", {"type": "keyDown", **base, **({"text": "\r"} if key == "Enter" else {})})
        self.cmd("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def set_files(self, testid: str, paths: list[str]) -> None:
        """Paths are on the browser's machine (the server)."""
        root = self.cmd("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = self.cmd("DOM.querySelector", {"nodeId": root, "selector": json.loads(self.sel(testid))})["nodeId"]
        if not node:
            raise CdpError(f"no element {testid}")
        self.cmd("DOM.setFileInputFiles", {"nodeId": node, "files": paths})

    def screenshot(self, path: str, full_page: bool = False) -> None:
        params = {"format": "png", "captureBeyondViewport": full_page}
        data = self.cmd("Page.captureScreenshot", params, timeout=90)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def record(self, folder: Path, max_width: int, max_height: int) -> Recording:
        """Start a screencast into `folder`; frames come only when the page repaints."""
        recording = self.b.recordings[self.s] = Recording(folder)
        self.cmd("Page.startScreencast", {"format": "jpeg", "quality": 85, "maxWidth": max_width,
                                          "maxHeight": max_height, "everyNthFrame": 1})
        return recording

    def stop_recording(self) -> Recording:
        self.cmd("Page.stopScreencast")
        self.b.drain(0.5)
        return self.b.recordings.pop(self.s)

    def clock(self) -> float:
        """The page's clock in seconds, the one screencast timestamps use."""
        return self.eval("Date.now()") / 1000

    def ax_tree(self) -> list[dict]:
        return self.cmd("Accessibility.getFullAXTree", timeout=90)["nodes"]

    def close(self) -> None:
        try:
            self.b.send("Target.closeTarget", {"targetId": self.target}, timeout=20)
        except CdpError:
            pass
