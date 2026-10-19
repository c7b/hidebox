# SPDX-License-Identifier: MIT
"""Checks that need only the files: licence headers, CSP-safe markup, banned words, numbers that
must come from /config, SEO metadata, trademark rules, contrast, partials, the privacy inventory;
and one that needs the network: security.txt's GitHub contact answers a visitor who isn't signed in.
Each check returns a list of problems (empty = pass), or None for SKIP. Python standard library only."""
import importlib.util
import itertools
import json
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import llms_full
import variants

WEB = Path(__file__).resolve().parents[2]
SITE, SHARED = WEB / "site", WEB / "shared"
PAGES = sorted((SITE / "pages").glob("*.html"))
PARTIALS = sorted((SHARED / "partials").glob("*.html"))
JS = sorted((SITE / "js").glob("*.js")) + sorted(SHARED.glob("*.js"))
PLACEHOLDERS = {"ORIGIN", "GIT_SHA", "VERSION", "BUILD_DATE", "NETWORK", "SECURITY_DROP_URL", "REPO_URL", "SRI", "BRAND"}
DATA_FILES = {".json", ".png", ".ico", ".webp", ".avif", ".woff2", ".bin", ".webmanifest", ".pyc", ".webm", ".mp4"}
NOT_SOURCE = {"OFL.txt", "NOTICE", "llms.txt", "llms-full.txt"}

# 11-brand §7.4 (and 12-integration "not promises"); "encriptado" per §7.7. Word-bounded, any case.
BANNED = ["seamless", "revolutionary", "game-changer", "cutting-edge", "next-gen", "unlock", "supercharge", "empower",
          "elevate", "leverage", "harness", "delve", "dive in", "in today's digital world", "in an era of",
          "military-grade", "bank-level", "unhackable", "100% secure", "100% private", "fully anonymous", "untraceable",
          "trustless", "zero-knowledge", "decentralized storage", "censorship-resistant", "your data, your rules",
          "peace of mind", "magic", "magically", "effortless", "robust", "world-class", "Web3", "to the moon", "LFG",
          "WAGMI", "XTR", "mining TARI", "Ootle chain", "Tari L3", "Emoji ID", "vault",
          "We see nothing", "We say nothing", "nothing left", "not anywhere", "no account to hack",
          "two independent indexers", "zero third-party runtime dependencies", "protects you from a malicious",
          "instead of through us", "gone forever", "deleted forever", "provably deleted", "vanished", "sealed file",
          "not promises", "encriptado", "encriptar"]


