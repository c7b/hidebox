# SPDX-License-Identifier: MIT
"""Links (shares): create, status, peek, the atomic open, edits, revocation and adoption.

Spec §4.6–§4.7 (access tokens, link proofs, the online-guessing policy), §5.2–§5.4, §6.3 Links,
brand patches P-25 (first_opened_min) and the P1 "Download the stored bytes" endpoint.

There is no server-side "Keep" for a received file: a recipient keeps one by opening it normally
and sealing the plaintext again as their own kept file. The sender's link then still ends on its
rule, and the sender's ciphertext still leaves.
"""
import json
import secrets

from .. import codec, db, items, lanes, quota
from ..http_util import ApiError, Response, get_b64, get_bool, get_enum, get_int, invalid, json_response
from .blobs import ranged

PW_LOCK_AFTER = 5            # link + password: wrong tries (with a valid link proof) before the first pause
PW_DELAY_START_S = 60
PW_DELAY_MAX_S = 3600
PW_PERMANENT_AFTER = 50
PWONLY_POW_AFTER = 3          # password only: per (link, IP key) failures before PoW and waiting start
PWONLY_GLOBAL_HARD = 100      # password only: daily failures across everyone before every try needs 20 bits
PWONLY_HARD_BITS = 20
EGRESS_PER_ITEM_DAY = 10 * quota.GiB
UNLIMITED_OPENS_PER_HOUR = 60
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
            error = check_secrets(ctx, conn, share)
    if error:
        raise error
    return share, conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()


# --- JSON shapes ---------------------------------------------------------------------------------

def share_json(share, now: int) -> dict:
    state = effective_state(share, now)
    left = None if share["max_views"] is None else max(0, share["max_views"] - share["views_used"])
    return {"id": share["id"], "mode": share["mode"], "state": state, "created_hour": share["created_hour"],
            "expires_at": share["expires_at"], "max_views": share["max_views"], "views_used": share["views_used"],
            "views_left": left}


def item_json(item) -> dict:
    return {"size_stored": item["size_stored"], "chunk_count": item["chunk_count"], "retention": item["retention"],
            "created_hour": item["created_hour"], "lane": item["lane"],
            "owner": "a locker" if item["owner_id"] else "nobody",
            "ct_hash": codec.b64u(item["ct_hash"]) if item["ct_hash"] else None}


def created_json(share) -> dict:
    return {"share_id": share["id"], "path": f"/s/{share['id']}", "state": share["state"],
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
    mode = get_enum(body, "mode", ("link", "link_password", "password"))
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
    cls = class_of_item(conn, item, ctx.now)
    if cls == "drop" and mode != "link":
        raise invalid("mode", "Drop deliveries use a plain link.")
    max_views, expires_at = link_rules(cls, max_views, expires_at, item, ctx.now)
    per_item = 1 if cls in ("drop", "canary") else quota.CLASSES[cls]["links_per_item"]
    share_id = codec.new_id()
    with db.tx(conn):
        item = get_item(conn, item_id)
        if item["state"] != "ready":
            raise ApiError(409, "item_not_ready", "Finish the upload first.")
        if conn.execute("SELECT COUNT(*) FROM shares WHERE item_id = ?", (item_id,)).fetchone()[0] >= per_item:
            raise ApiError(409, "conflict", "This file has as many links as it can have.",
                           details={"max_links": per_item})
        conn.execute("INSERT INTO shares(id, item_id, mode, wrapped_key, access_hash, link_hash, kdf, max_views, "
                     "expires_at, created_hour) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (share_id, item_id, mode, wrapped, access_verifier, link_verifier, kdf, max_views, expires_at,
                      codec.floor_hour(ctx.now)))
    return json_response(201, created_json(get_share(conn, share_id)))


# --- public status, peek, open -----------------------------------------------------------------------

def status(ctx, share_id: str):
    ctx.limit(("status64", ctx.ip64, 120, 60, 1))
    share = get_share(ctx.db, share_id)
    state = effective_state(share, ctx.now)
    if state != "active":
        raise gone(share, state, ctx.now)
    return json_response(200, {"state": "active", "mode": share["mode"], "needs_password": share["mode"] != "link",
                               "kdf": json.loads(share["kdf"]) if share["kdf"] else None})


