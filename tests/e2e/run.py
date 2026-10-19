#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The E2E runner (spec §17). Python stdlib only.

  python3 -I tests/e2e/run.py                         every scenario without chain transactions
  python3 -I tests/e2e/run.py --chain                 … plus the @chain ones (Esmeralda; E-J included)
  python3 -I tests/e2e/run.py --only E-01,E-15        just these
  python3 -I tests/e2e/run.py --chain --final         submission day: any SKIP fails the run
  python3 -I tests/e2e/run.py --list

It runs on the workstation (or as the operator on the server with --local) and drives headless Chromium 154 on
the server as the unprivileged `build` user through relay.py, over one multiplexed ssh connection. Admin
steps (takedown, tamper, freeze, canary-now) run on the server as mutis or drive; build never gets
sudo. Each scenario uses fresh browser contexts per actor. Screenshots and report.json go to --out.
"""
import argparse
import json
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
import harness  # noqa: E402
import scenarios  # noqa: E402,F401  (registers scenarios)
import scenarios_chain  # noqa: E402,F401
import scenarios_drive  # noqa: E402,F401
import test_headers  # noqa: E402
import test_privileges  # noqa: E402
from harness import CHAIN, REGISTRY, SSH_HOST, STAGING, Env, Failed, Remote, Skipped, T, scenario  # noqa: E402


@scenario("E-21", "Headers and privileges: D-01 and D-03 (D-02 is tests/e2e/test_logs.py)")
def e21(t: T) -> None:
    for name, problems in test_headers.run(t.origin, not app_deployed(t.origin), []):
        t.check(not problems, f"D-01 {name} {problems}")
    for line in test_privileges.inside(t.env.remote) + test_privileges.outside(t.origin):
        t.check(line.startswith(("PASS", "SKIP")), f"D-03 {line}")


def app_deployed(origin: str) -> bool:
    req = urllib.request.Request(origin + "/", headers={"User-Agent": "mutis-e2e"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return b'id="mutis-drop"' in res.read()


def select(only: str, chain: bool, staging: bool) -> list[harness.Scenario]:
    if only:
        wanted = [s.strip() for s in only.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in REGISTRY]
        if unknown:
            raise SystemExit(f"unknown scenario ids: {unknown}")
        picked = [REGISTRY[s] for s in wanted]
    else:
        picked = [s for s in REGISTRY.values()
                  if (chain or CHAIN not in s.tags) and (staging or STAGING not in s.tags)]
    return sorted(picked, key=lambda s: (s.sid == "E-03", s.sid))


def run_one(env: Env, sc: harness.Scenario, browser_ok: bool) -> dict:
    t = T(env, sc.sid)
    started = time.monotonic()
    status, detail = "PASS", ""
    try:
        if not browser_ok and sc.sid not in ("E-03", "E-21"):
            raise Skipped("the app isn't deployed yet (the home page has no drop widget)")
        sc.fn(t)
    except Skipped as e:
        status, detail = "SKIP", str(e)
    except (Failed, cdp.CdpError) as e:
        status, detail = "FAIL", str(e)
    except Exception as e:  # a scenario bug or an API error: report it with its place
        status, detail = "FAIL", f"{type(e).__name__}: {e} @ {traceback.extract_tb(e.__traceback__)[-1].lineno}"
    finally:
        if status == "FAIL":
            for i, ctx in enumerate(t.contexts):
                for j, page in enumerate(ctx.pages):
                    try:
                        page.screenshot(str(env.out / f"{sc.sid}-failure-{i}-{j}.png"))
                    except (cdp.CdpError, OSError, ValueError):
                        pass
        t.close()
    return {"id": sc.sid, "title": sc.title, "status": status, "detail": detail,
            "seconds": round(time.monotonic() - started, 1), "notes": t.notes}


def main() -> int:
    p = argparse.ArgumentParser(description="mutis E2E runner")
    p.add_argument("--origin", default="https://srv2052606.hstgr.cloud")
    p.add_argument("--host", default=SSH_HOST, help="ssh host of the server (MUTIS_SSH_HOST)")
    p.add_argument("--local", action="store_true", help="run on the server itself (as the operator)")
    p.add_argument("--only", default="")
    p.add_argument("--chain", action="store_true", help="include scenarios that make Esmeralda transactions")
    p.add_argument("--staging", action="store_true", help="include scenarios that change server limits")
    p.add_argument("--final", action="store_true", help="a skipped scenario fails the run (acceptance D-08)")
    p.add_argument("--out", type=Path, default=Path("e2e-artifacts"))
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    chosen = select(args.only, args.chain, args.staging)
    if args.list:
        for s in chosen:
            print(f"{s.sid:6} {','.join(s.tags):8} {s.title}")
        return 0
    out = args.out / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    control = Path(tempfile.mkdtemp(prefix="mutis-e2e-"))
    env = Env(args.origin.rstrip("/"), Remote(None if args.local else args.host, control), out)
    browser_ok = app_deployed(env.origin)
    if browser_ok:
        env.stage()
    results = []
    for sc in chosen:
        result = run_one(env, sc, browser_ok)
        results.append(result)
        print(f"{result['status']:4} {sc.sid:6} {result['seconds']:6.1f}s  {sc.title}"
              + (f"\n           {result['detail']}" if result["detail"] else ""), flush=True)
    (out / "report.json").write_text(json.dumps({"origin": env.origin, "results": results}, indent=1))
    failed = [r for r in results if r["status"] == "FAIL" or (args.final and r["status"] == "SKIP")]
    counts = {s: sum(r["status"] == s for r in results) for s in ("PASS", "FAIL", "SKIP")}
    verdict = "FAIL" if failed else "PASS" if not counts["SKIP"] else "PASS (with skips; --final fails on them)"
    print(f"e2e: {verdict} {counts} → {out}/report.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
