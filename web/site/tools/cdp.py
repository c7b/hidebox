# SPDX-License-Identifier: MIT
"""A small Chrome DevTools Protocol client over --remote-debugging-pipe (Python stdlib only).

Adapted from the research prototype cdpshot.py. One headless Chromium per Browser; each Page is a
fresh target with its own emulation. Everything a page says (console, network) is recorded as data.
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

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/154.0.0.0 Mobile Safari/537.36")


class Browser:
    def __init__(self, binary: str = "chromium"):
        self.profile = tempfile.mkdtemp(prefix="mutis-cdp-")
        to_child, self._w = os.pipe()
        self._r, from_child = os.pipe()
        keep_in = fcntl.fcntl(to_child, fcntl.F_DUPFD_CLOEXEC, 20)
        keep_out = fcntl.fcntl(from_child, fcntl.F_DUPFD_CLOEXEC, 20)
        os.close(to_child)
        os.close(from_child)

        def wire():
            os.dup2(keep_in, 3)
            os.dup2(keep_out, 4)

        self.proc = subprocess.Popen(
            [binary, "--headless", "--remote-debugging-pipe", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--mute-audio",
             "--disable-extensions", "--disable-background-networking", "--disable-sync",
             "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "about:blank"],
            preexec_fn=wire, close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(keep_in)
        os.close(keep_out)
        self._buf = b""
        self._id = 0
        self.events: list[dict] = []

    def _read(self, timeout: float):
        end = time.time() + timeout
        while b"\0" not in self._buf:
            left = end - time.time()
            if left <= 0 or not select.select([self._r], [], [], left)[0]:
                return None
            chunk = os.read(self._r, 1 << 20)
            if not chunk:
                return None
            self._buf += chunk
        msg, self._buf = self._buf.split(b"\0", 1)
        return json.loads(msg)

    def send(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 60):
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self._w, json.dumps(msg).encode() + b"\0")
        end = time.time() + timeout
        while time.time() < end:
            reply = self._read(end - time.time())
            if reply is None:
                break
            if reply.get("id") == self._id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})
            self.events.append(reply)
        raise TimeoutError(method)

    def pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            msg = self._read(end - time.time())
            if msg is None:
                break
            self.events.append(msg)

    def trace(self, categories: str, action) -> list[dict]:
        """Runs action() under Chromium's tracing and returns the trace events."""
        self.send("Tracing.start", {"categories": categories, "transferMode": "ReportEvents"})
        action()
        mark = len(self.events)
        self.send("Tracing.end")
        end = time.time() + 30
        while time.time() < end and not any(e.get("method") == "Tracing.tracingComplete" for e in self.events[mark:]):
            self.pump(0.2)
        return [event for e in self.events[mark:] if e.get("method") == "Tracing.dataCollected"
                for event in e["params"]["value"]]

    def page(self, width=1440, height=900, mobile=False, android=False, reduce=False, dark=False,
             block=(), cpu_throttle=1):
        return Page(self, width, height, mobile, android, reduce, dark, block, cpu_throttle)

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=5)
        except (RuntimeError, TimeoutError, OSError):
            pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Page:
    def __init__(self, browser, width, height, mobile, android, reduce, dark, block, cpu_throttle):
        self.b = browser
        self.width, self.height = width, height
        self.target = browser.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.sid = browser.send("Target.attachToTarget", {"targetId": self.target, "flatten": True})["sessionId"]
        for domain in ("Page", "Runtime", "Log", "Network"):
            self.cmd(f"{domain}.enable")
        self.cmd("Network.setCacheDisabled", {"cacheDisabled": True})
        self.cmd("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
        if mobile:
            self.cmd("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            self.cmd("Emulation.setUserAgentOverride", {"userAgent": ANDROID_UA if android else MOBILE_UA})
        features = [{"name": "prefers-reduced-motion", "value": "reduce" if reduce else "no-preference"},
                    {"name": "prefers-color-scheme", "value": "dark" if dark else "light"}]
        self.cmd("Emulation.setEmulatedMedia", {"features": features})
        if block:
            self.cmd("Network.setBlockedURLs", {"urls": list(block)})
        if cpu_throttle > 1:
            self.cmd("Emulation.setCPUThrottlingRate", {"rate": cpu_throttle})
        self._mark = len(browser.events)

    def close(self) -> None:
        self.b.send("Target.closeTarget", {"targetId": self.target})

    def cmd(self, method, params=None, timeout=60):
        return self.b.send(method, params, self.sid, timeout)

    def goto(self, url: str, settle: float = 1.5) -> None:
        self._mark = len(self.b.events)
        self.cmd("Page.navigate", {"url": url})
        end = time.time() + 45
        while time.time() < end and not any(e.get("method") == "Page.loadEventFired" and e.get("sessionId") == self.sid
                                            for e in self.b.events[self._mark:]):
            self.b.pump(0.2)
        self.b.pump(settle)

    def eval(self, expression: str, await_promise: bool = False):
        res = self.cmd("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                            "awaitPromise": await_promise})
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("exception", {}).get("description", "evaluate failed"))
        return res["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 10) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.eval(expression):
                return True
            self.b.pump(0.1)
        return False

    def scroll_to(self, y: float, settle: float = 0.6) -> None:
        self.eval(f"window.scrollTo(0, {y})")
        self.b.pump(settle)

    @staticmethod
    def _format(path: str) -> dict:
        return {"format": "webp", "quality": 82} if path.endswith(".webp") else {"format": "png"}

    def screenshot(self, path: str, full: bool = False) -> None:
        params = self._format(path)
        if full:
            h = self.eval("document.documentElement.scrollHeight")
            params.update(captureBeyondViewport=True,
                          clip={"x": 0, "y": 0, "width": self.width, "height": h, "scale": 1})
        data = self.cmd("Page.captureScreenshot", params)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def screenshot_element(self, selector: str, path: str) -> None:
        x, y, w, h = self.eval(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
                               " return [r.left + scrollX, r.top + scrollY, r.width, r.height]; })()")
        data = self.cmd("Page.captureScreenshot", {**self._format(path), "captureBeyondViewport": True,
                                                   "clip": {"x": x, "y": y, "width": w, "height": h, "scale": 1}})["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def _mine(self):
        return [e for e in self.b.events[self._mark:] if e.get("sessionId") == self.sid]

    def console(self) -> list[str]:
        out = []
        for e in self._mine():
            p = e.get("params", {})
            if e.get("method") == "Log.entryAdded":
                out.append(f"{p['entry'].get('level')}: {p['entry'].get('text')}")
            elif e.get("method") == "Runtime.consoleAPICalled":
                out.append(f"{p.get('type')}: " + " ".join(str(a.get('value', a.get('description', ''))) for a in p.get("args", [])))
            elif e.get("method") == "Runtime.exceptionThrown":
                out.append("exception: " + p["exceptionDetails"].get("exception", {}).get("description", p["exceptionDetails"].get("text", "")))
        return out

    def posts(self) -> list[tuple[str, str]]:
        """(url, body) of every request with a body since the last goto."""
        return [(e["params"]["request"]["url"], e["params"]["request"].get("postData", ""))
                for e in self._mine() if e.get("method") == "Network.requestWillBeSent"
                and e["params"]["request"].get("hasPostData")]

    def requests(self) -> list[dict]:
        """Every request since the last goto: url, method, status, encoded bytes on the wire, failure."""
        reqs: dict[str, dict] = {}
        for e in self._mine():
            p = e.get("params", {})
            m = e.get("method")
            if m == "Network.requestWillBeSent":
                reqs.setdefault(p["requestId"], {"url": p["request"]["url"], "method": p["request"]["method"],
                                                 "status": None, "bytes": 0, "type": p.get("type"), "failed": None})
            elif m == "Network.responseReceived" and p["requestId"] in reqs:
                reqs[p["requestId"]]["status"] = p["response"]["status"]
                reqs[p["requestId"]]["encoding"] = {k.lower(): v for k, v in p["response"]["headers"].items()}.get("content-encoding")
            elif m == "Network.loadingFinished" and p["requestId"] in reqs:
                reqs[p["requestId"]]["bytes"] = p.get("encodedDataLength", 0)
            elif m == "Network.loadingFailed" and p["requestId"] in reqs:
                reqs[p["requestId"]]["failed"] = p.get("blockedReason") or p.get("errorText")
        return list(reqs.values())
