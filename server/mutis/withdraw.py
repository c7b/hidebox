# SPDX-License-Identifier: MIT
"""Withdrawing earnings (docs/withdraw.md), behind features.withdraw: the rules and what our server keeps.

A withdrawal is a stealth transfer the seller's browser builds and signs with the drive's sales keys (derived from the
drive's seed, never sent anywhere): its inputs are outputs paid to the drive's sales address, one output goes to the
address the owner typed, another (the change) back to the sales address. Our server relays it, after two checks:

- **Shape**: the same stealth transfer as wallet.js's sends (one transfer in the fee phase paying its own fee of at most
  the network fee, one or two outputs), with up to MAX_INPUTS inputs.
- **Settled money only**: every input is one of this drive's payments our server vouches for, the same rule as
  Earnings counts (a committed payment that test money our demo wallet paid for a whole price, or that the owner's
  drive checked is its own: `owner_ok`), or change an earlier withdrawal of this drive sent back. A payment still being
  counted, or waiting for the owner's check, isn't: the payment checker can only count an output that is still on
  the chain, so spending it first would leave its buyer without the open they paid for.

Each input is marked with the withdrawal spending it (before the relay, so a second submission of the same outputs is
refused), until the drive reports the outcome (commit: spent; reject: free again) or PENDING_S passes. What our server
learns: that a withdrawal happened, when, which payments it spent, and the change the drive reports, so about how much
left. Never where to: the destination is inside a stealth output.
"""
import sqlite3

from . import cbor
from .http_util import ApiError

MAX_INPUTS = 8                 # outputs spent by one withdrawal (a send spends at most 4)
FEE_UT = 30000                 # the network fee every send pays (wallet.js FEE_UT); taken from what is withdrawn
MIN_ARRIVE_UT = FEE_UT         # at least as much as the fee reaches the address
MIN_UT = FEE_UT + MIN_ARRIVE_UT
DUST_UT = FEE_UT               # change below this costs more to move than it is worth: it goes along instead
PENDING_S = 600                # a withdrawal not reported within this is looked at again by the drive
ENVELOPE_MAX = 16 * 1024       # an eight-input withdrawal with change is about 5 KB
BODY_MAX = 32 * 1024
SUBMITS_PER_HOUR = 12          # per drive
TRIES_PER_HOUR = 60            # per drive, 120 per network: every request, counted before its envelope is read
LISTED = 500

# Instruction variants as tari_bor numbers them (handlers/chain.py, wallet.js unsignedTx).
STEALTH_TRANSFER, PUT_LAST_OUTPUT_ON_WORKSPACE, PAY_FEE_FROM_BUCKET = 12, 3, 13
RESOURCE_SUBSTATE = 1

# A payment of this drive's that our server vouches for (handlers/pay.py _EARNED, Earnings' totals).
_SALES = ("FROM sale_payments sp JOIN claims c ON c.id = sp.claim_id JOIN shares s ON s.id = c.share_id "
          "JOIN items i ON i.id = s.item_id WHERE i.owner_id = ?")
_VOUCHED = "sp.status IN ('counted','extra') AND (sp.owner_ok = 1 OR (c.demo = 1 AND sp.status = 'counted'))"


def config_block() -> dict:
    return {"fee_ut": str(FEE_UT), "min_ut": str(MIN_UT), "dust_ut": str(DUST_UT), "max_inputs": MAX_INPUTS,
            "pending_s": PENDING_S}


def invalid_tx() -> ApiError:
    return ApiError(422, "invalid", "Not a withdrawal this app builds.", details={"field": "transaction"})


