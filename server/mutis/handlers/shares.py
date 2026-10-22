# SPDX-License-Identifier: MIT
"""Links (shares): create, status, peek, the atomic open, edits, revocation and adoption.

Spec §4.6–§4.7 (access tokens, link proofs, the online-guessing policy), §5.2–§5.4, §6.3 Links,
brand patches P-25 (first_opened_min) and the P1 "Download the stored bytes" endpoint.

A folder link (16-drive-architecture §2.3) opens the folder's whole subtree in one view: the open returns
the tree (ids, headers, encrypted names, wraps) and a folder ticket that serves any file which, at the
moment it is asked for, still sits in that folder outside the Trash. Opens are counted per link per UTC
hour (`share_opens`), never per person.

There is no server-side "Keep" for a received file: a recipient keeps one by opening it normally
and sealing the plaintext again as their own kept file. The sender's link then still ends on its
rule, and the sender's ciphertext still leaves.
"""
import json
import secrets

from .. import codec, counts, db, items, lanes, quota, sales, tree
from ..http_util import ApiError, Response, get_b64, get_bool, get_enum, get_int, invalid, json_response
from .blobs import ranged

PW_LOCK_AFTER = 5            # link + password: wrong tries (with a valid link proof) before the first pause
PW_DELAY_START_S = 60
PW_DELAY_MAX_S = 3600
PW_PERMANENT_AFTER = 50
PWONLY_POW_AFTER = 3          # password only: per (link, IP key) failures before PoW and waiting start
PWONLY_GLOBAL_HARD = 100      # password only: daily failures across everyone before every try needs 20 bits
PWONLY_HARD_BITS = 20
EGRESS_PER_ITEM_DAY = items.EGRESS_PER_ITEM_DAY
UNLIMITED_OPENS_PER_HOUR = 60
TEASER_MAX = 2076             # iv ‖ AES-GCM(teaserKey, JSON padded to 256-byte steps): the pay page's preview
KDF_MIN_ITER, KDF_MAX_ITER = 600_000, 5_000_000
NOT_KNOWN = ["file_name", "file_type", "file_content", "link_key", "password", "ip_address_on_disk"]


# --- lookups and authorization ---------------------------------------------------------------------

