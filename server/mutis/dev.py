# SPDX-License-Identifier: MIT
"""`mutis-api --dev` (spec §3.6): the real API contract on http://127.0.0.1:8787 with fakes behind it.

A temporary data directory, small limits, a fake walletd, a fake indexer (fake mirror), the fake
sidecar, the chain worker and cleanup in threads, and (with --dist) the built site and app served
with the same rewrites and CSP headers Caddy uses. Fake chain outputs don't decrypt in a browser;
real chain flows are tested on staging.
"""
import json
import mimetypes
import os
import secrets
import threading
import time
from pathlib import Path

from . import api, cleanup, config, db
from .chain_worker import Worker
from .fake_chain import FAKE_WASM_SHA256, FakeChain, FakeIndexer, fake_keys
from .fake_sidecar import argv as fake_sidecar_argv
from .fake_walletd import FakeWalletd
from .http_util import Response
from .indexer import Indexers
from .sidecar import Sidecar
from .walletd import Walletd

SITE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            "object-src 'none'")
APP_CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; "
           "img-src 'self' blob: data:; media-src 'self' blob:; font-src 'self'; connect-src 'self' "
           "https://ootle-indexer-a.tari.com https://ootle-indexer-b.tari.com; manifest-src 'self'; base-uri 'none'; "
           "form-action 'self'; frame-ancestors 'none'; object-src 'none'; require-trusted-types-for 'script'; "
           "trusted-types mutis-url")
APP_ROUTES = ("/d/", "/locker", "/inbox", "/send", "/watch", "/upgrade", "/verify")
TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm",
         ".webmanifest": "application/manifest+json", ".woff2": "font/woff2", ".svg": "image/svg+xml"}


class Static:
    """The Caddy routes of spec §15.2 for a local dist/ directory."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _file(self, rel: str) -> Path | None:
        path = (self.root / rel.lstrip("/")).resolve()
        if path != self.root and self.root not in path.parents:
            return None
        if path.is_dir():
            path = path / "index.html"
        return path if path.is_file() else None

    def serve(self, req) -> Response:
        path = req.path
        csp, extra = SITE_CSP, {}
        if path == "/" or path.startswith(("/app/", "/vendor/")):
            csp = APP_CSP
            target = path
        elif path.startswith("/s/") or path == "/t":
            csp, extra, target = APP_CSP, {"X-Robots-Tag": "noindex, nofollow"}, "/app/view.html"
        elif path == "/drive" or path.startswith("/drive/"):   # lane app1: the drive's own page (16-drive-design §12)
            csp, extra, target = APP_CSP, {"X-Robots-Tag": "noindex, nofollow"}, "/app/drive.html"
        elif path.startswith(APP_ROUTES):
            csp, extra, target = APP_CSP, {"X-Robots-Tag": "noindex, nofollow"}, "/app/app.html"
        else:
            target = path
        file = self._file(target) if req.method == "GET" else None
        status = 200
        if file is None:
            file, status = self._file("/404.html"), 404
        body = file.read_bytes() if file else b"Not found"
        ctype = TYPES.get(file.suffix if file else "", None) or (mimetypes.guess_type(str(file))[0] if file else None)
        headers = {"Content-Type": ctype or "application/octet-stream", "Content-Security-Policy": csp,
                   "Referrer-Policy": "no-referrer", "Cross-Origin-Opener-Policy": "same-origin",
                   "Cross-Origin-Resource-Policy": "same-origin", "X-Frame-Options": "DENY",
                   "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
                                         "browsing-topics=()", "Cache-Control": "no-cache", **extra}
        return Response(status, body, headers)


def _write_keys(path: Path) -> str:
    keys = fake_keys()
    path.write_text(json.dumps(keys))
    os.chmod(path, 0o600)
    return str(path)


def dev_config(data: Path, port: int, walletd_url: str, indexer_url: str) -> config.Config:
    origin = f"http://127.0.0.1:{port}"
    mib = 1 << 20
    return config.from_dict({
        "public_origin": origin, "memo_origins": [origin, "https://mutis.sh"], "listen": f"127.0.0.1:{port}",
        "data_dir": str(data / "data"), "secret_key": str(data / "secret.key"),
        "gates": {"send_mode": "relay", "amount_proof": "sidecar", "key_bundle": False},
        "limits": {"reserve_min_bytes": 0, "small_lane_bytes": 256 * mib, "drop_lane_bytes": 256 * mib,
                   "anon_lane_max_bytes": 512 * mib},
        "budgets": {"public": {"courier": 50, "demo_pay_ut": 5_000_000, "sponsor_ut": 5_000_000},
                    "reserved": {"courier": 20, "decoy": 10, "demo_pay_ut": 2_000_000, "sponsor_ut": 2_000_000}},
        "ootle": {"walletd_url": walletd_url, "indexers": [indexer_url], "decoy_mean_gap_s": 600,
                  "receiver_keys": _write_keys(data / "receiver.json"), "robot_keys": _write_keys(data / "robot.json")},
        "sidecar": {"command": fake_sidecar_argv(), "expected_wasm_sha256": FAKE_WASM_SHA256, "canary_every_s": 600},
    }, dev=True)


def run(data: Path, dist: Path | None, port: int, pow_bits: int | None) -> None:
    data.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    (data / "secret.key").write_bytes(secret)
    chain = FakeChain()
    fake_indexer, fake_walletd = FakeIndexer(chain), FakeWalletd(chain)
    cfg = dev_config(data, port, fake_walletd.url, fake_indexer.url)
    db.migrate(cfg.db_path)
    app = api.App(cfg, secret, dev=True, pow_bits=pow_bits, static=Static(dist) if dist else None)
    stop = threading.Event()
    worker = Worker(cfg, secret, Walletd(cfg["ootle"]["walletd_url"]), Indexers(cfg["ootle"]["indexers"], rate=50),
                    Sidecar(cfg.sidecar_argv(), cfg.origin, FAKE_WASM_SHA256))

    def background() -> None:
        threading.Thread(target=worker.run, args=(stop,), daemon=True).start()

        def sweep() -> None:
            conn = db.connect(cfg.db_path)
            while not stop.wait(60):
                cleanup.run(conn, cfg, app.blobs, os.statvfs, int(time.time()))

        threading.Thread(target=sweep, daemon=True).start()
        print(f"mutis dev: {cfg.origin}  data: {data}  dist: {dist or '(none)'}", flush=True)

    try:
        api.serve(app, "127.0.0.1", port, on_ready=background)
    finally:
        stop.set()
