# SPDX-License-Identifier: MIT
"""Packs paid in tTARI: invoices, the demo payment and the sponsor grant (spec §6.3 Payments, §9.6, §9.7)."""
from .. import codec, db, jobs, ootle_addr, payments, quota
from ..http_util import ApiError, json_response
from .courier import budget_check, require_chain, slice_for
from .drops import require_testnet_address

DEMO_PAY_PER_DAY = 2


def _invoice(ctx, invoice_id: str, identity):
    row = ctx.db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None or row["identity_id"] != identity["id"]:
        raise ApiError(404, "not_found", "No such invoice.")
    return row


def create(ctx):
    identity = ctx.session()
    body = ctx.req.json()
    ctx.limit(("inv_locker", identity["id"], 10, 3600, 1))
    pack_id = body.get("pack")
    if pack_id not in quota.PACKS:
        raise ApiError(422, "unknown_pack", "No such pack.", details={"field": "pack"})
    pack = quota.PACKS[pack_id]
    require_chain(ctx)
    base = db.get_meta(ctx.db, "receiver_address")
    if not base:
        raise ApiError(503, "chain_unavailable", "Payments aren't ready yet. Try again in a minute.")
    pool = quota.measure(ctx.db, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], ctx.now)
    if pool.paid + pack["bytes"] > quota.PAID_CAP_FRACTION * pool.pool:
        raise ApiError(409, "sold_out", "The disk is finite. We'd rather say no than overbook.")
    invoice_id = codec.invoice_id()
    address = ootle_addr.with_pay_ref(base, invoice_id.encode())
    expires = ctx.now + payments.INVOICE_TTL_S
    with db.tx(ctx.db):
        ctx.db.execute("INSERT INTO invoices(id, identity_id, pack, price_ut, address, status, created_at, expires_at) "
                       "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                       (invoice_id, identity["id"], pack_id, pack["price_ut"], address, ctx.now, expires))
    return json_response(201, {"invoice_id": invoice_id, "address": address, "amount_ut": str(pack["price_ut"]),
                               "expires_at": expires, "status": "pending"})


def get_invoice(ctx, invoice_id: str):
    identity = ctx.session()
    inv = _invoice(ctx, invoice_id, identity)
    rows = ctx.db.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY seen_at", (invoice_id,)).fetchall()
    pack = quota.PACKS[inv["pack"]]
    credited = None
    if inv["status"] == "credited":
        credited = {"bytes": pack["bytes"], "until": inv["credited_at"] + pack["days"] * 86400}
    return json_response(200, {
        "invoice_id": inv["id"], "status": inv["status"],
        "pack": inv["pack"], "address": inv["address"], "expires_at": inv["expires_at"],
        "amount_ut": str(inv["price_ut"]), "received_ut": str(inv["received_ut"]),
        "payments": [{"utxo_id": p["utxo_id"], "value_ut": str(p["value_ut"]), "seen_at": p["seen_at"],
                      "checks": {"amount_proven": bool(p["proven"]), "committed_on_chain": bool(p["committed"])},
                      "epoch": p["epoch"], "tx_id": None} for p in rows],
        "credited": credited,
    })


def demo_pay(ctx, invoice_id: str):
    """The sponsor wallet pays this invoice; the normal verification loop credits it (spec §6.3)."""
    ctx.require_feature("demo_pay")
    identity = ctx.session()
    body = ctx.req.json(required=False)
    inv = _invoice(ctx, invoice_id, identity)
    if inv["status"] not in ("pending", "seen", "underpaid") \
            or ctx.now > inv["expires_at"] + payments.UNDERPAID_GRACE_DAYS * 86400:
        raise ApiError(409, "conflict", "This invoice is paid or closed.")
    with ctx.charged(("demo64", ctx.ip64, DEMO_PAY_PER_DAY, 86400, 1), ("demo48", ctx.ip48, 4, 86400, 1),
                     ("demo_locker", identity["id"], DEMO_PAY_PER_DAY, 86400, 1)):
        require_chain(ctx)
        judge = ctx.proof_of_work("demo_pay", body, budgeted=True)
        slice_ = slice_for(identity, ctx.now, judge)
        amount = inv["price_ut"] - inv["received_ut"]
        budget_check(ctx, "demo_pay", slice_, amount)
        with db.tx(ctx.db):
            if judge is not None:
                ctx.spend_judge(judge)
            job_id = jobs.enqueue(ctx.db, "demo_pay", slice_, {"address": inv["address"], "amount_ut": str(amount),
                                                               "ref": inv["id"]}, ctx.now, ctx.now)
    return json_response(202, {"job_id": job_id})


def sponsor(ctx):
    """G1 only: one grant a day to this locker's browser wallet (its address is then known to us)."""
    ctx.require_feature("sponsor")
    identity = ctx.session()
    body = ctx.req.json()
    address = require_testnet_address(body.get("wallet_address"), "wallet_address")
    with ctx.charged(("sponsor64", ctx.ip64, 1, 86400, 1), ("sponsor48", ctx.ip48, 3, 86400, 1),
                     ("sponsor_locker", identity["id"], 1, 86400, 1)):
        require_chain(ctx)
        judge = ctx.proof_of_work("sponsor", body, budgeted=True)
        slice_ = slice_for(identity, ctx.now, judge)
        budget_check(ctx, "sponsor", slice_, ctx.cfg["ootle"]["sponsor_grant_ut"])
        with db.tx(ctx.db):
            if judge is not None:
                ctx.spend_judge(judge)
            job_id = jobs.enqueue(ctx.db, "sponsor", slice_, {"address": address}, ctx.now, ctx.now)
    return json_response(202, {"job_id": job_id})

