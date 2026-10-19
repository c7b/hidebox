# SPDX-License-Identifier: MIT
"""The E2E environment, scenario registry and per-scenario context (spec §17). Python stdlib only.

Scenarios register with @scenario("E-01", "title", tags…) and receive a `T`: actors (fresh browser
contexts with device emulation), admin steps on the server (as mutis or drive, never as build), the
public API, screenshots, and the secrets list that E-03 searches every captured request for.
"""
import base64
import hashlib
import json
import os
import shlex
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cdp

E2E_DIR = Path(__file__).resolve().parent
REMOTE_DIR = "/home/build/work/deploy/e2e"           # on the server, owned by build
# The server's SSH alias (~/.ssh/config): MUTIS_SSH_HOST, else "hidebox". Every --host defaults to it.
SSH_HOST = os.environ.get("MUTIS_SSH_HOST", "hidebox")
CHAIN, STAGING = "chain", "staging"                   # tags: Esmeralda transactions; changes server limits


class Failed(AssertionError):
    pass


class Skipped(Exception):
    pass


@dataclass
class Scenario:
    sid: str
    title: str
    tags: tuple
    fn: Callable


REGISTRY: dict[str, Scenario] = {}


def scenario(sid: str, title: str, *tags: str):
    def register(fn):
        REGISTRY[sid] = Scenario(sid, title, tags, fn)
        return fn
    return register


class Remote:
    """Shell commands on the server: through one multiplexed ssh connection, or locally when on it."""

    def __init__(self, host: str | None, control_dir: Path):
        self.prefix = ["bash", "-c"] if host is None else [
            "ssh", "-o", "ControlMaster=auto", "-o", f"ControlPath={control_dir}/cm", "-o", "ControlPersist=15m",
            "-o", "ClearAllForwardings=yes", "-o", "ServerAliveInterval=30", host]

    def run(self, command: str, data: bytes | None = None, check: bool = True) -> str:
        res = subprocess.run(self.prefix + [command], input=data, capture_output=True, timeout=900)
        if check and res.returncode != 0:
            raise Failed(f"remote command failed ({res.returncode}): {command[:120]}: {res.stderr.decode()[-400:]}")
        return res.stdout.decode()

    def as_build(self, command: str, data: bytes | None = None) -> str:
        return self.run(f"sudo -iu build bash -c {shlex.quote(command)}", data)

    def admin(self, *args: str) -> str:
        return self.run("sudo mutis-admin " + " ".join(shlex.quote(a) for a in args))

    def sql(self, query: str, *params) -> list:
        """A read-only query on the live database, as mutis (statements arrive on stdin, not argv)."""
        script = ("import json, sqlite3, sys; c = sqlite3.connect('file:/srv/mutis/data/db/mutis.sqlite3?mode=ro', uri=True);"
                  f" print(json.dumps(c.execute({query!r}, {list(params)!r}).fetchall()))")
        return json.loads(self.run("cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'", script.encode()))

    def browser_command(self, jitless: bool) -> list[str]:
        relay = f"python3 -I {REMOTE_DIR}/relay.py" + (" --jitless" if jitless else "")
        return self.prefix + [f"sudo -iu build {relay}"]


@dataclass
class Env:
    origin: str
    remote: Remote
    out: Path
    hygiene: list = field(default_factory=list)       # (scenario id, problems) for E-03
    _config: dict | None = None

    def stage(self) -> None:
        """Copy the relay and the small fixtures to build's work directory on the server, and make
        the big ones there (the same deterministic bytes as big_fixture() computes here)."""
        self.remote.as_build(f"mkdir -p {REMOTE_DIR}/fixtures {REMOTE_DIR}/downloads")
        self.remote.as_build(f"cat > {REMOTE_DIR}/relay.py", (E2E_DIR / "relay.py").read_bytes())
        for name, data in small_fixtures().items():
            self.remote.as_build(f"cat > {REMOTE_DIR}/fixtures/{name}", data)
        for name, size in BIG_FIXTURES.items():
            self.remote.as_build(f"cd {REMOTE_DIR}/fixtures && python3 -I -c {shlex.quote(BIG_FIXTURE_CODE)} {name} {size}")

    def config(self) -> dict:
        if self._config is None:
            req = urllib.request.Request(self.origin + "/api/v1/config", headers={"User-Agent": "mutis-e2e"})
            with urllib.request.urlopen(req, timeout=20) as res:
                self._config = json.load(res)
        return self._config


# Big upload fixtures: SHA-256 of a counter, concatenated, cut to size. Made on the server, hashed here.
BIG_FIXTURES = {"ten-mb.dat": 10 * 1024 * 1024, "five-mb.dat": 5 * 1024 * 1024, "too-big.dat": 26 * 1024 * 1024 + 1}
BIG_FIXTURE_CODE = ("import hashlib, sys; n = int(sys.argv[2]); "
                    "data = b''.join(hashlib.sha256(i.to_bytes(4, 'big')).digest() for i in range(n // 32 + 1)); "
                    "open(sys.argv[1], 'wb').write(data[:n])")


