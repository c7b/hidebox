# SPDX-License-Identifier: MIT
"""GET/DELETE /me, the G2a key bundle, and the P1 kept-files list (spec §6.3)."""
import re
import secrets

from .. import cleanup, codec, db, items, quota
from ..http_util import ApiError, Response, get_b64, json_response
from .shares import _egress_ok, is_paid, opens_by_hour, paid_summary, share_json
from .system import limits_block

BUNDLE_MAX = 4096
PAGE_MAX = 50
OPENS_HOURS = 168               # a week of hourly open counts per link in the drive's list
_CURSOR = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{22})$")


def get_me(ctx):
    identity = ctx.session()
    pool = quota.measure(ctx.db, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], ctx.now)
    q = quota.free_quota(ctx.db, pool)
    cls = quota.class_of(identity, ctx.now)
    paid_active = cls == "paid"
    today = codec.day(ctx.now)
    # The drive's counts (16-drive-design §7): files and folders outside the Trash, and what the Trash
    # still holds (it counts in used_bytes until it empties).
    counts = ctx.db.execute(
        "SELECT COALESCE(SUM(CASE WHEN trashed_at IS NOT NULL THEN size_stored END), 0) AS trash_bytes, "
        "COUNT(CASE WHEN trashed_at IS NULL AND kind = 'file' THEN 1 END) AS files, "
        "COUNT(CASE WHEN trashed_at IS NULL AND kind = 'folder' THEN 1 END) AS folders "
        "FROM items WHERE owner_id = ? AND state = 'ready'", (identity["id"],)).fetchone()
    return json_response(200, {
        "identity": {"id": identity["id"], "created_day": identity["created_day"],
                     "probation": identity["distinct_days"] < 2},
        "plan": "paid" if paid_active else "free",
        "quota": {"limit_bytes": quota.locker_limit(identity, q, ctx.now), "used_bytes": identity["used_bytes"],
                  "reserved_bytes": identity["reserved_bytes"], "free_bytes": q,
                  "paid_bytes": identity["paid_bytes"] if paid_active else 0,
                  "paid_until": identity["paid_until"] if paid_active else None,
                  "trash_bytes": counts["trash_bytes"]},
        "files": counts["files"], "folders": counts["folders"],
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


def item_entry(conn, row, now: int) -> dict:
    """One item as the drive lists it, with its links (state, rule, opens left, opens per hour over the
    last `OPENS_HOURS` hours; `GET /s/{id}/manage` has them all)."""
    shares = conn.execute("SELECT * FROM shares WHERE item_id = ? ORDER BY created_hour", (row["id"],)).fetchall()
    since = codec.floor_hour(now) - (OPENS_HOURS - 1) * 3600
    return {"item_id": row["id"], "kind": row["kind"], "retention": row["retention"],
            "size_stored": row["size_stored"], "chunk_count": row["chunk_count"], "created_hour": row["created_hour"],
            "expires_at": row["expires_at"], "header": codec.b64u(row["header"]), "meta_ct": codec.b64u(row["meta_ct"]),
            "owner_wrap": codec.b64u(row["owner_wrap"]) if row["owner_wrap"] else None,
            "parent_id": row["parent_id"],
            "parent_wrap": codec.b64u(row["parent_wrap"]) if row["parent_wrap"] else None,
            "trashed_at": row["trashed_at"],
            "shares": [_share_entry(conn, s, now, since) for s in shares]}


def _share_entry(conn, share, now: int, since: int) -> dict:
    """A link as its item's row shows it; a paid link adds its summary (the row badge "{k} paid")."""
    out = {**share_json(share, now), "opens": opens_by_hour(conn, share["id"], since)}
    if is_paid(conn, share["id"]):
        out["paid"] = paid_summary(conn, share["id"])
    return out


def gone_entry(row, conn=None) -> dict:
    """An item that left this drive (`view=gone`, for Activity): enough to decrypt its name in the browser
    and recompute its exit leaf (`exit_receipt`: files only; a folder has no ciphertext). Fifth pass: with
    `conn`, `opens` too: its links' opens per UTC hour, summed (share_opens stays until the tombstone purge,
    16-drive-design §6), so Activity shows Opened before It left your drive."""
    out = {"item_id": row["id"], "kind": row["kind"], "created_hour": row["created_hour"],
           "exit_hour": row["exit_hour"], "reason": gone_reason(row), "exit_receipt": row["ct_hash"] is not None,
           "header": codec.b64u(row["header"]), "meta_ct": codec.b64u(row["meta_ct"]),
           "owner_wrap": codec.b64u(row["owner_wrap"]) if row["owner_wrap"] else None}
    if conn is not None:
        opens = {}
        for r in conn.execute("SELECT o.hour, o.n FROM share_opens o JOIN shares s ON s.id = o.share_id "
                              "WHERE s.item_id = ?", (row["id"],)):
            opens[r["hour"]] = opens.get(r["hour"], 0) + r["n"]
        out["opens"] = [[hour, n] for hour, n in sorted(opens.items())]
    return out


def gone_reason(row) -> str:
    """Why it left, from what the row already holds (no reason column: no new metadata). `deleted` covers
    Delete, the lapse of extra space and an unopened drive."""
    if row["state"] == "removed":
        return "removed"
    if row["trashed_at"] is not None:
        return "trash"
    if row["expires_at"] is not None and row["expires_at"] <= (row["exit_hour"] or 0) + 3600:
        return "expired"
    return "link_ended" if row["retention"] == "ephemeral" else "deleted"


VIEWS = ("all", "trash", "gone")


def list_items(ctx):
    """This drive's items, newest first, a page at a time, with their links.

    `view=all` (the default): every item outside the Trash, folders and files alike, flat (the locker UI's
    list). `parent=root|<folder id>`: one folder's contents. `view=trash`: what was put in the Trash, by
    when. `view=gone`: what left the drive in the last `tombstone_days` days. The cursor is
    "<hour or time>.<item_id>" of the last row: it says nothing about other drives' files.
    """
    ctx.require_feature("kept")
    identity = ctx.session()
    query = ctx.req.query
    limit = _query_int(ctx, "limit", 1, PAGE_MAX) if query.get("limit") else PAGE_MAX
    view = query.get("view", "all")
    parent = query.get("parent")
    if view not in VIEWS or (parent is not None and view != "all"):
        raise ApiError(400, "bad_request", "Bad view.")
    if (parent is not None or view != "all") and not ctx.features()["folders"]:
        raise ApiError(503, "feature_disabled", "This feature is off right now.", details={"feature": "folders"})
    key, after = 1 << 40, "~"                    # "~" sorts after every base64url character
    if query.get("cursor"):
        m = _CURSOR.match(query["cursor"])
        if not m:
            raise ApiError(400, "bad_request", "Bad cursor.")
        key, after = int(m.group(1)), m.group(2)
    conn, owner = ctx.db, identity["id"]
    if view == "gone":
        since = ctx.now - cleanup.TOMBSTONE_DAYS * 86400
        rows = conn.execute("SELECT * FROM items WHERE owner_id = ? AND state IN ('deleted','removed') "
                            "AND exit_hour >= ? AND (exit_hour < ? OR (exit_hour = ? AND id < ?)) "
                            "ORDER BY exit_hour DESC, id DESC LIMIT ?",
                            (owner, since, key, key, after, limit)).fetchall()
        out, order = [gone_entry(r, conn) for r in rows], "exit_hour"
    elif view == "trash":
        # Trash roots: trashed items whose folder isn't in the Trash with them (same moment).
        rows = conn.execute("SELECT i.* FROM items i LEFT JOIN items p ON p.id = i.parent_id "
                            "WHERE i.owner_id = ? AND i.state = 'ready' AND i.trashed_at IS NOT NULL "
                            "AND (p.id IS NULL OR p.state <> 'ready' OR p.trashed_at IS NOT i.trashed_at) "
                            "AND (i.trashed_at < ? OR (i.trashed_at = ? AND i.id < ?)) "
                            "ORDER BY i.trashed_at DESC, i.id DESC LIMIT ?", (owner, key, key, after, limit)).fetchall()
        out, order = [item_entry(conn, r, ctx.now) for r in rows], "trashed_at"
    else:
        where, args = "owner_id = ? AND state = 'ready'", [owner]
        if parent is None:
            where += " AND trashed_at IS NULL"
        else:
            folder = None if parent == "root" else conn.execute(
                "SELECT * FROM items WHERE id = ? AND owner_id = ? AND kind = 'folder' AND state = 'ready'",
                (parent, owner)).fetchone()
            if parent != "root" and folder is None:
                raise ApiError(404, "not_found", "No such folder in this drive.")
            where += " AND parent_id IS NULL" if folder is None else " AND parent_id = ?"
            args += [] if folder is None else [folder["id"]]
            if folder is None or folder["trashed_at"] is None:
                where += " AND trashed_at IS NULL"           # inside the Trash, a folder shows what it holds
        rows = conn.execute(f"SELECT * FROM items WHERE {where} AND (created_hour < ? OR (created_hour = ? AND id < ?)) "
                            "ORDER BY created_hour DESC, id DESC LIMIT ?", (*args, key, key, after, limit)).fetchall()
        out, order = [item_entry(conn, r, ctx.now) for r in rows], "created_hour"
    next_cursor = f"{rows[-1][order]}.{rows[-1]['id']}" if len(rows) == limit else None
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
        if item["kind"] == "folder":
            raise ApiError(409, "conflict", "A folder has nothing to download; list what it holds.")
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
