#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deploy smoke test (spec §15.5 step 5), run by deploy.sh from the workstation. Stdlib only.

  python3 -I tests/e2e/smoke.py --origin https://… --manifest dist/.well-known/mutis-manifest.json [--api] [--chain]

Passes when: the home page answers 200 with the app CSP and the §14.2 headers; the live hash manifest
lists exactly the files and hashes of the local build; with --api, /api/v1/health is ok and reports
the deployed commit; with --chain, /api/v1/stats reports chain_ok (the chain worker's heartbeat is
fresh and walletd answers it), so a worker that dies on start fails the deploy. Each check retries
while services restart: 20 s, and 150 s for the chain (stats are cached for 60 s).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import headers_spec  # noqa: E402


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "mutis-smoke", "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def home(origin: str, _manifest: dict) -> str | None:
    status, headers, _ = get(origin + "/")
    if status != 200:
        return f"home answered {status}"
    if headers.get("content-security-policy") != headers_spec.APP_CSP:
        return "home CSP is not the app policy of spec §14.2"
    wrong = [k for k, v in headers_spec.COMMON.items() if headers.get(k) != v]
    if wrong or any(k in headers for k in headers_spec.ABSENT):
        return f"home headers wrong: {wrong or [k for k in headers_spec.ABSENT if k in headers]}"
    return None


def manifest(origin: str, local: dict) -> str | None:
    status, _, body = get(origin + "/.well-known/mutis-manifest.json")
    if status != 200:
        return f"manifest answered {status}"
    live = json.loads(body)
    if live["git_sha"] != local["git_sha"]:
        return f"live manifest is for {live['git_sha']}, not {local['git_sha']}"
    if live["files"] != local["files"]:
        diff = sorted(set(live["files"].items()) ^ set(local["files"].items()))
        return f"live manifest differs from the local build in {len(diff)} entries, e.g. {diff[:3]}"
    return None


def health(origin: str, local: dict) -> str | None:
    status, _, body = get(origin + "/api/v1/health")
    if status != 200:
        return f"/api/v1/health answered {status}"
    doc = json.loads(body)
    if doc.get("ok") is not True or not local["git_sha"].startswith(doc.get("version", "?")):
        return f"/api/v1/health: {doc}"
    return None


def chain(origin: str, _local: dict) -> str | None:
    status, _, body = get(origin + "/api/v1/stats")
    if status != 200:
        return f"/api/v1/stats answered {status}"
    return None if json.loads(body).get("chain_ok") is True else "chain_ok is not true (mutis-chain heartbeat or walletd)"


def main() -> int:
    p = argparse.ArgumentParser(description="deploy smoke test")
    p.add_argument("--origin", required=True)
    p.add_argument("--manifest", required=True, help="the local build's .well-known/mutis-manifest.json")
    p.add_argument("--api", action="store_true", help="also require /api/v1/health (mutis-api enabled)")
    p.add_argument("--chain", action="store_true", help="also require chain_ok in /api/v1/stats (mutis-chain enabled)")
    args = p.parse_args()
    with open(args.manifest) as f:
        local = json.load(f)
    checks = [(home, 20), (manifest, 20)] + ([(health, 20)] if args.api else []) + ([(chain, 150)] if args.chain else [])
    failed = 0
    for check, seconds in checks:
        deadline = time.monotonic() + seconds
        while True:
            try:
                problem = check(args.origin.rstrip("/"), local)
            except (OSError, ValueError, KeyError) as e:
                problem = f"{type(e).__name__}: {e}"
            if problem is None or time.monotonic() > deadline:
                break
            time.sleep(2)
        print(f"{'PASS' if problem is None else 'FAIL'} smoke {check.__name__}" + (f": {problem}" if problem else ""))
        failed += problem is not None
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
