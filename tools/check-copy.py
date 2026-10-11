#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy checks (11-brand §16 P-20, §7.4; 12-integration §2). Python standard library only.

  python3 -I tools/check-copy.py [--root DIR] [--config FILE_OR_URL]

(1) Banned words and phrases (11-brand §7.4 plus "not promises"): case-insensitive, word-bounded,
    over the visible text of web/**/*.html, the values of web/app/i18n/*.json, README.md and docs/**.
    "simply", "just" and "anonymous" are banned only in some senses; they are listed for a human to
    read (WARN) and never fail the check.
(2) Digits in i18n values (en.json, es.json) outside {variables}: fail unless every digit is part of
    a format constant in tools/copy-allowlist.txt (one phrase per line).
(3) Numbers that /api/v1/config provides must not be written into site pages: they come from the
    config at runtime. Exempt: elements with a data-v binding (their text is the no-JS fallback), the
    exit wall's data-cue locker labels (sample exit rules drawn over by /stats/wall, not limits), and
    the format constants of the allowlist (the file format's "4 MB chunks" is not a limit).
    Runs only with --config (a saved /config JSON or its URL).
Exit status 1 when (1), (2) or (3) finds anything.
"""
import argparse
import html.parser
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = Path(__file__).resolve().parent / "copy-allowlist.txt"

BANNED = [
    r"seamless(ly)?", r"revolutionary", r"game[- ]changers?", r"cutting[- ]edge", r"next[- ]gen",
    r"unlock\w*", r"supercharg\w*", r"empower\w*", r"elevat(e|es|ed|ing)", r"leverag\w*",
    r"(?<!test )harness(es|ed|ing)?", r"delv(e|es|ed|ing)", r"dive in", r"in today's digital world",
    r"in an era of", r"military[- ]grade", r"bank[- ]level", r"unhackable", r"bulletproof(?!s\+)\w*",
    r"100% secure", r"100% private", r"fully anonymous", r"untraceable", r"trustless",
    r"zero[- ]knowledge", r"decentrali[sz]ed storage", r"censorship[- ]resistant", r"your data, your rules",
    r"peace of mind", r"magic(al(ly)?)?(?! (bytes|number))", r"effortless(ly)?", r"robust(ly|ness)?",
    r"world[- ]class", r"web3", r"to the moon", r"lfg", r"wagmi", r"xtr", r"mining tari", r"ootle chain",
    r"tari l3", r"emoji id", r"ghost(ly|s)?", r"vaults?", r"we see nothing", r"we say nothing",
    r"nothing left", r"not anywhere", r"no account to hack", r"two independent indexers",
    r"zero third-party runtime dependencies", r"protects you from a malicious", r"instead of through us",
    r"gone forever", r"deleted forever", r"provably deleted", r"vanished", r"sealed files?",
    r"not promises",
]
WATCH = [r"simply", r"just", r"anonymous(ly)?"]
BANNED_RX = re.compile(r"(?<![\w-])(" + "|".join(BANNED) + r")(?![\w-])", re.I)
WATCH_RX = re.compile(r"(?<![\w-])(" + "|".join(WATCH) + r")(?![\w-])", re.I)
VARIABLE = re.compile(r"\{[^{}]*\}")
UNIT_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)[ \u00a0]*(KB|MB|GB|KiB|MiB|GiB|hours?|days?|minutes?|tTARI|views?|opens?|"
                         r"sends?|iterations?|characters?)\b", re.I)
TEXT_ATTRS = ("alt", "title", "aria-label", "placeholder", "content")


class VisibleText(html.parser.HTMLParser):
    """Visible text (and human-facing attributes) of a page; text inside data-v / data-cue kept apart."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.bound, self.stack = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.parts += [a[k] for k in TEXT_ATTRS if a.get(k) and not (tag == "meta" and k == "content"
                                                                     and a.get("name") not in ("description",)
                                                                     and not str(a.get("property", "")).startswith("og:"))]
        if tag not in self.VOID:
            self.stack.append((tag, "data-v" in a or "data-cue" in a))

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        tags = [t for t, _ in self.stack]
        if "script" in tags or "style" in tags:
            return
        (self.bound if any(b for _, b in self.stack) else self.parts).append(data)


def page_text(text: str) -> tuple[str, str]:
    parser = VisibleText()
    parser.feed(text)
    return " ".join(parser.parts), " ".join(parser.bound)


def markdown_text(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return re.sub(r"`[^`]*`", " ", text)


def i18n_values(doc, key=""):
    if isinstance(doc, dict):
        for k, v in doc.items():
            yield from i18n_values(v, f"{key}.{k}" if key else k)
    elif isinstance(doc, str):
        yield key, doc


def copy_sources(root: Path) -> list[tuple[str, str]]:
    """(name, text to check) for every copy file in scope."""
    out = []
    for path in sorted((root / "web").rglob("*.html")):
        rel = path.relative_to(root).as_posix()
        if "/tests/" in rel or "/og/" in rel:
            continue
        out.append((rel, page_text(path.read_text(encoding="utf-8"))[0]))
    for path in sorted((root / "web" / "app" / "i18n").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        out += [(f"{path.relative_to(root).as_posix()}:{k}", v) for k, v in i18n_values(doc)]
    for path in [root / "README.md", *sorted((root / "docs").rglob("*.md"))]:
        if path.is_file():
            out.append((path.relative_to(root).as_posix(), markdown_text(path.read_text(encoding="utf-8"))))
    return out


def banned_words(root: Path) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    for name, text in copy_sources(root):
        fails += [f"{name}: banned {m.group(0)!r}" for m in BANNED_RX.finditer(text)]
        warns += [f"{name}: check the sense of {m.group(0)!r}" for m in WATCH_RX.finditer(text)]
    return fails, warns


def load_allowlist(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    phrases = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    return sorted(phrases, key=len, reverse=True)


def i18n_digits(root: Path, allowed: list[str]) -> list[str]:
    fails = []
    for lang in ("en", "es"):
        path = root / "web" / "app" / "i18n" / f"{lang}.json"
        if not path.is_file():
            continue
        for key, value in i18n_values(json.loads(path.read_text(encoding="utf-8"))):
            rest = VARIABLE.sub(" ", value)
            for phrase in allowed:
                rest = rest.replace(phrase, " ")
            if re.search(r"\d", rest):
                fails.append(f"{path.relative_to(root).as_posix()}:{key}: a number outside {{variables}}: {value!r}")
    return fails


def config_numbers(config: dict) -> set[tuple[str, str]]:
    """(number as written, unit family) for every number /config serves, in the forms copy would use."""
    found = set()

    def num(x: float) -> str:
        return f"{x:,.3f}".rstrip("0").rstrip(".")

    def walk(doc, key=""):
        if isinstance(doc, dict):
            for k, v in doc.items():
                walk(v, k)
        elif isinstance(doc, list):
            for v in doc:
                walk(v, key)
        elif isinstance(doc, (int, str)) and str(doc).isdigit() and not isinstance(doc, bool):
            n = int(doc)
            if key.endswith("bytes") or key == "chunk_size":
                for unit, size in (("kb", 1 << 10), ("mb", 1 << 20), ("gb", 1 << 30)):
                    tenths = n * 10 / size
                    if n >= size and tenths == int(tenths):          # 25 MB, 2 GB, 2.5 GB; not 0.3 GB
                        found.add((num(n / size), unit))
            elif key.endswith("_s") or key == "days":
                n = n * 86400 if key == "days" else n
                for unit, size in (("minute", 60), ("hour", 3600), ("day", 86400)):
                    if n >= size and n % size == 0:
                        found.add((num(n / size), unit))
            elif key.endswith("_ut"):
                found.add((num(n / 1_000_000), "ttari"))
            elif "views" in key:
                found.add((num(n), "view"))
            elif "sends" in key or "per_day" in key:
                found.add((num(n), "send"))
            elif "iter" in key:
                found.add((num(n), "iteration"))
            elif "chars" in key:
                found.add((num(n), "character"))
    walk(config)
    return found


def unit_family(unit: str) -> str:
    u = unit.lower().rstrip("s")
    return {"kib": "kb", "mib": "mb", "gib": "gb", "open": "view"}.get(u, u)


def hardcoded_config_numbers(root: Path, config: dict, allowed: list[str]) -> list[str]:
    served = config_numbers(config)
    fails = []
    for path in sorted((root / "web" / "site" / "pages").rglob("*.html")):
        text, _ = page_text(path.read_text(encoding="utf-8"))
        for phrase in allowed:
            text = text.replace(phrase, " ")
        for m in UNIT_NUMBER.finditer(text):
            if (m.group(1), unit_family(m.group(2))) in served:
                fails.append(f"{path.relative_to(root).as_posix()}: {m.group(0)!r} is a /config value; bind it with data-v")
    return fails


def load_config(source: str) -> dict:
    if source.startswith("https://") or source.startswith("http://127.0.0.1"):
        with urllib.request.urlopen(urllib.request.Request(source, headers={"User-Agent": "mutis-check-copy"}),
                                    timeout=15) as res:
            return json.load(res)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="mutis copy checks (P-20)")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--config", help="a /api/v1/config JSON file or URL, for check (3)")
    p.add_argument("--quiet", action="store_true", help="don't list the WARN lines")
    args = p.parse_args()
    root = args.root.resolve()
    fails, warns = banned_words(root)
    allowed = load_allowlist(root / "tools" / "copy-allowlist.txt")
    fails += i18n_digits(root, allowed)
    if args.config:
        fails += hardcoded_config_numbers(root, load_config(args.config), allowed)
    for line in fails:
        print("COPY", line)
    if not args.quiet:
        for line in warns:
            print("WARN", line)
    skipped = "" if args.config else ", (3) skipped: no --config"
    print(f"check-copy: {'FAIL' if fails else 'PASS'} ({len(fails)} problems, {len(warns)} to read{skipped})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
