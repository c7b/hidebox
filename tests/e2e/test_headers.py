#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""D-01: HTTPS, the spec §14.2 headers and per-route CSPs, exactly. Python stdlib only; runs anywhere.

  python3 -I tests/e2e/test_headers.py --origin https://srv2052606.hstgr.cloud [--holding]
                                       [--redirect-from old.host …]
  python3 -I tests/e2e/test_headers.py --local ultron     the production Caddyfile on a throwaway
                                                         stack (localstack.py) with a full build

For every route in headers_spec.ROUTES: the common headers with their exact values, no Server or
X-Powered-By or CORS header, the route's CSP (an error page always carries the site policy) and its
caching (pages revalidate, errors are never stored). The same for the status files, a font, and a
404 through every other route of the Caddyfile. Also: a 6 MB upload chunk is refused with a 413 in
the API's error shape (never a bare 502), plain HTTP answers a 308 to HTTPS with no Server header, a
made-up Host name gets a 421 with the same headers on both ports (never a redirect to that name), the
certificate verifies and has more than 14 days left, .wasm is served as application/wasm, /v2's loops as video in
byte ranges, kept a day, and each --redirect-from host answers 308 to the same path on the origin (browsers carry
the #fragment across it). --holding accepts 404 for pages that the holding build doesn't have.
A header sent twice counts as its values joined, so a header both Caddy and the API set fails.
--local runs everything but the certificate on the server's private copy of the stack: every route
of the table answers there, app pages included (the app-ui files are stubbed if they don't exist).
"""
import argparse
import datetime
import http.client
import json
import socket
import ssl
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import headers_spec  # noqa: E402

WASM = "/app/vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm"


def fetch(url: str, method: str = "GET", host: str | None = None, body: bytes = b"") -> tuple[int, dict, bytes]:
    """`host` replaces the Host header (the misdirected-request checks). A body is sent after the
    headers and may be cut short by the server (a 413 arrives before it is read)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=20, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=20)
    try:
        conn.putrequest(method, (u.path or "/") + (f"?{u.query}" if u.query else ""), skip_host=host is not None)
        for name, value in {"User-Agent": "mutis-test-headers", "Accept-Encoding": "identity",
                            **({"Host": host} if host else {}), **({"Content-Length": str(len(body))} if body else {})}.items():
            conn.putheader(name, value)
        conn.endheaders()
        try:
            conn.send(body)
        except OSError:
            pass    # the server answered and closed before the body was through
        res = conn.getresponse()
        data = res.read(1 << 16)
        headers = {}
        for k, v in res.getheaders():
            headers[k.lower()] = f"{headers[k.lower()]}, {v}" if k.lower() in headers else v
        return res.status, headers, data
    finally:
        conn.close()


def cert_days_left(host: str) -> float:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=20) as raw, ctx.wrap_socket(raw, server_hostname=host) as tls:
        not_after = tls.getpeercert()["notAfter"]
    expires = datetime.datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), datetime.UTC)
    return (expires - datetime.datetime.now(datetime.UTC)).total_seconds() / 86400


def header_problems(headers: dict, csp: str, extra: dict) -> list[str]:
    problems = [f"{k}: {headers.get(k)!r}" for k, v in (headers_spec.COMMON | extra).items() if headers.get(k) != v]
    problems += [f"unexpected {k}" for k in headers_spec.ABSENT if k in headers]
    if headers.get("content-security-policy") != csp:
        which = "app" if csp == headers_spec.APP_CSP else "site"
        problems.append(f"CSP is not the {which} policy: {headers.get('content-security-policy')!r}")
    return problems


