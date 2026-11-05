# SPDX-License-Identifier: MIT
"""deploy/ootle/npm-provenance.py: `check` accepts a tarball only when the registry's integrity, both attestations'
subject and the provenance's repository, tag and commit all agree, and copies out only the named regular files;
`repin` moves every pin in PIN_FILES from one vendored version to the next and stops on a stale list. Synthetic
packages; no network."""
import base64
import hashlib
import importlib.util
import io
import json
import re
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("npm_provenance", ROOT / "deploy" / "ootle" / "npm-provenance.py")
npm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npm)

COMMIT = "ab" * 20
NAME, PKG, VERSION = "@tari-project/ootle-wasm", "ootle-wasm", "9.9.9"


def tarball(files: dict[str, bytes], link: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo(link)
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
    return buf.getvalue()


def attestation(kind: str, digest: str, predicate: dict, subject: str | None = None) -> dict:
    stmt = {"_type": "https://in-toto.io/Statement/v1", "predicateType": kind, "predicate": predicate,
            "subject": [{"name": subject or f"pkg:npm/%40tari-project/{PKG}@{VERSION}", "digest": {"sha512": digest}}]}
    payload = base64.b64encode(json.dumps(stmt).encode()).decode()
    return {"predicateType": kind, "bundle": {"dsseEnvelope": {"payloadType": "application/vnd.in-toto+json",
                                                               "payload": payload, "signatures": []},
                                              "verificationMaterial": {"tlogEntries": [{"logIndex": "123"}]}}}


def slsa(ref: str = f"refs/tags/v{VERSION}", commit: str = COMMIT, repo: str = npm.REPO) -> dict:
    return {"buildDefinition": {"externalParameters": {"workflow": {
        "ref": ref, "repository": repo, "path": ".github/workflows/npm_publish_ootle_wasm.yml"}},
        "resolvedDependencies": [{"uri": f"git+{repo}@{ref}", "digest": {"gitCommit": commit}}]},
        "runDetails": {"metadata": {"invocationId": f"{npm.REPO}/actions/runs/42/attempts/1"}}}


class Downloads:
    """A downloads folder as curl leaves it (upgrade-0.50.md §2), with knobs to break one fact at a time."""

    def __init__(self, folder: Path, files=None, tamper=False, subject=None, predicate=None, link=None):
        data = tarball(files or {"package/ootle_wasm_bg.wasm": b"\0asm-wasm", "package/ootle_wasm_bg.js": b"glue",
                                 "package/README.md": b"not wanted"}, link)
        digest = hashlib.sha512(data)
        (folder / f"{PKG}-{VERSION}.tgz").write_bytes(data + (b"x" if tamper else b""))
        packument = {"name": NAME, "dist-tags": {"latest": VERSION}, "time": {VERSION: "2026-11-06T00:00:00Z"},
                     "versions": {VERSION: {"gitHead": COMMIT, "dist": {
                         "tarball": f"https://registry.npmjs.org/{NAME}/-/{PKG}-{VERSION}.tgz",
                         "integrity": "sha512-" + base64.b64encode(digest.digest()).decode()}}}}
        (folder / f"{PKG}.packument.json").write_text(json.dumps(packument))
        hexd = digest.hexdigest()
        (folder / f"{PKG}-{VERSION}.attestations.json").write_text(json.dumps({"attestations": [
            attestation(npm.NPM_PUBLISH, hexd, {"name": NAME, "version": VERSION}, subject),
            attestation(npm.SLSA, hexd, predicate or slsa())]}))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def facts(self, **kw) -> dict:
        Downloads(self.dir, **kw)
        return npm.check(NAME, VERSION, COMMIT, self.dir)

    def test_a_consistent_package_passes_with_its_facts(self):
        facts = self.facts()
        self.assertEqual((facts["ref"], facts["commit"], facts["run"], facts["rekor"]["provenance"]),
                         (f"refs/tags/v{VERSION}", COMMIT, 42, ["123"]))

    def test_each_broken_fact_is_refused(self):
        cases = {"integrity": {"tamper": True}, "subject": {"subject": "pkg:npm/%40tari-project/other@9.9.9"},
                 "commit": {"predicate": slsa(commit="cd" * 20)}, "tag": {"predicate": slsa(ref="refs/heads/main")},
                 "repository": {"predicate": slsa(repo="https://github.com/someone/tari-ootle")}}
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(npm.ProvenanceError):
                for f in self.dir.iterdir():
                    f.unlink()
                self.facts(**kw)

    def test_extract_copies_only_the_named_regular_files(self):
        Downloads(self.dir, link="package/ootle_wasm.d.ts")
        out = self.dir / "out"
        sums = npm.extract(self.dir / f"{PKG}-{VERSION}.tgz", ["ootle_wasm_bg.wasm", "ootle_wasm_bg.js"], out, None)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["SHA256SUMS", "ootle_wasm_bg.js", "ootle_wasm_bg.wasm"])
        self.assertEqual(sums["ootle_wasm_bg.js"], hashlib.sha256(b"glue").hexdigest())
        with self.assertRaises(npm.ProvenanceError):     # a link, not a file
            npm.extract(self.dir / f"{PKG}-{VERSION}.tgz", ["ootle_wasm.d.ts"], self.dir / "out2", None)
        with self.assertRaises(npm.ProvenanceError):     # not in the tarball
            npm.extract(self.dir / f"{PKG}-{VERSION}.tgz", ["ootle_wasm_bor_bg.wasm"], self.dir / "out3", None)
        with self.assertRaises(npm.ProvenanceError):     # a name that could leave the folder
            npm.extract(self.dir / f"{PKG}-{VERSION}.tgz", ["../ootle_wasm_bg.js"], self.dir / "out4", None)


