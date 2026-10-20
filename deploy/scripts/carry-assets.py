#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The live release's fingerprinted files that a new release doesn't have, copied into the new one before the switch.

  python3 -I deploy/scripts/carry-assets.py OLD_DIST NEW_DIST

A page loaded before a release keeps its references: a module the drive imports later, a picture that loads lazily,
asks for a hashed name of the old build (tools/assets.py), and would get the 404 page. A hashed name only ever holds
the same bytes, so the new release serves the old ones too, for one release: only names in the old release's own
manifest are carried (never what it carried itself), with their .gz and .br copies. They stay out of the new manifest
(tools/verify-deploy.py checks the new build's files); the release after next no longer has them. Standard library
only; activate-release.sh runs it.
"""
import json
import re
import shutil
import sys
from pathlib import Path

HASHED_NAME = re.compile(r"\.[0-9a-f]{10}\.[a-z0-9]+$")   # tools/assets.py's (deploy/tests/test_carry_assets.py checks)


def carry(old: Path, new: Path) -> int:
    try:
        files = json.loads((old / ".well-known" / "mutis-manifest.json").read_text())["files"]
    except (OSError, ValueError, KeyError):
        return 0
    carried = 0
    for rel in sorted(files):
        if not HASHED_NAME.search(rel.rpartition("/")[2]) or ".." in rel.split("/") or rel.startswith("/"):
            continue
        if (new / rel).exists() or not (old / rel).is_file():
            continue
        (new / rel).parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", ".gz", ".br"):
            source = old / (rel + suffix)
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, new / (rel + suffix))
        carried += 1
    return carried


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: carry-assets.py OLD_DIST NEW_DIST", file=sys.stderr)
        return 2
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
    if not new.is_dir():
        print(f"carry-assets: no {new}", file=sys.stderr)
        return 2
    print(f"carry-assets: {carry(old, new)} fingerprinted files of the live release kept for pages loaded before the switch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
