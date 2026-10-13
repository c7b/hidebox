#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Writes i18n/widget-en.json, the strings the home page's drop widget needs for a first drop: a
subset of en.json (the canonical dictionary), so the home page doesn't download every string of the
app. The rest loads with the code that needs it (ui/more.js). Python stdlib only.

  python3 -I web/app/i18n/subset.py           # write the subset
  python3 -I web/app/i18n/subset.py --check   # exit 1 if it differs from what would be written
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


def subset() -> str:
    full = json.loads((HERE / "en.json").read_text(encoding="utf-8"))
    part = {k: v for k, v in full.items() if k.startswith(PREFIXES) or k in KEYS}
    return json.dumps(part, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    out = HERE / "widget-en.json"
    text = subset()
    if not check:
        out.write_text(text, encoding="utf-8")
    elif not out.is_file() or out.read_text(encoding="utf-8") != text:
        print("subset: out of date: widget-en.json")
        return 1
    print("subset: " + ("up to date" if check else "written"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