def get_share(conn, share_id: str):
    row = conn.execute("SELECT * FROM shares WHERE id = ?", (share_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No active link has this id.")
    return row


def get_item(conn, item_id: str):
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None or row["state"] in ("deleted", "removed"):
        raise ApiError(404, "not_found", "No such item.")
    return row


def require_owner(ctx, item, allow_canary: bool = False) -> None:
    """The item's locker session, its manage token, or (canary items only) the canary token."""
    identity = ctx.session(required=False)
    if identity is not None and item["owner_id"] == identity["id"]:
        return
    token = ctx.manage_token()
    if token is not None and codec.equal(codec.sha256(token), item["manage_hash"]):
        return
    if allow_canary and item["canary"] and ctx.is_canary():
        return
    raise ApiError(403, "forbidden", "Only the owner can do that.")


def class_of_item(conn, item, now: int) -> str:
    if item["canary"]:
        return "canary"
    if item["lane"] == "drop":
        return "drop"
    if item["owner_id"] is None:
        return "anon"
    owner = conn.execute("SELECT * FROM identities WHERE id = ?", (item["owner_id"],)).fetchone()
    return quota.class_of(owner, now)


def effective_state(share, now: int) -> str:
    if share["state"] == "active" and share["expires_at"] is not None and now >= share["expires_at"]:
        return "expired"
    return share["state"]


def gone(share, state: str, now: int) -> ApiError:
    ended = share["ended_at"] or share["expires_at"] or now
    return ApiError(410, "gone", "This link has ended.",
                    details={"reason": items.ENDED_REASON[state], "ended_day": codec.day(ended)})


def _header_b64(ctx, name: str, length: int) -> bytes | None:
    value = ctx.req.header(name)
    if value is None:
        return None
    try:
        return codec.unb64u(value, length)
    except ValueError:
        return b""


def password_precheck(ctx, share, body: dict) -> None:
    """Password-only links: per (link, IP key) backoff and PoW, and a 20-bit PoW on busy days (spec §4.7)."""
    if share["mode"] != "password" or share["state"] != "active":
        return
    fails, last = ctx.app.pw_tries.get((share["id"], ctx.ip64), (0, 0))
    hard = share["pw_fails_day"] == codec.day(ctx.now) and share["pw_fails_today"] >= PWONLY_GLOBAL_HARD
    if fails < PWONLY_POW_AFTER and not hard:
        return
    if fails >= PWONLY_POW_AFTER:
        wait_until = last + 60 * min(2 ** (fails - PWONLY_POW_AFTER), 60)
        if ctx.now < wait_until:
            raise ApiError(428, "pow_required", "Wait a moment before trying again.", retry_after=wait_until - ctx.now,
                           details={"purpose": "password", "difficulty": PWONLY_HARD_BITS if hard else 16})
    ctx.proof_of_work("password", body, PWONLY_HARD_BITS if hard else 0)


def check_secrets(ctx, conn, share) -> ApiError | None:
    """Link proof and access token checks of spec §5.3, with the failure counters they update.

    Returns the error to raise after the caller commits (so counters persist), or None when allowed.
    """
    now = ctx.now
    if share["mode"] == "link_password":
        proof = _header_b64(ctx, "X-Mutis-Link", 32)
        if not proof or not codec.equal(codec.sha256(proof), share["link_hash"]):
            ctx.limit(("badlink", (share["id"], ctx.ip64), 30, 3600, 1))
            return ApiError(403, "bad_link", "This link is incomplete or wrong.")
        if share["pw_locked"]:
            return ApiError(423, "locked", "Too many wrong passwords. Ask the sender for a new link.",
                            details={"permanent": True})
        if share["pw_backoff_until"] and share["pw_backoff_until"] > now:
            return ApiError(423, "locked", "Too many wrong passwords. Wait a little.",
                            retry_after=share["pw_backoff_until"] - now, details={"permanent": False})
    token = _header_b64(ctx, "X-Mutis-Access", 32)
    if token and codec.equal(codec.sha256(token), share["access_hash"]):
        return None
    if share["mode"] == "link" or not token:
        return ApiError(403, "bad_access", "This link's key doesn't match.")
    if share["mode"] == "link_password":
        fails = share["pw_fail_count"] + 1
        locked = int(fails >= PW_PERMANENT_AFTER)
        backoff = None
        if fails >= PW_LOCK_AFTER and not locked:
            backoff = now + min(PW_DELAY_START_S * 2 ** (fails - PW_LOCK_AFTER), PW_DELAY_MAX_S)
        conn.execute("UPDATE shares SET pw_fail_count = ?, pw_locked = ?, pw_backoff_until = ? WHERE id = ?",
                     (fails, locked, backoff, share["id"]))
        return ApiError(403, "bad_access", "That's not the password.",
                        details={"tries_left": max(0, PW_LOCK_AFTER - fails)})
    today = codec.day(now)
    conn.execute("UPDATE shares SET pw_fails_today = CASE WHEN pw_fails_day = ? THEN pw_fails_today + 1 ELSE 1 END, "
                 "pw_fails_day = ? WHERE id = ?", (today, today, share["id"]))
    ctx.app.pw_tries.update((share["id"], ctx.ip64), lambda tries: (tries[0] + 1, now), (0, 0))
    return ApiError(403, "bad_access", "That's not the password.")


def authorized_share(ctx, share_id: str, body: dict):
    """Run the access checks for peek-like reads (no view used). Returns (share, item)."""
    conn = ctx.db
    share = get_share(conn, share_id)
    password_precheck(ctx, share, body)
    with db.tx(conn):
        share = get_share(conn, share_id)
        state = effective_state(share, ctx.now)
        if state != "active":
            error = gone(share, state, ctx.now)
        else:
            error = paid_claim(ctx, conn, share)[0] or check_secrets(ctx, conn, share)
    if error:
        raise error
    return share, conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()


def is_paid(conn, share_id: str) -> bool:
    return conn.execute("SELECT 1 FROM paid_shares WHERE share_id = ?", (share_id,)).fetchone() is not None


def paid_claim(ctx, conn, share) -> tuple[ApiError | None, str | None]:
    """Pay to open's gate (16-drive-architecture §1.5): a paid link opens, peeks and serves its bytes only
    with a released claim of this link (`X-Mutis-Claim`) that has opens left in its window. Checked before
    the link's own key, so a link without a payment reads 402 rather than a key error. Returns (error, the
    claim id to spend an open from); (None, None) for a link that isn't paid."""
    if not is_paid(conn, share["id"]):
        return None, None
    token = _header_b64(ctx, "X-Mutis-Claim", 32)
    if token is None:
        return ApiError(402, "payment_required", "Pay to open this."), None
    claim = conn.execute("SELECT * FROM claims WHERE share_id = ? AND token_hash = ?",
                         (share["id"], codec.sha256(token) if token else b"")).fetchone()
    if claim is None:
        return ApiError(403, "bad_claim", "This payment belongs to another link or browser."), None
    why = sales.usable(claim, ctx.now)
    if why == "payment_required":
        return ApiError(402, "payment_required", "This opens once your payment is on the chain."), None
    if why is not None:
        return ApiError(410, "claim_used", "Your payment's opens are used up." if why == "no_opens_left"
                        else "Your payment's time to open this is over.", details={"reason": why}), None
    return None, claim["id"]


# --- JSON shapes ---------------------------------------------------------------------------------

def share_json(share, now: int) -> dict:
    state = effective_state(share, now)
    left = None if share["max_views"] is None else max(0, share["max_views"] - share["views_used"])
    return {"id": share["id"], "mode": share["mode"], "state": state, "created_hour": share["created_hour"],
            "expires_at": share["expires_at"], "max_views": share["max_views"], "views_used": share["views_used"],
            "views_left": left}


def item_json(item, conn=None) -> dict:
    out = {"size_stored": item["size_stored"], "chunk_count": item["chunk_count"], "retention": item["retention"],
           "created_hour": item["created_hour"], "lane": item["lane"],
           "owner": "a locker" if item["owner_id"] else "nobody",
           "ct_hash": codec.b64u(item["ct_hash"]) if item["ct_hash"] else None, "kind": item["kind"]}
    if item["kind"] == "folder" and conn is not None:
        out["child_count"] = len(folder_tree(conn, item["id"], tree.MAX_TREE + 1))
    return out


def folder_tree(conn, folder_id: str, limit: int) -> list:
    """What a folder link shows: every ready descendant outside the Trash, breadth first."""
    rows = tree.subtree(conn, folder_id, ("ready",), limit + 1)[1:]          # [0] is the folder itself
    return [r for r in rows if r["trashed_at"] is None][:limit]


def opens_by_hour(conn, share_id: str, since: int | None = None) -> list[list[int]]:
    """[[hour, n], …] oldest first: how many times a link opened in each UTC hour (C40: a count, never who)."""
    rows = conn.execute("SELECT hour, n FROM share_opens WHERE share_id = ? AND hour >= ? ORDER BY hour",
                        (share_id, since or 0)).fetchall()
    return [[r["hour"], r["n"]] for r in rows]


def created_json(share, paid: bool = False) -> dict:
    return {"share_id": share["id"], "path": f"/{'p' if paid else 's'}/{share['id']}", "state": share["state"],
            "max_views": share["max_views"], "expires_at": share["expires_at"]}


# --- create ----------------------------------------------------------------------------------------

def _kdf(body: dict) -> str:
    kdf = body.get("kdf")
    if not isinstance(kdf, dict) or set(kdf) != {"alg", "iter", "salt"} or kdf["alg"] != "PBKDF2-SHA256" \
            or type(kdf["iter"]) is not int or not KDF_MIN_ITER <= kdf["iter"] <= KDF_MAX_ITER:
        raise invalid("kdf")
    get_b64(kdf, "salt", 16)
    return json.dumps({"alg": kdf["alg"], "iter": kdf["iter"], "salt": kdf["salt"]}, separators=(",", ":"))


def link_rules(cls: str, max_views, expires_at, item, now: int) -> tuple[int | None, int | None]:
    """Apply the class limits of spec §9.4 to a link's exit rule. Returns (max_views, expires_at)."""
    if cls == "drop":                       # fixed: 3 opens until the item's 7-day expiry
        return 3, item["expires_at"]
    if cls == "canary":                     # fixed: 3 opens within 24 hours
        return 3, min(now + 86400, item["expires_at"])
    limits = quota.CLASSES[cls]
    if max_views is None and cls not in ("locker", "paid"):
        raise invalid("max_views")
    if max_views is not None and not 1 <= max_views <= limits["max_views"]:
        raise invalid("max_views")
    if expires_at is None:
        if item["retention"] == "kept":
            return max_views, None          # "Never": a kept file's link may have no expiry
        if item["expires_at"] is not None:  # the file's own expiry passed this check when it was uploaded
            return max_views, item["expires_at"]
        expires_at = now + limits["default_expiry_s"]
    if expires_at <= now or expires_at > now + limits["max_expiry_s"] + 60 \
            or (item["expires_at"] is not None and expires_at > item["expires_at"]):
        raise invalid("expires_at")
    return max_views, _coarse(expires_at, item, now)


def _coarse(expires_at: int, item, now: int) -> int:
    rounded = codec.coarse_expiry(expires_at, now)
    return rounded if item["expires_at"] is None else min(rounded, item["expires_at"])


def create(ctx, item_id: str):
    body = ctx.req.json()
    conn = ctx.db
    item = get_item(conn, item_id)
    require_owner(ctx, item, allow_canary=True)
    mode = get_enum(body, "mode", ("link", "link_password", "password", "pay"))
    paid = _paid_fields(ctx, body, item) if mode == "pay" else None
    if paid:
        mode = "link"                       # a paid link opens like a plain link, once a claim is released
    wrapped = get_b64(body, "wrapped_key", 60)
    access_verifier = get_b64(body, "access_verifier", 32)
    link_verifier = get_b64(body, "link_verifier", 32, optional=True)
    if (mode == "link_password") != (link_verifier is not None):
        raise invalid("link_verifier")
    if mode == "link":
        if body.get("kdf") is not None:
            raise invalid("kdf")
        kdf = None
    else:
        kdf = _kdf(body)
    max_views = get_int(body, "max_views", 1, 1_000_000, optional=True)
    expires_at = get_int(body, "expires_at", 0, 2 ** 40, optional=True)
    then_delete = get_bool(body, "then_delete")
    # viral-1 (C60): a tab that arrived through Make your own secret says so once; only a one-off link from the
    # home's share box (an item without a drive) adds to the day's number
    from_share = get_bool(body, "from_share")
    cls = class_of_item(conn, item, ctx.now)
    if cls == "drop" and mode != "link":
        raise invalid("mode", "Drop deliveries use a plain link.")
    if item["kind"] == "folder":
        ctx.require_feature("folders")
    if paid:
        if max_views is not None or expires_at is not None or then_delete:
            raise invalid("mode", "A paid link opens for each buyer; it has no rule of its own.")
    else:
        max_views, expires_at = link_rules(cls, max_views, expires_at, item, ctx.now)
    if then_delete:
        _check_then_delete(ctx, item, expires_at)
    per_item = 1 if cls in ("drop", "canary") else quota.CLASSES[cls]["links_per_item"]
    share_id = codec.new_id()
    with db.tx(conn):
        item = get_item(conn, item_id)
        if item["state"] != "ready":
            raise ApiError(409, "item_not_ready", "Finish the upload first.")
        if item["trashed_at"] is not None:
            raise ApiError(409, "trashed", "Bring it back from the Trash first.")
        if conn.execute("SELECT COUNT(*) FROM shares WHERE item_id = ?", (item_id,)).fetchone()[0] >= per_item:
            raise ApiError(409, "conflict", "This file has as many links as it can have.",
                           details={"max_links": per_item})
        if paid and conn.execute("SELECT 1 FROM shares s JOIN paid_shares p ON p.share_id = s.id "
                                 "WHERE s.item_id = ? AND s.state = 'active'", (item_id,)).fetchone():
            raise ApiError(409, "conflict", "This already has a link to pay for. Stop that one first.")
        conn.execute("INSERT INTO shares(id, item_id, mode, wrapped_key, access_hash, link_hash, kdf, max_views, "
                     "expires_at, created_hour) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (share_id, item_id, mode, wrapped, access_verifier, link_verifier, kdf, max_views, expires_at,
                      codec.floor_hour(ctx.now)))
        if paid:
            conn.execute("INSERT INTO paid_shares(share_id, price_ut, server_half, teaser_ct, buyer_views, "
                         "buyer_window_s) VALUES (?, ?, ?, ?, ?, ?)",
                         (share_id, paid["price_ut"], paid["server_half"], paid["teaser_ct"], sales.BUYER_VIEWS,
                          sales.BUYER_WINDOW_S))
        if from_share and cls == "anon":
            counts.add(conn, "secret_from_share", ctx.now)
        if then_delete:
            # "Delete it from my drive after" (16-drive-design §3): the file leaves with its last link, at
            # the latest when this one expires, and gets its exit receipt (C42).
            conn.execute("UPDATE items SET retention = 'ephemeral', expires_at = MIN(COALESCE(expires_at, ?), ?) "
                         "WHERE id = ?", (expires_at, expires_at, item_id))
    out = created_json(get_share(conn, share_id), bool(paid))
    if then_delete:
        out["item_expires_at"] = conn.execute("SELECT expires_at FROM items WHERE id = ?", (item_id,)).fetchone()[0]
    return json_response(201, out)


def _paid_fields(ctx, body: dict, item) -> dict:
    """Pay to open (16-drive-architecture §1.5): a drive's own kept file or folder, a price from /config,
    our half of the link's key, and a registered sales address (`PUT /me/sales`)."""
    ctx.require_feature("pay_to_open")
    if ctx.cfg["gates"]["amount_proof"] != "sidecar":
        raise ApiError(503, "feature_disabled", "This feature is off right now.", details={"feature": "pay_to_open"})
    identity = ctx.session(required=False)
    if identity is None or item["owner_id"] != identity["id"] or item["retention"] != "kept" or item["canary"]:
        raise invalid("mode", "Only something kept in your drive can be sold.")
    if body.get("link_verifier") is not None or body.get("kdf") is not None:
        raise invalid("mode", "A paid link has no password.")
    price = body.get("price_ut")
    if not isinstance(price, (str, int)) or isinstance(price, bool) or str(price) not in [str(p) for p in sales.PRICES_UT]:
        raise invalid("price_ut", "Pick one of the prices offered.")
    fields = {"price_ut": int(price), "server_half": get_b64(body, "server_half", 32),
              "teaser_ct": get_b64(body, "teaser_ct", optional=True, max_len=TEASER_MAX)}
    if ctx.db.execute("SELECT 1 FROM sellers WHERE identity_id = ?", (identity["id"],)).fetchone() is None:
        raise ApiError(409, "seller_not_registered", "Your drive's sales address isn't set up yet.")
    return fields


def _check_then_delete(ctx, item, expires_at) -> None:
    """Only a drive's own kept file, outside the Trash, on a link that ends by itself (not "When I stop it")."""
    identity = ctx.session(required=False)
    if item["kind"] != "file" or item["retention"] != "kept" or identity is None \
            or item["owner_id"] != identity["id"]:
        raise invalid("then_delete", "Only a file kept in your drive can leave with its link.")
    if expires_at is None:
        raise invalid("then_delete", "A link that leaves with the file needs an end.")


# --- public status, peek, open -----------------------------------------------------------------------

def status(ctx, share_id: str):
    ctx.limit(("status64", ctx.ip64, 120, 60, 1))
    share = get_share(ctx.db, share_id)
    state = effective_state(share, ctx.now)
    if state != "active":
        raise gone(share, state, ctx.now)
    # No `kind` here: someone with only the path learns that a link exists and its state, not whether it
    # opens a file or a folder; the key holder reads `kind` from /peek (no view used) or /open.
    out = {"state": "active", "mode": share["mode"], "needs_password": share["mode"] != "link",
           "kdf": json.loads(share["kdf"]) if share["kdf"] else None}
    if is_paid(ctx.db, share_id):
        out["paid"] = True                       # a paid link's page is /p/{id}
    return json_response(200, out)


def peek(ctx, share_id: str):
    ctx.limit(("status64", ctx.ip64, 120, 60, 1))
    body = ctx.req.json(required=False)
    share, item = authorized_share(ctx, share_id, body)
    return json_response(200, {"share": share_json(share, ctx.now), "item": item_json(item, ctx.db),
                               "not_known": NOT_KNOWN})


_egress_ok = items.egress_ok


def _open_in_tx(ctx, conn, share_id: str) -> dict | ApiError:
    now = ctx.now
    share = conn.execute("SELECT * FROM shares WHERE id = ?", (share_id,)).fetchone()
    if share is None:
        return ApiError(404, "not_found", "No active link has this id.")
    if share["state"] != "active":
        return gone(share, share["state"], now)
    if effective_state(share, now) == "expired":
        items.end_share(conn, share_id, "expired", now)
        items.doom_if_unlinked(conn, share["item_id"], now)
        return gone(share, "expired", now)
    error, claim_id = paid_claim(ctx, conn, share)
    error = error or check_secrets(ctx, conn, share)
    if error:
        return error
    item = conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    if item["state"] != "ready":
        return ApiError(410, "gone", "This link has ended.", details={"reason": "removed", "ended_day": codec.day(now)})
    folder = item["kind"] == "folder"
    if folder:
        contents = folder_tree(conn, item["id"], tree.MAX_TREE + 1)
        if len(contents) > tree.MAX_TREE:          # before any view is used: share a smaller folder
            return ApiError(413, "too_many", "This folder holds too much to open in one visit.",
                            details={"max_tree": tree.MAX_TREE})
        total = sum(r["size_stored"] for r in contents)
    if share["max_views"] is None:
        hour = codec.floor_hour(now)
        opens = share["opens_in_hour"] if share["opens_hour"] == hour else 0
        if opens >= UNLIMITED_OPENS_PER_HOUR:
            return ApiError(429, "rate_limited", "This link was opened many times this hour.",
                            retry_after=hour + 3600 - now)
        conn.execute("UPDATE shares SET opens_hour = ?, opens_in_hour = ? WHERE id = ?", (hour, opens + 1, share_id))
    # A file's open counts its size against its daily egress; a folder visit counts each file as it is
    # served (blobs.py), since a visitor may take only some of them.
    if not folder and not _egress_ok(conn, item, now, item["size_stored"]):
        return ApiError(429, "rate_limited", "This file was downloaded a lot today.",
                        retry_after=codec.next_utc_midnight(now) - now)
    conn.execute("UPDATE shares SET views_used = views_used + 1, first_opened_min = COALESCE(first_opened_min, ?) "
                 "WHERE id = ? AND state = 'active'", (codec.floor_minute(now), share_id))
    count_open(conn, share_id, now)
    if claim_id is not None:                       # a paid link: this buyer's claim gives one open fewer
        conn.execute("UPDATE claims SET views_left = views_left - 1 WHERE id = ?", (claim_id,))
    views_used = share["views_used"] + 1
    burned = share["max_views"] is not None and views_used >= share["max_views"]
    if burned:
        items.end_share(conn, share_id, "exhausted", now)
    inline = not folder and item["size_stored"] <= quota.INLINE_MAX_STORED
    ticket = None
    if not inline:
        ticket = secrets.token_bytes(32)
        conn.execute("INSERT INTO tickets(token_hash, share_id, item_id, expires_at, max_bytes, scope) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (codec.sha256(ticket), share_id, item["id"], now + items.TICKET_S,
                      3 * (total if folder else item["size_stored"]), "tree" if folder else "item"))
    doomed = burned and items.doom_if_unlinked(conn, item["id"], now)
    response = {
        "wrapped_key": codec.b64u(share["wrapped_key"]), "header": codec.b64u(item["header"]),
        "meta_ct": codec.b64u(item["meta_ct"]), "chunk_size": quota.CHUNK, "chunk_count": item["chunk_count"],
        "size_stored": item["size_stored"], "kind": item["kind"],
        "views_left": None if share["max_views"] is None else share["max_views"] - views_used,
        "burned": burned, "ticket": codec.b64u(ticket) if ticket and not folder else None,
        "ticket_expires_at": now + items.TICKET_S if ticket else None,
        "inline_ct": codec.b64u(ctx.app.blobs.read_all(item["id"])) if inline else None}
    if folder:
        response.update({"tree": [tree_entry(r) for r in contents], "folder_ticket": codec.b64u(ticket)})
    return {"response": response, "unlink": item["id"] if inline and doomed else None}


