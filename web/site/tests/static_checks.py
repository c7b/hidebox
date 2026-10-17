# SPDX-License-Identifier: MIT
"""Checks that need only the files: licence headers, CSP-safe markup, banned words, numbers that
must come from /config, SEO metadata, trademark rules, contrast, partials, the privacy inventory;
and one that needs the network: security.txt's GitHub contact answers a visitor who isn't signed in.
Each check returns a list of problems (empty = pass), or None for SKIP. Python standard library only."""
import itertools
import json
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import llms_full
import variants

WEB = Path(__file__).resolve().parents[2]
SITE, SHARED = WEB / "site", WEB / "shared"
PAGES = sorted((SITE / "pages").glob("*.html"))
PARTIALS = sorted((SHARED / "partials").glob("*.html"))
JS = sorted((SITE / "js").glob("*.js")) + sorted(SHARED.glob("*.js"))
PLACEHOLDERS = {"ORIGIN", "GIT_SHA", "VERSION", "BUILD_DATE", "NETWORK", "SECURITY_DROP_URL", "REPO_URL", "SRI", "BRAND"}
DATA_FILES = {".json", ".png", ".ico", ".webp", ".woff2", ".bin", ".webmanifest", ".pyc"}
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


def check_seo():
    problems, titles = [], {}
    for f in PAGES:
        d, name = parse(f), f.relative_to(WEB)
        title = "".join(d.titles).strip()
        desc = attr(d, "meta", name="description")
        html = attr(d, "html")
        if not title or len(title) > 60:
            problems.append(f"{name}: title missing or over 60 characters ({len(title)})")
        titles.setdefault(title, []).append(str(name))
        if not desc or len(desc[0].get("content", "")) > 155:
            problems.append(f"{name}: description missing or over 155 characters")
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
            if not attr(d, "meta", name="robots"):
                problems.append(f"{name}: 404 should be noindex")
            continue
        if not attr(d, "link", rel="canonical"):
            problems.append(f"{name}: missing canonical")
    for title, files in titles.items():
        if len(files) > 1:
            problems.append(f"title {title!r} used by {files}")
    for page in ("index",):
        if 'type="application/ld+json"' not in (SITE / "pages" / f"{page}.html").read_text():
            problems.append(f"pages/{page}.html: no JSON-LD")
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
    the name, How it works, For judges (Under the hood left the nav for the footer), the light switch, and
    Open your drive (site v3: one label, always on): no status line."""
    problems = []
    line = (SHARED / "partials" / "status-line.html").read_text().split("\n", 1)[1].strip()
    header = (SHARED / "partials" / "header.html").read_text()
    links = re.findall(r'<a\b[^>]*href="([^"]+)"', header)
    labels = re.findall(r'data-testid="head-(?:make|open)">([^<]+)<', header)
    if links != ["/", "/how", "/judges", "/drive?make", "/drive"] or "data-theme-toggle" not in header or 'aria-label="Lights"' not in header \
            or labels != ["Open your drive", "Open your drive"]:
        problems.append("partials/header.html: the header is the wordmark, How it works, For judges, the Lights switch and "
                        "Open your drive (to /drive?make, or /drive with a drive)")
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
    """Fifth pass (16-drive-design §0, the owner: no ghost): no served page or partial shows the ghost. No
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
    for icon in manifest["icons"]:
        if not (s / icon["src"].lstrip("/")).is_file():
            problems.append(f"manifest icon {icon['src']} missing")
    for name, size, limit in (("og.png", (1200, 630), 150 * 1024), ("og-s.png", (1200, 630), 150 * 1024),
                              ("icon-192.png", (192, 192), None), ("icon-512.png", (512, 512), None),
                              ("apple-touch-icon.png", (180, 180), None)):
        f = s / name
        if not f.is_file() or png_size(f) != size:
            problems.append(f"{name}: missing or not {size}")
        elif limit and f.stat().st_size > limit:
            problems.append(f"{name}: over {limit} bytes")
    if not (s / "favicon.ico").is_file() or (s / "favicon.ico").read_bytes()[:4] != b"\0\0\1\0":
        problems.append("favicon.ico: missing or not an ICO (Bing and unfurlers ask for it by name)")
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
    parts = urllib.parse.urlsplit(repo)
    if parts.scheme != "https" or parts.netloc != "github.com" or parts.path.count("/") != 2:
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
        status, _, body = _anonymous_get(f"https://api.github.com/repos{parts.path}/private-vulnerability-reporting")
        enabled = status == 200 and json.loads(body or b"{}").get("enabled") is True
        if not enabled:
            problems.append(f"GitHub's API: private vulnerability reporting is not on for {parts.path[1:]} ({status})")
    except (urllib.error.URLError, OSError):
        return None
    return problems


def robots_allows(robots: str, path: str) -> bool:
    """Google's rule matching: the longest matching rule wins, Allow on a tie; * is any run, $ the end."""
    best = (-1, True)
    for kind, pattern in re.findall(r"^(Allow|Disallow):\s*(\S*)", robots, re.M):
        if not pattern:
            continue
        rx = re.escape(pattern).replace(r"\*", ".*")
        rx = rx[:-2] + "$" if rx.endswith(r"\$") else rx
        if re.match(rx, path) and (len(pattern), kind == "Allow") > best:
            best = (len(pattern), kind == "Allow")
    return best[1]


def indexable_paths():
    """The URL of every page the sitemap may list (not a 404, not noindex)."""
    out = []
    for f in PAGES:
        if f.stem == "404" or attr(parse(f), "meta", name="robots"):
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
# app. Pay to open's two labels arrive with lane app2's seller dialog (16-drive-design §15 step 15).
PENDING_LABELS: set[str] = set()  # lane app2: "Someone who pays you" and "Make pay link" are in en.json (step 15)


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


# A-06h (17-site-brief §1.2, docs/review/site-v3.md): the effects stay small and load late. field.js (the hero's
# grid) at most 6 KB, motion.js (the reveals and the decode, site v3) at most 4 KB, pixel.js (the closing's pixel
# field, site v3) at most 8 KB, all gzip -9; the home's own stylesheet grows by at most 3 KB over home.css at the
# tag spooky-secrets-2026-10 as it was before site v2 (f89963c, 1,770 B): site v2 and v3 together.
EFFECTS = {"field.js": 6144, "motion.js": 4096, "pixel.js": 8192}
HOME_CSS_BEFORE, HOME_CSS_GROWTH = 1770, 3072


def check_field_budget():
    """A-06h, the files' half (browser_checks has the loading half): field.js at most 6,144 B, motion.js at most
    4,096 B and pixel.js at most 8,192 B gzip -9; home.css at most 1,770 + 3,072 B gzip -9; no page, partial or
    stylesheet names the three, and only site.js imports them, each with import()."""
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
    NOTES_STATIC.append(f"A-06h: {'; '.join(notes)}, gzip -9; home.css {home:,} B "
                        f"(was {HOME_CSS_BEFORE:,}, +{home - HOME_CSS_BEFORE:,} of {HOME_CSS_GROWTH:,})")
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
          ("A-06h: field.js 6 KB, motion.js 4 KB, pixel.js 8 KB gzip at most, home.css 3 KB more, each only from site.js", check_field_budget),
          ("the four sides and What's tTARI? are the same on / and /how", check_shared_blocks),
          ("links to site pages and anchors land on something", check_internal_links)]
