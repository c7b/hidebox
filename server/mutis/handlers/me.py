# SPDX-License-Identifier: MIT
"""GET/DELETE /me, the G2a key bundle, and the P1 kept-files list (spec §6.3)."""
import re
import secrets

from .. import codec, db, items, quota
from ..http_util import ApiError, Response, get_b64, json_response
from .shares import _egress_ok, share_json
from .system import limits_block

BUNDLE_MAX = 4096
PAGE_MAX = 50
_CURSOR = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{22})$")


def get_me(ctx):
    identity = ctx.session()
    pool = quota.measure(ctx.db, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], ctx.now)
    q = quota.free_quota(ctx.db, pool)
    cls = quota.class_of(identity, ctx.now)
    paid_active = cls == "paid"
    today = codec.day(ctx.now)
    return json_response(200, {
        "identity": {"id": identity["id"], "created_day": identity["created_day"],
                     "probation": identity["distinct_days"] < 2},
        "plan": "paid" if paid_active else "free",
        "quota": {"limit_bytes": quota.locker_limit(identity, q, ctx.now), "used_bytes": identity["used_bytes"],
                  "reserved_bytes": identity["reserved_bytes"], "free_bytes": q,
                  "paid_bytes": identity["paid_bytes"] if paid_active else 0,
                  "paid_until": identity["paid_until"] if paid_active else None},
        "limits": limits_block()[cls],
        "sends_today": identity["sends_today"] if identity["sends_day"] == today else 0,
    })


def delete_me(ctx):
    """Delete the locker, its sessions, items (blobs now) and links; invoices keep anonymized rows."""
    identity = ctx.session()
    auth_key = get_b64(ctx.req.json(), "auth_key", 32)
    if not codec.equal(codec.sha256(auth_key), identity["auth_verifier"]):
        raise ApiError(401, "bad_auth", "This key doesn't open this locker.")
    conn = ctx.db
    with db.tx(conn):
        for row in conn.execute("SELECT id FROM items WHERE owner_id = ? AND state IN ('uploading','ready','doomed')",
                                (identity["id"],)).fetchall():
            items.doom_item(conn, row["id"], "owner_deleted", ctx.now)
            items.unlink(conn, ctx.app.blobs, row["id"], "deleted", ctx.now)
        conn.execute("DELETE FROM identities WHERE id = ?", (identity["id"],))
    return Response(204)


def _bundle_gate(ctx) -> None:
    if not ctx.cfg["gates"]["key_bundle"]:
        raise ApiError(503, "feature_disabled", "Key bundles aren't used on this deployment.",
                       details={"feature": "key_bundle"})


def put_bundle(ctx):
    _bundle_gate(ctx)
    identity = ctx.session()
    bundle = get_b64(ctx.req.json(), "bundle_ct", max_len=BUNDLE_MAX)
    with db.tx(ctx.db):
        ctx.db.execute("UPDATE identities SET bundle_ct = ? WHERE id = ?", (bundle, identity["id"]))
    return Response(204)


def get_bundle(ctx):
    _bundle_gate(ctx)
    identity = ctx.session()
    if identity["bundle_ct"] is None:
        raise ApiError(404, "not_found", "No key bundle stored.")
    return json_response(200, {"bundle_ct": codec.b64u(identity["bundle_ct"])})


def list_items(ctx):
    """P1: this locker's files (kept and ephemeral), newest hour first, with their links.

    The cursor is "<created_hour>.<item_id>" of the last row: it says nothing about other lockers' files.
    """
    ctx.require_feature("kept")
    identity = ctx.session()
    limit = _query_int(ctx, "limit", 1, PAGE_MAX) if ctx.req.query.get("limit") else PAGE_MAX
    hour, after = 1 << 40, "~"                    # "~" sorts after every base64url character
    if ctx.req.query.get("cursor"):
        m = _CURSOR.match(ctx.req.query["cursor"])
        if not m:
            raise ApiError(400, "bad_request", "Bad cursor.")
        hour, after = int(m.group(1)), m.group(2)
    rows = ctx.db.execute("SELECT * FROM items WHERE owner_id = ? AND state = 'ready' "
                          "AND (created_hour < ? OR (created_hour = ? AND id < ?)) "
                          "ORDER BY created_hour DESC, id DESC LIMIT ?",
                          (identity["id"], hour, hour, after, limit)).fetchall()
    out = []
    for row in rows:
        shares = ctx.db.execute("SELECT * FROM shares WHERE item_id = ? ORDER BY created_hour", (row["id"],)).fetchall()
        out.append({"item_id": row["id"], "retention": row["retention"], "size_stored": row["size_stored"],
                    "chunk_count": row["chunk_count"], "created_hour": row["created_hour"],
                    "expires_at": row["expires_at"], "header": codec.b64u(row["header"]),
                    "meta_ct": codec.b64u(row["meta_ct"]),
                    "owner_wrap": codec.b64u(row["owner_wrap"]) if row["owner_wrap"] else None,
                    "shares": [share_json(s, ctx.now) for s in shares]})
    next_cursor = f"{rows[-1]['created_hour']}.{rows[-1]['id']}" if len(rows) == limit else None
    return json_response(200, {"items": out, "next": next_cursor})


def _query_int(ctx, name: str, lo: int, hi: int) -> int:
    value = ctx.req.query.get(name, "")
    if not value.isdigit() or not lo <= int(value) <= hi:
        raise ApiError(400, "bad_request", f"Bad {name}.")
    return int(value)


def open_item(ctx, item_id: str):
    """P1: the owner reads their own file without using any link's views."""
    ctx.require_feature("kept")
    identity = ctx.session()
    conn = ctx.db
    with db.tx(conn):
        item = conn.execute("SELECT * FROM items WHERE id = ? AND owner_id = ? AND state = 'ready'",
                            (item_id, identity["id"])).fetchone()
        if item is None:
            raise ApiError(404, "not_found", "No such file in this locker.")
        if not _egress_ok(conn, item, ctx.now, item["size_stored"]):
            raise ApiError(429, "rate_limited", "This file was downloaded a lot today.")
        inline = item["size_stored"] <= quota.INLINE_MAX_STORED
        ticket = None if inline else secrets.token_bytes(32)
        if ticket:
            conn.execute("INSERT INTO tickets(token_hash, share_id, item_id, expires_at, max_bytes) "
                         "VALUES (?, NULL, ?, ?, ?)", (codec.sha256(ticket), item_id, ctx.now + items.TICKET_S,
                                                       3 * item["size_stored"]))
    return json_response(200, {
        "header": codec.b64u(item["header"]), "meta_ct": codec.b64u(item["meta_ct"]),
        "owner_wrap": codec.b64u(item["owner_wrap"]) if item["owner_wrap"] else None,
        "chunk_size": quota.CHUNK, "chunk_count": item["chunk_count"], "size_stored": item["size_stored"],
        "ticket": codec.b64u(ticket) if ticket else None,
        "ticket_expires_at": ctx.now + items.TICKET_S if ticket else None,
        "inline_ct": codec.b64u(ctx.app.blobs.read_all(item_id)) if inline else None})
