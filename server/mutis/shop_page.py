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
That text is the app's own markup, in the app's words: the elements and classes ui/shop-page.js and ui/market-page.js
draw, the release's copy deck (app/i18n/en.json, as lib/network.js says it on this network) and its icons. So when the
app draws, nothing on the page moves: the page's first frame already has its last one's layout (app/shop.html starts in
the drive's look). What only the browser knows (a shop's key after the #, this browser's open asks) the app adds.

Every piece of the owner's text is escaped for where it lands: HTML text and attribute values (esc(), quotes
included), JSON-LD (JSON with <, > and & as \\u escapes and no character outside ASCII), one line in meta tags. The
address is built from the stored username, which is ASCII a-z, 0-9 and hyphens by construction (shop.username), and
quoted again anyway. When the template doesn't have exactly the anchors this fills, or the copy deck lacks a word it
needs, the page goes out unfilled (noindex) rather than half-filled.
"""
import json
import re
import time
from decimal import ROUND_HALF_UP, Decimal
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
WORDS = "app/i18n/en.json"      # the copy deck the app reads (the build keeps this name beside the hashed one)
SPRITE = re.compile(r'/shared/ui/icons(?:\.[0-9a-f]+)?\.svg(?=#)')   # the icons, as the template names them
MAIN = re.compile(r'(?s)(<main id="main"[^>]*>).*?</main>')
MIB = 1024 * 1024
SENTENCE_END = re.compile(r'([.!?][”’")]?) (?=[“‘"(]?[A-Z])')   # ui/lines.js END
SIZE_BUCKETS = [n * MIB for n in (1, 5, 10, 50, 100, 500, 1024, 2048, 5120, 10240)]   # lib/pay.js BUCKETS
_template: dict = {}
_words: dict = {}


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


def words(site_dir: str, network: str) -> dict | None:
    """The release's copy deck as the app says it on this network (lib/network.js mainnetWords): on the mainnet a key's
    @mainnet line stands in for it, and tTARI reads TARI. Read again when it changes, like template()."""
    path = Path(site_dir) / WORDS
    try:
        st = path.stat()
        key = (str(path.resolve()), st.st_mtime_ns, st.st_size, network)
        hit = _words.get("deck")
        if hit is not None and hit[0] == key:
            return hit[1]
        deck = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(deck, dict):
        return None
    if network == "mainnet":
        def rename(v):
            if isinstance(v, dict):
                return {k: rename(x) for k, x in v.items()}
            return re.sub(r"\btTARI\b", "TARI", v) if isinstance(v, str) else v     # say() refuses anything else
        deck = {k: rename(deck.get(f"{k}@mainnet", v)) for k, v in deck.items() if not k.endswith("@mainnet")}
    _words["deck"] = (key, deck)
    return deck


def say(deck: dict, key: str, **params) -> str:
    """lib/i18n.js t(): the word for key with {name} filled in ({brand} is BRAND), plurals by count as en-US says them.
    A word the deck doesn't have raises TemplateError: the page goes out unfilled rather than with a key in it."""
    value = deck.get(key)
    if isinstance(value, dict):
        value = value.get("one" if params.get("count", 0) == 1 else "other", value.get("other"))
    if not isinstance(value, str):
        raise TemplateError(key)

    def fill(m):
        name = m[1]
        p = params.get(name, BRAND) if name == "brand" else params.get(name)
        if p is None:
            return m[0]
        return f"{p:,}" if isinstance(p, int) else str(p)
    return re.sub(r"\{(\w+)\}", fill, value)


def prose(text: str) -> str:
    """A paragraph's text as the app writes it (ui/lines.js lines(), one sentence a line): a <br> after every
    sentence but the last, the space before it kept; escaped."""
    part = SENTENCE_END.split(text)
    out, now = [], part[0]
    for i in range(1, len(part), 2):
        out.append(esc(f"{now}{part[i]} ") + "<br>")
        now = part[i + 1]
    out.append(esc(now))
    return "".join(out)


def icon(sprite: str, name: str) -> str:
    """ui/behaviors.js icon(): one glyph of the release's sprite."""
    return f'<svg class="icon" aria-hidden="true" focusable="false"><use href="{esc(sprite)}#i-{name}"></use></svg>'


def size_bucket(size: int) -> int:
    """lib/pay.js sizeBucket(): the listing's size as the app says it, rounded up to a bucket."""
    return next((b for b in SIZE_BUCKETS if size <= b), SIZE_BUCKETS[-1])


def format_bytes(n: int) -> str:
    """lib/i18n.js formatBytes(): binary units, one decimal under 10 (en-US, half away from zero)."""
    units, i, v = ("B", "KB", "MB", "GB"), 0, Decimal(n)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    places = 1 if v < 10 and i > 0 else 0
    text = f"{v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,}"
    return f"{text.rstrip('0').rstrip('.') if '.' in text else text} {units[i]}"


