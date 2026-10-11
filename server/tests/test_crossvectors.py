# SPDX-License-Identifier: MIT
"""Cross-check with the app builder's vectors (spec §3.4.8): the server recomputes everything in
web/app/tests/vectors/format-v1.json that needs no AES or ristretto, and its SealLog tree must produce
exactly the paths of merkle-rfc9162.json (the browser verifier's vectors)."""
import hashlib
import json
import unicodedata
import unittest
from pathlib import Path

import harness  # noqa: F401  (puts server/ on sys.path)
from mutis import codec, ootle_addr, pow, quota, seallog
from mutis.handlers.uploads import META_LENGTHS

APP_VECTORS = Path(__file__).resolve().parents[2] / "web" / "app" / "tests" / "vectors"
L = 2 ** 252 + 27742317777372353535851937790883648493
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def load(name: str) -> dict:
    path = APP_VECTORS / name
    if not path.exists():
        raise unittest.SkipTest(f"{path} not present (copy web/app/tests/vectors next to server/)")
    return json.loads(path.read_text(encoding="utf-8"))


def crockford(data: bytes) -> str:
    bits = int.from_bytes(data, "big")
    n = -(-len(data) * 8 // 5)
    bits <<= n * 5 - len(data) * 8
    return "".join(CROCKFORD[(bits >> (5 * (n - 1 - i))) & 31] for i in range(n))


class FormatV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = load("format-v1.json")
        i = cls.v["inputs"]
        cls.inputs = {k: bytes.fromhex(i[k]) for k in ("seed", "s", "s0", "fk", "header_salt", "P")}

    def ikm(self, name: str) -> bytes:
        if name == "s0 ‖ P":
            return self.inputs["s0"] + self.inputs["P"]
        return self.inputs[name]

    def test_hkdf_table(self):
        for row in self.v["hkdf"]:
            salt = self.inputs["header_salt"] if row["salt"] == "header_salt" else row["salt"].encode()
            out = codec.hkdf(self.ikm(row["ikm"]), salt, row["info"].encode(), row["length"])
            self.assertEqual(out.hex(), row["out"], row["name"])

    def test_scalar_reduction(self):
        for row in self.v["scalars_mod_l"]:
            reduced = (int.from_bytes(bytes.fromhex(row["hkdf64"]), "little") % L).to_bytes(32, "little")
            self.assertEqual(reduced.hex(), row["reduced"], row["info"])

    def test_pbkdf2_password(self):
        kdf = self.v["inputs"]["kdf"]
        password = unicodedata.normalize("NFC", self.v["inputs"]["password"]).encode()
        out = hashlib.pbkdf2_hmac("sha256", password, codec.unb64u(kdf["salt"]), kdf["iter"], 32)
        self.assertEqual(out, self.inputs["P"])

    def test_padme_header_and_layout(self):
        for length, padded in self.v["padme"]:
            self.assertEqual(quota.padme(length), padded)
        h = self.v["header"]
        header = bytes.fromhex(h["bytes"])
        self.assertEqual(header[:16], b"MTS1\x01\x16\x00\x00" + h["chunk_count"].to_bytes(4, "big") + bytes(4))
        self.assertEqual(hashlib.sha256(header).hexdigest(), h["sha256"])
        f = self.v["file"]
        self.assertTrue(quota.valid_layout(f["size_stored"], f["chunk_count"]))
        self.assertEqual(quota.stored_size(quota.padme(f["meta"]["size"])), f["size_stored"])
        ciphertext = codec.unb64u(f["ciphertext_b64u"])
        self.assertEqual(len(ciphertext), f["size_stored"])
        hashes = [codec.unb64u(x) for x in f["chunk_sha256_b64u"]]
        self.assertEqual(hashes, [hashlib.sha256(ciphertext).digest()])
        self.assertEqual(codec.b64u(codec.sha256(*hashes)), f["ct_hash_b64u"])
        self.assertIn(len(codec.unb64u(f["meta_ct_b64u"])), META_LENGTHS)
        self.assertEqual(len(codec.unb64u(f["wrapped_key_b64u"])), 60)

    def test_verifiers(self):
        v = self.v["verifiers"]
        access = codec.hkdf(self.inputs["s"], b"mutis/v1", b"share-access", 32)
        proof = codec.hkdf(self.inputs["s0"], b"mutis/v1", b"link-proof", 32)
        self.assertEqual((codec.b64u(access), codec.b64u(codec.sha256(access))),
                         (v["access_token_b64u"], v["access_verifier_b64u"]))
        self.assertEqual((codec.b64u(proof), codec.b64u(codec.sha256(proof))),
                         (v["link_proof_b64u"], v["link_verifier_b64u"]))

    def test_identity_as_the_server_sees_it(self):
        i = self.v["identity"]
        seed = bytes.fromhex(i["seed"])
        self.assertEqual(codec.b64u(codec.hkdf(seed, b"mutis/v1", b"identity-id", 16)), i["identity_id_b64u"])
        auth_key = codec.hkdf(seed, b"mutis/v1", b"auth", 32)
        self.assertEqual(codec.b64u(codec.sha256(auth_key)), i["auth_verifier_b64u"])
        code = crockford(seed + codec.sha256(b"mutis-recovery-v1", seed)[:2])
        self.assertEqual("MUTIS-" + "-".join(code[k:k + 5] for k in range(0, 55, 5)), i["recovery_code"])
        for address in (i["locker_address"], i["wallet_address"]):
            self.assertEqual(ootle_addr.classify(address), "ootle_testnet")

    def test_pow_cases(self):
        for case in self.v["pow"]:
            challenge, nonce = codec.unb64u(case["challenge"]), codec.unb64u(case["nonce"])
            self.assertEqual(len(challenge), pow.CHALLENGE_LEN)
            self.assertEqual(pow.leading_zero_bits(hashlib.sha256(challenge + nonce).digest()),
                             case["leading_zero_bits"])
            self.assertEqual(pow.solved(challenge, nonce, case["difficulty"]), case["valid"])
            self.assertEqual(challenge[2], case["difficulty"])        # the difficulty byte sits at offset 2


class Merkle(unittest.TestCase):
    def test_same_paths_as_the_browser_vectors(self):
        v = load("merkle-rfc9162.json")
        leaves = [hashlib.sha256(b"\x00" + f"leaf {i}".encode()).digest() for i in range(70)]
        self.assertEqual(seallog.root([]).hex(), v["empty_root"])
        for case in v["cases"]:
            tree = leaves[:case["tree_size"]]
            self.assertEqual(seallog.root(tree).hex(), case["root"])
            path = seallog.inclusion_proof(seallog.levels(tree), case["index"])
            self.assertEqual([p.hex() for p in path], case["path"])
            self.assertTrue(seallog.verify_inclusion(bytes.fromhex(case["leaf"]), case["index"], case["tree_size"],
                                                     [bytes.fromhex(p) for p in case["path"]],
                                                     bytes.fromhex(case["root"])))


if __name__ == "__main__":
    unittest.main()
