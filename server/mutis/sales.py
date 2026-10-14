# SPDX-License-Identifier: MIT
"""Pay to open (research 16-drive-design §4, annex 16-drive-architecture §1.3–§1.9).

A paid link splits its key: half after the `#` in the link (`sA`, which we never see), half
(`server_half`, `sB`) here. A buyer makes a claim (`clm_…`, which is also the payment reference) and pays
the owner's **sales address** with that reference in the memo; the money goes to the owner, never to us.
The chain worker finds the payment with the sales view key the owner's drive sealed to our payment
checker (`PUT /me/sales`), proves its amount with the official `unblindOutput` and checks an indexer
commits it, exactly as for packs (payments.py). Then the release gate decides:

* **Test money** (`demo = 1`): our demo wallet built the output for the full price, to the claim's
  address, so the owner can spend it by construction. It releases at `paid`.
* **Any other payment**: a view key proves amount and memo, never who can spend the output (R2, the same
  hole as R1 for packs: `createStealthOutputWitness` takes the owner and view keys separately). We can't
  run the ownership check, because only the owner's drive holds the sales owner key. So a `paid` claim
  waits at `owner_check = 'pending'` until the owner's drive checks the payment's one-time key and calls
  `POST /me/sales/claims/{cid}/confirm` (`ok` releases it; `bad` voids it).

`server_half` goes to whoever shows the claim token `t` (we keep only SHA-256(t)), once the claim is
released, while it has opens left and its window is open. `end_share` scrubs `server_half` and voids
the link's unreleased claims (`end_for_share`).
"""
import sqlite3

from . import codec, db, ootle_addr
from .payments import INDEXER_FAILOVER_AFTER, claim_ref, utxo_on_indexer

PRICES_UT = (100_000, 250_000, 500_000)     # 0.1 / 0.25 / 0.5 tTARI: each at least three fees
BUYER_VIEWS = 3                              # opens a paid claim gives
BUYER_WINDOW_S = 7 * 86400                   # within this long after its release
CLAIM_TTL_S = 3600                           # time to pay a claim
LATE_GRACE_S = 86400                         # top-ups of an underpaid claim still count this long
DEMO_MAX_UT = 500_000                        # our demo wallet pays at most this per claim (test money)
MAX_OPEN_CLAIMS_PER_SHARE = 20
MAX_OPEN_CLAIMS = 500                        # across every link: the worker's scanning stays bounded
SALES_PUT_PER_DAY = 10
SELLERS_PER_TICK = 50
SCAN_ROWS = 10_000                           # mirror rows one seller's scan reads per tick
WATCH_FLAG = 0x08                            # courier inner payload flag: the `s` slot carries a view key
WATCH_LABEL = b"mutis-watch-v1"
VIEW_SEALED_LEN = 125                        # a kind-3 sealed blob (10-spec §4.9.3)

OPEN = ("pending", "seen", "underpaid")      # waiting for money
UNRELEASED = OPEN + ("paid",)


def config_block(fee_ut: int, watch_address: str | None) -> dict:
    return {"prices_ut": [str(p) for p in PRICES_UT], "fee_ut": str(fee_ut), "buyer_views": BUYER_VIEWS,
            "buyer_window_s": BUYER_WINDOW_S, "claim_ttl_s": CLAIM_TTL_S, "late_grace_s": LATE_GRACE_S,
            "demo_max_ut": str(DEMO_MAX_UT), "watch_address": watch_address,
            "max_open_claims_per_share": MAX_OPEN_CLAIMS_PER_SHARE}


def watch_ref(address: str) -> bytes:
    """The `ref16` a sealed sales view key carries: it binds the blob to the address it watches."""
    return codec.sha256(WATCH_LABEL, address.encode())[:16]


def mirror_head(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(seq), 0) FROM chain_utxos").fetchone()[0]


def seller_of_share(conn: sqlite3.Connection, share_id: str):
    return conn.execute("SELECT se.* FROM sellers se JOIN items i ON i.owner_id = se.identity_id "
                        "JOIN shares s ON s.item_id = i.id WHERE s.id = ?", (share_id,)).fetchone()


def releasable(claim) -> bool:
    """The release gate: test money we built releases once paid; any other payment waits for the owner's
    drive to check the money is the owner's to spend."""
    return claim["status"] == "paid" and (claim["demo"] == 1 or claim["owner_check"] == "ok")


def release(conn: sqlite3.Connection, claim, paid_share, now: int) -> None:
    conn.execute("UPDATE claims SET status = 'released', released_at = ?, views_left = ?, open_until = ? "
                 "WHERE id = ? AND status = 'paid'",
                 (now, paid_share["buyer_views"], now + paid_share["buyer_window_s"], claim["id"]))


