# SPDX-License-Identifier: MIT
"""Sets the copy variants that are true for one deployment into its built pages (Python stdlib only).

A sentence that depends on the deployment ships in every variant, each marked data-when="name=value",
and js/stats.js shows the right one from /api/v1/config. Without this step, readers without
JavaScript, crawlers and llms-full.txt would get the HTML's defaults (relay sends, wallet-read
amounts, SealLog off), and every visitor would see the copy switch once /config arrives. This gives
each variant its `hidden` attribute from the deployment's mutis.toml before anything is served, then
writes llms-full.txt again from the built pages, and keeps in llms.txt only the lines whose
`{when:name=value}` marker is true here (the marker is dropped; a line for an unknown condition
stays). A condition the TOML doesn't set keeps the HTML's default, which is also the server's. The
runtime switch stays, for flags an admin changes later without a rebuild (`mutis-admin feature`).

The Ootle network is the one condition no admin flips later: a deployment is on Esmeralda or on the mainnet
from its build. On the mainnet the coin is TARI, not tTARI, so the unit word in every page, llms.txt and
llms-full.txt is localized here (localize()), and a paid link's share card (app/pay.html) says TARI and shows
the site's own card, whose picture names no coin (mainnet_cards()). The testnet's sentences themselves are
variants (data-when="network=esmeralda", with their mainnet versions beside them).

Run it on dist/ right after the pages are copied, before includes and placeholders are expanded, and run
after_includes() once the shared partials (header, footer, status line, staging banner) are inlined, so
their variants are set too:
  python3 -I web/site/tools/variants.py --config /etc/mutis/mutis.toml dist
"""
import argparse
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I leaves the script's own directory out
import llms_full  # noqa: E402

# condition → its value for this deployment, read from mutis.toml (the same values js/stats.js reads
# from /config).
READ = {
    "send_mode": lambda c: c["gates"]["send_mode"],
    "proof": lambda c: "wallet" if c["gates"]["amount_proof"] == "wallet" else "proven",
    "seallog": lambda c: "on" if c["features"]["seallog"] else "off",
    "kept": lambda c: "on" if c["features"]["kept"] else "off",
    "snapshots": lambda c: c["hosting"]["snapshots"],
    "security_drop": lambda c: "on" if c["security_drop_url"] else "off",
    "pay_to_open": lambda c: "on" if c["features"].get("pay_to_open") else "off",
    "folders": lambda c: "on" if c["features"].get("folders") else "off",
    "sponsor": lambda c: "on" if c["features"].get("sponsor") else "off",
    "test_pay": lambda c: "on" if c["features"].get("pay_to_open") and c["features"].get("demo_pay", True) else "off",
    # The Ootle network (esmeralda, the default, or mainnet), a staging rehearsal (staging = true: the mainnet
    # instance before its launch, on Esmeralda) and judge passes (features.judge_passes, off on the mainnet).
    "network": lambda c: network(c),
    "staging": lambda c: "on" if c.get("staging") else "off",
    "judge": lambda c: "on" if c.get("features", {}).get("judge_passes", True) else "off",
}
NETWORKS = ("esmeralda", "mainnet")
# The coin's name as the pages write it (the testnet's) and as each network calls it.
UNIT = re.compile(r"(?<![\w-])tTARI(?![\w-])")
COIN = {"esmeralda": "tTARI", "mainnet": "TARI"}
# Words a variant can't reach, because they sit in an attribute (a table's data-cue column labels, /judges' description
# for search and link previews): the mainnet's.
MAINNET_WORDS = (("Price (testnet)", "Price"),
                 ("Two six-step tracks for the Tari Council: one device and no wallet, about two minutes; then two devices "
                  "with Tari, about five minutes.",
                  "The contest entry, its two tracks and the judge passes are on hidebox.app/judges."))
VARIANT = re.compile(r'<[a-z][a-z0-9]*\s[^>]*?\bdata-when="([a-z_]+)=([a-z0-9_]+)"[^>]*>')
LINE = re.compile(r'^((?:\{when:[a-z_]+=[a-z0-9_]+\} )+)(.*\n?)', re.M)
MARKER = re.compile(r'\{when:([a-z_]+)=([a-z0-9_]+)\} ')
HIDDEN = re.compile(r'\s+hidden(?=[\s>])')
NOT_PAGES = ("app/", "vendor/", "shared/", "site/")


def network(cfg: dict) -> str:
    name = cfg.get("network", "esmeralda")
    if name not in NETWORKS:
        raise ValueError(f"network must be one of {', '.join(NETWORKS)}: {name!r}")
    return name


def localize(text: str, cfg: dict) -> str:
    """The coin's name for this deployment's network: tTARI on Esmeralda, TARI on the mainnet."""
    coin = COIN[network(cfg)]
    if coin == "tTARI":
        return text
    for old, new in MAINNET_WORDS:
        text = text.replace(old, new)
    return UNIT.sub(coin, text)


