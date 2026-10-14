# SPDX-License-Identifier: MIT
"""Payment verification (spec §10.5): credit only what was proven and is committed on chain.

The 2026-09-29 forged-deposit incident (community.tari.com/t/402) came from a wallet that checked an
amount proof and then ignored the result. Here a credit needs two separate facts:
  1. the amount: the official ootle-wasm `unblindOutput` (in the sidecar) opened the output's
     commitment with the decrypted value, so the value is proven, not reported; and
  2. existence: a Tari indexer (not walletd) serves a verified `Utxo` substate at exactly that id
     (the id contains the commitment).
walletd never decides a credit. In the G4 fallback (`amount_proof = "wallet"`) step 1 comes from
walletd's own list and the API reports `checks.amount_proven: false` ("Seen by our wallet").

R1 (2026-10-13, research 16-drive-architecture §1.1): a view key proves an output's amount and memo,
not who can spend it. A payer can build an output that opens with our receiver's view key while its
one-time key is the payer's own, get a pack and keep the money (and spending it back would make the
hourly reconcile freeze every credit). So, in sidecar mode, a third fact is needed:
  3. ownership: the one-time key the indexer shows for the output equals the one our receiver's owner
     key derives from the output's nonce (`stealthDhSecret`, the sidecar's `oneTimeKey`). A mismatch
     marks the payment `rejected`; it is never credited.

An invoice goes pending → seen → credited; the spec's `proven` step happens inside the crediting
transaction, so the UI's stepper reads `payments[].checks` instead of waiting for that status.
"""
import json
import re
import sqlite3

from . import db, logsafe, quota
from .indexer import IndexerError, substate_output

INVOICE_TTL_S = 3600
UNDERPAID_GRACE_DAYS = 7
INDEXER_FAILOVER_AFTER = 3
UNKNOWN_ALERT_AFTER = 3          # hourly reconciles that couldn't reach a verdict before the alert is critical
_INVOICE = re.compile(r"^inv_[a-z2-7]{20}$")
_CLAIM = re.compile(r"^clm_[a-z2-7]{20}$")


def pay_ref(memo) -> str | None:
    """The invoice id carried by a memo: PayRefAndBytes `[len u8][pay_ref][bytes]`, or a bare Message."""
    ref = memo_ref(memo)
    return ref if ref and _INVOICE.match(ref) else None


def claim_ref(memo) -> str | None:
    """The pay-to-open claim id (`clm_…`) carried by a memo, in the same two shapes (sales.py)."""
    ref = memo_ref(memo)
    return ref if ref and _CLAIM.match(ref) else None


def memo_ref(memo) -> str | None:
    """The reference a memo carries, unchecked: PayRefAndBytes' pay-ref, or the whole Message."""
    if not isinstance(memo, dict):
        return None
    if isinstance(memo.get("PayRefAndBytes"), str):
        try:
            raw = bytes.fromhex(memo["PayRefAndBytes"])
        except ValueError:
            return None
        if not raw or raw[0] + 1 > len(raw):
            return None
        ref = raw[1:1 + raw[0]].decode("ascii", "replace")
    elif isinstance(memo.get("Message"), str):
        ref = memo["Message"]
    else:
        return None
    return ref


def record_found(conn: sqlite3.Connection, found: list[dict], proven: bool, now: int, epoch: int | None) -> int:
    """Store newly found receiver outputs; a UTXO is recorded once, ever (idempotency). Returns new rows."""
    added = 0
    with db.tx(conn):
        for out in found:
            if conn.execute("SELECT 1 FROM payments WHERE utxo_id = ?", (out["id"],)).fetchone():
                continue
            ref = pay_ref(out.get("memo"))
            invoice = conn.execute("SELECT * FROM invoices WHERE id = ?", (ref,)).fetchone() if ref else None
            conn.execute("INSERT INTO payments(utxo_id, invoice_id, value_ut, seen_at, epoch, proven, status) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (out["id"], invoice["id"] if invoice else None, int(out["value_ut"]), now, epoch,
                          int(proven), "pending_check" if invoice else "unattributed"))
            if invoice and invoice["status"] == "pending":
                conn.execute("UPDATE invoices SET status = 'seen' WHERE id = ?", (invoice["id"],))
            added += 1
    return added


