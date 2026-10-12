# SPDX-License-Identifier: MIT
"""Checks that need only the files: licence headers, CSP-safe markup, banned words, numbers that
must come from /config, SEO metadata, trademark rules, contrast, partials, the privacy inventory.
Each check returns a list of problems (empty = pass). Python standard library only."""
import itertools
import json
import re
import struct
from html.parser import HTMLParser
from pathlib import Path

import llms_full
import variants

WEB = Path(__file__).resolve().parents[2]
SITE, SHARED = WEB / "site", WEB / "shared"
PAGES = sorted((SITE / "pages").glob("*.html")) + sorted((SITE / "pages" / "es").glob("*.html"))
PARTIALS = sorted((SHARED / "partials").glob("*.html"))
JS = sorted((SITE / "js").glob("*.js")) + sorted(SHARED.glob("*.js"))
PLACEHOLDERS = {"ORIGIN", "GIT_SHA", "VERSION", "BUILD_DATE", "NETWORK", "SECURITY_DROP_URL", "REPO_URL", "SRI"}
DATA_FILES = {".json", ".png", ".ico", ".webp", ".woff2", ".bin", ".webmanifest", ".pyc"}
NOT_SOURCE = {"OFL.txt", "NOTICE", "llms.txt", "llms-full.txt"}

