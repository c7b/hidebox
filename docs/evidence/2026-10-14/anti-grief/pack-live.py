#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A pack bought on chain with a judge pass, through the API (the sixth pass's live check).

  python3 -I docs/evidence/2026-10-14/anti-grief/pack-live.py ORIGIN JUDGE_PASS

E-13 pays from the browser's wallet, which in direct mode needs a sponsor grant from the evidence slice;
that slice was spent for the day, so this pays with test money instead (POST /invoices/{id}/demo-pay with
the pass: the evidence slice's demo_pay budget), a real stealth transaction that the chain worker proves
and an indexer confirms before crediting. Then: the drive holds the pack (/me), a second purchase is
refused (409 pack_active), /stats shows the public slice; the drive's id is printed for release-pack.
It prints no token, key, address or transaction id.
"""
import hashlib
import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests" / "e2e"))
from apiclient import ApiError, Client, b64u  # noqa: E402


def main() -> int:
    origin, judge = sys.argv[1], sys.argv[2]
    c = Client(origin, judge=judge)
    auth_key = secrets.token_bytes(32)
    body = {"identity_id": b64u(secrets.token_bytes(16)), "auth_verifier": b64u(hashlib.sha256(auth_key).digest())}
    _, res = c.call("POST", "/auth/register", body)
    c.token = res["token"]
    print("drive", res["identity_id"])
    status, inv = c.call("POST", "/invoices", {"pack": "s30"})
    print("invoice", status, inv["status"], "amount_ut", inv["amount_ut"])
    status, again = c.call("POST", "/invoices", {"pack": "s30"})
    print("same pack again while open:", status, "same invoice" if again["invoice_id"] == inv["invoice_id"] else "NEW")
    status, job = c.call("POST", f"/invoices/{inv['invoice_id']}/demo-pay", {})
    print("demo-pay", status)
    started, seen = time.monotonic(), None
    while time.monotonic() - started < 900:
        got = c.call("GET", f"/invoices/{inv['invoice_id']}")[1]
        if got["status"] != seen:
            seen = got["status"]
            checks = got["payments"][0]["checks"] if got["payments"] else {}
            print(f"{round(time.monotonic() - started)} s: {seen} {json.dumps(checks)}")
        if seen == "credited":
            break
        time.sleep(5)
    me = c.call("GET", "/me")[1]
    print("me.pack", json.dumps({k: me["pack"][k] for k in ("id", "bytes")} if me["pack"] else None),
          "plan", me["plan"], "renew_from - until", (me["pack"]["renew_from"] - me["pack"]["until"]) if me["pack"] else None)
    try:
        c.call("POST", "/invoices", {"pack": "m30"})
        print("second pack: ACCEPTED (wrong)")
    except ApiError as e:
        print("second pack:", e.status, e.code, e.body["error"]["message"])
    stats = c.call("GET", "/stats")[1]
    print("stats", json.dumps({k: stats[k] for k in ("packs_sold_public", "packs_cap_public")}))
    return 0 if seen == "credited" and me["pack"] else 1


if __name__ == "__main__":
    sys.exit(main())
