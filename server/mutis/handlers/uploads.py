# SPDX-License-Identifier: MIT
"""Uploads (spec §6.3): reserve bytes, receive ciphertext chunks with their SHA-256, complete.

Admission (class limits, lanes, freeze, quota) and the byte reservation happen in one
BEGIN IMMEDIATE transaction, so concurrent uploads can never overshoot a limit (S-04).
"""
import os
import struct

from .. import codec, db, items, lanes, quota, seallog
from ..http_util import ApiError, Response, get_b64, get_enum, get_int, invalid, json_response
from .drops import active_drop

UPLOAD_TTL_S = 7200
ANON_SMALL_PER_HOUR = 30          # per ip64, files ≤ 5 MiB (spec §6.2)
ANON_LARGE_PER_HOUR = 10          # per ip64, files of 5–25 MiB
META_LENGTHS = {12 + 256 * k + 16 for k in range(1, 9)}
SMALL_AT_ONCE_PER_48 = 100 * quota.MiB
DROP_FILES_PER_DAY = 50
DROP_BYTES_PER_DAY = 1 * quota.GiB


def _check_header(header: bytes, chunk_count: int) -> None:
    magic, version, chunk_log2, flags, count, reserved = struct.unpack(">4sBBHII", header[:16])
    if magic != b"MTS1" or version != 1 or chunk_log2 != 22 or flags != 0 or reserved != 0 or count != chunk_count:
        raise invalid("header")


def _anon_rules(ctx, lane: str, size: int) -> list:
    mb = quota.MiB
    if lane == "drop":
        return [("up_drop64", ctx.ip64, 10, 3600, 1), ("up_drop64b", ctx.ip64, 250 * mb, 86400, size),
                ("up_drop48", ctx.ip48, 30, 3600, 1)]
    if lane == "small":
        return [("up_small64", ctx.ip64, ANON_SMALL_PER_HOUR, 3600, 1), ("up_small64b", ctx.ip64, 150 * mb, 86400, size),
                ("up_small48", ctx.ip48, 90, 3600, 1), ("up_small48b", ctx.ip48, 400 * mb, 86400, size)]
    return [("up_anon64", ctx.ip64, ANON_LARGE_PER_HOUR, 3600, 1), ("up_anon64b", ctx.ip64, 500 * mb, 86400, size),
            ("up_anon48", ctx.ip48, 30, 3600, 1), ("up_anon48b", ctx.ip48, 1536 * mb, 86400, size),
            ("up_anon_all", "all", 6 * quota.GiB, 86400, size)]


def _small_at_once(ctx, size: int) -> None:
    """Per /48 (or /24), at most 100 MiB of SMALL-lane ciphertext stored at once (memory only)."""
    held = ctx.app.small_held.get(ctx.ip48, {})
    if held:
        marks = ",".join("?" * len(held))
        live = {r[0] for r in ctx.db.execute(f"SELECT id FROM items WHERE id IN ({marks}) "
                                             "AND state IN ('uploading','ready')", list(held))}
        gone = set(held) - live
        held = ctx.app.small_held.update(ctx.ip48, lambda table: {k: v for k, v in table.items() if k not in gone}, {})
    if sum(held.values()) + size > SMALL_AT_ONCE_PER_48:
        raise ApiError(429, "rate_limited", "Your network has a lot stored right now. Try again later.",
                       retry_after=3600)


def _remember_small(ctx, item_id: str, size: int) -> None:
    ctx.app.small_held.update(ctx.ip48, lambda held: {**held, item_id: size}, {})


