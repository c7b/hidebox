# SPDX-License-Identifier: MIT
"""UX feedback screenshots (docs/review/ux-feedback-1.md), as `build` on the server, from a copy of the repository:

  python3 -I docs/evidence/2026-10-18/ux-feedback-1/shots_ux.py --out DIR [--only 1440,390] [--frames]

The UI suite's own harness (web/app/ui/tests/run.py: the build, the real API on a dev server with its fake chain,
headless Chromium) walks the drop page as a stranger at 1440 and at 390: the steps while the file uploads, while
our relay waits to send it, while the chain takes it, the failure with Try again, Delivered, and the receipt's page
(/verify/tx: the summary, then Details), and Send by Tari in the share dialog (Queued, then Sent). Each state is shot in light and in dark (data-theme). To hold a state long
enough for its pictures, the page's fetch is wrapped in the test browser only: a chunk upload waits, or a job reads
queued, sending or failed, until the next state is asked for; the product code is unchanged. --frames also shoots
the sending → delivered moment frame by frame (every ~80 ms, light, 1440). WebP, `<state>-<width>-<theme>.webp`.
Python stdlib only.
"""
import argparse
import os
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
import flows  # noqa: E402

DEVICES = {1440: "desktop", 390: "iphone"}

# Test browser only: holds the drop page in one state while it is pictured (window.__ux_mode).
GATE = r"""(() => {
  if (window.__ux_gate) return;
  window.__ux_gate = true;
  window.__ux_mode = sessionStorage.getItem('ux_mode');
  const real = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = String(input instanceof Request ? input.url : input);
    const method = String(init.method || 'GET').toUpperCase();
    if (method === 'PUT' && /\/chunks\/\d+$/.test(url)) {
      while (window.__ux_mode === 'hold-upload') await new Promise((r) => setTimeout(r, 100));
    }
    if (/\/api\/v1\/chain\/tx\//.test(url)) {
      while (window.__ux_mode === 'hold-tx') await new Promise((r) => setTimeout(r, 100));
    }
    if (/\/api\/v1\/jobs\//.test(url) && /^job-/.test(window.__ux_mode || '')) {
      const res = await real(input, init);
      const body = await res.json();
      const state = window.__ux_mode.slice(4);
      const fake = { ...body, state, result: null, error: state === 'failed' ? 'walletd_failed' : null };
      return new Response(JSON.stringify(fake), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return real(input, init);
  };
})()"""


def theme(page, which):
    page.eval(f"document.documentElement.dataset.theme = {which!r}")
    time.sleep(0.3)


def both(out, page, name, width, full=False):
    for th in ("light", "dark"):
        theme(page, th)
        page.screenshot(os.path.join(out, f"{name}-{width}-{th}.webp"), full_page=full)
        print(f"  shot {name}-{width}-{th}", flush=True)
    theme(page, "light")


def mode(page, value):
    v = "null" if value is None else repr(value)
    page.eval(f"window.__ux_mode = {v}; {v} === null ? sessionStorage.removeItem('ux_mode') : sessionStorage.setItem('ux_mode', {v})")