class Doc(HTMLParser):
    """Text, tags and attributes of one HTML file; text inside [hidden]/[data-v] is tracked separately."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.main_text = [], [], []
        self.stack, self.in_main = [], 0
        self.titles, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag == "main":
            self.in_main += 1
        if tag in ("br", "img", "input", "meta", "link", "use", "path", "col", "source"):
            return
        self.stack.append((tag, "data-v" in a))

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main -= 1
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if any(v for _, v in self.stack):
            return
        top = self.stack[-1][0] if self.stack else ""
        if top == "title":
            self.titles.append(data)
        elif top == "script":
            self.scripts.append(data)
            return
        elif top == "style":
            return
        self.text.append(data)
        if self.in_main:
            self.main_text.append(data)


def parse(path):
    d = Doc()
    d.feed(path.read_text())
    return d


def attr(doc, tag, **match):
    return [a for t, a in doc.tags if t == tag and all(a.get(k) == v for k, v in match.items())]


def check_spdx():
    problems = []
    for f in sorted(p for p in (WEB / "site").rglob("*") if p.is_file()) + sorted(p for p in SHARED.rglob("*") if p.is_file()):
        if f.suffix in DATA_FILES or f.name in NOT_SOURCE or {"fixtures", "shots", "__pycache__"} & set(f.parts):
            continue
        head = f.read_text().splitlines()[:3]
        if not any("SPDX-License-Identifier: MIT" in line for line in head[:2] if line):
            problems.append(f"{f.relative_to(WEB)}: no SPDX-License-Identifier: MIT in its first lines")
    return problems


FORBIDDEN_JS = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function|setTimeout\(\s*['\"`]")


def check_js_sinks():
    return [f"{f.relative_to(WEB)}: {m.group(0)}" for f in JS for m in FORBIDDEN_JS.finditer(f.read_text())]


def check_markup():
    problems = []
    for f in PAGES + PARTIALS + sorted((SITE / "og").glob("*.html")):
        text = f.read_text()
        name = f.relative_to(WEB)
        if re.search(r"\sstyle=", text):
            problems.append(f"{name}: style attribute")
        if re.search(r"\son[a-z]+=", text):
            problems.append(f"{name}: inline event handler")
        if "http://" in text:
            problems.append(f"{name}: http:// URL")
        for m in re.finditer(r"<(script|link)\b[^>]*\b(?:src|href)=\"(https?:[^\"]+)\"", text):
            problems.append(f"{name}: absolute URL in <{m[1]}>: {m[2]}")
        for m in re.finditer(r"<script\b([^>]*)>", text):
            if "src=" not in m[1] and 'type="application/ld+json"' not in m[1]:
                problems.append(f"{name}: inline script")
        for m in re.finditer(r"<!--#include ([a-z0-9-]+(?:\.svg)?)-->", text):
            if not (SHARED / "partials" / (m[1] if m[1].endswith(".svg") else f"{m[1]}.html")).is_file():
                problems.append(f"{name}: include {m[1]} has no partial")
        for m in re.finditer(r"\{\{([A-Z_]+)\}\}", text):
            if m[1] not in PLACEHOLDERS:
                problems.append(f"{name}: unknown placeholder {m[0]}")
        for m in re.finditer(r"(?<!\{)\{([A-Z_]+)\}(?!\})", text):
            problems.append(f"{name}: {m[0]} has single braces, so the build leaves it as it is")
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
            try:
                json.loads(m[1])
            except ValueError as e:
                problems.append(f"{name}: JSON-LD doesn't parse: {e}")
    for f in sorted((SITE / "css").glob("*.css")) + sorted(SHARED.glob("*.css")):
        if re.search(r"url\(\s*['\"]?https?:", f.read_text()):
            problems.append(f"{f.relative_to(WEB)}: absolute URL in CSS")
    return problems


def check_banned_words():
    problems = []
    files = PAGES + PARTIALS + [SITE / "static" / "llms.txt", SITE / "static" / "llms-full.txt"] + JS
    for f in files:
        text = f.read_text()
        for word in BANNED:
            for m in re.finditer(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.I):
                problems.append(f"{f.relative_to(WEB)}: banned phrase {m[0]!r}")
    return problems


def config_numbers():
    """Every number /config provides, formatted the ways stats.js prints it."""
    c = json.loads((SITE / "tests" / "fixtures" / "config.json").read_text())
    nums, seconds = set(), set()

    def walk(v, key=""):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            nums.add(v)
            if key.endswith("_s"):
                seconds.add(v)
        elif isinstance(v, str) and v.isdigit():
            nums.add(int(v))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
    walk({k: v for k, v in c.items() if k not in ("network_byte",)})
    out = set()
    for n in nums:
        if n < 2 or n in (2025, 2026):
            continue
        for unit, size in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
            if n >= size and n % (size // 10 or 1) == 0:
                out.add(f"{n / size:g} {unit}")
                break
        if n % 86400 == 0 and n >= 2 * 86400:
            out.add(f"{n // 86400} days")
        elif n % 3600 == 0 and n >= 3600:
            out.add(f"{n // 3600} hours")
        if n >= 1000:
            out.add(f"{n:,}")
        if n % 1000 == 0 and n < 10_000_000:
            out.add(f"{n / 1e6:g} tTARI")
    for n in seconds:   # durations stats.js prints in minutes, such as the SealLog cadence (12-integration §7.2)
        if n % 3600 and n % 60 == 0 and n >= 120:
            out |= {f"{n // 60} minutes", f"{n // 60} minutos"}
    return out


def check_config_numbers():
    """11-brand P-20 (3): a page may not type a number that /config provides."""
    problems = []
    numbers = config_numbers()
    for f in PAGES + PARTIALS:
        text = " ".join(" ".join(parse(f).text).split())
        for n in numbers:
            if re.search(rf"(?<![\w.,]){re.escape(n)}(?![\w])", text):
                problems.append(f"{f.relative_to(WEB)}: types {n!r}, which /config provides")
    return problems


def check_variables():
    """Every [data-v] and [data-when] names something stats.js knows; data-v lives inside [data-needs]."""
    src = (SITE / "js" / "stats.js").read_text()
    variables = set(re.findall(r"^  ([a-z0-9_]+): \['(?:config|stats)'", src, re.M))
    conditions = set(re.findall(r"^  ([a-z_]+): \(c\) =>", src, re.M))
    problems = []
    for f in PAGES + PARTIALS:
        text = f.read_text()
        for name in re.findall(r'data-v="([^"]+)"', text):
            if name not in variables:
                problems.append(f"{f.relative_to(WEB)}: unknown variable {name}")
        for name in re.findall(r'data-when="([a-z_]+)=', text):
            if name not in conditions:
                problems.append(f"{f.relative_to(WEB)}: unknown condition {name}")
        for m in re.finditer(r"<(\w+)[^>]*data-v=\"([^\"]+)\"[^>]*>([^<]*)<", text):
            if m[3].strip() and m[2] != "mainnet_date":
                problems.append(f"{f.relative_to(WEB)}: {m[2]} has typed fallback text {m[3]!r}")
    return problems


# M-04 and the SEO pass (docs/review/seo-1.md): what every page's head carries for search and for link previews. The
# share card stays og.png at 1200 x 630 on every site page; a later brand pass may swap its bytes, never its name.
ROBOTS_INDEX = "index, follow, max-image-preview:large"
# Lengths are measured as served: {{BRAND}} filled with the build's name (tools/build.py BRAND).
BRAND = re.search(r'^BRAND = "([^"]+)"', (WEB.parent / "tools" / "build.py").read_text(), re.M)[1]
CARD = {"og:image": "{{ORIGIN}}/og.png", "og:image:secure_url": "{{ORIGIN}}/og.png", "og:image:type": "image/png",
        "og:image:width": "1200", "og:image:height": "630"}
ICONS = [("icon", "/favicon.ico", None), ("icon", "/favicon-32.png", "image/png"), ("icon", "/favicon.svg", "image/svg+xml"),
         ("apple-touch-icon", "/apple-touch-icon.png", None), ("manifest", "/manifest.webmanifest", None)]


def meta(doc, **match):
    found = attr(doc, "meta", **match)
    return found[0].get("content") if found else None


def json_ld(text):
    return [json.loads(m[1]) for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)]


def ld_types(blocks):
    nodes = [n for b in blocks for n in (b.get("@graph") or [b])]
    return {n.get("@type"): n for n in nodes}


def check_seo():
    """Every page: one <h1>, <html lang="en"> (one language, so no hreflang), a title of at most 60 characters and a
    description of at most 155, both unique, the full Open Graph and Twitter card (og.png at 1200 x 630, absolute,
    with its alt; twitter:* the same as og:*), both theme colours, the app title and the icons (ICO, 32 px PNG, SVG,
    apple-touch-icon, manifest). Indexable pages also: the name last in the title, a robots meta that allows a large
    image preview, a canonical on {{ORIGIN}} that og:url repeats, and JSON-LD: the home its WebSite and
    SoftwareApplication, every other page a BreadcrumbList that ends on its canonical. The 404 page is noindex. The
    app's pages (web/app/view.html, app.html, drive.html) are noindex and carry a card with no og:url or canonical."""
    problems, titles, descs = [], {}, {}
    for f in PAGES:
        d, name, text = parse(f), f.relative_to(WEB), f.read_text()
        title = "".join(d.titles).strip()
        desc = meta(d, name="description") or ""
        html = attr(d, "html")
        robots = meta(d, name="robots") or ""
        indexable = f.stem != "404" and "noindex" not in robots
        if not title or len(title.replace("{{BRAND}}", BRAND)) > 60:
            problems.append(f"{name}: title missing or over 60 characters ({len(title.replace('{{BRAND}}', BRAND))})")
        titles.setdefault(title, []).append(str(name))
        if not desc or len(desc.replace("{{BRAND}}", BRAND)) > 155:
            problems.append(f"{name}: description missing or over 155 characters ({len(desc.replace('{{BRAND}}', BRAND))})")
        descs.setdefault(desc, []).append(str(name))
        if not html or html[0].get("lang") != "en":
            problems.append(f"{name}: <html lang> is not en")
        if sum(1 for t, _ in d.tags if t == "h1") != 1:
            problems.append(f"{name}: needs exactly one <h1>")
        for prop in ("og:title", "og:description", "og:image", "og:url", "og:type"):
            if not attr(d, "meta", property=prop):
                problems.append(f"{name}: missing {prop}")
        if not attr(d, "meta", name="twitter:card") or not attr(d, "meta", name="theme-color"):
            problems.append(f"{name}: missing twitter:card or theme-color")
        if f.stem == "404":
            if "noindex" not in robots:
                problems.append(f"{name}: 404 should be noindex")
        if f.stem == "v2":   # the preview keeps the head it was made with (check_v2 holds it: noindex, unlinked)
            continue
        for prop, value in CARD.items():
            if meta(d, property=prop) != value:
                problems.append(f"{name}: {prop} is {meta(d, property=prop)!r}, not {value!r}")
        if not meta(d, property="og:image:alt") or meta(d, property="og:site_name") != "{{BRAND}}":
            problems.append(f"{name}: og:image:alt missing or og:site_name not {{{{BRAND}}}}")
        for tw, og in (("twitter:title", "og:title"), ("twitter:description", "og:description"),
                       ("twitter:image", "og:image"), ("twitter:image:alt", "og:image:alt")):
            if meta(d, name=tw) != meta(d, property=og):
                problems.append(f"{name}: {tw} differs from {og}")
        if meta(d, name="twitter:card") != "summary_large_image":
            problems.append(f"{name}: twitter:card is not summary_large_image")
        if sorted(a.get("media", "") for a in attr(d, "meta", name="theme-color")) != \
                ["(prefers-color-scheme: dark)", "(prefers-color-scheme: light)"]:
            problems.append(f"{name}: needs a theme-color for light and one for dark")
        if meta(d, name="apple-mobile-web-app-title") != "{{BRAND}}":
            problems.append(f"{name}: no apple-mobile-web-app-title")
        links = [(a.get("rel"), a.get("href"), a.get("type")) for t, a in d.tags
                 if t == "link" and a.get("rel") in ("icon", "apple-touch-icon", "manifest")]
        if links != ICONS:
            problems.append(f"{name}: icons {links}, expected {ICONS}")
        for t, a in d.tags:
            if t == "img" and not a.get("alt"):
                problems.append(f"{name}: <img src={a.get('src')!r}> has no alt text")
            if t == "img" and not (a.get("width") and a.get("height")):
                problems.append(f"{name}: <img src={a.get('src')!r}> has no width and height")
        if not indexable:
            continue
        path = "/" if f.stem == "index" else f"/{f.stem}"
        canonical = [a.get("href") for a in attr(d, "link", rel="canonical")]
        if canonical != ["{{ORIGIN}}" + path]:
            problems.append(f"{name}: canonical {canonical}, expected {{{{ORIGIN}}}}{path}")
        if meta(d, property="og:url") != "{{ORIGIN}}" + path:
            problems.append(f"{name}: og:url is not the canonical")
        if not title.endswith(" · {{BRAND}}"):
            problems.append(f"{name}: title {title!r} doesn't end with the name (' · {{{{BRAND}}}}')")
        if robots != ROBOTS_INDEX:
            problems.append(f"{name}: robots meta {robots!r}, expected {ROBOTS_INDEX!r}")
        try:
            types = ld_types(json_ld(text))
        except ValueError:
            continue   # check_markup reports it
        if f.stem == "index":
            app = types.get("SoftwareApplication", {})
            if "WebSite" not in types or app.get("name") != "{{BRAND}}" or app.get("operatingSystem") != "Any (web browser)" \
                    or app.get("offers", {}).get("price") != "0" or "aggregateRating" in app or "review" in app:
                problems.append(f"{name}: JSON-LD needs the WebSite and the SoftwareApplication ({{{{BRAND}}}}, any browser, "
                                "free; no rating or review, since there are none to show)")
        else:
            items = types.get("BreadcrumbList", {}).get("itemListElement", [])
            if [i.get("item") for i in items] != ["{{ORIGIN}}/", "{{ORIGIN}}" + path]:
                problems.append(f"{name}: JSON-LD BreadcrumbList should be Home then {{{{ORIGIN}}}}{path}")
    for kind, seen in (("title", titles), ("description", descs)):
        for value, files in seen.items():
            if len(files) > 1:
                problems.append(f"{kind} {value!r} used by {files}")
    # The public pages are a fixed set (tests/e2e/headers_spec.py INDEXABLE, which D-01 and tools/check-seo.py read): a
    # public page turned noindex, or a new page that isn't, fails here before it skips the rules above.
    public = sorted(indexable_paths())
    if public != sorted(public_pages()):
        problems.append(f"the indexable pages are {public}, tests/e2e/headers_spec.py INDEXABLE says {sorted(public_pages())}")
    # The app's pages (a shared link, a drop, the drive): noindex, and a preview card with no address in it (no
    # og:url, no canonical: one page serves every link, and a link's id is no business of a preview).
    cards = {"view": "{{ORIGIN}}/og-s.png", "app": "{{ORIGIN}}/og.png", "drive": "{{ORIGIN}}/og.png"}
    for page, card in cards.items():
        f = WEB / "app" / f"{page}.html"
        d, name = parse(f), f.relative_to(WEB)
        if "noindex" not in (meta(d, name="robots") or ""):
            problems.append(f"{name}: not noindex")
        if attr(d, "meta", property="og:url") or attr(d, "link", rel="canonical"):
            problems.append(f"{name}: og:url or a canonical (a preview must not name the link)")
        for prop, value in CARD.items():
            if meta(d, property=prop) != value.replace("/og.png", card.removeprefix("{{ORIGIN}}")):
                problems.append(f"{name}: {prop} is {meta(d, property=prop)!r}")
        for tw, og in (("twitter:title", "og:title"), ("twitter:description", "og:description"),
                       ("twitter:image", "og:image"), ("twitter:image:alt", "og:image:alt")):
            if not meta(d, property=og) or meta(d, name=tw) != meta(d, property=og):
                problems.append(f"{name}: {tw} differs from {og}")
    return problems


