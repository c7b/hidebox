# SPDX-License-Identifier: MIT
"""A shop's page (/shop/<ref>, docs/shop.md "The address"), the market's (/market, docs/market.md) and the sitemap of
public shops, behind features.shop (and features.market for /market).

Every /shop/<ref> page is the release's own app/shop.html (cfg `site_dir`, the built site; SRI, fingerprinted names and
the content security policy unchanged). For a private shop, an unknown name, a removed shop or anything else it is that
file byte for byte, `noindex`: the page opens the shop in the browser with the key after its #, and nothing here says
whether a private shop of that name exists. For a public shop (and not on a staging rehearsal) our server fills in what
anyone may read: the title, description, canonical address, OpenGraph and Twitter card text, structured data that says
only what is true (a page that lists things, their names), and the listings themselves (title, line, file or folder,
price) inside <main>, so search engines and readers without JavaScript see them; the app then draws the page as usual.

Every piece of the owner's text is escaped for where it lands: HTML text and attribute values (esc(), quotes
included), JSON-LD (JSON with <, > and & as \\u escapes and no character outside ASCII), one line in meta tags. The
address is built from the stored username, which is ASCII a-z, 0-9 and hyphens by construction (shop.username), and
quoted again anyway. When the template doesn't have exactly the anchors this fills, the page goes out unfilled
(noindex) rather than half-filled.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from . import logsafe, market, network as networks, shop
from .http_util import ApiError, Response

BRAND = "hidebox"
PAGE = "app/shop.html"
NOINDEX = "noindex, nofollow"
INDEX = "index, follow"
SITEMAP_MAX = 5000
SITEMAP_PER_MINUTE = 10     # per network: one query, but over every public shop
DESC_MAX = 155
_template: dict = {}


class TemplateError(Exception):
    pass


def template(site_dir: str) -> str | None:
    """The release's app/shop.html, read again when it changes (a release switches `current`)."""
    path = Path(site_dir) / PAGE
    try:
        st = path.stat()
        key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
        hit = _template.get("page")
        if hit is not None and hit[0] == key:
            return hit[1]
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    _template["page"] = (key, text)
    return text


