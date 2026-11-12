# SPDX-License-Identifier: MIT
"""A drive's shop (docs/shop.md; the lifecycle and limits are in shop.py), behind features.shop and pay_to_open.

The owner's routes (`/me/shop*`) take the drive's session, as every other drive route. The public read (`GET
/shop/{id}`) takes none and answers the same to everyone: the shop's title and bio and the listings that sell now,
cached a minute like the other public reads. Buying is the pay link's own page (/p/{id}), unchanged.
"""
from .. import codec, db, shop, tree
from ..http_util import ApiError, Response, get_b64, json_response
from .shares import folder_tree


def _on(ctx) -> None:
    ctx.require_feature("shop")
    ctx.require_feature("pay_to_open")


def _shop_json(conn, row, now: int) -> dict:
    return {"shop_id": row["id"], "path": f"/shop/{row['id']}", "title": row["title"], "bio": row["bio"],
            "key_wrap": codec.b64u(row["key_wrap"]), "state": row["state"], "created_at": row["created_at"],
            "listings": shop.owner_listings(conn, row["id"], now) if row["state"] == "open" else []}


def _open_shop(ctx, identity):
    row = shop.own_shop(ctx.db, identity["id"])
    if row is None:
        raise ApiError(404, "not_found", "This drive has no shop. Turn it on first.")
    if row["state"] != "open":
        raise ApiError(403, "shop_removed", "This shop was removed after a report.")
    return row


# --- the owner (a drive session) -------------------------------------------------------------------------

def get_mine(ctx):
    """The drive's shop with every listing (`selling`: it shows now), or `{shop: null}` while it's off."""
    _on(ctx)
    identity = ctx.session()
    row = shop.own_shop(ctx.db, identity["id"])
    return json_response(200, {"shop": _shop_json(ctx.db, row, ctx.now) if row else None})


def put_mine(ctx):
    """Turn the shop on (201, with `key_wrap`: the shop's key wrapped under the drive's) or change its title and bio
    (200). The id is ours, random; a shop that was removed stays removed (403 `shop_removed`)."""
    _on(ctx)
    identity = ctx.session()
    body = ctx.req.json()
    title = shop.plain_text(body, "title", shop.TITLE_MAX, required=True)
    bio = shop.plain_text(body, "bio", shop.BIO_MAX, required=False, lines=shop.BIO_LINES)
    key_wrap = get_b64(body, "key_wrap", shop.KEY_WRAP_LEN, optional=True)
    ctx.limit(("shop_put", identity["id"], shop.PUTS_PER_DAY, 86400, 1))
    conn = ctx.db
    with db.tx(conn):
        row = shop.own_shop(conn, identity["id"])
        if row is not None and row["state"] != "open":
            raise ApiError(403, "shop_removed", "This shop was removed after a report.")
        if row is None:
            if key_wrap is None:
                raise ApiError(422, "invalid", "A new shop needs its key.", details={"field": "key_wrap"})
            conn.execute("INSERT INTO shops(id, identity_id, title, bio, key_wrap, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", (codec.new_id(), identity["id"], title, bio, key_wrap,
                                                          ctx.now, ctx.now))
            status = 201
        else:
            if key_wrap is not None and not codec.equal(key_wrap, row["key_wrap"]):
                raise ApiError(409, "conflict", "This shop keeps its key. Turn it off and on for a new one.")
            conn.execute("UPDATE shops SET title = ?, bio = ?, updated_at = ? WHERE id = ?",
                         (title, bio, ctx.now, row["id"]))
            status = 200
    return json_response(status, {"shop": _shop_json(conn, shop.own_shop(conn, identity["id"]), ctx.now)})


def delete_mine(ctx):
    """Turn the shop off: the shop and its listings go, so its page answers 404. The pay links keep selling."""
    _on(ctx)
    identity = ctx.session()
    conn = ctx.db
    with db.tx(conn):
        row = shop.own_shop(conn, identity["id"])
        if row is not None and row["state"] != "open":
            raise ApiError(403, "shop_removed", "This shop was removed after a report.")
        conn.execute("DELETE FROM shops WHERE identity_id = ? AND state = 'open'", (identity["id"],))
    return Response(204)