def check_trademark():
    """Spec §13.5: no Tari marks in names, classes, ids; ™ on the first mention; the mandatory lines."""
    problems = []
    for f in sorted(p for p in (WEB / "site").rglob("*") if p.is_file()) + sorted(p for p in SHARED.rglob("*") if p.is_file()):
        if re.search(r"tari|ootle|xtm", f.name, re.I):
            problems.append(f"{f.relative_to(WEB)}: Tari mark in a file name")
    css = "".join(p.read_text() for p in list((SITE / "css").glob("*.css")) + list(SHARED.glob("*.css")))
    for m in re.finditer(r"[.#]([a-zA-Z][\w-]*)", css):
        if re.search(r"tari|ootle|xtm", m[1], re.I) and m[1] not in ("tari-purple", "tari-lime"):
            problems.append(f"CSS selector {m[0]} uses a Tari mark")
    for f in PAGES + PARTIALS:
        for t, a in parse(f).tags:
            if re.search(r"tari|ootle|xtm", a.get("class") or "", re.I):
                problems.append(f"{f.relative_to(WEB)}: class={a['class']!r}")
    for f in PAGES:
        main = " ".join(parse(f).main_text)
        first = re.search(r"\bTari\b(™)?", main)
        if first and not first[1]:
            problems.append(f"{f.relative_to(WEB)}: first mention of Tari in the page has no ™")
    required = ["Built on the Tari™ Ootle testnet.", "It is not affiliated with, endorsed by, or sponsored by Tari Labs, the Tari Council, or the Tari project.", "“Tari” is a trademark of Tari Labs. All rights reserved."]
    text = (SHARED / "partials" / "footer.html").read_text().replace("<br>", "")   # site v4: one sentence a line
    problems += [f"partials/footer.html: missing mandatory line {line!r}" for line in required if line not in text]
    for f in PAGES:
        if "<!--#include footer-->" not in f.read_text():
            problems.append(f"{f.relative_to(WEB)}: no footer (mandatory lines)")
    # No claim of official status: every sentence that uses those words must be a question or a denial.
    for f in PAGES + PARTIALS:
        for sentence in re.split(r"(?<=[.?!])\s+", " ".join(" ".join(parse(f).text).split())):
            if re.search(r"\b(official (partner|project|app|product)|partner(ed)? (of|with)|(endorsed|supported|sponsored) by Tari)\b",
                         sentence, re.I) and not re.search(r"\?|\bnot\b|\bno\b", sentence, re.I):
                problems.append(f"{f.relative_to(WEB)}: {sentence[:90]!r} reads as a claim of official status")
    return problems


def check_partials():
    """The footer repeats the status line; they must not drift. The header (site v2, 17-site-brief §2.1) holds
    the name, How it works, For judges (Under the hood left the nav for the footer), the GitHub link to the
    repository (site/share), the light switch, and Open your drive (site v3: one label, always on): no status line."""
    problems = []
    line = (SHARED / "partials" / "status-line.html").read_text().split("\n", 1)[1].strip()
    header = (SHARED / "partials" / "header.html").read_text()
    links = re.findall(r'<a\b[^>]*href="([^"]+)"', header)
    labels = re.findall(r'data-testid="head-(?:make|open)">([^<]+)<', header)
    if links != ["/", "/how", "/judges", "{{REPO_URL}}", "/drive?make", "/drive"] or "data-theme-toggle" not in header \
            or 'aria-label="Lights"' not in header or 'aria-label="Source code on GitHub"' not in header \
            or labels != ["Open your drive", "Open your drive"]:
        problems.append("partials/header.html: the header is the wordmark, How it works, For judges, Source code on GitHub "
                        "(the repository), the Lights switch and Open your drive (to /drive?make, or /drive with a drive)")
    footer = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', (SHARED / "partials" / "footer.html").read_text())
    if [label for _, label in footer] != ["How it works", "For judges", "Under the hood", "The fine print", "My drive"]:
        problems.append(f"partials/footer.html: the footer links are How it works, For judges, Under the hood, The fine print, My drive, not {footer}")
    for part in ("footer",):
        if line not in (SHARED / "partials" / f"{part}.html").read_text():
            problems.append(f"partials/{part}.html: status line differs from status-line.html")
    if (SHARED / "brand" / "favicon.svg").read_bytes() != (SITE / "static" / "favicon.svg").read_bytes():
        problems.append("static/favicon.svg differs from shared/brand/favicon.svg")
    return problems




def check_ghost():
    """16-drive-design §0 (no ghost): no served page or partial shows the ghost. No
    page links /shared/ghost.css, includes the ghost templates or the ghost partial, or holds a data-ghost
    element; the link and task pages (app/view.html, app/app.html) draw a Lucide tile instead."""
    problems = []
    app_pages = sorted((WEB / "app").glob("*.html"))
    for f in PAGES + PARTIALS + app_pages:
        text = f.read_text()
        for needle in ("/shared/ghost.css", "<!--#include ghost-templates-->", "<!--#include ghost.svg-->", "data-ghost="):
            if needle in text:
                problems.append(f"{f.relative_to(WEB)}: shows the ghost ({needle})")
    return problems


def check_privacy_inventory():
    schema = WEB.parent / "server" / "mutis" / "schema.sql"
    if not schema.is_file():
        return []
    tables = re.findall(r"CREATE TABLE (\w+)", schema.read_text())
    problems = []
    text = (SITE / "pages" / "fine-print.html").read_text()
    problems += [f"pages/fine-print.html: table {t} is not listed" for t in tables if f"<code>{t}</code>" not in text]
    return problems


def _rgb(value, tokens):
    value = value.strip()
    while value.startswith("var("):
        value = tokens[value[4:-1].strip()]
    if value.startswith("#"):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)), 1.0
    m = re.match(r"rgb\((\d+) (\d+) (\d+) / ([.\d]+)\)", value)
    return (int(m[1]), int(m[2]), int(m[3])), float(m[4])


