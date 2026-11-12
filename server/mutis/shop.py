# SPDX-License-Identifier: MIT
"""A drive's shop (docs/shop.md), behind features.shop: a public page that lists some of the drive's pay links.

What it stores is what the owner chose to publish: the shop's title and bio, and for each listed pay link a title
and one line, plus what our server already knew of that link (file or folder, its padded size, its price). The shop's
id is random (codec.new_id), never derived from the drive's id or keys. Buying goes through the pay link's own page,
unchanged (/p/<id>): a listing only points at it.

The shop's link is /shop/<username>#6<shop key> (a shop made before names: /shop/<id>#6…). The shop key never reaches us: the drive keeps it wrapped under its own
key (`key_wrap`, opened only in the owner's browser), and each listing carries the pay link's own half of its key
(`sA`, the part after a /p/ link's #) sealed with it (`link_ct`). So a copy of our database, which holds `sB` for every
pay link, still can't put the two halves of a listed link together; whoever holds the shop's whole link can.

The address (docs/shop.md "The address"): the owner picks a username (`username()`: ASCII a-z, 0-9 and single hyphens,
3 to 30 characters, case-folded, never a reserved word or a look-alike of the brand or of another shop). A private shop
(the default) answers only to its read token, HKDF(shop key, "mutis/v2", "shop-read"), so its name alone shows
nothing. A public shop answers to anyone, its page is server-rendered for search engines (shop_page.py) and its listings
are in the market (market.py); its key still never reaches us, so a visitor without the shop's whole link asks the
seller's drive for a listing's key half instead (docs/market.md). Going private again keeps the key, which was never
ours.

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

# A shop's address (docs/shop.md "The address").
USERNAME_MIN, USERNAME_MAX = 3, 30
_USERNAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)
_ASCII_NAME = re.compile(r"[A-Za-z0-9-]+", re.ASCII)
TOKEN_LEN = 32
HOLD_S = 30 * 86400          # a name given up stays its drive's this long
READ_INFO = b"shop-read"
V2_SALT = b"mutis/v2"
# Words that would read as us, as the service, or as one of its pages: refused as the whole name, after look-alikes
# are merged (skeleton), so "adm1n" and "st4tus" go too.
RESERVED = frozenset("""
    about abuse account accounts admin administrator alpha api app apps assets beta billing blog cdn checkout contact
    dashboard dev docs drive drop drops edit email esmeralda faq favicon fine-print help hidebox home how index info
    invoice judges legal login logout made mail mainnet me media mod moderator mutis my new news null official ootle
    owner pay payment payments press pricing privacy prod register report robots root security send settings shop shops
    signin signup sitemap staff staging static status store support system tari team terms test testnet tos undefined
    upgrade verify wallet watch well-known www
