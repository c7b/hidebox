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
    "/p/AAAAAAAAAAAAAAAAAAAAAA": (APP_CSP, NOINDEX),  # the buyer page of a paid link
    "/d/7kq2x9mdh4": (APP_CSP, NOINDEX),
    "/send": (APP_CSP, NOINDEX),
    "/watch": (APP_CSP, NOINDEX),
    "/drive": (APP_CSP, NOINDEX),                       # the drive
    "/drive/storage": (APP_CSP, NOINDEX),               # the drive
    "/drive/received": (APP_CSP, NOINDEX),
    "/drive/activity": (APP_CSP, NOINDEX),
    "/verify/tx/" + "0" * 64: (APP_CSP, NOINDEX),
    "/app/drive.html": (APP_CSP, NOINDEX),              # the drive's own pages under their file names
    "/app/view.html": (APP_CSP, NOINDEX),
    "/v2": (APP_CSP, {"x-robots-tag": "noindex"}),      # the home with the product loops (docs/review/home-v2.md)
    "/v2/": (APP_CSP, {"x-robots-tag": "noindex"}),
    "/how": (SITE_CSP, {}),
    "/made": (SITE_CSP, {}),
    "/judges": (SITE_CSP, {}),
    "/fine-print": (SITE_CSP, {}),
    "/.well-known/security.txt": (SITE_CSP, {}),
    "/.well-known/mutis-manifest.json": (SITE_CSP, {}),
    "/this-page-does-not-exist": (SITE_CSP, {}),
}

# The pages the ghost folded together (14-ghost-design §4.1, §17 step 4): each old address answers 301
# to its new place, with or without a trailing slash. deploy/caddy/Caddyfile must say exactly this
# (deploy/tests/test_config.py), and every target page and anchor must exist (the site suite).
REDIRECTS = {
    "/security": "/made#locks",
    "/privacy": "/fine-print#privacy",
    "/terms": "/fine-print#terms",
    "/abuse": "/fine-print#report",
    "/pricing": "/made#limits",
    "/faq": "/made",
    "/status": "/made#check",
    # the drive replaced the locker (16-drive-design §12); these targets are the drive's own pages
    "/locker": "/drive",
    "/inbox": "/drive/received",
    "/upgrade": "/drive/storage#more",
    # /v3, the preview of the stills and the open box, became the home (docs/review/promote-v3.md)
    "/v3": "/",
}

# Caching (deploy/caddy/Caddyfile): pages, app files and status files revalidate on every visit; an
# error response is never stored. The one font served is the drive's Geist (DESIGN.md "Typography",
# pinned in tools/build.py); any other font path answers 404 like any missing file (MISSING below).
REVALIDATE = {"cache-control": "no-cache"}
# /v2's loops and the home's stills (media/v3): kept a day (their names carry no version), served with their types, in
# byte ranges.
MEDIA = {"/site/media/motion/hidebox-A-hero.webm": "video/webm", "/site/media/motion/hidebox-A-hero.mp4": "video/mp4",
         "/site/media/v3/hero-1024.avif": "image/avif", "/site/media/v3/hero-1024.webp": "image/webp"}
MEDIA_CACHE = {"cache-control": "public, max-age=86400"}
ERROR_CACHE = {"cache-control": "no-store"}
# The pages search engines may index: no route above without NOINDEX may send X-Robots-Tag (test_headers.py).
INDEXABLE = ("/", "/how", "/made", "/judges", "/fine-print")
# What other products show beside a link (docs/review/seo-1.md): the share cards and the icons, kept a day (their
# names carry no version) and loadable from any origin (a preview drawn from the page loads og:image cross-origin).
CARDS = {"/og.png": "image/png", "/og-s.png": "image/png", "/favicon.ico": "image/vnd.microsoft.icon",
         "/favicon.svg": "image/svg+xml", "/favicon-32.png": "image/png", "/apple-touch-icon.png": "image/png",
         "/icon-192.png": "image/png", "/icon-512.png": "image/png", "/icon-maskable-512.png": "image/png"}
CARD_HEADERS = {"cache-control": "public, max-age=86400", "cross-origin-resource-policy": "cross-origin"}
# robots.txt and the sitemap: their types, kept an hour.
CRAWL = {"/robots.txt": "text/plain; charset=utf-8", "/sitemap.xml": "application/xml; charset=utf-8"}
CRAWL_CACHE = {"cache-control": "public, max-age=3600"}
# Served from /srv/mutis/status when the timers have written them, a 404 page otherwise.
STATUS_FILES = ("/status.json", "/evidence.json", "/releases.json")
# Always 404, each through a different route of the Caddyfile (a nested error once leaked Server: Caddy),
# and the Spanish pages, which the site doesn't have.
MISSING = ("/evidence-archive-x.json", "/shared/fonts/x.woff2", "/shared/fonts/MutisScript-Regular.woff2", "/app/nope.js",
           "/es/", "/es/how")

