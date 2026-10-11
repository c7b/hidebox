# SPDX-License-Identifier: MIT
"""The route table of spec §6.3. Path parameters are validated by type before a handler runs."""
from dataclasses import dataclass
from typing import Callable

from .handlers import (abuse, auth, blobs, canary, chain, courier, drops, invoices, me, seallog, shares, stats,
                       system, uploads)
from .http_util import PARAM_RE, ApiError


@dataclass(frozen=True)
class Route:
    method: str
    segments: tuple[str, ...]
    handler: Callable
    name: str


class Router:
    def __init__(self, table: list[tuple[str, str, Callable, str]]):
        self.routes = [Route(m, tuple(p.strip("/").split("/")), h, n) for m, p, h, n in table]

    def match(self, method: str, path: str):
        parts = path.strip("/").split("/")
        for route in self.routes:
            if route.method != method:
                continue
            params = self._bind(route.segments, parts)
            if params is not None:
                return route, params
        return None, {}

    @staticmethod
    def _bind(segments: tuple[str, ...], parts: list[str]) -> dict | None:
        params = {}
        for i, seg in enumerate(segments):
            if seg == "{rest:*}":
                params["rest"] = "/".join(parts[i:])
                return params if len(parts) > i else None
            if i >= len(parts):
                return None
            if seg.startswith("{"):
                name, kind = seg[1:-1].split(":")
                if not PARAM_RE[kind].match(parts[i]):
                    params["_bad"] = name
                params[name] = parts[i]
            elif seg != parts[i]:
                return None
        if len(parts) != len(segments):
            return None
        if "_bad" in params:
            raise ApiError(400, "bad_request", "Malformed id in the path.", details={"field": params["_bad"]})
        return params


V = "/api/v1"
ROUTER = Router([
    ("GET", f"{V}/health", system.health, "system.health"),
    ("GET", f"{V}/config", system.config, "system.config"),
    ("POST", f"{V}/pow", system.pow, "system.pow"),
    ("GET", f"{V}/stats", stats.stats, "stats.stats"),
    ("GET", f"{V}/stats/wall", stats.wall, "stats.wall"),

    ("POST", f"{V}/uploads", uploads.create, "uploads.create"),
    ("PUT", f"{V}/uploads/{{upload_id:id}}/chunks/{{index:index}}", uploads.put_chunk, "uploads.chunk"),
    ("POST", f"{V}/uploads/{{upload_id:id}}/complete", uploads.complete, "uploads.complete"),
    ("DELETE", f"{V}/uploads/{{upload_id:id}}", uploads.abort, "uploads.abort"),

    ("POST", f"{V}/items/{{item_id:id}}/shares", shares.create, "shares.create"),
    ("GET", f"{V}/s/{{share_id:id}}", shares.status, "shares.status"),
    ("POST", f"{V}/s/{{share_id:id}}/peek", shares.peek, "shares.peek"),
    ("POST", f"{V}/s/{{share_id:id}}/open", shares.open_share, "shares.open"),
    ("PATCH", f"{V}/s/{{share_id:id}}", shares.patch, "shares.patch"),
    ("GET", f"{V}/s/{{share_id:id}}/manage", shares.manage, "shares.manage"),
    ("DELETE", f"{V}/s/{{share_id:id}}", shares.revoke, "shares.revoke"),
    ("GET", f"{V}/s/{{share_id:id}}/exit", seallog.exit_receipt, "shares.exit"),
    ("GET", f"{V}/s/{{share_id:id}}/stored", shares.stored_bytes, "shares.stored"),
    ("DELETE", f"{V}/items/{{item_id:id}}", shares.delete_item, "items.delete"),
    ("POST", f"{V}/items/{{item_id:id}}/adopt", shares.adopt, "items.adopt"),

    ("GET", f"{V}/blobs/{{ticket:ticket}}", blobs.download, "blobs.get"),
    ("POST", f"{V}/blobs/{{ticket:ticket}}/done", blobs.done, "blobs.done"),

    ("POST", f"{V}/auth/register", auth.register, "auth.register"),
    ("POST", f"{V}/auth/session", auth.sign_in, "auth.session"),
    ("DELETE", f"{V}/auth/session", auth.sign_out, "auth.sign_out"),
    ("GET", f"{V}/me", me.get_me, "me.get"),
    ("DELETE", f"{V}/me", me.delete_me, "me.delete"),
    ("PUT", f"{V}/me/bundle", me.put_bundle, "me.bundle_put"),
    ("GET", f"{V}/me/bundle", me.get_bundle, "me.bundle_get"),
    ("GET", f"{V}/me/items", me.list_items, "me.items"),
    ("POST", f"{V}/me/items/{{item_id:id}}/open", me.open_item, "me.item_open"),

    ("POST", f"{V}/drops", drops.create, "drops.create"),
    ("GET", f"{V}/drops/{{drop_id:drop}}", drops.get_drop, "drops.get"),
    ("PATCH", f"{V}/drops/{{drop_id:drop}}", drops.patch, "drops.patch"),
    ("DELETE", f"{V}/drops/{{drop_id:drop}}", drops.close, "drops.close"),

    ("POST", f"{V}/courier", courier.send, "courier.send"),
    ("GET", f"{V}/jobs/{{job_id:id}}", courier.job, "jobs.get"),

    ("GET", f"{V}/chain/utxos", chain.utxos, "chain.utxos"),
    ("GET", f"{V}/chain/seq", chain.seq, "chain.seq"),
    ("GET", f"{V}/chain/tx/{{tx_id:tx}}/view", chain.tx_view, "chain.tx_view"),
    ("GET", f"{V}/chain/ix/{{rest:*}}", chain.proxy, "chain.proxy"),
    ("POST", f"{V}/chain/ix/{{rest:*}}", chain.proxy, "chain.proxy"),

    ("POST", f"{V}/invoices", invoices.create, "invoices.create"),
    ("GET", f"{V}/invoices/{{invoice_id:invoice}}", invoices.get_invoice, "invoices.get"),
    ("POST", f"{V}/invoices/{{invoice_id:invoice}}/demo-pay", invoices.demo_pay, "invoices.demo_pay"),
    ("POST", f"{V}/sponsor", invoices.sponsor, "invoices.sponsor"),

    ("GET", f"{V}/canary", canary.latest, "canary.get"),
    ("GET", f"{V}/canary/raw", canary.raw, "canary.raw"),

    ("POST", f"{V}/abuse", abuse.report, "abuse.report"),

    ("GET", f"{V}/seallog/checkpoints", seallog.checkpoints, "seallog.checkpoints"),
    ("GET", f"{V}/seallog/proof/{{item_id:id}}", seallog.proof, "seallog.proof"),
])
