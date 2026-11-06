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
import os
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


def tarball(files: dict[str, bytes], special: dict[str, bytes] | None = None) -> bytes:
    """`special`: {name: tar type} members that are not regular files (a symlink, a hard link, a directory)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, kind in (special or {}).items():
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "/etc/passwd"
            tar.addfile(info)
    return buf.getvalue()


def attestation(kind: str, digest: str, predicate: dict, subject: str | None = None, inner: str | None = None) -> dict:
    stmt = {"_type": "https://in-toto.io/Statement/v1", "predicateType": inner or kind, "predicate": predicate,
            "subject": [{"name": subject or f"pkg:npm/%40tari-project/{PKG}@{VERSION}", "digest": {"sha512": digest}}]}
    payload = base64.b64encode(json.dumps(stmt).encode()).decode()
    return {"predicateType": kind, "bundle": {"dsseEnvelope": {"payloadType": "application/vnd.in-toto+json",
                                                               "payload": payload, "signatures": []},
                                              "verificationMaterial": {"tlogEntries": [{"logIndex": "123"}]}}}


def slsa(ref: str = f"refs/tags/v{VERSION}", commit: str = COMMIT, repo: str = npm.REPO, uri: str | None = None) -> dict:
    return {"buildDefinition": {"externalParameters": {"workflow": {
        "ref": ref, "repository": repo, "path": ".github/workflows/npm_publish_ootle_wasm.yml"}},
        "resolvedDependencies": [{"uri": uri or f"git+{repo}@{ref}", "digest": {"gitCommit": commit}}]},
        "runDetails": {"metadata": {"invocationId": f"{npm.REPO}/actions/runs/42/attempts/1"}}}


class Downloads:
    """A downloads folder as curl leaves it (upgrade-0.50.md §2), with knobs to break one fact at a time.
    `listing(publish, provenance)` returns the attestation list to write, from the two good ones."""

    def __init__(self, folder: Path, files=None, tamper=False, subject=None, predicate=None, special=None,
                 listing=None, git_head=COMMIT, inner=None):
        data = tarball(files or {"package/ootle_wasm_bg.wasm": b"\0asm-wasm", "package/ootle_wasm_bg.js": b"glue",
                                 "package/README.md": b"not wanted"}, special)
        digest = hashlib.sha512(data)
        self.tarball = folder / f"{PKG}-{VERSION}.tgz"
        self.tarball.write_bytes(data + (b"x" if tamper else b""))
        meta = {"dist": {"tarball": f"https://registry.npmjs.org/{NAME}/-/{PKG}-{VERSION}.tgz",
                         "integrity": "sha512-" + base64.b64encode(digest.digest()).decode()}}
        if git_head:
            meta["gitHead"] = git_head
        packument = {"name": NAME, "dist-tags": {"latest": VERSION}, "time": {VERSION: "2026-11-06T00:00:00Z"},
                     "versions": {VERSION: meta}}
        (folder / f"{PKG}.packument.json").write_text(json.dumps(packument))
        hexd = digest.hexdigest()
        publish = attestation(npm.NPM_PUBLISH, hexd, {"name": NAME, "version": VERSION}, subject)
        provenance = attestation(npm.SLSA, hexd, predicate or slsa(), inner=inner)
        items = listing(publish, provenance, hexd) if listing else [publish, provenance]
        (folder / f"{PKG}-{VERSION}.attestations.json").write_text(json.dumps({"attestations": items}))


EVIL = slsa(repo="https://github.com/someone/tari-ootle", commit="cd" * 20)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def facts(self, **kw) -> tuple[dict, bytes]:
        for f in self.dir.iterdir():
            shutil.rmtree(f) if f.is_dir() else f.unlink()
        self.downloads = Downloads(self.dir, **kw)
        return npm.check(NAME, VERSION, COMMIT, self.dir)

    def test_a_consistent_package_passes_with_its_facts_and_bytes(self):
        facts, data = self.facts()
        self.assertEqual((facts["ref"], facts["commit"], facts["run"], facts["rekor"]["provenance"]),
                         (f"refs/tags/v{VERSION}", COMMIT, 42, ["123"]))
        self.assertEqual(data, self.downloads.tarball.read_bytes())

    def test_each_broken_fact_is_refused(self):
        cases = {
            "integrity": {"tamper": True},
            "subject": {"subject": "pkg:npm/%40tari-project/other@9.9.9"},
            "commit": {"predicate": slsa(commit="cd" * 20)},
            "tag": {"predicate": slsa(ref="refs/heads/main")},
            "repository": {"predicate": slsa(repo="https://github.com/someone/tari-ootle")},
            "dependency uri": {"predicate": slsa(uri="git+https://github.com/someone/tari-ootle@refs/tags/v9.9.9")},
            "no gitHead": {"git_head": None},
            "another gitHead": {"git_head": "cd" * 20},
            "statement of another type under the SLSA label": {"inner": npm.NPM_PUBLISH},
            "a second SLSA before the good one": {"listing": lambda pub, prov, d: [attestation(npm.SLSA, d, EVIL), prov, pub]},
            "a second SLSA after the good one": {"listing": lambda pub, prov, d: [pub, prov, attestation(npm.SLSA, d, EVIL)]},
            "a stray entry": {"listing": lambda pub, prov, d: [pub, prov, 1]},
            "one attestation": {"listing": lambda pub, prov, d: [prov]},
            "not a list": {"listing": lambda pub, prov, d: {"0": pub, "1": prov}},
        }
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(npm.ProvenanceError):
                self.facts(**kw)

    def test_a_malformed_integrity_is_refused(self):
        self.facts()
        path = self.dir / f"{PKG}.packument.json"
        packument = json.loads(path.read_text())
        packument["versions"][VERSION]["dist"]["integrity"] += "!!"
        path.write_text(json.dumps(packument))
        with self.assertRaises(npm.ProvenanceError):
            npm.check(NAME, VERSION, COMMIT, self.dir)

    def test_extract_reads_the_checked_bytes_and_only_named_regular_files(self):
        special = {"package/ootle_wasm.d.ts": tarfile.SYMTYPE, "package/hard.js": tarfile.LNKTYPE,
                   "package/folder": tarfile.DIRTYPE}
        _, data = self.facts(special=special)
        self.downloads.tarball.write_bytes(b"swapped after the check")      # extract never reads the file again
        out = self.dir / "out"
        sums = npm.extract(data, ["ootle_wasm_bg.wasm", "ootle_wasm_bg.js"], out, None)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["SHA256SUMS", "ootle_wasm_bg.js", "ootle_wasm_bg.wasm"])
        self.assertEqual(sums["ootle_wasm_bg.js"], hashlib.sha256(b"glue").hexdigest())
        refused = {"a symlink": ["ootle_wasm.d.ts"], "a hard link": ["hard.js"], "a directory": ["folder"],
                   "not in the tarball": ["ootle_wasm_bor_bg.wasm"], "a path out of the folder": ["../ootle_wasm_bg.js"],
                   "a name this script writes": ["SHA256SUMS"], "the license": ["LICENSE"]}
        for i, (name, files) in enumerate(refused.items()):
            with self.subTest(name), self.assertRaises(npm.ProvenanceError):
                npm.extract(data, files, self.dir / f"out{i}", None)

    def test_a_duplicate_member_is_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for body in (b"first", b"second"):
                info = tarfile.TarInfo("package/ootle_wasm_bg.js")
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        with self.assertRaises(npm.ProvenanceError):
            npm.extract(buf.getvalue(), ["ootle_wasm_bg.js"], self.dir / "dup", None)


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

    def test_a_stale_list_stops_it_before_it_writes_anything(self):
        (self.root / "deploy" / "scripts" / "init-keys.sh").write_text("#!/bin/sh\n")
        before = {rel: (self.root / rel).read_bytes() for rel in npm.PIN_FILES}
        with self.assertRaises(npm.ProvenanceError):
            npm.repin(self.root, self.OLD, "99.0.0")
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in npm.PIN_FILES}, before)

    def test_pin_files_lists_every_code_file_that_holds_a_pin(self):
        """A pin added anywhere else would be left behind by a repin: every code file outside the vendored folders,
        docs and evidence that names the vendored folders, their wasm and glue hashes or wasm_version is listed."""
        hashes = [d for pkg, (old, _) in self.new_sums.items() for n, d in old.items() if n.endswith((".wasm", "_bg.js"))]
        pin = re.compile("|".join([re.escape(f"ootle-wasm-{self.OLD}"), re.escape(f"ootle-wasm-bor-{self.OLD}"),
                                   *map(re.escape, hashes), r"wasm_version[\"'\]\s=:,]{1,8}" + re.escape(self.OLD)]))
        skip = {".git", "docs", "node_modules", "__pycache__", "e2e-artifacts", "dist", "release", "target", "evidence"}
        found = set()
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in skip and not d.startswith("ootle-wasm-")]
            for name in files:
                path = Path(folder, name)
                if path.suffix in {".py", ".js", ".mjs", ".sh", ".example", ".toml", ".html"} and \
                        pin.search(path.read_text(encoding="utf-8", errors="replace")):
                    found.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(sorted(found - set(npm.PIN_FILES)), [])

    def test_versions_must_be_two_releases(self):
        for old, new in ((self.OLD, self.OLD), (self.OLD, "99.0"), ("0.49.2/", "99.0.0")):
            with self.subTest(old=old, new=new), self.assertRaises(npm.ProvenanceError):
                npm.repin(self.root, old, new)


if __name__ == "__main__":
    unittest.main()
