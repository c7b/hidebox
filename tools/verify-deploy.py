#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that a live deployment serves exactly what a clean build of a git tag produces (spec §14.5).

  python3 -I tools/verify-deploy.py https://hidebox.app spooky-secrets-2026-10

1. Export the tag with `git archive` (a clean tree; this repository is not modified).
2. Build it with that tree's own tools/build.py. Placeholders ({{ORIGIN}}, {{REPO_URL}}, …) are filled
   from the deployment's public /api/v1/config, the values it was built with; the copy variants
   (relay or direct sends, how payments are checked, …) from the config tables the live manifest
   says the build read.
3. Download the live /.well-known/mutis-manifest.json and then every file it lists, hash each one
   ourselves (the manifest alone could lie), and compare with the local build.
4. When the deployment names a SealLog (/api/v1/config seal_log.component), read the log's template
   address from a Tari indexer and check, with the tag's own template/wasm_check.py, that the chain
   runs the tag's template/dist/seal_log.wasm byte for byte (template/check.sh --onchain).
Prints every difference; exit status 0 only when there are none. Python stdlib only.

Needs Python 3.11 or newer (the build reads its config with tomllib) and git. The export is made
with LF line endings whatever core.autocrlf says, so a Windows checkout compares the same bytes.

What this proves: the files your browser gets now match the published source, and SealLog runs the
published template. What it can't: that the files will still match on your next visit (a browser
can't pin a site), or what runs on the server.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEXER = "https://ootle-indexer-a.tari.com"
VARIANT_TABLES = ("gates", "features", "hosting")      # tools/build.py records these in the manifest
NAME = re.compile(r"[a-z_]+")
ADDRESS = re.compile(r"[0-9a-f]{64}")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mutis-verify-deploy"})   # the indexers refuse urllib's
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def live_config(origin: str) -> dict:
    """The deployment's own public configuration (empty if it doesn't answer)."""
    try:
        return json.loads(fetch(origin + "/api/v1/config"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value))       # a JSON string is a valid TOML basic string


def build_config(origin: str, cfg: dict, variant_config: dict) -> str:
    """The mutis.toml the tag is built with: the public settings from /config, then the tables the
    live build's copy variants read, as its manifest records them (only plain names and values)."""
    lines = [f"{k} = {toml_value(v)}" for k, v in {
        "public_origin": origin, "network": cfg.get("network", "esmeralda"),
        "security_drop_url": cfg.get("security_drop") or "", "repo_url": cfg.get("repo_url", "https://github.com/c7b/hidebox"),
    }.items()]
    for table in VARIANT_TABLES:
        values = variant_config.get(table)
        if isinstance(values, dict):
            lines += [f"[{table}]"] + [f"{k} = {toml_value(v)}" for k, v in sorted(values.items())
                                       if NAME.fullmatch(k) and isinstance(v, (str, bool, int))]
    return "\n".join(lines) + "\n"


def build_tag(tag: str, config: str, holding: bool, work: Path) -> tuple[str, dict, Path]:
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
    (work / "mutis.toml").write_text(config, encoding="utf-8", newline="\n")
    cmd = [sys.executable, "-I", str(src / "tools" / "build.py"), "--config", str(work / "mutis.toml"),
           "--web", str(src / "web"), "--out", str(work / "dist"), "--release", str(work / "release"),
           "--source", sha, version, when]
    if holding:
        cmd.append("--holding")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    local = json.loads((work / "dist" / ".well-known" / "mutis-manifest.json").read_text())
    return sha, local, src


def seallog_check(cfg: dict, src: Path) -> list[str]:
    """The template behind the deployment's SealLog is the tag's template/dist/seal_log.wasm."""
    component = (cfg.get("seal_log") or {}).get("component")
    if not component:
        print("SealLog: this deployment names no log")
        return []
    if not ADDRESS.fullmatch(str(component).removeprefix("component_")):
        return [f"SealLog: /api/v1/config names no valid component ({str(component)[:80]!r})"]
    try:
        body = json.loads(fetch(f"{INDEXER}/substates/{component}"))
        template = body["substate"]["Component"]["header"]["template_address"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        return [f"SealLog {component}: could not read its template from {INDEXER} ({e})"]
    if not ADDRESS.fullmatch(str(template)):
        return [f"SealLog {component}: the indexer gave no valid template address"]
    check = subprocess.run([sys.executable, "-I", str(src / "template" / "wasm_check.py"), "onchain", f"template_{template}"],
                           capture_output=True, text=True)
    print(f"SealLog {component}:\n" + "".join(f"  {line}\n" for line in (check.stdout + check.stderr).splitlines()), end="")
    return [] if check.returncode == 0 else [f"SealLog {component}: template_{template} is not the tag's seal_log.wasm"]


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
    cfg = live_config(origin)
    config = build_config(origin, cfg, live.get("variant_config") or {})
    with tempfile.TemporaryDirectory(prefix="mutis-verify-") as tmp:
        sha, local, src = build_tag(args.tag, config, "holding.css" in live["files"], Path(tmp))
        diffs = compare(origin, local, live, sha) + seallog_check(cfg, src)
    for line in diffs:
        print("DIFF", line)
    print(f"verify-deploy: {len(diffs)} differences across {len(local['files'])} files "
          f"({args.tag} = {sha[:12]}, {origin})")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
