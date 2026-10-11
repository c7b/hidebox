# SPDX-License-Identifier: MIT
"""Ootle addresses (bech32m) and the address input classifier (spec §4.9.4, §10.1).

Layout (tari-ootle v0.45.0 crates/ootle_address): HRP 'otl_esm_' on Esmeralda (network byte 0x26),
then bech32m(owner_pk[32] || view_pk[32] || pay_ref[0..64]). The HRP carries the network.
"""
import re

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32M_CONST = 0x2BC830A3
TESTNET_HRP = "otl_esm_"
MAX_PAY_REF = 64
MAX_LENGTH = 300

# Tari's 256-emoji address alphabet, RFC-0155 order. Copied from tari-project/tari
# base_layer/common_types/src/emoji.rs at commit bf3473b78783c158c2357c03c5dcc41945d41a86
# (file sha256 4d81892819f52cb5db30810db4906b6a3efb7e9b10a90fcfefac1e210f4060a6), BSD-3-Clause.
EMOJI_ALPHABET = (
    "🐢📟🌈🌊🎯🐋🌙🤔🌕⭐🎋🌰🌴🌵🌲🌸🌹🌻🌽🍀🍁🍄🥑🍆🍇🍈🍉🍊🍋🍌🍍🍎🍐🍑🍒🍓🍔🍕🍗🍚🍞🍟🥝🍣🍦🍩🍪🍫"
    "🍬🍭🍯🥐🍳🥄🍵🍶🍷🍸🍾🍺🍼🎀🎁🎂🎃🤖🎈🎉🎒🎓🎠🎡🎢🎣🎤🎥🎧🎨🎩🎪🎬🎭🎮🎰🎱🎲🎳🎵🎷🎸🎹🎺🎻🎼🎽🎾"
    "🎿🏀🏁🏆🏈⚽🏠🏥🏦🏭🏰🐀🐉🐊🐌🐍🦁🐐🐑🐔🙈🐗🐘🐙🐚🐛🐜🐝🐞🦋🐣🐨🦀🐪🐬🐭🐮🐯🐰🦆🦂🐴🐵🐶🐷🐸🐺🐻"
    "🐼🐽🐾👀👅👑👒🧢💅👕👖👗👘👙💃👛👞👟👠🥊👢👣🤡👻👽👾🤠👃💄💈💉💊💋👂💍💎💐💔🔒🧩💡💣💤💦💨💩➕💯"
    "💰💳💵💺💻💼📈📜📌📎📖📿📡⏰📱📷🔋🔌🚰🔑🔔🔥🔦🔧🔨🔩🔪🔫🔬🔭🔮🔱🗽😂😇😈🤑😍😎😱😷🤢👍👶🚀🚁🚂🚚"
    "🚑🚒🚓🛵🚗🚜🚢🚦🚧🚨🚪🚫🚲🚽🚿🧲"
)
_EMOJI_SET = frozenset(EMOJI_ALPHABET)
_BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{60,100}$")
_IGNORED_IN_EMOJI = {"️", "‍", " ", "\n", "\t"}

# Classes and the error code each one maps to (None = acceptable).
ERROR_FOR_CLASS = {"ootle_testnet": None, "ootle_other": "mainnet_address", "l1_emoji": "l1_address",
                   "l1_base58": "l1_address", "invalid": "bad_address"}


def _polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert_bits(data, frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = bits = 0
    out = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or (acc << (tobits - bits)) & maxv:
        raise ValueError("bad padding")
    return out


def encode(hrp: str, payload: bytes) -> str:
    data = _convert_bits(payload, 8, 5, True)
    pm = _polymod(_hrp_expand(hrp) + data + [0] * 6) ^ BECH32M_CONST
    checksum = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(CHARSET[d] for d in data + checksum)


def decode(address: str) -> tuple[str, bytes]:
    """bech32m → (hrp, payload). Raises ValueError on any malformation."""
    if not isinstance(address, str) or len(address) > MAX_LENGTH or not address.isascii():
        raise ValueError("not an address")
    if address.lower() != address and address.upper() != address:
        raise ValueError("mixed case")
    address = address.lower()
    pos = address.rfind("1")
    if pos < 1 or pos + 7 > len(address):
        raise ValueError("no separator")
    hrp, rest = address[:pos], address[pos + 1:]
    if any(c not in CHARSET for c in rest) or any(not 33 <= ord(c) <= 126 for c in hrp):
        raise ValueError("bad characters")
    data = [CHARSET.index(c) for c in rest]
    if _polymod(_hrp_expand(hrp) + data) != BECH32M_CONST:
        raise ValueError("bad checksum")
    return hrp, bytes(_convert_bits(data[:-6], 5, 8, False))


def parse_testnet(address: str) -> tuple[bytes, bytes, bytes]:
    """Return (owner_pk, view_pk, pay_ref) of a valid Esmeralda address. Raises ValueError."""
    hrp, payload = decode(address)
    if hrp != TESTNET_HRP or not 64 <= len(payload) <= 64 + MAX_PAY_REF:
        raise ValueError("not an Esmeralda address")
    return payload[:32], payload[32:64], payload[64:]


def with_pay_ref(address: str, pay_ref: bytes) -> str:
    """The same keys with a pay-ref embedded (an invoice address, spec §5.7)."""
    if not 0 < len(pay_ref) <= MAX_PAY_REF:
        raise ValueError("pay_ref must be 1..64 bytes")
    owner, view, _ = parse_testnet(address)
    return encode(TESTNET_HRP, owner + view + pay_ref)


def base_address(address: str) -> str:
    """The address without any pay-ref, in canonical lowercase."""
    owner, view, _ = parse_testnet(address)
    return encode(TESTNET_HRP, owner + view)


def classify(text: str) -> str:
    """classifyAddressInput (spec §4.9.4): ootle_testnet | ootle_other | l1_emoji | l1_base58 | invalid."""
    if not isinstance(text, str):
        return "invalid"
    s = text.strip()
    if not s or len(s) > 1000:
        return "invalid"
    if s.lower().startswith("otl_"):
        if s.lower().startswith(TESTNET_HRP + "1"):
            try:
                parse_testnet(s)
                return "ootle_testnet"
            except ValueError:
                return "invalid"
        return "ootle_other"
    emoji = [c for c in s if c not in _IGNORED_IN_EMOJI]
    if len(emoji) >= 20 and all(c in _EMOJI_SET for c in emoji):
        return "l1_emoji"
    if _BASE58.match(s):
        return "l1_base58"
    return "invalid"
