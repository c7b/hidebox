# SPDX-License-Identifier: MIT
"""The market (docs/market.md; the rules are in market.py), behind features.market, shop and pay_to_open.

Anyone: `GET /market` (what public shops sell, searchable), `POST /market/asks` (ask a listing's seller for its half of
the pay link's key, with a key pair made for the ask and a proof of work) and `GET /market/asks/{id}` (the ask's state
and, once answered, the sealed answer, to whoever holds the ask's token). The seller's drive: `GET /me/market/asks`
(asks waiting for its answer) and `PUT /me/market/asks/{id}` (the answer, sealed to the ask's keys, or a refusal).
Our server stores and relays sealed answers it can't open.
"""
from .. import codec, db, market, shop
from ..http_util import PARAM_RE, ApiError, Response, get_b64, invalid, json_response

KINDS = ("file", "folder")


def _on(ctx) -> None:
    ctx.require_feature("market")
    ctx.require_feature("shop")
    ctx.require_feature("pay_to_open")


def browse(ctx):
    """A page of listings in public shops, newest first: `?q=` words, `?kind=file|folder`, `?cursor=` (from `next`)."""
    _on(ctx)
    ctx.limit(("market64", ctx.ip64, market.READS_PER_MINUTE, 60, 1))
    query = ctx.req.query
    words = market.query_words(query.get("q"))
    kind = query.get("kind") or None
    if kind is not None and kind not in KINDS:
        raise invalid("kind")
    items, nxt = market.search(ctx.db, words, kind, market.parse_cursor(query.get("cursor")), ctx.now)
    return json_response(200, {"items": items, "next": nxt}, "public, max-age=60")


def _id(body: dict, name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not PARAM_RE["id"].match(value):
        raise invalid(name)
    return value


def ask(ctx):
    """Ask for a listing: `{ask_id, share_id, owner_pk, view_pk, token_hash, pow}`. The id and the token come from a
    secret only the shopper's browser holds; the two public keys are a pair made for this ask. 201 `{ask_id,
    expires_at}`; 404 when the listing isn't in the market; 429 `asks_full` when it has as many asks waiting as it
    may; 409 `conflict` for an id already taken."""
    _on(ctx)
    body = ctx.req.json()
    ask_id, share_id = _id(body, "ask_id"), _id(body, "share_id")
    owner_pk = get_b64(body, "owner_pk", market.KEY_LEN)
    view_pk = get_b64(body, "view_pk", market.KEY_LEN)
    token_hash = get_b64(body, "token_hash", 32)
    if codec.equal(owner_pk, view_pk):
        raise invalid("view_pk")
    ctx.limit(("ask64", ctx.ip64, market.ASKS_PER_HOUR, 3600, 1))
    ctx.proof_of_work("ask", body)
    conn, now = ctx.db, ctx.now
    with db.tx(conn):
        row = market.listing(conn, share_id, now)
        if row is None:
            raise ApiError(404, "not_found", "This isn't for sale in the market.")
        if market.waiting(conn, share_id, now) >= market.MAX_WAITING:
            raise ApiError(429, "asks_full", "Many people are waiting for this one. Try again later.", retry_after=3600)
        if conn.execute("SELECT 1 FROM market_asks WHERE id = ?", (ask_id,)).fetchone():
            raise ApiError(409, "conflict", "That ask exists already.")
        expires = now + market.ASK_S
        conn.execute("INSERT INTO market_asks(id, share_id, shop_id, owner_pk, view_pk, token_hash, created_at, expires_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (ask_id, share_id, row["shop_id"], owner_pk, view_pk, token_hash,
                                                        now, expires))
    return json_response(201, {"ask_id": ask_id, "expires_at": expires})


def ask_state(ctx, ask_id: str):
    """The ask, to whoever shows its token (`X-Mutis-Ask`): waiting, or answered with the sealed answer. 404 for an ask
    that doesn't exist, has run out, ended with its listing, or was asked with another token: all alike."""
    _on(ctx)
    ctx.limit(("askget64", ctx.ip64, market.ASK_READS_PER_MINUTE, 60, 1))
    try:
        token = codec.unb64u(ctx.req.header("X-Mutis-Ask") or "", 32)
    except (ValueError, TypeError):
        token = None
    row = market.live_ask(ctx.db, ask_id, ctx.now)
    if row is None or token is None or not codec.equal(codec.sha256(token), row["token_hash"]):
        raise ApiError(404, "not_found", "This ask has ended.")
    return json_response(200, market.ask_json(row), "private, no-store")


def _public_shop(ctx, identity):
    row = shop.own_shop(ctx.db, identity["id"])
    return row if row is not None and row["state"] == "open" and row["mode"] == "public" else None


def mine(ctx):
    """The asks waiting for this drive's answer (its shop public), oldest first, at most market.OWNER_PAGE."""
    _on(ctx)
    identity = ctx.session()
    row = _public_shop(ctx, identity)
    return json_response(200, {"asks": market.owner_asks(ctx.db, row["id"], ctx.now) if row else []})


def answer(ctx, ask_id: str):
    """Answer an ask of this drive's shop: `{answer}` (the listing's sA sealed to the ask's keys, 125 bytes) or
    `{refused: true}` (the drive couldn't seal to those keys: the ask goes). 204; 404 for an ask that isn't this
    shop's or has run out; 409 for one answered already with something else."""
    _on(ctx)
    identity = ctx.session()
    body = ctx.req.json()
    refused = body.get("refused") is True
    sealed = None if refused else get_b64(body, "answer", market.ANSWER_LEN)
    ctx.limit(("ask_answer", identity["id"], market.ANSWERS_PER_HOUR, 3600, 1))
    conn, now = ctx.db, ctx.now
    with db.tx(conn):
        own = _public_shop(ctx, identity)
        row = market.live_ask(conn, ask_id, now) if own else None
        if row is None or row["shop_id"] != own["id"]:
            raise ApiError(404, "not_found", "No ask of your shop has this id.")
        if refused:
            conn.execute("DELETE FROM market_asks WHERE id = ?", (ask_id,))
        elif row["answer"] is not None:
            if not codec.equal(row["answer"], sealed):
                raise ApiError(409, "conflict", "This ask has its answer already.")
        else:
            conn.execute("UPDATE market_asks SET answer = ?, answered_at = ? WHERE id = ?", (sealed, now, ask_id))
    return Response(204)
