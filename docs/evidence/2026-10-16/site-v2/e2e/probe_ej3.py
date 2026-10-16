# SPDX-License-Identifier: MIT
"""Probe of E-J step 3 on production: what the click on Delete it from my drive after hits."""
import json
import time

import scenarios_drive as drv
from harness import T, scenario

HIT = """(() => { const e = document.querySelector('[data-testid="share-then-delete"]'); if (!e) return null;
  const r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2; const hit = document.elementFromPoint(x, y);
  return { x, y, checked: e.getAttribute('aria-checked'), wired: e.dataset.wsw || null, hitIsSwitch: e.contains(hit),
    hit: hit ? (hit.tagName + '.' + hit.className + ' ' + (hit.dataset.testid || '') + ' ' + (hit.textContent || '').trim().slice(0, 60)) : null,
    toasts: [...document.querySelectorAll('[data-sonner-toast], .toast, [role=status]')].filter((t) => t.offsetParent).map((t) => t.textContent.trim().slice(0, 80)),
    dialog: (() => { const d = document.getElementById('share-dialog').getBoundingClientRect(); return [d.x, d.y, d.width, d.height]; })() }; })()"""


@scenario("P-EJ3", "probe: E-J step 3's switch on production")
def probe(t: T) -> None:
    desk = t.actor("desktop")
    desk.goto(t.origin + "/drive?make")
    desk.wait_for("drive-root", 120)
    desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    folder = f"{t.sid}-council"
    drv.upload_folder(t, desk, "council", {"minutes.txt": b"E2E probe minutes.\n", "agenda.txt": b"E2E probe agenda.\n",
                                           "notes.txt": b"E2E probe notes.\n"})
    drv.into(desk, folder)
    drv.wait_names(desk, ["minutes.txt", "agenda.txt"])
    drv.row_menu(desk, "minutes.txt", "share")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    desk.click("share-next")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
    t.note("before: " + json.dumps(desk.eval(HIT)))
    t.shot(desk, "before")
    desk.click("share-then-delete")
    t.note("after 0 s: " + json.dumps(desk.eval(HIT)))
    time.sleep(1)
    t.note("after 1 s: " + json.dumps(desk.eval(HIT)))
    t.shot(desk, "after")
    desk.click("share-make")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
    say = desk.eval("document.querySelector('[data-testid=\"share-step-result\"]')?.innerText") or ""
    t.note("result: " + say[:300].replace("\n", " | "))
    t.check("leaves your drive" in say, "the result says the file leaves")
