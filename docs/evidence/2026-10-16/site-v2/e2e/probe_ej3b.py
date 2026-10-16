# SPDX-License-Identifier: MIT
"""Probe 2 of E-J step 3 on production, as E-J does it (a phone open, Make my drive from the home page,
the folder still uploading), three times in one drive, with a log of the share dialog's life."""
import json
import time

import flows
import scenarios_drive as drv
from harness import T, scenario

WATCH = """(() => { window.__log = []; const t0 = performance.now(); const log = (m) => __log.push(Math.round(performance.now() - t0) + ' ' + m);
  new MutationObserver((ms) => { for (const m of ms) {
    for (const n of m.addedNodes) if (n.id === 'share-dialog') log('box added');
    for (const n of m.removedNodes) if (n.id === 'share-dialog') log('box removed');
    if (m.type === 'attributes' && m.target.id === 'share-dialog') log(m.attributeName + '=' + m.target.getAttribute(m.attributeName)); } })
    .observe(document.body, { childList: true, subtree: false, attributes: true, attributeFilter: ['data-step', 'hidden'], subtree: true });
  document.addEventListener('click', (e) => log('click ' + (e.target.closest('[data-testid]')?.dataset.testid || e.target.tagName)), true);
  addEventListener('error', (e) => log('error ' + e.message)); addEventListener('unhandledrejection', (e) => log('rejection ' + (e.reason?.message || e.reason)));
  return true; })()"""


@scenario("P-EJ3b", "probe: E-J step 3 as E-J does it, three times")
def probe(t: T) -> None:
    phone = t.actor("iphone")
    phone.goto(t.origin + "/")
    desk = t.actor("desktop")
    flows.home(desk, t.origin)
    desk.click("home-make")
    desk.wait_for("drive-root", 120)
    desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    folder = f"{t.sid}-council"
    drv.upload_folder(t, desk, "council", {"minutes.txt": b"E2E probe minutes.\n", "agenda.txt": b"E2E probe agenda.\n",
                                           "notes.txt": b"E2E probe notes.\n"})
    drv.into(desk, folder)
    drv.wait_names(desk, ["minutes.txt", "agenda.txt"])
    desk.eval(WATCH)
    for name in ("minutes.txt", "agenda.txt", "notes.txt"):
        drv.row_menu(desk, name, "share")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
        desk.click("share-next")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
        desk.click("share-then-delete")
        on = desk.eval("document.querySelector('[data-testid=\"share-then-delete\"]')?.getAttribute('aria-checked')")
        desk.click("share-make")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
        say = desk.eval("document.querySelector('[data-testid=\"share-step-result\"]')?.innerText") or ""
        t.check("leaves your drive" in say, f"{name}: switch {on}; the result says it leaves ({'leaves your drive' in say})")
        desk.key("Escape")
        desk.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 10)
        time.sleep(0.5)
    t.note("log: " + json.dumps(desk.eval("__log")))