def parse_envelope(raw: bytes, max_fee: int) -> tuple[list[str], list[str], int]:
    """(input utxo ids, output utxo ids, fee) of a withdrawal shaped like wallet.js's sends; 422 otherwise."""
    try:
        if len(raw) > ENVELOPE_MAX:
            raise ValueError("too large")
        version, [((unsigned, signatures), _seal)] = cbor.loads(raw)
        fee_instructions, instructions, inputs = unsigned[1], unsigned[2], unsigned[3]
        (kind, (resource, statement)), *rest = fee_instructions
        outputs, (fee, _seal_key), _proof = statement[1]
        shaped = (version == 0 and kind == STEALTH_TRANSFER and instructions == []
                  and [r[0] for r in rest] == [PUT_LAST_OUTPUT_ON_WORKSPACE, PAY_FEE_FROM_BUCKET]
                  and 2 <= len(inputs) <= 1 + MAX_INPUTS and len(signatures) == len(inputs) - 1
                  and 1 <= len(outputs) <= 2 and isinstance(fee, int) and 0 < fee <= max_fee
                  and inputs[0][0][0] == RESOURCE_SUBSTATE and inputs[0][2] is False)
        if not shaped:
            raise ValueError("shape")
        resource_hex = cbor.substate_id(inputs[0][0]).split("_", 1)[1]
        spent = [cbor.substate_id(i[0]) for i in inputs[1:]]
        if any(not (u or "").startswith("utxo_") for u in spent) or len(set(spent)) != len(spent) \
                or any(i[2] is not True for i in inputs[1:]):
            raise ValueError("inputs")
        # A commitment is 32 bytes, checked before anything is made from it: `bytes(n)` of a CBOR integer n would
        # allocate n bytes (security pass, 2026-11-09: a 153-byte envelope took the API past its memory limit).
        commitments = [o[0][0] for o in outputs]
        if any(not (isinstance(c, bytes) and len(c) == 32) for c in commitments):
            raise ValueError("outputs")
        made = [f"utxo_{resource_hex}_{c.hex()}" for c in commitments]
    except (cbor.CborError, IndexError, TypeError, ValueError, AttributeError):
        raise invalid_tx() from None
    return spent, made, fee


def spendable(conn: sqlite3.Connection, identity_id: str, now: int) -> list[dict]:
    """This drive's settled outputs not yet spent by a committed withdrawal, each with the withdrawal pending on it
    (if one is, and how long ago), oldest first: payments our server vouches for, and change back from withdrawals."""
    rows = conn.execute(f"SELECT sp.utxo_id, sp.value_ut, sp.seen_at AS at, c.demo, sp.withdraw_tx, sp.withdraw_at {_SALES} "
                        f"AND {_VOUCHED} AND sp.withdrawn = 0 ORDER BY sp.seen_at, sp.utxo_id LIMIT ?",
                        (identity_id, LISTED)).fetchall()
    out = [{"utxo_id": r["utxo_id"], "value_ut": str(r["value_ut"]), "source": "sale", "demo": bool(r["demo"]),
            "at": r["at"], "pending_tx": r["withdraw_tx"], "pending_at": r["withdraw_at"]} for r in rows]
    for r in conn.execute("SELECT * FROM sales_change WHERE identity_id = ? AND withdrawn = 0 ORDER BY created_at LIMIT ?",
                          (identity_id, LISTED)).fetchall():
        pending = (r["from_tx"], r["created_at"]) if not r["committed"] else (r["withdraw_tx"], r["withdraw_at"])
        out.append({"utxo_id": r["utxo_id"], "value_ut": str(r["value_ut"]), "source": "change", "demo": False,
                    "at": r["created_at"], "pending_tx": pending[0], "pending_at": pending[1]})
    return out


def waiting(conn: sqlite3.Connection, identity_id: str) -> dict:
    """This drive's payments not settled yet (being counted, or waiting for the owner's check): not withdrawable."""
    row = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(sp.value_ut), 0) {_SALES} AND sp.withdrawn = 0 AND ("
                       "sp.status = 'pending_check' OR (sp.status = 'counted' AND c.demo = 0 AND sp.owner_ok IS NULL))",
                       (identity_id,)).fetchone()
    return {"payments": row[0], "value_ut": str(row[1])}


def _busy(at, now: int) -> bool:
    return at is not None and now - at < PENDING_S