# 11-brand §7.4 (and 12-integration "not promises"); "encriptado" per §7.7. Word-bounded, any case.
BANNED = ["seamless", "revolutionary", "game-changer", "cutting-edge", "next-gen", "unlock", "supercharge", "empower",
          "elevate", "leverage", "harness", "delve", "dive in", "in today's digital world", "in an era of",
          "military-grade", "bank-level", "unhackable", "100% secure", "100% private", "fully anonymous", "untraceable",
          "trustless", "zero-knowledge", "decentralized storage", "censorship-resistant", "your data, your rules",
          "peace of mind", "magic", "magically", "effortless", "robust", "world-class", "Web3", "to the moon", "LFG",
          "WAGMI", "XTR", "mining TARI", "Ootle chain", "Tari L3", "Emoji ID", "ghost", "ghostly", "vault",
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
        for m in re.finditer(r"<!--#include ([a-z-]+)-->", text):
            if not (SHARED / "partials" / f"{m[1]}.html").is_file():
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
    """Every number /config provides, formatted the ways stats.js prints it (en and es)."""
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
            out |= {f"{n // 86400} days", f"{n // 86400} días"}
        elif n % 3600 == 0 and n >= 3600:
            out |= {f"{n // 3600} hours", f"{n // 3600} horas"}
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
        if not html or html[0].get("lang") not in ("en", "es"):
            problems.append(f"{name}: <html lang> missing")
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
        langs = {a.get("hreflang") for a in attr(d, "link", rel="alternate")}
        if langs != {"en", "es", "x-default"}:
            problems.append(f"{name}: hreflang set is {sorted(x for x in langs if x)}")
    for title, files in titles.items():
        if len(files) > 1:
            problems.append(f"title {title!r} used by {files}")
    for page in ("index", "faq"):
        for lang_dir in ("", "es/"):
            if 'type="application/ld+json"' not in (SITE / "pages" / f"{lang_dir}{page}.html").read_text():
                problems.append(f"pages/{lang_dir}{page}.html: no JSON-LD")
    return problems


def check_translations():
    en = {p.name for p in (SITE / "pages").glob("*.html")}
    es = {p.name for p in (SITE / "pages" / "es").glob("*.html")}
    problems = [f"pages/es/{n} missing" for n in sorted(en - es)]
    for f in sorted((SITE / "pages" / "es").glob("*.html")):
        text = f.read_text()
        if "<!--#include header-es-->" not in text or "<!--#include footer-es-->" not in text:
            problems.append(f"{f.relative_to(WEB)}: uses the English header or footer")
        for m in re.finditer(r'href="/(how|security|pricing|faq|judges|terms|privacy|abuse|status)\b', text):
            problems.append(f"{f.relative_to(WEB)}: links to the English /{m[1]}")
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
    lines = {"footer.html": ["Built on the Tari™ Ootle testnet.", "It is not affiliated with, endorsed by, or sponsored by Tari Labs, the Tari Council, or the Tari project.", "“Tari” is a trademark of Tari Labs. All rights reserved."],
             "footer-es.html": ["Construido sobre la testnet de Tari™ Ootle.", "No está afiliado, respaldado ni patrocinado por Tari Labs, el Consejo de Tari ni el proyecto Tari.", "“Tari” es una marca de Tari Labs. Todos los derechos reservados."]}
    for name, required in lines.items():
        text = (SHARED / "partials" / name).read_text()
        problems += [f"partials/{name}: missing mandatory line {line!r}" for line in required if line not in text]
    for f in PAGES:
        if not re.search(r"<!--#include footer(-es)?-->", f.read_text()):
            problems.append(f"{f.relative_to(WEB)}: no footer (mandatory lines)")
    # No claim of official status: every sentence that uses those words must be a question or a denial.
    for f in PAGES + PARTIALS:
        for sentence in re.split(r"(?<=[.?!])\s+", " ".join(" ".join(parse(f).text).split())):
            if re.search(r"\b(official (partner|project|app|product)|partner(ed)? (of|with)|(endorsed|supported|sponsored) by Tari|"
                         r"proyecto oficial|socio oficial|(respaldado|patrocinado) por Tari)\b", sentence, re.I) \
                    and not re.search(r"\?|\bnot\b|\bno\b|\bni\b|^¿", sentence, re.I):
                problems.append(f"{f.relative_to(WEB)}: {sentence[:90]!r} reads as a claim of official status")
    return problems


def check_partials():
    """The header's testnet chip and the footer repeat the status line; they must not drift."""
    problems = []
    for suffix in ("", "-es"):
        line = (SHARED / "partials" / f"status-line{suffix}.html").read_text().split("\n", 1)[1].strip()
        for part in ("header", "footer"):
            if line not in (SHARED / "partials" / f"{part}{suffix}.html").read_text():
                problems.append(f"partials/{part}{suffix}.html: status line differs from status-line{suffix}.html")
    if (SHARED / "brand" / "favicon.svg").read_bytes() != (SITE / "static" / "favicon.svg").read_bytes():
        problems.append("static/favicon.svg differs from shared/brand/favicon.svg")
    return problems


def check_privacy_inventory():
    schema = WEB.parent / "server" / "mutis" / "schema.sql"
    if not schema.is_file():
        return []
    tables = re.findall(r"CREATE TABLE (\w+)", schema.read_text())
    problems = []
    for page in (SITE / "pages" / "privacy.html", SITE / "pages" / "es" / "privacy.html"):
        text = page.read_text()
        problems += [f"{page.relative_to(WEB)}: table {t} is not listed" for t in tables if f"<code>{t}</code>" not in text]
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
    lamp = contrast(_rgb(light["--lamp"], light), _rgb(light["--stage-raised"], light))
    if lamp < 3:
        problems.append(f"lit keyhole on a locker is {lamp:.2f}, needs 3")
    return problems


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def check_static():
    s = SITE / "static"
    problems = []
    robots = (s / "robots.txt").read_text()
    for path in ("/s/", "/t$", "/api/", "/locker", "/inbox", "/send", "/watch", "/upgrade", "/verify"):
        if f"Disallow: {path}\n" not in robots:
            problems.append(f"robots.txt: no Disallow: {path}")
    for path in ("/t", "/s/abc", "/api/v1/stats/wall", "/api/v1/canary", "/locker", "/verify/tx/1"):
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
    # One contact, the dead drop: a GitHub advisory link would only work once the repository is public
    # and private reporting is switched on, and RFC 9116 wants every Contact to work.
    for field in ("Contact: {{SECURITY_DROP_URL}}", "Expires: ",
                  "Preferred-Languages: en, es", "Policy: {{ORIGIN}}/security", "Canonical: {{ORIGIN}}/.well-known/security.txt"):
        if field not in sec:
            problems.append(f"security.txt: missing {field!r}")
    if "advisories" in sec:
        problems.append("security.txt: names a GitHub contact (dead while the repository is private)")
    manifest = json.loads((s / "manifest.webmanifest").read_text())
    for icon in manifest["icons"]:
        if not (s / icon["src"].lstrip("/")).is_file():
            problems.append(f"manifest icon {icon['src']} missing")
    for name, size, limit in (("og.png", (1200, 630), 150 * 1024), ("og-s.png", (1200, 630), 150 * 1024),
                              ("og-es.png", (1200, 630), 150 * 1024),
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
    if not llms.startswith("# mutis\n") or "pay-to-open" in llms or "dead-drop" not in llms:
        problems.append("llms.txt: not the spec §13.4 shape")
    for fact in ("send_mode=direct", "send_mode=relay", "seallog=on"):
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
        prefix = "/es" if f.parent.name == "es" else ""
        out.append(prefix + "/" if f.stem == "index" else f"{prefix}/{f.stem}")
    return out


# The server's own defaults (server/mutis/config.py): what the HTML must show before /config is read.
SERVER_DEFAULTS = {"send_mode": "relay", "proof": "wallet", "seallog": "off", "kept": "on", "snapshots": "weekly",
                   "security_drop": "off"}
DIRECT = {"send_mode": "direct", "proof": "proven", "seallog": "on", "kept": "on", "snapshots": "off",
          "security_drop": "on"}


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


# The payment steps the app shows in each amount-proof mode (web/app/i18n upgrade.step.*).
PAY_STEPS = {"proven": ("waiting", "seen", "proven", "added"), "wallet": ("waiting", "seen_wallet", "exists", "added")}
HIDDEN_SPAN = re.compile(r"<span[^>]*\shidden[\s>][^<]*</span>")


def check_ui_strings():
    """/judges quotes the app's own words (NOTES §2.7). The page is read in each amount-proof mode and
    each send mode, as tools/variants.py builds it. Each phrase in bold in a step must be one of the
    app's i18n strings ({placeholders} match anything) unless the site's own home page says it, and a
    bold arrow sequence with the payment steps must be exactly the app's upgrade.step labels for that
    mode, so a label the app shows only in the other mode (or only in the other send mode, like the
    demo-pay button) fails. SKIP until the app-ui builder writes web/app/i18n/."""
    problems = []
    for lang, page, home in (("en", "judges.html", "index.html"), ("es", "es/judges.html", "es/index.html")):
        i18n = WEB / "app" / "i18n" / f"{lang}.json"
        if not i18n.is_file():
            return None
        strings = json.loads(i18n.read_text())
        patterns = [re.compile(re.sub(r"\\\{[^}]*\\\}", ".*", re.escape(s.strip())) + "$") for s in _strings(strings)]
        own = " ".join(parse(SITE / "pages" / home).text)
        for (proof, keys), mode in itertools.product(PAY_STEPS.items(), ("relay", "direct")):
            text = variants.resolve((SITE / "pages" / page).read_text(), {"proof": proof, "send_mode": mode})
            steps = re.findall(r'<li[^>]*><span class="n">.*?</li>', text)
            pay = [strings.get(f"upgrade.step.{k}") for k in keys]
            for bold in re.findall(r"<strong>(.*?)</strong>", " ".join(steps)):
                phrases = [p.strip() for p in re.sub(r"<[^>]+>|[“”✓]", "", HIDDEN_SPAN.sub("", bold)).split("→")]
                if pay[0] in phrases and phrases != pay:
                    problems.append(f"pages/{page} ({proof}, {mode}): payment steps “{' → '.join(phrases)}”, the app shows "
                                    f"“{' → '.join(str(s) for s in pay)}”")
                for phrase in phrases:
                    if phrase and phrase not in own and not any(p.match(phrase) for p in patterns):
                        problems.append(f"pages/{page} ({mode}): quotes “{phrase}”, which web/app/i18n/{lang}.json doesn't say")
    return problems


CHECKS = [("SPDX headers", check_spdx), ("no HTML/script sinks in JS", check_js_sinks),
          ("markup: CSP-safe, includes, placeholders, JSON-LD", check_markup), ("banned words", check_banned_words),
          ("no typed /config numbers (P-20)", check_config_numbers), ("variables and conditions", check_variables),
          ("SEO metadata (M-04)", check_seo), ("Spanish pages", check_translations),
          ("trademark and mandatory lines (M-05)", check_trademark), ("partials in sync", check_partials),
          ("privacy inventory covers the schema (M-06)", check_privacy_inventory),
          ("contrast table (M-03)", check_contrast), ("static files (M-04)", check_static),
          ("copy variants set at build time (M11)", check_build_variants),
          ("/judges quotes the app's words", check_ui_strings)]
