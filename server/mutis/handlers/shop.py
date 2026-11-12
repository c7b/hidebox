# SPDX-License-Identifier: MIT
"""A drive's shop (docs/shop.md; the lifecycle and limits are in shop.py), behind features.shop and pay_to_open.

The owner's routes (`/me/shop*`) take the drive's session, as every other drive route. The public read (`GET
/shop/{ref}`, a username or, for a shop made before names, its id) takes none: a public shop answers anyone; a private
one answers only to its read token (`X-Mutis-Shop`), and as if it didn't exist to everyone else. No shop's key ever
reaches us: a visitor with the shop's whole link buys through the pay link's own page (/p/{id}), and one without it asks
the seller's drive through the market (handlers/market.py, docs/market.md). The page itself (`/shop/<ref>`) and the
sitemap of public shops are shop_page.py's.
"""
from .. import codec, db, market, shop, tree
from ..http_util import ApiError, Response, get_b64, get_enum, invalid, json_response
from .shares import folder_tree

MODES = ("private", "public")


def _on(ctx) -> None:
    ctx.require_feature("shop")
    ctx.require_feature("pay_to_open")


def _shop_json(conn, row, now: int) -> dict:
    return {"shop_id": row["id"], "path": shop.path_of(row), "username": row["username"], "mode": row["mode"],
            "title": row["title"], "bio": row["bio"], "key_wrap": codec.b64u(row["key_wrap"]),
            "has_token": row["token_hash"] is not None, "state": row["state"], "created_at": row["created_at"],
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
    """Turn the shop on (201) or change it (200): `{title, bio, username, mode?, key_wrap, token_hash, relisted?}`.

    - `username`: required for a new shop, and for an older one the first time it takes a name; a change gives the old
      name up (held for its drive, shop.HOLD_S). 409 `username_taken` when another shop has it or a look-alike of it.
    - `key_wrap` (the shop key wrapped under the drive's) and `token_hash` (SHA-256 of the read token,
      HKDF(shop key, "mutis/v2", "shop-read")) come with a new key; a shop made before tokens adds its `token_hash`.
    - `mode`: `private` (the default) or `public` (anyone can read the shop, and its listings are in the market). The
      shop key stays in the drive in both: one sent here (`shop_key`) is refused. Going private again drops the shop
      from the market and ends its asks; the key stays, since we never had it. A new key (`key_wrap`, `token_hash`)
      may come at any time with `relisted`, every listing's `{share_id, link_ct}` sealed with it.
    The id is ours, random; a shop that was removed stays removed (403 `shop_removed`)."""
    _on(ctx)
    identity = ctx.session()
    body = ctx.req.json()
    title = shop.plain_text(body, "title", shop.TITLE_MAX, required=True)
    bio = shop.plain_text(body, "bio", shop.BIO_MAX, required=False, lines=shop.BIO_LINES)
    name = shop.username(body) if body.get("username") is not None else None
    mode = get_enum(body, "mode", MODES) if body.get("mode") is not None else None
    key_wrap = get_b64(body, "key_wrap", shop.KEY_WRAP_LEN, optional=True)
    token_hash = get_b64(body, "token_hash", 32, optional=True)
    if body.get("shop_key") is not None:
        raise ApiError(422, "invalid", "A shop's key stays in your drive.", details={"field": "shop_key"})
    relisted = body.get("relisted")
    if relisted is not None and (not isinstance(relisted, list) or len(relisted) > shop.MAX_LISTINGS):
        raise invalid("relisted")
    ctx.limit(("shop_put", identity["id"], shop.PUTS_PER_DAY, 86400, 1))
    conn = ctx.db
    with db.tx(conn):
        row = shop.own_shop(conn, identity["id"])
        if row is not None and row["state"] != "open":
            raise ApiError(403, "shop_removed", "This shop was removed after a report.")
        mode = mode or (row["mode"] if row is not None else "private")
        if row is None:
            if key_wrap is None or token_hash is None:
                raise ApiError(422, "invalid", "A new shop needs its key and its token.",
                               details={"field": "key_wrap" if key_wrap is None else "token_hash"})
            if name is None:
                raise invalid("username", "Pick a name for your shop's address.")
        new_key = row is not None and key_wrap is not None and not codec.equal(key_wrap, row["key_wrap"])
        if row is not None and not new_key and token_hash is not None and row["token_hash"] is not None \
                and not codec.equal(token_hash, row["token_hash"]):
            raise ApiError(409, "conflict", "A new token comes with a new key.")
        if row is not None and row["username"] is None and name is None:
            raise invalid("username", "Pick a name for your shop's address.")
        if new_key and token_hash is None:
            raise ApiError(422, "invalid", "A new key needs its token.", details={"field": "token_hash"})
        going_private = row is not None and row["mode"] == "public" and mode == "private"
        hashed = token_hash if (row is None or new_key or row["token_hash"] is None) else row["token_hash"]
        if hashed is None:
            raise ApiError(422, "invalid", "This shop needs its token.", details={"field": "token_hash"})
        if name is not None and (row is None or name != row["username"]) and not shop.name_free(conn, name, identity["id"], ctx.now):
            raise ApiError(409, "username_taken", "Another shop has that name, or one that reads the same.",
                           details={"field": "username"})
        if row is None:
            shop_id = codec.new_id()
            conn.execute("INSERT INTO shops(id, identity_id, title, bio, key_wrap, created_at, updated_at, username, "
                         "skeleton, mode, token_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (shop_id, identity["id"], title, bio, key_wrap, ctx.now, ctx.now, name, shop.skeleton(name),
                          mode, hashed))
            status = 201
        else:
            if new_key:
                _relist(conn, row, relisted)
            elif relisted is not None:
                raise invalid("relisted")
            if name is not None and name != row["username"]:
                shop.hold_name(conn, row, ctx.now)
            username = name or row["username"]
            conn.execute("UPDATE shops SET title = ?, bio = ?, key_wrap = ?, username = ?, skeleton = ?, mode = ?, "
                         "token_hash = ?, updated_at = ? WHERE id = ?",
                         (title, bio, key_wrap if new_key else row["key_wrap"], username, shop.skeleton(username), mode,
                          hashed, ctx.now, row["id"]))
            if going_private:
                market.end_for_shop(conn, row["id"])
            conn.execute("DELETE FROM shop_name_holds WHERE skeleton = ? AND identity_id = ?",
                         (shop.skeleton(username), identity["id"]))
            status = 200
    return json_response(status, {"shop": _shop_json(conn, shop.own_shop(conn, identity["id"]), ctx.now)})


