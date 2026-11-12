# SPDX-License-Identifier: MIT
"""The market (docs/market.md), behind features.market: what public shops sell, browsable and searchable, and asks.

A public shop's listings are public text already (its own page shows them). The market lists them across shops, newest
first. What it never has is a listing's half of its pay link's key (`sA`): that is sealed with the shop's key, which
stays after the `#` of the shop's link and in the owner's drive. A shopper who found a listing here asks the seller's
drive for it: the shopper's browser sends a key pair made for that ask alone, the seller's drive answers with `sA`
sealed to it (125 bytes, the address wrap of Send by Tari), and our server only relays the sealed answer. So our server
stores `sB` and sealed things, never both halves of a listed file's key; since anyone may ask, it could ask too
(docs/market.md, "Threat-model delta"). Callers hold a BEGIN IMMEDIATE transaction around every function that writes.
"""
import re
import sqlite3

from . import codec
from .http_util import invalid
from .shop import LIVE, listing_json

PAGE = 24                  # listings a page
Q_MAX = 60                 # a search's characters
Q_WORDS = 6
ASK_S = 7 * 86400          # an ask waits this long for its answer
ANSWER_KEEP_S = 7 * 86400  # an answer is kept this long for the shopper to come back to it
MAX_WAITING = 200          # unanswered asks a listing may have at once
ASKS_PER_HOUR = 30         # POST /market/asks per network
ASK_READS_PER_MINUTE = 120  # GET /market/asks/{id} per network
READS_PER_MINUTE = 60      # GET /market per network
OWNER_PAGE = 50            # asks the seller's drive fetches at a time
ANSWERS_PER_HOUR = 1200    # PUT /me/market/asks/{id} per drive
ANSWER_LEN = 125           # R ‖ iv ‖ AES-GCM(65 bytes), lib/ootle.js sealToKeys
KEY_LEN = 32
_CURSOR = re.compile(r"(\d{1,12})\.([A-Za-z0-9_-]{22})")
_LIKE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def config_block() -> dict:
    return {"page": PAGE, "q_max": Q_MAX, "ask_days": ASK_S // 86400, "answer_keep_days": ANSWER_KEEP_S // 86400,
            "max_waiting": MAX_WAITING}


def query_words(q) -> list[str]:
    """A search's words: plain text, at most Q_MAX characters and Q_WORDS words, ASCII letters folded to lower case."""
    if q is None or q == "":
        return []
    if not isinstance(q, str) or len(q) > Q_MAX or any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in q):
        raise invalid("q", f"Search with up to {Q_MAX} characters.")
    # Folded as SQLite's lower() folds the stored text: ASCII letters only, everything else as typed.
    return ["".join(c.lower() if c.isascii() else c for c in w) for w in q.split()][:Q_WORDS]


def parse_cursor(text):
    if text is None or text == "":
        return None
    m = _CURSOR.fullmatch(text) if isinstance(text, str) else None
    if not m:
        raise invalid("cursor")
    return int(m.group(1)), m.group(2)


# A listing is in the market while it shows on its public shop: the shop public, open and named, its pay link selling.
_IN_MARKET = (f"sh.mode = 'public' AND sh.state = 'open' AND sh.username IS NOT NULL AND {LIVE} AND p.paused = 0")
_FROM = ("FROM shop_listings l JOIN shops sh ON sh.id = l.shop_id JOIN shares s ON s.id = l.share_id "
         "JOIN paid_shares p ON p.share_id = l.share_id JOIN items i ON i.id = s.item_id")