def _lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    (f, a), (b, _) = fg, bg
    mixed = tuple(round(a * x + (1 - a) * y) for x, y in zip(f, b))
    hi, lo = sorted((_lum(mixed), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_contrast():
    """M-03: the 11-brand §13.2 table, recomputed from tokens.css."""
    css = (SHARED / "tokens.css").read_text()
    blocks = re.findall(r"(:root[^{]*|@media[^{]*\{\s*:root[^{]*)\{([^}]*)\}", css)
    light, dark = {}, {}
    for selector, body in blocks:
        if "contrast" in selector:
            continue
        decls = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))
        target = dark if "dark" in selector else light
        target.update(decls)
    dark = {**light, **dark}
    problems = []
    for theme, tokens in (("light", light), ("dark", dark)):
        for bg in ("--bg", "--bg-raised", "--bg-sunken"):
            back = _rgb(tokens[bg], tokens)
            for fg, need in (("--fg", 7), ("--fg-2", 4.5), ("--pay-text", 4.5), ("--ok-text", 4.5), ("--exit-text", 4.5), ("--line", 3)):
                ratio = contrast(_rgb(tokens[fg], tokens), back)
                if ratio < need:
                    problems.append(f"{theme}: {fg} on {bg} is {ratio:.2f}, needs {need}")
        for fg, bg, need in (("--on-pay", "--pay", 4.5), ("--on-ok", "--ok", 4.5), ("--on-exit", "--exit", 4.5)):
            ratio = contrast(_rgb(tokens[fg], tokens), _rgb(tokens[bg], tokens))
            if ratio < need:
                problems.append(f"{theme}: {fg} on {bg} is {ratio:.2f}, needs {need}")
    # site v2 (17-brand.md, "Measured pairs"): the brand fill's label, brand text on every surface it sits on,
    # muted text on the second surface and on the brand tint, the brand fill and icon against what is behind them
    for theme, tokens in (("light", light), ("dark", dark)):
        for fg, bg, need in (("--on-brand", "--brand-solid", 4.5), ("--on-brand", "--brand-solid-hover", 4.5),
                             ("--brand-text", "--bg", 4.5), ("--brand-text", "--bg-alt", 4.5), ("--brand-text", "--bg-raised", 4.5),
                             ("--brand-text", "--brand-subtle", 4.5), ("--fg", "--brand-subtle", 7), ("--fg-2", "--brand-subtle", 4.5),
                             ("--fg-2", "--bg-alt", 4.5), ("--fg", "--bg-alt", 7), ("--brand-text", "--brand-tile", 3),
                             # site v3: the lime fill's label at 7:1 (AAA), and its outline against the page: the
                             # lime-700 edge on light pages (lime on white is 1.21:1), the fill itself on dark ones
                             ("--on-brand", "--brand-solid", 7),
                             ("--brand-edge" if tokens["--brand-edge"] != "transparent" else "--brand-solid", "--bg", 3)):
            ratio = contrast(_rgb(tokens[fg], tokens), _rgb(tokens[bg], tokens))
            if ratio < need:
                problems.append(f"{theme}: {fg} on {bg} is {ratio:.2f}, needs {need}")
    for theme, tokens in (("light", light), ("dark", dark)):
        tari = contrast(_rgb(tokens["--tari-text"], tokens), _rgb(tokens["--bg"], tokens))
        if tari < 4.5:
            problems.append(f"{theme}: Tari text on the page is {tari:.2f}, needs 4.5")
    return problems


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def check_static():
    s = SITE / "static"
    problems = []
    robots = (s / "robots.txt").read_text()
    for path in ("/s/", "/p/", "/drive", "/t$", "/api/", "/locker", "/inbox", "/send", "/watch", "/upgrade", "/verify"):
        if f"Disallow: {path}\n" not in robots:
            problems.append(f"robots.txt: no Disallow: {path}")
    for path in ("/t", "/s/abc", "/p/abc", "/drive", "/drive/received", "/api/v1/stats/wall", "/api/v1/canary", "/locker", "/verify/tx/1"):
        if robots_allows(robots, path):
            problems.append(f"robots.txt: {path} is not disallowed")
    # A drop page is public by design (it carries noindex itself); the public config and numbers are
    # what the pages fill in, so a crawler that renders them may read them.
    for path in ("/d/abc", "/api/v1/config", "/api/v1/stats"):
        if not robots_allows(robots, path):
            problems.append(f"robots.txt: {path} is disallowed")
    problems += [f"robots.txt: blocks the indexable page {path}" for path in indexable_paths() if not robots_allows(robots, path)]
    for bot in PREVIEW_BOTS:
        for path in ("/", "/how", "/s/abc", "/p/abc", "/d/abc", "/t", "/drive"):
            if not robots_allows(robots, path, bot):
                problems.append(f"robots.txt: {bot} may not read {path} (it draws a link's preview card)")
        if robots_allows(robots, "/api/v1/stats/wall", bot):
            problems.append(f"robots.txt: {bot} may read the API")
    for path in ("/s/abc", "/p/abc", "/drive", "/api/v1/canary"):
        if robots_allows(robots, path, "Googlebot"):
            problems.append(f"robots.txt: a search crawler (Googlebot) may read {path}")
    if "Sitemap: {{ORIGIN}}/sitemap.xml" not in robots:
        problems.append("robots.txt: no Sitemap line")
    sec = (s / ".well-known" / "security.txt").read_text()
    # Two contacts, in order of preference (RFC 9116): the dead drop, then GitHub's private advisory form.
    # RFC 9116 wants every Contact to work; check_security_contacts asks GitHub, as a stranger, that it does.
    for field in ("Contact: {{SECURITY_DROP_URL}}", f"Contact: {{{{REPO_URL}}}}{ADVISORY_PATH}", "Expires: ",
                  "Preferred-Languages: en", "Policy: {{ORIGIN}}/made#disclosure", "Canonical: {{ORIGIN}}/.well-known/security.txt"):
        if field not in sec:
            problems.append(f"security.txt: missing {field!r}")
    contacts = [line.split(":", 1)[1].strip() for line in sec.splitlines() if line.startswith("Contact:")]
    if contacts != ["{{SECURITY_DROP_URL}}", "{{REPO_URL}}" + ADVISORY_PATH]:
        problems.append(f"security.txt: Contact lines should be the drop, then the advisory form; found {contacts}")
    manifest = json.loads((s / "manifest.webmanifest").read_text())
    for key in ("id", "name", "short_name", "description", "lang", "start_url", "scope", "display", "theme_color",
                "background_color", "icons"):
        if not manifest.get(key):
            problems.append(f"manifest.webmanifest: no {key}")
    if manifest.get("name") != "{{BRAND}}" or manifest.get("short_name") != "{{BRAND}}" or manifest.get("start_url") != "/":
        problems.append("manifest.webmanifest: name and short_name are {{BRAND}}, start_url is /")
    for icon in manifest["icons"]:
        if not (s / icon["src"].lstrip("/")).is_file():
            problems.append(f"manifest icon {icon['src']} missing")
    if not {"192x192", "512x512"} <= {i.get("sizes") for i in manifest["icons"]}:
        problems.append("manifest.webmanifest: needs a 192 px and a 512 px icon")
    if not any(i == {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"} for i in manifest["icons"]):
        problems.append("manifest: no maskable icon (/icon-maskable-512.png, 512x512, purpose maskable)")
    for name, size, limit in (("og.png", (1200, 630), 150 * 1024), ("og-s.png", (1200, 630), 150 * 1024),
                              ("icon-192.png", (192, 192), None), ("icon-512.png", (512, 512), None),
                              ("icon-maskable-512.png", (512, 512), None),
                              ("apple-touch-icon.png", (180, 180), None), ("favicon-32.png", (32, 32), None)):
        f = s / name
        if not f.is_file() or png_size(f) != size:
            problems.append(f"{name}: missing or not {size}")
        elif limit and f.stat().st_size > limit:
            problems.append(f"{name}: over {limit} bytes")
    ico = (s / "favicon.ico").read_bytes() if (s / "favicon.ico").is_file() else b""
    if ico[:4] != b"\0\0\1\0" or [ico[6 + 16 * i] for i in range(int.from_bytes(ico[4:6], "little"))] != [16, 32, 48]:
        problems.append("favicon.ico: missing, not an ICO, or not the 16, 32 and 48 px tile (Bing and unfurlers ask for it by name)")
    for page in PAGES + sorted((WEB / "app").glob("*.html")):
        for tag in re.findall(r'<link rel="icon" href="/favicon\.ico"[^>]*>', page.read_text()):
            if 'sizes="16x16 32x32 48x48"' not in tag:
                problems.append(f"{page.relative_to(WEB)}: {tag} (the ICO holds 16, 32 and 48 px)")
    llms = (s / "llms.txt").read_text()
    if not llms.startswith("# {{BRAND}}\n") or "private drive" not in llms or "dead-drop" not in llms:
        problems.append("llms.txt: not the spec §13.4 shape (the drive's, 16-drive-design §11)")
    for fact in ("send_mode=direct", "send_mode=relay", "seallog=on", "pay_to_open=on"):
        if f"{{when:{fact}}}" not in llms:
            problems.append(f"llms.txt: no line for {fact} (tools/variants.py keeps the ones true here)")
    fonts = SHARED / "fonts"
    for name in ("MutisScript-Regular.woff2", "MutisScript-Bold.woff2", "MutisScriptCode-Regular.woff2"):
        if (fonts / name).read_bytes()[:4] != b"wOF2":
            problems.append(f"fonts/{name}: not WOFF2")
    ofl = (fonts / "OFL.txt").read_text()
    if "Reserved Font Name Courier Prime." not in ofl or "SIL OPEN FONT LICENSE" not in ofl.upper():
        problems.append("fonts/OFL.txt: missing the copyright line or the licence")
    if "renamed as the licence requires" not in (fonts / "NOTICE").read_text():
        problems.append("fonts/NOTICE: missing the rename notice")
    return problems


ADVISORY_PATH = "/security/advisories/new"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _anonymous_get(url: str):
    """(status, Location, body) of one GET with no cookies, no credentials and no redirect followed."""
    request = urllib.request.Request(url, headers={"User-Agent": "mutis-site-check/1", "Accept": "*/*"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=20) as r:
            return r.status, r.headers.get("Location"), r.read(65536)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), b""


def check_security_contacts():
    """security.txt's second Contact, GitHub's private advisory form, must work for someone who isn't
    signed in: the URL answers 200, or a 302 to a github.com page that answers 200 (GitHub's sign-in
    page, which returns to the form), and GitHub's public API says private vulnerability reporting is on.
    The repository is the configuration's `repo_url` (the fixture's, which is the default). Needs the
    network: without it the check is reported as SKIP, never as PASS."""
    repo = json.loads((SITE / "tests" / "fixtures" / "config.json").read_text())["repo_url"].rstrip("/")
    repo_url = urllib.parse.urlsplit(repo)
    if repo_url.scheme != "https" or repo_url.netloc != "github.com" or repo_url.path.count("/") != 2:
        return [f"repo_url {repo!r} is not https://github.com/<owner>/<name>; security.txt's advisory Contact needs one"]
    url, problems = repo + ADVISORY_PATH, []
    try:
        status, location, _ = _anonymous_get(url)
        if status == 302 and location:
            target = urllib.parse.urljoin(url, location)
            if urllib.parse.urlsplit(target).netloc != "github.com":
                problems.append(f"{url}: 302 to {target}, off github.com")
            else:
                final, _, _ = _anonymous_get(target)
                if final != 200:
                    problems.append(f"{url}: 302 to {target}, which answers {final}")
        elif status != 200:
            problems.append(f"{url}: answers {status} to a visitor who isn't signed in (is the repository public?)")
        status, _, body = _anonymous_get(f"https://api.github.com/repos{repo_url.path}/private-vulnerability-reporting")
        enabled = status == 200 and json.loads(body or b"{}").get("enabled") is True
        if not enabled:
            problems.append(f"GitHub's API: private vulnerability reporting is not on for {repo_url.path[1:]} ({status})")
    except (urllib.error.URLError, OSError):
        return None
    return problems


def robots_groups(robots: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """(user agents, rules) per group (RFC 9309): consecutive User-agent lines open a group, its rules follow."""
    groups, agents, rules = [], [], []
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, _, value = line.partition(":")
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
    Allow on a tie; * is any run, $ the end."""
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


# The bots that draw a link's preview card (robots.txt's second group): they may read a shared link's page, never the
# API; a search crawler that isn't named there (Googlebot) follows the * group.
PREVIEW_BOTS = ("Twitterbot", "facebookexternalhit", "Slackbot-LinkExpanding", "LinkedInBot", "Discordbot", "TelegramBot",
                "WhatsApp")


def public_pages():
    """headers_spec.INDEXABLE: the pages search engines may index (read from the file, as serve.py reads REDIRECTS)."""
    spec_file = WEB.parent / "tests" / "e2e" / "headers_spec.py"
    spec = importlib.util.spec_from_file_location("headers_spec", spec_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.INDEXABLE)


def indexable_paths():
    """The URL of every page the sitemap may list (not a 404, not noindex)."""
    out = []
    for f in PAGES:
        if f.stem == "404" or "noindex" in (meta(parse(f), name="robots") or ""):
            continue
        out.append("/" if f.stem == "index" else f"/{f.stem}")
    return out


# The server's own defaults (server/mutis/config.py): what the HTML must show before /config is read.
SERVER_DEFAULTS = {"send_mode": "relay", "proof": "wallet", "seallog": "off", "kept": "on", "snapshots": "weekly",
                   "security_drop": "off", "pay_to_open": "off", "folders": "off"}
DIRECT = {"send_mode": "direct", "proof": "proven", "seallog": "on", "kept": "on", "snapshots": "off",
          "security_drop": "on", "pay_to_open": "on", "folders": "on"}


def check_build_variants():
    """M11: the HTML ships the server's defaults; tools/variants.py sets another deployment's into the pages,
    and the llms-full.txt it writes then carries that deployment's disclosures (the sponsor-grant linkage)."""
    problems = []
    for f in PAGES:
        text = f.read_text()
        if variants.resolve(text, SERVER_DEFAULTS) != text:
            problems.append(f"{f.relative_to(WEB)}: a data-when variant's default doesn't match the server's defaults")
        for m in variants.VARIANT.finditer(variants.resolve(text, DIRECT)):
            hidden = bool(variants.HIDDEN.search(m[0]))
            if hidden == (DIRECT.get(m[1]) == m[2]):
                problems.append(f"{f.relative_to(WEB)}: {m[0][:70]} not resolved for direct mode")
    direct = llms_full.render(lambda name: variants.resolve((SITE / "pages" / f"{name}.html").read_text(), DIRECT))
    for phrase in ("sponsor wallet", "Pedersen", "official Tari library opens"):
        if phrase not in direct:
            problems.append(f"llms-full.txt for a direct, proven deployment lacks {phrase!r}")
    return problems


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)


# A button /judges names before the app has it would be listed here; once it is in
# web/app/i18n/en.json it must leave this list (the check says so), so the script can't drift from the
# app. It is empty: every button /judges names is in en.json.
PENDING_LABELS: set[str] = set()


def check_ui_strings():
    """/judges quotes the app's own words: every button it names (<b class="ui">) is one of the app's
    i18n strings ({placeholders} match anything), in both send modes as tools/variants.py builds the
    page, unless it is a label the app gains later in this phase (PENDING_LABELS). SKIP until the app
    writes web/app/i18n/."""
    problems = []
    i18n = WEB / "app" / "i18n" / "en.json"
    if not i18n.is_file():
        return None
    strings = json.loads(i18n.read_text())
    patterns = [re.compile(re.sub(r"\\\{[^}]*\\\}", ".*", re.escape(s.strip())) + "$") for s in _strings(strings)]
    known = lambda phrase: any(p.match(phrase) for p in patterns)
    problems += [f"PENDING_LABELS: “{label}” is in en.json now; take it off the list" for label in PENDING_LABELS if known(label)]
    for mode in ("relay", "direct"):
        for pay in ("off", "on"):
            text = variants.resolve((SITE / "pages" / "judges.html").read_text(), {"send_mode": mode, "pay_to_open": pay})
            text = re.sub(r"<div[^>]*\shidden[\s>].*?</div>", "", text, flags=re.S)
            text = re.sub(r"<span[^>]*\shidden[\s>].*?</span>", "", text)
            for phrase in re.findall(r'<b class="ui">(.*?)</b>', text):
                if phrase not in PENDING_LABELS and not known(phrase):
                    problems.append(f"pages/judges.html ({mode}, pay to open {pay}): names the button “{phrase}”, which web/app/i18n/en.json doesn't have")
            # 16-drive-design §10: two tracks of at most six steps, whichever way pay to open is set
            steps = [len(re.findall(r"<li>", ol)) for ol in re.findall(r'<ol class="steps">(.*?)</ol>', text, re.S)]
            if len(steps) != 2 or any(n > 6 for n in steps):
                problems.append(f"pages/judges.html (pay to open {pay}): the script is {steps} steps; at most 6 + 6 (16-drive-design §10)")
    return problems


def check_redirects():
    """The 301 map (tests/e2e/headers_spec.py REDIRECTS, the Caddyfile's): every old page is gone from
    pages/, and every target page and anchor exists."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("headers_spec", WEB.parent / "tests" / "e2e" / "headers_spec.py")
    headers_spec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(headers_spec)
    problems = []
    for old, new in headers_spec.REDIRECTS.items():
        if (SITE / "pages" / f"{old.strip('/')}.html").exists():
            problems.append(f"{old}: still a page, but it redirects to {new}")
        path, _, anchor = new.partition("#")
        if path == "/drive" or path.startswith("/drive/"):
            continue  # the drive's own pages (web/app/drive.html; the UI suite checks them)
        page = SITE / "pages" / f"{path.strip('/') or 'index'}.html"
        if not page.is_file():
            problems.append(f"{old} → {new}: no page {page.name}")
        elif anchor and f'id="{anchor}"' not in page.read_text():
            problems.append(f"{old} → {new}: {page.name} has no id=\"{anchor}\"")
    return problems


# A-06h (17-site-brief §1.2, docs/review/site-v3.md): the effects stay small and load late. motion.js (the reveals and
# the decode, site v3) at most 4 KB, stills.js (/how's stills replaying what they show) at most 2 KB, all gzip -9.
# field.js (the hero's WebGL grid) and pixel.js (the closing's pixel field) are not part of the v3 design
# (docs/review/promote-v3.md): no page asks for a WebGL field, and site.js names neither. The home's own stylesheet
# grows by at most 3 KB over home.css at the tag spooky-secrets-2026-10 as it was before site v2 (f89963c, 1,770 B):
# site v2 and v3 together; site/share raised that 3 KB by 256 B, for the share window drawn in depth so it reads as a
# picture (the owner's ask; 4,733 B before it). The home also loads v2.css and v3.css after
# home.css (its layout and its stills, each in its own V-01 / V-02 limit): the home's own stylesheets together (every
# /site/css/ file index.html links but site.css, each gzip -9 as served) stay at most 8,704 B (promote-v3.md: 8,303 B
# measured, home.css 4,128 + v2.css 3,185 + v3.css 990).
EFFECTS = {"motion.js": 4096, "stills.js": 2048}
GONE_EFFECTS = ("field.js", "pixel.js")
HOME_CSS_BEFORE, HOME_CSS_GROWTH = 1770, 3328
HOME_STYLES_LIMIT = 8704


def check_field_budget():
    """A-06h, the files' half (browser_checks has the loading half): motion.js at most 4,096 B and stills.js at most
    2,048 B gzip -9, no page, partial or stylesheet names them, and only site.js imports them, each with import();
    field.js and pixel.js are gone, nothing names them and no page or partial carries data-field or data-pixel (the v3
    design has no WebGL field); home.css at most 1,770 + 3,328 B gzip -9, and the home's own stylesheets (home.css,
    v2.css, v3.css) at most 8,704 B together."""
    import gzip
    problems, notes = [], []
    for name, limit in EFFECTS.items():
        size = len(gzip.compress((SITE / "js" / name).read_bytes(), 9))
        notes.append(f"{name} {size:,} B (at most {limit:,})")
        if size > limit:
            problems.append(f"js/{name} is {size:,} B gzip -9 (at most {limit:,})")
    home = len(gzip.compress((SITE / "css" / "home.css").read_bytes(), 9))
    if home > HOME_CSS_BEFORE + HOME_CSS_GROWTH:
        problems.append(f"css/home.css is {home:,} B gzip -9 (at most {HOME_CSS_BEFORE:,} + {HOME_CSS_GROWTH:,})")
    linked = re.findall(r'<link rel="stylesheet" href="/site/css/([a-z0-9-]+\.css)"', (SITE / "pages" / "index.html").read_text())
    own = [n for n in linked if n != "site.css"]
    if own != ["home.css", "v2.css", "v3.css"]:
        problems.append(f"pages/index.html: its own stylesheets are {own}, expected home.css, v2.css, v3.css in that order")
    styles = {n: len(gzip.compress((SITE / "css" / n).read_bytes(), 9)) for n in own if (SITE / "css" / n).is_file()}
    if sum(styles.values()) > HOME_STYLES_LIMIT:
        problems.append(f"the home's stylesheets are {sum(styles.values()):,} B gzip -9 together (at most {HOME_STYLES_LIMIT:,}): {styles}")
    site = (SITE / "js" / "site.js").read_text()
    for name in EFFECTS:
        for f in PAGES + PARTIALS + sorted((SITE / "css").glob("*.css")):
            if name in f.read_text():
                problems.append(f"{f.relative_to(WEB)} names {name} (it loads only from site.js, after the load event)")
        for f in JS:
            if f.name not in ("site.js", name) and name in f.read_text():
                problems.append(f"{f.relative_to(WEB)} imports {name} (only site.js may, with import())")
        if f"import('./{name}')" not in site or re.search(rf"^import .*{re.escape(name)}", site, re.M):
            problems.append(f"js/site.js: {name} loads with import('./{name}') only")
    for name in GONE_EFFECTS:
        if (SITE / "js" / name).exists():
            problems.append(f"js/{name} is back (the v3 design has no WebGL field)")
        for f in PAGES + PARTIALS + sorted((SITE / "css").glob("*.css")) + JS:
            if name in f.read_text():
                problems.append(f"{f.relative_to(WEB)} names {name} (the v3 design has no WebGL field)")
    for f in PAGES + PARTIALS:
        if re.search(r"\sdata-(field|pixel)\b", f.read_text()):
            problems.append(f"{f.relative_to(WEB)}: data-field or data-pixel (the v3 design has no WebGL field)")
    NOTES_STATIC.append(f"A-06h: {'; '.join(notes)}, gzip -9; home.css {home:,} B "
                        f"(was {HOME_CSS_BEFORE:,}, +{home - HOME_CSS_BEFORE:,} of {HOME_CSS_GROWTH:,}); the home's stylesheets "
                        f"{sum(styles.values()):,} B ({', '.join(f'{n} {b:,}' for n, b in styles.items())}; at most {HOME_STYLES_LIMIT:,})")
    return problems


NOTES_STATIC: list[str] = []


def check_shared_blocks():
    """Who sees what's four sides and the What's tTARI? box are written out on / and on /how (a partial
    would miss the build's copy variants and llms-full.txt); the two copies must not drift."""
    problems = []
    blocks = {"the four sides": r'<ul class="sides".*?</ul>', "What's tTARI?": r'<aside class="coin-box".*?</aside>'}
    home, how = ((SITE / "pages" / f"{n}.html").read_text() for n in ("index", "how"))
    for name, rx in blocks.items():
        a, b = (" ".join(m.group(0).split()) if (m := re.search(rx, page, re.S)) else None for page in (home, how))
        if not a or not b:
            problems.append(f"{name}: missing on {'/' if not a else '/how'}")
        elif a != b:
            problems.append(f"{name}: / and /how differ")
    return problems



def check_internal_links():
    """Every link from a site page or partial to another site page, or to an anchor (#id, /page#id), lands on
    a page and an id that exist (the drive's, the API's and static files are checked elsewhere)."""
    problems = []
    pages = {"/" if f.stem == "index" else f"/{f.stem}": f for f in PAGES}
    ids = {path: set(re.findall(r'\sid="([^"]+)"', f.read_text())) for path, f in pages.items()}
    partial_ids = set().union(*(re.findall(r'\sid="([^"]+)"', f.read_text()) for f in PARTIALS))
    for f in PAGES + PARTIALS:
        here = ("/" if f.stem == "index" else f"/{f.stem}") if f in PAGES else None
        for href in re.findall(r'<a\b[^>]*\shref="([^"]+)"', f.read_text()):
            path, _, anchor = href.partition("#")
            if href.startswith("#"):
                path = here
            elif not path.startswith("/") or path.startswith("//") or "." in path.rsplit("/", 1)[-1]:
                continue
            if path is None:   # a partial's own anchor: it lands on whichever page includes it
                continue
            path = path.split("?")[0].rstrip("/") or "/"
            if path not in pages:
                if not re.match(r"/(drive|verify|watch|status|releases)(/|$)|/s/|/api/", path):
                    problems.append(f"{f.relative_to(WEB)}: {href} is no page")
                continue
            if anchor and not anchor.startswith("pass=") and anchor not in ids[path] | partial_ids:
                problems.append(f"{f.relative_to(WEB)}: {href} has no id=\"{anchor}\" on {path}")
    return problems


# /how's stills replay what they show (js/stills.js, css/how.css). Each loop lasts 4 to 7 s and rests at least
# 1.5 s on its settled still before it starts over; the words that change are the app's own.
HOW_LOOP_MS, HOW_REST_MS = (4000, 7000), 1500


def check_how_loops():
    """/how's loops: every .still-frame[data-loop] is a picture nobody reads out (it, or its card, is aria-hidden) of
    4 to 7 s; its parts' data-beats are name@ms in order, inside the loop, with a rest of 1.5 s or more at the end; the
    words its states show (the upload stages and title, the Tari send's steps) are strings of web/app/i18n/en.json;
    and the page has one Pause motion switch (WCAG 2.2.2), hidden until stills.js shows it, outside every
    aria-hidden picture."""
    problems = []
    text = (SITE / "pages" / "how.html").read_text()
    frames = re.findall(r'<div class="still-frame"([^>]*)>(.*?)\n      </div>\n    </section>', text, re.S)
    if len(frames) != 5 or any("data-loop" not in a for a, _ in frames):
        problems.append(f"pages/how.html: {sum('data-loop' in a for a, _ in frames)} of its {len(frames)} stills loop (all five should)")
    for i, (attrs, inner) in enumerate(frames, 1):
        where = f"pages/how.html still {i}"
        length = int(m[1]) if (m := re.search(r'data-loop="(\d+)"', attrs)) else 0
        if not HOW_LOOP_MS[0] <= length <= HOW_LOOP_MS[1]:
            problems.append(f"{where}: a loop of {length} ms (4,000 to 7,000)")
        if 'aria-hidden="true"' not in attrs and not re.match(r'\s*<div class="ui-card[^"]*" aria-hidden="true">', inner):
            problems.append(f"{where}: neither the picture nor its card is aria-hidden")
        beats = [b.split() for b in re.findall(r'data-beats="([^"]*)"', inner)]
        if not beats:
            problems.append(f"{where}: nothing in it has data-beats")
        last = 0
        for part in beats:
            times = [int(b.split("@")[1]) if re.fullmatch(r"[a-z]+@\d+", b) else -1 for b in part]
            if -1 in times or times != sorted(times) or any(not 0 < x < length for x in times):
                problems.append(f"{where}: data-beats=\"{' '.join(part)}\" isn't name@ms in order inside the loop")
            last = max([last, *times])
        if beats and length - last < HOW_REST_MS:
            problems.append(f"{where}: rests {length - last} ms before it starts over (at least {HOW_REST_MS:,})")
    strings = json.loads((WEB / "app" / "i18n" / "en.json").read_text())
    patterns = [re.compile(re.sub(r"\\\{[^}]*\\\}", ".+", re.escape(s.strip())) + "$") for s in _strings(strings)]
    shown = re.findall(r'<span class="b-(?:wait|done|lock|send|ok)">(?:<svg.*?</svg>)?([^<]+)</span>', text)
    shown += re.findall(r'<li data-beats="[^"]*"><span class="dot">.*?</span>([^<]+)</li>', text)
    if len(shown) < 10:
        problems.append(f"pages/how.html: only {len(shown)} words of the loops found to check against the app")
    problems += [f"pages/how.html: the loop says “{w}”, which web/app/i18n/en.json doesn't" for w in sorted(set(shown))
                 if not any(p.match(w) for p in patterns)]
    switches = re.findall(r'<button type="button" class="loops" data-loops aria-label="Pause motion" aria-pressed="false" hidden>', text)
    if len(switches) != 1 or text.count("data-loops") != 1:
        problems.append("pages/how.html: needs one Pause motion switch (WCAG 2.2.2: the loops run longer than five seconds)")
    elif _under_aria_hidden(text, "data-loops"):
        problems.append("pages/how.html: the Pause motion switch sits inside an aria-hidden picture")
    return problems


def _under_aria_hidden(text, marker):
    """Whether the first element carrying the attribute `marker` has an aria-hidden="true" ancestor."""
    VOID = {"br", "img", "input", "meta", "link", "use", "path", "rect", "source", "col", "hr", "wbr"}

    class Walk(HTMLParser):
        stack, found = [], None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if marker in a and self.found is None:
                self.found = any(self.stack)
            if tag not in VOID:
                self.stack.append(a.get("aria-hidden") == "true")

        def handle_endtag(self, tag):
            if tag not in VOID and self.stack:
                self.stack.pop()
    w = Walk()
    w.stack = []
    w.feed(text)
    return bool(w.found)


# V-01 (docs/review/home-v2.md): /v2, the home with the product loops, is a preview at its own address. Its files
# have their own budget (it is outside M-01 and A-06, which stay the home's): each loop's WebM, MP4 and poster, the
# media folder, and its own stylesheet and script (gzip -9). The browser half (what loads when) is browser_checks.
V2_FILE_LIMITS = {".webm": 3_500_000, ".mp4": 512_000, ".png": 256_000}
V2_FOLDER_LIMIT = 12 * 1024 * 1024
V2_CODE_LIMITS = {"css/v2.css": 4096, "js/clips.js": 2048}
WEBM_TYPE = 'video/webm; codecs="vp9"'


def check_v2():
    """V-01, the files' half: /v2 is noindex, outside the JSON-LD graph, linked from no page, partial or static file,
    and has the home's links, variants and labels (its words stay the ones it was made with: the copy pass,
    docs/review/copy-1.md, changed the home's and left the preview's on purpose); each <video data-clip>
    is muted, autoplay, loop, playsinline, its sources waiting in data-src (WebM with its codec first, then MP4), the
    first with preload="metadata" and its poster, the rest preload="none" with data-poster and a lazy still for readers
    without JavaScript; every file they name exists, no other page names the media folder, and the budget holds."""
    import gzip
    problems = []
    v2 = SITE / "pages" / "v2.html"
    text = v2.read_text()
    d, home = parse(v2), parse(SITE / "pages" / "index.html")
    if not any("noindex" in a.get("content", "") for a in attr(d, "meta", name="robots")):
        problems.append("pages/v2.html: no <meta name=\"robots\" content=\"noindex\">")
    if "application/ld+json" in text:
        problems.append("pages/v2.html: carries JSON-LD (the preview is no part of the graph)")
    # and the same links, buttons, variants and labels in the body (the Pause motion switch is v2's own)
    keys = ("href", "data-when", "hidden", "data-testid", "aria-label", "aria-labelledby", "id", "role")
    def marks(doc):
        body = doc.tags[next(i for i, (tag, _) in enumerate(doc.tags) if tag == "body"):]
        return sorted(str((tag, [(k, a.get(k)) for k in keys if k in a])) for tag, a in body
                      if any(k in a for k in keys) and "data-loops" not in a)
    extra, missing = sorted(set(marks(d)) - set(marks(home))), sorted(set(marks(home)) - set(marks(d)))
    if marks(d) != marks(home):
        problems.append(f"pages/v2.html: its links, variants or labels differ from the home's: only in v2 {extra[:3]}, only on / {missing[:3]}")
    if not re.search(r'<button type="button" class="loops" data-loops aria-label="Pause motion" aria-pressed="false" hidden>', text):
        problems.append("pages/v2.html: no Pause motion switch (WCAG 2.2.2: the loops run longer than five seconds)")
    for f in [p for p in PAGES if p != v2] + PARTIALS + sorted((SITE / "static").rglob("*.txt")):
        body = f.read_text()
        if re.search(r'href="(\{\{ORIGIN\}\})?/v2[/"#?]', body) or "{{ORIGIN}}/v2" in body:
            problems.append(f"{f.relative_to(WEB)}: links to /v2 (the preview stays out of nav, footer, sitemap and the graph)")
    for f in [p for p in PAGES if p.name not in ("v2.html", "index.html")] + PARTIALS + sorted((SITE / "css").glob("*.css")) + JS:
        if "/site/media/" in f.read_text() and f.name not in ("v2.css", "clips.js"):
            problems.append(f"{f.relative_to(WEB)}: names /site/media/ (only /v2 and the home load media)")
    videos = re.findall(r"<video\b([^>]*)>(.*?)</video>\s*(<noscript>.*?</noscript>)?", text, re.S)
    if not videos:
        problems.append("pages/v2.html: no loops")
    for i, (attrs, inner, fallback) in enumerate(videos):
        a = dict(re.findall(r'([a-z-]+)(?:="([^"]*)")?', attrs))
        where = f"pages/v2.html video {i + 1}"
        for flag in ("data-clip", "muted", "autoplay", "loop", "playsinline"):
            if flag not in a:
                problems.append(f"{where}: no {flag}")
        if "src" in a:
            problems.append(f"{where}: a src on the video itself (the sources wait in data-src)")
        want = ("metadata", "poster") if i == 0 else ("none", "data-poster")
        if a.get("preload") != want[0] or want[1] not in a or ("poster" in a) != (i == 0):
            problems.append(f"{where}: needs preload=\"{want[0]}\" and {want[1]} (the hero's loop alone is asked for at load)")
        sources = re.findall(r"<source\b([^>]*)>", inner)
        kinds = [(re.search(r'data-src="([^"]+)"', s), re.search(r"type='([^']+)'|type=\"([^\"]+)\"", s)) for s in sources]
        if any(re.search(r"\ssrc=", s) for s in sources):
            problems.append(f"{where}: a <source> with src (it must wait in data-src)")
        types = [(m.group(1) or m.group(2)) if m else None for _, m in kinds]
        if types != [WEBM_TYPE, "video/mp4"]:
            problems.append(f"{where}: sources {types}, expected [{WEBM_TYPE!r}, 'video/mp4']")
        files = [m.group(1) for m, _ in kinds if m] + [a.get("poster") or a.get("data-poster") or ""]
        if i:
            still = re.fullmatch(r'<noscript><img class="still" src="([^"]+)" alt="" width="832" height="480" loading="lazy"></noscript>', fallback)
            if not still or still.group(1) != a.get("data-poster"):
                problems.append(f"{where}: no lazy still of its poster for readers without JavaScript")
        for url in files:
            if not url.startswith("/site/media/") or not (SITE / url.removeprefix("/site/")).is_file():
                problems.append(f"{where}: {url!r} is not a file in web/site/media/")
    media = sorted(p for p in (SITE / "media").rglob("*") if p.is_file())   # the folder's total counts the home's stills too
    for f in media:   # only two folders: /v2's loops (V-01, here) and the home's stills (V-02, check_home_stills)
        if f.parent not in (SITE / "media" / "motion", SITE / "media" / "v3"):
            problems.append(f"{f.relative_to(WEB)}: outside media/motion and media/v3 (V-01 and V-02 hold only those folders)")
    for f in [m for m in media if m.parent == SITE / "media" / "motion"]:
        limit = V2_FILE_LIMITS.get(f.suffix)
        if limit is None:
            problems.append(f"{f.relative_to(WEB)}: not a loop's WebM, MP4 or poster")
        elif f.stat().st_size > limit:
            problems.append(f"{f.relative_to(WEB)}: {f.stat().st_size:,} B (V-01: at most {limit:,})")
    folder = sum(f.stat().st_size for f in media)
    if folder > V2_FOLDER_LIMIT:
        problems.append(f"web/site/media: {folder:,} B (V-01: at most {V2_FOLDER_LIMIT:,})")
    code = []
    for rel, limit in V2_CODE_LIMITS.items():
        size = len(gzip.compress((SITE / rel).read_bytes(), 9))
        code.append(f"{rel} {size:,} B")
        if size > limit:
            problems.append(f"{rel}: {size:,} B gzip -9 (V-01: at most {limit:,})")
    NOTES_STATIC.append(f"V-01 files: {len(videos)} loops on /v2, web/site/media {folder:,} B in {len(media)} files "
                        f"(at most {V2_FOLDER_LIMIT:,}); {', '.join(code)} gzip -9")
    return problems


# V-02 (docs/review/home-v3.md): the stills first shown at /v3, /v2 with a still in place of every loop (the hero and
# the closing show the open box with the files rising out of it) and the open box as the mark. That page is
# the home (docs/review/promote-v3.md) and V-02 is the home's own image budget: each still's AVIF and
# WebP, the folder, the mark (the favicon), and v3.css (gzip -9), beside M-01 and A-06, which stay the home's.
# The browser half is browser_checks.check_home_stills.
V3_STILL_LIMITS = {".avif": 64_000, ".webp": 96_000}
V3_FOLDER_LIMIT = 512 * 1024
V3_MARK_LIMIT = 2048
V3_CODE_LIMITS = {"css/v3.css": 2048}
V3_STAGES = ["stage-a", "stage-c", "stage-b", "stage-d", "stage-end"]   # the hero, the four sections in page order
V3_BAD_SVG = re.compile(r"<(image|script|foreignObject|use|a|style|animate\w*|set|iframe)\b|href=|\son[a-z]+=|data:|url\(", re.I)
# the open box (docs/review/brand-kit-1.md): one filled outline, the sprite's i-hidebox; the favicon and the brand files
# draw the same path data, lime on the ink tile, so the mark can't drift between them
OPEN_BOX = re.compile(r'<symbol id="i-hidebox" viewBox="2\.801 1\.801 26\.399 29\.399"><path fill="currentColor" d="([^"]+)" /></symbol>')
# the wordmark (the same review): the header's name, from the sprite, hidden (the link carries the name)
WORDMARK = '<svg class="wm-word" aria-hidden="true" focusable="false"><use href="/shared/ui/icons.svg#i-wordmark"/></svg>'


def image_size(f):
    """(width, height) of a lossy WebP (no alpha), an AVIF (its ispe box) or a PNG, from the bytes; None otherwise."""
    data = f.read_bytes()
    if f.suffix == ".webp":
        if data[:4] != b"RIFF" or data[8:16] != b"WEBPVP8 ":
            return None
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if f.suffix == ".avif":
        at = data.find(b"ispe")
        if data[4:12] != b"ftypavif" or at < 0:
            return None
        return int.from_bytes(data[at + 8:at + 12], "big"), int.from_bytes(data[at + 12:at + 16], "big")
    if f.suffix == ".png" and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None


def check_home_stills():
    """V-02, the files' half, on the home (the v3 design since docs/review/promote-v3.md): / is indexable (no noindex)
    and dark first (<html data-theme="dark">, the light switch still works: browser_checks); no video, no loop and no
    WebGL field. Each of its five stages (the hero, What's different, Who sees what, Tari, the closing) is one
    <picture>: an AVIF then a WebP srcset of three widths with one sizes, an <img> with its width and height and alt
    text that says what it shows (the stage stays aria-hidden: the words beside it carry the meaning; the alt is for
    search and for a picture that doesn't load), the hero's with fetchpriority="high", every other one lazy; each
    candidate is a file whose pixels match its w descriptor and the img's ratio, within V-02's sizes; the closing names
    the hero's srcset and sizes (the browser reuses its bytes). The favicons are /favicon.ico (the open box's tile at 16, 32 and
    48 px, the one search engines and unfurlers ask for by name), /favicon-32.png (32 px) then /favicon.svg; the favicon
    and the brand files are the open box in clean SVG (no raster, script, link or data), and the header's tile draws it from the sprite. Every
    file in media/v3 is named by the home; the folder and v3.css stay in V-02; no page links /v3, which is a 301."""
    import gzip
    problems = []
    home_page = SITE / "pages" / "index.html"
    text = home_page.read_text()
    d = parse(home_page)
    if "noindex" in (meta(d, name="robots") or ""):
        problems.append("pages/index.html: noindex (the home is indexable)")
    if (attr(d, "html") or [{}])[0].get("data-theme") != "dark":
        problems.append("pages/index.html: not dark first (<html data-theme=\"dark\">, as the v3 design)")
    for f in [p for p in PAGES if p != home_page] + PARTIALS + sorted((SITE / "static").rglob("*.txt")) + [home_page]:
        body = f.read_text()
        if re.search(r'href="(\{\{ORIGIN\}\})?/v3[/"#?]', body) or "{{ORIGIN}}/v3" in body:
            problems.append(f"{f.relative_to(WEB)}: links to /v3 (a 301 to / since the v3 design became the home)")
    for gone in ("<video", "clips.js", "/site/media/motion/", "data-loops"):
        if gone in text:
            problems.append(f"pages/index.html: {gone!r} (the home has no loops: every stage is a still)")
    named = set()
    stages = re.findall(r'<div class="stage ([a-z-]+) is-still" aria-hidden="true">\s*<picture>(.*?)</picture>\s*</div>', text, re.S)
    if [s for s, _ in stages] != V3_STAGES or text.count("<picture>") != len(V3_STAGES):
        problems.append(f"pages/index.html: stills {[s for s, _ in stages]}, expected one <picture> on each of {V3_STAGES}")
    sets = {}
    for i, (stage, inner) in enumerate(stages):
        where = f"pages/index.html {stage}"
        sources = re.findall(r'<source type="(image/[a-z]+)" srcset="([^"]+)" sizes="([^"]+)">', inner)
        img = re.search(r'<img class="pic" src="([^"]+)" alt="([^"]+)" width="(\d+)" height="(\d+)" ([a-z]+)="([a-z]+)" decoding="async">', inner)
        if [s[0] for s in sources] != ["image/avif", "image/webp"] or len({s[2] for s in sources}) != 1 or not img:
            problems.append(f"{where}: needs an AVIF then a WebP <source> with one sizes, and <img class=\"pic\"> with alt text, width and height")
            continue
        load = (img.group(5), img.group(6))
        if load != (("fetchpriority", "high") if i == 0 else ("loading", "lazy")):
            problems.append(f"{where}: {'=' .join(load)} (the hero's picture is fetched first, with fetchpriority=\"high\"; every other one is lazy)")
        w, h = int(img.group(3)), int(img.group(4))
        sets[stage] = sources
        widths = []
        for kind, srcset, _ in sources:
            cands = [c.split() for c in srcset.split(",")]
            if len(cands) != 3 or any(len(c) != 2 or not re.fullmatch(r"\d+w", c[1]) for c in cands):
                problems.append(f"{where}: {kind} srcset {srcset!r}, expected three 'url Nw' candidates")
                continue
            widths.append([c[1] for c in cands])
            for url, desc in cands:
                f = SITE / url.removeprefix("/site/")
                named.add(f.name)
                if not url.startswith("/site/media/v3/") or not f.is_file():
                    problems.append(f"{where}: {url!r} is not a file in web/site/media/v3/")
                    continue
                size = image_size(f)
                if f.suffix != "." + kind.split("/")[1] or not size:
                    problems.append(f"{where}: {url} is not a {kind} we can read (a lossy WebP without alpha, or an AVIF)")
                    continue
                if f"{size[0]}w" != desc or abs(size[1] * w - size[0] * h) > w:
                    problems.append(f"{where}: {url} is {size[0]}x{size[1]}, its descriptor says {desc} at {w}:{h}")
                if f.stat().st_size > V3_STILL_LIMITS[f.suffix]:
                    problems.append(f"{where}: {url} is {f.stat().st_size:,} B (V-02: at most {V3_STILL_LIMITS[f.suffix]:,})")
        if len(widths) == 2 and widths[0] != widths[1]:
            problems.append(f"{where}: the AVIF and WebP srcsets list different widths {widths}")
        if img.group(1) not in sources[1][1]:
            problems.append(f"{where}: the img's src {img.group(1)} is none of its WebP candidates")
    if sets.get("stage-a") != sets.get("stage-end"):
        problems.append("pages/index.html: the closing doesn't name the hero's srcset and sizes (it would fetch another file)")
    icons = attr(d, "link", rel="icon")
    expected = [("/favicon.ico", None), ("/favicon-32.png", "image/png"), ("/favicon.svg", "image/svg+xml")]
    if [(a.get("href"), a.get("type")) for a in icons] != expected:
        problems.append(f"pages/index.html: favicons {[(a.get('href'), a.get('type')) for a in icons]}, expected /favicon.ico, "
                        "/favicon-32.png then /favicon.svg")
    png = SITE / "static" / "favicon-32.png"
    if not png.is_file() or image_size(png) != (32, 32):
        problems.append(f"static/favicon-32.png: {image_size(png) if png.is_file() else 'missing'}, expected 32 x 32")
    for f in (SHARED / "ui" / "icons.svg", SHARED / "icons.svg", SITE / "static" / "favicon.svg", SHARED / "brand" / "favicon.svg",
              SHARED / "brand" / "symbol.svg"):
        try:
            ElementTree.fromstring(f.read_bytes())
        except ElementTree.ParseError as e:   # a "--" in a comment is enough, and then the browser draws none of its icons
            problems.append(f"{f.relative_to(WEB)}: not well-formed XML ({e})")
    sprite = (SHARED / "ui" / "icons.svg").read_text()
    box = OPEN_BOX.search(sprite)
    for mark in (SITE / "static" / "favicon.svg", SHARED / "brand" / "favicon.svg", SHARED / "brand" / "symbol.svg"):
        body = mark.read_text()
        if mark.stat().st_size > V3_MARK_LIMIT or V3_BAD_SVG.search(body) or body.count("<svg") != 1 or not box \
                or f'<path fill="#ACFF00" transform="translate(2.24 1.81) scale(.86)" d="{box.group(1)}"/>' not in body \
                or '<rect width="32" height="32" rx="7" fill="#0A0A0A"/>' not in body:
            problems.append(f"{mark.relative_to(WEB)}: {mark.stat().st_size} B; not the open box in lime on its ink tile, or it carries "
                            f"a raster, script, link or data (V-02: clean, at most {V3_MARK_LIMIT:,} B)")
    symbol = re.search(r'<symbol id="i-hidebox"[^>]*>(.*?)</symbol>', sprite, re.S)
    if not box or not symbol or V3_BAD_SVG.search(symbol.group(1)) or re.search(r'stroke|fill="none"', symbol.group(0)):
        problems.append("shared/ui/icons.svg: no clean i-hidebox symbol drawing the open box as one filled outline")
    word = re.search(r'<symbol id="i-wordmark" viewBox="-0\.5 -0\.5 148 34">(.*?)</symbol>', sprite, re.S)
    if not word or V3_BAD_SVG.search(word.group(1)) or "stroke" in word.group(1) \
            or re.findall(r'<path fill="([^"]+)" d="[^"]+" />', word.group(1)) != ["currentColor", "#ACFF00"]:
        problems.append("shared/ui/icons.svg: no clean i-wordmark symbol (its letters in currentColor, the i's rhombus #ACFF00)")
    header = (SHARED / "partials" / "header.html").read_text()
    if not re.search(r'<span class="wm-tile" aria-hidden="true"><svg class="icon" focusable="false"><use href="/shared/ui/icons.svg#i-hidebox"/></svg></span>', header):
        problems.append("partials/header.html: the tile doesn't draw the open box (#i-hidebox)")
    if f'<a class="wm" href="/" aria-label="{{{{BRAND}}}}, home">' not in header or f"</span>{WORDMARK}</a>" not in header:
        problems.append("partials/header.html: the name beside the tile isn't the wordmark (#i-wordmark, hidden; the link named "
                        "{{BRAND}}, home)")
    for page in (home_page, SITE / "pages" / "v2.html"):
        if f"</span>{WORDMARK}<span class=\"sr-only\">{{{{BRAND}}}}</span></span></th>" not in page.read_text():
            problems.append(f"pages/{page.name}: the comparison's hidebox column isn't headed by the tile and the wordmark, named in words")
    for rel, rule in (("site/css/site.css", ".wm-tile {"), ("site/css/home.css", ".us-name .wm-tile .icon {"), ("app/css/drive.css", ".brand-mark { background"),
                      ("app/css/flow.css", ".done-box {")):
        css = (WEB / rel).read_text()
        body = css[css.index(rule):css.index("}", css.index(rule))] if rule in css else ""
        if "color: #ACFF00;" not in body:
            problems.append(f"{rel}: {rule} doesn't draw the box in the kit's lime, #ACFF00 (the logo's lime in both themes)")
    media = sorted(p for p in (SITE / "media" / "v3").glob("*") if p.is_file())
    for f in media:
        if f.name not in named:
            problems.append(f"{f.relative_to(WEB)}: named by no picture on the home (V-02 serves only what the home shows)")
    folder = sum(f.stat().st_size for f in media)
    if folder > V3_FOLDER_LIMIT:
        problems.append(f"web/site/media/v3: {folder:,} B (V-02: at most {V3_FOLDER_LIMIT:,})")
    code = []
    for rel, limit in V3_CODE_LIMITS.items():
        size = len(gzip.compress((SITE / rel).read_bytes(), 9))
        code.append(f"{rel} {size:,} B")
        if size > limit:
            problems.append(f"{rel}: {size:,} B gzip -9 (V-02: at most {limit:,})")
    NOTES_STATIC.append(f"V-02 files: {len(stages)} stills on the home, web/site/media/v3 {folder:,} B in {len(media)} files "
                        f"(at most {V3_FOLDER_LIMIT:,}); {', '.join(code)} gzip -9")
    return problems


CHECKS = [("SPDX headers", check_spdx), ("no HTML/script sinks in JS", check_js_sinks),
          ("markup: CSP-safe, includes, placeholders, JSON-LD", check_markup), ("banned words", check_banned_words),
          ("no typed /config numbers (P-20)", check_config_numbers), ("variables and conditions", check_variables),
          ("SEO metadata (M-04)", check_seo),
          ("trademark and mandatory lines (M-05)", check_trademark), ("partials in sync", check_partials),
          ("no page shows the ghost", check_ghost),
          ("privacy inventory covers the schema (M-06)", check_privacy_inventory),
          ("contrast table (M-03)", check_contrast), ("static files (M-04)", check_static),
          ("security.txt contacts answer a stranger (needs the network)", check_security_contacts),
          ("copy variants set at build time (M11)", check_build_variants),
          ("/judges quotes the app's words, 6 + 6 steps", check_ui_strings),
          ("old pages redirect to pages and anchors that exist", check_redirects),
          ("A-06h: motion.js 4 KB, stills.js 2 KB gzip at most, each only from site.js; no WebGL field; home.css 3.25 KB more, the home's stylesheets 8.5 KB", check_field_budget),
          ("/how's loops: aria-hidden pictures, 4 to 7 s with a rest, the app's words, one Pause motion switch", check_how_loops),
          ("the four sides and What's tTARI? are the same on / and /how", check_shared_blocks),
          ("links to site pages and anchors land on something", check_internal_links),
          ("V-01: /v2 is noindex and unlinked, keeps the home's links and labels, its loops wait to be asked for, its budget", check_v2),
          ("V-02: the home's stills are sized and lazy, the hero's first; the open box is the favicon and the header's mark; no video", check_home_stills)]
