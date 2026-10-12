# SPDX-License-Identifier: MIT
"""A strict decoder for the CBOR that tari_bor writes (RFC 8949, definite lengths only): enough to read
a transaction envelope back before the proxy relays it (handlers/chain.py). Structs come as arrays,
enums as [variant index, payload], addresses as tagged byte strings; a tag's content is returned bare.
Anything else (indefinite lengths, floats, reserved values) is refused."""
import struct

MAX_ITEMS = 50_000
MAX_DEPTH = 32


class CborError(ValueError):
    pass


def loads(data: bytes):
    decoder = _Decoder(data)
    value = decoder.item(0)
    if decoder.pos != len(data):
        raise CborError("trailing bytes")
    return value


class _Decoder:
    def __init__(self, data: bytes):
        self.data, self.pos, self.items = data, 0, 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise CborError("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def head(self) -> tuple[int, int, int]:
        first = self.take(1)[0]
        major, info = first >> 5, first & 31
        if info < 24:
            return major, info, info
        if info > 27:
            raise CborError("indefinite length or reserved")
        size = 1 << (info - 24)
        return major, info, int.from_bytes(self.take(size), "big")

    def item(self, depth: int):
        self.items += 1
        if self.items > MAX_ITEMS or depth > MAX_DEPTH:
            raise CborError("too large")
        major, info, arg = self.head()
        if major == 0:
            return arg
        if major == 1:
            return -1 - arg
        if major == 2:
            return bytes(self.take(arg))
        if major == 3:
            try:
                return self.take(arg).decode("utf-8")
            except UnicodeDecodeError:
                raise CborError("bad text") from None
        if major == 4:
            return [self.item(depth + 1) for _ in range(arg)]
        if major == 5:
            pairs = [(self.item(depth + 1), self.item(depth + 1)) for _ in range(arg)]
            if any(not isinstance(k, (str, int)) for k, _ in pairs):
                raise CborError("bad map key")
            return dict(pairs)
        if major == 6:
            return self.item(depth + 1)
        if info in (20, 21):
            return info == 21
        if info == 22:
            return None
        raise CborError("unsupported simple value")
