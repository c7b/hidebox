# SPDX-License-Identifier: MIT
"""Test-side CBOR: decode a fixture envelope with the server's decoder and encode a tampered copy back
(definite lengths; tags are dropped, which the decoder treats as transparent anyway)."""
import base64

from mutis import cbor


def decode(envelope_b64: str):
    return cbor.loads(base64.b64decode(envelope_b64))


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * size):
            return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    raise ValueError("too large")


def encode(value) -> bytes:
    if value is True or value is False or value is None:
        return bytes([0xF5 if value is True else 0xF4 if value is False else 0xF6])
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return _head(3, len(raw)) + raw
    if isinstance(value, list):
        return _head(4, len(value)) + b"".join(encode(v) for v in value)
    if isinstance(value, dict):
        return _head(5, len(value)) + b"".join(encode(k) + encode(v) for k, v in value.items())
    raise TypeError(type(value).__name__)
