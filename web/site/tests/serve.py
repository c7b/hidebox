# SPDX-License-Identifier: MIT
"""Test server for the site (Python stdlib only). Not the build: production pages come from
tools/build.py. This expands the same includes and placeholders (§3.3 steps 4–6), sends the CSP
headers of spec §14.2, and answers the public API from tests/fixtures/, so pages can be checked
in a real browser without the server stack.

Usage: python3 -I web/site/tests/serve.py [--port 8791] [--wall 24|8|quiet] [--wall-delay S]
       [--mode relay|direct] [--seallog] [--pay] [--no-canary] [--dist DIR] [--api URL]
--wall-delay answers /api/v1/stats/wall S seconds late (a slow network, for the wall's data switch).
--dist serves a tree built by tools/build.py instead of expanding sources.
--api forwards /api/* to a running server (e.g. `mutis-api --dev`) instead of the fixtures.
"""
import argparse
import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parents[2]
SITE, SHARED, FIX = WEB / "site", WEB / "shared", WEB / "site" / "tests" / "fixtures"
SITE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            "object-src 'none'")
APP_CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; "
           "img-src 'self' blob: data:; media-src 'self' blob:; font-src 'self'; connect-src 'self' "
           "https://ootle-indexer-a.tari.com https://ootle-indexer-b.tari.com; manifest-src 'self'; base-uri 'none'; "
           "form-action 'self'; frame-ancestors 'none'; object-src 'none'; require-trusted-types-for 'script'; "
           "trusted-types mutis-url")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript",
         ".mjs": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".webmanifest": "application/manifest+json",
         ".wasm": "application/wasm", ".webm": "video/webm", ".mp4": "video/mp4"}
MEDIA = {".webm", ".mp4"}   # /v2's loops: answered in byte ranges, as Caddy's file server does
TEXT = {".html", ".txt", ".webmanifest"}   # the build expands placeholders in pages and static text only
INCLUDE = re.compile(r"<!--#include ([a-z0-9-]+(?:\.svg)?)-->")
SRI_TAG = re.compile(r'(<(?:script|link)\b[^>]*?(?:src|href)="(/[^"]+)"[^>]*?) integrity="\{\{SRI\}\}"')
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


class Site:
    def __init__(self, opts, origin):
        self.opts, self.origin = opts, origin
        self.values = {"ORIGIN": origin, "GIT_SHA": "0" * 40, "VERSION": "test", "BUILD_DATE": "2026-10-11",
                       "NETWORK": "esmeralda", "SECURITY_DROP_URL": f"{origin}/fine-print#report",
                       "REPO_URL": "https://github.com/c7b/hidebox", "BRAND": "hidebox"}

    def file_for(self, path):
        """URL path → source file, mirroring the dist/ layout of spec §3.3."""
        if self.opts.dist:
            f = Path(self.opts.dist) / path.lstrip("/")
            return f / "index.html" if f.is_dir() else f
        if path == "/":
            return SITE / "pages" / "index.html"
        m = re.fullmatch(r"/([a-z0-9-]+)/?", path)
        if m and (SITE / "pages" / f"{m[1]}.html").is_file():
            return SITE / "pages" / f"{m[1]}.html"
        for prefix, root in (("/shared/", SHARED), ("/site/js/", SITE / "js"), ("/site/css/", SITE / "css"),
                             ("/site/media/", SITE / "media"), ("/app/", WEB / "app")):
            if path.startswith(prefix):
                return root / path[len(prefix):]
        return SITE / "static" / path.lstrip("/")

    def expand(self, text):
        if self.opts.dist:
            return text
        for _ in range(3):
            text = INCLUDE.sub(lambda m: (SHARED / "partials" / (m[1] if m[1].endswith(".svg") else f"{m[1]}.html")).read_text(), text)

        def sri(m):
            target = self.file_for(m[2])
            digest = base64.b64encode(hashlib.sha384(self.render(target, m[2])).digest()).decode()
            return f'{m[1]} integrity="sha384-{digest}"'

        text = SRI_TAG.sub(sri, text)

        def value(m):
            if m[1] not in self.values:
                raise KeyError(f"unknown placeholder {m[0]}")
            return self.values[m[1]]

        return PLACEHOLDER.sub(value, text)

    def render(self, f, path):
        data = f.read_bytes()
        return self.expand(data.decode()).encode() if f.suffix in TEXT else data


