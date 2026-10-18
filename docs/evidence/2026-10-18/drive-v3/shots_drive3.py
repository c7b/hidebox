# SPDX-License-Identifier: MIT
"""Drive v3 screenshots (docs/review/drive-v3.md), as `build` on the server, from a copy of the repository:

  python3 -I docs/evidence/2026-10-18/drive-v3/shots_drive3.py --out DIR [--only 1440,390]

The UI suite's own harness (web/app/ui/tests/run.py: the build, the real API on a dev server with folders and pay
to open on, headless Chromium) walks one drive per width through the states the owner looks at, and shoots each
in light and in dark (the drive's theme switch, data-theme): the start screen (no drive yet), Open my drive, the
empty drive, the drive with files (a folder, a Once link, a Pay link, a private file), one file picked (computer;
a phone has no picking column, so its row menu instead), the share dialog's three steps, Save my key, and the pay
page a buyer sees (waiting, then open), and the link page a stranger sees for a Once link (before opening it). WebP, `<state>-<width>-<theme>.webp`. Python stdlib only.
"""
import argparse
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TESTS = ROOT / "web/app/ui/tests"
sys.path.insert(0, str(TESTS))
os.chdir(ROOT)
import run  # noqa: E402
from cdp import Browser  # noqa: E402
import flows  # noqa: E402,F401
import flows_drive  # noqa: E402,F401
import flows_share  # noqa: E402
import flows_pay  # noqa: E402

DEVICES = {1440: "desktop", 390: "iphone"}


def theme(page, which):
    page.eval(f"document.documentElement.dataset.theme = {which!r}")
    time.sleep(0.45)
    page.settle()


def both(out, page, name, width, full=False):
    for th in ("light", "dark"):
        theme(page, th)
        page.screenshot(os.path.join(out, f"{name}-{width}-{th}.webp"), full_page=full)
        print(f"  shot {name}-{width}-{th}", flush=True)
    theme(page, "light")


def walk(t, out, width):
    device = DEVICES[width]
    s = t.actor(device)
    s.goto(t.origin + "/drive")
    s.wait_for("drive-start", 60)
    both(out, s, "start", width)
    s.click("drive-open")
    s.wait("document.querySelector('[data-testid=\"open-dialog\"]')?.dataset.state === 'open'", 10)
    both(out, s, "open", width)

    fake = flows_pay.PayFake(t)
    a = t.actor(device)
    a.goto(t.origin + "/drive")
    a.wait("!!document.querySelector('script')", 30)
    fake.watch = a.eval("import('/app/lib/ootle.js').then((m) => m.newRandomKeys()).then((k) => k.address)")
    flows_pay.attach(t, fake, a)
    a.goto(t.origin + "/drive?make")
    a.wait_for("drive-root", 90)
    a.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    con = flows_pay.db(t)
    con.execute("UPDATE identities SET distinct_days = 2")
    con.commit()
    con.close()
    a.reload()
    a.wait_for("drive-empty", 90)
    both(out, a, "empty", width)

    flows_drive.upload_files(t, a, ["notes.txt", "agenda.txt", "song.txt"])
    a.eval("document.querySelector('[data-testid=\"upload-panel\"] .uploads-head .btn')?.click()")
    flows_share.new_folder(a, "trip-photos")
    flows_share.open_share(a, "notes.txt")
    flows_share.to_opens(a)
    once = flows_share.make_link(a)
    flows_share.close_dialog(a)
    url = flows_pay.sell(a, "song.txt")
    sid = re.search(flows_pay.PAY_LINK, url)[1]
    fake.links[sid]["seller_state"] = "ok"
    flows_pay.close_dialog(a)
    a.wait("document.querySelectorAll('[data-testid=\"file-row\"] [data-rule]').length >= 3", 30)
    try:   # the pay link reads Getting ready until the server has its half; then its badge says the price
        flows_pay.wait_badge(a, "song.txt", "Pay 0.1 tTARI", 45)
    except TimeoutError:
        a.reload()
        a.wait_for("drive-root", 60)
        a.wait("document.querySelectorAll('[data-testid=\"file-row\"] [data-rule]').length >= 3", 30)
    a.eval("scrollTo(0, 0)")
    both(out, a, "files", width)

    if width >= 768:
        a.eval("[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === 'agenda.txt').querySelector('.checkbox').click()")
        a.wait("!document.querySelector('[data-testid=\"selbar\"]').hidden", 10)
        both(out, a, "picked", width)
        a.click("sel-share")
    else:
        a.eval("""[...document.querySelectorAll('[data-testid="file-row"]')].find((e) => e.dataset.name === 'agenda.txt')
          .querySelector('[data-testid="row-kebab"]').click()""")
        a.wait("!document.getElementById('row-menu').hidden", 10)
        both(out, a, "menu", width)
        a.click("menu-share")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    both(out, a, "share-who", width)
    flows_share.to_opens(a)
    both(out, a, "share-opens", width)
    flows_share.make_link(a)
    both(out, a, "share-result", width)
    flows_share.close_dialog(a)

    a.click("key-reminder-save")
    a.wait("document.querySelector('[data-testid=\"key-dialog\"]')?.hidden === false", 10)
    both(out, a, "key", width)
    a.key("Escape")

    v, _ = flows_share.stranger(t, once, device)
    both(out, v, "link", width)

    b = flows_pay.buyer(t, fake, url, device)
    both(out, b, "pay", width)
    b.click("pay-test")
    flows_pay.wait_pay(b, ("open",), 90)
    both(out, b, "pay-open", width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="1440,390")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    r = run.Results()
    work = tempfile.mkdtemp(prefix="drive-v3-shots-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    port = run.free_port()
    dist = run.build(work, f"http://127.0.0.1:{port}")
    name = "data-sidecar-" + "-".join(flows_pay.FEATURES)
    proc = run.serve(dist, os.path.join(work, name), port, None, flows_pay.FEATURES)
    run.make_fixtures(os.path.join(work, "fixtures"))
    try:
        for width in [int(w) for w in args.only.split(",")]:
            r.current = f"shots-{width}"
            browser = Browser(())
            t = run.T(r, browser, f"http://127.0.0.1:{port}", work, None)
            try:
                walk(t, out, width)
                r.check(not t.violations(), f"{width}: no CSP or Trusted Types violation ({t.violations()[:2]})")
            finally:
                t.close()
                browser.close()
    finally:
        proc.terminate()
        proc.wait(10)
        shutil.rmtree(work, ignore_errors=True)
    print(f"shots {'PASS' if not r.failed else 'FAIL'} {r.passed}/{r.passed + len(r.failed)}")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
