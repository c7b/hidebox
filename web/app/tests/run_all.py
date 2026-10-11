#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Every app-core check in one command (Python stdlib; needs Debian node 20 and Chromium, as on ultron):

  python3 -I web/app/tests/run_all.py

Runs the lint, the independent vector cross-check, the KATs under Node 20 and in headless Chromium
(with the app CSP), the no-WebAssembly run, the sidecar protocol and permission tests, the PoW and
scan benchmarks under CPU throttling, and the library against the real API (`server/bin/mutis-api
--dev`, from the same checkout). The live chain gates (G1/G2c) are separate: tests/README.md.
"""
import hashlib
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", "..", ".."))
PY = [sys.executable, "-I"]
HEADLESS = [*PY, os.path.join(TESTS, "headless.py")]
NODE_RUN = ["node", os.path.join(TESTS, "node-run.mjs")]
CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def run(cmd, env=None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)


def contract():
    """The library against `mutis-api --dev --pow-bits 8` on a free port with a fresh data directory,
    with one judge pass added to its database (the P-12 table) for the judge-pass checks."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as data:
        server = subprocess.Popen([*PY, os.path.join(ROOT, "server", "bin", "mutis-api"), "--dev", "--data", data,
                                   "--port", str(port), "--pow-bits", "8"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(60):
                try:
                    with urllib.request.urlopen(origin + "/api/v1/health", timeout=2) as res:
                        if res.status == 200:
                            break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("mutis-api --dev did not start")
            code = "judge-" + "".join(secrets.choice(CROCKFORD) for _ in range(24))
            with sqlite3.connect(os.path.join(data, "data", "db", "mutis.sqlite3")) as db:
                db.execute("INSERT INTO judge_passes(code_hash, uses_left, created_at) VALUES (?, ?, ?)",
                           (hashlib.sha256(code.encode()).digest(), 5, int(time.time())))
            p = run([*NODE_RUN, "--api", origin], env={**os.environ, "MUTIS_JUDGE_PASS": code})
        finally:
            server.terminate()
            log = server.communicate(timeout=10)[1]
    if p.returncode:
        p.stderr += "\n-- mutis-api --dev log (tail) --\n" + log[-3000:]
    return p


STEPS = [
    ("lint (A-08)", [*PY, os.path.join(TESTS, "lint_core.py")]),
    ("vectors, independent Python cross-check", [*PY, os.path.join(TESTS, "vectors", "crosscheck.py")]),
    ("KATs under Node 20 (A-01)", NODE_RUN),
    ("KATs in headless Chromium, app CSP (A-01, A-05)", [*HEADLESS, "--timeout", "600"]),
    ("no WebAssembly, V8 --jitless (A-09)", [*HEADLESS, "--jitless", "--fragment", "nowasm", "--timeout", "600"]),
    ("sidecar protocol, permissions, G4 (A-12)", [*PY, os.path.join(TESTS, "sidecar_test.py")]),
    ("18-bit PoW at 6x CPU throttling (A-13)", [*HEADLESS, "--page", "/app/tests/bench/bench.html", "--fragment", "pow", "--throttle", "6"]),
    ("in-browser scan, phone emulation at 4x (report)", [*HEADLESS, "--page", "/app/tests/bench/bench.html", "--fragment", "scan", "--throttle", "4", "--mobile"]),
    ("contract: the library against mutis-api --dev", contract),
]


def main():
    summary = []
    for name, step in STEPS:
        t0 = time.time()
        p = step() if callable(step) else run(step)
        tail = [line for line in p.stdout.splitlines() if line.strip()][-3:]
        shown = (line for line in p.stdout.splitlines() if not line.startswith("PASS ") or "  [" in line)
        print(f"\n== {name}\n" + "\n".join(shown))
        if p.returncode:
            print(p.stderr[-2000:])
        summary.append((name, p.returncode == 0, round(time.time() - t0, 1), tail[-1] if tail else ""))
    print("\n== summary")
    for name, ok, secs, last in summary:
        print(f"{'PASS' if ok else 'FAIL'}  {name:52} {secs:6}s  {last}")
    failed = sum(1 for _, ok, _, _ in summary if not ok)
    print(f"\n{'ALL PASS' if not failed else f'{failed} FAILED'} ({len(summary)} steps)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
