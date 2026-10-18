# SPDX-License-Identifier: MIT
"""The waits and their results (docs/review/ux-feedback-1.md): the drop page's steps lit one by one with their clock,
a bar that sweeps or fills, our relay's countdown, the chain's line, the failure that says what to retry, the done
moment (Delivered, the receipt, one lime); /verify/tx's summary over its folded record; the drive's upload sweep and
key file spinner; the home widget's busy bar. To hold a state long enough to check it, the page's fetch is wrapped in
the test browser only (GATE): a chunk upload waits, a transaction read waits, or a job reads queued, sending or
failed. The product code is unchanged."""
import json
import re
import time

from flows import home, no_hscroll, owner_with_drop, scenario
from flows_drive import fixture_files
from flows_share import FEATURES, drive_page

GATE = r"""(() => {
  if (window.__ux_gate) return;
  window.__ux_gate = true;
  window.__ux_mode = sessionStorage.getItem('ux_mode');
  window.__ux_steps = [];
  new MutationObserver((ms) => {
    for (const m of ms) {
      const li = m.target;
      if (li.matches?.('.flow li[data-step]') && li.dataset.state === 'now') window.__ux_steps.push(li.dataset.step);
    }
  }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-state'] });
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
      const body = await (await real(input, init)).json();
      const state = window.__ux_mode.slice(4);
      return new Response(JSON.stringify({ ...body, state, result: null, error: state === 'failed' ? 'walletd_failed' : null }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return real(input, init);
  };
})()"""

LIME = "rgb(188, 254, 0)"


def gate(page):
    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": GATE})


def mode(page, value):
    v = "null" if value is None else json.dumps(value)
    page.eval(f"window.__ux_mode = {v}; {v} === null ? sessionStorage.removeItem('ux_mode') : sessionStorage.setItem('ux_mode', {v})")


def step(page, name):
    return page.eval(f"document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"{name}\"]')?.dataset.state ?? ''")


def note(page, name):
    return page.eval(f"document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"{name}\"] .step-note')?.textContent ?? ''")


def running(page, name):
    return page.eval(f"document.getAnimations().some((a) => a.animationName === {json.dumps(name)} && a.playState === 'running')")


def limes(page):
    """Visible buttons and links filled with the lime."""
    return page.eval(f"""[...document.querySelectorAll('button, a')].filter((e) => e.getClientRects().length && e.checkVisibility()
      && getComputedStyle(e).backgroundColor === {json.dumps(LIME)}).map((e) => e.textContent.trim())""")