def search(conn: sqlite3.Connection, words: list[str], kind: str | None, cursor, now: int) -> tuple[list, str | None]:
    """A page of what public shops sell now, newest first: each listing as its shop shows it, with the shop's name and
    address; and the cursor of the next page, or None."""
    where, args = [_IN_MARKET], [now, now]
    if kind:
        where.append("l.kind = ?")
        args.append(kind)
    for word in words:
        pattern = "%" + word.translate(_LIKE) + "%"
        where.append("(lower(l.title) LIKE ? ESCAPE '\\' OR lower(l.description) LIKE ? ESCAPE '\\' "
                     "OR lower(sh.title) LIKE ? ESCAPE '\\')")
        args += [pattern, pattern, pattern]
    if cursor:
        where.append("(l.created_at < ? OR (l.created_at = ? AND l.share_id < ?))")
        args += [cursor[0], cursor[0], cursor[1]]
    rows = conn.execute(f"SELECT l.*, sh.username, sh.title AS shop_title {_FROM} WHERE {' AND '.join(where)} "
                        "ORDER BY l.created_at DESC, l.share_id DESC LIMIT ?", (*args, PAGE + 1)).fetchall()
    items = []
    for r in rows[:PAGE]:
        out = listing_json(r, public=True)
        out.pop("link_ct")                  # sealed with a key a market visitor doesn't have: of no use here
        out["shop"] = {"username": r["username"], "title": r["shop_title"], "path": f"/shop/{r['username']}"}
        items.append(out)
    more = len(rows) > PAGE
    return items, (f"{rows[PAGE - 1]['created_at']}.{rows[PAGE - 1]['share_id']}" if more else None)


def listing(conn: sqlite3.Connection, share_id: str, now: int):
    """The listing a shopper may ask about: in the market now. None otherwise."""
    return conn.execute(f"SELECT l.share_id, l.shop_id {_FROM} WHERE l.share_id = ? AND {_IN_MARKET}",
                        (share_id, now, now)).fetchone()


def waiting(conn: sqlite3.Connection, share_id: str, now: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM market_asks WHERE share_id = ? AND answered_at IS NULL AND expires_at > ?",
                        (share_id, now)).fetchone()[0]


def ask_json(row) -> dict:
    out = {"ask_id": row["id"], "share_id": row["share_id"], "state": "answered" if row["answer"] else "waiting",
           "expires_at": row["expires_at"] if row["answer"] is None else row["answered_at"] + ANSWER_KEEP_S}
    if row["answer"] is not None:
        out["answer"] = codec.b64u(row["answer"])
    return out


def live_ask(conn: sqlite3.Connection, ask_id: str, now: int):
    """The ask, while it waits or its answer is kept; None once it has run out."""
    row = conn.execute("SELECT * FROM market_asks WHERE id = ?", (ask_id,)).fetchone()
    if row is None:
        return None
    if row["answered_at"] is None and row["expires_at"] <= now:
        return None
    if row["answered_at"] is not None and row["answered_at"] + ANSWER_KEEP_S <= now:
        return None
    return row


def owner_asks(conn: sqlite3.Connection, shop_id: str, now: int) -> list:
    """The asks waiting for this shop's answer, oldest first, for listings still in the market."""
    rows = conn.execute("SELECT a.* FROM market_asks a JOIN shop_listings l ON l.share_id = a.share_id "
                        "WHERE a.shop_id = ? AND a.answered_at IS NULL AND a.expires_at > ? AND l.shop_id = a.shop_id "
                        "ORDER BY a.created_at, a.id LIMIT ?", (shop_id, now, OWNER_PAGE)).fetchall()
    return [{"ask_id": r["id"], "share_id": r["share_id"], "owner_pk": codec.b64u(r["owner_pk"]),
             "view_pk": codec.b64u(r["view_pk"]), "created_at": r["created_at"]} for r in rows]


def end_for_shop(conn: sqlite3.Connection, shop_id: str) -> None:
    """The shop left the market (private again, taken down): its asks end."""
    conn.execute("DELETE FROM market_asks WHERE shop_id = ?", (shop_id,))


def purge(conn: sqlite3.Connection, now: int) -> int:
    """Asks that ran out: unanswered past their time, answered past the time their answer is kept."""
    return conn.execute("DELETE FROM market_asks WHERE (answered_at IS NULL AND expires_at <= ?) "
                        "OR (answered_at IS NOT NULL AND answered_at <= ?)", (now, now - ANSWER_KEEP_S)).rowcount