def esc(text: str) -> str:
    """HTML text or a quoted attribute value: &, <, >, " and ' escaped (what html.escape does; that module is one of the
    parsers the API never imports, test_uploads_inert.py)."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#x27;"))


def one_line(text: str, limit: int | None = None) -> str:
    out = " ".join(text.split())
    if limit is not None and len(out) > limit:
        out = out[:limit - 1].rstrip() + "…"
    return out


def ld_json(obj) -> str:
    """JSON for a <script type="application/ld+json"> block: nothing in it can close the element or start markup."""
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def amount(ut: int) -> str:
    whole, frac = divmod(int(ut), 1_000_000)
    return f"{whole}.{frac:06d}".rstrip("0") if frac else str(whole)


def _one(pattern: str, repl: str, text: str, flags: int = 0) -> str:
    new, n = re.subn(pattern, lambda _m: repl, text, count=2, flags=flags)
    if n != 1:
        raise TemplateError(pattern)
    return new


def _meta(text: str, attr: str, name: str, value: str) -> str:
    return _one(rf'<meta {attr}="{re.escape(name)}" content="[^"]*">', f'<meta {attr}="{name}" content="{esc(value)}">',
                text)


def render_public(page: str, row, items: list, origin: str, coin: str) -> str:
    """The template filled for a public shop. Raises TemplateError when an anchor is missing or doubled."""
    canonical = f"{origin}/shop/{quote(row['username'], safe='')}"
    title = one_line(row["title"])
    count = len(items)
    things = "1 thing" if count == 1 else f"{count} things"
    description = one_line(row["bio"], DESC_MAX) if row["bio"] else f"{things} for sale on {BRAND}, paid with Tari."
    out = _one(r'<meta name="robots" content="noindex, nofollow">', f'<meta name="robots" content="{INDEX}">', page)
    out = _one(r"<title>[^<]*</title>", f"<title>{esc(title)} · {BRAND}</title>", out)
    out = _meta(out, "name", "description", description)
    for attr, name in (("property", "og:title"), ("name", "twitter:title")):
        out = _meta(out, attr, name, title)
    for attr, name in (("property", "og:description"), ("name", "twitter:description")):
        out = _meta(out, attr, name, description)
    data = {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "description": description,
            "url": canonical, "isPartOf": {"@type": "WebSite", "name": BRAND, "url": origin},
            "mainEntity": {"@type": "ItemList", "numberOfItems": count,
                           "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": one_line(it["title"])}
                                               for i, it in enumerate(items)]}}
    head = (f'<link rel="canonical" href="{esc(canonical)}">\n<meta property="og:url" content="{esc(canonical)}">\n'
            f'<script type="application/ld+json">{ld_json(data)}</script>\n</head>')
    out = _one(r"</head>", head, out)
    return _one(r'(?s)<main id="main" class="container a-main" tabindex="-1">.*?</main>',
                '<main id="main" class="container a-main" tabindex="-1">' + body(row, items, coin) + "</main>", out)


def body(row, items: list, coin: str) -> str:
    """The shop as text inside <main>, for readers without JavaScript and for search engines; the app replaces it."""
    parts = ['<div class="shop" data-ssr="1"><header class="shop-head">',
             '<span class="badge" data-variant="secondary">Shop</span>',
             f'<h1 class="h1 shop-own-text">{esc(row["title"])}</h1>']
    if row["bio"]:
        parts.append(f'<div class="shop-bio shop-own-text">{esc(row["bio"])}</div>')
    parts.append("<p class=\"small muted\">Its owner wrote this page. The server doesn't check it.</p></header>")
    if items:
        count = len(items)
        parts.append('<section class="shop-list" aria-labelledby="shop-list-h">'
                     f'<h2 class="h4" id="shop-list-h">{"1 thing" if count == 1 else f"{count} things"} for sale</h2>'
                     '<ul class="shop-items" role="list">')
        for it in items:
            line = f'<div class="shop-item-desc shop-own-text">{esc(it["description"])}</div>' if it["description"] else ""
            parts.append('<li class="card shop-item"><div class="shop-item-main"><div class="shop-item-text">'
                         f'<h3 class="shop-item-title shop-own-text">{esc(it["title"])}</h3>{line}'
                         f'<div class="shop-item-meta">{"Folder" if it["kind"] == "folder" else "File"}</div></div></div>'
                         f'<div class="shop-item-buy"><span class="shop-price">{esc(amount(it["price_ut"]))} {esc(coin)}'
                         '</span></div></li>')
        parts.append("</ul></section>")
    else:
        parts.append('<div class="empty"><div class="empty-header"><h2 class="empty-title">Nothing for sale right now.</h2>'
                     '</div></div>')
    parts.append("</div>")
    return "".join(parts)


def _page(ctx, text: str, robots: str, status: int = 200) -> Response:
    headers = {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache", "X-Robots-Tag": robots,
               "Referrer-Policy": "no-referrer"}
    if ctx.app.static is not None:           # the dev server: Caddy sets these in production (deploy/caddy/Caddyfile)
        from .dev import APP_CSP
        headers.update({"Content-Security-Policy": APP_CSP, "X-Frame-Options": "DENY",
                        "Cross-Origin-Opener-Policy": "same-origin"})
    return Response(status, text.encode("utf-8"), headers)


# A release is server/ and dist/ side by side (deploy/scripts/activate-release.sh): this file is server/mutis/shop_page.py.
RELEASE_DIST = Path(__file__).resolve().parents[2] / "dist"


def site_dir(ctx) -> str:
    if ctx.app.static is not None:           # the dev server serves its own --dist
        return str(ctx.app.static.root)
    return ctx.cfg["site_dir"] or str(RELEASE_DIST)


def page(ctx, ref: str):
    """GET /shop/<ref> (Caddy sends it here as /api/v1/page/shop/<ref>)."""
    text = template(site_dir(ctx))
    if text is None:
        raise ApiError(503, "unavailable", "The shop's page isn't here right now.")
    feats = ctx.features()
    if not (feats["shop"] and feats["pay_to_open"]):
        return _page(ctx, text, NOINDEX)
    ctx.limit(("shop64", ctx.ip64, shop.READS_PER_MINUTE, 60, 1))
    row = shop.by_ref(ctx.db, ref)            # a username as stored, or an id (case matters in an id)
    if row is None and ref.isascii() and ref.lower() != ref:
        row = shop.by_ref(ctx.db, ref.lower())   # /shop/Mila: the same name
    public = row is not None and row["state"] == "open" and row["mode"] == "public" and row["username"]
    if not public:
        return _page(ctx, text, NOINDEX)
    if ref != row["username"]:               # /shop/Alice, or a public shop's old /shop/<id>: one address per shop
        return Response(301, b"", {"Location": shop.path_of(row), "Cache-Control": "no-cache"})
    if ctx.cfg["staging"]:
        robots = NOINDEX
    else:
        robots = INDEX
    items = shop.public_listings(ctx.db, row["id"], ctx.now)
    try:
        filled = render_public(text, row, items, ctx.cfg.origin, networks.get(ctx.cfg["network"]).coin)
    except TemplateError:
        logsafe.event("api.shop_template", "warning")
        return _page(ctx, text, NOINDEX)
    if robots == NOINDEX:
        filled = filled.replace(f'<meta name="robots" content="{INDEX}">', f'<meta name="robots" content="{NOINDEX}">', 1)
    return _page(ctx, filled, robots)


MARKET_TITLE = "The market"
MARKET_DESC = f"Files and folders for sale in public shops on {BRAND}, paid with Tari. Each stays encrypted until you pay."


def render_market(page: str, items: list, origin: str, coin: str) -> str:
    """The template filled for /market: its title, description, canonical address and the newest listings as text,
    for search engines and readers without JavaScript. Raises TemplateError when an anchor is missing or doubled."""
    canonical = f"{origin}/market"
    out = _one(r'<meta name="robots" content="noindex, nofollow">', f'<meta name="robots" content="{INDEX}">', page)
    out = _one(r"<title>[^<]*</title>", f"<title>{MARKET_TITLE} · {BRAND}</title>", out)
    out = _meta(out, "name", "description", MARKET_DESC)
    for attr, name in (("property", "og:title"), ("name", "twitter:title")):
        out = _meta(out, attr, name, f"{MARKET_TITLE} on {BRAND}")
    for attr, name in (("property", "og:description"), ("name", "twitter:description")):
        out = _meta(out, attr, name, MARKET_DESC)
    data = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{MARKET_TITLE} on {BRAND}",
            "description": MARKET_DESC, "url": canonical, "isPartOf": {"@type": "WebSite", "name": BRAND, "url": origin},
            "mainEntity": {"@type": "ItemList", "numberOfItems": len(items),
                           "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": one_line(it["title"])}
                                               for i, it in enumerate(items)]}}
    head = (f'<link rel="canonical" href="{esc(canonical)}">\n<meta property="og:url" content="{esc(canonical)}">\n'
            f'<script type="application/ld+json">{ld_json(data)}</script>\n</head>')
    out = _one(r"</head>", head, out)
    parts = ['<div class="shop market" data-ssr="1"><header class="shop-head">',
             f'<h1 class="h1">{MARKET_TITLE}</h1><p class="shop-bio">{esc(MARKET_DESC)}</p></header>']
    if items:
        parts.append('<ul class="shop-items" role="list">')
        for it in items:
            line = f'<div class="shop-item-desc shop-own-text">{esc(it["description"])}</div>' if it["description"] else ""
            parts.append('<li class="card shop-item"><div class="shop-item-main"><div class="shop-item-text">'
                         f'<h3 class="shop-item-title shop-own-text">{esc(it["title"])}</h3>{line}'
                         f'<div class="shop-item-meta">{"Folder" if it["kind"] == "folder" else "File"} · '
                         f'<a href="{esc(it["shop"]["path"])}">{esc(it["shop"]["title"])}</a></div></div></div>'
                         f'<div class="shop-item-buy"><span class="shop-price">{esc(amount(it["price_ut"]))} {esc(coin)}'
                         '</span></div></li>')
        parts.append("</ul>")
    parts.append("</div>")
    return _one(r'(?s)<main id="main" class="container a-main" tabindex="-1">.*?</main>',
                '<main id="main" class="container a-main" tabindex="-1">' + "".join(parts) + "</main>", out)


def market_page(ctx):
    """GET /market (Caddy sends it here as /api/v1/page/market): shop.html, filled with the market's words and its
    newest listings while the market is on; plain and noindex otherwise, and on a staging rehearsal."""
    text = template(site_dir(ctx))
    if text is None:
        raise ApiError(503, "unavailable", "The market's page isn't here right now.")
    feats = ctx.features()
    if not (feats["shop"] and feats["pay_to_open"] and feats.get("market")):
        return _page(ctx, text, NOINDEX)
    ctx.limit(("market64", ctx.ip64, market.READS_PER_MINUTE, 60, 1))
    items, _ = market.search(ctx.db, [], None, None, ctx.now)
    try:
        filled = render_market(text, items, ctx.cfg.origin, networks.get(ctx.cfg["network"]).coin)
    except TemplateError:
        logsafe.event("api.shop_template", "warning")
        return _page(ctx, text, NOINDEX)
    if ctx.cfg["staging"]:
        filled = filled.replace(f'<meta name="robots" content="{INDEX}">', f'<meta name="robots" content="{NOINDEX}">', 1)
        return _page(ctx, filled, NOINDEX)
    return _page(ctx, filled, INDEX)


def sitemap(ctx):
    """GET /sitemap-shops.xml (Caddy sends it here): every public shop with something for sale, newest change first.
    Empty on a staging rehearsal and while shops are off."""
    feats = ctx.features()
    urls = []
    if feats["shop"] and feats["pay_to_open"] and not ctx.cfg["staging"]:
        ctx.limit(("shopmap64", ctx.ip64, SITEMAP_PER_MINUTE, 60, 1))
        rows = ctx.db.execute("SELECT sh.username, sh.updated_at FROM shops sh WHERE sh.state = 'open' AND sh.mode = 'public' "
                              "AND sh.username IS NOT NULL AND EXISTS (SELECT 1 FROM shop_listings l "
                              "JOIN shares s ON s.id = l.share_id JOIN paid_shares p ON p.share_id = l.share_id "
                              f"JOIN items i ON i.id = s.item_id WHERE l.shop_id = sh.id AND {shop.LIVE} AND p.paused = 0) "
                              "ORDER BY sh.updated_at DESC LIMIT ?", (ctx.now, ctx.now, SITEMAP_MAX)).fetchall()
        for row in rows:
            day = time.strftime("%Y-%m-%d", time.gmtime(row["updated_at"]))
            loc = esc(f"{ctx.cfg.origin}/shop/{quote(row['username'], safe='')}")
            urls.append(f"  <url><loc>{loc}</loc><lastmod>{day}</lastmod></url>")
        if feats.get("market"):
            urls.insert(0, f"  <url><loc>{esc(ctx.cfg.origin + '/market')}</loc></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "".join(u + "\n" for u in urls) + "</urlset>\n")
    return Response(200, xml.encode("utf-8"), {"Content-Type": "application/xml; charset=utf-8",
                                               "Cache-Control": "public, max-age=3600"})

