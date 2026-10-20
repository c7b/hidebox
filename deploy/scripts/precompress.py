#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Precompressed copies of a built tree's text files, for Caddy's `file_server { precompressed br gzip }`.

  python3 -I deploy/scripts/precompress.py DIST

Beside every file of a compressible type (TYPES) of at least 512 B it writes NAME.gz (gzip -9 from Python's zlib, no
file name, mtime 0, so the same bytes give the same file) and, when `node` is on the PATH, NAME.br (Brotli at quality
11 from Node's built-in zlib, no package; each one decoded again and compared before it is kept). Each only when it is
smaller than the file and only where it is missing, so a second run adds just what the first couldn't: tools/build.py
runs it on the workstation, and activate-release.sh again on the server, which has Node (provision.sh), so a build made
without Node still gets its .br files. Identical files (a fingerprinted copy and its plain name) are compressed once.

Caddy answers a browser that accepts br or gzip with the sidecar, Content-Encoding set and Vary: Accept-Encoding, and
anything else with the file; the sidecars are never in the hash manifest (they are written after it), and
tools/verify-deploy.py checks that what each encoding decodes to is the file. Python standard library only.
"""
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TYPES = {".html", ".css", ".js", ".mjs", ".svg", ".json", ".webmanifest", ".txt", ".xml", ".wasm"}
MIN_SIZE = 512          # Caddy's own `encode` leaves smaller answers alone too
SIDECARS = (".gz", ".br")
BROTLI = r"""
const fs = require('fs'), zlib = require('zlib');
const jobs = JSON.parse(fs.readFileSync(0, 'utf8')), written = [];
for (const [src, dst, text] of jobs) {
  const data = fs.readFileSync(src);
  const br = zlib.brotliCompressSync(data, { params: {
    [zlib.constants.BROTLI_PARAM_QUALITY]: 11,
    [zlib.constants.BROTLI_PARAM_MODE]: text ? zlib.constants.BROTLI_MODE_TEXT : zlib.constants.BROTLI_MODE_GENERIC,
    [zlib.constants.BROTLI_PARAM_SIZE_HINT]: data.length } });
  if (!zlib.brotliDecompressSync(br).equals(data)) throw new Error('brotli round trip failed: ' + src);
  if (br.length < data.length) { fs.writeFileSync(dst, br); written.push(dst); }
}
process.stdout.write(JSON.stringify({ written, brotli: process.versions.brotli || '', node: process.version }));
"""


def compressible(path: Path) -> bool:
    return path.suffix in TYPES and path.stat().st_size >= MIN_SIZE


def groups(dist: Path) -> list[list[Path]]:
    """The compressible files, identical contents together, in a stable order."""
    by_hash: dict[str, list[Path]] = {}
    for path in sorted(p for p in dist.rglob("*") if p.is_file() and p.suffix not in SIDECARS):
        if compressible(path):
            by_hash.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), []).append(path)
    return list(by_hash.values())


def sidecar(path: Path, ext: str) -> Path:
    return path.with_name(path.name + ext)


def precompress(dist: Path, node: str | None = None) -> dict:
    """Write the missing sidecars under `dist`; returns counts and the Brotli encoder used ("" for none)."""
    node = node if node is not None else (shutil.which("node") or "")
    summary = {"files": 0, "gzip": 0, "br": 0, "brotli": ""}
    todo = groups(dist)
    for paths in todo:
        summary["files"] += len(paths)
        missing = [p for p in paths if not sidecar(p, ".gz").exists()]
        if missing:
            data = paths[0].read_bytes()
            packed = gzip.compress(data, compresslevel=9, mtime=0)
            if len(packed) < len(data):
                for p in missing:
                    sidecar(p, ".gz").write_bytes(packed)
                    summary["gzip"] += 1
    jobs = [(paths, [p for p in paths if not sidecar(p, ".br").exists()]) for paths in todo]
    jobs = [(paths, missing) for paths, missing in jobs if missing]
    if not node:
        return summary
    if not jobs:
        summary["brotli"] = "node: every .br was there"
        return summary
    with tempfile.TemporaryDirectory(prefix="mutis-br-") as tmp:
        work = [[str(paths[0]), str(Path(tmp) / f"{i}.br"), paths[0].suffix != ".wasm"] for i, (paths, _) in enumerate(jobs)]
        run = subprocess.run([node, "-e", BROTLI], input=json.dumps(work), capture_output=True, text=True, timeout=600)
        if run.returncode != 0:
            raise RuntimeError(f"node could not make the .br files: {run.stderr.strip()[-400:]}")
        result = json.loads(run.stdout)
        summary["brotli"] = f"node {result['node']}" + (f", brotli {result['brotli']}" if result["brotli"] else "")
        done = set(result["written"])
        for (paths, missing), (_, dst, _) in zip(jobs, work):
            if dst in done:
                packed = Path(dst).read_bytes()
                for p in missing:
                    sidecar(p, ".br").write_bytes(packed)
                    summary["br"] += 1
    return summary


def main() -> int:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print("usage: precompress.py DIST", file=sys.stderr)
        return 2
    summary = precompress(Path(sys.argv[1]))
    brotli = summary["brotli"] or "no node on the PATH: gzip only"
    print(f"precompress: {summary['files']} files, {summary['gzip']} .gz and {summary['br']} .br written ({brotli})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
