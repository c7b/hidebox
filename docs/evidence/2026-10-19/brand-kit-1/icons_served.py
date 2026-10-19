# SPDX-License-Identifier: MIT
"""How Caddy serves the icons and cards (docs/review/brand-kit-1.md): the production Caddyfile on the throwaway stack of
tests/e2e/localstack.py (on the server, as build; nothing of production is touched), with a full build of this tree.
From the repository root on a machine that reaches the server over SSH:

  python3 -I docs/evidence/2026-10-19/brand-kit-1/icons_served.py [--host SSH_HOST] [--out icons-served.json]

For each file: the status, Content-Type, Cache-Control and length, plain and with Accept-Encoding: gzip, br; the bytes
compared with the built file. Python stdlib only.
"""
import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
from harness import SSH_HOST  # noqa: E402
from localstack import LocalStack, stub_build  # noqa: E402

FILES = ("favicon.ico", "favicon.svg", "favicon-32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png",
         "icon-maskable-512.png", "manifest.webmanifest", "og.png", "og-s.png", "shared/ui/icons.svg")


def get(url: str, encoding: str | None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "mutis-icons-served", "Accept-Encoding": encoding or "identity"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.status, {k.lower(): v for k, v in res.getheaders()}, res.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=SSH_HOST)
    ap.add_argument("--out", default="icons-served.json")
    args = ap.parse_args()
    rows, problems = [], []
    with tempfile.TemporaryDirectory(prefix="mutis-icons-") as tmp:
        dist = stub_build(Path(tmp) / "dist")
        with LocalStack(args.host, dist) as stack:
            for name in FILES:
                status, head, body = get(f"{stack.web}/{name}", None)
                _, zhead, zbody = get(f"{stack.web}/{name}", "gzip, br")
                row = {"file": name, "status": status, "type": head.get("content-type"), "cache": head.get("cache-control"),
                       "bytes": len(body), "same_as_built": body == (dist / name).read_bytes(),
                       "compressed": zhead.get("content-encoding"), "compressed_bytes": len(zbody)}
                rows.append(row)
                print(json.dumps(row))
                if status != 200 or not row["same_as_built"]:
                    problems.append(name)
    Path(args.out).write_text(json.dumps(rows, indent=1) + "\n")
    print("icons_served:", "PASS" if not problems else f"FAIL {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