def tari(ut) -> str:
    """ui/drive-parts.js formatTari(): whole TARI and thousandths, no trailing zero."""
    v = int(ut)
    milli = (v % 1_000_000) // 1000
    return str(v // 1_000_000) + (("." + f"{milli:03d}".rstrip("0")) if milli else "")


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


def _one(pattern: str, repl: str, text: str, flags: int = 0) -> str:
    new, n = re.subn(pattern, lambda _m: repl, text, count=2, flags=flags)
    if n != 1:
        raise TemplateError(pattern)
    return new


def _main(text: str, inner: str) -> str:
    """<main id="main"> with inner as its content; its own opening tag (its look's classes) as the template has it."""
    found = MAIN.findall(text)
    if len(found) != 1:
        raise TemplateError("main")
    return MAIN.sub(lambda m: m[1] + inner + "</main>", text, count=1)


def _sprite(text: str) -> str:
    m = SPRITE.search(text)
    if m is None:
        raise TemplateError("sprite")
    return m[0]


def _meta(text: str, attr: str, name: str, value: str) -> str:
    return _one(rf'<meta {attr}="{re.escape(name)}" content="[^"]*">', f'<meta {attr}="{name}" content="{esc(value)}">',
                text)


def render_public(page: str, row, items: list, origin: str, coin: str, deck: dict, market_on: bool,
                  network: str = "") -> str:
    """The template filled for a public shop. Raises TemplateError when an anchor is missing or doubled, or a word."""
    canonical = f"{origin}/shop/{quote(row['username'], safe='')}"
    sprite = _sprite(page)              # the template's, before any of the owner's text is in the page
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
    report = "/fine-print#link=" + quote(canonical, safe="-_.!~*'()")     # ui/shell.js abuseHref()
    return _main(out, body(row, items, coin, deck, sprite, market_on, _foot(deck, network, report)))


def _item(deck: dict, sprite: str, it, coin: str, extra: str, meta_end: str, slot: str) -> str:
    """One listing as ui/shop-page.js item() and ui/market-page.js card() draw it (extra: the market's class)."""
    kind = say(deck, "shop.kind_folder" if it["kind"] == "folder" else "shop.kind_file")
    size = say(deck, "buy.about", size=format_bytes(size_bucket(int(it["size_stored"]))))
    price = say(deck, "shop.price", price=tari(it["price_ut"]), unit=coin)
    line = f'<div class="shop-item-desc shop-own-text">{esc(it["description"])}</div>' if it["description"] else ""
    return (f'<li class="card shop-item{extra}"><div class="shop-item-main"><span class="shop-item-icon" aria-hidden="true">'
            f'{icon(sprite, "folder" if it["kind"] == "folder" else "file-lock")}</span><div class="shop-item-text">'
            f'<h3 class="shop-item-title shop-own-text">{esc(it["title"])}</h3>{line}'
            f'<div class="shop-item-meta">{esc(kind)} · {esc(size)}{meta_end}</div></div></div>'
            f'<div class="shop-item-buy{" market-item-buy" if extra else ""}"><span class="shop-price">{esc(price)}</span>'
            f'{slot}</div></li>')


def _ask(deck: dict, sprite: str, title: str) -> str:
    """ui/market-ask.js askSlot() before anything is asked: Ask for it (the app's own button takes its place)."""
    return ('<div class="market-ask-slot"><div class="stack-sm"><button class="btn" type="button" '
            f'aria-label="{esc(say(deck, "shop.ask_aria", title=title))}">{icon(sprite, "key-round")}'
            f'{esc(say(deck, "shop.ask"))}</button></div></div>')


def _empty(deck: dict, sprite: str, title: str, line: str | None) -> str:
    text = f'<p class="empty-description">{prose(say(deck, line))}</p>' if line else ""
    return (f'<div class="empty"><div class="empty-header"><div class="empty-media" data-variant="icon">{icon(sprite, "store")}'
            f'</div><h2 class="empty-title">{esc(say(deck, title))}</h2>{text}</div></div>')


def _foot(deck: dict, network: str, report: str | None = None) -> str:
    """The page's foot as the app draws it on the mainnet (ui/marks.js testnetLine, then Report this shop on a shop's
    page), so the page is as tall at its first frame as at its last. Elsewhere the line depends on the browser's dates
    (the testnet's phase), and the app adds the foot below the list."""
    if network != "mainnet":
        return ""
    link = f'<a class="link-plain small" href="{esc(report)}">{esc(say(deck, "shop.report"))}</a>' if report else ""
    return f'<footer class="shop-foot"><p class="a-testnet">{prose(say(deck, "testnet"))}</p>{link}</footer>'


def body(row, items: list, coin: str, deck: dict, sprite: str, market_on: bool, foot: str = "") -> str:
    """The shop inside <main> as ui/shop-page.js draws it for a visitor without its key (the address alone; a key after
    the # is the browser's to read): for readers without JavaScript and for search engines, and the app's first frame."""
    parts = ['<div class="shop" data-ssr="1"><header class="shop-head">',
             f'<span class="badge" data-variant="secondary">{icon(sprite, "store")}{esc(say(deck, "shop.label"))}</span>',
             f'<h1 class="h1 shop-own-text">{esc(row["title"])}</h1>']
    if row["bio"]:
        parts.append(f'<div class="shop-bio shop-own-text">{esc(row["bio"])}</div>')
    parts.append(f'<p class="small muted">{prose(say(deck, "shop.owner_wrote"))}</p></header>')
    if items:
        parts.append('<section class="shop-list" aria-labelledby="shop-list-h">'
                     f'<h2 class="h4" id="shop-list-h">{esc(say(deck, "shop.count", count=len(items)))}</h2>'
                     f'<p class="small muted">{prose(say(deck, "shop.keyless" if market_on else "shop.how"))}</p>'
                     '<ul class="shop-items" role="list">')
        for it in items:
            slot = (_ask(deck, sprite, it["title"]) if market_on
                    else f'<p class="small muted">{prose(say(deck, "shop.no_key"))}</p>')
            parts.append(_item(deck, sprite, it, coin, "", "", slot))
        parts.append("</ul></section>")
    else:
        parts.append(_empty(deck, sprite, "shop.empty", "shop.empty_d"))
    parts.append(foot + "</div>")
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
    deck = words(site_dir(ctx), ctx.cfg["network"])
    try:
        if deck is None:
            raise TemplateError(WORDS)
        filled = render_public(text, row, items, ctx.cfg.origin, networks.get(ctx.cfg["network"]).coin, deck,
                               bool(feats.get("market")), ctx.cfg["network"])
    except TemplateError:
        logsafe.event("api.shop_template", "warning")
        return _page(ctx, text, NOINDEX)
    if robots == NOINDEX:
        filled = filled.replace(f'<meta name="robots" content="{INDEX}">', f'<meta name="robots" content="{NOINDEX}">', 1)
    return _page(ctx, filled, robots)


MARKET_TITLE = "The market"
MARKET_DESC = f"Files and folders for sale in public shops on {BRAND}, paid with Tari. Each stays encrypted until you pay."


def render_market(page: str, items: list, origin: str, coin: str, deck: dict, network: str = "") -> str:
    """The template filled for /market: its title, description, canonical address and the newest listings, as
    ui/market-page.js draws them before any search (for search engines, readers without JavaScript and the app's first
    frame). Raises TemplateError when an anchor is missing or doubled, or a word."""
    canonical = f"{origin}/market"
    sprite = _sprite(page)
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
    say_ = lambda key, **p: esc(say(deck, key, **p))   # noqa: E731
    kinds = "".join(f'<option value="{v}">{say_(k)}</option>'
                    for v, k in (("", "market.kind_all"), ("file", "market.kind_file"), ("folder", "market.kind_folder")))
    parts = ['<div class="shop market" data-ssr="1"><header class="shop-head">',
             f'<span class="badge" data-variant="secondary">{icon(sprite, "store")}{say_("market.page_title")}</span>',
             f'<h1 class="h1">{say_("market.h")}</h1><p class="shop-bio">{prose(say(deck, "market.desc"))}</p>',
             f'<p class="small muted">{prose(say(deck, "market.owner_wrote"))}</p></header>',
             f'<section class="shop-list" aria-label="{say_("market.h")}">',
             '<form class="market-search" role="search"><input class="input" id="market-q" type="search" name="q" '
             f'maxlength="60" autocomplete="off" aria-label="{say_("market.search_label")}"><select class="input market-kind" '
             f'aria-label="{say_("market.kind_all")}">{kinds}</select><button class="btn" type="submit">{icon(sprite, "search")}'
             f'{say_("market.search")}</button></form><ul class="shop-items" role="list">']
    for it in items:
        shop_link = (f' · <a class="link-plain shop-own-text" href="{esc(it["shop"]["path"])}">'
                     f'{say_("market.by", shop=it["shop"]["title"])}</a>')
        parts.append(_item(deck, sprite, it, coin, " market-item", shop_link, _ask(deck, sprite, it["title"])))
    parts.append("</ul><div>")
    if not items:
        parts.append(_empty(deck, sprite, "market.empty", "market.empty_d"))
    parts.append("</div></section>" + _foot(deck, network) + "</div>")
    return _main(out, "".join(parts))


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
    deck = words(site_dir(ctx), ctx.cfg["network"])
    try:
        if deck is None:
            raise TemplateError(WORDS)
        filled = render_market(text, items, ctx.cfg.origin, networks.get(ctx.cfg["network"]).coin, deck,
                               ctx.cfg["network"])
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

