# SPDX-License-Identifier: MIT
"""Chain reads: the UTXO mirror, the allowlisted indexer proxy and "What the chain sees" (spec §6.3, §10.6, §10.7).

Everyone downloads the same mirror, so the server never learns which outputs a browser can open.
The proxy forwards no client header and only paths on the allowlist.
"""
import json
import re

from .. import indexer
from ..http_util import ApiError, PARAM_RE, Response, json_response
from ..indexer import IndexerError

PAGE_MAX = 1000
INDEXER_LOOKUPS = 8              # outputs per transaction view the indexer is asked about when the mirror can't say
TX_BODY_MAX = 200 * 1024
_GET_ALLOW = [
    (re.compile(r"^substates/((?:utxo|component|template|resource|vault)_[0-9a-f_]{20,200})$"),
     "/substates/{0}?include_proof=true"),
    (re.compile(r"^transactions/([0-9a-f]{64})/result$"), "/transactions/{0}/result"),
    (re.compile(r"^network$"), "/network"),
    (re.compile(r"^epoch-manager/stats$"), "/epoch-manager/stats"),     # the browser wallet's epoch (G1)
    (re.compile(r"^templates/((?:template_)?[0-9a-f]{64})$"), "/templates/{0}"),
]
_POST_ALLOW = {"transactions": "/transactions", "transactions/dry-run": "/transactions/dry-run"}


def _query_int(ctx, name: str, default: int, lo: int, hi: int) -> int:
    value = ctx.req.query.get(name)
    if value is None or value == "":
        return default
    if not value.isdigit() or not lo <= int(value) <= hi:
        raise ApiError(400, "bad_request", f"Bad {name}.")
    return int(value)


def utxos(ctx):
    ctx.limit(("chain64", ctx.ip64, 120, 60, 1))
    after = _query_int(ctx, "after", 0, 0, 1 << 62)
    limit = _query_int(ctx, "limit", 500, 1, PAGE_MAX)
    rows = ctx.db.execute("SELECT seq, id, nonce, enc, tag, epoch FROM chain_utxos WHERE seq > ? ORDER BY seq LIMIT ?",
                          (after, limit)).fetchall()
    head = ctx.db.execute("SELECT COALESCE(MAX(seq), 0) FROM chain_utxos").fetchone()[0]
    items = [{"seq": r["seq"], "id": r["id"], "nonce": r["nonce"].hex(), "enc": r["enc"].hex(),
              "tag": r["tag"].hex() if r["tag"] is not None else None, "epoch": r["epoch"]} for r in rows]
    return json_response(200, {"items": items, "next": rows[-1]["seq"] if rows else after, "head": head},
                         "public, max-age=5")


def seq(ctx):
    """The mirror position just before `epoch`: pass it as `after` to scan from that epoch on."""
    ctx.limit(("chain64", ctx.ip64, 120, 60, 1))
    epoch = _query_int(ctx, "epoch", 0, 0, 1 << 40)
    value = ctx.db.execute("SELECT COALESCE(MAX(seq), 0) FROM chain_utxos WHERE epoch < ?", (epoch,)).fetchone()[0]
    return json_response(200, {"seq": value}, "public, max-age=5")


def _with_source(data: bytes, source: str) -> bytes:
    try:
        obj = json.loads(data)
    except ValueError:
        raise ApiError(502, "chain_unavailable", "The indexer answered with something unexpected.") from None
    if isinstance(obj, dict):
        obj["_source"] = source
    return json.dumps(obj, separators=(",", ":")).encode()


