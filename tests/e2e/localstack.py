# SPDX-License-Identifier: MIT
"""A throwaway copy of the production web stack on the server, run as `build`: `mutis-api --dev`
(fakes, small limits, its own temporary data; spec §3.6) behind Caddy running deploy/caddy/Caddyfile
with only its paths and ports rewritten. griefer.py (E-23) and test_headers.py --local use it.

Nothing in it touches production: other ports bound to 127.0.0.1, build's own work directory, a
private Caddy with its admin API off. One ssh connection carries the commands and the tunnel, so
from here the stack is http://127.0.0.1:WEB_PORT (Caddy) and http://127.0.0.1:API_PORT (the API).
"""
import io
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from harness import Remote

ROOT = Path(__file__).resolve().parents[2]
WORK = "/home/build/work/deploy/localstack"
API_PORT, WEB_PORT, REDIRECT_PORT = 18788, 18444, 18445
APP_STUBS = {
    "app.html": '<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n<html lang="en"><head><title>app</title></head>'
                '<body><main id="mutis-app"></main></body></html>\n',
    "view.html": '<!doctype html>\n<!-- SPDX-License-Identifier: MIT -->\n<html lang="en"><head><title>view</title></head>'
                 '<body><main id="mutis-view"></main></body></html>\n',
    "drop-widget.js": "// SPDX-License-Identifier: MIT\nexport {};\n",
}


def local_caddyfile(text: str, buffered: bool = True) -> str:
    """The production Caddyfile with its paths and ports moved into the work directory."""
    rewrites = [
        ("admin unix//run/caddy/admin.sock", "admin off"),
        ("import /etc/caddy/mutis.d/*.caddy", ""),
        ("http://{$MUTIS_HOST} {", f"http://127.0.0.1:{REDIRECT_PORT} {{\n\tbind 127.0.0.1"),
        ("\n{$MUTIS_HOST} {", f"\nhttp://127.0.0.1:{WEB_PORT} {{\n\tbind 127.0.0.1"),
        ("\nhttps:// {", f"\nhttp://:{WEB_PORT} {{\n\tbind 127.0.0.1"),
        ("\nhttp:// {", f"\nhttp://:{REDIRECT_PORT} {{\n\tbind 127.0.0.1"),
        ("/srv/mutis/app/current/dist", f"{WORK}/dist"),
        ("/srv/mutis/status", f"{WORK}/status"),
        ("reverse_proxy 127.0.0.1:8787", f"reverse_proxy 127.0.0.1:{API_PORT}"),
    ]
    if not buffered:
        rewrites.append((re.search(r"\n\s*buffer_requests\n\s*max_buffer_size \S+", text).group(0), ""))
    for old, new in rewrites:
        if old not in text:
            raise ValueError(f"the Caddyfile no longer contains {old!r}")
        text = text.replace(old, new)
    return text


def stub_build(out: Path) -> Path:
    """A full build of the working tree into `out`; the app-ui files that don't exist yet are stubbed
    in a temporary copy of web/ (the real tree is not touched). server/ comes along because the
    build's lint resolves the app's test imports of the server package against the copy."""
    sys.path.insert(0, str(ROOT / "tools"))
    import build
    with tempfile.TemporaryDirectory(prefix="mutis-stub-") as tmp:
        web = Path(tmp) / "web"
        subprocess.run(["cp", "-r", str(ROOT / "web"), str(ROOT / "server"), tmp], check=True)
        for name, text in APP_STUBS.items():
            if not (web / "app" / name).exists():
                (web / "app" / name).write_text(text)
        cfg = build.load_config(ROOT / "deploy" / "config" / "mutis.toml.example")
        values = build.settings(cfg, f"http://127.0.0.1:{WEB_PORT}")
        build.build(web, out, Path(tmp) / "release", cfg, values, build.source_state(), holding=False)
    return out


class LocalStack:
    def __init__(self, host: str, dist: Path | None = None, buffered: bool = True):
        self.control = Path(tempfile.mkdtemp(prefix="mutis-stack-"))
        self.remote = Remote(host, self.control)
        self.host, self.dist, self.buffered = host, dist, buffered
        self.api = f"http://127.0.0.1:{API_PORT}"
        self.web = f"http://127.0.0.1:{WEB_PORT}"
        self.tunnel = None

    def _upload(self) -> bytes:
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as tar:
            tar.add(ROOT / "server", "server", filter=lambda t: None if "__pycache__" in t.name or "/tests" in t.name else t)
            caddyfile = local_caddyfile((ROOT / "deploy" / "caddy" / "Caddyfile").read_text(), self.buffered).encode()
            info = tarfile.TarInfo("Caddyfile")
            info.size = len(caddyfile)
            tar.addfile(info, io.BytesIO(caddyfile))
            if self.dist:
                tar.add(self.dist, "dist")
        return data.getvalue()

    def __enter__(self) -> "LocalStack":
        w = shlex.quote(WORK)
        self.remote.as_build(f"rm -rf {w} && mkdir -p {w}/status {w}/dist && tar -x -C {w}", self._upload())
        self.remote.as_build(
            f"cd {w} && (setsid python3 -I server/bin/mutis-api --dev --data {w}/data --port {API_PORT}"
            f" > api.log 2>&1 < /dev/null & echo $! > api.pid)"
            f" && (setsid caddy run --config Caddyfile --adapter caddyfile > caddy.log 2>&1 < /dev/null & echo $! > caddy.pid)")
        forwards = [a for p in (API_PORT, WEB_PORT, REDIRECT_PORT) for a in ("-L", f"{p}:127.0.0.1:{p}")]
        self.tunnel = subprocess.Popen(["ssh", "-o", "ControlPath=none", "-o", "ExitOnForwardFailure=yes", "-N",
                                        *forwards, self.host])
        deadline = time.monotonic() + 60
        while not (self._answers(self.api + "/api/v1/health") and self._answers(self.web + "/api/v1/health")):
            if time.monotonic() > deadline:
                logs = self.remote.as_build(f"tail -n 5 {w}/api.log {w}/caddy.log")
                self.__exit__()
                raise RuntimeError(f"the local stack did not come up:\n{logs}")
            time.sleep(1)
        return self

    @staticmethod
    def _answers(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=5) as res:
                return res.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def api_threads(self) -> int:
        status = self.remote.as_build(f"cat /proc/$(cat {WORK}/api.pid)/status")
        return int(re.search(r"^Threads:\s+(\d+)", status, re.M).group(1))

    def __exit__(self, *_exc) -> None:
        stop = f"cd {WORK} && kill $(cat api.pid caddy.pid) 2>/dev/null; sleep 1; cd /tmp && rm -rf {WORK}"
        self.remote.run(f"sudo -iu build bash -c {shlex.quote(stop)}", check=False)
        if self.tunnel:
            self.tunnel.terminate()
        subprocess.run(["ssh", "-o", f"ControlPath={self.control}/cm", "-O", "exit", self.host], capture_output=True)