def tree_entry(row) -> dict:
    return {"id": row["id"], "kind": row["kind"], "parent_id": row["parent_id"], "header": codec.b64u(row["header"]),
            "meta_ct": codec.b64u(row["meta_ct"]),
            "parent_wrap": codec.b64u(row["parent_wrap"]) if row["parent_wrap"] else None,
            "size_stored": row["size_stored"], "chunk_count": row["chunk_count"]}


def count_open(conn, share_id: str, now: int) -> None:
    """One more open of this link in this UTC hour (the owner's Activity; C40)."""
    conn.execute("INSERT INTO share_opens(share_id, hour, n) VALUES (?, ?, 1) "
                 "ON CONFLICT(share_id, hour) DO UPDATE SET n = n + 1", (share_id, codec.floor_hour(now)))


def open_share(ctx, share_id: str):
    """The atomic burn (spec §5.3): exactly one of N concurrent opens of a Once link succeeds."""
    ctx.limit(("open64", ctx.ip64, 60, 60, 1))
    body = ctx.req.json(required=False)
    conn = ctx.db
    password_precheck(ctx, get_share(conn, share_id), body)
    with db.tx(conn):
        outcome = _open_in_tx(ctx, conn, share_id)
    if isinstance(outcome, ApiError):
        raise outcome
    if outcome["unlink"]:
        with db.tx(conn):
            items.unlink_if_unreferenced(conn, ctx.app.blobs, outcome["unlink"], ctx.now)
    return json_response(200, outcome["response"])


