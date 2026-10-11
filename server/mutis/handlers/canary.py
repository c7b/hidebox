# SPDX-License-Identifier: MIT
"""GET /canary and /canary/raw (spec §6.3, §8.4): our own hourly sealed file, exactly as the disk holds it.

P1: a canary's file key is published once it is a day old ("Yesterday's key — now you can read it").
"""
from .. import codec, db
from ..http_util import ApiError, json_response
from .blobs import ranged


def _log(conn) -> list[dict]:
    return db.get_meta_json(conn, "canary_log", [])


def _item(conn, item_id: str):
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return row if row is not None and row["state"] in ("ready", "doomed") else None


def latest(ctx):
    conn = ctx.db
    item_id = db.get_meta(conn, "canary_item_id")
    item = _item(conn, item_id) if item_id else None
    if item is None:
        raise ApiError(404, "not_found", "No canary yet.")
    revealed = []
    for entry in reversed(_log(conn)):
        old = _item(conn, entry["item_id"]) if entry.get("fk") else None
        if old is not None:
            revealed.append({"n": entry["n"], "sealed_at": entry["sealed_at"],
                             "raw": f"/api/v1/canary/raw?n={entry['n']}", "fk": entry["fk"],
                             "header": codec.b64u(old["header"]), "meta_ct": codec.b64u(old["meta_ct"]),
                             "size_stored": old["size_stored"]})
    return json_response(200, {
        "n": int(db.get_meta(conn, "canary_n", "0")), "sealed_at": int(db.get_meta(conn, "canary_sealed_at", "0")),
        "size_stored": item["size_stored"], "header": codec.b64u(item["header"]), "meta_ct": codec.b64u(item["meta_ct"]),
        "ct_hash": codec.b64u(item["ct_hash"]), "raw": "/api/v1/canary/raw",
        "delivery_tx": db.get_meta(conn, "canary_delivery_tx"), "revealed": revealed,
    }, "public, max-age=60")


def raw(ctx):
    ctx.limit(("canaryraw64", ctx.ip64, 30, 60, 1))
    conn = ctx.db
    wanted = ctx.req.query.get("n")
    if wanted is None:
        n, item_id = db.get_meta(conn, "canary_n"), db.get_meta(conn, "canary_item_id")
    else:
        if not wanted.isdigit() or len(wanted) > 9:
            raise ApiError(400, "bad_request", "Bad n.")
        match = [e for e in _log(conn) if e["n"] == int(wanted) and (e.get("fk") or
                                                                    e["item_id"] == db.get_meta(conn, "canary_item_id"))]
        n, item_id = (wanted, match[0]["item_id"]) if match else (None, None)
    item = _item(conn, item_id) if item_id else None
    if item is None or not ctx.app.blobs.exists(item["id"]):
        raise ApiError(404, "not_found", "No such canary.")
    return ranged(ctx, item["id"], item["size_stored"], f"mutis-canary-{int(n)}.bin", "public, max-age=60")
