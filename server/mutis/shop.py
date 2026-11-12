# SPDX-License-Identifier: MIT
"""A drive's shop (docs/shop.md), behind features.shop: a public page that lists some of the drive's pay links.

What it stores is what the owner chose to publish: the shop's title and bio, and for each listed pay link a title
and one line, plus what our server already knew of that link (file or folder, its padded size, its price). The shop's
id is random (codec.new_id), never derived from the drive's id or keys. Buying goes through the pay link's own page,
unchanged (/p/<id>): a listing only points at it.

The shop's link is /shop/<id>#6<shop key>. The shop key never reaches us: the drive keeps it wrapped under its own
key (`key_wrap`, opened only in the owner's browser), and each listing carries the pay link's own half of its key
(`sA`, the part after a /p/ link's #) sealed with it (`link_ct`). So a copy of our database, which holds `sB` for every
pay link, still can't put the two halves of a listed link together; whoever holds the shop's whole link can.

A listing shows while its pay link sells: the link active and not paused, our half of its key still here, its
file or folder ready and outside the Trash. Pausing hides it; ending the link (stopped, deleted, the Trash, a
takedown, its file leaving) deletes it (`end_for_share`, from items.end_share). Turning the shop off deletes the shop
and its listings. Callers hold a BEGIN IMMEDIATE transaction around every function that writes.
"""
import re
import sqlite3
from urllib.parse import urlsplit

from . import codec
from .http_util import PARAM_RE, ApiError, invalid

MAX_LISTINGS = 50          # listings per shop
TITLE_MAX = 60             # the shop's public name
BIO_MAX = 280              # a short bio; it may break into a few lines
BIO_LINES = 4
ITEM_TITLE_MAX = 80        # a listing's title
DESC_MAX = 140             # a listing's one line
KEY_WRAP_LEN = 60          # iv ‖ AES-GCM(32-byte key) under the drive's key
LINK_CT_LEN = 60           # iv ‖ AES-GCM(32-byte sA) under the shop's key
PUTS_PER_DAY = 30          # PUT /me/shop per drive
LISTING_WRITES_PER_HOUR = 120    # listings put or removed per drive
READS_PER_MINUTE = 120     # GET /shop/{id} per network, as a link's status
# Bidirectional embeddings, overrides, isolates and marks: they can make a name read as something it isn't.
_BIDI = re.compile("[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")


def config_block() -> dict:
    return {"max_listings": MAX_LISTINGS, "title_max": TITLE_MAX, "bio_max": BIO_MAX, "bio_lines": BIO_LINES,
            "item_title_max": ITEM_TITLE_MAX, "description_max": DESC_MAX}


def plain_text(body: dict, name: str, max_chars: int, required: bool, lines: int = 1) -> str:
    """Owner text to publish: a string of at most `max_chars` characters with no control characters (a line break only
    where `lines` > 1, at most `lines` lines) and no bidirectional overrides, trimmed. Empty is refused when
    `required`. Shown as text, never as markup or a link."""
    value = body.get(name, "" if not required else None)
    if value is None and not required:
        value = ""
    if not isinstance(value, str):
        raise invalid(name)
    value = value.strip()
    if (required and not value) or len(value) > max_chars or _BIDI.search(value):
        raise invalid(name)
    # Control characters (a line break only where lines are allowed), and lone surrogates, which JSON can carry but
    # no UTF-8 text holds.
    if any((ord(c) < 32 and not (c == "\n" and lines > 1)) or 0x7f <= ord(c) < 0xa0 or 0xd800 <= ord(c) <= 0xdfff
           for c in value):
        raise invalid(name)
    if value.count("\n") >= lines:
        raise invalid(name)
    return "\n".join(line.strip() for line in value.split("\n"))


def own_shop(conn: sqlite3.Connection, identity_id: str):
    return conn.execute("SELECT * FROM shops WHERE identity_id = ?", (identity_id,)).fetchone()


def end_for_share(conn: sqlite3.Connection, share_id: str) -> None:
    """A link ended (stopped, deleted, the Trash, a takedown, its file left): its listing goes with it."""
    conn.execute("DELETE FROM shop_listings WHERE share_id = ?", (share_id,))