def stored_bytes(ctx, share_id: str):
    """P1 "Download the stored bytes": the ciphertext exactly as stored, without using a view.

    Safe for the link holder too: the wrapped file key is released only by /open.
    """
    ctx.limit(("stored64", ctx.ip64, 30, 60, 1))
    _, item = authorized_share(ctx, share_id, {})
    if item["state"] != "ready":
        raise ApiError(410, "gone", "This link has ended.", details={"reason": "removed", "ended_day": codec.day(ctx.now)})
    if item["kind"] == "folder":
        raise ApiError(409, "conflict", "A folder has no stored bytes of its own; open it.")
    with db.tx(ctx.db):
        allowed = _egress_ok(ctx.db, item, ctx.now, item["size_stored"])
    if not allowed:
        raise ApiError(429, "rate_limited", "This file was downloaded a lot today.")
    return ranged(ctx, item["id"], item["size_stored"], "sealed.bin", "no-store")


# --- owner edits -------------------------------------------------------------------------------------

def patch(ctx, share_id: str):
    body = ctx.req.json()
    conn = ctx.db
    share = get_share(conn, share_id)
    item = conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    require_owner(ctx, item)
    max_views_given = "max_views" in body
    new_views = get_int(body, "max_views", 1, 1_000_000, optional=True)
    new_expiry = get_int(body, "expires_at", 0, 2 ** 40, optional=True)
    unlock = get_bool(body, "unlock")
    paused = body.get("paused")
    paid = is_paid(conn, share_id)
    if paused is not None and (not paid or type(paused) is not bool):
        raise invalid("paused", "Only a link to pay for can stop selling.")
    if paid and (max_views_given or new_expiry is not None or unlock):
        raise invalid("max_views", "A paid link opens for each buyer; it has no rule of its own.")
    cls = class_of_item(conn, item, ctx.now)
    with db.tx(conn):
        share = get_share(conn, share_id)
        state = effective_state(share, ctx.now)
        if state != "active":
            error = gone(share, state, ctx.now)
        elif paid:
            error = None
            if paused is not None:      # Stop selling / Sell again: no new claims; released ones keep their opens
                conn.execute("UPDATE paid_shares SET paused = ? WHERE share_id = ?", (int(paused), share_id))
        else:
            error = _apply_patch(conn, share, item, cls, max_views_given, new_views, new_expiry, unlock, ctx.now)
    if error:
        raise error
    out = created_json(get_share(conn, share_id), paid)
    if paid:
        out["paused"] = bool(conn.execute("SELECT paused FROM paid_shares WHERE share_id = ?", (share_id,)).fetchone()[0])
    return json_response(200, out)


