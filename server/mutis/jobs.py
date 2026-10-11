# SPDX-License-Identifier: MIT
"""The job queue between the API (writes) and the chain worker (executes), spec §10.4.

Payloads hold only what the send needs and are scrubbed to NULL when a job ends, so a destination
address lives in the database only while its delivery is pending. A job is `sending` from its claim
until its transaction settles; once submitted, its `result` holds `{"pending_tx"}` so a restart waits
for that transaction instead of sending again.
"""
import json
import re
import sqlite3

from . import budgets, codec, db, ootle_addr

KINDS = ("courier", "decoy", "demo_pay", "sponsor")
MAX_ATTEMPTS = 3
BACKOFF_S = (10, 60)
MEMO_MAX_BYTES = 253
DEMO_PAY_MAX_UT = 2_000_000
SLICE_ORDER = "CASE slice WHEN 'evidence' THEN 0 WHEN 'reserved' THEN 1 ELSE 2 END"


class PayloadError(Exception):
    pass


def memo_regex(origins: list[str]) -> re.Pattern:
    alternatives = "|".join(re.escape(o) for o in origins)
    return re.compile(rf"^(?:{alternatives})/t#[34][A-Za-z0-9_-]{{167}}$")


def courier_memo(origin: str, kind: int, blob: bytes) -> str:
    """The only memo text our wallet ever sends (spec §4.10): built here, never taken from a client."""
    return f"{origin}/t#{kind}{codec.b64u(blob)}"


