# SPDX-License-Identifier: MIT
"""Probe 2: E-J's step 3 click exactly as E-J does it (no input listeners in the page); the switch read at once
and again later, and when it flipped (a MutationObserver, which doesn't touch input handling)."""
import json
import os
import time

import flows
import scenarios_drive as drv
from harness import T, scenario

WATCH = r"""(() => { window.__flip = []; const t0 = performance.now();
  new MutationObserver((ms) => { for (const m of ms) if (m.target.dataset?.testid === 'share-then-delete') window.__flip.push(Math.round(performance.now() - t0) + ' ' + m.target.getAttribute('aria-checked')); })
    .observe(document.getElementById('share-dialog'), { subtree: true, attributes: true, attributeFilter: ['aria-checked'] });
  return Math.round(t0); })()"""


@scenario("P-JR2", "probe: E-J step 3's click, read at once and later")
def probe(t: T) -> None:
    judge = os.environ.get("PROBE_JUDGE") or None
    phone, desk = t.actor("iphone", judge_pass=judge), t.actor("desktop", judge_pass=judge)
    flows.home(desk, t.origin)
    desk.click("home-make")
    desk.wait_for("drive-root", 120)
    desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    folder = f"{t.sid}-council"
    drv.upload_folder(t, desk, "council", {"minutes.txt": b"probe minutes.\n", "agenda.txt": b"probe agenda.\n", "notes.txt": b"probe notes.\n"})
    drv.into(desk, folder)
    drv.wait_names(desk, ["minutes.txt", "agenda.txt"])
    drv.row_menu(desk, "minutes.txt", "share")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    desk.click("share-next")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
    desk.eval(WATCH)
    desk.click("share-then-delete")
    now = desk.attr("share-then-delete", "aria-checked")
    time.sleep(1)
    later = desk.attr("share-then-delete", "aria-checked")
    t.note(f"at once {now}; a second later {later}; flips {desk.eval('window.__flip')}")
    t.check(later == "true", f"the switch is on a second after one press (at once {now}, later {later})")
