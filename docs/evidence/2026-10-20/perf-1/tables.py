#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The tables of docs/review/perf-1.md, from two runs of tests/e2e/perf_probe.py (probe-before.json on main before the
pass, probe-after.json on the branch) and two builds (tools/build.py of each tree).

  python3 -I tables.py probe-before.json probe-after.json DIST_BEFORE DIST_AFTER > tables.md
"""
import json
import re
import sys
from pathlib import Path

HASHED = re.compile(r"\.[0-9a-f]{10}(\.[a-z0-9]+)(?=$|[?#])")
IMAGES = (".png", ".ico", ".webp", ".avif", ".svg", ".jpg", ".webm", ".mp4")


def kb(n):
    return f"{n:,}"


def visits(report):
    return {key: {name: v["summary"] for name, v in page.items() if name != "pictures"} for key, page in report["pages"].items()}


def image_bytes(report, key):
    reqs = report["pages"][key]["first"]["requests"]
    return sum(r["bytes"] for r in reqs if r["mime"].startswith("image/") and r["network"])


def main():
    before, after = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    dist_before, dist_after = Path(sys.argv[3]), Path(sys.argv[4])
    vb, va = visits(before), visits(after)
    print("## Bytes on the wire per page (Chromium's encodedDataLength: headers and body as sent)\n")
    print("| Page | First visit before | after | Requests | Images at load before | after "
          "| Repeat visit before | after | Requests to the network before | after "
          "| After a release before | after |")
    print("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for key in vb:
        b, a = vb[key], va.get(key)
        if not a:
            continue
        print(f"| `{key}` | {kb(b['first']['bytes'])} | {kb(a['first']['bytes'])} | {b['first']['requests']} → {a['first']['requests']} "
              f"| {kb(image_bytes(before, key))} | {kb(image_bytes(after, key))} "
              f"| {kb(b['repeat']['bytes'])} | {kb(a['repeat']['bytes'])} | {b['repeat']['network']} ({b['repeat']['not_modified']} × 304) "
              f"| {a['repeat']['network']} ({a['repeat']['not_modified']} × 304) "
              f"| {kb(b['after_release']['bytes'])} | {kb(a['after_release']['bytes'])} |")
    print("\n## What a repeat visit still asks the network for (after)\n")
    for key, page in after["pages"].items():
        net = [HASHED.sub(r"\1", r["path"]) + f" ({r['status']})" for r in page["repeat"]["requests"] if r["network"]]
        print(f"- `{key}`: {', '.join(net) or 'nothing'}")
    print("\n## Every image file the build serves, bytes (and the .br a browser gets for SVG)\n")
    print("| File | Before | After | After, br |")
    print("|---|--:|--:|--:|")

    def files(d):
        out = {}
        for p in d.rglob("*"):
            rel = p.relative_to(d).as_posix()
            if p.is_file() and p.suffix in IMAGES and not HASHED.search(p.name) and not rel.startswith("vendor/"):
                br = p.with_name(p.name + ".br")
                out[rel] = (p.stat().st_size, br.stat().st_size if br.is_file() else None)
        return out
    fb, fa = files(dist_before), files(dist_after)
    for rel in sorted(set(fb) | set(fa)):
        b, a = fb.get(rel, (None, None)), fa.get(rel, (None, None))
        print(f"| `{rel}` | {kb(b[0]) if b[0] is not None else '-'} | {kb(a[0]) if a[0] is not None else 'deleted'} "
              f"| {kb(a[1]) if a[1] else ''} |")
    print(f"| **all** | **{kb(sum(v[0] for v in fb.values()))}** | **{kb(sum(v[0] for v in fa.values()))}** | |")
    print("\n## The pictures the browser took (after, scrolled through)\n")
    print("| Page | Picture | Shown (CSS px) | Device px needed | Candidate taken (w) | Its file |")
    print("|---|---|--:|--:|--:|--:|")
    for key, page in after["pages"].items():
        for pic in page.get("pictures", []):
            name = HASHED.sub(r"\1", pic["src"])
            if name.startswith("data:"):
                continue
            f = dist_after / name.lstrip("/")
            print(f"| `{key}` | `{name}` | {pic['shown']} | {pic['needed']} | {pic['took']} | {kb(f.stat().st_size) if f.is_file() else ''} |")


if __name__ == "__main__":
    main()
