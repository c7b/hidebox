#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write seallog-v1.json: Merkle vectors for everything that builds or checks a SealLog root.

The tree is the RFC 9162 §2.1 Merkle Tree Hash over SHA-256. Leaf formats:
  stored  "mutis-leaf-v1" || item_id(16) || ct_hash(32)          (10-spec §4.4.4)
  exit    "mutis-exit-v1" || item_id(16) || u32be(unix // 3600)  (11-brand §16 P-8)
  pad     "mutis-pad-v1"  || 32 random bytes                     (10-spec §11.3)
Each checkpoint pads the tree to the next multiple of 64 above its size, so it always adds at
least one pad and the count moves by 64 even in a window with no new records. Pads stay in the
tree, so every checkpoint's tree is a prefix of the next one. SealLog enforces the result: every
leaf_count is a multiple of 64 and larger than the last.

The story in the vector: one file is stored (leaf 0, checkpoint 64), later it leaves (exit
leaf 64, checkpoint 128), then a window passes with nothing new (checkpoint 192). Vector inputs
are derived from fixed labels so the file is reproducible; production pads use 32 bytes from a
CSPRNG. Item ids appear as hex and as the API's unpadded base64url; exit hours as the leaf's
hour index and as the API's `exit_hour` (unix seconds at the start of that hour).

Usage: python3 -I gen.py          rewrite seallog-v1.json next to this file
       python3 -I gen.py --check  exit 1 if the committed file differs from a fresh run
"""

import argparse
import base64
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).with_name("seallog-v1.json")
PAD_STEP = 64
STORED_TAG, EXIT_TAG, PAD_TAG = b"mutis-leaf-v1", b"mutis-exit-v1", b"mutis-pad-v1"

# RFC 6962 reference vectors (certificate-transparency test data): leaves and the root of
# every prefix of length 1..8. RFC 9162 keeps the same tree hash.
KAT_LEAVES = ["", "00", "10", "2021", "3031", "40414243", "5051525354555657",
              "606162636465666768696a6b6c6d6e6f"]
KAT_ROOTS = [
    "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
    "aeb6bcfe274b70a14fb067a5e5578264db0fa9b51af5e0ba159158f329e06e77",
    "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    "4e3bbb1f7b478dcfe71fb631631519a3bca12c9aefca1612bfce4c13a86264d4",
    "76e67dadbcdf1e10e1b74ddc608abd2f98dfb16fbce75277b5232a127f2087ef",
    "ddb89be403809e325750d3d263cd78929c2942b7942a34b77e122c9594a74c8c",
    "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328",
]


def sha256(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def leaf_hash(data: bytes) -> bytes:
    return sha256(b"\x00", data)


def node_hash(left: bytes, right: bytes) -> bytes:
    return sha256(b"\x01", left, right)


def split(n: int) -> int:
    """The largest power of two smaller than n (n > 1)."""
    return 1 << ((n - 1).bit_length() - 1)


def root(hashes: list[bytes]) -> bytes:
    n = len(hashes)
    if n == 0:
        return sha256()
    if n == 1:
        return hashes[0]
    k = split(n)
    return node_hash(root(hashes[:k]), root(hashes[k:]))


def inclusion_path(m: int, hashes: list[bytes]) -> list[bytes]:
    """RFC 9162 §2.1.3.1 PATH(m, D[n]), leaf to root."""
    n = len(hashes)
    if n <= 1:
        return []
    k = split(n)
    if m < k:
        return inclusion_path(m, hashes[:k]) + [root(hashes[k:])]
    return inclusion_path(m - k, hashes[k:]) + [root(hashes[:k])]


def verify_inclusion(index: int, size: int, leaf: bytes, path: list[bytes], expected: bytes) -> bool:
    """RFC 9162 §2.1.3.2, written independently of inclusion_path."""
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            while not fn & 1 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == expected


def padded(size: int) -> int:
    """The next multiple of PAD_STEP above size (10-spec §11.3): always at least one pad."""
    return (size // PAD_STEP + 1) * PAD_STEP


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def stored_leaf(item_id: bytes, ct_hash: bytes) -> dict:
    return {"kind": "stored", "item_id": item_id.hex(), "item_id_b64u": b64u(item_id),
            "ct_hash": ct_hash.hex(), "leaf_data": (STORED_TAG + item_id + ct_hash).hex()}


def exit_leaf(item_id: bytes, exit_unix: int) -> dict:
    hour = exit_unix // 3600
    return {"kind": "exit", "item_id": item_id.hex(), "item_id_b64u": b64u(item_id),
            "exit_unix": exit_unix, "exit_hour_unix": hour * 3600, "exit_hour_index": hour,
            "leaf_data": (EXIT_TAG + item_id + hour.to_bytes(4, "big")).hex()}


def pad_leaf(index: int) -> dict:
    random = sha256(b"seallog-v1 vector pad", index.to_bytes(4, "big"))
    return {"kind": "pad", "random": random.hex(), "leaf_data": (PAD_TAG + random).hex()}


def checkpoint(leaves: list[dict], new_records: list[dict]) -> int:
    """Add one window's records and its pads; return the new tree size."""
    leaves.extend(new_records)
    size = padded(len(leaves))
    while len(leaves) < size:
        leaves.append(pad_leaf(len(leaves)))
    return size


def build() -> dict:
    item_id = sha256(b"seallog-v1 vector item")[:16]
    ct_hash = sha256(b"seallog-v1 vector ciphertext hash")
    exit_unix = int(datetime(2026, 10, 31, 7, 20, 34, tzinfo=UTC).timestamp())

    leaves: list[dict] = []
    windows = [[stored_leaf(item_id, ct_hash)], [exit_leaf(item_id, exit_unix)], []]
    sizes = [(checkpoint(leaves, records), len(records)) for records in windows]
    exit_index = sizes[0][0]
    leaves = [{"index": i, **leaf, "leaf_hash": leaf_hash(bytes.fromhex(leaf["leaf_data"])).hex()}
              for i, leaf in enumerate(leaves)]
    hashes = [bytes.fromhex(leaf["leaf_hash"]) for leaf in leaves]

    checkpoints = []
    for size, new_records in sizes:
        proven = [i for i in (0, exit_index) if i < size]
        tree = hashes[:size]
        tree_root = root(tree)
        proofs = []
        for index in proven:
            path = inclusion_path(index, tree)
            require(verify_inclusion(index, size, tree[index], path, tree_root), f"proof of leaf {index}")
            proofs.append({"leaf_index": index, "path": [p.hex() for p in path]})
        checkpoints.append({"tree_size": size, "new_records": new_records, "root": tree_root.hex(),
                            "proofs": proofs})

    return {
        "about": "SealLog Merkle vectors, generated by template/seal_log/tests/vectors/gen.py. Do not edit.",
        "tree": "RFC 9162 section 2.1: leaf = SHA-256(0x00 || leaf_data), node = SHA-256(0x01 || left || right)",
        "pad_step": PAD_STEP,
        "checkpoints": checkpoints,
        "leaves": leaves,
        "rfc6962_kat": {"leaves": KAT_LEAVES, "roots": KAT_ROOTS},
    }


def require(ok: bool, what: str) -> None:
    if not ok:
        raise SystemExit(f"self-check failed: {what}")


def self_check() -> None:
    leaves = [leaf_hash(bytes.fromhex(x)) for x in KAT_LEAVES]
    require(root([]) == sha256(), "empty tree")
    for n, expected in enumerate(KAT_ROOTS, start=1):
        require(root(leaves[:n]).hex() == expected, f"RFC 6962 root of {n} leaves")
        tree = leaves[:n]
        for m in range(n):
            require(verify_inclusion(m, n, tree[m], inclusion_path(m, tree), root(tree)), f"proof {m} of {n}")
    tree = leaves[:7]
    path = inclusion_path(3, tree)
    require(not verify_inclusion(2, 7, tree[3], path, root(tree)), "a proof must not verify at another index")
    require(not verify_inclusion(3, 7, tree[3], path[:-1], root(tree)), "a truncated proof must fail")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed file instead of writing")
    args = parser.parse_args()
    self_check()
    text = json.dumps(build(), indent=1) + "\n"
    if args.check:
        if OUT.read_text() != text:
            print(f"{OUT.name} is stale: run gen.py", file=sys.stderr)
            return 1
        print(f"{OUT.name}: up to date, RFC 6962 vectors and proofs verified")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
