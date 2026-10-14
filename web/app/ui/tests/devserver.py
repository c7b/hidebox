#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Test-only: `server/bin/mutis-api --dev` with its payment gate set to another mode, for the flows that
check what the app shows in production's mode (`amount_proof = "wallet"`, the server's default and
deploy/config/mutis.toml.example's). `--dev` itself always runs the sidecar mode. Everything else is
the dev server unchanged: same fakes, same routes, same CSP.

  python3 -I web/app/ui/tests/devserver.py --amount-proof wallet --data DIR --dist DIR --port N [--pow-bits B]

Lane app2: `--features folders,pay_to_open` also turns those features on (they are off in config.py until the
drive's routes switch over), for the flows of the share dialog, the folder viewer and Received.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "server"))

from mutis import config, dev, logsafe  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amount-proof", choices=("sidecar", "chromium", "wallet"), required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--dist", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--pow-bits", type=int)
    ap.add_argument("--features", default="", help="comma-separated features to turn on (lane app2)")
    args = ap.parse_args()
    from_dict = config.from_dict

    def with_gate(raw, **kw):
        raw["gates"]["amount_proof"] = args.amount_proof
        for name in filter(None, args.features.split(",")):
            raw.setdefault("features", {})[name] = True
        return from_dict(raw, **kw)

    config.from_dict = with_gate
    logsafe.setup()
    dev.run(args.data, args.dist, args.port, args.pow_bits)


if __name__ == "__main__":
    main()
