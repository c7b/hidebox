#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Writes merkle-rfc9162.json: Merkle tree heads and inclusion proofs computed with an independent
Python implementation of RFC 9162 §2.1 (stdlib only), for the browser's SealLog verifier tests.

  python3 -I web/app/tests/vectors/merkle_vectors.py
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def h(b):
    return hashlib.sha256(b).digest()


def mth(leaves):
    """MTH(D[n]) over leaf hashes (RFC 9162 §2.1.1, with leaf hashing already applied)."""
    n = len(leaves)
    if n == 0:
        return h(b"")
    if n == 1:
        return leaves[0]
    k = 1 << ((n - 1).bit_length() - 1)
    return h(b"\x01" + mth(leaves[:k]) + mth(leaves[k:]))


def path(m, leaves):
    """PATH(m, D[n]) (RFC 9162 §2.1.3.1)."""
    n = len(leaves)
    if n == 1:
        return []
    k = 1 << ((n - 1).bit_length() - 1)
    if m < k:
        return path(m, leaves[:k]) + [mth(leaves[k:])]
    return path(m - k, leaves[k:]) + [mth(leaves[:k])]


def main():
    all_leaves = [h(b"\x00" + f"leaf {i}".encode()) for i in range(70)]
    cases = []
    for n in list(range(1, 18)) + [64, 65, 70]:
        leaves = all_leaves[:n]
        root = mth(leaves).hex()
        for m in sorted({0, n // 2, n - 1, min(5, n - 1)}):
            cases.append({"tree_size": n, "index": m, "leaf": leaves[m].hex(), "path": [p.hex() for p in path(m, leaves)], "root": root})
    out = {"_about": "RFC 9162 inclusion proofs from an independent Python implementation (merkle_vectors.py).",
           "empty_root": mth([]).hex(), "cases": cases}
    with open(os.path.join(HERE, "merkle-rfc9162.json"), "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"{len(cases)} inclusion proofs")


if __name__ == "__main__":
    main()