def proxy(ctx, rest: str):
    if ctx.req.method == "GET":
        ctx.limit(("chain64", ctx.ip64, 120, 60, 1))
        for pattern, target in _GET_ALLOW:
            m = pattern.match(rest)
            if m:
                upstream = target.format(*m.groups())
                break
        else:
            raise ApiError(404, "not_found", "That indexer path isn't proxied.")

        def fetch():
            try:
                status, data, source = ctx.app.indexers.call("GET", upstream)
            except IndexerError as e:
                raise ApiError(503, "chain_unavailable", "The Tari indexers aren't answering.") from e
            return status, _with_source(data, source)

        status, body = ctx.app.cached("ix:" + upstream, 10, fetch)
        return Response(status, body, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"})

    if rest not in _POST_ALLOW:
        raise ApiError(404, "not_found", "That indexer path isn't proxied.")
    ctx.require_feature("direct_send")
    ctx.limit(("ixpost64", ctx.ip64, 30, 3600, 1), ("ixpost48", ctx.ip48, 90, 3600, 1))
    ctx.req.check_length(TX_BODY_MAX)
    body = b"".join(ctx.req.body_slices(ctx.req.content_length))
    try:
        json.loads(body)
        status, data, source = ctx.app.indexers.call("POST", _POST_ALLOW[rest], body)
    except ValueError:
        raise ApiError(400, "bad_request", "Body is not valid JSON.") from None
    except IndexerError as e:
        raise ApiError(503, "chain_unavailable", "The Tari indexers aren't answering.") from e
    return Response(status, _with_source(data, source), {"Content-Type": "application/json; charset=utf-8"})


def tx_view(ctx, tx_id: str):
    """The "What the chain sees" model: the indexer's committed receipt (kept indefinitely), and for
    each output what it reveals, read from our mirror or the indexer, never assumed."""
    ctx.limit(("chain64", ctx.ip64, 120, 60, 1))
    view = ctx.app.cached("txview:" + tx_id, 60, lambda: _build_view(ctx, tx_id))
    if view is None:
        raise ApiError(404, "not_found", "The indexers don't know this transaction.")
    return json_response(200, view, "public, max-age=60")


def _build_view(ctx, tx_id: str) -> dict | None:
    try:
        status, obj, source = ctx.app.indexers.get_json(f"/transaction-receipts/{tx_id}")
    except IndexerError as e:
        raise ApiError(503, "chain_unavailable", "The Tari indexers aren't answering.") from e
    if status != 200 or not isinstance(obj, dict) or not isinstance(obj.get("receipt"), dict):
        return None
    receipt = obj["receipt"]
    diff = receipt.get("diff_summary") or {}
    upped = [u.get("substate_id") for u in diff.get("upped", []) if isinstance(u, dict)]
    downed = [d.get("substate_id") for d in diff.get("downed", []) if isinstance(d, dict)]
    utxos = [sid for sid in upped
             if isinstance(sid, str) and PARAM_RE["substate"].match(sid) and sid.startswith("utxo_")]
    outputs = [_output_view(ctx, sid, ask_indexer=i < INDEXER_LOOKUPS) for i, sid in enumerate(utxos)]
    fee = (receipt.get("fee_receipt") or {}).get("total_fees_paid")
    return {"tx_id": tx_id, "status": receipt.get("outcome"), "epoch": receipt.get("epoch"),
            "fee_ut": str(fee) if isinstance(fee, int) else None,
            "inputs": [d for d in downed if isinstance(d, str)],
            "outputs": outputs,
            "substates_created": [u for u in upped if isinstance(u, str) and not u.startswith("utxo_")],
            "_source": source}


def _output_view(ctx, substate_id: str, ask_indexer: bool) -> dict:
    """One output as the chain shows it: "hidden" only where the output itself was read and reveals
    nothing (no minimum value promise, no viewable balance)."""
    row = ctx.db.execute("SELECT length(enc) AS sealed, promise, viewable, auth FROM chain_utxos WHERE id = ?",
                         (substate_id,)).fetchone()
    facts = {"sealed": row["sealed"], **{k: row[k] for k in ("promise", "viewable", "auth")}} if row else \
        {"sealed": None, "promise": None, "viewable": None, "auth": None}
    if facts["auth"] is None and ask_indexer:
        facts.update(_indexer_facts(ctx, substate_id))
    promise, viewable = facts["promise"], facts["viewable"]
    amount = "unknown" if promise is None or viewable is None else \
        "viewable" if viewable else "lower_bound" if promise > 0 else "hidden"
    owner = "unknown" if facts["auth"] is None else "one-time key" if facts["auth"] == "key" else "spend rule"
    out = {"id": substate_id, "commitment": substate_id.rsplit("_", 1)[1], "amount": amount, "owner": owner,
           "sealed_bytes": facts["sealed"]}
    if promise:
        out["min_value_ut"] = str(promise)
    return out


def _indexer_facts(ctx, substate_id: str) -> dict:
    """The output's facts from the indexer (an output spent since then answers "… is down": no facts)."""
    try:
        status, obj, _ = ctx.app.indexers.get_json(f"/substates/{substate_id}")
        output = obj["substate"]["Utxo"]["output"]
        enc = output["output"]["encrypted_data"]
    except (IndexerError, KeyError, TypeError):
        return {}
    if status != 200 or not isinstance(output, dict) or not isinstance(enc, str):
        return {}
    return {"sealed": len(enc) // 2, **indexer.reveals(output)}
