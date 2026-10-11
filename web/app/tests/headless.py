#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a test page of web/app in headless Chromium and report its result. Python stdlib only.

Serves the repository with the production URL layout (/app/**, /vendor/**, /shared/**) and the app
CSP of spec §14.2 on every response, opens the page over the DevTools pipe, and waits until the page
title reads "<WORD> PASS ..." or "<WORD> FAIL ...". CSP and Trusted Types violations fail the run.

  python3 -I web/app/tests/headless.py                       # KATs: /app/tests/run.html
  python3 -I web/app/tests/headless.py --page /app/tests/gates/g1.html --fragment 'mode=addr' --indexer
  python3 -I web/app/tests/headless.py --jitless             # Tor-like: WebAssembly unavailable
  python3 -I web/app/tests/headless.py --throttle 6 --page /app/tests/bench/pow.html

--indexer enables /api/v1/chain/ix/<path> for the gate pages: an allowlisted pass-through to the
public Tari indexer (the same allowlist the production proxy needs). Page output is data only.
"""
import argparse
import base64
import fcntl
import http.server
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; "
       "img-src 'self' blob: data:; media-src 'self' blob:; font-src 'self'; "
       "connect-src 'self' https://ootle-indexer-a.tari.com https://ootle-indexer-b.tari.com; "
       "manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; "
       "require-trusted-types-for 'script'; trusted-types mutis-url")
MOUNTS = [("/app/", "web/app/"), ("/vendor/", "web/app/vendor/"), ("/shared/", "web/shared/"),
          ("/server/tests/vectors/", "server/tests/vectors/")]
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".json": "application/json", ".wasm": "application/wasm", ".css": "text/css", ".jpg": "image/jpeg",
         ".png": "image/png", ".webp": "image/webp", ".bin": "application/octet-stream", ".txt": "text/plain; charset=utf-8"}
INDEXER = "https://ootle-indexer-b.tari.com"
IX_GET = ("substates/utxo_", "transactions/", "epoch-manager/stats")
IX_LOG = []


def ix_allowed(method, path):
    if method == "POST":
        return path == "transactions"
    if path.startswith("transactions/"):
        return path.endswith("/result") and len(path) == len("transactions/") + 64 + len("/result")
    return path.startswith(IX_GET)


class Handler(http.server.BaseHTTPRequestHandler):
    indexer = False
    config = {}

    def log_message(self, *args):
        pass

    def headers_out(self, status, ctype, length):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def reply(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers_out(status, ctype, len(data))
        self.wfile.write(data)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/v1/"):
            return self.api(method, path[len("/api/v1/"):])
        if method != "GET" or ".." in path:
            return self.reply(404, {"error": {"code": "not_found"}})
        for prefix, base in MOUNTS:
            if path.startswith(prefix):
                fs = os.path.join(ROOT, base, path[len(prefix):])
                if os.path.isfile(fs):
                    with open(fs, "rb") as f:
                        data = f.read()
                    return self.reply(200, data, TYPES.get(os.path.splitext(fs)[1], "application/octet-stream"))
        self.reply(404, {"error": {"code": "not_found"}})

    def api(self, method, rest):
        if rest == "config" and method == "GET":
            return self.reply(200, self.config)
        if rest.startswith("chain/ix/") and self.indexer:
            ix = rest[len("chain/ix/"):]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            if not ix_allowed(method, ix):
                return self.reply(403, {"error": {"code": "forbidden", "message": "path not allowlisted"}})
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else None
            IX_LOG.append(method + " /" + re.sub(r"utxo_[0-9a-f]{64}_[0-9a-f]{64}", "{utxo_id}", re.sub(r"\b[0-9a-f]{64}\b", "{tx_id}", ix)))
            # The indexer's CDN rejects urllib's default User-Agent (Cloudflare error 1010).
            headers = {"User-Agent": "mutis-test-proxy/1", **({"Content-Type": "application/json"} if body else {})}
            req = urllib.request.Request(f"{INDEXER}/{ix}" + (f"?{query}" if query else ""), data=body, method=method,
                                         headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return self.reply(r.status, r.read())
            except urllib.error.HTTPError as e:
                return self.reply(e.code, e.read())
        self.reply(404, {"error": {"code": "not_found"}})


class CDP:
    """Chromium DevTools protocol over --remote-debugging-pipe (fds 3 and 4)."""

    def __init__(self, extra_args):
        self.udd = tempfile.mkdtemp(prefix="mutis-cdp-")
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        r1h = fcntl.fcntl(r1, fcntl.F_DUPFD_CLOEXEC, 20)
        w2h = fcntl.fcntl(w2, fcntl.F_DUPFD_CLOEXEC, 20)
        os.close(r1)
        os.close(w2)

        def pre():
            os.dup2(r1h, 3)
            os.dup2(w2h, 4)

        args = ["chromium", "--headless", "--remote-debugging-pipe", f"--user-data-dir={self.udd}",
                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                "--disable-background-networking", "--disable-sync", "--mute-audio", *extra_args, "about:blank"]
        self.p = subprocess.Popen(args, preexec_fn=pre, close_fds=False,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(r1h)
        os.close(w2h)
        self.w, self.r, self.buf, self.mid, self.events = w1, r2, b"", 0, []

    def _read(self, timeout):
        end = time.time() + timeout
        while b"\0" not in self.buf:
            left = end - time.time()
            if left <= 0 or not select.select([self.r], [], [], left)[0]:
                return None
            chunk = os.read(self.r, 1 << 20)
            if not chunk:
                return None
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def send(self, method, params=None, session=None, timeout=60):
        self.mid += 1
        m = {"id": self.mid, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        os.write(self.w, json.dumps(m).encode() + b"\0")
        end = time.time() + timeout
        while time.time() < end:
            msg = self._read(end - time.time())
            if msg is None:
                break
            if msg.get("id") == self.mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)
        raise TimeoutError(method)

    def pump(self, timeout):
        msg = self._read(timeout)
        if msg is not None:
            self.events.append(msg)

    def close(self):
        try:
            self.send("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self.p.wait(10)
        except Exception:
            self.p.kill()
        shutil.rmtree(self.udd, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="/app/tests/run.html")
    ap.add_argument("--fragment", default="")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--jitless", action="store_true", help="V8 without JIT: no WebAssembly (Tor Safer-like)")
    ap.add_argument("--throttle", type=float, default=0, help="CPU throttling rate, e.g. 6")
    ap.add_argument("--mobile", action="store_true", help="390x844 touch phone emulation")
    ap.add_argument("--indexer", action="store_true", help="enable the allowlisted indexer pass-through")
    ap.add_argument("--config", default="", help="JSON for GET /api/v1/config")
    ap.add_argument("--screenshot", default="", help="write a PNG of the final page here")
    ap.add_argument("--out", default="", help="write the page's #out text here")
    a = ap.parse_args()

    Handler.indexer = a.indexer
    Handler.config = json.loads(a.config) if a.config else {
        "origin": "https://srv2052606.hstgr.cloud",
        "memo_origins": ["https://srv2052606.hstgr.cloud", "https://mutis.sh"],
        "network": "esmeralda", "network_byte": 38, "send_mode": "direct", "ootle": {"mirror_start_seq": 1}}
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}{a.page}" + (f"#{a.fragment}" if a.fragment else "")

    cdp = CDP(["--js-flags=--jitless"] if a.jitless else [])
    violations, console = [], []
    status = 2
    try:
        tid = cdp.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = cdp.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        for dom in ("Page.enable", "Runtime.enable", "Log.enable"):
            cdp.send(dom, session=sid)
        if a.mobile:
            cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True}, session=sid)
            cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, session=sid)
        if a.throttle:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": a.throttle}, session=sid)
        t0 = time.time()
        cdp.send("Page.navigate", {"url": url}, session=sid)
        title = ""
        while time.time() - t0 < a.timeout:
            cdp.pump(0.5)
            for e in cdp.events:
                m, p = e.get("method"), e.get("params", {})
                if m == "Runtime.consoleAPICalled":
                    console.append(" ".join(str(x.get("value", x.get("description", ""))) for x in p.get("args", [])))
                elif m == "Log.entryAdded" and p["entry"].get("source") in ("security", "violation") \
                        or m == "Log.entryAdded" and "Content Security Policy" in p["entry"].get("text", ""):
                    violations.append(p["entry"]["text"])
                elif m == "Runtime.exceptionThrown":
                    console.append("EXCEPTION " + json.dumps(p["exceptionDetails"])[:600])
            cdp.events.clear()
            title = cdp.send("Runtime.evaluate", {"expression": "document.title", "returnByValue": True},
                             session=sid)["result"].get("value", "")
            if " PASS" in title or " FAIL" in title:
                break
        seconds = round(time.time() - t0, 1)
        out = cdp.send("Runtime.evaluate", {"expression": "document.getElementById('out')?.textContent ?? ''",
                                            "returnByValue": True}, session=sid)["result"].get("value", "")
        if a.screenshot:
            shot = cdp.send("Page.captureScreenshot", {"format": "png"}, session=sid)
            with open(a.screenshot, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(out)
        print(out)
        for c in console:
            print("console:", c[:400])
        for v in violations:
            print("CSP VIOLATION:", v[:400])
        if IX_LOG:
            print("indexer paths:", ", ".join(sorted(set(IX_LOG))))
        print(f"title: {title or '(none)'}  ({seconds}s{', jitless' if a.jitless else ''}{f', {a.throttle}x CPU' if a.throttle else ''})")
        status = 0 if " PASS" in title and not violations else 1
    finally:
        cdp.close()
        server.shutdown()
    sys.exit(status)


if __name__ == "__main__":
    main()
