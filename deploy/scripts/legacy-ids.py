#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The frozen set of a deployment's link ids, for the host that takes it over (docs/cutover.md). As root:
  legacy-ids.py export --db /srv/mutis/data/db/mutis.sqlite3 --out /srv/mutis-NAME/legacy
  legacy-ids.py check  --out /srv/mutis-NAME/legacy s/<share id> d/<drop id> …
`export` opens the database read-only and writes one empty file for each id a link of that deployment can carry in its
path: s/<share id> for every share (a link, a folder link, a pay link opened as /s/), p/<share id> for every pay link,
d/<drop id> for every drop link, verify/tx/<id> for every transaction our server made (relay sends, decoys, demo
payments, SealLog checkpoints). Caddy's file matcher on the new host sends exactly those paths to legacy_origin
(deploy/scripts/instance.py). Only ids of the exact shapes the routes take are written, so nothing in the database can
name another path; export only adds, so running it again after the move catches what was made in between. `check`
says which of the given paths are in the set, for ids we must not open (the owner's links, the security drop): it
reads names only. Python standard library only.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

SHAPES = {"s": re.compile(r"[A-Za-z0-9_-]{22}"), "p": re.compile(r"[A-Za-z0-9_-]{22}"),
          "d": re.compile(r"[0-9a-hjkmnp-tv-z]{10}"), "verify/tx": re.compile(r"[0-9a-f]{64}")}


def ids(conn: sqlite3.Connection) -> dict[str, set[str]]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    out: dict[str, set[str]] = {k: set() for k in SHAPES}
    out["s"] |= {r[0] for r in conn.execute("SELECT id FROM shares")}
    if "paid_shares" in tables:
        out["p"] |= {r[0] for r in conn.execute("SELECT share_id FROM paid_shares")}
    if "drops" in tables:
        out["d"] |= {r[0] for r in conn.execute("SELECT id FROM drops")}
    for (result,) in conn.execute("SELECT result FROM jobs WHERE result IS NOT NULL") if "jobs" in tables else ():
        try:
            tx = json.loads(result).get("tx_id")
        except (ValueError, AttributeError):
            continue
        if isinstance(tx, str):
            out["verify/tx"].add(tx)
    if "seal_checkpoints" in tables:
        out["verify/tx"] |= {r[0] for r in conn.execute("SELECT tx_id FROM seal_checkpoints WHERE tx_id IS NOT NULL")}
    return {kind: {i for i in found if isinstance(i, str) and SHAPES[kind].fullmatch(i)} for kind, found in out.items()}


def export(db: Path, out: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        found = ids(conn)
    finally:
        conn.close()
    added = {}
    os.umask(0o022)
    for kind, names in found.items():
        folder = out / kind
        folder.mkdir(parents=True, exist_ok=True, mode=0o755)
        before = {p.name for p in folder.iterdir()}
        for name in names - before:
            (folder / name).touch(mode=0o644, exist_ok=True)
        added[kind] = len(names - before)
    return {"added": added, "total": {k: len(list((out / k).iterdir())) for k in SHAPES}}


def check(out: Path, paths: list[str]) -> dict[str, bool]:
    answers = {}
    for path in paths:
        kind, _, name = path.strip("/").rpartition("/")
        shape = SHAPES.get(kind)
        answers[path] = bool(shape and shape.fullmatch(name) and (out / kind / name).is_file())
    return answers


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("paths", nargs="+")
    args = p.parse_args()
    if args.command == "export":
        print(json.dumps(export(args.db, args.out), sort_keys=True))
        return 0
    answers = check(args.out, args.paths)
    for path, there in answers.items():
        print(f"{'in the set' if there else 'NOT in the set'}: {path}")
    return 0 if all(answers.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