def _relist(conn, row, relisted) -> None:
    """A new shop key: every listing comes sealed again with it, all of them at once, or nothing changes (409
    `relist_needed` with the listings' ids, when one was added or taken off in between)."""
    have = [r[0] for r in conn.execute("SELECT share_id FROM shop_listings WHERE shop_id = ?", (row["id"],))]
    given = {}
    for entry in relisted or []:
        if not isinstance(entry, dict) or set(entry) != {"share_id", "link_ct"} or not isinstance(entry["share_id"], str):
            raise invalid("relisted")
        given[entry["share_id"]] = get_b64(entry, "link_ct", shop.LINK_CT_LEN)
    if set(given) != set(have):
        raise ApiError(409, "relist_needed", "Your listings changed. Seal them again with the new key.",
                       details={"share_ids": sorted(have)})
    for share_id, link_ct in given.items():
        conn.execute("UPDATE shop_listings SET link_ct = ? WHERE share_id = ? AND shop_id = ?", (link_ct, share_id, row["id"]))


def delete_mine(ctx):
    """Turn the shop off: the shop and its listings go, so its page answers 404. The pay links keep selling."""
    _on(ctx)
    identity = ctx.session()
    conn = ctx.db
    with db.tx(conn):
        row = shop.own_shop(conn, identity["id"])
        if row is not None and row["state"] != "open":
            raise ApiError(403, "shop_removed", "This shop was removed after a report.")
        shop.hold_name(conn, row, ctx.now)            # the name stays this drive's for a while
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
    # The shop key the browser sealed with, named by its wrap: a tab that still holds a key the shop no longer has (it
    # went private, with a new key, elsewhere) must not list anything under the old one, which our server knew.
    sealed_under = get_b64(body, "key_wrap", shop.KEY_WRAP_LEN, optional=True)
    ctx.limit(("shop_list", identity["id"], shop.LISTING_WRITES_PER_HOUR, 3600, 1))
    conn = ctx.db
    with db.tx(conn):
        row = _open_shop(ctx, identity)
        if sealed_under is None or not codec.equal(sealed_under, row["key_wrap"]):
            raise ApiError(409, "key_changed", "Your shop has a new key since this page opened. Open My shop again.")
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
        conn.execute("DELETE FROM market_asks WHERE share_id = ? AND shop_id = ?", (share_id, row["id"]))
    if not gone:
        raise ApiError(404, "not_found", "This shop doesn't list that.")
    return Response(204)


# --- anyone ------------------------------------------------------------------------------------------------

def public(ctx, ref: str):
    """The shop's data: its title, bio and what sells now. A public shop answers anyone (each listing's `link_ct` opens
    only with the key after the shop link's #; without it, a visitor asks through the market); a private one answers
    only with its read token in `X-Mutis-Shop`, and 404 otherwise, as for a shop that doesn't exist. 410 `gone` (reason `removed`) after a takedown. Never the drive, its address or
    anything about who bought."""
    _on(ctx)
    ctx.limit(("shop64", ctx.ip64, shop.READS_PER_MINUTE, 60, 1))
    row = shop.by_ref(ctx.db, ref)
    if row is None and ref.isascii() and ref.lower() != ref:
        row = shop.by_ref(ctx.db, ref.lower())          # /shop/Mila is /shop/mila
    # A private shop answers nothing without its token, open or removed: the name alone tells nothing of it.
    if row is not None and row["mode"] == "private" and row["token_hash"] is not None:
        try:
            token = codec.unb64u(ctx.req.header("X-Mutis-Shop") or "", shop.TOKEN_LEN)
        except (ValueError, TypeError):
            token = None
        if not shop.token_ok(row, token):
            row = None
    if row is None:
        raise ApiError(404, "not_found", "No shop has this address.")
    if row["state"] != "open":
        raise ApiError(410, "gone", "This shop was removed.", details={"reason": "removed",
                                                                      "ended_day": codec.day(row["updated_at"])})
    out = {"title": row["title"], "bio": row["bio"], "username": row["username"], "mode": row["mode"],
           "path": shop.path_of(row), "items": shop.public_listings(ctx.db, row["id"], ctx.now)}
    if row["mode"] == "public":
        out["market"] = bool(ctx.features().get("market"))      # Ask for it, without the shop's key
        return json_response(200, out, "public, max-age=60")
    return json_response(200, out, "private, no-store")