def run(origin: str, holding: bool, redirect_from: list[str], plain_http: str | None = None) -> list[tuple[str, list[str]]]:
    """`plain_http`: where the HTTP→HTTPS redirect answers, when not on port 80 of the origin's host
    (the local stack); the certificate is then not checked."""
    results = []
    error = (headers_spec.SITE_CSP, headers_spec.ERROR_CACHE)
    for path, (csp, extra) in headers_spec.ROUTES.items():
        status, headers, _ = fetch(origin + path)
        missing_route = path == "/this-page-does-not-exist"
        if missing_route or status == 404:
            expected_ok = missing_route or holding
            problems = [] if expected_ok else [f"status {status}"]
            problems += header_problems(headers, *error)
        else:
            problems = [] if status == 200 else [f"status {status}"]
            problems += header_problems(headers, csp, extra | headers_spec.REVALIDATE)
        results.append((f"GET {path} → {status}", problems))

    for old, new in headers_spec.REDIRECTS.items():
        for path in (old, old + "/"):
            status, headers, data = fetch(origin + path)
            problems = [] if status == 301 and headers.get("location") == new else [f"status {status}, location {headers.get('location')!r}"]
            problems += [f"missing {k}" for k, v in headers_spec.COMMON.items() if headers.get(k) != v]
            problems += [f"unexpected {k}" for k in headers_spec.ABSENT if k in headers]
            results.append((f"GET {path} → {status} {headers.get('location')} (an old page, folded into a new one)", problems))

    for path in headers_spec.STATUS_FILES:
        status, headers, _ = fetch(origin + path)
        expected = (headers_spec.SITE_CSP, headers_spec.REVALIDATE) if status == 200 else error
        problems = ([] if status in (200, 404) else [f"status {status}"]) + header_problems(headers, *expected)
        results.append((f"GET {path} → {status}", problems))
    for path in headers_spec.MISSING:
        status, headers, _ = fetch(origin + path)
        problems = ([] if status == 404 else [f"status {status}"]) + header_problems(headers, *error)
        results.append((f"GET {path} → {status} (an error page through another route)", problems))

    status, headers, _ = fetch(origin + "/api/v1/health")
    results.append((f"GET /api/v1/health → {status} (security headers on API responses)",
                    header_problems(headers, headers_spec.SITE_CSP, {})))

    if not holding:
        for path, ctype in headers_spec.MEDIA.items():
            status, headers, _ = fetch(origin + path, "HEAD")
            problems = ([] if status == 200 and headers.get("content-type") == ctype and headers.get("accept-ranges") == "bytes"
                        else [f"status {status}, content-type {headers.get('content-type')!r}, accept-ranges {headers.get('accept-ranges')!r}"])
            problems += header_problems(headers, headers_spec.SITE_CSP, headers_spec.MEDIA_CACHE)
            results.append((f"HEAD {path} is {ctype}, in byte ranges, kept a day", problems))
        status, headers, _ = fetch(origin + WASM, "HEAD")
        problems = [] if status == 200 and headers.get("content-type") == "application/wasm" else \
            [f"status {status}, content-type {headers.get('content-type')!r}"]
        results.append((f"HEAD {WASM} is application/wasm", problems))

    oversized = b"\0" * (6 << 20)
    status, headers, data = fetch(origin + "/api/v1/uploads/AAAAAAAAAAAAAAAAAAAAAA/chunks/0", "PUT", body=oversized)
    problems = [] if status == 413 else [f"status {status}"]
    problems += header_problems(headers, headers_spec.SITE_CSP, headers_spec.ERROR_CACHE)
    try:
        err = json.loads(data)["error"]
        if (err["code"], err["details"]["max_bytes"]) != ("too_large", 5 << 20):
            problems.append(f"error body {err!r}")
    except (ValueError, KeyError, TypeError):
        problems.append(f"not the API's error shape: {data[:80]!r}")
    results.append((f"PUT 6 MB to /api/v1/uploads/…/chunks/0 → {status} (413 in the API's error shape, not a bare 502)", problems))

    for method in ("TRACE", "PUT"):
        status, headers, data = fetch(origin + "/how", method)
        problems = ([] if status == 405 and headers.get("allow") == "GET, HEAD" else [f"status {status}, allow {headers.get('allow')!r}"])
        problems += header_problems(headers, headers_spec.SITE_CSP, headers_spec.ERROR_CACHE)
        if b"<" in data:
            problems.append("a page body came back")
        results.append((f"{method} /how → {status} (405 with Allow: GET, HEAD, the headers, no body)", problems))

    host = urllib.parse.urlsplit(origin).hostname
    status, headers, _ = fetch(f"{plain_http or 'http://' + host}/how?x=1")
    ok = status == 308 and headers.get("location") == f"https://{host}/how?x=1"
    problems = ([] if ok else ["expected 308 to https"]) + [f"unexpected {k}" for k in headers_spec.ABSENT if k in headers]
    results.append((f"{plain_http or 'http://' + host}/how?x=1 → {status} {headers.get('location')}", problems))

    for base in (origin, plain_http or "http://" + host):
        status, headers, _ = fetch(base + "/how", host="not-this-site.example")
        problems = ([] if status == 421 else [f"status {status}"]) + header_problems(headers, *error)
        if "not-this-site" in headers.get("location", ""):
            problems.append("the made-up host is reflected in a redirect")
        results.append((f"{base}/how with Host: not-this-site.example → {status} (421, the security headers, nothing reflected)", problems))

    if not plain_http:
        days = cert_days_left(host)
        results.append((f"certificate for {host} verifies, {days:.0f} days left", [] if days > 14 else ["expires within 14 days"]))

    for old in redirect_from:
        status, headers, _ = fetch(f"https://{old}/s/AAAAAAAAAAAAAAAAAAAAAA")
        ok = status == 308 and headers.get("location") == origin + "/s/AAAAAAAAAAAAAAAAAAAAAA"
        results.append((f"https://{old}/s/… → {status} {headers.get('location')}", [] if ok else ["expected 308 to the origin"]))
    return results


def main() -> int:
    p = argparse.ArgumentParser(description="D-01 headers test")
    p.add_argument("--origin", default="https://srv2052606.hstgr.cloud")
    p.add_argument("--holding", action="store_true", help="the holding build is live: pages may be 404")
    p.add_argument("--redirect-from", action="append", default=[], metavar="HOST")
    p.add_argument("--local", metavar="SSH_HOST", help="test the Caddyfile on a throwaway stack on this server")
    args = p.parse_args()
    if args.local:
        import tempfile
        from localstack import REDIRECT_PORT, LocalStack, stub_build
        with tempfile.TemporaryDirectory(prefix="mutis-headers-") as tmp, \
                LocalStack(args.local, stub_build(Path(tmp) / "dist")) as stack:
            results = run(stack.web, False, [], f"http://127.0.0.1:{REDIRECT_PORT}")
    else:
        results = run(args.origin.rstrip("/"), args.holding, args.redirect_from)
    failures = 0
    for name, problems in results:
        print(("PASS " if not problems else "FAIL ") + name + "".join(f"\n     {x}" for x in problems))
        failures += bool(problems)
    print(f"test_headers: {'PASS' if not failures else f'FAIL ({failures})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