def big_fixture_sha256(name: str) -> str:
    n = BIG_FIXTURES[name]
    data = b"".join(hashlib.sha256(i.to_bytes(4, "big")).digest() for i in range(n // 32 + 1))
    return hashlib.sha256(data[:n]).hexdigest()


def small_fixtures() -> dict[str, bytes]:
    jpeg = (E2E_DIR.parents[1] / "web" / "app" / "tests" / "fixtures" / "exif" / "jpeg-gps.jpg").read_bytes()
    return {
        "photo-gps.jpg": jpeg,
        "setup.exe": b"MZ" + bytes(510) + b"This program cannot be run in DOS mode." + bytes(1000),
        "notes.txt": "mutis e2e plain text: the quick brown fox\n".encode(),
    }


class T:
    """One scenario run."""

    def __init__(self, env: Env, sid: str):
        self.env, self.sid = env, sid
        self.origin = env.origin
        self.notes: list[str] = []
        self.secrets: list[tuple[str, str]] = []
        self.browsers: dict[bool, cdp.Browser] = {}
        self.contexts: list[cdp.Context] = []
        self.shots = 0

    def browser(self, jitless: bool = False) -> cdp.Browser:
        if jitless not in self.browsers:
            self.browsers[jitless] = cdp.Browser(self.env.remote.browser_command(jitless))
        return self.browsers[jitless]

    def actor(self, device: str = "desktop", reduced_motion: bool = False, jitless: bool = False,
              judge_pass: str | None = None) -> cdp.Page:
        """A fresh browser context. `judge_pass`: the device holds it as a /judges#pass= link saves it
        (P-12): `localStorage` `mutis.judge` = `{code, until}`, a week from now (store.saveJudgePass)."""
        ctx = self.browser(jitless).context()
        ctx.downloads_to(f"{REMOTE_DIR}/downloads/{self.sid}-{len(self.contexts)}")
        self.contexts.append(ctx)
        page = ctx.page(device, reduced_motion)
        if judge_pass:
            saved = f"JSON.stringify({{code: {json.dumps(judge_pass)}, until: Date.now() + 7 * 86400000}})"
            page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": f"localStorage.setItem('mutis.judge', {saved});"})
        return page

    def fixture(self, name: str) -> str:
        return f"{REMOTE_DIR}/fixtures/{name}"

    def check(self, condition, message: str) -> None:
        if not condition:
            raise Failed(message)
        self.notes.append("ok: " + message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def skip(self, reason: str) -> None:
        raise Skipped(reason)

    def shot(self, page: cdp.Page, name: str) -> Path:
        self.shots += 1
        path = self.env.out / f"{self.sid}-{self.shots:02d}-{name}.png"
        page.screenshot(str(path))
        return path

    def secret(self, name: str, value: str | bytes) -> None:
        """A value that must never appear in any URL, header or body this scenario's browsers send."""
        raw = value.encode() if isinstance(value, str) else value
        forms = {raw.hex(), base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), base64.b64encode(raw).decode()}
        if isinstance(value, str):
            forms.add(value)
        self.secrets += [(name, f) for f in forms if len(f) >= 8]

    def hygiene(self) -> list[str]:
        """E-03: search every request of every page of this scenario for the registered secrets."""
        problems = []
        for ctx in self.contexts:
            for page in ctx.pages:
                page.collect()
                for r in page.requests:
                    blob = r["url"] + json.dumps(r["headers"]) + (r["body"] or "")
                    problems += [f"{name} sent in {r['method']} {r['url'][:80]}" for name, form in self.secrets if form in blob]
        self.env.hygiene.append((self.sid, problems))
        return problems

    def downloaded(self, page: cdp.Page, timeout: float = 120) -> str:
        """Wait for the next completed download of this page's context; return its path on the server."""
        done = page.b.wait_event("Browser.downloadProgress", None, timeout, lambda p: p.get("state") == "completed")
        ctx = next(c for c in self.contexts if page in c.pages)
        return f"{REMOTE_DIR}/downloads/{self.sid}-{self.contexts.index(ctx)}/{done['guid']}"

    def download_sha256(self, page: cdp.Page) -> str:
        return self.env.remote.as_build(f"sha256sum {shlex.quote(self.downloaded(page))}").split()[0]

    def close(self) -> None:
        for ctx in self.contexts:
            ctx.close()
        for b in self.browsers.values():
            b.close()


def poll(fn: Callable, timeout: float, interval: float = 2.0):
    end = time.monotonic() + timeout
    while True:
        value = fn()
        if value or time.monotonic() > end:
            return value
        time.sleep(interval)
