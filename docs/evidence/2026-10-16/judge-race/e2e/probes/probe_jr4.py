# SPDX-License-Identifier: MIT
"""Probe 4: E-J step 3 exactly (nothing between the wait and the click), with passive page logs only:
mutations, long tasks, fetches; no input listeners."""
import json
import os
import time

import flows
import scenarios_drive as drv
from harness import T, scenario

PASSIVE = r"""(() => { if (window.__p) return; const P = window.__p = []; const t0 = performance.now(); const L = (m) => P.push(Math.round(performance.now() - t0) + ' ' + m);
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) L('longtask ' + Math.round(e.startTime - t0) + '+' + Math.round(e.duration)); }).observe({ type: 'longtask', buffered: true }); } catch {}
  const f = window.fetch; window.fetch = function (i, o) { const u = String(i?.url ?? i).replace(/^https?:\/\/[^/]+/, ''); L('fetch ' + (o?.method || 'GET') + ' ' + u.slice(0, 60)); return f.apply(this, arguments).then((r) => { L('  ' + r.status + ' ' + u.slice(0, 40)); return r; }); };
  new MutationObserver((ms) => { for (const m of ms) { const b = document.getElementById('share-dialog');
    if (b && m.target === b && m.type === 'childList') L('dialog drawn ' + b.dataset.step);
    if (m.type === 'attributes' && m.target.dataset?.testid === 'share-then-delete') L('switch ' + m.attributeName + '=' + m.target.getAttribute(m.attributeName));
    if (m.type === 'attributes' && m.target === b) L('dialog ' + m.attributeName + '=' + b.getAttribute(m.attributeName));
    for (const n of m.addedNodes) if (n.nodeType === 1 && m.target === document.body) L('body+ ' + (n.id || n.className || n.tagName));
    for (const n of m.removedNodes) if (n.nodeType === 1 && m.target === document.body) L('body- ' + (n.id || n.className || n.tagName)); } })
    .observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-checked', 'data-state', 'hidden', 'data-step'] });
})()"""


@scenario("P-JR4", "probe: E-J step 3 exactly, passive logs")
def probe(t: T) -> None:
    judge = os.environ.get("PROBE_JUDGE") or None
    phone, desk = t.actor("iphone", judge_pass=judge), t.actor("desktop", judge_pass=judge)
    desk.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": PASSIVE})
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
    desk.click("share-then-delete")
    now = desk.attr("share-then-delete", "aria-checked")
    time.sleep(1.5)
    later = desk.attr("share-then-delete", "aria-checked")
    t.shot(desk, "after")
    t.note(f"at once {now}; later {later}")
    t.note("log " + json.dumps(desk.eval("window.__p")))
    t.check(now == "true", f"the switch is on at once after one press (at once {now}, later {later})")