def _apply_patch(conn, share, item, cls, views_given, new_views, new_expiry, unlock, now) -> ApiError | None:
    if cls in ("drop", "canary") and (views_given or new_expiry is not None):
        return invalid("max_views", "This link's exit rule is fixed.")
    views, expiry = share["max_views"], share["expires_at"]
    loosen = False
    if views_given:
        limits = quota.CLASSES[cls]
        if new_views is None and cls not in ("locker", "paid"):
            return invalid("max_views")
        if new_views is not None and (new_views < share["views_used"] or new_views > limits["max_views"]):
            return invalid("max_views")
        if views is not None and (new_views is None or new_views > views):
            loosen = True
        views = new_views
    if new_expiry is not None:
        limits = quota.CLASSES[cls]
        if new_expiry <= now or new_expiry > now + limits["max_expiry_s"] + 60 \
                or (item["expires_at"] is not None and new_expiry > item["expires_at"]):
            return invalid("expires_at")
        if expiry is not None and new_expiry > expiry:
            loosen = True
        expiry = _coarse(new_expiry, item, now)
    if loosen and share["views_used"] > 0:
        return ApiError(409, "already_opened", "It was already opened, so its rule can only get stricter.")
    conn.execute("UPDATE shares SET max_views = ?, expires_at = ? WHERE id = ?", (views, expiry, share["id"]))
    if unlock:
        conn.execute("UPDATE shares SET pw_fail_count = 0, pw_backoff_until = NULL, pw_locked = 0 WHERE id = ?",
                     (share["id"],))
    if views is not None and views == share["views_used"]:
        items.end_share(conn, share["id"], "exhausted", now)
        items.doom_if_unlinked(conn, item["id"], now)
    return None


