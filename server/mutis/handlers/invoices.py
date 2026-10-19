# SPDX-License-Identifier: MIT
"""Packs paid in tTARI: invoices, the demo payment and the sponsor grant (spec §6.3 Payments, §9.6, §9.7)."""
import time

from .. import auth, codec, db, jobs, ootle_addr, packs, payments, quota
from ..http_util import ApiError, json_response
from .courier import budget_check, require_chain, slice_for
from .drops import require_testnet_address

DEMO_PAY_PER_DAY = 2


def _unless_judge(ctx, network_rules: tuple) -> tuple:
    """A valid judge pass lifts the per-network limits, so two judges on one network both get through;
    the per-locker limit and the pass's own uses still apply. An invalid pass is refused here (403)."""
    return () if ctx.judge() is not None else network_rules


def _invoice(ctx, invoice_id: str, identity):
    row = ctx.db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None or row["identity_id"] != identity["id"]:
        raise ApiError(404, "not_found", "No such invoice.")
    return row


PACKS_LIMITED = "Packs are limited to a few a day while we're small. Try tomorrow."


def _invoice_json(row) -> dict:
    return {"invoice_id": row["id"], "address": row["address"], "amount_ut": str(row["price_ut"]),
            "expires_at": row["expires_at"], "status": row["status"]}


def create(ctx):
    """A pack invoice (packs.py). One pack per drive at a time, renewable with the same pack in
    its last `renew_days` days; an open invoice for the same pack is handed back rather than made again.
    Then the brakes: per network a UTC day (in memory), the deployment's daily ceiling (from the invoices),
    and the slice of the paid cap the purchase draws from (judges' or public)."""
    ctx.require_feature("packs")
    identity = ctx.session()
    body = ctx.req.json()
    ctx.limit(("inv_locker", identity["id"], 10, 3600, 1))
    pack_id = body.get("pack")
    if pack_id not in quota.PACKS:
        raise ApiError(422, "unknown_pack", "No such pack.", details={"field": "pack"})
    pack, cfg, now = quota.PACKS[pack_id], ctx.cfg["packs"], ctx.now
    replaced = []                            # the drive changed its mind about an unpaid invoice
    for row in ctx.db.execute("SELECT * FROM invoices WHERE identity_id = ? AND status IN ('pending','seen') "
                              "AND expires_at > ? ORDER BY created_at DESC", (identity["id"], now)).fetchall():
        if row["pack"] == pack_id:
            return json_response(200, _invoice_json(row))
        if row["status"] == "seen" or row["received_ut"]:
            raise ApiError(409, "conflict", "A payment for your other invoice is on its way.")
        replaced.append(row["id"])
    swapped = bool(replaced)
    holding = packs.held(identity, now, cfg["renew_days"])
    if holding and (now < holding["renew_from"] or holding["id"] not in (None, pack_id)):
        size = f"{holding['bytes'] / quota.GiB:g} GiB"
        until = time.strftime("%b %d", time.gmtime(holding["until"]))
        raise ApiError(409, "pack_active", f"You already have {size} until {until}.",
                       details={"pack": holding["id"], "bytes": holding["bytes"], "until": holding["until"],
                                "renew_from": holding["renew_from"]})
    require_chain(ctx)
    base = db.get_meta(ctx.db, "receiver_address")
    if not base:
        raise ApiError(503, "chain_unavailable", "Payments aren't ready yet. Try again in a minute.")
    code = ctx.judge_soft()
    judge, exempt = code is not None, ctx.exempt()
    if exempt or swapped:                    # a swap was charged with the invoice it replaces
        network = ()
    elif judge:
        # Per network, and per pass too: the devil's run found one pass, spread over networks, could take the
        # judges' slice and spill into the public one in minutes (docs/evidence/2026-10-14/anti-grief/).
        network = (("packs64j", ctx.ip64, cfg["judge_per_network_day"], 1),
                   ("packspass", auth.judge_hash(code), cfg["judge_per_network_day"], 1))
    else:
        network = (("packs64", ctx.ip64, cfg["per_network_day"], 1),)
    pool = quota.measure(ctx.db, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], now)
    invoice_id = codec.invoice_id()
    address = ootle_addr.with_pay_ref(base, invoice_id.encode())
    expires = now + payments.INVOICE_TTL_S
    with ctx.daily(*network, code="packs_limited", message=PACKS_LIMITED), db.tx(ctx.db):
        for old_id in replaced:              # closed with the new one (a refusal keeps it); a late payment still credits
            ctx.db.execute("UPDATE invoices SET status = 'expired', expires_at = ? WHERE id = ? AND status = 'pending' "
                           "AND received_ut = 0", (now, old_id))
        # The server's own address (its tests) isn't held to the ceiling, but what it buys counts toward it.
        if not exempt and packs.sold_today(ctx.db, now, judge) >= cfg["judge_per_day" if judge else "public_per_day"]:
            raise ApiError(429, "packs_limited", PACKS_LIMITED,
                           retry_after=max(1, codec.next_utc_midnight(now) - now))
        if not holding and not packs.slices(ctx.db, pool, cfg, now).room(pack["bytes"], judge):
            raise ApiError(409, "sold_out", "The disk is finite. We'd rather say no than overbook.")
        ctx.db.execute("INSERT INTO invoices(id, identity_id, pack, price_ut, address, status, created_at, expires_at, "
                       "judge) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                       (invoice_id, identity["id"], pack_id, pack["price_ut"], address, now, expires, int(judge)))
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
    ctx.require_feature("packs")
    identity = ctx.session()
    body = ctx.req.json(required=False)
    inv = _invoice(ctx, invoice_id, identity)
    if inv["status"] not in ("pending", "seen", "underpaid") \
            or ctx.now > inv["expires_at"] + payments.UNDERPAID_GRACE_DAYS * 86400:
        raise ApiError(409, "conflict", "This invoice is paid or closed.")
    network = (("demo64", ctx.ip64, DEMO_PAY_PER_DAY, 86400, 1), ("demo48", ctx.ip48, 4, 86400, 1))
    with ctx.charged(*_unless_judge(ctx, network), ("demo_locker", identity["id"], DEMO_PAY_PER_DAY, 86400, 1)):
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
    """G1 only: one grant a day to this locker's browser wallet (its address is then known to us);
    two a day per /64, so a phone and a computer on one network both get theirs."""
    ctx.require_feature("sponsor")
    identity = ctx.session()
    body = ctx.req.json()
    address = require_testnet_address(body.get("wallet_address"), "wallet_address")
    network = (("sponsor64", ctx.ip64, 2, 86400, 1), ("sponsor48", ctx.ip48, 3, 86400, 1))
    with ctx.charged(*_unless_judge(ctx, network), ("sponsor_locker", identity["id"], 1, 86400, 1)):
        require_chain(ctx)
        judge = ctx.proof_of_work("sponsor", body, budgeted=True)
        slice_ = slice_for(identity, ctx.now, judge)
        budget_check(ctx, "sponsor", slice_, ctx.cfg["ootle"]["sponsor_grant_ut"])
        with db.tx(ctx.db):
            if judge is not None:
                ctx.spend_judge(judge)
            job_id = jobs.enqueue(ctx.db, "sponsor", slice_, {"address": address}, ctx.now, ctx.now)
    return json_response(202, {"job_id": job_id})

