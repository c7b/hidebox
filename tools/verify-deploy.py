#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that a live deployment serves exactly what a clean build of a git tag produces (spec §14.5).

  python3 -I tools/verify-deploy.py https://srv2052606.hstgr.cloud spooky-secrets-2026-10

1. Export the tag with `git archive` (a clean tree; this repository is not modified).
2. Build it with that tree's own tools/build.py. Placeholders ({{ORIGIN}}, {{REPO_URL}}, …) are filled
   from the deployment's public /api/v1/config, the values it was built with.
3. Download the live /.well-known/mutis-manifest.json and then every file it lists, hash each one
   ourselves (the manifest alone could lie), and compare with the local build.
Prints every difference; exit status 0 only when there are none. Python stdlib only.

Needs Python 3.11 or newer (the build reads its config with tomllib) and git. The export is made
with LF line endings whatever core.autocrlf says, so a Windows checkout compares the same bytes.

What this proves: the files your browser gets now match the published source. What it can't: that
they will still match on your next visit (a browser can't pin a site), or what runs on the server.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mutis-verify-deploy"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def live_settings(origin: str) -> dict:
    """The deployment's own public configuration, for the build's placeholders."""
    try:
        cfg = json.loads(fetch(origin + "/api/v1/config"))
    except (urllib.error.URLError, OSError, ValueError):
        cfg = {}
    return {"public_origin": origin, "network": cfg.get("network", "esmeralda"),
            "security_drop_url": cfg.get("security_drop") or "", "repo_url": cfg.get("repo_url", "https://github.com/c7b/mutis")}


def toml_string(value: str) -> str:
    return json.dumps(value)


def build_tag(tag: str, origin: str, holding: bool, work: Path) -> tuple[str, dict]:
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", f"{tag}^{{commit}}"],
                         capture_output=True, text=True, check=True).stdout.strip()
    version = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--always", sha],
                             capture_output=True, text=True, check=True).stdout.strip()
    when = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct", sha],
                          capture_output=True, text=True, check=True).stdout.strip()
    src = work / "src"
    src.mkdir()
    archive = subprocess.run(["git", "-C", str(ROOT), "-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", sha],
                             capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
    settings = live_settings(origin)
    config = work / "mutis.toml"
    config.write_text("".join(f"{k} = {toml_string(v)}\n" for k, v in settings.items()))
    cmd = [sys.executable, "-I", str(src / "tools" / "build.py"), "--config", str(config), "--web", str(src / "web"),
           "--out", str(work / "dist"), "--release", str(work / "release"), "--source", sha, version, when]
    if holding:
        cmd.append("--holding")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    local = json.loads((work / "dist" / ".well-known" / "mutis-manifest.json").read_text())
    return sha, local


def compare(origin: str, local: dict, live: dict, sha: str) -> list[str]:
    diffs = []
    if live.get("git_sha") != sha:
        diffs.append(f"the live manifest is for commit {live.get('git_sha')}, the tag is {sha}")
    for path in sorted(set(local["files"]) - set(live["files"])):
        diffs.append(f"missing on the live site: {path}")
    for path in sorted(set(live["files"]) - set(local["files"])):
        diffs.append(f"on the live site but not in the build: {path}")
    for path in sorted(set(live["files"]) & set(local["files"])):
        url = origin + "/" + urllib.parse.quote(path)
        try:
            served = hashlib.sha256(fetch(url)).hexdigest()
        except (urllib.error.URLError, OSError) as e:
            diffs.append(f"{path}: could not download ({e})")
            continue
        if served != local["files"][path]:
            diffs.append(f"{path}: served bytes differ from the build")
        elif live["files"][path] != served:
            diffs.append(f"{path}: the live manifest's hash is wrong")
    return diffs


def main() -> int:
    if sys.version_info < (3, 11):
        print(f"verify-deploy: needs Python 3.11 or newer (this is {sys.version.split()[0]})", file=sys.stderr)
        return 2
    p = argparse.ArgumentParser(description="verify a live mutis deployment against a git tag")
    p.add_argument("origin")
    p.add_argument("tag")
    args = p.parse_args()
    origin = args.origin.rstrip("/")
    live = json.loads(fetch(origin + "/.well-known/mutis-manifest.json"))
    with tempfile.TemporaryDirectory(prefix="mutis-verify-") as tmp:
        sha, local = build_tag(args.tag, origin, "holding.css" in live["files"], Path(tmp))
    diffs = compare(origin, local, live, sha)
    for line in diffs:
        print("DIFF", line)
    print(f"verify-deploy: {len(diffs)} differences across {len(local['files'])} files "
          f"({args.tag} = {sha[:12]}, {origin})")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