# A paid link's share card (app/pay.html, viral-1) on the mainnet: its words say TARI, and it shows the site's card
# (og.png), because og-p.png's picture says "Pay with test money". Each pair must match the page exactly once.
PAY_CARD = (
    ("The {{BRAND}} logo over: A locked file on {{BRAND}}. Pay with Tari test money to open it. No account needed. "
     "Beside it, a locked file, Pay to open, and Pay with test money.",
     "The {{BRAND}} logo over: A locked file on {{BRAND}}. Pay with TARI to open it. No account needed. "
     "Beside it, a locked file, Pay to open, and Pay with TARI."),
    ("Pay with Tari test money to open it. No account needed.", "Pay with TARI to open it. No account needed."),
    ("/og-p.png", "/og-p-mainnet.png"),    # web/site/og/og-p-mainnet.html: the same card, saying TARI
)


# The conditions a build fixes for good: no admin flips a deployment's network or its staging rehearsal without a
# new build. Every build leaves out the elements whose network or staging condition is false here: a mainnet page
# carries no testnet sentence, not even a hidden one (a crawler or a copy of the page would read it), and no page
# carries the other network's copy or a banner it never shows (the home's budget, M-01).
FIXED = ("network", "staging")
TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")


def prune(html: str, known: dict) -> str:
    """`html` without the elements whose FIXED condition is false in `known` (start tag to matching end tag)."""
    pos = 0
    while True:
        m = next((v for v in VARIANT.finditer(html, pos) if v.group(1) in FIXED and v.group(1) in known
                  and known[v.group(1)] != v.group(2)), None)
        if not m:
            return html
        name = TAG.match(html, m.start()).group(2).lower()
        depth, end = 0, None
        for t in TAG.finditer(html, m.start()):
            if t.group(2).lower() != name:
                continue
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = t.end()
                break
        if end is None:
            raise ValueError(f"no end tag for {m.group(0)[:70]}")
        html, pos = html[:m.start()] + html[end:], m.start()


def mainnet_cards(dist: Path, cfg: dict) -> bool:
    """app/pay.html's share card for this network (PAY_CARD on the mainnet). False when there is no app."""
    page = dist / "app" / "pay.html"
    if network(cfg) != "mainnet" or not page.is_file():
        return False
    text = page.read_text(encoding="utf-8")
    for old, new in PAY_CARD:
        if old not in text:
            raise ValueError(f"app/pay.html no longer says {old[:60]!r}: update PAY_CARD in web/site/tools/variants.py")
        text = text.replace(old, new)
    page.write_text(text, encoding="utf-8")
    return True


def facts(cfg: dict) -> dict:
    out = {}
    for name, read in READ.items():
        try:
            out[name] = read(cfg)
        except KeyError:
            pass
    return out


def resolve(html: str, known: dict) -> str:
    def one(m: re.Match) -> str:
        name, wanted = m.group(1), m.group(2)
        if name not in known:
            return m.group(0)
        tag = HIDDEN.sub("", m.group(0))
        return tag if known[name] == wanted else tag[:-1] + " hidden>"
    return VARIANT.sub(one, html)


def resolve_lines(text: str, known: dict) -> str:
    """llms.txt: a marked line stays, unmarked, when its conditions hold here (a line may carry several markers, all
    of which must hold; one for a condition this deployment doesn't know counts as holding); goes when one doesn't."""
    def one(m: re.Match) -> str:
        holds = all(name not in known or known[name] == wanted for name, wanted in MARKER.findall(m.group(1)))
        return m.group(2) if holds else ""
    return LINE.sub(one, text)


def set_pages(dist: Path, cfg: dict, known: dict, shells: bool = False) -> int:
    """Each site page's variants and coin name for this deployment (with `shells`, also the app's pages that show the
    site's header and footer: app/app.html, view.html, drop.html, pay.html); returns how many pages changed."""
    changed = 0
    for page in sorted(dist.rglob("*.html")):
        rel = page.relative_to(dist).as_posix()
        if rel.startswith(NOT_PAGES) and not (shells and rel.startswith("app/") and rel.count("/") == 1):
            continue
        text = page.read_text(encoding="utf-8")
        new = prune(resolve(text, known), known)
        new = localize(new, cfg)
        if new != text:
            page.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def apply(dist: Path, cfg: dict) -> dict:
    known = facts(cfg)
    changed = set_pages(dist, cfg, known)
    llms = llms_full.render(lambda name: (dist / name / "index.html").read_text(encoding="utf-8"))
    (dist / "llms-full.txt").write_text(localize(llms, cfg), encoding="utf-8")
    short = dist / "llms.txt"
    if short.is_file():
        short.write_text(localize(resolve_lines(short.read_text(encoding="utf-8"), known), cfg), encoding="utf-8")
    cards = mainnet_cards(dist, cfg)
    return {"facts": known, "pages_changed": changed, "pay_card": "mainnet" if cards else "as written"}


def after_includes(dist: Path, cfg: dict) -> dict:
    """The same, once tools/build.py has inlined the shared partials (their variants: the staging banner, the judges'
    links, the footer's network line). Idempotent: a page apply() already set is left as it is."""
    return {"pages_changed": set_pages(dist, cfg, facts(cfg), shells=True)}


def main() -> int:
    p = argparse.ArgumentParser(description="set this deployment's copy variants into dist/")
    p.add_argument("--config", type=Path, required=True, help="the deployment's mutis.toml")
    p.add_argument("dist", type=Path)
    args = p.parse_args()
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    print(f"variants: {apply(args.dist, cfg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
