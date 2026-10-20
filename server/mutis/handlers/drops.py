# SPDX-License-Identifier: MIT
"""Dead drops (spec §4.11, §5.5, §6.3): a public intake that delivers on chain to its locker's address.

A drop needs no session (an 18-bit PoW instead), so the server can't tie it to a locker id. It
does store the drop's Tari address, label and tag: a dead drop is public by design.
"""
from .. import codec, db, jobs, ootle_addr, quota
from ..http_util import ApiError, Response, get_b64, get_str, json_response

LABEL_MAX = 80
COURIER_PER_DAY = 50


def require_testnet_address(value, field: str = "address") -> str:
    """Spec §4.9.4 classification with its specific error codes."""
    cls = ootle_addr.classify(value) if isinstance(value, str) else "invalid"
    code = ootle_addr.ERROR_FOR_CLASS[cls]
    if code:
        messages = {"mainnet_address": "That's an Ootle address for another network. mutis runs on the testnet.",
                    "l1_address": "That's a Tari base-layer address. mutis runs on the Ootle testnet.",
                    "bad_address": "That isn't a Tari Ootle address."}
        raise ApiError(422, code, messages[code], details={"field": field, "class": cls})
    return ootle_addr.base_address(value)


def active_drop(conn, drop_id: str):
    if not isinstance(drop_id, str) or not drop_id.isascii() or len(drop_id) != 10:
        raise ApiError(404, "drop_not_found", "No drop here.")
    row = conn.execute("SELECT * FROM drops WHERE id = ?", (drop_id,)).fetchone()
    if row is None:
        raise ApiError(404, "drop_not_found", "No drop here.")
    if row["state"] != "active":
        raise ApiError(410, "drop_closed", "This drop is closed.", details={"reason": row["state"]})
    return row


def _manage(ctx, drop_id: str):
    row = ctx.db.execute("SELECT * FROM drops WHERE id = ?", (drop_id,)).fetchone()
    if row is None:
        raise ApiError(404, "drop_not_found", "No drop here.")
    token = ctx.manage_token()
    if token is None or not codec.equal(codec.sha256(token), row["manage_hash"]):
        raise ApiError(403, "forbidden", "Only the drop's owner can do that.")
    return row


def drop_json(ctx, row) -> dict:
    today = codec.day(ctx.now)
    files = row["files_today"] if row["day"] == today else 0
    limits = quota.CLASSES["drop"]
    return {"drop_id": row["id"], "state": row["state"], "address": row["address"], "tag": codec.b64u(row["tag"]),
            "label": row["label"],
            "limits": {"max_file_bytes": limits["max_file_bytes"], "expiry_s": limits["expiry_s"],
                       "views": limits["views"]},
            "today": {"left": max(0, COURIER_PER_DAY - files)}}


def _label(body: dict) -> str:
    return (get_str(body, "label", LABEL_MAX, optional=True) or "").strip()


def create(ctx):
    ctx.require_feature("drops")
    body = ctx.req.json()
    ctx.limit(("drop64", ctx.ip64, 5, 3600, 1), ("drop48", ctx.ip48, 15, 3600, 1))
    address = require_testnet_address(body.get("address"))
    tag = get_b64(body, "tag", 16)
    label = _label(body)
    manage_verifier = get_b64(body, "manage_verifier", 32)
    ctx.proof_of_work("drop_create", body)
    with db.tx(ctx.db):
        drop_id = codec.drop_id()
        while ctx.db.execute("SELECT 1 FROM drops WHERE id = ?", (drop_id,)).fetchone():
            drop_id = codec.drop_id()
        ctx.db.execute("INSERT INTO drops(id, address, tag, label, manage_hash, created_day) VALUES (?, ?, ?, ?, ?, ?)",
                       (drop_id, address, tag, label, manage_verifier, codec.day(ctx.now)))
    return json_response(201, {"drop_id": drop_id, "url": f"{ctx.cfg.origin}/d/{drop_id}"})


def get_drop(ctx, drop_id: str):
    ctx.limit(("dropget64", ctx.ip64, 60, 60, 1))
    return json_response(200, drop_json(ctx, active_drop(ctx.db, drop_id)))


def _close(ctx, drop_id: str) -> None:
    with db.tx(ctx.db):
        ctx.db.execute("UPDATE drops SET state = 'closed', ended_day = ? WHERE id = ? AND state = 'active'",
                       (codec.day(ctx.now), drop_id))
        jobs.end_drop_deliveries(ctx.db, drop_id, "drop_closed", ctx.now)


def patch(ctx, drop_id: str):
    body = ctx.req.json()
    row = _manage(ctx, drop_id)
    if row["state"] != "active":
        raise ApiError(410, "drop_closed", "This drop is closed.", details={"reason": row["state"]})
    if set(body) == {"state"} and body["state"] == "closed":
        _close(ctx, drop_id)
    elif set(body) == {"label"}:
        label = _label(body)
        with db.tx(ctx.db):
            ctx.db.execute("UPDATE drops SET label = ? WHERE id = ?", (label, drop_id))
    else:
        raise ApiError(422, "invalid", "Change either the label or the state.", details={"field": "body"})
    row = ctx.db.execute("SELECT * FROM drops WHERE id = ?", (drop_id,)).fetchone()
    return json_response(200, drop_json(ctx, row))


def close(ctx, drop_id: str):
    _manage(ctx, drop_id)
    _close(ctx, drop_id)
    return Response(204)
