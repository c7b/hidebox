# SPDX-License-Identifier: MIT
"""Probe: E-J track one up to step 3's switch, as E-J does it, with the page's input and the dialog logged."""
import json
import os
import time

import flows
import scenarios_drive as drv
from harness import T, scenario

LOG = r"""(() => { if (window.__jr) return; const R = window.__jr = []; const t0 = performance.now();
  const L = (m) => R.push(Math.round(performance.now() - t0) + ' ' + m);
  const who = (e) => { const el = e.target?.nodeType === 1 ? e.target : e.target?.parentElement; const tid = el?.closest?.('[data-testid]')?.dataset.testid; return (tid || el?.tagName || '?') + (el?.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''); };
  for (const k of ['pointerdown', 'mousedown', 'mouseup', 'click']) addEventListener(k, (e) => { if (document.getElementById('share-dialog')) L(k + ' ' + who(e) + ' @' + Math.round(e.clientX) + ',' + Math.round(e.clientY) + (e.isTrusted ? '' : ' synthetic')); }, true);
  addEventListener('sh:change', (e) => L('sh:change ' + who(e) + ' checked=' + e.target.getAttribute?.('aria-checked')), true);
  addEventListener('focusin', (e) => { if (document.getElementById('share-dialog')) L('focus ' + who(e)); }, true);
  new MutationObserver((ms) => { for (const m of ms) { const b = document.getElementById('share-dialog');
    if (m.target === b && m.type === 'childList') L('dialog drawn ' + b.dataset.step);
    if (m.type === 'attributes' && m.target.dataset?.testid === 'share-then-delete') L('switch ' + m.attributeName + '=' + m.target.getAttribute(m.attributeName));
    for (const n of m.addedNodes) if (n.nodeType === 1 && n.parentElement === document.body) L('body+ ' + (n.id || n.className || n.tagName));
    for (const n of m.removedNodes) if (n.nodeType === 1 && m.target === document.body) L('body- ' + (n.id || n.className || n.tagName)); } })
    .observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-checked', 'data-state', 'hidden'] });
})()"""

STACK = r"""(() => { const e = document.querySelector('[data-testid="share-then-delete"]'); if (!e) return null; const r = e.getBoundingClientRect();
  const x = r.x + r.width / 2, y = r.y + r.height / 2;
  return { x, y, rect: [r.x, r.y, r.width, r.height].map(Math.round), stack: document.elementsFromPoint(x, y).slice(0, 6).map((n) => (n.dataset?.testid || n.id || n.tagName) + '.' + (typeof n.className === 'string' ? n.className.split(' ')[0] : '') + ' z=' + getComputedStyle(n).zIndex),
    checked: e.getAttribute('aria-checked'), dialogs: [...document.querySelectorAll('.overlay')].length, judge: !!localStorage.getItem('mutis.judge') }; })()"""


@scenario("P-JR1", "probe: E-J track one to step 3's switch, logged")
def probe(t: T) -> None:
    judge = os.environ.get("PROBE_JUDGE") or None
    phone, desk = t.actor("iphone", judge_pass=judge), t.actor("desktop", judge_pass=judge)
    desk.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LOG})
    flows.home(desk, t.origin)
    desk.eval(LOG)
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
    before = desk.eval(STACK)
    t0 = time.monotonic()
    desk.click("share-then-delete")
    took = time.monotonic() - t0
    after = desk.eval(STACK)
    t.note("before " + json.dumps(before))
    t.note(f"click took {took:.2f} s")
    t.note("after " + json.dumps(after))
    t.note("log " + json.dumps(desk.eval("window.__jr")))
    t.shot(desk, "switch")
    t.check(after and after["checked"] == "true", f"the switch is on after one press ({after and after['checked']}, the press took {took:.2f} s)")