@scenario("ux-drop", "The drop page's run (ux-feedback-1): each step lit in order with its clock; a sweep while a chunk travels; the relay's countdown fills the bar; the chain's line; a failed delivery says what to retry; Delivered with the receipt, one lime; /verify/tx's summary over Details")
def ux_drop(t):
    _, drop, _ = owner_with_drop(t, device="desktop")
    b = t.actor("desktop")
    gate(b)
    b.goto(drop)
    t.check(b.wait_state("dd-root", ("ready",), 60) == "ready", "the drop page is ready")
    mode(b, "hold-upload")
    b.set_files("dd-input", [t.fixture("photo-gps.jpg")])
    b.wait("document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"upload\"]')?.dataset.state === 'now'", 60)
    t.check(b.attr("dd-root", "data-state") == "sealing" and step(b, "lock") == "done", "picked: Locking it in this browser is done, Uploading lit")
    t.check([x.strip() for x in b.eval("[...document.querySelectorAll('[data-testid=\"dd-steps\"] .step-label')].map((e) => e.textContent)")]
            == ["Locking it in this browser", "Uploading", "Waiting for the Tari chain", "Delivered"], "four steps, in people's words")
    t.check(bool(re.search(r"\d", note(b, "upload"))), f"the upload step says how big it is ({note(b, 'upload')!r})")
    time.sleep(2.4)
    clock = b.eval("document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"upload\"] .step-time')?.textContent ?? ''")
    t.check(bool(re.fullmatch(r"0:0[2-9]", clock)), f"a step past two seconds shows its clock ({clock!r})")
    t.check(b.eval("document.querySelector('[data-testid=\"dd-steps\"] .flow-bar').dataset.mode") == "busy" and running(b, "fl-sweep"),
            "while the chunk travels, the bar sweeps (it never stands still)")
    t.check(running(b, "fl-spin"), "the lit step's dot turns")
    t.check(b.exists("exif-chip") and b.eval("!!document.querySelector('[data-testid=\"dd-root\"] .a-linkbtn')"),
            "the photo's chip and Stop stay with the steps")
    mode(b, "job-queued")
    b.wait("(document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"chain\"] .step-note')?.textContent || '').includes('relay')", 60)
    first = b.eval("Number(document.querySelector('[data-testid=\"dd-steps\"] .flow-bar').getAttribute('aria-valuenow'))")
    time.sleep(2.2)
    later = b.eval("Number(document.querySelector('[data-testid=\"dd-steps\"] .flow-bar').getAttribute('aria-valuenow'))")
    said = note(b, "chain")
    t.check(step(b, "upload") == "done" and step(b, "chain") == "now" and b.attr("dd-root", "data-state") == "sending", "uploaded: Waiting for the Tari chain lit")
    t.check(bool(re.fullmatch(r"Our relay sends it in about \d+ seconds?\.", said)) or said == "Our relay is sending it.",
            f"the relay's own time to send, counted down ({said!r})")
    t.check(later > first or said == "Our relay is sending it.", f"the bar fills toward the relay's moment ({first} → {later})")
    mode(b, "job-sending")
    b.wait("(document.querySelector('[data-testid=\"dd-steps\"] li[data-step=\"chain\"] .step-note')?.textContent || '').includes('few seconds')", 30)
    t.check(note(b, "chain") == "The chain usually takes a few seconds." and running(b, "fl-sweep"), "on its way: the chain's line, the bar sweeps")
    mode(b, "job-failed")
    t.check(b.wait_state("dd-root", ("error",), 60) == "error", "a failed delivery")
    banner = b.text("error-banner")
    t.check(step(b, "chain") == "failed" and step(b, "upload") == "done", "the step that failed is marked; the ones before stay done")
    t.check("didn't go through" in banner and "Your file is stored." in banner
            and b.eval("[...document.querySelectorAll('[data-testid=\"error-banner\"] button')].some((x) => x.textContent === 'Try again')"),
            f"it says what failed, that the file is safe, and offers Try again ({banner[:90]!r})")
    mode(b, None)
    b.eval("[...document.querySelectorAll('[data-testid=\"error-banner\"] button')].find((x) => x.textContent === 'Try again').click()")
    t.check(b.wait_state("dd-root", ("delivered", "error"), 180) == "delivered", "Try again: Delivered")
    order = b.eval("window.__ux_steps")
    t.check(order[:3] == ["lock", "upload", "chain"] and order[3:] in ([], ["chain"]), f"the steps lit in their order ({order})")
    b.wait("document.activeElement?.classList.contains('done-title')", 10)
    t.check(b.text("dd-done").find("Delivered.") >= 0 and b.eval("document.activeElement.textContent") == "Delivered.",
            "the done moment: Delivered., focused for a screen reader")
    say = b.eval("document.querySelector('[data-testid=\"dd-done\"] .done-say').textContent")
    t.check(say == "Your photo is in their drive. Only that drive can open it.", f"what happened, in people's words ({say!r})")
    tx = b.attr("dd-tx", "data-tx") or ""
    href = b.attr("dd-chain-link", "href") or ""
    t.check(bool(re.fullmatch(r"[0-9a-f]{64}", tx)) and href == f"/verify/tx/{tx}" and "Receipt" in b.text("dd-chain-link"),
            "the transaction is a Receipt link, its id shortened")
    t.check("The Tari chain recorded the delivery." in b.text("dd-done"), "the chain's line, in plain words")
    t.check(b.exists("exif-chip") and b.eval("[...document.querySelectorAll('[data-testid=\"dd-done\"] button')].some((x) => x.textContent === 'Leave another')"),
            "the photo's chip and Leave another")
    lime = limes(b)
    t.check(lime == ["Open your drive"], f"one lime on the page: the header's Open your drive ({lime})")
    off = b.eval("""(() => { const c = document.querySelector('[data-testid="dd-done"]').getBoundingClientRect(), mid = c.left + c.width / 2;
      return ['.done-art', '.done-title', '.done-say', '.done-receipt', '.done-actions'].map((s) => {
        const r = document.querySelector('[data-testid="dd-done"] ' + s).getBoundingClientRect(); return Math.abs(r.left + r.width / 2 - mid); }); })()""")
    t.check(max(off) < 2, f"the moment sits on one axis, not floating ({[round(x, 1) for x in off]})")
    time.sleep(1.2)
    t.check(b.eval("getComputedStyle(document.querySelector('.done-title')).opacity") == "1"
            and b.eval("getComputedStyle(document.querySelector('.done-file')).opacity") == "0",
            "after its 1.2 s the moment rests: the words in full, the file inside the box")
    t.shot(b, "ux-drop-1440-delivered")
    # /verify/tx: the summary first, the record under Details
    mode(b, "hold-tx")
    b.click("dd-chain-link")
    b.wait_for("tx-loading", 60)
    b.wait("(document.querySelector('[data-testid=\"tx-loading\"] .step-note')?.textContent || '').length > 0", 20)
    t.check(b.text("tx-loading").startswith("Reading it from the indexer") and "few seconds to reach the indexers" in b.text("tx-loading"),
            "a slow read says what it waits for")
    mode(b, None)
    b.wait_for("tx-summary", 60)
    summary = b.text("tx-summary")
    t.check(summary.startswith("Confirmed.") and "epoch" in summary and "a tick of its clock" in summary,
            f"the status first, the epoch in one phrase ({summary[:90]!r})")
    chips = b.eval("[...document.querySelectorAll('[data-testid=\"tx-hidden\"] li')].map((e) => e.textContent)")
    t.check(chips == ["The amount", "Who got it", "What it carries"], f"what stays hidden, read from this transaction ({chips})")
    t.check("The Tari chain accepted this transaction, and it is final." in b.text("tx-root")
            and "Anyone can see the fee, and that it happened." in b.text("tx-hidden"), "what this proves; what is public")
    t.check(b.eval("document.querySelector('[data-testid=\"tx-details\"]').open && document.querySelector('[data-testid=\"tx-check\"]').open"),
            "a computer opens Details and the check")
    t.check(b.exists("tx-fee") and len(b.eval("[...document.querySelectorAll('[data-testid=\"tx-output\"]')]")) >= 1
            and b.eval("!!document.querySelector('[data-testid=\"tx-details\"] .a-raw pre')"), "every field of the record is still there")
    t.shot(b, "ux-verify-1440", full_page=True)