def peek(ctx, share_id: str):
    ctx.limit(("status64", ctx.ip64, 120, 60, 1))
    body = ctx.req.json(required=False)
    share, item = authorized_share(ctx, share_id, body)
    return json_response(200, {"share": share_json(share, ctx.now), "item": item_json(item),
                               "not_known": NOT_KNOWN})


def _egress_ok(conn, item, now: int, size: int) -> bool:
    today = codec.day(now)
    used = item["egress_bytes"] if item["egress_day"] == today else 0
    if used + size > EGRESS_PER_ITEM_DAY:
        return False
    conn.execute("UPDATE items SET egress_day = ?, egress_bytes = ? WHERE id = ?", (today, used + size, item["id"]))
    return True


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
    error = check_secrets(ctx, conn, share)
    if error:
        return error
    item = conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    if item["state"] != "ready":
        return ApiError(410, "gone", "This link has ended.", details={"reason": "removed", "ended_day": codec.day(now)})
    if share["max_views"] is None:
        hour = codec.floor_hour(now)
        opens = share["opens_in_hour"] if share["opens_hour"] == hour else 0
        if opens >= UNLIMITED_OPENS_PER_HOUR:
            return ApiError(429, "rate_limited", "This link was opened many times this hour.",
                            retry_after=hour + 3600 - now)
        conn.execute("UPDATE shares SET opens_hour = ?, opens_in_hour = ? WHERE id = ?", (hour, opens + 1, share_id))
    if not _egress_ok(conn, item, now, item["size_stored"]):
        return ApiError(429, "rate_limited", "This file was downloaded a lot today.",
                        retry_after=codec.next_utc_midnight(now) - now)
    conn.execute("UPDATE shares SET views_used = views_used + 1, first_opened_min = COALESCE(first_opened_min, ?) "
                 "WHERE id = ? AND state = 'active'", (codec.floor_minute(now), share_id))
    views_used = share["views_used"] + 1
    burned = share["max_views"] is not None and views_used >= share["max_views"]
    if burned:
        items.end_share(conn, share_id, "exhausted", now)
    inline = item["size_stored"] <= quota.INLINE_MAX_STORED
    ticket = None
    if not inline:
        ticket = secrets.token_bytes(32)
        conn.execute("INSERT INTO tickets(token_hash, share_id, item_id, expires_at, max_bytes) VALUES (?, ?, ?, ?, ?)",
                     (codec.sha256(ticket), share_id, item["id"], now + items.TICKET_S, 3 * item["size_stored"]))
    doomed = burned and items.doom_if_unlinked(conn, item["id"], now)
    return {
        "response": {
            "wrapped_key": codec.b64u(share["wrapped_key"]), "header": codec.b64u(item["header"]),
            "meta_ct": codec.b64u(item["meta_ct"]), "chunk_size": quota.CHUNK, "chunk_count": item["chunk_count"],
            "size_stored": item["size_stored"],
            "views_left": None if share["max_views"] is None else share["max_views"] - views_used,
            "burned": burned, "ticket": codec.b64u(ticket) if ticket else None,
            "ticket_expires_at": now + items.TICKET_S if ticket else None,
            "inline_ct": codec.b64u(ctx.app.blobs.read_all(item["id"])) if inline else None},
        "unlink": item["id"] if inline and doomed else None,
    }


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
    cls = class_of_item(conn, item, ctx.now)
    with db.tx(conn):
        share = get_share(conn, share_id)
        state = effective_state(share, ctx.now)
        if state != "active":
            error = gone(share, state, ctx.now)
        else:
            error = _apply_patch(conn, share, item, cls, max_views_given, new_views, new_expiry, unlock, ctx.now)
    if error:
        raise error
    return json_response(200, created_json(get_share(conn, share_id)))


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
                "pw_fail_count": share["pw_fail_count"]})
    return json_response(200, {"share": out, "item": item_json(item)})


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
        item = get_item(conn, item_id)
        if item["state"] == "uploading":
            items.unlink(conn, ctx.app.blobs, item_id, "deleted", ctx.now)
        else:
            items.doom_item(conn, item_id, "owner_deleted", ctx.now)
            items.unlink_if_unreferenced(conn, ctx.app.blobs, item_id, ctx.now)
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
