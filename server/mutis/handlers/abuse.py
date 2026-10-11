# SPDX-License-Identifier: MIT
"""POST /abuse (spec §6.3 Abuse). The operator acts with `mutis-admin takedown` (spec §15.7).

The browser strips the link's key unless the reporter chose to include it; when it's included we
keep it with the report so the operator can look at the content, and the report says so.
"""
from urllib.parse import urlsplit

from .. import codec, db
from ..http_util import PARAM_RE, get_enum, get_str, invalid, json_response

CATEGORIES = ("csam", "malware", "phishing", "copyright", "harassment", "other")


def parse_link(link: str, origins: list[str]) -> tuple[str | None, str | None, str]:
    """→ (share_id, drop_id, fragment) for a mutis /s/ or /d/ link on one of our origins."""
    parts = urlsplit(link.strip())
    if f"{parts.scheme}://{parts.netloc}" not in origins or parts.query:
        raise invalid("link", "Paste a mutis link.")
    segments = parts.path.strip("/").split("/")
    if len(segments) == 2 and segments[0] == "s" and PARAM_RE["id"].match(segments[1]):
        return segments[1], None, parts.fragment
    if len(segments) == 2 and segments[0] == "d" and PARAM_RE["drop"].match(segments[1]):
        return None, segments[1], ""
    raise invalid("link", "Paste a mutis link.")


def report(ctx):
    body = ctx.req.json()
    ctx.limit(("abuse64", ctx.ip64, 10, 3600, 1))
    share_id, drop_id, fragment = parse_link(get_str(body, "link", 600), list(ctx.cfg["memo_origins"]))
    category = get_enum(body, "category", CATEGORIES)
    details = get_str(body, "details", 2000)
    contact = get_str(body, "contact", 200, optional=True) or None
    ctx.proof_of_work("report", body)
    if fragment:
        details += f"\n\n[Reporter included the link key: #{fragment[:200]}]"
    item_id = None
    if share_id:
        row = ctx.db.execute("SELECT item_id FROM shares WHERE id = ?", (share_id,)).fetchone()
        item_id = row["item_id"] if row else None
    report_id = codec.report_id()
    with db.tx(ctx.db):
        ctx.db.execute("INSERT INTO abuse_reports(id, share_id, item_id, drop_id, category, details, contact, "
                       "included_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (report_id, share_id, item_id, drop_id, category, details, contact, int(bool(fragment)),
                        ctx.now))
    return json_response(201, {"report_id": report_id})

