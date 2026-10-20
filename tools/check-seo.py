#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Search and link-preview checks from outside, as a crawler or an unfurler sees the site. Python standard library only.

  python3 -I tools/check-seo.py [--origin https://hidebox.app]   the live site (the default)
  python3 -I tools/check-seo.py --dist DIR                       a tree built by tools/build.py, served locally
  python3 -I tools/check-seo.py --local [SSH_HOST]               the working tree, built and served by the production
                                                                 Caddyfile on the server's throwaway stack (localstack.py)

Each public page (tests/e2e/headers_spec.INDEXABLE, which the sitemap must list exactly) is fetched and checked: 200 HTML,
<html lang="en">, one <h1> and no skipped heading level, a title of at most 60 characters ending with the name and a
description of at most 155 (both unique), robots that allow indexing, a canonical on the origin that og:url repeats,
the Open Graph card (type, site name, title, description, an absolute image with its secure URL, type, real size and
alt) and the same Twitter card, JSON-LD that parses (the home's WebSite and SoftwareApplication, a BreadcrumbList that
ends on the page elsewhere; no rating or review), theme colours for light and dark, the app title, the icons, every
image with alt text and a size, link text that says where it goes, and at least three links into the site. Then the
share cards (PNG, 1200 x 630 for summary_large_image, under WhatsApp's 300 KB), the icons and the manifest; robots.txt
(its Sitemap line, the public pages allowed, the private paths blocked) and sitemap.xml (it parses, the public pages
with a lastmod); every private route noindex; and an unknown page answers 404, noindex.

What only Caddy sets (X-Robots-Tag on the private routes, the cards' cache and cross-origin policy, the crawl files'
cache) is checked against --origin and --local; with --dist the pages' own robots metas stand in where a route serves
a file, and the rest is SKIP (tests/e2e/test_headers.py --local checks the Caddyfile itself). The origin the tags must
name is the one the tree was built for (its robots.txt says), or --expect-origin.
Prints PASS, FAIL or SKIP per page and per site-wide check, then a table of titles and descriptions; --json writes the
results. Exit status 1 when anything fails.
"""
import argparse
import http.client
import json
import re
import ssl
import struct
import sys
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
import headers_spec  # noqa: E402

BRAND = re.search(r'^BRAND = "([^"]+)"', (ROOT / "tools" / "build.py").read_text(encoding="utf-8"), re.M)[1]
UA = "mutis-check-seo/1 (+https://github.com/c7b/hidebox)"
TITLE_MAX, DESC_MAX = 60, 155
CARD_SIZE = (1200, 630)
WHATSAPP_MAX = 300 * 1024      # WhatsApp drops a preview image over about 300 KB
ROBOTS_BLOCKED = ("/drive", "/drive/received", "/drive/earnings", "/s/AAAAAAAAAAAAAAAAAAAAAA", "/p/AAAAAAAAAAAAAAAAAAAAAA", "/t",
                  "/api/v1/stats/wall", "/send", "/verify/tx/" + "0" * 64)
# Private routes: never in an index. They answer X-Robots-Tag (Caddy); the HTML ones also carry a robots meta.
PRIVATE = ("/drive", "/drive/received", "/drive/earnings", "/s/AAAAAAAAAAAAAAAAAAAAAA", "/p/AAAAAAAAAAAAAAAAAAAAAA", "/t", "/d/7kq2x9mdh4",
           "/send", "/watch", "/verify/tx/" + "0" * 64, "/v2", "/app/drive.html", "/app/view.html", "/app/app.html",
           "/api/v1/config")
# The bots that draw a pasted link's card (robots.txt's second group): they may read a shared link's page.
PREVIEW_BOTS = ("Twitterbot", "facebookexternalhit", "Slackbot-LinkExpanding", "LinkedInBot", "Discordbot", "TelegramBot",
                "WhatsApp")
GENERIC_LINK_TEXT = {"here", "click here", "read more", "more", "link", "this", "this page"}


def fetch(url: str, method: str = "GET") -> tuple[int, dict, bytes]:
    """One request, no redirect followed, no compression; headers lower-cased (a repeated one joined). A request that
    fails (no answer, TLS, a URL that isn't http or https) is status 0 with the reason in an "error" header, so the
    check that made it fails and says why."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return 0, {"error": f"not an http(s) URL: {url!r}"}, b""
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=30, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=30)
    try:
        conn.request(method, (u.path or "/") + (f"?{u.query}" if u.query else ""),
                     headers={"User-Agent": UA, "Accept-Encoding": "identity", "Accept": "*/*"})
        res = conn.getresponse()
        body = res.read()
        headers: dict[str, str] = {}
        for k, v in res.getheaders():
            headers[k.lower()] = f"{headers[k.lower()]}, {v}" if k.lower() in headers else v
        return res.status, headers, body
    except (OSError, http.client.HTTPException) as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}, b""
    finally:
        conn.close()


class Page(HTMLParser):
    """The parts of a page a crawler and an unfurler read."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title, self.in_title = "", False
        self.metas: list[dict] = []
        self.links: list[dict] = []
        self.headings: list[int] = []
        self.images: list[dict] = []
        self.anchors: list[tuple[str, str]] = []
        self.ld: list[str] = []
        self._ld, self._a = None, None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        elif tag == "img":
            self.images.append(a)
            if self._a is not None:
                self._a[1].append(a.get("alt", ""))
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._ld = []
        elif tag == "a" and "href" in a:
            self._a = (a["href"], [a.get("aria-label", "")])
        elif tag == "svg" and self._a is not None and a.get("aria-label"):
            self._a[1].append(a["aria-label"])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script" and self._ld is not None:
            self.ld.append("".join(self._ld))
            self._ld = None
        elif tag == "a" and self._a is not None:
            self.anchors.append((self._a[0], " ".join(" ".join(self._a[1]).split())))
            self._a = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self._ld is not None:
            self._ld.append(data)
        if self._a is not None:
            self._a[1].append(data)

    def meta(self, **match) -> str | None:
        for m in self.metas:
            if all(m.get(k) == v for k, v in match.items()):
                return m.get("content")
        return None

    def all_meta(self, **match) -> list[dict]:
        return [m for m in self.metas if all(m.get(k) == v for k, v in match.items())]

    def rel(self, rel: str) -> list[dict]:
        return [link for link in self.links if rel in link.get("rel", "").lower().split()]


def parse(body: bytes) -> Page:
    page = Page()
    page.feed(body.decode("utf-8", "replace"))
    return page


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


def max_age(headers: dict) -> int:
    m = re.search(r"max-age=(\d+)", headers.get("cache-control", ""))
    return int(m[1]) if m and "no-store" not in headers.get("cache-control", "") else 0


def robots_groups(robots: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """(user agents, rules) per group (RFC 9309): consecutive User-agent lines open a group, its rules follow."""
    groups, agents, rules = [], [], []
    for raw in robots.splitlines():
        key, _, value = raw.split("#", 1)[0].strip().partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents:
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    return groups


def robots_allows(robots: str, path: str, agent: str = "*") -> bool:
    """Google's rule matching in the group that names `agent` (else the * group): the longest matching rule wins,
    Allow on a tie; * is any run, $ the end; an empty Disallow allows everything."""
    groups = robots_groups(robots)
    rules = [r for agents, rs in groups if agent.lower() in agents for r in rs] or \
        [r for agents, rs in groups if "*" in agents for r in rs]
    best = (-1, True)
    for kind, pattern in rules:
        if not pattern:
            continue
        rx = re.escape(pattern).replace(r"\*", ".*")
        rx = rx[:-2] + "$" if rx.endswith(r"\$") else rx
        if re.match(rx, path) and (len(pattern), kind == "allow") > best:
            best = (len(pattern), kind == "allow")
    return best[1]


def robots_tokens(*values: str) -> set[str]:
    """The directives of robots metas and X-Robots-Tag values, lower-cased (an agent prefix such as "googlebot:" kept)."""
    return {token for value in values for token in re.split(r"[,\s]+", value.lower()) if token}


def ld_nodes(blocks: list[str]) -> tuple[list[dict], list[str]]:
    """Every node of every JSON-LD block (a block may be one node, a @graph or a list of either)."""
    nodes, problems = [], []
    for raw in blocks:
        try:
            doc = json.loads(raw)
        except ValueError as e:
            problems.append(f"JSON-LD doesn't parse: {e}")
            continue
        for item in doc if isinstance(doc, list) else [doc]:
            if not isinstance(item, dict):
                problems.append(f"JSON-LD holds a {type(item).__name__}, not an object")
                continue
            if item.get("@context") != "https://schema.org":
                problems.append(f"JSON-LD @context is {item.get('@context')!r}")
            graph = item.get("@graph")
            nodes += [n for n in graph if isinstance(n, dict)] if isinstance(graph, list) else [item]
    return nodes, problems


def ld_types(nodes: list[dict]) -> dict[str, dict]:
    """Each node by its @type (a node with several types under each)."""
    types = {}
    for node in nodes:
        kinds = node.get("@type")
        for kind in kinds if isinstance(kinds, list) else [kinds]:
            if isinstance(kind, str):
                types.setdefault(kind, node)
    return types


class Checker:
    def __init__(self, origin: str, expect: str, caddy: bool):
        self.origin, self.expect, self.caddy = origin.rstrip("/"), expect.rstrip("/"), caddy
        self.results: list[dict] = []
        self.table: list[dict] = []
        self.images: dict[str, list[str]] = {}

    def add(self, name: str, problems: list[str] | None, notes: list[str] = ()) -> None:
        state = "SKIP" if problems is None else "FAIL" if problems else "PASS"
        self.results.append({"check": name, "result": state, "problems": problems or [], "notes": list(notes)})

    def local(self, url: str) -> str:
        """A URL the tags name (on the expected origin), fetched from the origin being checked."""
        return self.origin + url[len(self.expect):] if url.startswith(self.expect) else url

    def page(self, path: str) -> None:
        problems, notes = [], []
        status, headers, body = fetch(self.origin + path)
        if status != 200 or not headers.get("content-type", "").startswith("text/html"):
            self.add(f"page {path}", [f"status {status}, content-type {headers.get('content-type')!r}"])
            return
        p = parse(body)
        url = self.expect + path
        title = " ".join(p.title.split())
        desc = p.meta(name="description") or ""
        self.table.append({"path": path, "title": title, "title_len": len(title), "description": desc,
                           "description_len": len(desc)})
        if p.lang != "en":
            problems.append(f"<html lang> is {p.lang!r}")
        if not p.meta(name="viewport"):
            problems.append("no viewport meta")
        if not title or len(title) > TITLE_MAX or not title.endswith(f" · {BRAND}"):
            problems.append(f"title {title!r} ({len(title)}): at most {TITLE_MAX} characters, the name last")
        if not desc or len(desc) > DESC_MAX:
            problems.append(f"description of {len(desc)} characters (1 to {DESC_MAX})")
        robots = robots_tokens(p.meta(name="robots") or "", headers.get("x-robots-tag", ""))
        if robots & {"noindex", "nofollow", "none"}:
            problems.append(f"robots: {', '.join(sorted(robots & {'noindex', 'nofollow', 'none'}))}")
        if "max-image-preview:large" not in robots:
            problems.append("robots don't allow a large image preview (max-image-preview:large)")
        canonical = [link.get("href") for link in p.rel("canonical")]
        if canonical != [url]:
            problems.append(f"canonical {canonical}, expected [{url!r}]")
        if p.headings.count(1) != 1:
            problems.append(f"{p.headings.count(1)} <h1>")
        skips = [f"h{a} to h{b}" for a, b in zip(p.headings, p.headings[1:]) if b > a + 1]
        if skips:
            problems.append(f"heading levels skipped: {', '.join(skips)}")
        problems += self.card(p, url)
        nodes, ld_problems = ld_nodes(p.ld)
        problems += ld_problems
        types = ld_types(nodes)
        if any("aggregateRating" in n or "review" in n for n in nodes):
            problems.append("JSON-LD carries a rating or a review")
        if path == "/":
            app = types.get("SoftwareApplication", {})
            if "WebSite" not in types or app.get("name") != BRAND or not app.get("operatingSystem") \
                    or app.get("offers", {}).get("price") != "0" or app.get("url") != url:
                problems.append("JSON-LD: needs the WebSite and the SoftwareApplication (name, url, operatingSystem, a free offer)")
        else:
            items = types.get("BreadcrumbList", {}).get("itemListElement", [])
            if [i.get("item") for i in items] != [self.expect + "/", url]:
                problems.append(f"JSON-LD: BreadcrumbList {[i.get('item') for i in items]}, expected home then {url}")
        notes.append("JSON-LD: " + (", ".join(sorted(t for t in types if t)) or "none"))
        themes = sorted(m.get("media", "") for m in p.all_meta(name="theme-color"))
        if themes != ["(prefers-color-scheme: dark)", "(prefers-color-scheme: light)"]:
            problems.append(f"theme-color for {themes}, expected light and dark")
        if p.meta(name="apple-mobile-web-app-title") != BRAND:
            problems.append("no apple-mobile-web-app-title")
        icons = [link.get("href", "") for link in p.rel("icon")]
        for want in (".ico", ".svg"):
            if not any(i.endswith(want) for i in icons):
                problems.append(f"no {want} icon link")
        if not p.rel("apple-touch-icon") or not p.rel("manifest"):
            problems.append("no apple-touch-icon or manifest link")
        for img in p.images:
            if not img.get("alt", "").strip():
                problems.append(f"<img src={img.get('src')!r}> has no alt text")
            if not (img.get("width") and img.get("height")):
                problems.append(f"<img src={img.get('src')!r}> has no width and height")
        internal = set()
        for href, text in p.anchors:
            if not text:
                problems.append(f"a link to {href!r} has no text or label")
            elif text.lower().strip(" .") in GENERIC_LINK_TEXT:
                problems.append(f"a link to {href!r} says {text!r}")
            target = urllib.parse.urlsplit(urllib.parse.urljoin(url, href))
            if f"{target.scheme}://{target.netloc}" == self.expect and target.path != path:
                internal.add(target.path)
        if len(internal) < 3:
            problems.append(f"{len(internal)} links to other pages of the site (at least 3)")
        notes.append(f"{len(internal)} pages linked, {len(p.images)} images, {len(p.headings)} headings")
        self.add(f"page {path}", problems, notes)

    def card(self, p: Page, url: str) -> list[str]:
        """The Open Graph and Twitter tags (Telegram, WhatsApp, iMessage, Slack, Discord, X and LinkedIn read these)."""
        problems = []
        og = {k: p.meta(property=f"og:{k}") for k in ("type", "site_name", "title", "description", "url", "image",
                                                      "image:secure_url", "image:type", "image:width", "image:height",
                                                      "image:alt")}
        missing = [k for k, v in og.items() if not v]
        if missing:
            problems.append(f"missing og:{', og:'.join(missing)}")
        if og["site_name"] != BRAND or og["url"] != url:
            problems.append(f"og:site_name {og['site_name']!r}, og:url {og['url']!r} (expected {BRAND!r}, {url!r})")
        image = og["image"] or ""
        if not image.startswith(self.expect + "/"):
            problems.append(f"og:image {image!r} is not an absolute URL on {self.expect}")
        if og["image:secure_url"] and og["image:secure_url"] != image:
            problems.append("og:image:secure_url is not og:image")
        if self.expect.startswith("https://") and not image.startswith("https://"):
            problems.append("og:image is not an https URL")
        tw = {k: p.meta(name=f"twitter:{k}") for k in ("card", "title", "description", "image", "image:alt")}
        if tw["card"] != "summary_large_image":
            problems.append(f"twitter:card is {tw['card']!r}")
        for k, o in (("title", "title"), ("description", "description"), ("image", "image"), ("image:alt", "image:alt")):
            if tw[k] != og[o]:
                problems.append(f"twitter:{k} {tw[k]!r} differs from og:{o}")
        if image:
            size = (og["image:width"], og["image:height"])
            self.images.setdefault(image, [])
            if size not in self.images[image]:
                self.images[image].append(size)
            if og["image:type"] and og["image:type"] != "image/png":
                problems.append(f"og:image:type {og['image:type']!r}")
        return problems

    def cards(self) -> None:
        for image, sizes in sorted(self.images.items()):
            problems, notes = [], []
            if not image.startswith(self.expect + "/"):
                continue   # the page that names it already failed: never fetched from another site
            status, headers, body = fetch(self.local(image))
            real = png_size(body)
            if status != 200 or headers.get("content-type") != "image/png" or not real:
                self.add(f"card {image}", [f"status {status}, content-type {headers.get('content-type')!r}, PNG {bool(real)}"
                                           + (f", {headers['error']}" if "error" in headers else "")])
                continue
            for w, h in sizes:
                if (str(real[0]), str(real[1])) != (w, h):
                    problems.append(f"the tags say {w} x {h}, the file is {real[0]} x {real[1]}")
            if real != CARD_SIZE:
                problems.append(f"{real[0]} x {real[1]}, not {CARD_SIZE[0]} x {CARD_SIZE[1]} (1.91:1, a large card everywhere)")
            if len(body) > WHATSAPP_MAX:
                problems.append(f"{len(body):,} B: WhatsApp drops a preview image over {WHATSAPP_MAX:,} B")
            notes.append(f"{real[0]} x {real[1]}, {len(body):,} B")
            self.add(f"card {image}", problems, notes)
            if not self.caddy:
                self.add(f"card {image}: kept a day, loadable from any origin (Caddy sets it)", None)
                continue
            problems = []
            if max_age(headers) < 86400:
                problems.append(f"Cache-Control {headers.get('cache-control')!r}: at least a day")
            if headers.get("cross-origin-resource-policy") != "cross-origin":
                problems.append(f"Cross-Origin-Resource-Policy {headers.get('cross-origin-resource-policy')!r}: "
                                "a preview drawn from the page loads it from another origin")
            self.add(f"card {image}: kept a day, loadable from any origin", problems,
                     [f"{headers.get('cache-control')!r}, CORP {headers.get('cross-origin-resource-policy')!r}"])

    def icons_and_manifest(self) -> None:
        problems, notes = [], []
        for path, ctype in headers_spec.CARDS.items():
            if path.startswith("/og"):
                continue
            status, headers, body = fetch(self.origin + path)
            if status != 200 or headers.get("content-type") != ctype or not body:
                problems.append(f"{path}: status {status}, content-type {headers.get('content-type')!r}")
            elif self.caddy and max_age(headers) < 86400:
                problems.append(f"{path}: Cache-Control {headers.get('cache-control')!r}")
        status, headers, body = fetch(self.origin + "/manifest.webmanifest")
        try:
            manifest = json.loads(body) if status == 200 else {}
        except ValueError:
            manifest = {}
        if headers.get("content-type", "").split(";")[0] != "application/manifest+json":
            problems.append(f"manifest content-type {headers.get('content-type')!r}")
        for key in ("id", "name", "short_name", "description", "start_url", "display", "theme_color", "background_color"):
            if not manifest.get(key):
                problems.append(f"manifest: no {key}")
        for icon in manifest.get("icons", []):
            s, h, _ = fetch(self.origin + icon.get("src", "/"), "HEAD")
            if s != 200 or h.get("content-type") != icon.get("type"):
                problems.append(f"manifest icon {icon.get('src')}: status {s}, content-type {h.get('content-type')!r}")
            if "maskable" in icon.get("purpose", ""):
                notes.append(f"maskable icon {icon.get('src')}")
        notes.append(f"manifest: {manifest.get('name')!r}, {len(manifest.get('icons', []))} icons, start_url {manifest.get('start_url')!r}")
        self.add("icons and manifest", problems, notes)

    def robots(self, public: list[str]) -> str:
        problems = []
        status, headers, body = fetch(self.origin + "/robots.txt")
        text = body.decode("utf-8", "replace")
        if status != 200 or not headers.get("content-type", "").startswith("text/plain"):
            problems.append(f"status {status}, content-type {headers.get('content-type')!r}")
        if f"Sitemap: {self.expect}/sitemap.xml" not in text:
            problems.append(f"no 'Sitemap: {self.expect}/sitemap.xml'")
        problems += [f"blocks the public page {p}" for p in public if not robots_allows(text, p)]
        problems += [f"doesn't block {p}" for p in ROBOTS_BLOCKED if robots_allows(text, p)]
        for bot in PREVIEW_BOTS:
            problems += [f"{bot} may not read {p} (it draws the card of a pasted link)"
                         for p in ("/", "/s/AAAAAAAAAAAAAAAAAAAAAA", "/p/AAAAAAAAAAAAAAAAAAAAAA", "/d/7kq2x9mdh4")
                         if not robots_allows(text, p, bot)]
        if self.caddy and max_age(headers) < 3600:
            problems.append(f"Cache-Control {headers.get('cache-control')!r}")
        self.add("robots.txt", problems, [f"{len(re.findall(r'(?m)^Disallow:', text))} Disallow lines"])
        return text

    def sitemap(self, public: list[str]) -> None:
        problems = []
        status, headers, body = fetch(self.origin + "/sitemap.xml")
        if status != 200 or headers.get("content-type", "").split(";")[0] not in ("application/xml", "text/xml"):
            problems.append(f"status {status}, content-type {headers.get('content-type')!r}")
        locs, dates = [], set()
        try:
            root = ET.fromstring(body)
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            if root.tag != ns + "urlset":
                problems.append(f"root element {root.tag!r}")
            for u in root.findall(ns + "url"):
                locs.append(u.findtext(ns + "loc"))
                lastmod = u.findtext(ns + "lastmod") or ""
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", lastmod):
                    problems.append(f"{u.findtext(ns + 'loc')}: lastmod {lastmod!r}")
                dates.add(lastmod)
        except ET.ParseError as e:
            problems.append(f"doesn't parse: {e}")
        want = sorted(self.expect + p for p in public)
        if sorted(locs) != want:
            problems.append(f"lists {sorted(locs)}, expected {want}")
        if self.caddy and max_age(headers) < 3600:
            problems.append(f"Cache-Control {headers.get('cache-control')!r}")
        self.add("sitemap.xml", problems, [f"{len(locs)} URLs, lastmod {', '.join(sorted(dates))}"])

    def private(self) -> None:
        """noindex on every private route; a private page's card (a shared link's og-s.png) is checked with the others,
        and names no address (no og:url, no canonical: one page answers for every link)."""
        problems, notes, skipped = [], [], []
        for path in PRIVATE:
            status, headers, body = fetch(self.origin + path)
            header = headers.get("x-robots-tag", "")
            html = headers.get("content-type", "").startswith("text/html")
            page = parse(body) if html and status == 200 else None
            page_robots = page.meta(name="robots") or "" if page else ""
            if page and path != "/v2":   # the unlinked preview keeps the head it was made with
                if page.meta(property="og:url") or page.rel("canonical"):
                    problems.append(f"{path}: og:url or a canonical (a preview must not name the link)")
                image = page.meta(property="og:image")
                if image:
                    size = (page.meta(property="og:image:width"), page.meta(property="og:image:height"))
                    if size not in self.images.setdefault(image, []):
                        self.images[image].append(size)
                if page.meta(name="twitter:image") != image:
                    problems.append(f"{path}: twitter:image differs from og:image")
            if self.caddy:
                if status != 200 or "noindex" not in header:
                    problems.append(f"{path}: status {status}, X-Robots-Tag {header!r}")
            elif status == 200 and html:
                if "noindex" not in page_robots + header:
                    problems.append(f"{path}: no noindex in its robots meta")
            else:
                skipped.append(path)
        self.add("private routes are noindex" + ("" if self.caddy else " (their robots meta, where a file answers)"),
                 problems, notes)
        if skipped:
            self.add("private routes: X-Robots-Tag (Caddy sets it): " + ", ".join(skipped), None)

    def not_found(self) -> None:
        status, headers, body = fetch(self.origin + "/this-page-does-not-exist")
        robots = (parse(body).meta(name="robots") or "") + headers.get("x-robots-tag", "")
        self.add("an unknown page answers 404, noindex",
                 [] if status == 404 and "noindex" in robots else [f"status {status}, robots {robots!r}"])

    def run(self) -> None:
        public = list(headers_spec.INDEXABLE)
        for path in public:
            self.page(path)
        titles = [r["title"] for r in self.table]
        descs = [r["description"] for r in self.table]
        dupes = sorted({t for t in titles if titles.count(t) > 1} | {d for d in descs if descs.count(d) > 1})
        self.add("titles and descriptions are unique", [f"used twice: {d!r}" for d in dupes])
        self.private()
        self.cards()
        self.icons_and_manifest()
        self.robots(public)
        self.sitemap(public)
        self.not_found()


def serve_dist(dist: Path):
    """The built tree over HTTP with web/site/tests/serve.py (files as built: no includes or placeholders added)."""
    sys.path.insert(0, str(ROOT / "web" / "site" / "tests"))
    import serve
    server, origin = serve.make_server(serve.options(["--port", "0", "--dist", str(dist)]))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, origin


def built_origin(dist: Path) -> str:
    m = re.search(r"^Sitemap: (\S+)/sitemap\.xml$", (dist / "robots.txt").read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"{dist}/robots.txt names no sitemap: is it a tree built by tools/build.py?")
    return m[1]


def report(checker: Checker, json_out: Path | None) -> int:
    failures = 0
    for r in checker.results:
        print(f"{r['result']} {r['check']}" + "".join(f"\n     {p}" for p in r["problems"])
              + "".join(f"\n     note: {n}" for n in r["notes"]))
        failures += r["result"] == "FAIL"
    print(f"\n{'Path':<12} {'Title (characters)':<62} Description (characters)")
    for row in checker.table:
        print(f"{row['path']:<12} {row['title']} ({row['title_len']})\n{'':<12} {row['description']} ({row['description_len']})")
    passed = sum(r["result"] == "PASS" for r in checker.results)
    skipped = sum(r["result"] == "SKIP" for r in checker.results)
    print(f"check-seo: {'PASS' if not failures else 'FAIL'} ({passed} passed, {failures} failed, {skipped} skipped; "
          f"fetched from {checker.origin}, tags on {checker.expect})")
    if json_out:
        json_out.write_text(json.dumps({"origin": checker.origin, "expect_origin": checker.expect, "caddy": checker.caddy,
                                        "results": checker.results, "pages": checker.table}, indent=1) + "\n",
                            encoding="utf-8")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description="search and link-preview checks")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--origin", default="https://hidebox.app", help="a running site (the live one by default)")
    where.add_argument("--dist", type=Path, help="a tree built by tools/build.py, served here without Caddy")
    where.add_argument("--local", nargs="?", const="", metavar="SSH_HOST",
                       help="build the working tree and serve it with the production Caddyfile on the server's throwaway stack")
    p.add_argument("--expect-origin", help="the origin the tags must name (default: the one fetched from, or the tree's)")
    p.add_argument("--json", type=Path, help="also write the results here")
    args = p.parse_args()
    if args.local is not None:
        import tempfile
        import harness
        from localstack import LocalStack, stub_build
        with tempfile.TemporaryDirectory(prefix="mutis-seo-") as tmp, \
                LocalStack(args.local or harness.SSH_HOST, stub_build(Path(tmp) / "dist")) as stack:
            checker = Checker(stack.web, args.expect_origin or stack.web, caddy=True)
            checker.run()
        return report(checker, args.json)
    if args.dist:
        server, origin = serve_dist(args.dist.resolve())
        try:
            checker = Checker(origin, args.expect_origin or built_origin(args.dist), caddy=False)
            checker.run()
        finally:
            server.shutdown()
        return report(checker, args.json)
    checker = Checker(args.origin, args.expect_origin or args.origin, caddy=True)
    checker.run()
    return report(checker, args.json)


if __name__ == "__main__":
    sys.exit(main())
