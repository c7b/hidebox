#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Notarize the live release on the Ootle (brand patch P-9, claim C10), as root after a deploy:

  sudo python3 -I /srv/mutis/app/current/deploy/scripts/notarize-release.py

With `features.seallog` on and `ootle.seallog_component` set, it calls SealLog's notarize() with the
SHA-256 of the served /.well-known/mutis-manifest.json (through `mutis-admin notarize`, as drive, the
only service user walletd lets in) and appends {release, manifest_sha256, tx_id, at} to
/srv/mutis/status/releases.json, which Caddy serves at /releases.json for /security to link.
A release that is already listed is not notarized twice. With SealLog off it does nothing.
Python standard library only.
"""
import contextlib
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

CONFIG = Path("/etc/mutis/mutis.toml")
CURRENT = Path("/srv/mutis/app/current")
LEDGER = Path("/srv/mutis/status/releases.json")


def publish(path: Path, text: str) -> None:
    """Write `path` in the shared status directory through a new file of a random name, created exclusively,
    its mode set on the open file, then renamed over `path`: a name another service user planted there (a
    symlink to some other file) is never opened or followed (security-audit-1). This runs as root.."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def main() -> int:
    with open(CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    if not (cfg.get("features", {}).get("seallog") and cfg.get("ootle", {}).get("seallog_component")):
        print("notarize: skipped (features.seallog is off)")
        return 0
    release = (CURRENT / "RELEASE").read_text().strip()
    digest = hashlib.sha256((CURRENT / "dist" / ".well-known" / "mutis-manifest.json").read_bytes()).hexdigest()
    ledger = json.loads(LEDGER.read_text()) if LEDGER.is_file() else []
    if any(r["release"] == release and r["manifest_sha256"] == digest for r in ledger):
        print(f"notarize: {release} is already notarized")
        return 0
    out = subprocess.run(["runuser", "-u", "drive", "--", "env", f"MUTIS_CONFIG={CONFIG}", "python3", "-I",
                          str(CURRENT / "server" / "bin" / "mutis-admin"), "notarize", digest],
                         capture_output=True, text=True, cwd="/tmp")
    try:
        result = json.loads(out.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        result = {}
    if out.returncode != 0 or not result.get("committed"):
        print(f"notarize: FAIL ({out.stderr.strip()[-200:] or result})", file=sys.stderr)
        return 1
    ledger.append({"release": release, "manifest_sha256": digest, "tx_id": result["tx_id"],
                   "at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    publish(LEDGER, json.dumps(ledger, indent=1) + "\n")
    print(f"notarize: {release} manifest {digest[:12]}… in tx {result['tx_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
