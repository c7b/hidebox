#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The receive address of a Minotari console wallet, read off its TUI (it prints it nowhere else).

  python3 -I deploy/ootle/l1-address.py -- <command that starts the wallet's TUI>
  python3 -I deploy/ootle/l1-address.py --check <base58 address>

Runs the command in a pseudo-terminal for half a minute, tabs through the screens, quits, and prints every base58
string the TUI drew that is a valid Tari address: its DammSum checksum holds and its network byte is the mainnet's
(0x00). For each it prints the base58 form and the emoji form (each byte one emoji, RFC-0155's alphabet, as
server/mutis/ootle_addr.py has it). Python standard library only.
"""
import argparse
import os
import pty
import re
import select
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from mutis.ootle_addr import EMOJI_ALPHABET  # noqa: E402

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MAINNET = 0x00


def decode(address: str) -> bytes | None:
    """Tari's base58 address: the network and features bytes as one character each, then the rest as one number."""
    if len(address) < 60 or any(c not in B58 for c in address):
        return None
    n = 0
    for c in address[2:]:
        n = n * 58 + B58.index(c)
    rest = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([B58.index(address[0]), B58.index(address[1])]) + rest


def dammsum(data: bytes) -> int:
    """tari_common_types dammsum: coefficients [4, 3, 1] over GF(2^8), mask 0x1b."""
    r = 0
    for d in data:
        r ^= d
        overflow = r & 0x80
        r = (r << 1) & 0xFF
        if overflow:
            r ^= 0x1B
    return r


def valid(address: str) -> bytes | None:
    body = decode(address)
    if not body or len(body) not in (35, 67) or body[0] != MAINNET or dammsum(body[:-1]) != body[-1]:
        return None
    return body


def screen(argv: list[str], seconds: float = 30) -> str:
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(TERM="xterm", COLUMNS="220", LINES="60")
        os.execvp(argv[0], argv)
    import fcntl
    import struct
    import termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 220, 0, 0))
    buf = b""

    def pump(for_s: float) -> None:
        nonlocal buf
        end = time.time() + for_s
        while time.time() < end:
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    buf += os.read(fd, 65536)
                except OSError:
                    return
    pump(seconds * 0.6)
    for _ in range(6):
        os.write(fd, b"\t")
        pump(seconds * 0.06)
    os.write(fd, b"q")
    pump(3)
    try:
        os.kill(pid, signal.SIGINT)
    except OSError:
        pass
    return re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b" ", buf).decode("utf-8", "replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check")
    p.add_argument("command", nargs="*")
    args = p.parse_args()
    candidates = [args.check] if args.check else sorted(set(re.findall(r"\b[1-9A-HJ-NP-Za-km-z]{60,120}\b",
                                                                       screen(args.command))))
    found = 0
    for address in candidates:
        body = valid(address)
        if body:
            found += 1
            print(f"base58  {address}")
            print(f"emoji   {''.join(EMOJI_ALPHABET[b] for b in body)}")
            print(f"        network 0x{body[0]:02x} (mainnet), features 0x{body[1]:02x}, DammSum ok")
    if not found:
        print("l1-address: no valid mainnet address found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