class Api:
    """The public endpoints the site reads, from fixtures (shapes as server/mutis/handlers/*.py)."""

    def __init__(self, opts, origin):
        self.opts, self.origin = opts, origin

    def fixture(self, name):
        return json.loads((FIX / name).read_text())

    def get(self, path, query):
        now = int(time.time())
        if path == "/api/v1/config":
            c = self.fixture("config.json")
            c["origin"], c["memo_origins"] = self.origin, [self.origin, "https://mutis.sh"]
            c["send_mode"] = self.opts.mode
            c["amount_proof"] = "sidecar" if self.opts.mode == "direct" else "wallet"
            c["features"]["seallog"] = self.opts.seallog
            if self.opts.pay:   # as on the live deployment: pay to open and the sponsor grant on
                c["features"].update(pay_to_open=True, sponsor=True)
            return 200, c
        if path == "/api/v1/stats":
            return 200, {**self.fixture("stats.json"), "updated_at": now}
        if path == "/api/v1/stats/wall":
            time.sleep(self.opts.wall_delay)
            return 200, self.fixture(f"wall-{self.opts.wall}.json")
        if path == "/api/v1/canary" and self.opts.canary:
            c = self.fixture("canary.json")
            c["sealed_at"] = now - 240
            for i, entry in enumerate(c["revealed"]):   # newest first, a day old and older
                entry["sealed_at"] = now - 86400 - 240 - 3600 * i
            return 200, c
        if re.fullmatch(r"/api/v1/chain/tx/[0-9a-f]{64}/view", path):
            return 200, self.fixture("txview.json")
        if path in ("/evidence.json", "/status.json"):
            return 200, self.fixture(path[1:])
        return 404, {"error": {"code": "not_found", "message": "Not found."}}

    def canary_raw(self, query):
        n = query.get("n", "812")
        f = FIX / f"canary-{n}.bin"
        return f.read_bytes() if self.opts.canary and f.is_file() else None

    def post(self, path, body):
        if path == "/api/v1/pow":
            challenge = bytes([1, 5, 4, 0]) + (int(time.time()) + 300).to_bytes(4, "big") + bytes(28)
            return 200, {"challenge": base64.urlsafe_b64encode(challenge).decode().rstrip("="), "difficulty": 4,
                         "expires_at": int(time.time()) + 300}
        if path == "/api/v1/abuse":
            if not re.search(r"/(s|d)/", str(body.get("link", ""))):
                return 422, {"error": {"code": "invalid", "message": "Paste a mutis link.", "details": {"field": "link"}}}
            return 201, {"report_id": "rep_abcdefghijklmnop"}
        return 404, {"error": {"code": "not_found", "message": "Not found."}}


class Handler(BaseHTTPRequestHandler):
    site: Site
    api: Api

    def log_message(self, *args):
        pass

    def send(self, status, body, ctype, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, status, obj):
        self.send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def forward(self):
        """--api: the same request to a real server; its answer comes back unchanged."""
        length = int(self.headers.get("Content-Length", "0"))
        headers = {k: v for k, v in self.headers.items() if k.lower() in ("content-type", "range", "origin")}
        req = urllib.request.Request(self.site.opts.api + self.path, data=self.rfile.read(length) if length else None,
                                     headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                status, body, ctype = res.status, res.read(), res.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status, body, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        self.send(status, body, ctype)

    def do_GET(self):
        if self.site.opts.api and self.path.startswith("/api/"):
            return self.forward()
        path, _, qs = self.path.partition("?")
        query = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        if path == "/api/v1/canary/raw":
            return self.raw(self.api.canary_raw(query))
        if path.startswith("/api/") or path in ("/evidence.json", "/status.json"):
            return self.json(*self.api.get(path, query))
        f = self.site.file_for(path)
        if ".." in path or not f.is_file():
            f, status = self.site.file_for("/404"), 404
            if self.site.opts.dist:
                f = Path(self.site.opts.dist) / "404.html"
        else:
            status = 200
        csp = APP_CSP if path in ("/", "/v2", "/v2/") else SITE_CSP   # the pages with the drop widget (Caddyfile)
        body = self.site.render(f, path)
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if f.suffix in MEDIA and status == 200 and m and int(m[1]) < len(body):
            start, end = int(m[1]), min(int(m[2] or len(body) - 1), len(body) - 1)
            return self.send(206, body[start:end + 1], TYPES[f.suffix],
                             [("Content-Range", f"bytes {start}-{end}/{len(body)}"), ("Accept-Ranges", "bytes")])
        self.send(status, body, TYPES.get(f.suffix, "application/octet-stream"),
                  [("Content-Security-Policy", csp)] if f.suffix == ".html" else
                  [("Accept-Ranges", "bytes")] if f.suffix in MEDIA else [])

    do_HEAD = do_GET

    def raw(self, data):
        if data is None:
            return self.json(404, {"error": {"code": "not_found", "message": "No such canary."}})
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if m:
            start, end = int(m[1]), min(int(m[2] or len(data) - 1), len(data) - 1)
            return self.send(206, data[start:end + 1], "application/octet-stream",
                             [("Content-Range", f"bytes {start}-{end}/{len(data)}")])
        self.send(200, data, "application/octet-stream",
                  [("Content-Disposition", 'attachment; filename="mutis-canary-812.bin"')])

    def do_POST(self):
        if self.site.opts.api and self.path.startswith("/api/"):
            return self.forward()
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.json(*self.api.post(self.path, body))


def make_server(opts):
    server = ThreadingHTTPServer(("127.0.0.1", opts.port), Handler)
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    handler = type("H", (Handler,), {"site": Site(opts, origin), "api": Api(opts, origin)})
    server.RequestHandlerClass = handler
    return server, origin


def options(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--wall", choices=("24", "8", "quiet"), default="24")
    p.add_argument("--wall-delay", type=float, default=0)
    p.add_argument("--mode", choices=("relay", "direct"), default="relay")
    p.add_argument("--seallog", action="store_true")
    p.add_argument("--pay", action="store_true", help="pay to open and the sponsor grant on")
    p.add_argument("--no-canary", dest="canary", action="store_false")
    p.add_argument("--dist")
    p.add_argument("--api")
    return p.parse_args(argv)


if __name__ == "__main__":
    srv, url = make_server(options())
    print(f"serving {url}", flush=True)
    srv.serve_forever()