def claim_inputs(conn: sqlite3.Connection, identity_id: str, utxo_ids: list[str], marker: str, now: int) -> int:
    """Inside the caller's transaction: check every input is this drive's settled, unspent output with no withdrawal
    pending on it, and mark it with `marker`. -> the inputs' total (µT). 409 `not_withdrawable` or `withdraw_pending`
    (details.utxo_id) otherwise."""
    total = 0
    for utxo_id in utxo_ids:
        sale = conn.execute(f"SELECT sp.value_ut, sp.withdraw_tx, sp.withdraw_at {_SALES} AND {_VOUCHED} "
                            "AND sp.withdrawn = 0 AND sp.utxo_id = ?", (identity_id, utxo_id)).fetchone()
        change = None if sale else conn.execute("SELECT * FROM sales_change WHERE utxo_id = ? AND identity_id = ? "
                                                "AND withdrawn = 0", (utxo_id, identity_id)).fetchone()
        row = sale or change
        if row is None or (change is not None and not change["committed"]):
            raise ApiError(409, "not_withdrawable", "Some of this money isn't settled yet, or isn't this drive's.",
                           details={"utxo_id": utxo_id})
        if row["withdraw_tx"] is not None and _busy(row["withdraw_at"], now):
            raise ApiError(409, "withdraw_pending", "A withdrawal of this money is already on its way.",
                           details={"utxo_id": utxo_id})
        table = "sale_payments" if sale else "sales_change"
        conn.execute(f"UPDATE {table} SET withdraw_tx = ?, withdraw_at = ? WHERE utxo_id = ?", (marker, now, utxo_id))
        total += row["value_ut"]
    return total


def retag(conn: sqlite3.Connection, marker: str, tx_id: str | None) -> None:
    """The marker of a withdrawal being relayed becomes its transaction id, or is cleared (None) when it wasn't."""
    for table in ("sale_payments", "sales_change"):
        if tx_id is None:
            conn.execute(f"UPDATE {table} SET withdraw_tx = NULL, withdraw_at = NULL WHERE withdraw_tx = ?", (marker,))
        else:
            conn.execute(f"UPDATE {table} SET withdraw_tx = ? WHERE withdraw_tx = ?", (tx_id, marker))


def settle(conn: sqlite3.Connection, identity_id: str, tx_id: str, committed: bool) -> int:
    """The drive's report of a withdrawal's outcome. Commit: its inputs are spent and its change is withdrawable.
    Reject: its inputs are free again and its change never existed. -> the rows it touched."""
    mine = (f"utxo_id IN (SELECT sp.utxo_id {_SALES})", (identity_id,))
    touched = 0
    if committed:
        touched += conn.execute(f"UPDATE sale_payments SET withdrawn = 1 WHERE withdraw_tx = ? AND {mine[0]}",
                                (tx_id, *mine[1])).rowcount
        touched += conn.execute("UPDATE sales_change SET withdrawn = 1 WHERE withdraw_tx = ? AND identity_id = ?",
                                (tx_id, identity_id)).rowcount
        touched += conn.execute("UPDATE sales_change SET committed = 1 WHERE from_tx = ? AND identity_id = ?",
                                (tx_id, identity_id)).rowcount
    else:
        touched += conn.execute(f"UPDATE sale_payments SET withdraw_tx = NULL, withdraw_at = NULL WHERE withdraw_tx = ? "
                                f"AND withdrawn = 0 AND {mine[0]}", (tx_id, *mine[1])).rowcount
        touched += conn.execute("UPDATE sales_change SET withdraw_tx = NULL, withdraw_at = NULL WHERE withdraw_tx = ? "
                                "AND withdrawn = 0 AND identity_id = ?", (tx_id, identity_id)).rowcount
        touched += conn.execute("DELETE FROM sales_change WHERE from_tx = ? AND identity_id = ? AND committed = 0",
                                (tx_id, identity_id)).rowcount
    return touched
