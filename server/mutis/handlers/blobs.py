# SPDX-License-Identifier: MIT
"""GET /blobs/{ticket} (Range, streamed in 64 KiB writes) and POST /blobs/{ticket}/done (spec §6.3)."""
import re

from .. import codec, db, items
from ..http_util import ApiError, Response

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """One `bytes=` range → (start, end) inclusive, None for the whole body. Raises 416."""
    if header is None:
        return None
    m = _RANGE.match(header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        raise ApiError(416, "bad_request", "Unsupported range.")
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    else:
        suffix = int(m.group(2))
        start, end = max(0, size - suffix), size - 1
    if start >= size or end < start:
        raise ApiError(416, "bad_request", "Range not satisfiable.")
    return start, end


def ranged(ctx, item_id: str, size: int, filename: str, cache: str, charge=None) -> Response:
    """Stream an item's ciphertext, honouring a Range header. `charge(length)` may refuse with an ApiError."""
    span = parse_range(ctx.req.header("Range"), size)
    start, end = span if span else (0, size - 1)
    length = end - start + 1
    if charge:
        charge(length)
    headers = {"Content-Type": "application/octet-stream", "Accept-Ranges": "bytes", "Cache-Control": cache,
               "Content-Disposition": f'attachment; filename="{filename}"'}
    if span:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    blobs = ctx.app.blobs
    return Response(206 if span else 200, headers=headers, length=length,
                    stream=lambda: blobs.read_range(item_id, start, length))


def _ticket(ctx, ticket: str):
    try:
        token = codec.unb64u(ticket, 32)
    except ValueError:                    # 43 base64url characters that don't encode 32 bytes canonically
        token = None
    row = ctx.db.execute("SELECT * FROM tickets WHERE token_hash = ?", (codec.sha256(token),)).fetchone() \
        if token else None
    if row is None or row["done"] or row["expires_at"] <= ctx.now:
        raise ApiError(404, "not_found", "This download has ended.")
    return row


def download(ctx, ticket: str):
    ctx.limit(("blob64", ctx.ip64, 300, 60, 1))
    row = _ticket(ctx, ticket)
    item = ctx.db.execute("SELECT id, state, size_stored FROM items WHERE id = ?", (row["item_id"],)).fetchone()
    if item is None or item["state"] not in ("ready", "doomed") or not ctx.app.blobs.exists(item["id"]):
        raise ApiError(404, "not_found", "This download has ended.")

    def charge(length: int) -> None:
        with db.tx(ctx.db):
            cur = ctx.db.execute("UPDATE tickets SET bytes_served = bytes_served + ? "
                                 "WHERE token_hash = ? AND bytes_served + ? <= max_bytes",
                                 (length, row["token_hash"], length))
        if cur.rowcount != 1:
            raise ApiError(429, "byte_cap", "This download used its byte allowance.")

    return ranged(ctx, item["id"], item["size_stored"], "sealed.bin", "no-store", charge)


def done(ctx, ticket: str):
    """End a ticket early; a doomed item with no other ticket loses its ciphertext right away."""
    row = _ticket(ctx, ticket)
    with db.tx(ctx.db):
        ctx.db.execute("UPDATE tickets SET done = 1 WHERE token_hash = ?", (row["token_hash"],))
        items.unlink_if_unreferenced(ctx.db, ctx.app.blobs, row["item_id"], ctx.now)
    return Response(204)
