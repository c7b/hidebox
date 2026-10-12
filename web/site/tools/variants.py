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

Run it on dist/ right after the pages are copied, before includes and placeholders are expanded:
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
}
VARIANT = re.compile(r'<[a-z][a-z0-9]*\s[^>]*?\bdata-when="([a-z_]+)=([a-z0-9_]+)"[^>]*>')
LINE = re.compile(r'^\{when:([a-z_]+)=([a-z0-9_]+)\} (.*\n?)', re.M)
HIDDEN = re.compile(r'\s+hidden(?=[\s>])')
NOT_PAGES = ("app/", "vendor/", "shared/", "site/")


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
    """llms.txt: a marked line stays, unmarked, when its condition holds here; goes when it doesn't."""
    def one(m: re.Match) -> str:
        name, wanted, line = m.groups()
        if name not in known:
            return line
        return line if known[name] == wanted else ""
    return LINE.sub(one, text)


def apply(dist: Path, cfg: dict) -> dict:
    known = facts(cfg)
    changed = 0
    for page in sorted(dist.rglob("*.html")):
        if page.relative_to(dist).as_posix().startswith(NOT_PAGES):
            continue
        text = page.read_text(encoding="utf-8")
        new = resolve(text, known)
        if new != text:
            page.write_text(new, encoding="utf-8")
            changed += 1
    llms = llms_full.render(lambda name: (dist / name / "index.html").read_text(encoding="utf-8"))
    (dist / "llms-full.txt").write_text(llms, encoding="utf-8")
    short = dist / "llms.txt"
    if short.is_file():
        short.write_text(resolve_lines(short.read_text(encoding="utf-8"), known), encoding="utf-8")
    return {"facts": known, "pages_changed": changed}


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
