# SPDX-License-Identifier: MIT
"""owner-5, /verify/tx: what "Tari's own indexer" can link to, checked with real transaction ids.

  python3 -I docs/evidence/2026-10-19/owner-5/indexer-link/probe.py [--host HOST] TX_ID ...

For each id: the public indexers' JSON endpoints (status, type, CORS header, the outcome they say), then the indexer's
own web page for the transaction in headless Chromium on the server (tests/e2e/relay.py, as the unprivileged user):
its rendered words and a screenshot (<id prefix>-page.png next to this file). Python stdlib only.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "tests" / "e2e"))
import cdp  # noqa: E402
import harness  # noqa: E402

API = ("https://ootle-indexer-a.tari.com", "https://ootle-indexer-b.tari.com")
PAGE = "https://indexer.esme.tari.com/transactions/{}"


def api(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "hidebox-owner-5-probe"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body, status, headers = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        body, status, headers = e.read(), e.code, e.headers
    try:
        doc = json.loads(body)
    except ValueError:
        doc = None
    outcome = (doc or {}).get("receipt", {}).get("outcome") if isinstance(doc, dict) else None
    return {"url": url, "status": status, "type": headers.get("content-type"), "cors": headers.get("access-control-allow-origin"),
            "outcome": outcome}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=harness.SSH_HOST)
    p.add_argument("tx", nargs="+")
    args = p.parse_args()
    out = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "transactions": []}
    control = Path(os.environ.get("TMPDIR", "/tmp")) / f"owner5-{os.getpid()}"
    control.mkdir(parents=True, exist_ok=True)
    remote = harness.Remote(args.host, control)
    browser = cdp.Browser(remote.browser_command(False))
    try:
        page = browser.context().page("desktop")
        for tx in args.tx:
            row = {"tx": tx, "api": [api(f"{base}/{path}{tx}") for base in API for path in ("transaction-receipts/", "transactions/")]}
            page.goto(PAGE.format(tx))
            time.sleep(6)                       # the page is drawn in the browser from the indexer's JSON
            row["page"] = PAGE.format(tx)
            row["page_text"] = " ".join(page.eval("document.body.innerText").split())[:600]
            page.screenshot(str(HERE / f"{tx[:12]}-page.png"))
            out["transactions"].append(row)
    finally:
        browser.close()
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
