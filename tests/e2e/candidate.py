# SPDX-License-Identifier: MIT
"""A branch's front end on the live API, without a deploy (run.py --candidate DIST).

Every page and static file the browser asks the origin for is answered from a local build (tools/build.py --origin
<the same origin> --out DIST) through the DevTools Fetch domain, with the live response's own headers (its CSP
included); /api/ passes through untouched. A file the branch adds is a 404 on the live site: it gets the type its
name says, as Caddy would serve it. The live server, its database and its chain are what the scenario uses; only the
browser's copy of the front end differs. Python stdlib only.
"""
import base64
import mimetypes
import urllib.parse
from pathlib import Path

# Caddy's rewrites (deploy/caddy/Caddyfile: @viewer, @paylink, @droplink, @approute, @drive): a route and the page it serves.
PAGES = (("/s/", "app/view.html"), ("/p/", "app/pay.html"), ("/t", "app/view.html"), ("/d/", "app/drop.html"),
         ("/send", "app/app.html"), ("/watch", "app/app.html"), ("/verify", "app/app.html"), ("/drive", "app/drive.html"))
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".svg": "image/svg+xml", ".woff2": "font/woff2", ".wasm": "application/wasm"}
DROP = {"content-length", "content-encoding", "etag", "last-modified", "content-md5"}


class Override:
    def __init__(self, dist: Path, origin: str):
        self.dist, self.origin = dist.resolve(), origin.rstrip("/")
        self.served = 0
        if not (self.dist / "app" / "drive.html").is_file():
            raise SystemExit(f"--candidate {dist}: not a built tree (no app/drive.html)")

    def patterns(self) -> list[dict]:
        return [{"urlPattern": self.origin + "/*", "requestStage": "Response"}]

    def local(self, path: str, document: bool) -> Path | None:
        if path.startswith("/api/"):
            return None
        if document:
            for prefix, page in PAGES:
                if path.startswith(prefix) if prefix.endswith("/") else path == prefix or path.startswith(prefix + "/"):
                    return self.dist / page
            return self.inside("index.html" if path == "/" else path.strip("/") + "/index.html")
        return self.inside(path.lstrip("/"))

    def inside(self, rel: str) -> Path | None:
        """A file of the build, never one outside it (a path with .. or a link out)."""
        f = (self.dist / rel).resolve()
        return f if f.is_file() and self.dist in f.parents else None

    def handle(self, browser, msg: dict) -> None:
        p = msg["params"]
        rid, req, status = p["requestId"], p["request"], p.get("responseStatusCode")
        document = p.get("resourceType") == "Document"
        target = None
        if req["url"].startswith(self.origin + "/") and (status == 200 or (status == 404 and not document)):
            target = self.local(urllib.parse.urlsplit(req["url"]).path, document)
        if target is None:
            browser._write("Fetch.continueRequest", {"requestId": rid}, msg.get("sessionId"))
            return
        keep = status == 200
        headers = [x for x in p.get("responseHeaders", []) if x["name"].lower() not in DROP
                   and (keep or x["name"].lower() not in ("content-type", "cache-control"))]
        if not any(x["name"].lower() == "content-type" for x in headers):
            kind = TYPES.get(target.suffix) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            headers.append({"name": "Content-Type", "value": kind})
        body = base64.b64encode(target.read_bytes()).decode()
        browser._write("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 200, "responseHeaders": headers, "body": body},
                       msg.get("sessionId"))
        self.served += 1
