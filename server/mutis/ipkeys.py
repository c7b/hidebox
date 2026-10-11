# SPDX-License-Identifier: MIT
"""IP keys (spec §6.2): keyed hashes of address prefixes, with a key that lives in memory for one UTC day.

Rate limits key on these 8-byte values. The day key is never written anywhere, so yesterday's keys
can't be linked to an address once the process has rolled over.
"""
import hashlib
import hmac
import ipaddress
import secrets
import threading

TRUSTED_PEERS = {"127.0.0.1", "::1"}


class IpKeys:
    def __init__(self, on_rotate=None):
        self._lock = threading.Lock()
        self._day = -1
        self._key = b""
        self._on_rotate = on_rotate

    def _day_key(self, now: int) -> bytes:
        today = now // 86400
        with self._lock:
            if today != self._day:
                self._day, self._key = today, secrets.token_bytes(32)
                rotated = True
            else:
                rotated = False
            key = self._key
        if rotated and self._on_rotate:
            self._on_rotate()
        return key

    def keyed(self, label: bytes, now: int) -> bytes:
        return hmac.new(self._day_key(now), label, hashlib.sha256).digest()[:8]

    def keys(self, ip_text: str, now: int) -> tuple[bytes, bytes]:
        """(ip64, ip48): IPv6 /64 and /48 prefixes, or the full IPv4 address and its /24."""
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            ip = ipaddress.ip_address("0.0.0.0")
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.version == 4:
            narrow = b"4:" + ip.packed
            wide = b"4/24:" + ip.packed[:3]
        else:
            narrow = b"6/64:" + ip.packed[:8]
            wide = b"6/48:" + ip.packed[:6]
        return self.keyed(narrow, now), self.keyed(wide, now)


def client_ip(peer: str, real_ip_header: str | None) -> str:
    """X-Real-IP is trusted only when the TCP peer is loopback (Caddy on the same host)."""
    if peer in TRUSTED_PEERS and real_ip_header:
        return real_ip_header.strip()
    return peer
