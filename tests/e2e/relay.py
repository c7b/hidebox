#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run headless Chromium with --remote-debugging-pipe and relay its DevTools pipe over stdin/stdout.

  sudo -iu build python3 -I relay.py [--jitless]        (started by cdp.py, usually through ssh)

The E2E orchestrator runs where it can also do admin steps (the jarvis box, or lcam on ultron), while
the browser runs here as the unprivileged `build` user. Messages are NUL-delimited JSON in both
directions and pass through unchanged; nothing in them is interpreted. Chromium's profile lives in a
temporary directory that is removed when stdin closes. Python stdlib only.
"""
import fcntl
import os
import selectors
import shutil
import subprocess
import sys
import tempfile

FLAGS = ["--headless", "--remote-debugging-pipe", "--no-first-run", "--no-default-browser-check",
         "--disable-extensions", "--disable-background-networking", "--disable-sync", "--disable-default-apps",
         "--disable-component-update", "--mute-audio", "--hide-scrollbars", "--use-angle=swiftshader",
         "--enable-unsafe-swiftshader", "--password-store=basic", "--window-size=1440,900"]


def main() -> int:
    profile = tempfile.mkdtemp(prefix="mutis-e2e-")
    to_chrome_r, to_chrome_w = os.pipe()
    from_chrome_r, from_chrome_w = os.pipe()
    # Chromium reads commands on fd 3 and writes on fd 4. Move the child's ends above both first, so
    # that putting one in place can't overwrite the other. Python's own descriptors are close-on-exec,
    # so with close_fds=False only 3 and 4 reach Chromium (close_fds=True would close them, since
    # CPython closes descriptors after preexec_fn runs).
    child_r = fcntl.fcntl(to_chrome_r, fcntl.F_DUPFD_CLOEXEC, 20)
    child_w = fcntl.fcntl(from_chrome_w, fcntl.F_DUPFD_CLOEXEC, 20)
    os.close(to_chrome_r)
    os.close(from_chrome_w)

    def child_fds():
        os.dup2(child_r, 3)
        os.dup2(child_w, 4)

    flags = FLAGS + (["--js-flags=--jitless"] if "--jitless" in sys.argv else [])
    chrome = subprocess.Popen(["chromium", *flags, f"--user-data-dir={profile}", "about:blank"],
                              preexec_fn=child_fds, close_fds=False,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(child_r)
    os.close(child_w)
    stdin, stdout = sys.stdin.buffer.fileno(), sys.stdout.buffer.fileno()
    sel = selectors.DefaultSelector()
    sel.register(stdin, selectors.EVENT_READ, to_chrome_w)
    sel.register(from_chrome_r, selectors.EVENT_READ, stdout)
    try:
        while True:
            for key, _ in sel.select():
                data = os.read(key.fd, 1 << 20)
                if not data:
                    return 0
                view = memoryview(data)
                while view:
                    view = view[os.write(key.data, view):]
    finally:
        chrome.terminate()
        try:
            chrome.wait(10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