@scenario("ux-drop-phone", "The drop page on a phone with reduced motion: Delivered at once and still; /verify/tx folds its record; nothing sideways")
def ux_drop_phone(t):
    _, drop, _ = owner_with_drop(t, device="desktop")
    p = t.actor("iphone", reduced_motion=True)
    p.goto(drop)
    t.check(p.wait_state("dd-root", ("ready",), 60) == "ready", "the drop page is ready")
    p.set_files("dd-input", [t.fixture("photo-gps.jpg")])
    p.wait("!!document.querySelector('[data-testid=\"dd-steps\"]')", 30)
    t.check(no_hscroll(p), "the steps fit a phone")
    t.check(p.wait_state("dd-root", ("delivered", "error"), 180) == "delivered", "Delivered")
    t.check(p.eval("getComputedStyle(document.querySelector('.done-title')).opacity") == "1"
            and p.eval("document.querySelector('.done-file') === null || getComputedStyle(document.querySelector('.done-file')).display === 'none'")
            and not p.eval("document.getAnimations().some((a) => a.playState === 'running' && a.effect?.target?.closest?.('.done'))"),
            "reduced motion: the moment is there at once, nothing flies")
    t.check(p.eval("document.querySelector('[data-testid=\"dd-done\"]').getBoundingClientRect().top >= 0"), "the moment starts in view")
    t.check(no_hscroll(p), "the done moment fits a phone")
    t.shot(p, "ux-drop-390-delivered")
    p.click("dd-chain-link")
    p.wait_for("tx-summary", 90)
    t.check(p.eval("!document.querySelector('[data-testid=\"tx-details\"]').open && !document.querySelector('[data-testid=\"tx-check\"]').open"),
            "a phone keeps Details and the check folded")
    t.check(p.text("tx-summary").startswith("Confirmed.") and no_hscroll(p), "the summary first, nothing sideways")
    p.eval("document.querySelector('[data-testid=\"tx-details\"] summary').click()")
    t.check(p.eval("document.querySelector('[data-testid=\"tx-details\"]').open") and p.exists("tx-fee"), "Details opens to the full record")