""".split())
# Words that would make a shop read as ours or as staff: refused as any part between hyphens too ("tari-official",
# "hidebox-support"), once look-alikes are merged.
IMPERSONATION = frozenset(("admin", "administrator", "hidebox", "moderator", "mutis", "official", "ootle", "security",
                           "staff", "support", "system", "tari"))
# Brand words refused anywhere inside a name, once look-alikes are merged ("myhidebox", "h1d3b0x").
BRANDS = ("hidebox", "mutis")
# Single characters first (digits that pass for letters, hyphens dropped), then the pairs that pass for one letter,
# again until nothing changes, so "c1ara" and "r-n" fold as "clara" and "rn" do.
_LOOKALIKE_CHARS = str.maketrans({"0": "o", "1": "l", "i": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "-": None})
_LOOKALIKE_PAIRS = (("rn", "m"), ("vv", "w"), ("cl", "d"))
HOLDS_PER_DRIVE = 3          # names a drive keeps held at once; an older hold lapses when it gives up another


def skeleton(name: str) -> str:
    """`name` (already a valid, folded username) with look-alike characters merged and hyphens dropped: two names
    with the same skeleton read the same, so only one shop may hold it."""
    out = name.translate(_LOOKALIKE_CHARS)
    while True:
        before = out
        for a, b in _LOOKALIKE_PAIRS:
            out = out.replace(a, b)
        if out == before:
            return out


_RESERVED_SKELETONS = frozenset(skeleton(w) for w in RESERVED)
_IMPERSONATION_SKELETONS = frozenset(skeleton(w) for w in IMPERSONATION)
_BRAND_SKELETONS = tuple(skeleton(b) for b in BRANDS)


def username(body: dict, name: str = "username") -> str:
    """A shop's username from a request: refused (422 `invalid`, details.field) unless it is a string of ASCII letters,
    digits and single hyphens, 3 to 30 characters, with no hyphen at either end. The length is checked first, before
    anything else looks at it; anything not ASCII (accents, look-alike letters from other scripts, width variants,
    bidirectional or zero-width marks, control characters, emoji) is refused, never normalized. ASCII capitals are
    folded to lower case, the only form we store. 422 `username_reserved` for a reserved word or a look-alike of one,
    or a name with the brand in it."""
    value = body.get(name)
    if not isinstance(value, str) or not USERNAME_MIN <= len(value) <= USERNAME_MAX:
        raise invalid(name, f"Use {USERNAME_MIN} to {USERNAME_MAX} letters, digits or hyphens.")
    if not value.isascii() or not _ASCII_NAME.fullmatch(value):
        raise invalid(name, "Use only the letters a to z, digits and hyphens.")
    folded = value.lower()
    if not _USERNAME.fullmatch(folded):
        raise invalid(name, "A hyphen goes between letters or digits, one at a time.")
    whole = skeleton(folded)
    parts = [skeleton(x) for x in folded.split("-")]
    if folded in RESERVED or whole in _RESERVED_SKELETONS or any(x in _IMPERSONATION_SKELETONS for x in parts) \
            or any(b in whole for b in _BRAND_SKELETONS):
        raise ApiError(422, "username_reserved", "That name is kept for the service. Pick another.",
                       details={"field": name})
    return folded


def read_token(shop_key: bytes) -> bytes:
    """What a holder of the shop key shows to read a private shop (lib/shop.js readToken)."""
    return codec.hkdf(shop_key, V2_SALT, READ_INFO, TOKEN_LEN)


def token_ok(row, token: bytes | None) -> bool:
    return row["token_hash"] is not None and token is not None and codec.equal(codec.sha256(token), row["token_hash"])


def name_free(conn: sqlite3.Connection, folded: str, identity_id: str, now: int) -> bool:
    """No other shop holds this name or a look-alike of it, no other drive's hold covers it, and it isn't the random id
    of an existing shop (an old /shop/<id> link must keep reaching its own shop)."""
    skel = skeleton(folded)
    taken = conn.execute("SELECT 1 FROM shops WHERE (username = ? OR skeleton = ? OR id = ?) AND identity_id != ?",
                         (folded, skel, folded, identity_id)).fetchone()
    held = conn.execute("SELECT 1 FROM shop_name_holds WHERE skeleton = ? AND identity_id != ? AND until > ?",
                        (skel, identity_id, now)).fetchone()
    return taken is None and held is None


def hold_name(conn: sqlite3.Connection, row, now: int) -> None:
    """The name a shop gives up (renamed, turned off) stays its drive's for HOLD_S; expired holds go."""
    conn.execute("DELETE FROM shop_name_holds WHERE until <= ?", (now,))
    if row is not None and row["skeleton"]:
        conn.execute("INSERT INTO shop_name_holds(skeleton, identity_id, until) VALUES (?, ?, ?) ON CONFLICT(skeleton) "
                     "DO UPDATE SET identity_id = excluded.identity_id, until = excluded.until",
                     (row["skeleton"], row["identity_id"], now + HOLD_S))
        # A drive can't park names: it keeps its newest few held, no more.
        conn.execute("DELETE FROM shop_name_holds WHERE identity_id = ? AND skeleton NOT IN (SELECT skeleton FROM "
                     "shop_name_holds WHERE identity_id = ? ORDER BY until DESC, skeleton LIMIT ?)",
                     (row["identity_id"], row["identity_id"], HOLDS_PER_DRIVE))


