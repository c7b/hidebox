#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The cut-over (docs/cutover.md): a host moves from the testnet deployment to a mainnet instance, the testnet moves to
a host of its own, and the mainnet instance's old host answers 308. As root, from a copy of deploy/:
  cutover.py switch --host hidebox.app --testnet-host testnet.hidebox.app --old-host mainnet.hidebox.app \\
                    --mainnet-instance mainnet [--testnet-instance NAME] [--check]
  cutover.py rollback --from /var/backups/mutis-cutover-<time>
The testnet is production (no --testnet-instance: its host is MUTIS_HOST in /etc/mutis/caddy.env) or an instance (its
host is its config's, its site in /etc/caddy/mutis.d). switch, in order:
 1. checks each side is where the move starts from, and keeps every file it changes in /var/backups/mutis-cutover-<time>;
 2. exports the frozen set of the testnet's link ids (legacy-ids.py) for the mainnet instance's Caddy site;
 3. edits both configs (origins, memo origins, legacy_origin, redirect_hosts, the security drop's host) and has each
    deployment's own mutis-admin check them;
 4. renders the sites with each release's own instance.py, and validates the whole Caddy configuration with them in
    a copy (production's Caddyfile, every other mutis.d file, the new MUTIS_HOST);
 5. installs, reloads Caddy once, restarts both APIs and chain workers, and exports the set again.
Any failure before the reload changes nothing live; a refused reload puts every file back. --check stops after step 4,
with nothing installed. rollback puts back what a switch kept and reloads. Python standard library only.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("legacy_ids", HERE / "legacy-ids.py")
legacy_ids = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy_ids)

CADDY_D = Path("/etc/caddy/mutis.d")
CADDYFILE = Path("/etc/caddy/Caddyfile")
PREISSUE = CADDY_D / "cutover-preissue.caddy"   # a host's certificate asked for ahead (docs/cutover.md "Before")
HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


class Stop(Exception):
    pass


def run(*cmd, env=None, check=True) -> subprocess.CompletedProcess:
    res = subprocess.run(list(cmd), capture_output=True, text=True, env=env)
    if check and res.returncode:
        raise Stop(f"{' '.join(cmd[:4])}: {(res.stderr or res.stdout).strip()[-600:]}")
    return res


def layout(name: str) -> dict:
    s = f"-{name}" if name else ""
    return {"name": name, "etc": Path(f"/etc/mutis{s}"), "config": Path(f"/etc/mutis{s}/mutis.toml"),
            "db": Path(f"/srv/mutis{s}/data/db/mutis.sqlite3"), "release": Path(f"/srv/mutis{s}/app/current"),
            "admin": f"/usr/local/sbin/mutis-admin{s}", "units": [f"mutis{s}-api", f"mutis{s}-chain"],
            "site": CADDY_D / f"{name}.caddy" if name else None, "legacy": Path(f"/srv/mutis{s}/legacy")}


# --- config edits: line by line, every key once, so a comment or another table can't be touched -----------------------

def top_level(text: str) -> str:
    """The lines before the first [table]."""
    m = re.search(r"^\[", text, re.M)
    return text[:m.start()] if m else text


def set_key(text: str, key: str, value: str) -> str:
    """Sets a top-level `key = value` (a TOML literal); adds it after public_origin when missing."""
    head = top_level(text)
    found = re.findall(rf"^{key} = .*$", head, re.M)
    if len(found) > 1:
        raise Stop(f"{key} is set {len(found)} times")
    if found:
        return text.replace(found[0], f"{key} = {value}", 1)
    at = re.search(r"^public_origin = .*$", head, re.M)
    if not at:
        raise Stop("no public_origin line")
    return text[:at.end()] + f"\n{key} = {value}" + text[at.end():]


def get_key(text: str, key: str):
    m = re.search(rf"^{key} = (.*)$", top_level(text), re.M)
    return json.loads(m.group(1)) if m else None


def testnet_config(text: str, host: str, testnet_host: str) -> str:
    """The testnet at its own host; the memos already on the chain keep naming the old one."""
    if get_key(text, "public_origin") != f"https://{host}":
        raise Stop(f"the testnet's public_origin isn't https://{host}: {get_key(text, 'public_origin')}")
    memos = get_key(text, "memo_origins") or []
    text = set_key(text, "public_origin", json.dumps(f"https://{testnet_host}"))
    text = set_key(text, "memo_origins", json.dumps(memos + [f"https://{testnet_host}"] if f"https://{testnet_host}" not in memos else memos))
    drop = get_key(text, "security_drop_url")
    if drop:
        text = set_key(text, "security_drop_url", json.dumps(re.sub(r"^https://[^/]+", f"https://{testnet_host}", drop)))
    return text


def mainnet_config(text: str, host: str, testnet_host: str, old_host: str) -> str:
    if get_key(text, "public_origin") != f"https://{old_host}":
        raise Stop(f"the mainnet instance's public_origin isn't https://{old_host}: {get_key(text, 'public_origin')}")
    for key, value in (("public_origin", f"https://{host}"), ("memo_origins", [f"https://{host}", f"https://{old_host}"]),
                       ("testnet_origin", f"https://{testnet_host}"), ("legacy_origin", f"https://{testnet_host}"),
                       ("redirect_hosts", [old_host])):
        text = set_key(text, key, json.dumps(value))
    return text


def caddy_env(text: str, host: str, testnet_host: str) -> str:
    if not re.search(rf"^MUTIS_HOST={re.escape(host)}$", text, re.M):
        raise Stop(f"caddy.env doesn't say MUTIS_HOST={host}")
    return re.sub(r"^MUTIS_HOST=.*$", f"MUTIS_HOST={testnet_host}", text, count=1, flags=re.M)


# --- the switch ---------------------------------------------------------------------------------------------------------

def render(side: dict, config: Path, out: Path) -> None:
    run(sys.executable, "-I", str(side["release"] / "deploy" / "scripts" / "instance.py"), "caddy", side["name"], str(config), str(out))


def check_config(side: dict, text: str, keep: Path) -> None:
    """The deployment's own mutis-admin, as its own user, on the new text in a probe file beside the live one (which
    stays as it is); the probe goes to the backups afterwards."""
    import grp
    user = f"mutis-{side['name']}" if side["name"] else "mutis"
    probe = side["etc"] / "mutis.toml.cutover-check"
    probe.write_text(text)
    os.chown(probe, 0, grp.getgrnam(user).gr_gid)
    probe.chmod(0o640)
    try:
        run("runuser", "-u", user, "--", "env", f"MUTIS_CONFIG={probe}", "python3", "-I",
            str(side["release"] / "server" / "bin" / "mutis-admin"), "check-config")
    finally:
        probe.rename(keep / f"checked-{side['name'] or 'production'}.toml")


def switch(a) -> int:
    for h in (a.host, a.testnet_host, a.old_host):
        if not HOST.fullmatch(h):
            raise Stop(f"not a host name: {h}")
    test, main = layout(a.testnet_instance), layout(a.mainnet_instance)
    if not main["name"]:
        raise Stop("--mainnet-instance names the instance that takes the host")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    keep = Path(f"/var/backups/mutis-cutover-{stamp}")
    work = Path(tempfile.mkdtemp(prefix="mutis-cutover-"))
    env_file = Path("/etc/mutis/caddy.env")
    files = [test["config"], main["config"], main["site"]] + ([test["site"]] if test["name"] else [env_file])
    files += [PREISSUE] if PREISSUE.exists() else []
    keep.mkdir(mode=0o700, parents=True)
    for f in files:
        shutil.copy2(f, keep / f"{f.parent.name}__{f.name}")
    (keep / "manifest.json").write_text(json.dumps({"files": [str(f) for f in files], "testnet": test["name"], "mainnet": main["name"]}))
    print(f"cutover: kept {len(files)} files in {keep}")

    print("cutover: frozen set", json.dumps(legacy_ids.export(test["db"], main["legacy"])))
    new = {"test": testnet_config(test["config"].read_text(), a.host, a.testnet_host),
           "main": mainnet_config(main["config"].read_text(), a.host, a.testnet_host, a.old_host)}
    check_config(test, new["test"], keep)
    check_config(main, new["main"], keep)
    print("cutover: both configs check")

    (work / "main.toml").write_text(new["main"])
    render(main, work / "main.toml", work / "main.caddy")
    candidate = {main["site"]: (work / "main.caddy").read_text()}
    env_text = env_file.read_text()
    if test["name"]:
        (work / "test.toml").write_text(new["test"])
        render(test, work / "test.toml", work / "test.caddy")
        candidate[test["site"]] = (work / "test.caddy").read_text()
    else:
        env_text = caddy_env(env_text, a.host, a.testnet_host)
    copy = work / "mutis.d"
    copy.mkdir()
    for f in CADDY_D.glob("*.caddy"):
        if f not in candidate and f != PREISSUE:
            shutil.copy2(f, copy / f.name)
    for f, text in candidate.items():
        (copy / f.name).write_text(text)
    caddyfile = CADDYFILE.read_text()
    if "import /etc/caddy/mutis.d/*.caddy" not in caddyfile:
        raise Stop("the Caddyfile has no 'import /etc/caddy/mutis.d/*.caddy' line")
    (work / "Caddyfile").write_text(caddyfile.replace("import /etc/caddy/mutis.d/*.caddy", f"import {copy}/*.caddy"))
    env = {**os.environ, **dict(line.split("=", 1) for line in env_text.splitlines() if "=" in line and not line.startswith("#"))}
    run("caddy", "validate", "--config", str(work / "Caddyfile"), "--adapter", "caddyfile", env=env)
    print("cutover: the whole Caddy configuration validates with the move")
    if a.check:
        print(f"cutover: --check: nothing installed ({work} has the candidate)")
        return 0

    try:
        for side, key in ((test, "test"), (main, "main")):
            side["config"].write_text(new[key])
        for f, text in candidate.items():
            f.write_text(text)
            f.chmod(0o644)
        if not test["name"]:
            env_file.write_text(env_text)
        if PREISSUE.exists():
            PREISSUE.rename(keep / "cutover-preissue.caddy.taken-out")
        run("systemctl", "reload", "caddy")
    except Exception:
        restore(keep)
        raise
    print("cutover: installed; Caddy reloaded")
    for side in (test, main):
        for unit in side["units"]:
            if run("systemctl", "is-enabled", "--quiet", unit, check=False).returncode == 0:
                run("systemctl", "restart", unit)
                print(f"cutover: restarted {unit}")
    print("cutover: frozen set again", json.dumps(legacy_ids.export(test["db"], main["legacy"])))
    print(f"cutover: done; rollback: cutover.py rollback --from {keep}")
    return 0


def restore(keep: Path, reload: bool = True) -> None:
    manifest = json.loads((keep / "manifest.json").read_text())
    for f in map(Path, manifest["files"]):
        shutil.copy2(keep / f"{f.parent.name}__{f.name}", f)
    if reload:
        run("systemctl", "reload", "caddy")
    print(f"cutover: put back {len(manifest['files'])} files from {keep}" + ("; Caddy reloaded" if reload else ""))


def rollback(a) -> int:
    restore(a.source)
    manifest = json.loads((a.source / "manifest.json").read_text())
    for name in (manifest["testnet"], manifest["mainnet"]):
        for unit in layout(name)["units"]:
            if run("systemctl", "is-enabled", "--quiet", unit, check=False).returncode == 0:
                run("systemctl", "restart", unit)
                print(f"cutover: restarted {unit}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("switch")
    s.add_argument("--host", required=True)
    s.add_argument("--testnet-host", required=True)
    s.add_argument("--old-host", required=True)
    s.add_argument("--mainnet-instance", required=True)
    s.add_argument("--testnet-instance", default="")
    s.add_argument("--check", action="store_true")
    r = sub.add_parser("rollback")
    r.add_argument("--from", dest="source", type=Path, required=True)
    a = p.parse_args()
    if os.geteuid() != 0:
        print("cutover: run as root", file=sys.stderr)
        return 2
    try:
        return switch(a) if a.command == "switch" else rollback(a)
    except (Stop, ValueError, OSError) as e:
        print(f"cutover: STOP: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
