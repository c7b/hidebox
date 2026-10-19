#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A browser never renders a stored file as a page on this origin (docs/review/upload-safety-1.md).

  python3 -I tests/e2e/test_stored_bytes.py [--origin URL] [--host H]

The server can't tell ciphertext from a web page, so whatever bytes a client uploaded must reach a browser only
as a download. The canary is the one stored file anyone may fetch, and it comes through the same code as every
other stored file (handlers/blobs.py, ranged()). In headless Chromium on the server:

1. Opening its address in a tab starts a download and commits no document (the tab stays on about:blank).
2. The /made page's "Download the stored bytes" link downloads too, and the page stays where it was.
3. The browser's copy has the SHA-256 of the bytes fetched here directly: nothing on the way decoded or
   changed them.
4. A page of the origin can't frame it (X-Frame-Options and frame-ancestors).
"""
import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
from harness import REMOTE_DIR, SSH_HOST, Env, Remote  # noqa: E402

DOWNLOADS = f"{REMOTE_DIR}/downloads-stored-bytes"


def get(url: str) -> tuple[dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "mutis-e2e", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return {k.lower(): v for k, v in res.headers.items()}, res.read()


def downloaded(browser: cdp.Browser, timeout: float = 30) -> dict:
    """The next download the browser begins and finishes: its url, guid and final state."""
    began = browser.wait_event("Browser.downloadWillBegin", None, timeout)
    done = browser.wait_event("Browser.downloadProgress", None, timeout,
                              match=lambda p: p.get("guid") == began["guid"] and p.get("state") in ("completed", "canceled"))
    return {"url": began["url"], "guid": began["guid"], "state": done["state"]}


def main() -> int:
    p = argparse.ArgumentParser(description="stored bytes reach a browser only as a download")
    p.add_argument("--origin", default="https://hidebox.app")
    p.add_argument("--host", default=SSH_HOST)
    args = p.parse_args()
    origin = args.origin.rstrip("/")
    _, body = get(origin + "/api/v1/canary")
    raw_url = origin + json.loads(body)["raw"]
    headers, stored = get(raw_url)
    stored_sha = hashlib.sha256(stored).hexdigest()
    results = []

    env = Env(origin, Remote(args.host, Path(tempfile.mkdtemp(prefix="mutis-stored-"))), Path("."))
    env.remote.as_build(f"mkdir -p {REMOTE_DIR} && rm -rf {DOWNLOADS} && mkdir -p {DOWNLOADS}")
    env.remote.as_build(f"cat > {REMOTE_DIR}/relay.py", (Path(__file__).parent / "relay.py").read_bytes())
    browser = cdp.Browser(env.remote.browser_command(False))
    try:
        ctx = browser.context()
        ctx.downloads_to(DOWNLOADS)
        page = ctx.page("desktop")

        nav = page.cmd("Page.navigate", {"url": raw_url})
        got = downloaded(browser)
        where = page.eval("location.href")
        problems = [] if got["state"] == "completed" and got["url"] == raw_url else [f"download {got}"]
        if where != "about:blank":
            problems.append(f"a document was committed: the tab shows {where}")
        results.append((f"opening {raw_url[len(origin):]} in a tab downloads it and renders nothing "
                        f"(navigation: {nav.get('errorText', 'no error')})", problems))
        sha = env.remote.as_build(f"sha256sum {DOWNLOADS}/{got['guid']}").split()[0]
        results.append(("the browser's copy is byte for byte the stored file",
                        [] if sha == stored_sha else [f"sha256 {sha} != {stored_sha}"]))

        page.goto(origin + "/made")
        page.eval("document.querySelector('a[href=\"/api/v1/canary/raw\"]').click()")
        got = downloaded(browser)
        where = page.eval("location.pathname")
        problems = [] if got["state"] == "completed" else [f"download {got}"]
        if where != "/made":
            problems.append(f"the page navigated to {where}")
        results.append(("/made's \"Download the stored bytes\" link downloads, the page stays", problems))

        framed = page.eval("""new Promise(done => {
          const f = document.createElement('iframe');
          f.src = '/api/v1/canary/raw';
          f.onload = () => { let readable; try { readable = f.contentDocument !== null && f.contentDocument.URL; }
                             catch (e) { readable = false; } done(String(readable)); };
          setTimeout(() => done('no load event'), 8000);
          document.body.appendChild(f);
        })""", await_promise=True)
        page.collect()
        blocked = any("frame" in (e.get("text") or "").lower() for e in page.logs) or framed in ("false", "about:blank",
                                                                                                    "no load event")
        results.append((f"a page of the origin can't frame it ({framed})", [] if blocked else [f"framed: {framed}"]))
    finally:
        browser.close()
        env.remote.as_build(f"rm -rf {DOWNLOADS}")

    for key, want in (("content-type", "application/octet-stream"), ("x-content-type-options", "nosniff")):
        results.append((f"{key}: {headers.get(key)}", [] if headers.get(key) == want else [f"expected {want}"]))
    csp = headers.get("content-security-policy", "")
    results.append((f"content-security-policy ends in sandbox: {csp}", [] if csp.endswith("; sandbox") else ["no sandbox"]))

    failures = 0
    for name, problems in results:
        print(("PASS " if not problems else "FAIL ") + name + "".join(f"\n     {x}" for x in problems))
        failures += bool(problems)
    print(f"test_stored_bytes: {'PASS' if not failures else f'FAIL ({failures})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
