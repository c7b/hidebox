# SPDX-License-Identifier: MIT
"""mutis-api: a ThreadingHTTPServer bound to loopback behind Caddy (spec §8.1 implementation notes).

Nothing from a request is ever logged: the stock request/error logging of http.server is
replaced, and failures are reported only as fixed event codes through logsafe.
"""
import ipaddress
import os
import signal
import sqlite3
import threading
import time
import traceback
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from . import auth, codec, config, db, logsafe
from .http_util import HEADERS_MAX, ApiError, Request, Response, error_response
from .indexer import Indexers
from .ipkeys import IpKeys, client_ip
from .pow import Pow, PowError
from .ratelimit import DayCounts, Limiter, Recent
from .router import ROUTER
from .storage import Blobs

API_PREFIX = "/api/v1/"
FEATURE_CACHE_S = 2
DRAIN_MAX = 8 * 1024 * 1024       # an early error still reads a body this small, so the client sees the answer
MEMORY_CAP = 200_000              # entries in each in-memory table
IN_FLIGHT_64 = 32                 # requests in progress per IPv6 /64 or IPv4 address (a browser uses about 6)
IN_FLIGHT_48 = 128                # per IPv6 /48 or IPv4 /24


class InFlight:
    """Counts requests in progress, in all (SIGTERM lets them finish, up to 20 s) and per network, so slow
    downloads from one network can't hold every API thread."""

    def __init__(self):
        self._cond = threading.Condition()
        self.count = 0
        self._per: dict[bytes, int] = {}

    def acquire_slot(self, caps: tuple[tuple[bytes, int], ...]) -> bool:
        """Count a request against each (network key, cap); False, counting nothing, when one is full."""
        with self._cond:
            if any(self._per.get(key, 0) >= cap for key, cap in caps):
                return False
            self.count += 1
            for key, _ in caps:
                self._per[key] = self._per.get(key, 0) + 1
            return True

    def release_slot(self, caps: tuple[tuple[bytes, int], ...]) -> None:
        with self._cond:
            self.count -= 1
            for key, _ in caps:
                if self._per[key] > 1:
                    self._per[key] -= 1
                else:
                    del self._per[key]
            self._cond.notify_all()

    def wait_idle(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self.count and time.monotonic() < deadline:
                self._cond.wait(deadline - time.monotonic())


class App:
    """Process-wide state: configuration, keys, in-memory counters and caches."""

    def __init__(self, cfg: config.Config, secret: bytes, dev: bool = False, pow_bits: int | None = None,
                 static=None):
        self.cfg = cfg
        self.dev = dev
        self.k_pow = codec.hkdf(secret, b"mutis/v1", b"pow", 32)
        self.canary_token = codec.hkdf(secret, b"mutis/v1", b"canary", 32)
        self.limiter = Limiter()
        self.pow = Pow(self.k_pow, pow_bits)
        self.ipkeys = IpKeys(on_rotate=self._new_day)
        self.blobs = Blobs(cfg.blob_dir)
        self.indexers = Indexers(cfg["ootle"]["indexers"])
        self.statvfs = os.statvfs
        self.clock = codec.now
        self.static = static
        self.git_sha = _git_sha()
        self.pw_tries = Recent(MEMORY_CAP)       # (share id, ip64) → (wrong passwords today, last try)
        self.small_held = Recent(MEMORY_CAP)     # ip48 → {item id: SMALL-lane bytes it holds}
        self.daily = DayCounts(MEMORY_CAP)       # the daily brakes (drives, drive uploads, packs) per network
        self.exempt_nets = tuple(ipaddress.ip_network(a, strict=False) for a in cfg["brakes"]["exempt_addresses"])
        self.cache: dict = {}
        self.inflight = InFlight()
        self._features = (0.0, {})

    def _new_day(self) -> None:
        self.limiter.clear()
        self.pow.reset()
        self.pw_tries.clear()
        self.small_held.clear()
        self.daily.clear()

    def exempt(self, ip_text: str) -> bool:
        """The server's own addresses (brakes.exempt_addresses) skip the per-network daily brakes."""
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            return False
        return any(ip.version == net.version and ip in net for net in self.exempt_nets)

    def connect(self) -> sqlite3.Connection:
        return db.connect(self.cfg.db_path)

    def features(self, conn: sqlite3.Connection) -> dict:
        stamp, cached = self._features
        if time.monotonic() - stamp < FEATURE_CACHE_S:
            return cached
        merged = dict(self.cfg["features"])
        merged.update({k: v for k, v in db.get_meta_json(conn, "features", {}).items() if k in merged})
        self._features = (time.monotonic(), merged)
        return merged

    def cached(self, key: str, ttl: int, make):
        now = time.monotonic()
        hit = self.cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = make()
        if value is None:           # nothing found yet (a transaction the indexers haven't seen): ask again next time
            return None
        if len(self.cache) > 5000:
            self.cache.clear()
        self.cache[key] = (now, value)
        return value


def _git_sha() -> str:
    path = Path(__file__).resolve().parent.parent / "GIT_SHA"
    try:
        return path.read_text().strip() or "dev"
    except OSError:
        return "dev"


class Ctx:
    """Everything a handler needs for one request."""

    def __init__(self, app: App, req: Request, now: int):
        self.app, self.req, self.now = app, req, now
        self.cfg = app.cfg
        self.ip64, self.ip48 = app.ipkeys.keys(req.ip, now)
        self._db: sqlite3.Connection | None = None
        self._identity = None

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = self.app.connect()
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()

    def features(self) -> dict:
        return self.app.features(self.db)

    def require_feature(self, name: str) -> None:
        if not self.features()[name]:
            raise ApiError(503, "feature_disabled", "This feature is off right now.", details={"feature": name})

    def limit(self, *rules, message: str = "Too many requests. Try again shortly.") -> None:
        wait = self.app.limiter.hit(list(rules), self.now)
        if wait:
            raise ApiError(429, "rate_limited", message, retry_after=wait)

    @contextmanager
    def charged(self, *rules, message: str = "Too many requests. Try again shortly."):
        """Charge rate-limit rules for a block, and give them back if the block refuses the request."""
        self.limit(*rules, message=message)
        try:
            yield
        except ApiError:
            for rule in rules:
                self.app.limiter.refund(rule, self.now)
            raise

    @contextmanager
    def daily(self, *rules, code: str, message: str):
        """Charge per-UTC-day brakes (name, key, limit, cost) for a block: 429 `code` until midnight UTC when
        one is used up, and give them back if the block refuses the request."""
        if not self.app.daily.take(rules):
            raise ApiError(429, code, message, retry_after=max(1, codec.next_utc_midnight(self.now) - self.now))
        try:
            yield
        except ApiError:
            self.app.daily.give_back(rules)
            raise

    def exempt(self) -> bool:
        return self.app.exempt(self.req.ip)

    def session(self, required: bool = True) -> sqlite3.Row | None:
        if self._identity is None:
            token = auth.bearer(self.req.header("Authorization"))
            if token is None:
                if required:
                    raise ApiError(401, "auth_required", "This needs a locker session.")
                return None
            self._identity = auth.resolve(self.db, token, self.now)
        return self._identity

    def manage_token(self) -> bytes | None:
        value = self.req.header("X-Mutis-Manage")
        if value is None:
            return None
        try:
            return codec.unb64u(value, 32)
        except ValueError:
            raise ApiError(403, "forbidden", "Not allowed.") from None

    def is_canary(self) -> bool:
        value = self.req.header("X-Mutis-Canary")
        if value is None:
            return False
        try:
            token = codec.unb64u(value, 32)
        except ValueError:
            raise ApiError(403, "forbidden", "Not allowed.") from None
        if not codec.equal(token, self.app.canary_token):
            raise ApiError(403, "forbidden", "Not allowed.")
        return True

    def judge(self) -> str | None:
        """The X-Mutis-Judge code (P-12) when it names a live pass, None without the header, else 403.

        A pass stands in for proof of work, using one of its PoW skips each time. Budgeted sends
        (courier, demo-pay, sponsor) draw from the evidence slice and spend one of its uses together
        with the job they queue (`spend_judge`), so a refused send costs the pass nothing.
        """
        code = self.req.header("X-Mutis-Judge")
        if code is None:
            return None
        if len(code) > 64 or not auth.judge_pass_live(self.db, code, self.now):
            raise _judge_refused()
        return code

    def judge_soft(self) -> str | None:
        """The X-Mutis-Judge code when it names a live pass, else None (never a 403): for the brakes a pass
        widens (uploads, packs), where an old pass in a browser must not break the request."""
        code = self.req.header("X-Mutis-Judge")
        if code is None or len(code) > 64 or not auth.judge_pass_live(self.db, code, self.now):
            return None
        return code

    def spend_judge(self, code: str) -> None:
        """Inside the transaction that queues a budgeted send."""
        if not auth.spend_judge_use(self.db, code, self.now):
            raise _judge_refused()

    def proof_of_work(self, purpose: str, body: dict, min_difficulty: int = 0, budgeted: bool = False) -> str | None:
        """Require a PoW solution for `purpose`, or a judge pass. Returns the pass code when one was used."""
        code = self.judge()
        if code is not None:
            if not budgeted and not auth.skip_pow(self.db, code, self.now):
                raise _judge_refused()
            return code
        try:
            self.app.pow.verify(self.db, body.get("pow"), purpose, self.ip64, self.now, min_difficulty)
        except PowError as e:
            message = "Solve a fresh proof of work." if e.code == "pow_required" else "That proof of work isn't valid."
            raise ApiError(428, e.code, message, details={"purpose": purpose, "difficulty": e.difficulty}) from None
        return None


def _judge_refused() -> ApiError:
    return ApiError(403, "forbidden", "This judge pass is unknown or used up.", details={"judge": "invalid"})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60

    # http.server would print the client address and request line; we print nothing from requests.
    def log_message(self, format, *args):
        pass

    def log_error(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        status = code if code in (400, 413, 414, 431, 501, 505) else 400
        self._write(Response(status, b'{"error":{"code":"bad_request","message":"Malformed request."}}',
                             {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}))

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self.send_error(501)

    def do_POST(self):
        self._serve()

    def do_PUT(self):
        self._serve()

    def do_PATCH(self):
        self._serve()

    def do_DELETE(self):
        self._serve()

    def _serve(self) -> None:
        app = self.server.app
        started = time.monotonic()
        url = urlsplit(self.path)
        route_name = "unknown"
        req = Request(self.command, url.path, dict(parse_qsl(url.query)), self.headers, self.rfile,
                      client_ip(self.client_address[0], self.headers.get("X-Real-IP")))
        ctx = Ctx(app, req, app.clock())
        caps = ((ctx.ip64, IN_FLIGHT_64), (ctx.ip48, IN_FLIGHT_48))
        counted = app.inflight.acquire_slot(caps)
        try:
            if not counted:
                raise ApiError(429, "rate_limited", "Too many requests at once from your network. Try again shortly.",
                               retry_after=1)
            if not url.path.startswith(API_PREFIX) and app.static is not None:
                route_name = "static"
                resp = app.static.serve(req)
            else:
                route, params = ROUTER.match(self.command, url.path)
                route_name = route.name if route else "unknown"
                resp = self._dispatch(ctx, route, params)
        except ApiError as e:
            resp = error_response(e)
        except Exception:
            logsafe.event("api.internal_error", "error")
            if app.dev:
                traceback.print_exc()
            resp = error_response(ApiError(500, "internal", "Something went wrong on our side."))
        finally:
            ctx.close()
        if not req.body_read and req.content_length:
            self._drain(req)
        try:
            self._write(resp)
        except OSError:
            logsafe.event("api.connection_error")
        finally:
            if counted:
                app.inflight.release_slot(caps)
        logsafe.request(route_name, resp.status, int((time.monotonic() - started) * 1000))

    def _drain(self, req: Request) -> None:
        """Discard an unread body; a large one closes the connection instead (it would corrupt the next request)."""
        if 0 < req.content_length <= DRAIN_MAX and not req.headers.get("Transfer-Encoding"):
            try:
                for _ in req.body_slices(req.content_length):
                    pass
                return
            except (ApiError, OSError):
                pass
        self.close_connection = True

    def _dispatch(self, ctx: Ctx, route, params) -> Response:
        if route is None:
            raise ApiError(404, "not_found", "No such endpoint.")
        if sum(len(k) + len(v) + 4 for k, v in self.headers.items()) > HEADERS_MAX:
            raise ApiError(400, "bad_request", "Headers too large.")
        ctx.limit(("any64", ctx.ip64, 600, 60, 1), ("any48", ctx.ip48, 3000, 60, 1))
        if self.command != "GET":
            origin = ctx.req.header("Origin")
            if origin is not None and origin != ctx.cfg.origin:
                raise ApiError(403, "bad_origin", "Cross-origin request refused.")
        return route.handler(ctx, **params)

    def _write(self, resp: Response) -> None:
        self.send_response_only(resp.status)
        headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", **resp.headers}
        length = resp.length if resp.stream is not None else len(resp.body)
        headers["Content-Length"] = str(length)
        if self.close_connection:
            headers["Connection"] = "close"
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if resp.stream is not None:
            for data in resp.stream():
                self.wfile.write(data)
        elif resp.body:
            self.wfile.write(resp.body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128          # the default backlog of 5 drops bursts of new connections

    def __init__(self, address, app: App):
        self.app = app
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        logsafe.event("api.connection_error")


def make_server(app: App, host: str, port: int) -> Server:
    if host != "127.0.0.1":
        raise config.ConfigError("mutis-api binds to loopback only")
    return Server((host, port), app)


def serve(app: App, host: str, port: int, on_ready=None) -> None:
    """Serve until SIGTERM/SIGINT, then let in-flight requests finish for up to 20 s."""
    server = make_server(app, host, port)

    def on_term(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    logsafe.event("api.start")
    if on_ready:
        on_ready()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        app.inflight.wait_idle(20)
        server.server_close()
        logsafe.event("api.stop")