# A listing shows while its pay link sells: the link active and not past an expiry, our half of its key still here,
# its file or folder ready, outside the Trash and not past its own time to leave (Delete it after), which counts here
# before the cleanup ends the link. Both queries start from the shop's own listings (its index), whatever the size of
# the other tables: CROSS JOIN keeps SQLite's join order as written.
_LIVE = ("s.state = 'active' AND (s.expires_at IS NULL OR s.expires_at > ?) AND p.server_half IS NOT NULL "
         "AND i.state = 'ready' AND i.trashed_at IS NULL AND (i.expires_at IS NULL OR i.expires_at > ?)")


def listing_json(row, public: bool) -> dict:
    out = {"share_id": row["share_id"], "title": row["title"], "description": row["description"], "kind": row["kind"],
           "size_stored": row["size_stored"], "price_ut": str(row["price_ut"]), "link_ct": codec.b64u(row["link_ct"])}
    if not public:
        out.update({"created_at": row["created_at"], "selling": bool(row["selling"]), "paused": bool(row["paused"])})
    return out


def public_listings(conn: sqlite3.Connection, shop_id: str, now: int) -> list:
    rows = conn.execute("SELECT l.* FROM shop_listings l INDEXED BY shop_listings_shop CROSS JOIN shares s ON s.id = l.share_id "
                        "CROSS JOIN paid_shares p ON p.share_id = l.share_id CROSS JOIN items i ON i.id = s.item_id "
                        f"WHERE l.shop_id = ? AND {_LIVE} AND p.paused = 0 ORDER BY l.created_at DESC, l.share_id LIMIT ?",
                        (shop_id, now, now, MAX_LISTINGS)).fetchall()
    return [listing_json(r, public=True) for r in rows]


def owner_listings(conn: sqlite3.Connection, shop_id: str, now: int) -> list:
    """Every listing of the shop, newest first, each with whether it shows now (`selling`) and `paused`."""
    rows = conn.execute("SELECT l.*, COALESCE(p.paused, 0) AS paused, "
                        f"COALESCE({_LIVE} AND p.paused = 0, 0) AS selling "
                        "FROM shop_listings l INDEXED BY shop_listings_shop LEFT JOIN shares s ON s.id = l.share_id "
                        "LEFT JOIN paid_shares p ON p.share_id = l.share_id LEFT JOIN items i ON i.id = s.item_id "
                        "WHERE l.shop_id = ? ORDER BY l.created_at DESC, l.share_id", (now, now, shop_id)).fetchall()
    return [listing_json(r, public=False) for r in rows]


def sold_link(conn: sqlite3.Connection, identity_id: str, share_id: str, now: int):
    """The drive's own pay link that a listing may point at, with its item: 404 when it isn't one, 409 `not_selling`
    when it has ended or its file or folder isn't ready (in the Trash, leaving)."""
    row = conn.execute("SELECT s.state AS share_state, s.expires_at AS share_expires, p.price_ut, p.server_half, "
                       "p.paused, i.* FROM shares s JOIN paid_shares p ON p.share_id = s.id JOIN items i "
                       "ON i.id = s.item_id WHERE s.id = ?", (share_id,)).fetchone()
    if row is None or row["owner_id"] != identity_id:
        raise ApiError(404, "not_found", "No pay link of this drive has this id.")
    live = (row["share_state"] == "active" and (row["share_expires"] is None or row["share_expires"] > now)
            and row["server_half"] is not None and row["state"] == "ready" and row["trashed_at"] is None
            and (row["expires_at"] is None or row["expires_at"] > now))
    if not live:
        raise ApiError(409, "not_selling", "This pay link has ended. Make a new one to list it.")
    return row


def takedown(conn: sqlite3.Connection, shop_id: str, now: int) -> bool:
    """The operator removes a shop (mutis-admin takedown shop): its page answers 410, its listings go, and its drive
    can't open another until the row is cleared. The title and bio stay with the record of what was removed."""
    found = conn.execute("UPDATE shops SET state = 'removed', updated_at = ? WHERE id = ?", (now, shop_id)).rowcount == 1
    conn.execute("DELETE FROM shop_listings WHERE shop_id = ?", (shop_id,))
    return found


def shop_of_link(link: str, origins: list[str]) -> tuple[str, str] | None:
    """(shop id, fragment) for a /shop/<id> link on one of our origins; None for any other link (POST /abuse)."""
    url = urlsplit(link.strip())
    segments = url.path.strip("/").split("/")
    if f"{url.scheme}://{url.netloc}" not in origins or url.query or len(segments) != 2 or segments[0] != "shop" \
            or not PARAM_RE["id"].match(segments[1]):
        return None
    return segments[1], url.fragment