def utxo_on_indexer(indexers, utxo_id: str, position: int) -> tuple[str, dict]:
    """One indexer's answer about a UTXO id: (`ok` | `missing` | `unknown`, {"auth_key", "nonce"}).

    ok: HTTP 200, verified == true and a Utxo substate at exactly that id. missing: the indexer says
    so (its JSON 404 "… not found", or "… is down" for a spent output, or a 200 that isn't a verified
    Utxo). unknown: anything about the indexer rather than the output (5xx, 429, a 404 or 200 that isn't
    the indexer's JSON, such as a gateway's page while it deploys, a timeout). With `ok` come the
    output's one-time key and public nonce as the indexer shows them (None when absent), for R1.
    """
    none = {"auth_key": None, "nonce": None}
    try:
        status, data, _ = indexers.call_one(position, "GET", f"/substates/{utxo_id}?include_proof=true")
    except IndexerError:
        return "unknown", none
    if status not in (200, 404):
        return "unknown", none
    try:
        obj = json.loads(data)
    except ValueError:
        return "unknown", none
    if status == 404:
        return ("missing" if isinstance(obj, dict) and isinstance(obj.get("error"), str) else "unknown"), none
    if isinstance(obj, dict) and obj.get("verified") is True and isinstance(obj.get("substate"), dict) \
            and "Utxo" in obj["substate"]:
        auth_key, nonce = substate_output(obj)
        return "ok", {"auth_key": auth_key, "nonce": nonce}
    return "missing", none


def committed_on_indexer(indexers, utxo_id: str, position: int) -> str:
    """`utxo_on_indexer`'s verdict alone: `ok`, `missing` or `unknown`."""
    return utxo_on_indexer(indexers, utxo_id, position)[0]


def committed_anywhere(indexers, utxo_id: str) -> str:
    """`ok` when any indexer proves the UTXO, `missing` only when every indexer says it is gone."""
    answers = [committed_on_indexer(indexers, utxo_id, i) for i in range(len(indexers.upstreams))]
    if "ok" in answers:
        return "ok"
    return "missing" if all(a == "missing" for a in answers) else "unknown"


def check_pending(conn: sqlite3.Connection, indexers, failures: dict, now: int, owns=None) -> int:
    """Step 3: confirm each pending payment on indexer-b (indexer-a after 3 failures); credit it.

    `owns(nonce_hex, auth_key_hex)` → True | False | None is the R1 ownership check (sidecar mode): True
    credits, False rejects the payment for good, None (the check couldn't run) waits for the next tick
    like an indexer failure. Without it (the walletd fallback) ownership is walletd's own listing.
    """
    if db.get_meta(conn, "credit_freeze") == "1" or db.get_meta(conn, "reconcile_mismatch") is not None:
        return 0                                 # frozen, or held until a mismatch is checked again
    credited = 0
    for row in conn.execute("SELECT * FROM payments WHERE status = 'pending_check'").fetchall():
        position = 1 if failures.get(row["utxo_id"], 0) >= INDEXER_FAILOVER_AFTER and len(indexers.upstreams) > 1 \
            else 0
        verdict, seen = utxo_on_indexer(indexers, row["utxo_id"], position)
        ours = None if verdict != "ok" else True if owns is None else owns(seen["nonce"], seen["auth_key"])
        if ours is None:                         # never a credit without proof
            failures[row["utxo_id"]] = failures.get(row["utxo_id"], 0) + 1
            continue
        failures.pop(row["utxo_id"], None)
        if ours:
            credit(conn, row["utxo_id"], now)
            credited += 1
        else:
            reject(conn, row["utxo_id"])
    return credited


def reject(conn: sqlite3.Connection, utxo_id: str) -> None:
    """R1: an output that opens with our view key but that our owner key can't spend is not a payment.
    It stays recorded (a UTXO counts once, ever) as `rejected` and is never credited."""
    with db.tx(conn):
        conn.execute("UPDATE payments SET status = 'rejected' WHERE utxo_id = ? AND status = 'pending_check'",
                     (utxo_id,))
    logsafe.event("chain.payment_not_ours", "warning")


def credit(conn: sqlite3.Connection, utxo_id: str, now: int) -> None:
    with db.tx(conn):
        pay = conn.execute("SELECT * FROM payments WHERE utxo_id = ? AND status = 'pending_check'",
                           (utxo_id,)).fetchone()
        if pay is None:
            return
        conn.execute("UPDATE payments SET committed = 1, status = 'credited' WHERE utxo_id = ?", (utxo_id,))
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (pay["invoice_id"],)).fetchone()
        if inv is None or inv["status"] == "credited" or now > inv["expires_at"] + UNDERPAID_GRACE_DAYS * 86400:
            return
        received = inv["received_ut"] + min(pay["value_ut"], inv["price_ut"])   # one payment credits ≤ the price
        if received < inv["price_ut"]:
            status = "seen" if now <= inv["expires_at"] else "underpaid"
            conn.execute("UPDATE invoices SET received_ut = ?, status = ? WHERE id = ?", (received, status, inv["id"]))
            return
        conn.execute("UPDATE invoices SET received_ut = ?, status = 'credited', credited_at = ? WHERE id = ?",
                     (received, now, inv["id"]))
        if inv["identity_id"]:
            grant_pack(conn, inv["identity_id"], inv["pack"], now)


