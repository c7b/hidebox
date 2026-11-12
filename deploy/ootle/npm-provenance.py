#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Vendor an official @tari-project npm package as files, never with npm (upgrade-0.50.md §2).

  check  --name @tari-project/ootle-wasm --version <version> --commit <sha> --downloads DIR
         [--out web/app/vendor/ootle-wasm-<version> --file ootle_wasm_bg.wasm … --license LICENSE]
  repin  --from <old version> --to <new version> [--root .]

`check` reads, from DIR, what curl fetched (names as upgrade-0.50.md §2 gives them):
  <pkg>.packument.json         https://registry.npmjs.org/@tari-project%2f<pkg>
  <pkg>-<version>.tgz          the packument's dist.tarball
  <pkg>-<version>.attestations.json   https://registry.npmjs.org/-/npm/v1/attestations/@tari-project%2f<pkg>@<version>
It checks the tarball's sha512 against the registry's dist.integrity, that both attestations (SLSA provenance
v1 and npm publish) name exactly this tarball, and that the provenance says it was built by
github.com/tari-project/tari-ootle at refs/tags/v<version>, commit <sha>. With --out it then copies the named
files out of the tarball's package/ folder (nothing else is read from it) and writes SHA256SUMS. It prints the
facts PROVENANCE.md records. It does not verify the Sigstore signatures (no verifier without a third-party
toolchain; PROVENANCE.md says so), and nothing in the tarball is run.

