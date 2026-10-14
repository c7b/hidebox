# SPDX-License-Identifier: MIT
"""Pay to open: the drive's sales address, the pay page, claims, test money for claims and the owner's
check (research 16-drive-design §4, annex 16-drive-architecture §1.5; the lifecycle is in sales.py).

The buyer's routes (`/p/*`) never read a session, so a claim is never linked to a drive; a claim is a
random id plus SHA-256 of a token only the buyer's browser holds (`X-Mutis-Claim`), never an IP.
"""
from .. import codec, db, jobs, ootle_addr, sales, tree
from ..http_util import ApiError, Response, get_b64, get_enum, invalid, json_response
from .courier import budget_check, require_chain, slice_for
from .drops import require_testnet_address
from .invoices import _unless_judge
from .shares import _header_b64, effective_state, folder_tree, gone

CLAIMS_PER_HOUR_64, CLAIMS_PER_HOUR_48 = 10, 30
DEMO_PER_DAY_64, DEMO_PER_DAY_48 = 3, 6
CHECKS_LISTED = 100


# --- the seller (a drive session) -----------------------------------------------------------------------

def put_sales(ctx):
    """The drive's sales address and its view key sealed (kind 3, flag 0x08) to our payment checker.
    The API can't open the blob; the chain worker does, and keeps the key in its memory only (C34)."""
    ctx.require_feature("pay_to_open")
    identity = ctx.session()
    body = ctx.req.json()
    address = body.get("address")
    if require_testnet_address(address) != address:
        raise invalid("address", "Use the drive's sales address itself, without a payment reference.")
    view_sealed = get_b64(body, "view_sealed", sales.VIEW_SEALED_LEN)
    ctx.limit(("sales_put", identity["id"], sales.SALES_PUT_PER_DAY, 86400, 1))
    with db.tx(ctx.db):
        ctx.db.execute("INSERT INTO sellers(identity_id, address, view_sealed, state, created_at) "
                       "VALUES (?, ?, ?, 'pending', ?) ON CONFLICT(identity_id) DO UPDATE SET "
                       "address = excluded.address, view_sealed = excluded.view_sealed, state = 'pending', "
                       "scan_seq = 0, scanned_at = NULL", (identity["id"], address, view_sealed, ctx.now))
    return Response(204)


def get_sales(ctx):
    """The drive's sales registration and the paid claims waiting for its ownership check (annex §1.9):
    for each, the outputs that paid it, so the drive can compare their one-time keys with its own."""
    identity = ctx.session()
    conn = ctx.db
    seller = conn.execute("SELECT address, state FROM sellers WHERE identity_id = ?", (identity["id"],)).fetchone()
    rows = conn.execute("SELECT c.* FROM claims c JOIN shares s ON s.id = c.share_id JOIN items i ON i.id = s.item_id "
                        "WHERE i.owner_id = ? AND c.status = 'paid' AND c.owner_check = 'pending' "
                        "ORDER BY c.paid_at LIMIT ?", (identity["id"], CHECKS_LISTED)).fetchall()
    to_check = [{"claim_id": c["id"], "share_id": c["share_id"], "paid_at": c["paid_at"],
                 "amount_ut": str(c["price_ut"]), "received_ut": str(c["received_ut"]),
                 "utxo_ids": [r[0] for r in conn.execute("SELECT utxo_id FROM sale_payments WHERE claim_id = ? "
                                                         "AND status = 'counted'", (c["id"],))]} for c in rows]
    return json_response(200, {"seller": dict(seller) if seller else None, "to_check": to_check})


def confirm_claim(ctx, claim_id: str):
    """The owner's drive checked the money that paid this claim: `ok` (its one-time keys are the drive's
    own) lets the buyer's next poll release it; `bad` (the payer kept control) voids it."""
    identity = ctx.session()
    check = get_enum(ctx.req.json(), "check", ("ok", "bad"))
    conn = ctx.db
    with db.tx(conn):
        claim = conn.execute("SELECT c.*, i.owner_id FROM claims c JOIN shares s ON s.id = c.share_id "
                             "JOIN items i ON i.id = s.item_id WHERE c.id = ?", (claim_id,)).fetchone()
        if claim is None or claim["owner_id"] != identity["id"]:
            raise ApiError(404, "not_found", "No such payment.")
        if claim["status"] != "paid" or claim["demo"] or claim["owner_check"] not in ("pending", "ok"):
            raise ApiError(409, "conflict", "This payment isn't waiting for your check.")
        if check == "ok":
            conn.execute("UPDATE claims SET owner_check = 'ok' WHERE id = ?", (claim_id,))
        else:
            conn.execute("UPDATE claims SET owner_check = 'bad', status = 'void' WHERE id = ?", (claim_id,))
    row = conn.execute("SELECT status, owner_check FROM claims WHERE id = ?", (claim_id,)).fetchone()
    return json_response(200, {"claim_id": claim_id, "status": row["status"], "owner_check": row["owner_check"]})