def grant_pack(conn: sqlite3.Connection, identity_id: str, pack_id: str, now: int) -> None:
    """Stack bytes and extend paid_until by the pack's days from max(now, paid_until) (spec §9.6)."""
    pack = quota.PACKS[pack_id]
    row = conn.execute("SELECT paid_bytes, paid_until FROM identities WHERE id = ?", (identity_id,)).fetchone()
    if row is None:
        return
    active = row["paid_until"] is not None and row["paid_until"] > now
    paid_bytes = (row["paid_bytes"] if active else 0) + pack["bytes"]
    paid_until = max(now, row["paid_until"] or 0) + pack["days"] * 86400
    conn.execute("UPDATE identities SET paid_bytes = ?, paid_until = ? WHERE id = ?", (paid_bytes, paid_until,
                                                                                       identity_id))


def reconcile(conn: sqlite3.Connection, rescan, committed, now: int) -> str:
    """Hourly check independent of walletd: every credited UTXO is still in our mirror, the sidecar
    still proves the same value for it, and it is still committed.

    `rescan(rows)` returns {utxo_id: value_ut} for the mirror rows it can open with the receiver key;
    `committed(utxo_id)` → ok | missing | unknown (`committed_anywhere`). A mismatch holds credits until
    the next round, five minutes later, and a second one in a row freezes them (`_finish_reconcile`);
    an indexer that can't answer only skips the round. Returns `ok`, `mismatch` or `unknown`.
    """
    credited = conn.execute("SELECT utxo_id, value_ut FROM payments WHERE status = 'credited'").fetchall()
    ids = [r["utxo_id"] for r in credited]
    rows = []
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        rows += conn.execute(f"SELECT id, nonce, enc FROM chain_utxos WHERE id IN ({','.join('?' * len(part))})",
                             part).fetchall()
    proven = rescan(rows) if rows else {}
    if len(rows) != len(ids) or any(proven.get(r["utxo_id"]) != r["value_ut"] for r in credited):
        verdict = "mismatch"
    else:
        answers = {committed(r["utxo_id"]) for r in credited}
        verdict = "mismatch" if "missing" in answers else "unknown" if "unknown" in answers else "ok"
    _finish_reconcile(conn, verdict, now)
    return verdict


def reconcile_wallet(conn: sqlite3.Connection, wallet_balance_ut: int, now: int) -> str:
    """G4 fallback reconcile: what we credited can't exceed what the receiving wallet holds."""
    total = conn.execute("SELECT COALESCE(SUM(value_ut), 0) FROM payments WHERE status = 'credited'").fetchone()[0]
    verdict = "ok" if total <= wallet_balance_ut else "mismatch"
    _finish_reconcile(conn, verdict, now)
    return verdict


def _finish_reconcile(conn: sqlite3.Connection, verdict: str, now: int) -> None:
    """A mismatch holds credits (`meta.reconcile_mismatch`) and the worker checks again five minutes
    later: a second mismatch in a row freezes credits until `mutis-admin unfreeze-credits`, an ok
    releases the hold. Both indexers can answer wrongly at the same moment (2026-10-12 15:37: one round
    found a mismatch that no round before or after it found, and every credited output was proven on
    both indexers), and a freeze stops every pack until a human acts; nothing is credited while a
    mismatch waits for its second check."""
    with db.tx(conn):
        unknown = int(db.get_meta(conn, "reconcile_unknown", "0")) + 1 if verdict == "unknown" else 0
        db.set_meta(conn, "reconcile_unknown", str(unknown))
        held = db.get_meta(conn, "reconcile_mismatch") is not None or db.get_meta(conn, "credit_freeze") == "1"
        # held: a mismatch is waiting for this check, or credits are already frozen (they stay frozen)
        if verdict != "unknown":
            db.set_meta(conn, "last_reconcile", str(now))
            db.del_meta(conn, "reconcile_mismatch")
        if verdict == "mismatch" and held:
            db.set_meta(conn, "credit_freeze", "1")
        elif verdict == "mismatch":
            db.set_meta(conn, "reconcile_mismatch", str(now))
    if verdict == "ok":
        logsafe.event("chain.reconcile_ok")
    elif verdict == "mismatch" and held:
        logsafe.event("chain.credit_freeze", "critical")
    elif verdict == "mismatch":
        logsafe.event("chain.reconcile_mismatch", "warning")
    else:
        logsafe.event("chain.reconcile_unknown", "critical" if unknown >= UNKNOWN_ALERT_AFTER else "warning")


def expire_invoices(conn: sqlite3.Connection, now: int) -> None:
    """Cleanup step 7: pending/seen invoices past expiry become expired or underpaid."""
    with db.tx(conn):
        conn.execute("UPDATE invoices SET status = CASE WHEN received_ut > 0 THEN 'underpaid' ELSE 'expired' END "
                     "WHERE status IN ('pending','seen') AND expires_at <= ?", (now,))

