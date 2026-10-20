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

# The API's answers (its JSON and the stored bytes it serves as attachments) are data, never pages: a sandbox
# with nothing allowed (docs/review/upload-safety-1.md). Stricter than the site policy the API had before.
API_CSP = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"

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
    "/drive/earnings": (APP_CSP, NOINDEX),
    "/drive/activity": (APP_CSP, NOINDEX),
    "/verify/tx/" + "0" * 64: (APP_CSP, NOINDEX),
    "/app/drive.html": (APP_CSP, NOINDEX),              # the drive's own pages under their file names
    "/app/view.html": (APP_CSP, NOINDEX),
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
    # /v3, the preview of the stills and the open box, became the home (docs/review/promote-v3.md); /v2, the preview
    # with the product loops before it, left with its loops (docs/review/perf-1.md)
    "/v3": "/",
    "/v2": "/",
}

# Caching (deploy/caddy/Caddyfile): pages, app files and status files revalidate on every visit; an
# error response is never stored. The one font served is the drive's Geist (DESIGN.md "Typography",
# pinned in tools/build.py); any other font path answers 404 like any missing file (MISSING below).
REVALIDATE = {"cache-control": "no-cache"}
# The home's stills (media/v3) and the 404 page's art (media/404) under their plain names: kept a day (those names carry
# no version), served with their types, in byte ranges. The pages ask for the fingerprinted names (HASHED below).
MEDIA = {"/site/media/v3/hero-1024.avif": "image/avif", "/site/media/v3/hero-1024.webp": "image/webp",
         "/site/media/404/box-zero-480.avif": "image/avif"}
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
# Fingerprinted files (tools/assets.py; the Caddyfile's @hashed and @hashed_app): every asset a page asks for, under a
# name with a hash of its bytes, kept a year. test_headers.py looks up each plain name below in the live manifest's
# "assets" and checks the hashed address: 200, the plain name's type, a year and immutable, the folder's policy
# (the app's under /app/, with noindex), the security headers. One of each kind the pages load.
IMMUTABLE = {"cache-control": "public, max-age=31536000, immutable"}
HASHED = ("shared/tokens.css", "site/css/site.css", "site/js/site.js", "shared/theme.js", "app/drop-widget.js",
          "app/css/widget.css", "app/lib/pow-worker.js", "app/i18n/widget-en.json", "shared/ui/icons.svg",
          "shared/fonts/geist/Geist-Latin.woff2", "site/media/v3/hero-480.avif", "site/media/v3/hero-480.webp",
          "site/media/404/box-zero-480.avif", "favicon-32.png", "icon-512.png",
          "app/vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm")
# A hashed name that no build made: the 404 page, never stored, through both hashed routes.
HASHED_MISSING = ("/site/css/site.0000000000.css", "/app/ui/app.0000000000.js")
# The text a browser gets compressed from the .br and .gz copies the build and the activation make
# (deploy/scripts/precompress.py): with Accept-Encoding br, Content-Encoding br; with gzip alone, gzip that decodes
# to the file's bytes; with neither, the file. Each with Vary: Accept-Encoding. A hashed asset of each text type, and
# pages (whose names never change: they keep revalidating, compressed the same way).
PRECOMPRESSED_ASSETS = ("site/css/site.css", "site/js/site.js", "shared/ui/icons.svg", "app/i18n/en.json",
                        "app/vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm")
PRECOMPRESSED_PAGES = ("/", "/how", "/manifest.webmanifest", "/this-page-does-not-exist")
# Served from /srv/mutis/status when the timers have written them, a 404 page otherwise.
STATUS_FILES = ("/status.json", "/evidence.json", "/releases.json")
# Always 404, each through a different route of the Caddyfile (a nested error once leaked Server: Caddy),
# and the Spanish pages, which the site doesn't have.
MISSING = ("/evidence-archive-x.json", "/shared/fonts/x.woff2", "/shared/fonts/MutisScript-Regular.woff2", "/app/nope.js",
           "/es/", "/es/how")

