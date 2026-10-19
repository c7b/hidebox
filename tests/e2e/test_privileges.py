#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""D-03 (and D-11): privilege separation on the server, checked from inside and from outside.

  python3 -I tests/e2e/test_privileges.py [--host H] [--origin URL]

Inside: deploy/scripts/privilege-check.sh as root on the server (sent on stdin): which users can
reach walletd (5100) and the L1 wallet (18143), Caddy's admin socket, secret.key, the keyring
credential, the served release, /home/drive and /srv/mutis/data; no password on any command line;
npm and npx absent. Outside: from this machine, nothing but 22, 80 and 443 answers on the server's
public addresses (the API, walletd, the L1 wallet and Caddy's admin all listen on loopback only).
"""
import argparse
import socket
import sys
import tempfile
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SSH_HOST, Remote  # noqa: E402

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "privilege-check.sh"
CLOSED_PORTS = (5100, 8787, 18143, 2019, 9000, 9100)


def inside(remote: Remote) -> list[str]:
    out = remote.run("sudo bash -s", CHECK_SCRIPT.read_bytes(), check=False)
    return [line for line in out.splitlines() if line.startswith(("PASS", "FAIL", "SKIP"))]


def outside(origin: str) -> list[str]:
    host = urllib.parse.urlsplit(origin).hostname
    lines = []
    for family, label in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
        try:
            address = socket.getaddrinfo(host, None, family)[0][4][0]
        except OSError:
            lines.append(f"SKIP no {label} address for {host}")
            continue
        for port in CLOSED_PORTS:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                reachable = s.connect_ex((address, port)) == 0
            lines.append(f"{'FAIL' if reachable else 'PASS'} port {port} is closed from outside ({label} {address})")
    return lines


def main() -> int:
    p = argparse.ArgumentParser(description="D-03 privilege tests")
    p.add_argument("--host", default=SSH_HOST)
    p.add_argument("--origin", default="https://hidebox.app")
    args = p.parse_args()
    lines = inside(Remote(args.host, Path(tempfile.mkdtemp(prefix="mutis-priv-")))) + outside(args.origin)
    print("\n".join(lines))
    failed = [line for line in lines if line.startswith("FAIL")]
    print(f"test_privileges: {'FAIL' if failed else 'PASS'} ({len(lines) - len(failed)}/{len(lines)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
