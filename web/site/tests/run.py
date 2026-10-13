# SPDX-License-Identifier: MIT
"""One command for every site test: python3 -I web/site/tests/run.py [--static]

Static checks always run. dates.js runs under Node (two time zones) when `node` exists, and the
browser checks run when `chromium` exists (on the server, as `build`); otherwise they are reported as
SKIP, never as PASS. Exit code 1 if anything failed.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools")]   # -I leaves the script's own directory out
import static_checks  # noqa: E402


def node_dates():
    node = shutil.which("node")
    if not node:
        return None
    major = int(subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()[1:].split(".")[0])
    flags = ["--experimental-default-type=module"] if major < 22 else []
    problems = []
    for tz in ("Europe/Madrid", "America/Mexico_City"):
        run = subprocess.run([node, *flags, "--test", str(HERE / "dates.test.mjs")], capture_output=True, text=True,
                             env={**os.environ, "TZ": tz})
        if run.returncode:
            problems.append(f"TZ={tz}: " + (run.stdout + run.stderr)[-600:])
    return problems


def llms_full():
    run = subprocess.run([sys.executable, "-I", str(HERE.parent / "tools" / "llms_full.py"), "--check"],
                         capture_output=True, text=True)
    return [run.stderr.strip() or run.stdout.strip()] if run.returncode else []


def main() -> int:
    started = time.time()
    results = [(name, fn()) for name, fn in static_checks.CHECKS]
    results.append(("llms-full.txt matches /how, /made and /fine-print", llms_full()))
    dates = node_dates()
    results.append(("dates.js in two time zones (M-08)", dates))
    notes = []
    if "--static" not in sys.argv and shutil.which("chromium"):
        import browser_checks
        results += browser_checks.run_all()
        notes = browser_checks.NOTES
    else:
        results.append(("browser checks", None))
    failed = 0
    for name, problems in results:
        if problems is None:
            print(f"SKIP {name}")
        elif problems:
            failed += 1
            print(f"FAIL {name}")
            for p in problems[:12]:
                print(f"     {p}")
        else:
            print(f"PASS {name}")
    for note in notes:
        print(f"note {note}")
    print(f"{len(results) - failed} of {len(results)} checks without failures, {time.time() - started:.0f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
