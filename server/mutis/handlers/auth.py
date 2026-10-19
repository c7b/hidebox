# SPDX-License-Identifier: MIT
"""Locker registration and sign-in without signatures (spec §4.8.4, §6.3 Lockers and sessions)."""
import sqlite3

from .. import auth, codec, db
from ..http_util import ApiError, PARAM_RE, Response, get_b64, invalid, json_response

REGISTRATIONS_PER_DAY = 2000


def _identity_id(body: dict) -> str:
    value = body.get("identity_id")
    if not isinstance(value, str) or not PARAM_RE["id"].match(value):
        raise invalid("identity_id")
    return value


def register(ctx):
    body = ctx.req.json()
    # A judge pass lifts the per-network limits (judges sharing an office network), as it does
    # for sends and test money; the deployment-wide daily cap still applies.
    judge = ctx.judge() is not None
    network = () if judge else (("reg64", ctx.ip64, 5, 3600, 1), ("reg48", ctx.ip48, 20, 3600, 1))
    ctx.limit(*network, ("reg_all", "all", REGISTRATIONS_PER_DAY, 86400, 1))
    identity_id = _identity_id(body)
    verifier = get_b64(body, "auth_verifier", 32)
    # New drives a UTC day per network (in memory), so a patient griefer can't make the
    # dozens of drives it takes to hold the free space; a judge pass and the server's own address skip it.
    brakes = ctx.cfg["brakes"]
    daily = () if judge or ctx.exempt() else (("drives64", ctx.ip64, brakes["drives_per_network_day"], 1),
                                              ("drives48", ctx.ip48, brakes["drives_per_wide_network_day"], 1))
    with ctx.daily(*daily, code="drives_limited",
                   message="Your network has made all the new drives it can today. Try again tomorrow."):
        ctx.proof_of_work("register", body)
        today = codec.day(ctx.now)
        try:
            with db.tx(ctx.db):
                ctx.db.execute("INSERT INTO identities(id, auth_verifier, created_day, last_seen_day) "
                               "VALUES (?, ?, ?, ?)", (identity_id, verifier, today, today))
                token, expires = auth.create_session(ctx.db, identity_id, ctx.now)
        except sqlite3.IntegrityError:
            raise ApiError(409, "identity_exists", "This locker already exists. Sign in instead.") from None
    return json_response(201, {"token": codec.b64u(token), "expires_at": expires, "identity_id": identity_id,
                               "probation": True})


def sign_in(ctx):
    body = ctx.req.json()
    ctx.limit(("signin64", ctx.ip64, 30, 60, 1))
    identity_id = _identity_id(body)
    auth_key = get_b64(body, "auth_key", 32)
    row = ctx.db.execute("SELECT * FROM identities WHERE id = ?", (identity_id,)).fetchone()
    if row is None:
        raise ApiError(404, "unknown_identity", "No locker with this key exists here.")
    if not codec.equal(codec.sha256(auth_key), row["auth_verifier"]):
        raise ApiError(401, "bad_auth", "This key doesn't open that locker.")
    if row["state"] != "active":
        raise ApiError(403, "forbidden", "This locker is suspended.")
    with db.tx(ctx.db):
        auth.touch_identity(ctx.db, identity_id, ctx.now)
        token, expires = auth.create_session(ctx.db, identity_id, ctx.now)
    row = ctx.db.execute("SELECT distinct_days FROM identities WHERE id = ?", (identity_id,)).fetchone()
    return json_response(201, {"token": codec.b64u(token), "expires_at": expires, "identity_id": identity_id,
                               "probation": row["distinct_days"] < 2})


def sign_out(ctx):
    token = auth.bearer(ctx.req.header("Authorization"))
    if token is None:
        raise ApiError(401, "auth_required", "This needs a locker session.")
    auth.end_session(ctx.db, token)
    return Response(204)
