# SPDX-License-Identifier: MIT
"""SealLog receipts (spec §6.3 P1, §11; brand patch P-8): inclusion proofs for stored and exit leaves.

A proof is checked in the browser against the root the SealLog component holds on the Ootle.
It shows we committed to a hash at a checkpoint; it can't show we kept no copy. A leaf's index is
returned only with a proof against a committed checkpoint. While SealLog is off, these endpoints
answer 503 `feature_disabled`, so no page can promise a checkpoint that will never come.
"""
from .. import items, seallog
from ..http_util import ApiError, json_response

PAGE_MAX = 200


def _require_seallog(ctx) -> None:
    if not (ctx.features()["seallog"] and ctx.cfg["ootle"]["seallog_component"]):
        raise ApiError(503, "feature_disabled", "SealLog receipts are off on this deployment.",
                       details={"feature": "seallog"})


def _proof(ctx, leaf: bytes) -> dict:
    """{"leaf_index", "proof", "checkpoint"} against the newest committed root, or a pending marker."""
    conn = ctx.db
    index = seallog.leaf_index(conn, leaf)
    checkpoint = seallog.latest_committed(conn)
    if index is None or checkpoint is None or checkpoint["tree_size"] <= index:
        eta = seallog.next_checkpoint_eta(conn, ctx.now)
        return {"leaf_index": None, "proof": {"pending": True, "next_checkpoint_eta": eta}, "checkpoint": None}
    size = checkpoint["tree_size"]
    tree = ctx.app.cached(f"seal:{size}", 3600, lambda: seallog.levels(seallog.leaf_hashes(conn, size)))
    return {"leaf_index": index, "proof": [h.hex() for h in seallog.inclusion_proof(tree, index)],
            "checkpoint": seallog.checkpoint_json(checkpoint)}


def checkpoints(ctx):
    _require_seallog(ctx)
    ctx.limit(("seal64", ctx.ip64, 60, 60, 1))
    after = ctx.req.query.get("after", "")
    limit = ctx.req.query.get("limit", "")
    if (after and not after.isdigit()) or (limit and not limit.isdigit()):
        raise ApiError(400, "bad_request", "Bad after or limit.")
    count = min(int(limit or PAGE_MAX), PAGE_MAX) or PAGE_MAX
    rows = ctx.db.execute("SELECT * FROM seal_checkpoints WHERE state = 'committed' AND idx > ? ORDER BY idx LIMIT ?",
                          (int(after) if after else -1, count)).fetchall()
    return json_response(200, {"checkpoints": [seallog.checkpoint_json(r) for r in rows],
                               "next": rows[-1]["idx"] if len(rows) == count else None}, "public, max-age=60")


def proof(ctx, item_id: str):
    _require_seallog(ctx)
    ctx.limit(("seal64", ctx.ip64, 60, 60, 1))
    item = ctx.db.execute("SELECT ct_hash FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None or item["ct_hash"] is None:
        raise ApiError(404, "not_found", "No stored file with this id.")
    leaf = seallog.stored_leaf(item_id, item["ct_hash"])
    return json_response(200, {"item_id": item_id, "kind": "stored", "leaf_hash": leaf.hex(), **_proof(ctx, leaf)})


def exit_receipt(ctx, share_id: str):
    """P-8: why a link ended and the exit leaf of its file, while the link's tombstone exists.

    `item_id` lets the browser recompute the leaf itself, so the receipt is about this file and no
    other. The id opens nothing: every endpoint that acts on an item also wants its owner's secret.
    """
    _require_seallog(ctx)
    ctx.limit(("seal64", ctx.ip64, 60, 60, 1))
    share = ctx.db.execute("SELECT state, item_id FROM shares WHERE id = ?", (share_id,)).fetchone()
    if share is None:
        raise ApiError(404, "not_found", "No link with this id.")
    if share["state"] == "active":
        raise ApiError(409, "conflict", "This link hasn't ended.")
    item = ctx.db.execute("SELECT exit_hour, ct_hash FROM items WHERE id = ?", (share["item_id"],)).fetchone()
    out = {"reason": items.ENDED_REASON[share["state"]], "item_id": share["item_id"], "exit_hour": None,
           "leaf_hash": None}
    if item is None or item["exit_hour"] is None or item["ct_hash"] is None:
        out.update({"leaf_index": None, "checkpoint": None,
                    "proof": {"pending": True, "next_checkpoint_eta": seallog.next_checkpoint_eta(ctx.db, ctx.now)}})
        return json_response(200, out)
    leaf = seallog.exit_leaf(share["item_id"], item["exit_hour"])
    out.update({"exit_hour": item["exit_hour"], "leaf_hash": leaf.hex(), **_proof(ctx, leaf)})
    return json_response(200, out)
