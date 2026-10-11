#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Writes i18n/widget-<lang>.json, the strings the home page's drop widget needs for a first drop: a
subset of <lang>.json (the canonical dictionaries), so the home page doesn't download every string of
the app. The rest loads with the code that needs it (ui/more.js). Python stdlib only.

  python3 -I web/app/i18n/subset.py           # write the subsets
  python3 -I web/app/i18n/subset.py --check   # exit 1 if they differ from what would be written
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREFIXES = ("hero.", "zone.", "compose.", "seal.", "exif.", "noise.", "dur.")
# The first card (Once, a plain link) and what it can say before ui/more.js loads the rest: the
# Change panel, kept files and passwords bring the full dictionary with them.
KEYS = {"card.locked", "card.note", "card.strip", "card.key_lead", "card.key_rest", "card.copy", "card.change",
        "card.send", "card.another", "card.live", "card.rule.once", "toast.copied", "toast.copied_link",
        "toast.stopped", "toast.stopped_early", "known.toggle", "locker.opening", "locker.offer",
        "error.clipboard", "recent.h"}


def subset(lang: str) -> str:
    full = json.loads((HERE / f"{lang}.json").read_text(encoding="utf-8"))
    part = {k: v for k, v in full.items() if k.startswith(PREFIXES) or k in KEYS}
    return json.dumps(part, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for lang in ("en", "es"):
        out = HERE / f"widget-{lang}.json"
        text = subset(lang)
        if check:
            if not out.is_file() or out.read_text(encoding="utf-8") != text:
                stale.append(out.name)
        else:
            out.write_text(text, encoding="utf-8")
    if stale:
        print("subset: out of date:", ", ".join(stale))
        return 1
    print("subset: " + ("up to date" if check else "written"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