def put_listing(ctx, share_id: str):
    """List one of the drive's pay links, or change its title and line: `{title, description, link_ct}`. Our server
    fills in what it already knows of the link (file or folder, the padded size, the price); never a name."""
    _on(ctx)
    identity = ctx.session()
    body = ctx.req.json()
    title = shop.plain_text(body, "title", shop.ITEM_TITLE_MAX, required=True)
    description = shop.plain_text(body, "description", shop.DESC_MAX, required=False)
    link_ct = get_b64(body, "link_ct", shop.LINK_CT_LEN)
    ctx.limit(("shop_list", identity["id"], shop.LISTING_WRITES_PER_HOUR, 3600, 1))
    conn = ctx.db
    with db.tx(conn):
        row = _open_shop(ctx, identity)
        link = shop.sold_link(conn, identity["id"], share_id, ctx.now)
        if link["kind"] == "folder":
            size = sum(r["size_stored"] for r in folder_tree(conn, link["id"], tree.MAX_TREE))
        else:
            size = link["size_stored"]
        old = conn.execute("SELECT shop_id FROM shop_listings WHERE share_id = ?", (share_id,)).fetchone()
        if old is None:
            listed = conn.execute("SELECT COUNT(*) FROM shop_listings WHERE shop_id = ?", (row["id"],)).fetchone()[0]
            if listed >= shop.MAX_LISTINGS:
                raise ApiError(409, "shop_full", "This shop lists as many things as it can. Take one off first.",
                               details={"max_listings": shop.MAX_LISTINGS})
            conn.execute("INSERT INTO shop_listings(share_id, shop_id, title, description, kind, size_stored, price_ut, "
                         "link_ct, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (share_id, row["id"], title, description, link["kind"], size, link["price_ut"], link_ct,
                          ctx.now))
            status = 201
        else:
            conn.execute("UPDATE shop_listings SET title = ?, description = ?, link_ct = ?, size_stored = ? "
                         "WHERE share_id = ? AND shop_id = ?", (title, description, link_ct, size, share_id, row["id"]))
            status = 200
    listing = next((x for x in shop.owner_listings(conn, row["id"], ctx.now) if x["share_id"] == share_id), None)
    if listing is None:             # its link ended in the instant after this listing was written
        raise ApiError(409, "not_selling", "This pay link has ended. Make a new one to list it.")
    return json_response(status, {"listing": listing})


def delete_listing(ctx, share_id: str):
    """Take a pay link off the shop; the link itself keeps selling."""
    _on(ctx)
    identity = ctx.session()
    ctx.limit(("shop_list", identity["id"], shop.LISTING_WRITES_PER_HOUR, 3600, 1))
    conn = ctx.db
    with db.tx(conn):
        row = _open_shop(ctx, identity)
        gone = conn.execute("DELETE FROM shop_listings WHERE share_id = ? AND shop_id = ?",
                            (share_id, row["id"])).rowcount
    if not gone:
        raise ApiError(404, "not_found", "This shop doesn't list that.")
    return Response(204)


# --- anyone ------------------------------------------------------------------------------------------------

def public(ctx, shop_id: str):
    """The shop's page: its title, bio and what sells now. 404 when there is none (or it was turned off), 410
    `gone` (reason `removed`) after a takedown. Never the drive, its address or anything about who bought."""
    _on(ctx)
    ctx.limit(("shop64", ctx.ip64, shop.READS_PER_MINUTE, 60, 1))
    row = ctx.db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No shop has this address.")
    if row["state"] != "open":
        raise ApiError(410, "gone", "This shop was removed.", details={"reason": "removed",
                                                                      "ended_day": codec.day(row["updated_at"])})
    return json_response(200, {"title": row["title"], "bio": row["bio"],
                               "items": shop.public_listings(ctx.db, shop_id, ctx.now)}, "public, max-age=60")
