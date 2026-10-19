# SPDX-License-Identifier: MIT
"""Test-only: the folder API (16-drive-architecture §2.4, §5.1) faked in front of a dev server that
doesn't report `features.folders`.

Such a `server --dev` stores kept files, links and uploads, but has no folders, no trash, no
`expires_at` on kept files and no `view=gone`. This proxies one drive's API traffic from the page (CDP
Fetch, Request stage), forwards what the dev server knows, and keeps the rest in memory, exactly in the
annex's shapes: POST /folders, PATCH /items/{id} {parent_id, parent_wrap, meta_ct, trashed, expires_at},
GET /me/items?view=all|trash|gone&parent=, uploads with parent_id/parent_wrap, /config with
features.folders on. Every byte the page encrypts is the product code's; only the server's bookkeeping of
the tree is faked. When the dev server itself reports features.folders, attach() leaves it all to the
server, except SealLog's exit receipts for a fake built with seallog=True (dev runs with SealLog off).
"""
import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

API = "/api/v1"


def _b64id():
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")


class DriveFake:
    def __init__(self, origin, trash_days=30, max_days=30, seallog=False):
        self.origin = origin.rstrip("/")
        self.seallog = seallog       # receipts on (dev runs with SealLog off): /seallog/proof/{id}?kind=exit answers
        self.exit_tx = None          # None: every exit waits for the next checkpoint; a tx id: committed in it
        self.trash_days, self.max_days = trash_days, max_days
        self.folders = {}      # id -> row
        self.over = {}         # item id -> overrides (parent_id, parent_wrap, meta_ct, trashed_at, expires_at)
        self.known = {}        # item id -> the last row the server listed (for gone rows)
        self.gone = {}         # item id -> row with exit_hour
        self.calls = []        # (method, path) of every faked call, for checks
        self.native = None

    # --- plumbing ---------------------------------------------------------------------------------

    def server_has_folders(self):
        if self.native is None:
            with urllib.request.urlopen(self.origin + API + "/config", timeout=10) as res:
                self.native = bool(json.load(res).get("features", {}).get("folders"))
        return self.native

    def attach(self, page):
        """Proxy this page's API calls (all pages of one drive share one fake). Once the dev server has
        folders, only SealLog's exit receipts stay faked (dev runs with SealLog off), when asked for."""
        if self.server_has_folders():
            if not self.seallog:
                return self
            patterns = [f"{self.origin}{API}/config", f"{self.origin}{API}/seallog/proof/*"]
        else:
            patterns = [f"{self.origin}{API}/*"]
        page.on("Fetch.requestPaused", lambda p: self._paused(page, p))
        page.cmd("Fetch.enable", {"patterns": [{"urlPattern": u, "requestStage": "Request"} for u in patterns]})
        return self

    def _forward(self, req, path=None, body=None):
        url = self.origin + (path or urllib.parse.urlsplit(req["url"]).path + ("?" + urllib.parse.urlsplit(req["url"]).query if urllib.parse.urlsplit(req["url"]).query else ""))
        data = body if body is not None else (req.get("postData").encode() if req.get("postData") is not None else None)
        headers = {k: v for k, v in req.get("headers", {}).items() if k.lower() not in ("host", "content-length", "accept-encoding", "connection")}
        r = urllib.request.Request(url, data=data, method=req["method"], headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=60) as res:
                return res.status, res.read(), dict(res.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def _fulfil(self, page, rid, status, body, headers=None):
        raw = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
        hdrs = [{"name": k, "value": v} for k, v in (headers or {}).items()
                if k.lower() in ("content-type", "retry-after", "cache-control")] or [{"name": "Content-Type", "value": "application/json"}]
        page.cmd("Fetch.fulfillRequest", {"requestId": rid, "responseCode": status, "responseHeaders": hdrs,
                                          "body": base64.b64encode(raw).decode()})

    def _paused(self, page, params):
        req, rid = params["request"], params["requestId"]
        parts = urllib.parse.urlsplit(req["url"])
        path, query = parts.path[len(API):], urllib.parse.parse_qs(parts.query)
        method = req["method"]
        try:
            out = self._route(req, method, path, query)
        except Exception as e:  # a broken fake must fail the flow loudly, never hang the page
            out = (500, {"error": {"code": "internal", "message": f"drivefake: {e}", "details": {}}}, None)
        if out is None:
            return page.cmd("Fetch.continueRequest", {"requestId": rid})
        status, body, headers = out
        self._fulfil(page, rid, status, body, headers)

    # --- the routes -------------------------------------------------------------------------------

    def _route(self, req, method, path, query):
        if method == "PUT" or path.startswith("/blobs/"):     # ciphertext chunks and downloads pass untouched
            return None
        try:
            body = json.loads(req["postData"]) if req.get("postData") else {}
        except ValueError:
            body = {}
        if self.native and not (path == "/config" or path.startswith("/seallog/proof/")):
            return None
        if method == "GET" and path == "/config":
            status, raw, headers = self._forward(req)
            cfg = json.loads(raw)
            if self.native:   # the server's own folders block; SealLog receipts on
                cfg["features"]["seallog"] = True
                cfg["seal_log"] = {**cfg.get("seal_log", {}), "component": "component_" + "fd" * 32}
                return status, cfg, {"Content-Type": "application/json"}
            cfg.setdefault("features", {})["folders"] = True
            cfg["folders"] = {"max_depth": 16, "max_children": 1000, "max_tree": 1000, "max_items": 10000,
                              "max_upload_files": 500, "zip_max_bytes": 2 << 30, "zip_max_bytes_phone": 500 << 20}
            cfg.setdefault("retention", {})["trash_days"] = self.trash_days
            cfg["items"] = {"max_delete_after_days": self.max_days}
            if self.seallog:
                cfg["features"]["seallog"] = True
                cfg["seal_log"] = {**cfg.get("seal_log", {}), "component": "component_" + "fd" * 32}
            return status, cfg, {"Content-Type": "application/json"}
        if method == "POST" and path == "/folders":
            self.calls.append((method, path))
            fid = _b64id()
            now = int(time.time())
            self.folders[fid] = {"item_id": fid, "kind": "folder", "retention": "kept", "size_stored": 0, "chunk_count": 0,
                                 "created_hour": now - now % 3600, "expires_at": None, "header": body["header"],
                                 "meta_ct": body["meta_ct"], "owner_wrap": body["owner_wrap"], "parent_id": body.get("parent_id"),
                                 "parent_wrap": body.get("parent_wrap"), "trashed_at": None, "shares": []}
            return 201, {"item_id": fid}, None
        if method == "POST" and path == "/uploads" and body.get("parent_id"):
            self.calls.append((method, path))
            status, raw, headers = self._forward(req)
            if status == 201:
                item = json.loads(raw)["item_id"]
                self.over.setdefault(item, {}).update(parent_id=body["parent_id"], parent_wrap=body.get("parent_wrap"))
            return status, raw, headers
        if method == "PATCH" and path.startswith("/items/"):
            self.calls.append((method, path))
            item = path.split("/")[2]
            o = self.folders.get(item) if item in self.folders else self.over.setdefault(item, {})
            for k in ("parent_id", "parent_wrap", "meta_ct", "expires_at"):
                if k in body:
                    o[k] = body[k]
            if "trashed" in body:
                o["trashed_at"] = int(time.time()) if body["trashed"] else None
            return 200, {"item_id": item}, None
        if method == "DELETE" and path.startswith("/items/"):
            self.calls.append((method, path))
            item = path.split("/")[2]
            if item in self.folders:
                for child in [i for i, o in self.over.items() if o.get("parent_id") == item]:
                    self._forward(req, path=f"{API}/items/{child}")
                    self._leave(child)
                self.folders.pop(item)
                return 204, b"", None
            status, raw, headers = self._forward(req)
            if status == 204:
                self._leave(item)
            return status, raw, headers
        if method == "GET" and path == "/me/items":
            return self._list(req, query)
        if method == "GET" and path == "/me":     # the server lane's quota.trash_bytes: the trash counts until it empties
            status, raw, headers = self._forward(req)
            if status != 200:
                return status, raw, headers
            me = json.loads(raw)
            me["quota"]["trash_bytes"] = sum(self.known.get(i, {}).get("size_stored", 0) for i, o in self.over.items() if o.get("trashed_at"))
            return 200, me, {"Content-Type": "application/json"}
        if method == "GET" and path.startswith("/seallog/proof/") and (query.get("kind") or [""])[0] == "exit":
            self.calls.append((method, path))
            item = path.split("/")[3]
            if not self.seallog or (item not in self.gone and not self.native):
                return 404, {"error": {"code": "not_found", "message": "This file hasn't left.", "details": {}}}, None
            if self.exit_tx:   # committed: the shape of handlers/seallog.py _proof() with checkpoint_json()
                proof = {"leaf_index": 7, "proof": ["ab" * 32] * 6, "checkpoint": {"index": 3, "tree_size": 64, "tx_id": self.exit_tx}}
            else:
                proof = {"leaf_index": None, "proof": {"pending": True, "next_checkpoint_eta": int(time.time()) + 600}, "checkpoint": None}
            now = int(time.time())
            hour = self.gone[item]["exit_hour"] if item in self.gone else now - now % 3600
            return 200, {"item_id": item, "kind": "exit", "exit_hour": hour, "leaf_hash": "cd" * 32, **proof}, None
        return None

    def _leave(self, item):
        row = dict(self.known.get(item) or {"item_id": item})
        now = int(time.time())
        row.update(self.over.get(item, {}))
        row.update(exit_hour=now - now % 3600, reason="deleted", trashed_at=None)
        self.gone[item] = row

    def _row(self, row):
        out = {**row, "kind": row.get("kind", "file"), "parent_id": None, "parent_wrap": None, "trashed_at": None}
        out.update(self.over.get(row["item_id"], {}))
        if out.get("trashed_at"):
            out["shares"] = [{**s, "state": "revoked" if s["state"] == "active" else s["state"]} for s in out.get("shares", [])]
        return out

    def _list(self, req, query):
        view = (query.get("view") or ["all"])[0]
        parent = (query.get("parent") or [None])[0]
        if view == "gone":     # the server lane's gone_entry(): no links, exit_receipt for files only
            keep = ("item_id", "kind", "created_hour", "exit_hour", "reason", "header", "meta_ct", "owner_wrap")
            rows = [{**{k: r.get(k) for k in keep}, "kind": r.get("kind", "file"), "exit_receipt": r.get("kind", "file") == "file"}
                    for r in self.gone.values()]
            return 200, {"items": rows, "next": None}, None
        q = {k: v[0] for k, v in query.items() if k not in ("view", "parent")}
        status, raw, headers = self._forward(req, path=f"{API}/me/items?{urllib.parse.urlencode(q)}")
        if status != 200:
            return status, raw, headers
        data = json.loads(raw)
        rows = []
        for r in data["items"]:
            self.known[r["item_id"]] = r
            rows.append(self._row(r))
        if "cursor" not in q:
            rows = [dict(f) for f in self.folders.values()] + rows
        rows = [r for r in rows if bool(r.get("trashed_at")) == (view == "trash")]
        if parent:
            rows = [r for r in rows if (r.get("parent_id") or "root") == parent]
        data["items"] = rows
        return 200, data, {"Content-Type": "application/json"}
