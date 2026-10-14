#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The sixth pass's devil (anti-griefing): try to sell out the packs and fill the free space fast.

  python3 -I tests/e2e/devil.py [--host hidebox] [--json OUT]

It never touches production. Like griefer.py it starts the local stack on the server (localstack.py:
`mutis-api --dev` with the fake chain, its own temporary data, as `build`) and talks to the API on
loopback through an ssh tunnel, forging X-Real-IP from documentation addresses (192.0.2.0/24,
198.51.100.0/24, 2001:db8::/32), so every request meets the per-network brakes. It prints what got
through and what was stopped, attack by attack:

  P1  one network makes 5 drives and asks each for the big pack
  P2  40 networks, one drive each, ask for the big pack (and pay with test money what they get)
  P3  a judge pass from 6 networks, 3 drives each
  P4  a drive that holds a pack (s30, paid with test money) asks for another (m30)
  F1  one network, 3 drives from their second day, reserves 256 MiB at a time (16 tries, 4 GiB)
  F2  one /48 rotating 8 /64s, a drive each, 4 reservations each (8 GiB)
  D1  one /48 rotating 40 /64s makes a drive each

Run from an older checkout (the same file copied in) it measures the code before the brakes. The
reservations are real files on the server's disk (posix_fallocate); the stack's removal frees them.
"""
import argparse
import json
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apiclient import ApiError, Client  # noqa: E402
from localstack import WORK, LocalStack  # noqa: E402

MiB = 1 << 20
DB = f"{WORK}/data/data/db/mutis.sqlite3"


def code(e: ApiError) -> str:
    return e.code if isinstance(e.code, str) else str(e.status)


def tally(results: list) -> dict:
    out = {"through": sum(1 for r in results if r == "ok"), "stopped": {}}
    for r in results:
        if r != "ok":
            out["stopped"][r] = out["stopped"].get(r, 0) + 1
    return out


def attempt(fn) -> str:
    try:
        fn()
        return "ok"
    except ApiError as e:
        return code(e)


def on_stack(stack: LocalStack, python: str) -> str:
    """A short Python program on the stack's own database, as build."""
    script = f"import sqlite3, sys; sys.path.insert(0, 'server'); c = sqlite3.connect({DB!r}); {python}"
    return stack.remote.as_build(f"cd {WORK} && python3 -I -c {shlex.quote(script)}")


def judge_pass(stack: LocalStack) -> str:
    return on_stack(stack, "from mutis import auth; code = auth.new_judge_code(); "
                           "c.execute('INSERT INTO judge_passes(code_hash, uses_left, created_at, pow_skips_left) "
                           "VALUES (?, 50, strftime(\\'%s\\',\\'now\\'), 500)', (auth.judge_hash(code),)); c.commit(); print(code)"
                    ).strip()


def graduate(stack: LocalStack) -> None:
    """Every drive so far is on its second active day (the patient griefer of the owner's concern)."""
    on_stack(stack, "c.execute('UPDATE identities SET distinct_days = 2'); c.commit()")


def drive(api: str, origin: str, ip: str, judge: str | None = None) -> Client | str:
    c = Client(api, ip, origin, judge=judge)
    try:
        c.register()
    except ApiError as e:
        return code(e)
    return c


def credited(c: Client, invoice_id: str, wait_s: int = 90) -> bool:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if c.call("GET", f"/invoices/{invoice_id}")[1]["status"] == "credited":
            return True
        time.sleep(2)
    return False


def run(stack: LocalStack) -> dict:
    api, origin, report = stack.api, stack.api, {}

    # P1: one network, five drives, the big pack each.
    p1, holder = [], None
    for _ in range(5):
        c = drive(api, origin, "192.0.2.10")
        if isinstance(c, str):
            p1.append(c)
            continue
        r = attempt(lambda: c.invoice("m30"))
        p1.append(r)
        holder = holder or (c if r == "ok" else None)
    report["P1 one network, 5 drives, m30 each"] = tally(p1)

    # P2: forty networks, one drive each; pay what they get with test money.
    p2, paid = [], []
    for i in range(40):
        c = drive(api, origin, f"2001:db8:{0xb00 + i:x}:1::1")
        if isinstance(c, str):
            p2.append(c)
            continue
        try:
            inv = c.invoice("m30")
            p2.append("ok")
        except ApiError as e:
            p2.append(code(e))
            continue
        pay = attempt(lambda: c.demo_pay(inv["invoice_id"]))
        paid.append((c, inv["invoice_id"]) if pay == "ok" else pay)
    credits = sum(1 for p in paid if not isinstance(p, str) and credited(*p))
    report["P2 40 networks, m30 each"] = tally(p2) | {
        "paid_with_test_money": credits, "pay_refused": sorted({p for p in paid if isinstance(p, str)})}
    stats = stack_stats(api)
    report["P2 /api/v1/stats after"] = {k: stats.get(k) for k in ("packs_sold_public", "packs_cap_public")}

    # P3: one judge pass from six networks, three drives each.
    code_ = judge_pass(stack)
    p3 = []
    for n in range(6):
        for _ in range(3):
            c = drive(api, origin, f"198.51.100.{20 + n}", judge=code_)
            p3.append(c if isinstance(c, str) else attempt(lambda: c.invoice("s30")))
    report["P3 a judge pass, 6 networks x 3 drives, s30 each"] = tally(p3)

    # P4: a drive that holds a pack asks for another.
    if holder is not None:
        inv = holder.call("POST", "/invoices", {"pack": "s30"})[1]
        pay = attempt(lambda: holder.demo_pay(inv["invoice_id"]))
        got = pay == "ok" and credited(holder, inv["invoice_id"])
        report["P4 a drive holding a pack asks for another"] = {
            "first_pack_credited": got if pay == "ok" else pay,
            "second": attempt(lambda: holder.invoice("m30")) if got else "skipped"}

    # F1: one network, three drives on their second day, 256 MiB reservations.
    drives = [drive(api, origin, "192.0.2.50") for _ in range(3)]
    graduate(stack)
    f1 = [attempt(lambda d=d: d.create_upload(256 * MiB - 64 * 1024)) if not isinstance(d, str) else d
          for d in drives for _ in range(6)][:16]
    report["F1 one network, 3 drives, 16 x 256 MiB"] = tally(f1)

    # F2: one /48, eight /64s, a drive each, four 256 MiB reservations each.
    drives = [drive(api, origin, f"2001:db8:c00:{k:x}::1") for k in range(8)]
    graduate(stack)
    f2 = [attempt(lambda d=d: d.create_upload(256 * MiB - 64 * 1024)) if not isinstance(d, str) else d
          for d in drives for _ in range(4)]
    report["F2 one /48, 8 /64s, 32 x 256 MiB"] = tally(f2)

    # D1: one /48 rotating forty /64s makes a drive each.
    d1 = [drive(api, origin, f"2001:db8:d00:{k:x}::1") for k in range(40)]
    report["D1 one /48, 40 /64s, a drive each"] = tally(["ok" if not isinstance(d, str) else d for d in d1])
    return report


def stack_stats(api: str) -> dict:
    try:
        return Client(api, "192.0.2.250").call("GET", "/stats")[1]
    except ApiError:
        return {}


def main() -> int:
    p = argparse.ArgumentParser(description="the sixth pass's devil (on a throwaway stack, never production)")
    p.add_argument("--host", default="hidebox")
    p.add_argument("--json", help="also write the report here")
    args = p.parse_args()
    started = time.time()
    with LocalStack(args.host) as stack:
        report = run(stack)
    report["seconds"] = round(time.time() - started)
    text = json.dumps(report, indent=1, sort_keys=False)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