def usable(claim, now: int) -> str | None:
    """Why a claim can't open its link right now (`payment_required`, `no_opens_left`, `window_over`)."""
    if claim["status"] != "released":
        return "payment_required"
    if claim["views_left"] <= 0:
        return "no_opens_left"
    if now >= claim["open_until"]:
        return "window_over"
    return None


def end_for_share(conn: sqlite3.Connection, share_id: str) -> None:
    """A paid link ended (revoked, its file deleted or removed): our half of the key goes, claims still
    waiting are void, and released buyers have no opens left. The rows stay for the owner's Activity."""
    conn.execute("UPDATE paid_shares SET server_half = NULL WHERE share_id = ?", (share_id,))
    conn.execute(f"UPDATE claims SET status = 'void' WHERE share_id = ? AND status IN ({_q(UNRELEASED)})",
                 (share_id, *UNRELEASED))
    conn.execute("UPDATE claims SET views_left = 0 WHERE share_id = ? AND status = 'released'", (share_id,))


def expire_claims(conn: sqlite3.Connection, now: int) -> None:
    """Cleanup: claims past their time to pay become expired (nothing seen) or underpaid; an underpaid
    claim whose late grace is over expires too. Released claims keep their row until the tombstone purge."""
    with db.tx(conn):
        conn.execute("UPDATE claims SET status = CASE WHEN status = 'pending' THEN 'expired' ELSE 'underpaid' END "
                     "WHERE status IN ('pending','seen') AND expires_at <= ?", (now,))
        conn.execute("UPDATE claims SET status = 'expired' WHERE status = 'underpaid' AND expires_at + ? <= ?",
                     (LATE_GRACE_S, now))


# --- the chain worker's side (annex §1.6) ------------------------------------------------------------

def _q(values: tuple) -> str:
    return ",".join("?" * len(values))


def sellers_to_open(conn: sqlite3.Connection) -> list:
    """Sellers whose sealed view key the worker hasn't opened yet (new or replaced)."""
    return conn.execute("SELECT * FROM sellers WHERE state = 'pending' ORDER BY created_at LIMIT ?",
                        (SELLERS_PER_TICK,)).fetchall()


def set_seller_state(conn: sqlite3.Connection, identity_id: str, view_sealed: bytes, state: str) -> None:
    """Only for the blob the worker opened: a replacement in between stays `pending` for the next tick."""
    with db.tx(conn):
        conn.execute("UPDATE sellers SET state = ? WHERE identity_id = ? AND view_sealed = ?",
                     (state, identity_id, view_sealed))


_OPEN_CLAIMS_OF = ("FROM claims c JOIN shares s ON s.id = c.share_id JOIN items i ON i.id = s.item_id "
                   f"WHERE i.owner_id = se.identity_id AND c.status IN ({_q(OPEN)}) AND ? <= c.expires_at + ?")


def sellers_to_scan(conn: sqlite3.Connection, now: int) -> list:
    """Sellers with a claim still waiting for money, least recently scanned first, at most 50, each with
    the mirror position its oldest waiting claim was made at."""
    return conn.execute(f"SELECT se.*, (SELECT MIN(c.created_seq) {_OPEN_CLAIMS_OF}) AS first_seq FROM sellers se "
                        f"WHERE se.state = 'ok' AND EXISTS (SELECT 1 {_OPEN_CLAIMS_OF}) "
                        "ORDER BY COALESCE(se.scanned_at, 0), se.created_at LIMIT ?",
                        (*OPEN, now, LATE_GRACE_S, *OPEN, now, LATE_GRACE_S, SELLERS_PER_TICK)).fetchall()


def scan_start(seller) -> int:
    return max(seller["scan_seq"], (seller["first_seq"] or 1) - 1)


def record_sales(conn: sqlite3.Connection, seller_id: str, found: list[dict], scanned_to: int, now: int,
                 epoch: int | None) -> int:
    """Store the outputs a seller's scan found whose memo names a claim on one of this seller's links.
    Anything else the view key opens (the seller's other income) is not recorded. A UTXO counts once, ever."""
    added = 0
    with db.tx(conn):
        for out in found:
            cid = claim_ref(out.get("memo"))
            claim = conn.execute(
                "SELECT c.* FROM claims c JOIN shares s ON s.id = c.share_id JOIN items i ON i.id = s.item_id "
                "WHERE c.id = ? AND i.owner_id = ?", (cid, seller_id)).fetchone() if cid else None
            if claim is None or claim["status"] in ("expired", "void"):
                continue
            if conn.execute("SELECT 1 FROM sale_payments WHERE utxo_id = ?", (out["id"],)).fetchone():
                continue
            conn.execute("INSERT INTO sale_payments(utxo_id, claim_id, value_ut, seen_at, epoch, status) "
                         "VALUES (?, ?, ?, ?, ?, 'pending_check')", (out["id"], claim["id"], int(out["value_ut"]),
                                                                   now, epoch))
            if claim["status"] == "pending":
                conn.execute("UPDATE claims SET status = 'seen' WHERE id = ?", (claim["id"],))
            added += 1
        conn.execute("UPDATE sellers SET scan_seq = MAX(scan_seq, ?), scanned_at = ? WHERE identity_id = ?",
                     (scanned_to, now, seller_id))
    return added