def manage(ctx, share_id: str):
    conn = ctx.db
    share = get_share(conn, share_id)
    item = conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    require_owner(ctx, item)
    out = share_json(share, ctx.now)
    if out["state"] != "active":
        out["reason"] = items.ENDED_REASON[out["state"]]
    out.update({"first_opened_min": share["first_opened_min"], "pw_locked": bool(share["pw_locked"]),
                "pw_fail_count": share["pw_fail_count"], "opens": opens_by_hour(conn, share_id)})
    if is_paid(conn, share_id):
        out["paid"] = paid_summary(conn, share_id, detail=True)
    return json_response(200, {"share": out, "item": item_json(item, conn)})


def paid_summary(conn, share_id: str, detail: bool = False) -> dict:
    """What the owner sees of a paid link (16-drive-architecture §1.5, §3): the price, whether it sells,
    claim counts and earnings; with `detail`, the last 50 claims by a 4-character reference and the hour
    they were paid and released. Never who paid: we don't know."""
    p = conn.execute("SELECT p.price_ut, p.paused, se.state AS seller_state FROM paid_shares p "
                     "JOIN shares s ON s.id = p.share_id JOIN items i ON i.id = s.item_id "
                     "LEFT JOIN sellers se ON se.identity_id = i.owner_id WHERE p.share_id = ?", (share_id,)).fetchone()
    counts = {k: 0 for k in ("pending", "seen", "underpaid", "paid", "released", "expired", "void")}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM claims WHERE share_id = ? GROUP BY status", (share_id,)):
        counts[row["status"]] = row["n"]
    earned = conn.execute("SELECT COALESCE(SUM(sp.value_ut), 0) FROM sale_payments sp JOIN claims c "
                          "ON c.id = sp.claim_id WHERE c.share_id = ? AND sp.status IN ('counted','extra')",
                          (share_id,)).fetchone()[0]
    out = {"price_ut": str(p["price_ut"]), "paused": bool(p["paused"]), "seller_state": p["seller_state"],
           "counts": counts, "earned_ut": str(earned)}
    if detail:
        hour = lambda ts: codec.floor_hour(ts) if ts else None    # noqa: E731
        out["recent"] = [{"ref4": c["id"][4:8], "status": c["status"], "received_ut": str(c["received_ut"]),
                          "paid_hour": hour(c["paid_at"]), "released_hour": hour(c["released_at"]),
                          "demo": bool(c["demo"]), "owner_check": c["owner_check"]}
                         for c in conn.execute("SELECT * FROM claims WHERE share_id = ? ORDER BY created_at DESC "
                                               "LIMIT 50", (share_id,))]
    return out