def enqueue(conn: sqlite3.Connection, kind: str, slice_: str, payload: dict, not_before: int, now: int,
            evidence: bool = False) -> str:
    job_id = codec.new_id()
    conn.execute("INSERT INTO jobs(id, kind, slice, evidence, payload, state, not_before, created_at, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                 (job_id, kind, slice_, int(evidence), json.dumps(payload, separators=(",", ":")), not_before, now, now))
    return job_id


def cost(kind: str, payload: dict, sponsor_grant_ut: int) -> int:
    if kind in ("courier", "decoy"):
        return 1
    if kind == "demo_pay":
        return int(payload["amount_ut"])
    return sponsor_grant_ut


def validate(kind: str, payload: dict, memo_origins: list[str]) -> dict:
    """The worker's re-check of every payload field (spec §10.4). Raises PayloadError."""
    if not isinstance(payload, dict):
        raise PayloadError()

    def address(value, pay_ref: bool = False) -> str:
        try:
            _, _, ref = ootle_addr.parse_testnet(value)
        except (ValueError, TypeError, AttributeError):
            raise PayloadError() from None
        if bool(ref) != pay_ref:
            raise PayloadError()
        return value

    if kind == "courier":
        memo = payload.get("memo")
        if set(payload) != {"address", "memo"} or not isinstance(memo, str) \
                or len(memo.encode()) > MEMO_MAX_BYTES or not memo_regex(memo_origins).match(memo):
            raise PayloadError()
        return {"address": address(payload["address"]), "memo": memo}
    if kind == "decoy":
        if payload:
            raise PayloadError()
        return {}
    if kind == "demo_pay":
        amount, ref = payload.get("amount_ut"), payload.get("ref")
        if set(payload) != {"address", "amount_ut", "ref"} or not isinstance(amount, str) or not amount.isdigit() \
                or not 0 < int(amount) <= DEMO_PAY_MAX_UT or not isinstance(ref, str):
            raise PayloadError()
        addr = address(payload["address"], pay_ref=True)
        if ootle_addr.parse_testnet(addr)[2] != ref.encode():
            raise PayloadError()
        return {"address": addr, "amount_ut": amount, "ref": ref}
    if kind == "sponsor":
        if set(payload) != {"address"}:
            raise PayloadError()
        return {"address": address(payload["address"])}
    raise PayloadError()


def claim(conn: sqlite3.Connection, cfg_budgets: dict, sponsor_grant_ut: int, now: int) -> sqlite3.Row | None:
    """Take the next due job (evidence, then reserved, then public) and charge its budget slice in the
    same transaction. A retry was charged on its first claim.

    A job whose slice is spent fails with `budget_exhausted` (payload scrubbed) and the next one is tried.
    """
    with db.tx(conn):
        while True:
            row = conn.execute("SELECT * FROM jobs WHERE state = 'queued' AND not_before <= ? "
                               f"ORDER BY {SLICE_ORDER}, not_before LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            if row["attempts"] > 0:
                break
            try:
                price = cost(row["kind"], json.loads(row["payload"] or "{}"), sponsor_grant_ut)
            except (KeyError, ValueError, TypeError):
                price = None
            if price is not None and budgets.has_room(conn, cfg_budgets, row["kind"], row["slice"], price, now):
                budgets.charge(conn, row["kind"], row["slice"], price, now)
                break
            conn.execute("UPDATE jobs SET state = 'failed', payload = NULL, error = ?, updated_at = ? WHERE id = ?",
                         ("budget_exhausted" if price is not None else "invalid_payload", now, row["id"]))
        return conn.execute("UPDATE jobs SET state = 'sending', attempts = attempts + 1, updated_at = ? "
                            "WHERE id = ? RETURNING *", (now, row["id"])).fetchone()


def mark_submitted(conn: sqlite3.Connection, job_id: str, tx_id: str, now: int) -> None:
    """Record the transaction before waiting for it: from here on the job is never sent again."""
    with db.tx(conn):
        conn.execute("UPDATE jobs SET result = ?, updated_at = ? WHERE id = ?",
                     (json.dumps({"pending_tx": tx_id}, separators=(",", ":")), now, job_id))


def pending_tx(job: sqlite3.Row) -> str | None:
    return json.loads(job["result"]).get("pending_tx") if job["state"] == "sending" and job["result"] else None


def submitted(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE state = 'sending' AND result IS NOT NULL "
                        "ORDER BY updated_at").fetchall()


def recover(conn: sqlite3.Connection, now: int) -> int:
    """At worker start: a job claimed but not recorded as submitted may or may not have reached walletd.
    It fails as `interrupted` (the UI offers Try again) rather than risk a second payment."""
    with db.tx(conn):
        return conn.execute("UPDATE jobs SET state = 'failed', payload = NULL, error = 'interrupted', updated_at = ? "
                            "WHERE state = 'sending' AND result IS NULL", (now,)).rowcount


def finish(conn: sqlite3.Connection, job_id: str, result: dict, now: int) -> None:
    with db.tx(conn):
        conn.execute("UPDATE jobs SET state = 'done', payload = NULL, result = ?, error = NULL, updated_at = ? "
                     "WHERE id = ?", (json.dumps(result, separators=(",", ":")), now, job_id))


def fail(conn: sqlite3.Connection, job: sqlite3.Row, error: str, now: int, retry: bool = True) -> None:
    """Retry with backoff, or end the job as failed after the last attempt (payload scrubbed).

    Only a job that sent nothing may be retried: never one whose transaction is still pending.
    """
    with db.tx(conn):
        if retry and job["attempts"] < MAX_ATTEMPTS:
            delay = BACKOFF_S[min(job["attempts"], len(BACKOFF_S)) - 1]
            conn.execute("UPDATE jobs SET state = 'queued', not_before = ?, error = ?, result = NULL, updated_at = ? "
                         "WHERE id = ?", (now + delay, error, now, job["id"]))
        else:
            conn.execute("UPDATE jobs SET state = 'failed', payload = NULL, result = NULL, error = ?, updated_at = ? "
                         "WHERE id = ?", (error, now, job["id"]))


def public_view(row: sqlite3.Row) -> dict:
    """GET /jobs/{id}: never an address, never a payload."""
    result = None
    if row["state"] == "done" and row["result"]:
        tx_id = json.loads(row["result"]).get("tx_id")
        result = {"tx_id": tx_id} if tx_id else None
    error = row["error"] if row["state"] == "failed" else None
    return {"kind": row["kind"], "state": row["state"], "not_before": row["not_before"], "result": result,
            "error": error}
