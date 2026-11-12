# SPDX-License-Identifier: MIT
"""Withdrawing earnings (docs/withdraw.md; the rules are in withdraw.py), behind features.withdraw and pay_to_open.

Every route takes the drive's session. The transaction arrives signed: our server never holds a key that could
spend the money, never learns where it goes, and relays only a withdrawal that spends this drive's settled outputs.
"""
import base64
import binascii
import json
import re

from .. import codec, db, payments, withdraw
from ..http_util import ApiError, get_enum, invalid, json_response
from ..indexer import IndexerError

TX_ID = re.compile(r"^[0-9a-f]{64}\Z")


def _on(ctx) -> None:
    ctx.require_feature("withdraw")
    ctx.require_feature("pay_to_open")


def outputs(ctx):
    """What this drive can withdraw: its settled outputs (each with any withdrawal pending on it), what is still being
    settled, and the rules the browser plans with."""
    _on(ctx)
    identity = ctx.session()
    return json_response(200, {"outputs": withdraw.spendable(ctx.db, identity["id"], ctx.now),
                               "waiting": withdraw.waiting(ctx.db, identity["id"]), **withdraw.config_block()})


def submit(ctx):
    """`{transaction, change?: {utxo_id, value_ut}}`: a withdrawal signed in the browser. Checked (shape, settled
    inputs of this drive, none already on its way), marked, relayed to the network; → 201 {tx_id, inputs}. `change`
    names the output that goes back to the sales address (one of this transaction's) and its value, so the drive can
    withdraw it later from any device."""
    _on(ctx)
    identity = ctx.session()
    # Counted before the envelope is read, whatever comes of it; SUBMITS_PER_HOUR below counts withdrawals.
    ctx.limit(("withdraw_try", identity["id"], withdraw.TRIES_PER_HOUR, 3600, 1),
              ("withdraw_try64", ctx.ip64, 2 * withdraw.TRIES_PER_HOUR, 3600, 1))
    ctx.req.check_length(withdraw.BODY_MAX)
    body = ctx.req.json()
    text = body.get("transaction")
    if set(body) - {"transaction", "change"} or not isinstance(text, str) or len(text) > withdraw.ENVELOPE_MAX * 4 // 3 + 4:
        raise withdraw.invalid_tx()
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise withdraw.invalid_tx() from None
    spent, made, _fee = withdraw.parse_envelope(raw, ctx.cfg["ootle"]["max_fee_transfer_ut"])
    change = body.get("change")
    if change is not None:
        value = change.get("value_ut") if isinstance(change, dict) else None
        if not isinstance(change, dict) or set(change) != {"utxo_id", "value_ut"} or change["utxo_id"] not in made \
                or not isinstance(value, str) or not value.isdigit() or len(value) > 19 or not 0 < int(value) < 2 ** 63:
            raise invalid("change")
    ctx.limit(("withdraw", identity["id"], withdraw.SUBMITS_PER_HOUR, 3600, 1), ("withdraw64", ctx.ip64, 30, 3600, 1))
    marker = "relaying:" + codec.new_id()
    with db.tx(ctx.db):
        total = withdraw.claim_inputs(ctx.db, identity["id"], spent, marker, ctx.now)
        if change is not None and int(change["value_ut"]) >= total:
            raise invalid("change")
    try:
        status, data, _source = ctx.app.indexers.call("POST", "/transactions", json.dumps({"transaction": text}).encode(),
                                                      lane="send")
        tx_id = json.loads(data).get("transaction_id") if status == 200 else None
    except (IndexerError, ValueError, AttributeError):
        status, tx_id = 503, None
    if not isinstance(tx_id, str) or not TX_ID.match(tx_id):
        with db.tx(ctx.db):
            withdraw.retag(ctx.db, marker, None)
        if status >= 500:
            raise ApiError(503, "chain_unavailable", "The Tari indexers aren't answering. Nothing was spent.")
        raise ApiError(422, "rejected", "The network refused this withdrawal. Nothing was spent.")
    with db.tx(ctx.db):
        withdraw.retag(ctx.db, marker, tx_id)
        if change is not None:
            ctx.db.execute("INSERT OR IGNORE INTO sales_change(utxo_id, identity_id, value_ut, from_tx, created_at) "
                           "VALUES (?, ?, ?, ?, ?)", (change["utxo_id"], identity["id"], int(change["value_ut"]), tx_id,
                                                      ctx.now))
    return json_response(201, {"tx_id": tx_id, "inputs": spent})


def report(ctx, tx_id: str):
    """`{outcome: "commit" | "reject"}`: what the drive saw of its withdrawal on the chain. 404 when no output of this
    drive waits on that transaction."""
    _on(ctx)
    identity = ctx.session()
    outcome = get_enum(ctx.req.json(), "outcome", ("commit", "reject"))
    with db.tx(ctx.db):
        touched = withdraw.settle(ctx.db, identity["id"], tx_id, outcome == "commit")
    if not touched:
        raise ApiError(404, "not_found", "No withdrawal of this drive has this id.")
    return json_response(200, {"tx_id": tx_id, "outcome": outcome})


def gone(ctx, utxo_id: str):
    """The drive found one of its withdrawable outputs missing on the chain (lib/withdraw.js loadInput): spent from
    another device, or by a withdrawal whose answer was lost. Our server asks every indexer itself and takes it off
    the list only on evidence it was spent: a verified down state, and no indexer serving it live
    (payments.spent_on_indexers). A 404, even from every indexer, is no evidence: the money stays listed. The drive's
    word alone changes nothing. -> 200 {utxo_id, gone}, or 409 `still_there` without the evidence (it asks again
    later)."""
    _on(ctx)
    identity = ctx.session()
    ctx.limit(("withdraw_gone", identity["id"], withdraw.GONE_PER_HOUR, 3600, 1))
    withdraw.gone_row(ctx.db, identity["id"], utxo_id, ctx.now)
    if not payments.spent_on_indexers(ctx.app.indexers, utxo_id):
        raise ApiError(409, "still_there", "The chain doesn't show this money as spent. It stays in your earnings.",
                       details={"utxo_id": utxo_id})
    with db.tx(ctx.db):
        source, _row = withdraw.gone_row(ctx.db, identity["id"], utxo_id, ctx.now)
        withdraw.mark_gone(ctx.db, identity["id"], source, utxo_id)
    return json_response(200, {"utxo_id": utxo_id, "gone": True})