@scenario("ux-drive-waits", "The drive's waits (ux-feedback-1): an upload row sweeps while its chunk travels; Save key file turns and says so", features=FEATURES)
def ux_drive_waits(t):
    a = drive_page(t)
    gate(a)
    a.reload()
    a.wait_for("drive-root", 90)
    a.wait("!!document.querySelector('[data-testid=\"upload-files-input\"]')", 30)
    mode(a, "hold-upload")
    a.set_files("upload-files-input", fixture_files(t, ["slow-net.txt"]))
    a.wait("!!document.querySelector('[data-testid=\"upload-row\"][data-busy]')", 30)
    t.check(running(a, "up-sweep"), "a chunk on its way: the row's bar sweeps")
    t.check(a.eval("document.querySelector('[data-testid=\"upload-row\"] .stage').textContent") == "Uploading", "the row says Uploading")
    mode(a, None)
    a.wait("!!document.querySelector('[data-testid=\"upload-row\"][data-done]')", 60)
    t.check(not a.eval("!!document.querySelector('[data-testid=\"upload-row\"][data-busy]')"), "done: the sweep stops")
    a.eval("document.querySelector('[data-testid=\"acct-key\"]').click()")
    a.wait_for("key-dialog", 15)
    a.fill("key-passphrase", "tidal amber quiet lantern")
    a.eval("""(() => { const b = document.querySelector('[data-testid="key-save-file"]'); window.__key_seen = [];
      new MutationObserver(() => window.__key_seen.push(b.textContent)).observe(b, { childList: true, subtree: true, characterData: true }); })()""")
    a.click("key-save-file")
    a.wait("(document.querySelector('[data-testid=\"key-dialog\"] p[aria-live=\"polite\"]')?.textContent || '').length > 0", 30)
    seen = a.eval("window.__key_seen")
    t.check("Locking the key file…" in seen and a.text("key-save-file") == "Save key file",
            f"while the key file locks, the button turns and says so; then it is back ({seen[:3]})")


@scenario("ux-widget", "The home's quick share while a chunk travels: a bar moves under Locking it up")
def ux_widget(t):
    c = t.actor("iphone")
    gate(c)
    home(t, c)
    mode(c, "hold-upload")
    c.set_files("drop-input", [t.fixture("photo-gps.jpg")])
    c.wait("!!document.querySelector('.md-sealing [data-testid=\"seal-progress\"]')", 30)
    t.check(running(c, "md-run"), "the busy line has a bar that moves")
    mode(c, None)
    c.wait("((document.querySelector('[data-testid=\"sealed-link\"]') || {}).value || '').startsWith('http')", 60)
    t.check(True, "released: the link")
