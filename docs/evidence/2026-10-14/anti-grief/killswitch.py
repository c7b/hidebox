#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The packs kill switch on production (sixth pass): a fresh drive, `mutis-admin feature packs off`, an
invoice is refused with 503 feature_disabled {feature: packs}, `feature packs clear`, the drive deletes
itself. Run from the repository root: python3 -I docs/evidence/2026-10-14/anti-grief/killswitch.py"""
import hashlib
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests" / "e2e"))
from apiclient import ApiError, Client, b64u
O = "https://srv2052606.hstgr.cloud"
c = Client(O)
key = secrets.token_bytes(32)
_, res = c.call("POST", "/auth/register", {"identity_id": b64u(secrets.token_bytes(16)),
                "auth_verifier": b64u(hashlib.sha256(key).digest()), "pow": c.pow("register")})
c.token = res["token"]
print("drive", res["identity_id"])
print(subprocess.run(["ssh", "hidebox", "sudo mutis-admin feature packs off"], capture_output=True, text=True).stdout.strip()[:80], "...")
t0 = time.monotonic()
time.sleep(2.5)
try:
    c.call("POST", "/invoices", {"pack": "s30"})
    print("invoice while paused: ACCEPTED (wrong)")
except ApiError as e:
    print(f"invoice while paused ({time.monotonic() - t0:.1f} s after the switch):", e.status, e.code, e.body["error"].get("details"))
print(subprocess.run(["ssh", "hidebox", "sudo mutis-admin feature packs clear"], capture_output=True, text=True).stdout.strip()[:80], "...")
c.call("DELETE", "/me", {"auth_key": b64u(key)})
print("drive deleted")