def revoke(ctx, share_id: str):
    conn = ctx.db
    share = get_share(conn, share_id)
    item = conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    require_owner(ctx, item)
    with db.tx(conn):
        items.end_share(conn, share_id, "revoked", ctx.now)
        items.doom_if_unlinked(conn, item["id"], ctx.now)
        items.unlink_if_unreferenced(conn, ctx.app.blobs, item["id"], ctx.now)
    return Response(204)


def delete_item(ctx, item_id: str):
    conn = ctx.db
    item = get_item(conn, item_id)
    require_owner(ctx, item)
    with db.tx(conn):
        get_item(conn, item_id)
        items.delete_tree(conn, ctx.app.blobs, item_id, "owner_deleted", ctx.now)   # a folder: its subtree too
    return Response(204)


def adopt(ctx, item_id: str):
    """An anonymous item becomes the locker's (spec §6.3): it moves to the locker lane and quota."""
    body = ctx.req.json()
    identity = ctx.session()
    conn = ctx.db
    item = get_item(conn, item_id)
    token = ctx.manage_token()
    if item["owner_id"] is not None or item["canary"] or item["lane"] == "drop" or token is None \
            or not codec.equal(codec.sha256(token), item["manage_hash"]):
        raise ApiError(403, "forbidden", "Only the uploader can move this file into a locker.")
    cls = quota.class_of(identity, ctx.now)
    expires_at = get_int(body, "expires_at", ctx.now + 1, ctx.now + quota.CLASSES[cls]["max_expiry_s"] + 60)
    lanes.check_file_size(cls, item["size_stored"])
    pool = quota.measure(conn, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], ctx.now)
    with db.tx(conn):
        item = get_item(conn, item_id)
        if item["state"] != "ready":
            raise ApiError(409, "item_not_ready", "Finish the upload first.")
        identity = conn.execute("SELECT * FROM identities WHERE id = ?", (identity["id"],)).fetchone()
        lanes.admit_locker(conn, pool, identity, item["size_stored"], "none", ctx.now)
        conn.execute("UPDATE items SET owner_id = ?, lane = 'locker', expires_at = ? WHERE id = ?",
                     (identity["id"], expires_at, item_id))
        conn.execute("UPDATE identities SET used_bytes = used_bytes + ? WHERE id = ?",
                     (item["size_stored"], identity["id"]))
    return json_response(200, {"item_id": item_id, "lane": "locker", "expires_at": expires_at})