def create(ctx):
    body = ctx.req.json()
    now = ctx.now
    canary = ctx.is_canary()
    drop_id = body.get("drop_id")
    identity = None if canary or drop_id is not None else ctx.session(required=False)
    retention = get_enum(body, "retention", ("ephemeral", "kept"))
    header = get_b64(body, "header", 32)
    meta_ct = get_b64(body, "meta_ct", max_len=2048 + 28)
    if len(meta_ct) not in META_LENGTHS:
        raise invalid("meta_ct")
    chunk_count = get_int(body, "chunk_count", 1, 1 << 20)
    size = get_int(body, "size_stored", 1, 1 << 42)
    if not quota.valid_layout(size, chunk_count):
        raise invalid("size_stored")
    _check_header(header, chunk_count)
    owner_wrap = get_b64(body, "owner_wrap", 60, optional=True)
    expires_at = get_int(body, "expires_at", 0, 1 << 40, optional=True)

    rules, pow_purpose, drop = [], None, None
    if canary:
        lane = "small"
        if retention != "ephemeral" or expires_at is None or not now < expires_at <= now + quota.CANARY_MAX_EXPIRY_S:
            raise invalid("expires_at")
        lanes.check_file_size("anon", size)
    elif identity is None:
        if retention != "ephemeral" or owner_wrap is not None:
            raise ApiError(401, "auth_required", "Keeping a file needs a locker.")
        if drop_id is not None:
            lane = "drop"
            if not isinstance(drop_id, str):
                raise invalid("drop_id")
            drop = active_drop(ctx.db, drop_id)
            if expires_at is None or abs(expires_at - (now + quota.CLASSES["drop"]["expiry_s"])) > 60:
                raise invalid("expires_at", "Drop deliveries expire in exactly 7 days.")
        else:
            lane = lanes.lane_for_anonymous(size)
            expires_at = expires_at or now + quota.CLASSES["anon"]["default_expiry_s"]
            if not now < expires_at <= now + quota.CLASSES["anon"]["max_expiry_s"] + 60:
                raise invalid("expires_at")
        lanes.check_file_size("drop" if lane == "drop" else "anon", size)
        rules, pow_purpose = _anon_rules(ctx, lane, size), "upload"
    else:
        lane, cls = "locker", quota.class_of(identity, now)
        lanes.check_file_size(cls, size)
        if retention == "kept":
            ctx.require_feature("kept")
            if owner_wrap is None or expires_at is not None:
                raise invalid("owner_wrap" if owner_wrap is None else "expires_at")
        else:
            if owner_wrap is not None:
                raise invalid("owner_wrap")
            expires_at = expires_at or now + quota.CLASSES[cls]["default_expiry_s"]
            if not now < expires_at <= now + quota.CLASSES[cls]["max_expiry_s"] + 60:
                raise invalid("expires_at")
        rules = [("up_locker64", ctx.ip64, 120, 3600, 1), ("up_locker", identity["id"], 60, 3600, 1)]

    with ctx.charged(*rules):
        if lane == "small" and not canary:
            _small_at_once(ctx, size)
        if pow_purpose:
            ctx.proof_of_work(pow_purpose, body)
        item_id, upload_id, manage = _admit(ctx, lane, canary, identity, drop, size, chunk_count, header, meta_ct,
                                            owner_wrap, retention, expires_at)
    if lane == "small" and not canary:
        _remember_small(ctx, item_id, size)
    return json_response(201, {"upload_id": upload_id, "item_id": item_id, "manage_token": codec.b64u(manage),
                               "expires_at": now + UPLOAD_TTL_S})