# --- the buyer (no session) ---------------------------------------------------------------------------

def paid_share(conn, share_id: str):
    row = conn.execute("SELECT s.*, p.price_ut, p.server_half, p.teaser_ct, p.buyer_views, p.buyer_window_s, "
                       "p.paused FROM shares s JOIN paid_shares p ON p.share_id = s.id WHERE s.id = ?",
                       (share_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No paid link has this id.")
    return row


def _live(ctx, share):
    state = effective_state(share, ctx.now)
    if state != "active":
        raise gone(share, state, ctx.now)


def claim_for(ctx, conn, share_id: str, claim_id: str):
    """The claim, when the request carries its token (`X-Mutis-Claim`); 404 unknown, 403 `bad_claim`."""
    token = _header_b64(ctx, "X-Mutis-Claim", 32)
    claim = conn.execute("SELECT * FROM claims WHERE id = ? AND share_id = ?", (claim_id, share_id)).fetchone()
    if claim is None:
        raise ApiError(404, "not_found", "No such payment.")
    if not token or not codec.equal(codec.sha256(token), claim["token_hash"]):
        raise ApiError(403, "bad_claim", "This payment belongs to another browser.")
    return claim


def page(ctx, share_id: str):
    """What the pay page shows before anyone pays: price, fee, what you get, the encrypted teaser (only
    the link holder's half of the key opens it). Never the seller's address: a claim's address carries
    that claim's reference and comes with the claim."""
    ctx.require_feature("pay_to_open")
    ctx.limit(("status64", ctx.ip64, 120, 60, 1))
    conn = ctx.db
    share = paid_share(conn, share_id)
    _live(ctx, share)
    item = conn.execute("SELECT * FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    if item["state"] != "ready":
        raise ApiError(410, "gone", "This link has ended.", details={"reason": "removed", "ended_day": codec.day(ctx.now)})
    contents = folder_tree(conn, item["id"], tree.MAX_TREE) if item["kind"] == "folder" else []
    seller = conn.execute("SELECT state FROM sellers WHERE identity_id = ?", (item["owner_id"],)).fetchone()
    return json_response(200, {
        "state": "paused" if share["paused"] else "selling", "price_ut": str(share["price_ut"]),
        "fee_ut": str(ctx.cfg["ootle"]["max_fee_transfer_ut"]), "buyer_views": share["buyer_views"],
        "buyer_window_s": share["buyer_window_s"], "kind": item["kind"],
        "size_stored": sum(r["size_stored"] for r in contents) if contents else item["size_stored"],
        "child_count": len(contents), "teaser_ct": codec.b64u(share["teaser_ct"]) if share["teaser_ct"] else None,
        "seller": {"ready": seller is not None and seller["state"] == "ok"}, "testnet": True})


def create_claim(ctx, share_id: str):
    """A buyer's attempt: a reference to pay with, the address that carries it, and the time to pay."""
    ctx.require_feature("pay_to_open")
    body = ctx.req.json()
    verifier = get_b64(body, "claim_verifier", 32)
    conn = ctx.db
    share = paid_share(conn, share_id)
    _live(ctx, share)
    if share["paused"]:
        raise ApiError(409, "not_for_sale", "The owner stopped selling this for now.")
    seller = sales.seller_of_share(conn, share_id)
    if seller is None or seller["state"] != "ok":
        raise ApiError(409, "seller_not_ready", "The owner's drive isn't ready to take payments yet. Try again soon.")
    rules = (("claim64", ctx.ip64, CLAIMS_PER_HOUR_64, 3600, 1), ("claim48", ctx.ip48, CLAIMS_PER_HOUR_48, 3600, 1))
    with ctx.charged(*rules):
        ctx.proof_of_work("claim", body)
        claim_id = codec.claim_id()
        address = ootle_addr.with_pay_ref(seller["address"], claim_id.encode())
        expires = ctx.now + sales.CLAIM_TTL_S
        open_ = sales.OPEN
        with db.tx(conn):
            here = conn.execute(f"SELECT COUNT(*) FROM claims WHERE share_id = ? AND status IN ({sales._q(open_)})",
                                (share_id, *open_)).fetchone()[0]
            if here >= sales.MAX_OPEN_CLAIMS_PER_SHARE:
                raise ApiError(409, "busy", "Many people are paying for this right now. Try again in a few minutes.")
            total = conn.execute(f"SELECT COUNT(*) FROM claims WHERE status IN ({sales._q(open_)})", open_).fetchone()[0]
            if total >= sales.MAX_OPEN_CLAIMS:
                raise ApiError(503, "busy", "Too many payments are open right now. Try again in a few minutes.",
                               retry_after=60)
            if conn.execute("SELECT 1 FROM claims WHERE token_hash = ?", (verifier,)).fetchone():
                raise invalid("claim_verifier")
            conn.execute("INSERT INTO claims(id, share_id, token_hash, address, price_ut, status, created_at, "
                         "created_seq, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                         (claim_id, share_id, verifier, address, share["price_ut"], ctx.now,
                          sales.mirror_head(conn), expires))
    return json_response(201, {"claim_id": claim_id, "address": address, "amount_ut": str(share["price_ut"]),
                               "expires_at": expires, "status": "pending"})


def get_claim(ctx, share_id: str, claim_id: str):
    """The buyer's stepper. The first poll of a claim that passes the release gate releases it; while
    it has opens left in its window, the answer carries our half of the key."""
    ctx.require_feature("pay_to_open")
    ctx.limit(("claim_get64", ctx.ip64, 60, 60, 1))
    conn = ctx.db
    with db.tx(conn):
        claim = claim_for(ctx, conn, share_id, claim_id)
        share = paid_share(conn, share_id)
        if sales.releasable(claim) and effective_state(share, ctx.now) == "active" and share["server_half"]:
            sales.release(conn, claim, share, ctx.now)
            claim = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    pays = conn.execute("SELECT * FROM sale_payments WHERE claim_id = ? ORDER BY seen_at", (claim_id,)).fetchall()
    out = {"claim_id": claim_id, "status": claim["status"], "address": claim["address"],
           "amount_ut": str(claim["price_ut"]), "received_ut": str(claim["received_ut"]),
           "expires_at": claim["expires_at"], "demo": bool(claim["demo"]), "owner_check": claim["owner_check"],
           "payments": [{"value_ut": str(p["value_ut"]), "seen_at": p["seen_at"], "counted": p["status"] == "counted",
                         "checks": {"amount_proven": True, "committed_on_chain": bool(p["committed"])}} for p in pays]}
    if claim["status"] == "released":
        out.update({"views_left": claim["views_left"], "open_until": claim["open_until"]})
        if sales.usable(claim, ctx.now) is None and share["server_half"]:
            out["server_half"] = codec.b64u(share["server_half"])
    return json_response(200, out)


def demo_pay(ctx, share_id: str, claim_id: str):
    """Test money: our demo wallet pays the owner's claim address for the buyer (the judge path). The worker
    re-checks claim, seller and address before anything is sent (sales.demo_payload_ok)."""
    ctx.require_feature("pay_to_open")
    ctx.require_feature("demo_pay")
    body = ctx.req.json(required=False)
    conn = ctx.db
    claim = claim_for(ctx, conn, share_id, claim_id)
    share = paid_share(conn, share_id)
    _live(ctx, share)
    if share["price_ut"] > sales.DEMO_MAX_UT:
        raise invalid("price_ut", "Test money pays only the lower prices.")
    busy = conn.execute("SELECT 1 FROM jobs WHERE kind = 'demo_pay' AND state IN ('queued','sending') "
                        "AND json_extract(payload, '$.ref') = ?", (claim_id,)).fetchone()
    if claim["status"] not in sales.OPEN or ctx.now > claim["expires_at"] + sales.LATE_GRACE_S or claim["demo"] or busy:
        raise ApiError(409, "conflict", "This payment is done, closed or already on its way.")
    seller = sales.seller_of_share(conn, share_id)
    if seller is None or seller["state"] != "ok":
        raise ApiError(409, "seller_not_ready", "The owner's drive isn't ready to take payments yet. Try again soon.")
    network = (("demo_clm64", ctx.ip64, DEMO_PER_DAY_64, 86400, 1), ("demo_clm48", ctx.ip48, DEMO_PER_DAY_48, 86400, 1))
    with ctx.charged(*_unless_judge(ctx, network)):
        require_chain(ctx)
        judge = ctx.proof_of_work("demo_pay", body, budgeted=True)
        slice_ = slice_for(None, ctx.now, judge)
        amount = min(claim["price_ut"] - claim["received_ut"], sales.DEMO_MAX_UT)
        budget_check(ctx, "demo_pay", slice_, amount)
        with db.tx(conn):
            if judge is not None:
                ctx.spend_judge(judge)
            job_id = jobs.enqueue(conn, "demo_pay", slice_, {"address": claim["address"], "amount_ut": str(amount),
                                                             "ref": claim_id}, ctx.now, ctx.now)
    return json_response(202, {"job_id": job_id})
