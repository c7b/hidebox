#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independent re-computation of the frozen vectors with Python's stdlib (no shared code with the JS).

  python3 -I web/app/tests/vectors/crosscheck.py

Checks every HKDF row, the mod-ℓ reductions, Padmé, the header, verifiers, link fragments, the stored
file's chunk hashes and ct_hash, identity id, auth verifier, recovery code, safety code, key-file text,
bech32m addresses, PoW cases and the ZIP of Download all (zipfile). AES-GCM and ristretto255 aren't in the stdlib; the JS KATs cover them.
"""
import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ELL = 2**252 + 27742317777372353535851937790883648493
EMOJI_TABLE_SHA256 = "993865fde3ad66a36b51811eca899c55f7d8ebd4070352f5d34d4a38627f2c1f"  # tari v6.1.0 emoji.rs
failures = []
checked = []


def check(name, ok):
    checked.append(name)
    if not ok:
        failures.append(name)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hkdf(ikm, salt, info, length):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def padme(n):
    if n <= 1024:
        return 1024
    e = n.bit_length() - 1
    s = e.bit_length()
    step = 1 << (e - s)
    return -(-n // step) * step


def crockford(data):
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    bits = "".join(f"{b:08b}" for b in data)
    bits += "0" * (-len(bits) % 5)
    return "".join(alphabet[int(bits[i:i + 5], 2)] for i in range(0, len(bits), 5))


def bech32m_decode(addr):
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    pos = addr.rfind("1")
    hrp, data = addr[:pos], [charset.index(c) for c in addr[pos + 1:]]
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + data:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    assert chk == 0x2bc830a3, "checksum"
    acc = bits = 0
    out = bytearray()
    for v in data[:-6]:
        acc = (acc << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 255)
    return hrp, bytes(out)


def main():
    f = json.load(open(os.path.join(HERE, "format-v1.json"), encoding="utf-8"))
    w = json.load(open(os.path.join(HERE, "wrap-v2.json"), encoding="utf-8"))
    inp = f["inputs"]
    named = {"fk": bytes.fromhex(inp["fk"]), "s": bytes.fromhex(inp["s"]), "s0": bytes.fromhex(inp["s0"]),
             "seed": bytes.fromhex(inp["seed"]), "P": bytes.fromhex(inp["P"])}
    named["s0 ‖ P"] = named["s0"] + named["P"]
    salts = {"header_salt": bytes.fromhex(inp["header_salt"]), "mutis/v1": b"mutis/v1"}

    p = hashlib.pbkdf2_hmac("sha256", inp["password"].encode(), unb64u(inp["kdf"]["salt"]), inp["kdf"]["iter"], 32)
    check("PBKDF2 P", p == named["P"])
    for row in f["hkdf"]:
        out = hkdf(named[row["ikm"]], salts[row["salt"]], row["info"].encode(), row["length"])
        check(f"HKDF {row['name']}", out.hex() == row["out"])
    for sc in f["scalars_mod_l"]:
        n = int.from_bytes(bytes.fromhex(sc["hkdf64"]), "little") % ELL
        check(f"mod ℓ {sc['info']}", n.to_bytes(32, "little").hex() == sc["reduced"])
    for n, lp in f["padme"]:
        check(f"padme {n}", padme(n) == lp)

    h = f["header"]
    hdr = b"MTS1" + bytes([1, 22, 0, 0]) + h["chunk_count"].to_bytes(4, "big") + bytes(4) + bytes.fromhex(h["salt"])
    check("header bytes", hdr.hex() == h["bytes"])
    check("header sha256", hashlib.sha256(hdr).hexdigest() == h["sha256"])

    v = f["verifiers"]
    access = hkdf(named["s"], b"mutis/v1", b"share-access", 32)
    proof = hkdf(named["s0"], b"mutis/v1", b"link-proof", 32)
    check("access token", b64u(access) == v["access_token_b64u"])
    check("access verifier", b64u(hashlib.sha256(access).digest()) == v["access_verifier_b64u"])
    check("link verifier", b64u(hashlib.sha256(proof).digest()) == v["link_verifier_b64u"])
    for fr in f["fragments"]:
        check(f"fragment {fr['kind']}", fr["fragment"] == str(fr["kind"]) + b64u(bytes.fromhex(fr["secret"])) and len(fr["fragment"]) == 44)

    fl = f["file"]
    ct = unb64u(fl["ciphertext_b64u"])
    n = fl["chunk_count"]
    check("file size_stored", len(ct) == fl["size_stored"] == padme(5000) + 16 * n)
    hashes = [hashlib.sha256(ct[i * (4194304 + 16):(i + 1) * (4194304 + 16)]).digest() for i in range(n)]
    check("chunk hashes", [b64u(x) for x in hashes] == fl["chunk_sha256_b64u"])
    check("ct_hash", b64u(hashlib.sha256(b"".join(hashes)).digest()) == fl["ct_hash_b64u"])
    check("meta_ct length", (len(unb64u(fl["meta_ct_b64u"])) - 28) % 256 == 0)
    check("wrapped key length", len(unb64u(fl["wrapped_key_b64u"])) == 60)

    ident = f["identity"]
    seed = named["seed"]
    check("identity id", b64u(hkdf(seed, b"mutis/v1", b"identity-id", 16)) == ident["identity_id_b64u"])
    check("auth verifier", b64u(hashlib.sha256(hkdf(seed, b"mutis/v1", b"auth", 32)).digest()) == ident["auth_verifier_b64u"])
    code = crockford(seed + hashlib.sha256(b"mutis-recovery-v1" + seed).digest()[:2])
    check("recovery code", ident["recovery_code"] == "MUTIS-" + "-".join(code[i:i + 5] for i in range(0, 55, 5)))

    src = open(os.path.join(HERE, "..", "..", "lib", "emoji.js"), encoding="utf-8").read()
    alphabet = src[src.index("Object.freeze(`") + 15:src.index("`.trim()")].split()
    check("emoji table = tari v6.1.0", len(alphabet) == 256 and hashlib.sha256("".join(alphabet).encode()).hexdigest() == EMOJI_TABLE_SHA256)
    hrp, payload = bech32m_decode(ident["locker_address"])
    check("locker address hrp", hrp == "otl_esm_" and len(payload) == 64)
    check("locker address keys", payload.hex() == w["locker"]["owner_pk"] + w["locker"]["view_pk"])
    sh = hashlib.sha256(b"mutis-safety-v1" + payload[:32] + payload[32:64]).digest()[:12]
    check("safety code emoji", [alphabet[b] for b in sh] == ident["safety_code"]["emoji"])
    check("safety code hex", " ".join(re.findall("....", sh.hex())) == ident["safety_code"]["hex"])
    e = ident["safety_code"]["emoji"]
    expected_file = "\n".join([
        "mutis locker key. Keep it private: anyone with this file can open your locker.",
        f"Safety code: {''.join(e[:4])} {''.join(e[4:8])} {''.join(e[8:])}",
        f"Tari address (Esmeralda testnet): {ident['locker_address']}",
        f"Created: {ident['created']}",
        f"Key: {ident['recovery_code']}", ""])
    check("key file text", expected_file == ident["key_file_text"])
    check("key file name", ident["key_file_name"] == f"mutis-key-{sh[:3].hex()}.txt")

    for case in f["pow"]:
        d = hashlib.sha256(unb64u(case["challenge"]) + unb64u(case["nonce"])).digest()
        lz = 256 - int.from_bytes(d, "big").bit_length()
        check(f"pow d={case['difficulty']} lz", lz == case["leading_zero_bits"])
        check(f"pow d={case['difficulty']} verdict", (lz >= case["difficulty"]) == case["valid"])

    inner = bytes.fromhex(w["inner"]["bytes"])
    check("inner layout", len(inner) == 65 and inner[16:48].hex() == w["inner"]["s"] and inner[48] == 1)
    for kind in ("kind3", "kind4"):
        blob = bytes.fromhex(w[kind]["blob"])
        check(f"{kind} blob length", len(blob) == 125)
        for origin, memo in w[kind]["memos"].items():
            check(f"{kind} memo {origin}", memo == f"{origin}/t#{kind[-1]}{b64u(blob)}" and len(memo.encode()) <= 253)
    check("memo bytes mutis.sh", w["memo_bytes"]["https://mutis.sh"] == 187)

    # lane app2: Download all's ZIP (lib/zip.js), opened by Python's zipfile, CRC-32 by binascii.
    z = json.load(open(os.path.join(HERE, "zip-v1.json"), encoding="utf-8"))
    for text, want in z["crc32"]:
        check(f"crc32 {text[:12]!r}", f"{binascii.crc32(text.encode()):08x}" == want)
    raw = base64.b64decode(z["archive_b64"])
    check("zip sha256", hashlib.sha256(raw).hexdigest() == z["sha256"])
    with zipfile.ZipFile(io.BytesIO(raw)) as arc:
        infos = arc.infolist()
        check("zip testzip (every CRC)", arc.testzip() is None)
        check("zip names in order", [i.filename for i in infos] == z["names"])
        check("zip stored, UTF-8 names", all(i.compress_type == zipfile.ZIP_STORED and i.flag_bits & 0x800 for i in infos))
        check("zip dates", all(i.date_time == (2026, 10, 13, 12, 0, 0) for i in infos))
        check("zip folders", sorted(i.filename for i in infos if i.is_dir()) == z["dirs"])
        check("zip files", all(arc.read(n) == body.encode() for n, body in z["files"].items()))
        check("zip bytes file", arc.read(z["seq_file"]) == bytes((i * 7) & 255 for i in range(300)))
        check("zip paths stay inside", all(not i.filename.startswith("/") and ".." not in i.filename.split("/") for i in infos))

    print(f"crosscheck: {len(checked) - len(failures)}/{len(checked)} checks passed")
    for name in failures:
        print("FAIL", name)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
