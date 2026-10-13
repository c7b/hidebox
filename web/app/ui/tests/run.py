#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The app-ui test run, one command (on ultron as `build`, from a copy of the repository):

  python3 -I web/app/ui/tests/run.py [--only ID ...] [--shots] [--keep]

1. Static checks: repository lint and copy checks for web/app, both dictionaries complete, every
   string the UI asks for exists, the data-testid contract of spec §3.4.9 present in the sources.
2. Builds dist/ with tools/build.py (dev origin) into a fresh directory under /var/tmp.
3. Starts `server/bin/mutis-api --dev` on it: the real API, fakes for the chain (and, for the flows
   that ask for production's payment mode, a second one through ui/tests/devserver.py).
4. Drives headless Chromium through every flow in flows.py; with --shots also writes the curated
   screenshots to web/app/shots/.
Prints one PASS/FAIL line per check and a summary; exits 1 on any failure. Python stdlib only.
"""
import argparse
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser, Page  # noqa: E402
from realize import Realizer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.dirname(HERE)
APP = os.path.dirname(UI)
ROOT = os.path.abspath(os.path.join(APP, "..", ".."))

TESTIDS = """drop-input drop-write drop-textarea drop-seal-text seal-progress exif-chip sealed-link copy-link who when
views-input expiry-preset password-input password-mode apply-rules known-toggle known-panel delete-drop error-banner
view-root view-password view-password-submit view-open view-text view-image view-video view-audio view-filename view-save
view-save-anyway view-known view-views-left view-chain-saw locker-root locker-safety locker-address copy-address
key-save-file key-pm-save key-saved-check key-later key-banner restore-text restore-submit forget-device delete-locker
export-view-key view-key-value watch-mine quota-bar drop-create drop-label drop-link drop-copy drop-close dd-root dd-label
dd-safety dd-input dd-tx dd-chain-link inbox-root inbox-item inbox-empty inbox-scan send-recipient send-safety send-kind
send-submit send-status send-tx watch-address watch-viewkey watch-run watch-summary watch-row pack- invoice-address
invoice-status pay-browser demo-pay pay-step tx-root tx-output tx-fee card-change card-send-address noise-canvas""".split()
# P-15 (accepted in 12-integration §2): no copy button for the key, so `key-copy` is not built.
WAIVED_TESTIDS = {"key-copy"}

# Key families the UI builds at run time (t(`prefix.${x}`)).
DYNAMIC = {
    "dur": ["minute", "hour", "day"],
    "send.step": ["sealing", "waiting", "sending", "delivered"],
    "send.path": ["direct", "relay", "refused"],
    "upgrade.status": ["pending", "seen", "credited", "underpaid", "expired"],
    "upgrade.step": ["waiting", "seen", "proven", "added", "seen_wallet", "exists"],
    "upgrade.short": ["_pending", "_refused"],
    "watch.kind": ["payment", "sealed_file", "file_link"],
    "chain.amount": ["_hidden", "_viewable", "_lower", "_unknown"],
    "known.never": ["name", "contents", "key", "password", "email", "ip", "browser"],
    "nav": ["locker", "inbox", "send"],
    "rules": ["pw_too_short", "pw_common", "pw_pattern", "pw_fair", "pw_strong"],
    "gone": ["burned", "expired", "revoked", "removed"],
    # lane app1: the drive's families (ui/drive*.js)
    "drive.side": ["mine", "received", "shared", "activity", "trash", "storage"],
    "drive.theme": ["light", "dark", "system"],
    "drive.sto.kind": ["media", "docs", "other", "trash"],
    "drive.error": ["quota_exceeded", "probation_limit", "too_large_locker", "auth_required", "bad_auth"],
}


class Results:
    def __init__(self):
        self.passed, self.failed, self.current = 0, [], ""

    def check(self, ok, what):
        print(f"{'PASS' if ok else 'FAIL'} {self.current}: {what}", flush=True)
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{self.current}: {what}")
        return ok


# --- static checks -----------------------------------------------------------------------------------

def static_checks(r):
    r.current = "static"
    for cmd in (["tools/lint.py", "--only", "web/app"], ["tools/check-copy.py", "--quiet"], ["web/app/i18n/subset.py", "--check"]):
        res = subprocess.run([sys.executable, "-I", *cmd], cwd=ROOT, capture_output=True, text=True)
        r.check(res.returncode == 0, f"{cmd[0]}: {res.stdout.strip().splitlines()[-1] if res.stdout.strip() else res.stderr[-200:]}")
    en = json.load(open(os.path.join(APP, "i18n", "en.json"), encoding="utf-8"))
    used = set()
    sources = {}
    for name in sorted(os.listdir(UI)):
        if name.endswith(".js"):
            sources[name] = open(os.path.join(UI, name), encoding="utf-8").read()
    for text in sources.values():
        used.update(re.findall(r"\bt\(\s*'([a-z0-9_.]+)'", text))
        used.update(re.findall(r"(?:setTitle\(|(?<!\w)key:\s*|simple\('[a-z-]+',\s*)'([a-z0-9_.]+)'", text))
        used.update(k for k in re.findall(r"'([a-z_]+\.[a-z0-9_.]+)'", text) if k in en)
    known = re.search(r"const KNOWN = new Set\(`([^`]*)`", sources["errors.js"]).group(1).split()
    used.update(f"error.{code}" for code in known)
    used.add("error.details")
    for prefix, rest in DYNAMIC.items():
        used.update(f"{prefix}{'' if r_.startswith('_') else '.'}{r_}" for r_ in rest)
    for who in ("link", "password", "password_only"):
        for count in ("once", "n", "unlimited"):
            used.update({f"rules.sentence.{who}.{count}", f"rules.sentence.{who}.{count}_kept"})
    missing = sorted(k for k in used if k not in en)
    unused = sorted(k for k in en if k not in used)
    r.check(not missing, f"every string the UI asks for exists ({missing[:8]})")
    r.check(not unused, f"no string in the dictionaries goes unused ({unused[:8]})")
    # lib/preview.js sets view-text, view-image, view-video and view-audio as `view-${kind}`.
    preview = open(os.path.join(APP, "lib", "preview.js"), encoding="utf-8").read()
    code = "".join(sources.values())
    if "'data-testid': `view-${kind}`" in preview:
        code += " 'view-text 'view-image 'view-video 'view-audio"
    absent = [i for i in TESTIDS if f"'{i}" not in code and f'"{i}' not in code and f"`{i}" not in code]
    r.check(not absent, f"every data-testid of spec §3.4.9 is in the UI ({len(TESTIDS)} ids; missing {absent})")


# --- build and serve ---------------------------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build(out, origin):
    res = subprocess.run([sys.executable, "-I", "tools/build.py", "--origin", origin,
                          "--source", "0000000", "ui-test", str(int(time.time())),
                          "--out", os.path.join(out, "dist"), "--release", os.path.join(out, "release")],
                         cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"build failed:\n{res.stdout}\n{res.stderr}")
    return os.path.join(out, "dist")


def serve(dist, data, port, amount_proof=None):
    os.makedirs(data, exist_ok=True)
    log = open(os.path.join(data, "server.log"), "w")
    cmd = ["server/bin/mutis-api", "--dev"] if amount_proof is None else ["web/app/ui/tests/devserver.py", "--amount-proof", amount_proof]
    proc = subprocess.Popen([sys.executable, "-I", *cmd, "--data", os.path.join(data, "srv"),
                             "--dist", dist, "--port", str(port), "--pow-bits", "8"], cwd=ROOT, stdout=log, stderr=log)
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as res:
                if res.status == 200:
                    return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("the dev server didn't start")


ACTORS = itertools.count(1)  # every actor in the run gets its own client address


class T:
    """What a flow gets: the origin, actors, the realizer, fixtures, checks and screenshots."""

    def __init__(self, results, browser, origin, work, shots):
        self.r, self.browser, self.origin, self.work, self.shots = results, browser, origin, work, shots
        self.realizer = Realizer(origin)
        self.pages, self.shared = [], {}

    def check(self, ok, what):
        return self.r.check(ok, what)

    def actor(self, device="desktop", **kw):
        n = next(ACTORS)
        page = Page(self.browser, device, downloads=os.path.join(self.work, "downloads", str(n)),
                    client_ip=f"10.{n // 250 % 250 + 1}.{n % 250 + 1}.7", **kw)
        self.pages.append(page)
        return page

    def fixture(self, name):
        return os.path.join(self.work, "fixtures", name)

    def shot(self, page, name, full_page=False):
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            page.settle()
            page.screenshot(os.path.join(self.shots, f"{name}.webp"), full_page=full_page)

    def violations(self):
        out = []
        for p in self.pages:
            try:
                out += p.csp_violations()
            except Exception:  # a closed context has nothing to report
                pass
        return out

    def close(self):
        for p in self.pages:
            try:
                p.close()
            except Exception:
                pass
        self.pages = []


def make_fixtures(folder):
    os.makedirs(folder, exist_ok=True)
    exif = os.path.join(APP, "tests", "fixtures", "exif")
    shutil.copy(os.path.join(exif, "jpeg-gps.jpg"), os.path.join(folder, "photo-gps.jpg"))
    with open(os.path.join(folder, "setup.exe"), "wb") as f:
        f.write(b"MZ" + bytes(4094))
    with open(os.path.join(folder, "too-big.bin"), "wb") as f:
        f.truncate(26 * 1024 * 1024 + 1)
    with open(os.path.join(folder, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("Meeting notes. The office key is under the plant.\n")
    with open(os.path.join(folder, "report.dat"), "wb") as f:
        f.write(os.urandom(1_500_000))
    # Program names that only show once invisible or forbidden characters are gone (P-14).
    for name in ("invoice.b\u200bat", "run.p|s1"):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write("@echo off\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--shots", action="store_true", help="write the curated screenshots to web/app/shots/")
    ap.add_argument("--keep", action="store_true", help="keep the work directory")
    args = ap.parse_args()
    import flows  # noqa: E402 (after sys.path)
    import flows_drive  # noqa: E402,F401 (lane app1: the drive's flows register themselves)

    r = Results()
    static_checks(r)
    # /var/tmp is disk-backed on Debian (/tmp is a small tmpfs): the dev server sizes its lanes and the
    # paid capacity from the disk its data sits on, and a pack needs room for 2 GiB.
    work = tempfile.mkdtemp(prefix="mutis-ui-run-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    port = free_port()
    dist = build(work, f"http://127.0.0.1:{port}")
    servers = {None: (serve(dist, os.path.join(work, "data"), port), f"http://127.0.0.1:{port}")}

    def origin_for(amount_proof):
        if amount_proof not in servers:
            other = free_port()
            servers[amount_proof] = (serve(dist, os.path.join(work, f"data-{amount_proof}"), other, amount_proof),
                                     f"http://127.0.0.1:{other}")
        return servers[amount_proof][1]

    make_fixtures(os.path.join(work, "fixtures"))
    shots = os.path.join(APP, "shots") if args.shots else None
    try:
        for sid, title, fn, opts in flows.SCENARIOS:
            if args.only and sid not in args.only:
                continue
            r.current = sid
            print(f"--- {sid} {title}", flush=True)
            browser = Browser(opts.get("args", ()))
            t = T(r, browser, origin_for(opts.get("amount_proof")), work, shots)
            try:
                fn(t)
                r.check(not t.violations(), f"no CSP or Trusted Types violation ({t.violations()[:2]})")
            except Exception as e:  # a crashed flow is a failure with its trace, never a skip
                r.check(False, f"{type(e).__name__}: {e}")
                traceback.print_exc()
                for i, p in enumerate(t.pages):
                    try:
                        where = p.eval("location.href + ' :: ' + document.body.innerText.replace(/\\s+/g, ' ').slice(0, 400)")
                    except Exception:  # the page may be gone
                        where = "(no page)"
                    print(f"  page {i}: {where}\n    errors: {p.errors[-4:]}")
            finally:
                t.close()
                browser.close()
    finally:
        for proc, _ in servers.values():
            proc.terminate()
            proc.wait(10)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"work directory kept: {work}")
    print(f"\nUI {'PASS' if not r.failed else 'FAIL'} {r.passed}/{r.passed + len(r.failed)}")
    for f in r.failed:
        print("  failed:", f)
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
