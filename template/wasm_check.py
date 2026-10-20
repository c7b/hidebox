#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stdlib checks of an Ootle template binary.

  abi <wasm>                  print the sha256 of the ABI (the `tari_tdef` custom section)
  address <author> <wasm>     print the template address that publishing <wasm> signed by
                              <author> (hex public key) creates
  onchain <template address>  fetch the template from an indexer, check the address commits to
                              the bytes it returned, and compare them with dist/seal_log.wasm

`abi` and `onchain` fail if a binary carries a custom section other than `tari_tdef`, which the
engine rejects at publish. `onchain` exits 0 only when the chain holds exactly the --wasm bytes,
and 1 on any failure, the indexer being unreachable included.

Usage: python3 -I wasm_check.py <command> ...
"""

import argparse
import hashlib
import json
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

ABI_SECTION = b"tari_tdef"
DIST = Path(__file__).resolve().parent / "dist" / "seal_log.wasm"
INDEXER = "https://ootle-indexer-a.tari.com"
# tari_engine_types 0.45 hashing.rs: a DomainSeparatedBorshHasher over BLAKE2b-256 with the
# "com.tari.ootle.engine" domain, version 0, label "Template".
TEMPLATE_LABEL = b"com.tari.ootle.engine.v0.Template"


def uleb128(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, pos


def custom_sections(module: bytes):
    if module[:8] != b"\0asm\x01\0\0\0":
        raise ValueError("not a WASM 1.0 module")
    pos = 8
    while pos < len(module):
        section_id = module[pos]
        size, start = uleb128(module, pos + 1)
        if section_id == 0:
            name_len, name_start = uleb128(module, start)
            name_end = name_start + name_len
            yield module[name_start:name_end], module[name_end:start + size]
        pos = start + size


def abi_hash(module: bytes) -> str:
    """sha256 of the `tari_tdef` payload. Raises ValueError for a module the engine would reject."""
    sections = dict(custom_sections(module))
    if ABI_SECTION not in sections:
        raise ValueError("no tari_tdef section: not a template")
    extra = sorted(name.decode() for name in sections if name != ABI_SECTION)
    if extra:
        raise ValueError(f"unexpected custom sections: {', '.join(extra)}")
    return hashlib.sha256(sections[ABI_SECTION]).hexdigest()


def template_hash(*borsh_fields: bytes) -> bytes:
    digest = hashlib.blake2b(digest_size=32)
    digest.update(struct.pack("<Q", len(TEMPLATE_LABEL)) + TEMPLATE_LABEL)
    for field in borsh_fields:
        digest.update(field)
    return digest.digest()


def template_address(author_hex: str, binary: bytes) -> str:
    """PublishedTemplateAddress::from_author_and_binary_hash (published_template.rs). Borsh
    encodes the binary and the author key as u32-length-prefixed byte strings."""
    author = bytes.fromhex(author_hex)
    binary_hash = template_hash(struct.pack("<I", len(binary)) + binary)
    return template_hash(struct.pack("<I", len(author)) + author, binary_hash).hex()


def describe(module: bytes) -> str:
    return f"{len(module)} bytes, sha256 {hashlib.sha256(module).hexdigest()}"


def substate_value(body) -> dict | None:
    """The substate value of a GET /substates answer: `state.up.substate` (tari_indexer 0.47.0) or `substate`
    (earlier indexers); None for anything else, a spent version (`state.down`) included."""
    if not isinstance(body, dict):
        return None
    if "state" in body:
        up = body["state"].get("up") if isinstance(body["state"], dict) else None
        value = up.get("substate") if isinstance(up, dict) else None
    else:
        value = body.get("substate")
    return value if isinstance(value, dict) else None


def onchain(address: str, indexer: str, wasm: Path, out: Path | None) -> int:
    address = address.removeprefix("template_")
    url = f"{indexer.rstrip('/')}/substates/template_{address}"
    # The public indexers refuse urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "mutis-wasm-check/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.load(response)
    template = (substate_value(body) or {}).get("Template")
    if not isinstance(template, dict):
        print(f"FAIL: the indexer holds no live template at template_{address}")
        return 1
    binary = bytes.fromhex(template["binary"])
    print(f"template_{address}: {template['template_name']}, author {template['author']}, "
          f"epoch {template['at_epoch']}, indexer verified: {body.get('verified')}")
    print(f"on chain   {describe(binary)}")
    if out:
        out.write_bytes(binary)
        print(f"wrote {out}")
    if template_address(template["author"], binary) != address:
        print("FAIL: the address does not commit to the bytes the indexer returned")
        return 1
    print("the address commits to these bytes")
    local = wasm.read_bytes()
    print(f"{wasm.name:<10} {describe(local)}")
    same_abi = abi_hash(binary) == abi_hash(local)
    print(f"ABI (tari_tdef): {'equal' if same_abi else 'DIFFERENT'}")
    if binary == local:
        print(f"the chain runs {wasm.name} byte for byte")
        return 0
    print(f"FAIL: the chain runs different bytes from {wasm.name}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    abi = commands.add_parser("abi", help="print the ABI hash")
    abi.add_argument("wasm", type=Path)
    addr = commands.add_parser("address", help="print the template address a publish creates")
    addr.add_argument("author", help="the publishing key, 64 hex characters")
    addr.add_argument("wasm", type=Path)
    chain = commands.add_parser("onchain", help="compare a published template with a local binary")
    chain.add_argument("address", help="template_<hex> or <hex>")
    chain.add_argument("--indexer", default=INDEXER)
    chain.add_argument("--wasm", type=Path, default=DIST)
    chain.add_argument("--out", type=Path, help="also save the on-chain binary here")
    args = parser.parse_args()
    try:
        if args.command == "abi":
            print(abi_hash(args.wasm.read_bytes()))
            return 0
        if args.command == "address":
            print(template_address(args.author, args.wasm.read_bytes()))
            return 0
        return onchain(args.address, args.indexer, args.wasm, args.out)
    except (ValueError, urllib.error.URLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
