# SPDX-License-Identifier: MIT
"""The response headers of spec §14.2, copied verbatim from the spec (not from the Caddyfile, so a
typo there fails the tests). Used by test_headers.py (D-01) and the deploy smoke test."""

COMMON = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
}

SITE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            "object-src 'none'; upgrade-insecure-requests")

APP_CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; "
           "img-src 'self' blob: data:; media-src 'self' blob:; font-src 'self'; "
           "connect-src 'self' https://ootle-indexer-a.tari.com https://ootle-indexer-b.tari.com; manifest-src 'self'; "
           "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; "
           "require-trusted-types-for 'script'; trusted-types mutis-url; upgrade-insecure-requests")

ABSENT = ("server", "x-powered-by", "access-control-allow-origin")

# Path → (CSP, extra headers that must be present). App pages are noindex (spec §13.3, §15.2).
NOINDEX = {"x-robots-tag": "noindex, nofollow"}
ROUTES = {
    "/": (APP_CSP, {}),
    "/s/AAAAAAAAAAAAAAAAAAAAAA": (APP_CSP, NOINDEX),
    "/t": (APP_CSP, NOINDEX),
    "/d/7kq2x9mdh4": (APP_CSP, NOINDEX),
    "/locker": (APP_CSP, NOINDEX),
    "/inbox": (APP_CSP, NOINDEX),
    "/send": (APP_CSP, NOINDEX),
    "/watch": (APP_CSP, NOINDEX),
    "/upgrade": (APP_CSP, NOINDEX),
    "/verify/tx/" + "0" * 64: (APP_CSP, NOINDEX),
    "/how": (SITE_CSP, {}),
    "/security": (SITE_CSP, {}),
    "/pricing": (SITE_CSP, {}),
    "/faq": (SITE_CSP, {}),
    "/judges": (SITE_CSP, {}),
    "/terms": (SITE_CSP, {}),
    "/privacy": (SITE_CSP, {}),
    "/abuse": (SITE_CSP, {}),
    "/robots.txt": (SITE_CSP, {}),
    "/.well-known/security.txt": (SITE_CSP, {}),
    "/.well-known/mutis-manifest.json": (SITE_CSP, {}),
    "/this-page-does-not-exist": (SITE_CSP, {}),
}

# Caching (deploy/caddy/Caddyfile): pages, app files and status files revalidate on every visit; an
# error response is never stored. No font is served (DESIGN.md: system faces only); the fonts route
# answers 404 like any missing file (MISSING below).
REVALIDATE = {"cache-control": "no-cache"}
ERROR_CACHE = {"cache-control": "no-store"}
# Served from /srv/mutis/status when the timers have written them, a 404 page otherwise.
STATUS_FILES = ("/status.json", "/evidence.json", "/releases.json")
# Always 404, each through a different route of the Caddyfile (a nested error once leaked Server: Caddy),
# and the Spanish pages the site no longer has (removed 2026-10-12).
MISSING = ("/evidence-archive-x.json", "/shared/fonts/x.woff2", "/shared/fonts/MutisScript-Regular.woff2", "/app/nope.js",
           "/es/", "/es/how")