`repin` moves every pin of the vendored ootle-wasm and ootle-wasm-bor from one version to the next: the folder
names, the four pinned sha256 (from the two folders' SHA256SUMS) and `wasm_version`, in the files listed in
PIN_FILES. Each must change, or it stops; deploy/tests/test_config.py (PinnedWasmTest) and tools/build.py then
check that the copies agree. The prose (NOTICE, PROVENANCE.md, CHANGELOG, READMEs) is left to a person.

Python standard library only. Exit status 1 on any failure.
"""
import argparse
import base64
import binascii
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

REPO = "https://github.com/tari-project/tari-ootle"
SLSA = "https://slsa.dev/provenance/v1"
NPM_PUBLISH = "https://github.com/npm/attestation/tree/main/specs/publish/v0.1"
MAX_FILE = 16 * 1024 * 1024
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
RESERVED = {"SHA256SUMS", "LICENSE", "PROVENANCE.md"}     # files this script or a person writes, never copied
# What repin rewrites; a path here that no longer holds a pin stops it (the list is stale).
PIN_FILES = (
    "tools/build.py", "web/app/vendor/ootle-wasm-shim.js", "web/app/sidecar/loader.mjs", "server/mutis/config.py",
    "deploy/scripts/activate-release.sh", "deploy/scripts/init-keys.sh", "deploy/config/mutis.toml.example",
    "deploy/config/instance.toml.example",
    "deploy/scripts/collect-evidence.py", "deploy/tests/test_build.py", "deploy/tests/test_config.py",
    "server/tests/test_contract.py", "tests/e2e/headers_spec.py", "tests/e2e/test_headers.py",
    "web/app/tests/node-run.mjs", "web/app/tests/make-rows.mjs", "web/app/tests/vectors/generate.mjs",
    "web/app/tests/sidecar_test.py", "web/app/tests/lint_core.py", "web/app/ui/tests/realize.py",
)
PACKAGES = ("ootle-wasm", "ootle-wasm-bor")


class ProvenanceError(Exception):
    pass


def need(cond: bool, message: str) -> None:
    if not cond:
        raise ProvenanceError(message)


def short(name: str) -> str:
    need(re.fullmatch(r"@tari-project/[a-z0-9-]{1,64}", name or "") is not None, f"not a @tari-project package: {name!r}")
    return name.split("/", 1)[1]


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProvenanceError(f"{path.name}: {e}") from None


def statement(attestation: dict) -> dict:
    envelope = attestation.get("bundle", {}).get("dsseEnvelope", {})
    need(envelope.get("payloadType") == "application/vnd.in-toto+json", "an attestation is not an in-toto statement")
    try:
        stmt = json.loads(base64.b64decode(envelope["payload"], validate=True))
    except (KeyError, ValueError) as e:
        raise ProvenanceError(f"an attestation's payload does not decode: {e}") from None
    need(isinstance(stmt, dict), "an attestation's payload is not a statement")
    return stmt


def rekor(attestation: dict) -> list[str]:
    entries = attestation.get("bundle", {}).get("verificationMaterial", {}).get("tlogEntries", [])
    return [str(e.get("logIndex")) for e in entries if isinstance(e, dict) and str(e.get("logIndex", "")).isdigit()]


def check(name: str, version: str, commit: str, downloads: Path) -> tuple[dict, bytes]:
    """(The facts PROVENANCE.md records, the tarball's bytes those facts hold for), once every check holds;
    ProvenanceError otherwise. `extract` reads these bytes, never the file again."""
    pkg = short(name)
    need(VERSION.fullmatch(version or "") is not None, f"not a release version: {version!r}")
    need(re.fullmatch(r"[0-9a-f]{40}", commit or "") is not None, "--commit must be the 40-hex release commit")
    packument = load_json(downloads / f"{pkg}.packument.json")
    need(isinstance(packument, dict) and packument.get("name") == name, "the packument is not this package's")
    meta = packument.get("versions", {}).get(version)
    need(isinstance(meta, dict), f"the registry lists no {name}@{version}")
    dist = meta.get("dist", {})
    tarball = downloads / f"{pkg}-{version}.tgz"
    need(dist.get("tarball") == f"https://registry.npmjs.org/{name}/-/{pkg}-{version}.tgz",
         f"unexpected dist.tarball: {dist.get('tarball')!r}")
    integrity = dist.get("integrity", "")
    need(isinstance(integrity, str) and integrity.startswith("sha512-"), "dist.integrity is not sha512")
    try:
        expected = base64.b64decode(integrity[7:], validate=True)
    except (binascii.Error, ValueError):
        raise ProvenanceError("dist.integrity is not base64") from None
    data = tarball.read_bytes()
    digest = hashlib.sha512(data).digest()
    need(expected == digest, "the tarball's sha512 is not dist.integrity")
    attestations = load_json(downloads / f"{pkg}-{version}.attestations.json")
    items = attestations.get("attestations") if isinstance(attestations, dict) else None
    # Exactly the two the registry publishes, each once: a third, a duplicate or a stray entry is refused, so the
    # verdict never depends on the order of the list.
    need(isinstance(items, list) and len(items) == 2 and all(isinstance(a, dict) for a in items),
         "expected exactly two attestations")
    by_type = {a.get("predicateType"): a for a in items}
    need(set(by_type) == {SLSA, NPM_PUBLISH}, f"expected the SLSA and npm publish attestations, got {sorted(map(str, by_type))}")
    subject = {"name": f"pkg:npm/%40tari-project/{pkg}@{version}", "digest": {"sha512": digest.hex()}}
    statements = {kind: statement(attestation) for kind, attestation in by_type.items()}
    for kind, stmt in statements.items():
        need(stmt.get("predicateType") == kind, f"the {kind} attestation's statement is of another type")   # the label is unsigned
        need(stmt.get("subject") == [subject], f"the {kind} attestation names another subject")
    predicate = statements[SLSA].get("predicate", {})
    build = predicate.get("buildDefinition", {})
    workflow = build.get("externalParameters", {}).get("workflow", {})
    need(workflow.get("repository") == REPO, f"built from {workflow.get('repository')!r}, not {REPO}")
    need(workflow.get("ref") == f"refs/tags/v{version}", f"built from {workflow.get('ref')!r}, not refs/tags/v{version}")
    deps = build.get("resolvedDependencies", [])
    need(isinstance(deps, list) and len(deps) == 1 and isinstance(deps[0], dict), "expected one resolved dependency")
    need(deps[0].get("uri") == f"git+{REPO}@refs/tags/v{version}", f"built from {deps[0].get('uri')!r}")
    need(deps[0].get("digest") == {"gitCommit": commit}, f"built from commit {deps[0].get('digest')!r}, not {commit}")
    need(meta.get("gitHead") == commit, f"the registry's gitHead {meta.get('gitHead')!r} is not {commit}")
    run = predicate.get("runDetails", {}).get("metadata", {}).get("invocationId", "")
    m = re.fullmatch(re.escape(REPO) + r"/actions/runs/(\d+)/attempts/(\d+)", run)
    need(m is not None, f"unexpected invocationId {run!r}")
    return {"package": name, "version": version, "tarball": dist["tarball"], "bytes": len(data),
            "published": packument.get("time", {}).get(version), "latest": packument.get("dist-tags", {}).get("latest"),
            "integrity": integrity, "sha512": digest.hex(), "git_head": meta.get("gitHead"), "commit": commit,
            "workflow": workflow.get("path"), "ref": workflow["ref"], "run": int(m.group(1)), "attempt": int(m.group(2)),
            "rekor": {"provenance": rekor(by_type[SLSA]), "publish": rekor(by_type[NPM_PUBLISH])}}, data


def extract(tarball: bytes, files: list[str], out: Path, license_file: Path | None) -> dict[str, str]:
    """Copy package/<file> for each named file (regular files only) out of the tarball `check` verified (its
    bytes, not the file, which could have changed since) into `out`, then write SHA256SUMS."""
    need(not out.exists() or not any(out.iterdir()), f"{out} is not empty")
    wanted = {f"package/{f}": f for f in files}
    need(all(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", f) and not f.startswith(".") and f not in RESERVED for f in files),
         "a bad file name")
    found = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for member in tar:
            if member.name not in wanted:
                continue
            need(member.isreg() and member.size <= MAX_FILE, f"{member.name} is not a regular file of a sane size")
            need(member.name not in found, f"{member.name} appears twice in the tarball")
            found[member.name] = tar.extractfile(member).read()
    need(set(found) == set(wanted), f"missing from the tarball: {sorted(set(wanted) - set(found))}")
    out.mkdir(parents=True, exist_ok=True)
    sums = {}
    for member, data in found.items():
        (out / wanted[member]).write_bytes(data)
        sums[wanted[member]] = hashlib.sha256(data).hexdigest()
    if license_file is not None:
        data = license_file.read_bytes()
        (out / "LICENSE").write_bytes(data)
        sums["LICENSE"] = hashlib.sha256(data).hexdigest()
    (out / "SHA256SUMS").write_text("".join(f"{sums[n]}  {n}\n" for n in sorted(sums)))
    return sums


def read_sums(folder: Path) -> dict[str, str]:
    sums = {}
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name.strip()] = digest
    return sums


def repin(root: Path, old: str, new: str) -> dict[str, int]:
    """{file: replacements}. Old and new hashes are paired by file name through the two SHA256SUMS. Every file is
    rewritten in memory first, so a stale PIN_FILES stops it before it writes anything."""
    need(VERSION.fullmatch(old or "") is not None and VERSION.fullmatch(new or "") is not None and old != new,
         f"versions must be two different X.Y.Z: {old!r} {new!r}")
    vendor = root / "web" / "app" / "vendor"
    pairs = [(f"{p}-{old}/", f"{p}-{new}/") for p in PACKAGES] + [(f"{p}-{old}\"", f"{p}-{new}\"") for p in PACKAGES]
    for pkg in PACKAGES:
        before, after = read_sums(vendor / f"{pkg}-{old}"), read_sums(vendor / f"{pkg}-{new}")
        for name in ("ootle_wasm_bg.wasm", "ootle_wasm_bg.js", "ootle_wasm_bor_bg.wasm", "ootle_wasm_bor_bg.js"):
            if name in before:
                need(name in after, f"{pkg}-{new}/SHA256SUMS has no {name}")
                pairs.append((before[name], after[name]))     # an unchanged hash is still a pin (of the new file)
    # `wasm_version = "…"`, `"wasm_version": "…"`, `["wasm_version"], "…"`, `get("wasm_version", "…"`
    version_pin = re.compile(r"""(wasm_version["'\]\s=:,]{1,8})""" + re.escape(old) + r"""(?=["'])""")
    counts, texts = {}, {}
    for rel in PIN_FILES:
        with open(root / rel, encoding="utf-8", newline="") as f:
            text = f.read()
        n = 0
        for a, b in pairs:
            n += text.count(a)
            text = text.replace(a, b)
        text, k = version_pin.subn(lambda m: m.group(1) + new, text)
        n += k
        need(n > 0, f"{rel}: holds no pin of {old} (PIN_FILES is stale)")
        texts[rel], counts[rel] = text, n
    for rel, text in texts.items():
        with open(root / rel, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return counts


def markdown(facts: dict, sums: dict[str, str] | None) -> str:
    lines = [f"| Tarball | `{facts['tarball']}` ({facts['bytes']:,} bytes), published {facts['published']}, "
             f"`dist-tags.latest` {facts['latest']} |",
             f"| Registry integrity (`dist.integrity`) | `{facts['integrity']}` |",
             f"| Tarball sha512, computed locally | identical (`{facts['sha512'][:16]}…` in hex) |",
             f"| Registry `gitHead` | `{facts['git_head']}` |",
             f"| SLSA provenance and npm publish attestation, subject | `pkg:npm/%40tari-project/"
             f"{short(facts['package'])}@{facts['version']}`, sha512 `{facts['sha512'][:16]}…` = the tarball |",
             f"| Build | `{facts['ref']}`, commit `{facts['commit']}`, `{facts['workflow']}`, run `{facts['run']}` "
             f"(attempt {facts['attempt']}) |",
             f"| Transparency log | Rekor entries {', '.join(facts['rekor']['provenance'])} (provenance) and "
             f"{', '.join(facts['rekor']['publish'])} (npm publish attestation) |"]
    if sums:
        lines += ["", "| File | sha256 |", "|---|---|"] + [f"| `{n}` | `{d}` |" for n, d in sorted(sums.items())]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--name", required=True)
    c.add_argument("--version", required=True)
    c.add_argument("--commit", required=True)
    c.add_argument("--downloads", type=Path, required=True)
    c.add_argument("--out", type=Path)
    c.add_argument("--file", action="append", default=[])
    c.add_argument("--license", type=Path)
    r = sub.add_parser("repin")
    r.add_argument("--from", dest="old", required=True)
    r.add_argument("--to", dest="new", required=True)
    r.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            facts, tarball = check(args.name, args.version, args.commit, args.downloads)
            sums = None
            if args.out:
                need(bool(args.file), "--out needs at least one --file")
                sums = extract(tarball, args.file, args.out, args.license)
            print(json.dumps({**facts, "sha256": sums}, indent=1))
            print(markdown(facts, sums), file=sys.stderr)
        else:
            for rel, n in repin(args.root, args.old, args.new).items():
                print(f"{n:3d}  {rel}")
    except (ProvenanceError, OSError, tarfile.TarError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"npm-provenance: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
