#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""D-01: HTTPS, the spec §14.2 headers and per-route CSPs, exactly. Python stdlib only; runs anywhere.

  python3 -I tests/e2e/test_headers.py --origin https://hidebox.app [--holding]
                                       [--redirect-from old.host …]
  python3 -I tests/e2e/test_headers.py --local SSH_HOST   the production Caddyfile on a throwaway
                                                         stack (localstack.py) with a full build

For every route in headers_spec.ROUTES: the common headers with their exact values, no Server or
X-Powered-By or CORS header, the route's CSP (an error page always carries the site policy) and its
caching (pages revalidate, errors are never stored); private routes carry X-Robots-Tag: noindex, and no
other route does (the indexable pages never send it). The share cards and icons are kept a day and may be
loaded from any origin; robots.txt and the sitemap have their types and are kept an hour; every API
answer is noindex and carries the API's sandbox policy, and the stored bytes come back as an
application/octet-stream attachment (never something a browser would render). The same for the status files, a font, and a
404 through every other route of the Caddyfile. Also: a 6 MB upload chunk is refused with a 413 in
the API's error shape (never a bare 502), plain HTTP answers a 308 to HTTPS with no Server header, a
made-up Host name gets a 421 with the same headers on both ports (never a redirect to that name), the
certificate verifies and has more than 14 days left, .wasm is served as application/wasm, /v2's loops and the
home's stills with their types in byte ranges, kept a day, and each --redirect-from host answers 308 to the same path on the origin (browsers carry
the #fragment across it). --holding accepts 404 for pages that the holding build doesn't have.
Fingerprinted files (headers_spec.HASHED, looked up in the live manifest's "assets"): their plain name's type, a year
and immutable, the policy of their folder; a hashed name no build made is the 404 page. Precompressed text
(PRECOMPRESSED_*): br when the browser takes it, gzip that decodes to the file when it takes only gzip, the file
itself otherwise, each with Vary: Accept-Encoding.
A header sent twice counts as its values joined, so a header both Caddy and the API set fails.
--local runs everything but the certificate on the server's private copy of the stack: every route
of the table answers there, app pages included (the app-ui files are stubbed if they don't exist).
"""
import argparse
import datetime
import gzip
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


def fetch(url: str, method: str = "GET", host: str | None = None, body: bytes = b"", encoding: str = "identity",
          limit: int | None = 1 << 16) -> tuple[int, dict, bytes]:
    """`host` replaces the Host header (the misdirected-request checks). A body is sent after the
    headers and may be cut short by the server (a 413 arrives before it is read). `encoding` is the
    Accept-Encoding sent; `limit` how much of the body is read (None: all of it)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=20, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=20)
    try:
        conn.putrequest(method, (u.path or "/") + (f"?{u.query}" if u.query else ""), skip_host=host is not None,
                        skip_accept_encoding=True)
        for name, value in {"User-Agent": "mutis-test-headers", "Accept-Encoding": encoding,
                            **({"Host": host} if host else {}), **({"Content-Length": str(len(body))} if body else {})}.items():
            conn.putheader(name, value)
        conn.endheaders()
        try:
            conn.send(body)
        except OSError:
            pass    # the server answered and closed before the body was through
        res = conn.getresponse()
        data = res.read() if limit is None else res.read(limit)
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
        which = {headers_spec.APP_CSP: "app", headers_spec.API_CSP: "API"}.get(csp, "site")
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
            if "x-robots-tag" not in extra and "x-robots-tag" in headers:
                problems.append(f"x-robots-tag {headers['x-robots-tag']!r} on a route that may be indexed")
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
    results.append((f"GET /api/v1/health → {status} (security headers on API responses, noindex, the API's sandbox)",
                    header_problems(headers, headers_spec.API_CSP, headers_spec.NOINDEX)))
    # Stored bytes (docs/review/upload-safety-1.md): the canary is the one stored file anyone may fetch.
    status, headers, data = fetch(origin + "/api/v1/canary/raw")
    problems = header_problems(headers, headers_spec.API_CSP, headers_spec.NOINDEX)
    if status == 200:
        if headers.get("content-type") != "application/octet-stream":
            problems.append(f"content-type {headers.get('content-type')!r}")
        if not headers.get("content-disposition", "").startswith("attachment;"):
            problems.append(f"content-disposition {headers.get('content-disposition')!r}")
        if "content-encoding" in headers:
            problems.append(f"content-encoding {headers['content-encoding']!r} on stored bytes")
    elif status != 404:
        problems.append(f"status {status}")
    results.append((f"GET /api/v1/canary/raw → {status} (stored bytes: an octet-stream attachment, nosniff, the sandbox)",
                    problems))
    status, headers, _ = fetch(origin + "/api/v1/blobs/" + "A" * 43)
    problems = ([] if status == 404 else [f"status {status}"]) + header_problems(headers, headers_spec.API_CSP, headers_spec.NOINDEX)
    results.append((f"GET /api/v1/blobs/<unknown ticket> → {status} (the download route's answer carries the sandbox)", problems))

    if not holding:
        for path, ctype in headers_spec.MEDIA.items():
            status, headers, _ = fetch(origin + path, "HEAD")
            problems = ([] if status == 200 and headers.get("content-type") == ctype and headers.get("accept-ranges") == "bytes"
                        else [f"status {status}, content-type {headers.get('content-type')!r}, accept-ranges {headers.get('accept-ranges')!r}"])
            problems += header_problems(headers, headers_spec.SITE_CSP, headers_spec.MEDIA_CACHE)
            results.append((f"HEAD {path} is {ctype}, in byte ranges, kept a day", problems))
        for path, ctype in headers_spec.CARDS.items():
            status, headers, _ = fetch(origin + path, "HEAD")
            problems = [] if status == 200 and headers.get("content-type") == ctype else \
                [f"status {status}, content-type {headers.get('content-type')!r}"]
            problems += header_problems(headers, headers_spec.SITE_CSP, headers_spec.CARD_HEADERS)
            results.append((f"HEAD {path} is {ctype}, kept a day, loadable from any origin (a link preview's card or icon)", problems))
        for path, ctype in headers_spec.CRAWL.items():
            status, headers, body = fetch(origin + path)
            problems = [] if status == 200 and headers.get("content-type") == ctype else \
                [f"status {status}, content-type {headers.get('content-type')!r}"]
            problems += header_problems(headers, headers_spec.SITE_CSP, headers_spec.CRAWL_CACHE)
            if "x-robots-tag" in headers:
                problems.append("x-robots-tag on a file crawlers must read")
            if path == "/robots.txt" and f"Sitemap: {origin}/sitemap.xml".encode() not in body:
                problems.append("no Sitemap line naming this origin")
            if path == "/sitemap.xml" and f"<loc>{origin}/</loc>".encode() not in body:
                problems.append("the home is not in the sitemap")
            results.append((f"GET {path} is {ctype}, kept an hour", problems))
        status, headers, _ = fetch(origin + WASM, "HEAD")
        problems = [] if status == 200 and headers.get("content-type") == "application/wasm" else \
            [f"status {status}, content-type {headers.get('content-type')!r}"]
        results.append((f"HEAD {WASM} is application/wasm", problems))
        results += fingerprinted(origin)

    oversized = b"\0" * (6 << 20)
    status, headers, data = fetch(origin + "/api/v1/uploads/AAAAAAAAAAAAAAAAAAAAAA/chunks/0", "PUT", body=oversized)
    problems = [] if status == 413 else [f"status {status}"]
    problems += header_problems(headers, headers_spec.API_CSP, headers_spec.ERROR_CACHE)
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


def encoded(origin: str, path: str) -> list[str]:
    """The same address asked for with br, with gzip alone and with neither: the encodings and Vary, and the gzip
    body decoding to the plain one."""
    url = origin + path
    answers = {enc: fetch(url, encoding=enc, limit=None) for enc in ("identity", "gzip", "br, gzip")}
    plain_status, plain_headers, plain = answers["identity"]
    problems = []
    if len({status for status, _, _ in answers.values()}) != 1:
        problems.append(f"statuses {[status for status, _, _ in answers.values()]}")
    if "content-encoding" in plain_headers:
        problems.append(f"Accept-Encoding: identity answered {plain_headers['content-encoding']!r}")
    for enc, want in (("gzip", "gzip"), ("br, gzip", "br")):
        _, headers, data = answers[enc]
        if headers.get("content-encoding") != want:
            problems.append(f"Accept-Encoding: {enc} answered content-encoding {headers.get('content-encoding')!r}, not {want}")
        if "accept-encoding" not in headers.get("vary", "").lower():
            problems.append(f"Accept-Encoding: {enc}: no Vary: Accept-Encoding ({headers.get('vary')!r})")
        if want == "gzip" and headers.get("content-encoding") == "gzip":
            try:
                if gzip.decompress(data) != plain:
                    problems.append("the gzip copy decodes to other bytes than the file")
            except (OSError, EOFError) as e:
                problems.append(f"the gzip copy doesn't decode ({e})")
        if want == "br" and headers.get("content-encoding") == "br" and not 0 < len(data) < len(plain):
            problems.append(f"the br copy is {len(data)} B for a {len(plain)} B file")
    return problems


def fingerprinted(origin: str) -> list[tuple[str, list[str]]]:
    """headers_spec.HASHED, HASHED_MISSING and PRECOMPRESSED_*: the hashed names from the live manifest."""
    results = []
    status, _, body = fetch(origin + "/.well-known/mutis-manifest.json", limit=None)
    try:
        names = json.loads(body).get("assets", {}) if status == 200 else {}
    except ValueError:
        names = {}
    for plain in headers_spec.HASHED:
        hashed = names.get(plain)
        if not hashed:
            results.append((f"/{plain} has a fingerprinted name in the live manifest", ["no entry in its \"assets\""]))
            continue
        _, plain_headers, _ = fetch(f"{origin}/{plain}", "HEAD")
        status, headers, _ = fetch(f"{origin}/{hashed}", "HEAD")
        app = hashed.startswith(("app/", "vendor/"))
        problems = [] if status == 200 and headers.get("content-type") == plain_headers.get("content-type") else \
            [f"status {status}, content-type {headers.get('content-type')!r} (the plain name's: {plain_headers.get('content-type')!r})"]
        problems += header_problems(headers, headers_spec.APP_CSP if app else headers_spec.SITE_CSP,
                                    headers_spec.IMMUTABLE | (headers_spec.NOINDEX if app else {}))
        if not app and "x-robots-tag" in headers:
            problems.append(f"x-robots-tag {headers['x-robots-tag']!r} on a site file")
        results.append((f"HEAD /{hashed}: {headers.get('content-type')}, kept a year, immutable, the "
                        f"{'app' if app else 'site'} policy", problems))
    for path in headers_spec.HASHED_MISSING:
        status, headers, _ = fetch(origin + path)
        problems = ([] if status == 404 else [f"status {status}"]) + \
            header_problems(headers, headers_spec.SITE_CSP, headers_spec.ERROR_CACHE)
        results.append((f"GET {path} → {status} (a hashed name no build made: the 404 page, never stored)", problems))
    for path in ["/" + names.get(p, p) for p in headers_spec.PRECOMPRESSED_ASSETS] + list(headers_spec.PRECOMPRESSED_PAGES):
        results.append((f"GET {path}: br, gzip or the file, as the browser accepts (Vary: Accept-Encoding)",
                        encoded(origin, path)))
    return results


def main() -> int:
    p = argparse.ArgumentParser(description="D-01 headers test")
    p.add_argument("--origin", default="https://hidebox.app")
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
