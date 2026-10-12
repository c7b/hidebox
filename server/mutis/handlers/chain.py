# SPDX-License-Identifier: MIT
"""Chain reads: the UTXO mirror, the allowlisted indexer proxy and "What the chain sees" (spec §6.3, §10.6, §10.7).

Everyone downloads the same mirror, so the server never learns which outputs a browser can open.
The proxy forwards no client header and only paths on the allowlist. Submitting a transaction takes
a locker session and relays only a transaction shaped like the ones wallet.js builds, so the proxy
can't serve as an address-hiding relay for any other Esmeralda transaction (claims review, item 21).
"""
import base64
import binascii
import json
import re

from .. import cbor, indexer, mirror
from ..http_util import ApiError, PARAM_RE, Response, json_response
from ..indexer import IndexerError

PAGE_MAX = 1000
INDEXER_LOOKUPS = 8              # outputs per transaction view the indexer is asked about when the mirror can't say
ENVELOPE_MAX = 8 * 1024          # a four-input send with change and a delivery memo is about 2.5 KB
TX_BODY_MAX = 12 * 1024          # the envelope in base64 plus its JSON wrapper
MAX_INPUTS = 4                   # wallet.js MAX_INPUTS: outputs spent in one send
# Instruction variants as tari_bor numbers them (web/app/lib/wallet.js unsignedTx, in that order).
STEALTH_TRANSFER, PUT_LAST_OUTPUT_ON_WORKSPACE, PAY_FEE_FROM_BUCKET = 12, 3, 13
_RESULT = re.compile(r"^transactions/([0-9a-f]{64})/result$")
_GET_ALLOW = [
    (re.compile(r"^substates/((?:utxo|component|template|resource|vault)_[0-9a-f_]{20,200})$"),
     "/substates/{0}?include_proof=true"),
    (_RESULT, "/transactions/{0}/result"),
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
        if status == 200 and pattern is _RESULT:
            ctx.app.cached("mirrored:" + m.group(1), 86400, lambda: _mirror_if_committed(ctx, body))
        return Response(status, body, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"})

    if rest not in _POST_ALLOW:
        raise ApiError(404, "not_found", "That indexer path isn't proxied.")
    ctx.require_feature("direct_send")
    ctx.session()
    ctx.limit(("ixpost64", ctx.ip64, 30, 3600, 1), ("ixpost48", ctx.ip48, 90, 3600, 1))
    ctx.req.check_length(TX_BODY_MAX)
    body = ctx.req.json()
    envelope = _own_send_envelope(body, ctx.cfg["ootle"]["max_fee_transfer_ut"])
    try:
        status, data, source = ctx.app.indexers.call("POST", _POST_ALLOW[rest], json.dumps({"transaction": envelope}).encode())
    except IndexerError as e:
        raise ApiError(503, "chain_unavailable", "The Tari indexers aren't answering.") from e
    return Response(status, _with_source(data, source), {"Content-Type": "application/json; charset=utf-8"})


def _own_send_envelope(body: dict, max_fee: int) -> str:
    """The base64 BOR envelope of a transaction shaped like wallet.js's send(): one stealth transfer
    in the fee phase paying its own fee of at most `max_fee` from a bucket, one output plus change,
    up to MAX_INPUTS inputs after the resource, no other instruction. Anything else is refused."""
    raw = body.get("transaction")
    if set(body) != {"transaction"} or not isinstance(raw, str) or len(raw) > ENVELOPE_MAX * 4 // 3 + 4:
        raise ApiError(422, "invalid", "Not a transaction this app builds.", details={"field": "transaction"})
    try:
        envelope = base64.b64decode(raw, validate=True)
        if len(envelope) > ENVELOPE_MAX:
            raise ValueError("too large")
        version, [((unsigned, signatures), _seal)] = cbor.loads(envelope)
        fee_instructions, instructions, inputs = unsigned[1], unsigned[2], unsigned[3]
        (kind, (_resource, statement)), *rest = fee_instructions
        outputs, (fee, _seal_key), _proof = statement[1]
        shaped = (version == 0 and kind == STEALTH_TRANSFER and instructions == []
                  and [r[0] for r in rest] == [PUT_LAST_OUTPUT_ON_WORKSPACE, PAY_FEE_FROM_BUCKET]
                  and 2 <= len(inputs) <= 1 + MAX_INPUTS and len(signatures) == len(inputs) - 1
                  and 1 <= len(outputs) <= 2 and isinstance(fee, int) and 0 < fee <= max_fee)
    except (binascii.Error, cbor.CborError, IndexError, TypeError, ValueError):
        shaped = False
    if not shaped:
        raise ApiError(422, "invalid", "Not a transaction this app builds.", details={"field": "transaction"})
    return raw


def _mirror_if_committed(ctx, body: bytes) -> bool | None:
    """Direct mode: a browser waits for its own transaction here. Once it has committed, its outputs go
    into the mirror at once, as the chain worker's own do (once per transaction; None asks again)."""
    tx = _from_result(json.loads(body))
    if tx is None or tx["outcome"] != "Commit":
        return None
    mirror.add_committed(ctx.db, ctx.app.indexers, tx["upped"], tx["epoch"], ctx.now)
    return True


def tx_view(ctx, tx_id: str):
    """The "What the chain sees" model: the transaction as an indexer holds it, and for each output what
    it reveals, read from our mirror or the indexer, never assumed."""
    ctx.limit(("chain64", ctx.ip64, 120, 60, 1))
    view = ctx.app.cached("txview:" + tx_id, 60, lambda: _build_view(ctx, tx_id))
    if view is None:
        raise ApiError(404, "not_found", "The indexers don't know this transaction.")
    return json_response(200, view, "public, max-age=60")


def _ask_each(ctx, path: str, parse):
    """`parse(answer)` of the first indexer whose answer parses (None: try the next), with its name."""
    answered = False
    for position in range(len(ctx.app.indexers.upstreams)):
        try:
            status, obj, source = ctx.app.indexers.get_json(path, only=position)
        except IndexerError:
            continue
        answered = True
        found = parse(obj) if status == 200 and isinstance(obj, dict) else None
        if found is not None:
            return found, source
    if not answered:
        raise ApiError(503, "chain_unavailable", "The Tari indexers aren't answering.")
    return None


def _from_receipt(obj: dict) -> dict | None:
    """GET /transaction-receipts/{id}: kept indefinitely, but filled in minutes after the commit."""
    receipt = obj.get("receipt")
    if not isinstance(receipt, dict):
        return None
    diff = receipt.get("diff_summary") or {}
    return {"outcome": receipt.get("outcome"), "epoch": receipt.get("epoch"),
            "upped": [u.get("substate_id") for u in diff.get("upped", []) if isinstance(u, dict)],
            "downed": [d.get("substate_id") for d in diff.get("downed", []) if isinstance(d, dict)],
            "fee": (receipt.get("fee_receipt") or {}).get("total_fees_paid")}


def _from_result(obj: dict) -> dict | None:
    """GET /transactions/{id}/result: there as soon as the transaction is final, forgotten after 50 epochs."""
    final = (obj.get("result") or {}).get("Finalized") if isinstance(obj.get("result"), dict) else None
    execution = final.get("execution_result") if isinstance(final, dict) else None
    finalize = execution.get("finalize") if isinstance(execution, dict) else None
    if not isinstance(finalize, dict):
        return None
    accept = (finalize.get("result") or {}).get("Accept") or {}
    return {"outcome": final.get("final_decision"), "epoch": execution.get("execute_epoch"),
            "upped": _first_items(accept.get("up_substates", [])), "downed": _first_items(accept.get("down_substates", [])),
            "fee": (finalize.get("fee_receipt") or {}).get("total_fees_paid")}


def _first_items(rows) -> list:
    """[[substate_id, …], …] → the ids."""
    return [r[0] for r in rows if isinstance(r, list) and r]


def _build_view(ctx, tx_id: str) -> dict | None:
    """From the committed receipt, or, until the indexers have filled it in, the transaction's result.
    Each indexer is asked in turn: a transaction committed seconds ago can reach one before the other."""
    found = _ask_each(ctx, f"/transaction-receipts/{tx_id}", _from_receipt) \
        or _ask_each(ctx, f"/transactions/{tx_id}/result", _from_result)
    if found is None:
        return None
    tx, source = found
    upped = [u for u in tx["upped"] if isinstance(u, str)]
    utxos = [sid for sid in upped if PARAM_RE["substate"].match(sid) and sid.startswith("utxo_")]
    outputs = [_output_view(ctx, sid, ask_indexer=i < INDEXER_LOOKUPS) for i, sid in enumerate(utxos)]
    fee = tx["fee"]
    return {"tx_id": tx_id, "status": tx["outcome"], "epoch": tx["epoch"],
            "fee_ut": str(fee) if isinstance(fee, int) else None,
            "inputs": [d for d in tx["downed"] if isinstance(d, str)],
            "outputs": outputs,
            "substates_created": [u for u in upped if not u.startswith("utxo_")],
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
