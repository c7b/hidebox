# SPDX-License-Identifier: MIT
"""POST /courier and GET /jobs/{id} (spec §4.10, §6.3 Courier, §10.4).

The client sends only a kind and a 125-byte sealed blob. The server builds the memo from its own
PUBLIC_ORIGIN, and a drop delivery always goes to the drop's own address, so nobody can make our
wallet carry other text or reach another address through a drop.

The counters shared with strangers (per destination address, per drop) are charged only after every
check that can refuse the sender, and given back if the job still can't be queued: a refused sender
can't use up someone else's daily allowance.
"""
import secrets

from .. import budgets, codec, db, jobs, quota
from ..http_util import ApiError, get_b64, get_bool, get_enum, get_int, json_response
from .drops import COURIER_PER_DAY, active_drop, require_testnet_address

BLOB_LEN = 125
HEARTBEAT_MAX_AGE_S = 60
PER_DESTINATION_PER_DAY = 20


def require_chain(ctx) -> None:
    beat = int(db.get_meta(ctx.db, "chain_heartbeat", "0"))
    if ctx.now - beat > HEARTBEAT_MAX_AGE_S:
        raise ApiError(503, "chain_unavailable", "Our chain worker isn't answering. Try again in a minute.")


def budget_check(ctx, kind: str, slice_: str, cost: int) -> None:
    if not budgets.has_room(ctx.db, ctx.cfg["budgets"], kind, slice_, cost, ctx.now):
        resets = budgets.resets_at(ctx.now)
        raise ApiError(429, "budget_exhausted", "Today's budget for this is used up.", retry_after=resets - ctx.now,
                       details={"kind": kind, "resets_at": resets})


def slice_for(identity, now: int, judge: str | None) -> str:
    """Judge passes use the evidence slice, lockers older than today the reserved one (spec §9.5)."""
    if judge is not None:
        return "evidence"
    if identity is not None and identity["created_day"] < codec.day(now):
        return "reserved"
    return "public"


def send(ctx):
    body = ctx.req.json()
    to = get_enum(body, "to", ("drop", "address"))
    kind = get_int(body, "kind", 3, 4)
    try:
        blob = get_b64(body, "blob")
    except ApiError:
        raise ApiError(422, "bad_blob", "The sealed blob is malformed.", details={"field": "blob"}) from None
    if len(blob) != BLOB_LEN:
        raise ApiError(422, "bad_blob", "The sealed blob must be 125 bytes.", details={"field": "blob"})
    evidence = get_bool(body, "evidence")
    identity, judge, shared, full = None, None, None, ""

    if to == "drop":
        ctx.require_feature("drops")
        if kind != 3 or evidence:
            raise ApiError(422, "invalid", "Drop deliveries are sealed to owner and view keys.",
                           details={"field": "kind"})
        ctx.limit(("cour_drop64", ctx.ip64, 10, 3600, 1), ("cour_drop48", ctx.ip48, 30, 3600, 1))
        drop = active_drop(ctx.db, body.get("drop_id"))
        address = drop["address"]
        require_chain(ctx)
        judge = ctx.proof_of_work("courier", body, budgeted=True)
        slice_ = slice_for(None, ctx.now, judge)
        shared, full = ("cour_drop", drop["id"], COURIER_PER_DAY, 86400, 1), "This drop took all it can today."
    elif ctx.is_canary():
        if not evidence:
            raise ApiError(422, "invalid", "Canary deliveries are evidence.", details={"field": "evidence"})
        address = require_testnet_address(body.get("address"))
        require_chain(ctx)
        slice_ = "evidence"
    else:
        ctx.require_feature("relay_send")
        identity = ctx.session()
        if evidence:
            raise ApiError(403, "forbidden", "Only our canary makes evidence deliveries.")
        address = require_testnet_address(body.get("address"))
        require_chain(ctx)
        judge = ctx.judge()
        slice_ = slice_for(identity, ctx.now, judge)
        _count_send(ctx, identity, charge=False)
        shared = ("cour_dest", ctx.app.ipkeys.keyed(b"addr:" + address.encode(), ctx.now), PER_DESTINATION_PER_DAY,
                  86400, 1)
        full = "This address got all the deliveries it can today."

    budget_check(ctx, "courier", slice_, 1)
    low, high = ctx.cfg["ootle"]["jitter_s"]
    not_before = ctx.now + low + secrets.randbelow(high - low + 1)
    memo = jobs.courier_memo(ctx.cfg.origin, kind, blob)
    payload = {"address": address, "memo": memo}
    if to == "drop":
        payload["drop_id"] = drop["id"]       # the worker sends it only while that drop is still open
    with ctx.charged(*([shared] if shared else []), message=full):
        with db.tx(ctx.db):
            if judge is not None:
                ctx.spend_judge(judge)
            if identity is not None:
                _count_send(ctx, identity)
            job_id = jobs.enqueue(ctx.db, "courier", slice_, payload, not_before, ctx.now, evidence=evidence)
    return json_response(202, {"job_id": job_id, "not_before": not_before})


def _count_send(ctx, identity, charge: bool = True) -> None:
    """A locker's relay sends today: checked first, counted inside the transaction that queues the job."""
    today = codec.day(ctx.now)
    row = ctx.db.execute("SELECT * FROM identities WHERE id = ?", (identity["id"],)).fetchone()
    sent = row["sends_today"] if row["sends_day"] == today else 0
    allowed = quota.CLASSES[quota.class_of(row, ctx.now)]["sends_per_day"]
    if sent >= allowed:
        raise ApiError(429, "rate_limited", "This locker sent all it can today.",
                       retry_after=codec.next_utc_midnight(ctx.now) - ctx.now, details={"sends_per_day": allowed})
    if charge:
        ctx.db.execute("UPDATE identities SET sends_day = ?, sends_today = ? WHERE id = ?",
                       (today, sent + 1, identity["id"]))


def job(ctx, job_id: str):
    ctx.limit(("job64", ctx.ip64, 120, 60, 1))
    row = ctx.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No such job.")
    return json_response(200, jobs.public_view(row))