def _admit(ctx, lane, canary, identity, drop, size, chunk_count, header, meta_ct, owner_wrap, retention, expires_at):
    """Freeze, lane or quota checks, the byte reservation and the rows, in one write transaction."""
    conn, now = ctx.db, ctx.now
    item_id, upload_id, manage = codec.new_id(), codec.new_id(), os.urandom(32)
    pool = quota.measure(conn, ctx.app.statvfs, ctx.cfg.data_dir, ctx.cfg["limits"], now)
    with db.tx(conn):
        frozen = lanes.freeze_state(conn, pool)
        if identity is not None:
            identity = conn.execute("SELECT * FROM identities WHERE id = ?", (identity["id"],)).fetchone()
            lanes.admit_locker(conn, pool, identity, size, frozen, now)
            conn.execute("UPDATE identities SET reserved_bytes = reserved_bytes + ? WHERE id = ?",
                         (size, identity["id"]))
        else:
            lanes.admit_lane(conn, pool, lane, size, frozen)
        if drop is not None:
            _count_drop(conn, drop["id"], size, now)
        conn.execute("INSERT INTO items(id, owner_id, manage_hash, retention, lane, canary, state, header, meta_ct, "
                     "owner_wrap, chunk_count, size_stored, created_hour, expires_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, 'uploading', ?, ?, ?, ?, ?, ?, ?)",
                     (item_id, identity["id"] if identity else None, codec.sha256(manage), retention, lane,
                      int(canary), header, meta_ct, owner_wrap, chunk_count, size, codec.floor_hour(now), expires_at))
        conn.execute("INSERT INTO uploads(id, item_id, owner_id, lane, reserved, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (upload_id, item_id, identity["id"] if identity else None, lane, size, now + UPLOAD_TTL_S))
        try:
            ctx.app.blobs.create_part(item_id, size)
        except OSError:
            raise ApiError(503, "uploads_frozen", "The disk is full.", details={"scope": "all"}) from None
    return item_id, upload_id, manage


def _count_drop(conn, drop_id: str, size: int, now: int) -> None:
    today = codec.day(now)
    row = conn.execute("SELECT day, files_today, bytes_today FROM drops WHERE id = ?", (drop_id,)).fetchone()
    files, used = (row["files_today"], row["bytes_today"]) if row["day"] == today else (0, 0)
    if files + 1 > DROP_FILES_PER_DAY or used + size > DROP_BYTES_PER_DAY:
        raise ApiError(429, "rate_limited", "This drop took all it can today.",
                       retry_after=codec.next_utc_midnight(now) - now)
    conn.execute("UPDATE drops SET day = ?, files_today = ?, bytes_today = ? WHERE id = ?",
                 (today, files + 1, used + size, drop_id))


def _upload(ctx, upload_id: str):
    row = ctx.db.execute("SELECT u.id AS upload_id, u.expires_at AS upload_expires, i.* FROM uploads u "
                         "JOIN items i ON i.id = u.item_id WHERE u.id = ?", (upload_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No such upload.")
    if row["state"] == "ready":
        raise ApiError(409, "already_complete", "This upload is already complete.")
    if row["state"] != "uploading" or row["upload_expires"] <= ctx.now:
        raise ApiError(410, "upload_expired", "This upload expired. Start again.")
    return row


def put_chunk(ctx, upload_id: str, index: str):
    ctx.limit(("chunk64", ctx.ip64, 2000, 3600, 1), ("chunk48", ctx.ip48, 6000, 3600, 1))
    row = _upload(ctx, upload_id)
    idx = int(index)
    if idx >= row["chunk_count"]:
        raise ApiError(400, "bad_index", "No chunk with that index.")
    expected = quota.chunk_length(row["size_stored"], row["chunk_count"], idx)
    if not ctx.req.has_length or ctx.req.content_length != expected or ctx.req.headers.get("Transfer-Encoding"):
        raise ApiError(400, "bad_length", "Wrong chunk length.", details={"expected": expected})
    try:
        claimed = codec.unb64u(ctx.req.header("X-Mutis-Chunk-SHA256") or "", 32)
    except ValueError:
        raise ApiError(400, "bad_request", "Send X-Mutis-Chunk-SHA256.") from None
    digest = ctx.app.blobs.write_at(row["id"], idx * (quota.CHUNK + quota.TAG), ctx.req.body_slices(expected))
    if not codec.equal(digest, claimed):
        # The bytes on disk changed, so an earlier good copy of this chunk no longer counts.
        with db.tx(ctx.db):
            ctx.db.execute("DELETE FROM chunks WHERE item_id = ? AND idx = ?", (row["id"], idx))
        raise ApiError(422, "hash_mismatch", "The chunk doesn't match its hash.")
    with db.tx(ctx.db):
        ctx.db.execute("INSERT INTO chunks(item_id, idx, sha256) VALUES (?, ?, ?) "
                       "ON CONFLICT(item_id, idx) DO UPDATE SET sha256 = excluded.sha256", (row["id"], idx, digest))
    return Response(204)


def complete(ctx, upload_id: str):
    ctx.req.json(required=False)
    row = _upload(ctx, upload_id)
    hashes = ctx.db.execute("SELECT idx, sha256 FROM chunks WHERE item_id = ? ORDER BY idx", (row["id"],)).fetchall()
    have = {h["idx"] for h in hashes}
    missing = [i for i in range(row["chunk_count"]) if i not in have]
    if missing:
        raise ApiError(409, "missing_chunks", "Some chunks haven't arrived.", details={"missing": missing[:100]})
    ct_hash = codec.sha256(*(h["sha256"] for h in hashes))
    ctx.app.blobs.finalize(row["id"])
    with db.tx(ctx.db):
        ctx.db.execute("UPDATE items SET state = 'ready', ct_hash = ? WHERE id = ? AND state = 'uploading'",
                       (ct_hash, row["id"]))
        ctx.db.execute("UPDATE uploads SET reserved = 0 WHERE id = ?", (upload_id,))
        if row["owner_id"]:
            ctx.db.execute("UPDATE identities SET reserved_bytes = MAX(0, reserved_bytes - ?), "
                           "used_bytes = used_bytes + ? WHERE id = ?", (row["size_stored"], row["size_stored"],
                                                                       row["owner_id"]))
        seallog.append(ctx.db, "stored", seallog.stored_leaf(row["id"], ct_hash))
        if not row["canary"]:
            db.set_meta(ctx.db, "last_sealed_at", str(ctx.now))
    return json_response(200, {"item_id": row["id"], "ct_hash": codec.b64u(ct_hash), "size_stored": row["size_stored"]})


def abort(ctx, upload_id: str):
    row = _upload(ctx, upload_id)
    with db.tx(ctx.db):
        items.unlink(ctx.db, ctx.app.blobs, row["id"], "deleted", ctx.now)
    return Response(204)