def by_ref(conn: sqlite3.Connection, ref: str):
    """The shop a /shop/<ref> address names: a username (folded) first, then, for a shop made before names, its id."""
    if isinstance(ref, str) and USERNAME_MIN <= len(ref) <= USERNAME_MAX and _USERNAME.fullmatch(ref):
        row = conn.execute("SELECT * FROM shops WHERE username = ?", (ref,)).fetchone()
        if row is not None:
            return row
    if isinstance(ref, str) and PARAM_RE["id"].match(ref):
        return conn.execute("SELECT * FROM shops WHERE id = ?", (ref,)).fetchone()
    return None


def path_of(row) -> str:
    return f"/shop/{row['username']}" if row["username"] else f"/shop/{row['id']}"


def config_block() -> dict:
    return {"max_listings": MAX_LISTINGS, "title_max": TITLE_MAX, "bio_max": BIO_MAX, "bio_lines": BIO_LINES,
            "item_title_max": ITEM_TITLE_MAX, "description_max": DESC_MAX, "username_min": USERNAME_MIN,
            "username_max": USERNAME_MAX}


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
    """A link ended (stopped, deleted, the Trash, a takedown, its file left): its listing goes with it, and the market's
    asks for it (docs/market.md)."""
    conn.execute("DELETE FROM shop_listings WHERE share_id = ?", (share_id,))
    conn.execute("DELETE FROM market_asks WHERE share_id = ?", (share_id,))


# A listing shows while its pay link sells: the link active and not past an expiry, our half of its key still here,
# its file or folder ready, outside the Trash and not past its own time to leave (Delete it after), which counts here
# before the cleanup ends the link. Both queries start from the shop's own listings (its index), whatever the size of
# the other tables: CROSS JOIN keeps SQLite's join order as written.
LIVE = ("s.state = 'active' AND (s.expires_at IS NULL OR s.expires_at > ?) AND p.server_half IS NOT NULL "
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
                        f"WHERE l.shop_id = ? AND {LIVE} AND p.paused = 0 ORDER BY l.created_at DESC, l.share_id LIMIT ?",
                        (shop_id, now, now, MAX_LISTINGS)).fetchall()
    return [listing_json(r, public=True) for r in rows]


def owner_listings(conn: sqlite3.Connection, shop_id: str, now: int) -> list:
    """Every listing of the shop, newest first, each with whether it shows now (`selling`) and `paused`."""
    rows = conn.execute("SELECT l.*, COALESCE(p.paused, 0) AS paused, "
                        f"COALESCE({LIVE} AND p.paused = 0, 0) AS selling "
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
    found = conn.execute("UPDATE shops SET state = 'removed', published_key = NULL, updated_at = ? WHERE id = ?",
                         (now, shop_id)).rowcount == 1
    conn.execute("DELETE FROM shop_listings WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM market_asks WHERE shop_id = ?", (shop_id,))
    return found


def shop_of_link(link: str, origins: list[str]) -> tuple[str, str] | None:
    """(shop ref, fragment) for a /shop/<username> or /shop/<id> link on one of our origins; None for any other link
    (POST /abuse). The ref is a folded username or an id, never anything else."""
    url = urlsplit(link.strip())
    segments = url.path.strip("/").split("/")
    if f"{url.scheme}://{url.netloc}" not in origins or url.query or len(segments) != 2 or segments[0] != "shop":
        return None
    ref = segments[1]
    if PARAM_RE["id"].match(ref):
        return ref, url.fragment
    if USERNAME_MIN <= len(ref) <= USERNAME_MAX and ref.isascii() and _USERNAME.fullmatch(ref.lower()):
        return ref.lower(), url.fragment
    return None