def walk(t, out, width, frames):
    device = DEVICES[width]
    a, drop, _ = flows.owner_with_drop(t, device="desktop")
    b = t.actor(device)
    b.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": GATE})
    b.goto(drop)
    b.wait_state("dd-root", ("ready",), 60)
    mode(b, "hold-upload")
    b.set_files("dd-input", [t.fixture("photo-gps.jpg")])
    b.wait("document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"upload\"]')?.dataset.state === 'now'", 60)
    b.eval("document.querySelector('[data-testid=\"dd-steps\"]').scrollIntoView({ block: 'center' })")
    time.sleep(2.4)                     # the step's clock shows from 2 s
    both(out, b, "drop-upload", width)
    mode(b, "job-queued")
    b.wait("document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"chain\"] .step-note')?.textContent.includes('relay')", 60)
    time.sleep(2.2)
    both(out, b, "drop-relay", width)
    mode(b, "job-sending")
    b.wait("document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"chain\"] .step-note')?.textContent.includes('few seconds')", 60)
    both(out, b, "drop-chain", width)
    mode(b, "job-failed")
    b.wait_state("dd-root", ("error",), 60)
    both(out, b, "drop-failed", width)
    mode(b, None)
    b.eval("[...document.querySelectorAll('[data-testid=\"dd-root\"] button')].find((x) => x.textContent === 'Try again').click()")
    if frames:
        mode(b, "job-sending")
        b.wait("document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"chain\"] .step-note')?.textContent.includes('few seconds')", 120)
        fdir = os.path.join(out, f"frames-{width}")
        os.makedirs(fdir, exist_ok=True)
        mode(b, None)
        shots, started = 0, time.monotonic()
        seen_done = None
        while time.monotonic() - started < 120:
            state = b.attr("dd-root", "data-state")
            if state == "delivered" and seen_done is None:
                seen_done = time.monotonic()
            if seen_done is not None or b.eval("!!document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"chain\"][data-state=\"done\"]')"):
                b.screenshot(os.path.join(fdir, f"f{shots:02d}-{int((time.monotonic() - started) * 1000):06d}ms.webp"))
                shots += 1
            if seen_done is not None and time.monotonic() - seen_done > 1.6:
                break
            time.sleep(0.05)
        print(f"  frames: {shots}", flush=True)
    b.wait_state("dd-root", ("delivered",), 180)
    time.sleep(1.4)
    both(out, b, "drop-delivered", width)
    both(out, b, "drop-delivered-full", width, full=True)
    mode(b, "hold-tx")
    b.click("dd-chain-link")
    b.wait("!!document.querySelector('[data-testid=\"tx-loading\"]')", 60)
    b.wait("document.querySelector('[data-testid=\"tx-loading\"] .step-note')?.textContent.length > 0", 30)
    both(out, b, "verify-loading", width)
    mode(b, None)
    b.wait("!!document.querySelector('[data-testid=\"tx-summary\"], [data-testid=\"error-banner\"]')", 90)
    time.sleep(1.4)
    both(out, b, "verify", width)
    both(out, b, "verify-full", width, full=True)


def walk_tari(t, out, width):
    """Send by Tari in the share dialog: the same steps (held on Queued, then on the chain), then Sent."""
    import flows_drive
    import flows_share
    device = DEVICES[width]
    b = flows_share.drive_page(t, device="desktop")
    address = b.wait("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]'); return e && e.textContent.startsWith('otl_esm_1') ? e.textContent : ''; })()", 90)
    a = flows_share.drive_page(t, device=device)
    a.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": GATE})
    a.reload()
    a.wait_for("drive-root", 90)
    flows_drive.upload_files(t, a, ["for-them.txt"])
    flows_share.open_share(a, "for-them.txt")
    a.click("share-choice", "tari")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'tari'", 10)
    a.fill("send-recipient", address)
    a.wait_for("send-safety", 60)
    mode(a, "job-queued")
    a.click("send-submit")
    a.wait("(document.querySelector('#share-dialog .flow li[data-step=\"waiting\"] .step-note')?.textContent || '').includes('relay')", 90)
    time.sleep(2.2)
    both(out, a, "tari-queued", width)
    mode(a, None)
    a.wait_state("send-status", ("delivered", "failed"), 180)
    time.sleep(1.4)
    both(out, a, "tari-sent", width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="1440,390")
    ap.add_argument("--frames", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    r = run.Results()
    work = tempfile.mkdtemp(prefix="mutis-ux-shots-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    port = run.free_port()
    dist = run.build(work, f"http://127.0.0.1:{port}")
    server = run.serve(dist, os.path.join(work, "data"), port)
    port2 = run.free_port()   # the drive's folders are a feature the default dev server keeps off
    server2 = run.serve(dist, os.path.join(work, "data-sidecar-folders"), port2, None, ("folders",))
    run.make_fixtures(os.path.join(work, "fixtures"))
    try:
        for width in [int(w) for w in args.only.split(",")]:
            browser = Browser()
            t = run.T(r, browser, f"http://127.0.0.1:{port}", work, None)
            try:
                walk(t, args.out, width, args.frames and width == 1440)
                t.origin = f"http://127.0.0.1:{port2}"
                walk_tari(t, args.out, width)
            finally:
                t.close()
                browser.close()
    finally:
        for proc in (server, server2):
            proc.terminate()
            proc.wait(10)
        shutil.rmtree(work, ignore_errors=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