class RepinTest(unittest.TestCase):
    """On a copy of the files repin touches, with the vendored folders' SHA256SUMS and a next version whose wasm and
    glue hashes differ, nothing of the old version is left in PIN_FILES, and every new hash is in place."""

    OLD = re.search(r'"wasm_version": "([0-9.]+)"', (ROOT / "server" / "mutis" / "config.py").read_text()).group(1)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for rel in npm.PIN_FILES:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, self.root / rel)
        self.new_sums = {}
        for pkg in npm.PACKAGES:
            old = ROOT / "web" / "app" / "vendor" / f"{pkg}-{self.OLD}" / "SHA256SUMS"
            copy = self.root / "web" / "app" / "vendor" / f"{pkg}-{self.OLD}"
            new = self.root / "web" / "app" / "vendor" / f"{pkg}-99.0.0"
            copy.mkdir(parents=True)
            shutil.copyfile(old, copy / "SHA256SUMS")
            new.mkdir(parents=True)
            lines = [line.split(maxsplit=1) for line in old.read_text().splitlines()]
            sums = {n: hashlib.sha256((d + "next").encode()).hexdigest() for d, n in lines}
            (new / "SHA256SUMS").write_text("".join(f"{sums[n]}  {n}\n" for n in sorted(sums)))
            self.new_sums[pkg] = (dict((n, d) for d, n in lines), sums)

    def test_every_pin_moves(self):
        counts = npm.repin(self.root, self.OLD, "99.0.0")
        self.assertEqual(set(counts), set(npm.PIN_FILES))
        text = {rel: (self.root / rel).read_text() for rel in npm.PIN_FILES}
        for rel, body in text.items():
            self.assertNotIn(f"ootle-wasm-{self.OLD}", body, rel)
            self.assertNotIn(f"ootle-wasm-bor-{self.OLD}", body, rel)
            self.assertNotRegex(body, rf"wasm_version[\"'\]\s=:,]{{1,8}}{re.escape(self.OLD)}", rel)
        for pkg, (old, new) in self.new_sums.items():
            for name in ("ootle_wasm_bg.wasm", "ootle_wasm_bg.js", "ootle_wasm_bor_bg.wasm", "ootle_wasm_bor_bg.js"):
                if name in old:
                    self.assertFalse(any(old[name] in body for body in text.values()), f"{pkg} {name}")
        self.assertIn(self.new_sums["ootle-wasm"][1]["ootle_wasm_bg.wasm"], text["server/mutis/config.py"])
        self.assertIn(self.new_sums["ootle-wasm-bor"][1]["ootle_wasm_bor_bg.wasm"], text["web/app/vendor/ootle-wasm-shim.js"])
        self.assertIn('"wasm_version": "99.0.0"', text["server/mutis/config.py"])

    def test_a_stale_list_stops_it(self):
        (self.root / "deploy" / "scripts" / "init-keys.sh").write_text("#!/bin/sh\n")
        with self.assertRaises(npm.ProvenanceError):
            npm.repin(self.root, self.OLD, "99.0.0")


if __name__ == "__main__":
    unittest.main()