def check_pending(conn: sqlite3.Connection, indexers, failures: dict, now: int) -> int:
    """Each found sale payment must be committed on an indexer (indexer-b, indexer-a after 3 failures)
    before it counts, as for packs. Pack crediting's freeze doesn't stop this: none of the money is ours."""
    counted = 0
    for row in conn.execute("SELECT utxo_id FROM sale_payments WHERE status = 'pending_check'").fetchall():
        key = ("sale", row["utxo_id"])
        position = 1 if failures.get(key, 0) >= INDEXER_FAILOVER_AFTER and len(indexers.upstreams) > 1 else 0
        if utxo_on_indexer(indexers, row["utxo_id"], position)[0] != "ok":
            failures[key] = failures.get(key, 0) + 1
            continue
        failures.pop(key, None)
        count(conn, row["utxo_id"], now)
        counted += 1
    return counted


def count(conn: sqlite3.Connection, utxo_id: str, now: int) -> None:
    """A committed sale payment adds to its claim. Enough → `paid`; test money we built releases from there,
    anything else waits for the owner's check. A payment to a claim already paid, or closed, is `extra`:
    the owner keeps it, nothing more opens."""
    with db.tx(conn):
        pay = conn.execute("SELECT * FROM sale_payments WHERE utxo_id = ? AND status = 'pending_check'",
                           (utxo_id,)).fetchone()
        if pay is None:
            return
        claim = conn.execute("SELECT * FROM claims WHERE id = ?", (pay["claim_id"],)).fetchone()
        if claim is None or claim["status"] not in OPEN or now > claim["expires_at"] + LATE_GRACE_S:
            conn.execute("UPDATE sale_payments SET committed = 1, status = 'extra' WHERE utxo_id = ?", (utxo_id,))
            return
        conn.execute("UPDATE sale_payments SET committed = 1, status = 'counted' WHERE utxo_id = ?", (utxo_id,))
        received = claim["received_ut"] + pay["value_ut"]           # an overpayment counts in full
        if received < claim["price_ut"]:
            conn.execute("UPDATE claims SET received_ut = ?, status = ? WHERE id = ?",
                         (received, "seen" if now <= claim["expires_at"] else "underpaid", claim["id"]))
            return
        conn.execute("UPDATE claims SET received_ut = ?, status = 'paid', paid_at = ?, "
                     "owner_check = CASE WHEN demo = 1 THEN 'none' ELSE 'pending' END WHERE id = ?",
                     (received, now, claim["id"]))


def demo_payload_ok(conn: sqlite3.Connection, payload: dict, now: int) -> bool:
    """The worker's guard for a demo payment to a claim (ref `clm_…`): the claim still waits for money on
    a live link, the address is that link owner's sales address with this claim's reference, the seller's
    view key opened, and the amount is no more than what is missing (and our per-claim cap). A compromised
    API can't steer test money anywhere else."""
    claim = conn.execute("SELECT c.*, s.state AS share_state, i.owner_id AS owner_id FROM claims c "
                         "JOIN shares s ON s.id = c.share_id JOIN items i ON i.id = s.item_id WHERE c.id = ?",
                         (payload["ref"],)).fetchone()
    if claim is None or claim["status"] not in OPEN or now > claim["expires_at"] + LATE_GRACE_S \
            or claim["share_state"] != "active":
        return False
    seller = conn.execute("SELECT * FROM sellers WHERE identity_id = ?", (claim["owner_id"],)).fetchone()
    if seller is None or seller["state"] != "ok":
        return False
    if payload["address"] != ootle_addr.with_pay_ref(seller["address"], claim["id"].encode()):
        return False
    return int(payload["amount_ut"]) <= min(claim["price_ut"] - claim["received_ut"], DEMO_MAX_UT)


def mark_demo(conn: sqlite3.Connection, claim_id: str, amount_ut: int) -> None:
    """Our demo wallet's payment committed. Only a payment of the whole price makes the claim test money
    (spendable by the owner by construction); a top-up of someone else's partial payment doesn't."""
    with db.tx(conn):
        conn.execute("UPDATE claims SET demo = 1, owner_check = 'none' WHERE id = ? AND price_ut = ? "
                     "AND owner_check IN ('none','pending')", (claim_id, amount_ut))
