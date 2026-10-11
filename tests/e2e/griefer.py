#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""E-23, the griefer (spec §17.2, §9.8): try to break the judge path cheaply, then check it holds.

  python3 -I tests/e2e/griefer.py [--host ultron] [--then-judge https://…] [--slow-only [--unbuffered]]

It never touches production. It starts the local stack on the server (localstack.py: `mutis-api
--dev`, with fakes, small limits and its own temporary data, behind the production Caddyfile, all as
`build`) and talks to the API directly on loopback through an ssh tunnel, so the API believes the
forged X-Real-IP values (documentation addresses, 2001:db8::/32). From ten /48s and 200 /64s it fills
the anonymous lanes, registers 200 lockers, drains the public `courier` and `demo_pay` slices, pushes
PoW difficulty up from one /64 by spending proofs, and makes 60 path-only attempts on a link +
password share. Then it holds 300 slow uploads open through Caddy (a byte every few seconds) while it
counts the API's threads and times a health request through Caddy. It checks what must still hold:
the free quota didn't move, PoW escalated for the hammering /64 while a fresh /48 still gets the base
difficulty, a small file still fits, the password link isn't locked, the public slices were refused
with budget_exhausted, and the slow uploads held no API thread while the API kept answering. The
stack is removed afterwards.

--then-judge ORIGIN finally runs E-J (the judge script) against that origin, the real site.
--slow-only runs just the slow uploads (a minute instead of half an hour of proofs of work), and
--unbuffered runs the stack without Caddy's request buffering, to show what that check guards against
(it is then expected to fail).
"""
import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apiclient  # noqa: E402
from apiclient import ApiError, Client  # noqa: E402
from localstack import WEB_PORT, LocalStack  # noqa: E402

STOP = {"rate_limited", "lane_full", "uploads_frozen", "too_large", "budget_exhausted", "quota_exceeded",
        "pow_too_hard", "probation_limit"}
SLOW_UPLOADS = 300
SLOW_HOLD_S = 20
SLOW_EXTRA_THREADS = 25        # the API may start a few threads of its own meanwhile; 300 held would be ~300
HEALTH_MAX_S = 2.0


def ip(net48: int, net64: int = 0) -> str:
    return f"2001:db8:{0xa00 + net48:x}:{net64:x}::1"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mutis-griefer"}), timeout=20) as res:
        return json.load(res)


def until_refused(make, attempts: int, patience: int = 20) -> tuple[int, set]:
    """Call make(i) until it has been refused `patience` times in a row; return (accepted, codes)."""
    done, codes, refused = 0, set(), 0
    for i in range(attempts):
        try:
            make(i)
            done, refused = done + 1, 0
        except ApiError as e:
            codes.add(e.code)
            refused += e.code in STOP
            if refused >= patience:
                break
    return done, codes


def grief(api: str, origin: str, file_mib: int) -> tuple[dict, set, dict]:
    """The cheap attacks; returns the report, the path-only codes and the password share."""
    report = {}
    anon = [Client(api, ip(i // 20, i % 20), origin) for i in range(200)]
    report["anon_lane"] = until_refused(lambda i: anon[i % 200].upload(file_mib << 20), 2000)
    report["small_lane"] = until_refused(lambda i: anon[i % 200].upload(2 << 20), 2000)
    report["lockers"] = until_refused(lambda i: Client(api, ip(i % 10, 100 + i), origin).register(), 200)

    drops = []
    for i in range(10):
        owner = Client(api, ip(i, 200), origin)
        try:
            owner.register()
            drops.append(owner.create_drop(apiclient.random_address(), "griefer")["drop_id"])
        except ApiError as e:
            report.setdefault("drop_setup", []).append(e.code)
    senders = [Client(api, ip(i % 10, 300 + i), origin) for i in range(100)]
    report["courier"] = until_refused(
        lambda i: senders[i % 100].courier_to_drop(drops[i % len(drops)]), 2000) if drops else (0, {"no_drops"})
    payers = [Client(api, ip(20 + i % 10, 400 + i), origin) for i in range(40)]     # /48s that registered nothing yet

    def demo(i):
        payer = payers[i % 40]
        if not payer.token:
            payer.register()
        payer.demo_pay(payer.invoice()["invoice_id"])
    report["demo_pay"] = until_refused(demo, 200)

    # Escalation counts proofs used, not challenges asked: one /64 spends 15 in a few minutes.
    hot = Client(api, ip(30, 999), origin)
    for _ in range(15):
        try:
            hot.upload(1000)
        except ApiError:
            pass
    fresh = Client(api, "2001:db8:bbbb:1::1", origin)
    report["pow_bits"] = {"hammering /64": hot.call("POST", "/pow", {"purpose": "upload"})[1]["difficulty"],
                          "fresh /48": fresh.call("POST", "/pow", {"purpose": "upload"})[1]["difficulty"]}

    owner = Client(api, ip(5, 500), origin)
    shared = owner.share(owner.upload(1000), max_views=3, with_password=True)
    prober = Client(api, ip(6, 600), origin)
    codes = set()
    for _ in range(60):
        try:
            prober.call("POST", f"/s/{shared['share_id']}/peek", headers={"X-Mutis-Access": apiclient.b64u(b"\0" * 32)})
        except ApiError as e:
            codes.add(e.code)
    return report, codes, {"owner": owner, "share": shared}


def slow_uploads(stack: LocalStack, origin: str) -> dict:
    """SLOW_UPLOADS chunk uploads through Caddy that send a byte every few seconds."""
    up = Client(stack.api, "2001:db8:cccc:1::1", origin).create_upload(1 << 20)
    head = (f"PUT /api/v1/uploads/{up['upload_id']}/chunks/0 HTTP/1.1\r\nHost: 127.0.0.1:{WEB_PORT}\r\n"
            f"Origin: {origin}\r\nContent-Type: application/octet-stream\r\nX-Mutis-Chunk-SHA256: {'A' * 43}\r\n"
            f"Content-Length: {up['size_stored']}\r\n\r\n").encode()
    before = stack.api_threads()
    socks = []
    try:
        for _ in range(SLOW_UPLOADS):
            s = socket.create_connection(("127.0.0.1", WEB_PORT), timeout=10)
            s.sendall(head + b"\0")
            socks.append(s)
        end, slowest, peak = time.monotonic() + SLOW_HOLD_S, 0.0, before
        while time.monotonic() < end:
            for s in socks:
                try:
                    s.sendall(b"\0")
                except OSError:
                    pass                               # an upload Caddy gave up on counts as not held
            started = time.monotonic()
            try:
                get_json(stack.web + "/api/v1/health")
            except OSError:
                pass                                   # no answer within get_json's timeout: counted below
            slowest = max(slowest, time.monotonic() - started)
            peak = max(peak, stack.api_threads())
            time.sleep(3)
    finally:
        for s in socks:
            s.close()
    return {"held": len(socks), "api_threads_before": before, "api_threads_peak": peak,
            "slowest_health_s": round(slowest, 2)}


def cheap_attacks(stack: LocalStack, origin: str, file_mib: int, checks: list) -> dict:
    """The attacks and what must hold after them; appends to `checks`, returns the report."""
    quota_before = get_json(stack.api + "/api/v1/stats")["free_quota_bytes"]
    report, codes, link = grief(stack.api, origin, file_mib)
    quota_after = get_json(stack.api + "/api/v1/stats")["free_quota_bytes"]
    checks.append(("the free quota didn't move", quota_after == quota_before, f"{quota_before} → {quota_after}"))
    bits = report["pow_bits"]
    checks.append(("PoW escalates for the hammering /64 only; a fresh /48 gets the base difficulty",
                   bits["hammering /64"] > bits["fresh /48"] and bits["fresh /48"] <= 16, str(bits)))
    try:
        Client(stack.api, "2001:db8:bbbb:2::1", origin).upload(500 * 1024)
        checks.append(("a 500 KB file still fits", True, ""))
    except ApiError as e:
        checks.append(("a 500 KB file still fits", False, e.code))
    status = link["owner"].call("GET", f"/s/{link['share']['share_id']}")[1]
    checks.append(("path-only attempts never lock a link (the prober may be rate limited)",
                   "bad_link" in codes and codes <= {"bad_link", "rate_limited"} and status["state"] == "active",
                   f"{sorted(codes)}, {status['state']}"))
    for slice_ in ("courier", "demo_pay"):
        refused = report[slice_][1]
        checks.append((f"the public {slice_} slice ran dry and said so", "budget_exhausted" in refused, str(sorted(refused))))
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="E-23 griefer (on a throwaway stack, never production)")
    p.add_argument("--host", default="ultron")
    p.add_argument("--then-judge", metavar="ORIGIN", help="run E-J against this origin afterwards")
    p.add_argument("--slow-only", action="store_true", help="only the slow uploads through Caddy")
    p.add_argument("--unbuffered", action="store_true", help="the stack without Caddy's request buffering")
    p.add_argument("--file-mib", type=int, default=6, help="size of the anonymous-lane uploads")
    args = p.parse_args()
    checks, report = [], {}
    with LocalStack(args.host, buffered=not args.unbuffered) as stack:
        origin = stack.api                             # mutis-api --dev's own origin, for the Origin header
        if not args.slow_only:
            report = cheap_attacks(stack, origin, args.file_mib, checks)
        slow = slow_uploads(stack, origin)
        report["slow_uploads"] = slow
        grew = slow["api_threads_peak"] - slow["api_threads_before"]
        checks.append((f"{slow['held']} slow uploads held no API thread", grew <= SLOW_EXTRA_THREADS,
                       f"{slow['api_threads_before']} → {slow['api_threads_peak']} threads"))
        checks.append(("the API answered through Caddy meanwhile", slow["slowest_health_s"] <= HEALTH_MAX_S,
                       f"slowest {slow['slowest_health_s']} s"))
    print(json.dumps({k: (v if not isinstance(v, tuple) else {"accepted": v[0], "refused_with": sorted(v[1])})
                      for k, v in report.items()}, indent=1))
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name} ({detail})")
    failed = any(not ok for _, ok, _ in checks)
    if args.then_judge and not failed:
        failed = subprocess.run([sys.executable, "-I", str(Path(__file__).parent / "run.py"), "--origin", args.then_judge,
                                 "--host", args.host, "--chain", "--only", "E-J"]).returncode != 0
    print(f"griefer: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
