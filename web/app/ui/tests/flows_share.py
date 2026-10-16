# SPDX-License-Identifier: MIT
"""The share dialog, the folder viewer and Received (lane app2; 16-drive-design §3, §5, §6, §12, §15 steps 8
and 10), against the real API in headless Chromium. These flows run on a dev server of their own with
features.folders on (config.py keeps it off until the drive's routes switch over; run.py starts it from
the scenario's `features`), so the server lane's folder links, tree tickets and then_delete are the real
code, not app1's fake.

share-once, share-rules (A few times, Until a time, Public link; a drive's first day), share-word-then-delete,
share-send-tari (+ kind 4), received-list (Tari arrivals, sender hidden, Save to my drive, the drop link,
purchases, offline), received-folder (a folder by Tari, opened and saved as a tree), folder-zip (Download all, checked with Python's zipfile) and folder-viewer (a visit: countdown,
phones, one by one, preview)."""
import glob
import json
import os
import re
import sqlite3
import time
import zipfile

from flows import FAKE_SHARE, VIEW_ASK, VIEW_END, Intercept, api_error, downloaded, no_hscroll, safety_emoji, scan_code, scenario
from flows_drive import fixture_files, row_menu, table_names, upload_files

FEATURES = ("folders",)
LINK = r"/s/[A-Za-z0-9_-]{22}#1[A-Za-z0-9_-]{43}"
WORD_LINK = r"/s/[A-Za-z0-9_-]{22}#2[A-Za-z0-9_-]{43}"
NOTES = "Meeting notes. The office key is under the plant.\n"


# --- steps shared by these flows ----------------------------------------------------------------------

def drive_page(t, device="desktop", share=False):
    """/drive?make on a fresh actor; `share` gives the page a navigator.share that records what it got."""
    page = t.actor(device)
    if share:
        page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": FAKE_SHARE})
    page.goto(t.origin + "/drive?make")
    page.wait_for("drive-root", 90)
    page.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    t.check(page.eval("fetch('/api/v1/config').then((r) => r.json()).then((c) => c.features.folders === true)"),
            "this flow's server has features.folders on (the real folder API, no fake)")
    return page


def db(t):
    found = glob.glob(os.path.join(t.work, "data-sidecar-folders", "**", "mutis.sqlite3"), recursive=True)
    return sqlite3.connect(found[0], timeout=30)


def grow(t, page):
    """A drive past its first day (identities.distinct_days >= 2), then the drive opened again."""
    con = db(t)
    con.execute("UPDATE identities SET distinct_days = 2")
    con.commit()
    con.close()
    page.reload()
    page.wait_for("drive-root", 90)
    page.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)


def dialog_step(page):
    return page.eval("document.getElementById('share-dialog')?.dataset.step || ''")


def open_share(page, name):
    row_menu(page, name, "share")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)


def to_opens(page):
    page.click("share-next")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)


def choices(page):
    return page.eval("[...document.querySelectorAll('#share-dialog [data-testid=\"share-choice\"]')].map((e) => e.dataset.value)")


def checked(page):
    return page.eval("document.querySelector('#share-dialog [data-testid=\"share-choice\"][data-state=\"checked\"]')?.dataset.value ?? ''")


def end_options(page):
    page.click("share-ends")
    page.wait("[...document.querySelectorAll('[role=\"listbox\"]')].some((l) => !l.hidden)", 5)
    values = page.eval("[...document.querySelectorAll('[role=\"listbox\"]:not([hidden]) [role=\"option\"]')].map((o) => o.dataset.value)")
    page.key("Escape")
    return values


def pick_end(page, value):
    page.click("share-ends")
    page.wait("[...document.querySelectorAll('[role=\"listbox\"]')].some((l) => !l.hidden)", 5)
    page.eval(f"[...document.querySelectorAll('[role=\"listbox\"]:not([hidden]) [role=\"option\"]')].find((o) => o.dataset.value === {json.dumps(value)}).click()")
    page.wait(f"document.querySelector('[data-testid=\"share-ends\"]')?.dataset.value === {json.dumps(value)}", 5)


def make_link(page):
    page.click("share-make")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
    return page.value("share-link")


def close_dialog(page):
    page.key("Escape")
    page.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 10)


def rule_of(page, name):
    return page.eval(f"""[...document.querySelectorAll('[data-testid="file-row"], [data-testid="folder-card"]')]
      .find((e) => e.dataset.name === {json.dumps(name)})?.querySelector('[data-rule]')?.dataset.rule ?? ''""")


def wait_rule(page, name, rule, timeout=30):
    page.wait(f"""[...document.querySelectorAll('[data-testid="file-row"], [data-testid="folder-card"]')]
      .find((e) => e.dataset.name === {json.dumps(name)})?.querySelector('[data-rule]')?.dataset.rule === {json.dumps(rule)}""", timeout)
    return True


def clipboard(page):
    return page.eval("navigator.clipboard.readText()")


def stranger(t, url, device="desktop"):
    v = t.actor(device)
    v.goto(url)
    return v, v.wait_state("view-root", VIEW_ASK, 60)


def new_folder(page, name):
    """New folder, waiting out the last one's closing dialog (520 ms) so the steps reach the new one."""
    page.wait("![...document.querySelectorAll('[data-testid=\"new-folder-dialog\"]')].some((d) => !d.hidden)", 10)
    page.eval("document.dispatchEvent(new CustomEvent('drive:new', { detail: 'folder' }))")
    page.wait("[...document.querySelectorAll('[data-testid=\"new-folder-dialog\"]')].some((d) => !d.hidden && d.dataset.state === 'open')", 10)
    page.fill("folder-name", name)
    page.click("folder-create")
    page.wait(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === {json.dumps(name)})", 30)


def into(page, name):
    fid = page.eval(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === {json.dumps(name)}).dataset.id")
    page.eval(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === {json.dumps(name)}).querySelector('.folder-icon').click()")
    page.wait(f"location.pathname === '/drive/folders/{fid}'", 10)
    page.wait_for("breadcrumbs", 30)
    return fid


def write_fixture(t, name, data):
    path = t.fixture(name)
    with open(path, "wb") as f:
        f.write(data)
    return path


# --- §15 step 8: the share dialog -----------------------------------------------------------------------

@scenario("share-once", "Share a file once (step 8): who, how many times, It ends, Make link, Copy, the code; a stranger opens it once; Copy a once link; the Links tab and Stop sharing", features=FEATURES)
def share_once(t):
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["notes.txt"])
    open_share(a, "notes.txt")
    t.check(a.eval("document.querySelector('#share-dialog .dialog-title').textContent") == "Share notes.txt", "the dialog names the file")
    t.check(choices(a) == ["link", "tari"] and checked(a) == "link",
            f"Who can open it? Anyone with the link (the default) or one Tari address ({choices(a)}; pay to open joins with step 15)")
    t.check(a.ax_unnamed() == [], f"every control in the dialog has a name ({a.ax_unnamed()[:4]})")
    t.shot(a, "share-1440-who")
    to_opens(a)
    t.check(choices(a) == ["once", "few", "nolimit"] and checked(a) == "once", f"How many times? Once (the default), A few times, No limit ({choices(a)})")
    t.check(a.attr("share-ends", "data-value") == "week", "It ends: In a week by default")
    t.check(end_options(a) == ["day", "week"] and "From your second day" in a.text("share-step-opens"),
            "a drive's first day: Tomorrow or In a week; When I stop it waits for the second day, and the dialog says so")
    t.check(a.exists("share-word") and a.exists("share-then-delete"), "the secret word and Delete it from my drive after are switches on the same step")
    t.shot(a, "share-1440-opens")
    url = make_link(a)
    t.check(re.fullmatch(re.escape(t.origin) + LINK, url or "") is not None, f"a link with its own key after the # ({url[-50:] if url else url})")
    say = a.text("share-say")
    t.check(say.startswith("It opens one time, until ") and say.endswith(". Then the link ends."), f"the rule in one sentence (C26: {say})")
    payload, _, _ = scan_code(a, "share-qr")
    t.check(payload == url, "the code on a computer reads back as the same link")
    t.check("That uses its one open." in a.text("share-qr"), "under a Once code: scanning uses its one open (C27, child form)")
    t.check("Everything after # is the key." in a.text("share-step-result"), "the key note under the link (C2)")
    a.click("share-copy")
    t.check(a.wait(f"navigator.clipboard.readText().then((x) => x === {json.dumps(url)})", 10), "Copy link puts the whole link on the clipboard")
    t.shot(a, "share-1440-result-once")
    close_dialog(a)
    t.check(wait_rule(a, "notes.txt", "once"), "the row wears its rule: Once")
    v, state = stranger(t, url)
    t.check(state == "ready", f"a stranger's first screen asks before it uses the open ({state})")
    v.click("view-open")
    t.check(v.wait_state("view-root", VIEW_END, 60) == "opened" and v.text("view-text") == NOTES, "it opens, once, in another browser")
    w, state = stranger(t, url)
    t.check(state == "burned", f"the second look finds the link ended ({state})")
    a.reload()
    a.wait_for("drive-root", 90)
    t.check(wait_rule(a, "notes.txt", "ended"), "back in the drive the row says Link ended; the file stays")
    # The one-tap path: the row menu's Copy a once link.
    row_menu(a, "notes.txt", "once")
    a.wait("[...document.querySelectorAll('.toast')].some((e) => e.textContent.includes('Once link copied.'))", 30)
    once = clipboard(a)
    t.check(re.fullmatch(re.escape(t.origin) + LINK, once or "") is not None and once != url, "Copy a once link: a new Once link on the clipboard, in one tap")
    t.check(wait_rule(a, "notes.txt", "once"), "the row says Once again")
    # The Links tab: Copy (this browser made it) and Stop sharing.
    open_share(a, "notes.txt")
    t.check(a.exists("share-tab-links") and a.text("share-tab-links") == "Links (1)", "a file with a link opens on two tabs: New link, Links (1)")
    a.click("share-tab-links")
    a.wait_for("link-row", 10)
    t.check(a.eval("document.querySelector('[data-testid=\"link-row\"] [data-rule]').dataset.rule") == "once", "the Links tab lists the link with its rule")
    t.shot(a, "share-1440-links")
    a.click("link-copy")
    t.check(a.wait(f"navigator.clipboard.readText().then((x) => x === {json.dumps(once)})", 10), "Copy on a link this browser made")
    a.click("link-stop")
    a.wait("[...document.querySelectorAll('.toast')].some((e) => e.textContent.includes('Stopped sharing.'))", 30)
    t.check(wait_rule(a, "notes.txt", "ended"), "Stop sharing: the link ends now, the file stays")
    _, state = stranger(t, once)
    t.check(state == "revoked", f"the stopped link no longer opens ({state})")


@scenario("share-rules", "A few times, Until a time and a Public link on a phone (step 8): the first day's limits, then the second day; Share is the primary", features=FEATURES)
def share_rules(t):
    a = drive_page(t, "iphone", share=True)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["few.txt", "first-day.txt", "until.txt", "public.txt"])
    # A few times, Tomorrow.
    open_share(a, "few.txt")
    to_opens(a)
    a.click("share-choice", "few")
    t.check("Up to 3 opens." in a.text("share-step-opens"), "A few times says how many")
    pick_end(a, "day")
    t.check(no_hscroll(a), "no horizontal scroll in the dialog at 390")
    t.shot(a, "share-390-opens")
    url = make_link(a)
    say = a.text("share-say")
    t.check(say.startswith("It opens up to 3 times, until ") and say.endswith("Then the link ends."), f"A few times, until tomorrow (C26-f: {say})")
    t.check(a.exists("share-native") and not a.exists("share-qr"), "a phone: Share is the primary, no code to scan")
    t.check(a.eval("document.querySelector('[data-testid=\"share-native\"]').matches('.btn:not([data-variant])')") and a.attr("share-copy", "data-variant") == "outline",
            "one filled button: Share; Copy link is outline")
    a.click("share-native")
    t.check(a.wait(f"window.__shared && window.__shared.url === {json.dumps(url)}", 10), "Share hands the link to the phone's share sheet")
    t.shot(a, "share-390-result-few")
    close_dialog(a)
    t.check(wait_rule(a, "few.txt", "few"), "the row says 3 opens")
    # No limit on the first day: the most opens the day allows.
    open_share(a, "first-day.txt")
    to_opens(a)
    a.click("share-choice", "nolimit")
    t.check("On your first day, up to 50 opens." in a.text("share-step-opens"), "No limit on a first day says its cap")
    make_link(a)
    t.check(a.text("share-say").startswith("It opens up to 50 times, until "), f"and the result says it ({a.text('share-say')})")
    close_dialog(a)
    # The second day: Until a time and the Public link.
    grow(t, a)
    open_share(a, "until.txt")
    to_opens(a)
    a.click("share-choice", "nolimit")
    t.check(end_options(a) == ["day", "week", "never"], "from the second day: When I stop it")
    t.check("As many opens as people want" in a.text("share-step-opens"), "No limit means no count")
    make_link(a)
    say = a.text("share-say")
    t.check(say.startswith("Anyone with the link can open it until ") and "stop" not in say, f"Until a time ({say})")
    close_dialog(a)
    t.check(wait_rule(a, "until.txt", "until"), "the row says Until {date}")
    open_share(a, "public.txt")
    to_opens(a)
    a.click("share-choice", "nolimit")
    pick_end(a, "never")
    t.check(not a.exists("share-then-delete"), "a link that never ends can't take the file with it: the switch goes")
    t.check(a.text("share-ends-where") == "You stop it from this file's menu: Stop sharing.", "When I stop it says where: this file's menu")
    make_link(a)
    t.check(a.text("share-say") == "Anyone with the link can open it until you stop it, from this file's menu.", "the Public link, and where to stop it")
    close_dialog(a)
    t.check(wait_rule(a, "public.txt", "public"), "the row says Public link")
    t.shot(a, "share-390-rows", full_page=True)


@scenario("share-stop", "Stop sharing where people look (B): the row menu ends a file's links in one click (the toast says a stopped link can't come back, no Undo); the result has its own Stop sharing; the Links tab says where", features=FEATURES)
def share_stop(t):
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["notes.txt", "song.txt"])
    menu = "[...document.querySelectorAll('#row-menu .menu-item')].map((e) => e.dataset.value)"
    kebab = """[...document.querySelectorAll('[data-testid="file-row"]')].find((e) => e.dataset.name === 'notes.txt').querySelector('[data-testid="row-kebab"]').click()"""
    a.eval(kebab)
    a.wait("!document.getElementById('row-menu').hidden", 10)
    t.check("stop-share" not in a.eval(menu) and "stop-sell" not in a.eval(menu), f"a file without a link has no Stop sharing ({a.eval(menu)})")
    a.key("Escape")
    a.wait("document.getElementById('row-menu').hidden", 10)
    open_share(a, "notes.txt")
    to_opens(a)
    url = make_link(a)
    row = a.text("share-stop-row")
    t.check(row.startswith("Stop it any time, here or from this file's menu.") and a.text("share-stop") == "Stop sharing",
            f"the result: Stop sharing, and where else it lives ({row!r})")
    t.check(a.ax_unnamed() == [], "every control in the result has a name")
    t.shot(a, "share-1440-result-stop")
    close_dialog(a)
    t.check(wait_rule(a, "notes.txt", "once"), "the row wears its link")
    # The row menu: Stop sharing right under Share, one click, a toast that says it can't come back.
    a.eval(kebab)
    a.wait("!document.getElementById('row-menu').hidden", 10)
    t.check(a.eval(menu)[:3] == ["share", "once", "stop-share"] and a.text("menu-stop-share") == "Stop sharing", f"the menu: Share, Copy a once link, Stop sharing ({a.eval(menu)})")
    t.shot(a, "share-1440-menu-stop")
    a.click("menu-stop-share")
    a.wait("[...document.querySelectorAll('.toast')].some((e) => e.textContent.includes('Stopped sharing.'))", 30)
    toast = a.eval("[...document.querySelectorAll('.toast')].find((e) => e.textContent.includes('Stopped sharing.')).textContent")
    t.check("A stopped link can't come back. To share again, make a new link." in toast
            and not a.eval("[...document.querySelectorAll('.toast')].some((e) => e.textContent.includes('Stopped sharing.') && e.querySelector('.toast-action'))"),
            f"one click; the toast says a stopped link can't come back, and offers no Undo ({toast!r})")
    t.check(wait_rule(a, "notes.txt", "ended"), "the row says the link ended; the file stays")
    _, state = stranger(t, url)
    t.check(state == "revoked", f"the link no longer opens ({state})")
    # From the result itself: the dialog closes on Stop sharing.
    open_share(a, "song.txt")
    to_opens(a)
    url2 = make_link(a)
    a.click("share-stop")
    a.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 30)
    t.check(wait_rule(a, "song.txt", "ended"), "Stop sharing in the result: the link ends, the dialog closes")
    _, state = stranger(t, url2)
    t.check(state == "revoked", f"that link no longer opens either ({state})")
    # A Public link (second day): the Links tab says where it stops.
    grow(t, a)
    open_share(a, "song.txt")
    to_opens(a)
    a.click("share-choice", "nolimit")
    pick_end(a, "never")
    make_link(a)
    close_dialog(a)
    open_share(a, "song.txt")
    a.click("share-tab-links")
    a.wait_for("link-row", 10)
    t.check("When you stop it, from this file's menu" in a.text("link-row") and a.text("link-stop") == "Stop sharing",
            f"the Links tab: When you stop it, from this file's menu; Stop sharing ({a.text('link-row')!r})")
    close_dialog(a)


@scenario("share-word-then-delete", "A secret word, and Delete it from my drive after (step 8): the word box; a Once link that takes the file with it (C42)", features=FEATURES)
def share_word_then_delete(t):
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["word.txt", "leaves.txt"])
    open_share(a, "word.txt")
    to_opens(a)
    a.click("share-word")
    a.wait_for("share-word-input", 10)
    word = a.value("share-word-input")
    t.check(re.fullmatch(r"[a-z]+(-[a-z]+){3}", word or "") is not None, f"turning the word on fills in four words from the list ({word})")
    t.shot(a, "share-1440-word")
    url = make_link(a)
    t.check(re.fullmatch(re.escape(t.origin) + WORD_LINK, url or "") is not None, "a link with a word carries only its half of the key (#2)")
    t.check(word in a.text("share-word-box") and "Send the word a different way than the link." in a.text("share-step-result"), "the word box, and keep them apart")
    close_dialog(a)
    t.check(wait_rule(a, "word.txt", "word"), "the row says Secret word")
    v, state = stranger(t, url)
    t.check(state == "password", f"the link alone asks for the word ({state})")
    v.fill("view-password", word)
    v.click("view-password-submit")
    t.check(v.wait_state("view-root", ("ready", "opened"), 60) in ("ready", "opened"), "the word opens it")
    if v.state("view-root") == "ready":
        v.click("view-open")
    t.check(v.wait_state("view-root", VIEW_END, 60) == "opened" and "word.txt" in v.text("view-text"), "and it is the file")
    # Delete it from my drive after.
    open_share(a, "leaves.txt")
    to_opens(a)
    a.click("share-then-delete")
    t.check(a.attr("share-then-delete", "aria-checked") == "true", "Delete it from my drive after: on")
    url = make_link(a)
    t.check("After that, it leaves your drive. We write that on the Tari chain." in a.text("share-say-more"), "the result says the file leaves too (C42)")
    t.shot(a, "share-1440-result-then-delete")
    close_dialog(a)
    a.wait("!!document.querySelector('[data-testid=\"file-row\"][data-name=\"leaves.txt\"] [data-testid=\"leaves-badge\"]')", 30)
    t.check(True, "the row shows when it leaves (the Leaves badge)")
    v, _ = stranger(t, url)
    v.click("view-open")
    t.check(v.wait_state("view-root", VIEW_END, 60) == "opened", "the stranger opens it once")
    a.reload()
    a.wait_for("drive-root", 90)
    a.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].length >= 1", 30)
    names = a.wait("(() => { const n = [...document.querySelectorAll('[data-testid=\"file-row\"]')].map((e) => e.dataset.name); return n.includes('leaves.txt') ? null : n; })()", 60)
    t.check(names == ["word.txt"], f"after its one open the file left the drive ({names})")


@scenario("share-send-tari", "Send by Tari (step 8): the address, its safety code, the C8 line, What the chain shows; sent; kind 4; the Links tab says Sent by Tari", features=FEATURES)
def share_send_tari(t):
    b = drive_page(t)
    b.wait_for("drive-empty", 30)
    address = b.wait("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]'); return e && e.textContent.startsWith('otl_esm_1') ? e.textContent : ''; })()", 90)
    t.realizer.addresses.add(address)
    t.shared["received_address"] = address
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["for-b.txt", "for-wallet.txt"])
    open_share(a, "for-b.txt")
    a.click("share-choice", "tari")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'tari'", 10)
    a.fill("send-recipient", "hello")
    a.wait("document.getElementById('tari-to-msg').textContent.length > 0", 10)
    t.check(not a.visible("send-safety") and a.attr("send-submit", "disabled") is not None, "a wrong address is explained and Send waits")
    a.fill("send-recipient", address)
    a.wait_for("send-safety", 60)
    t.check(len(safety_emoji(a, "send-safety")) == 12 and "Compare all 12 with them." in a.text("share-step-tari"), "their safety code: twelve symbols to compare")
    t.check(a.attr("send-path", "data-path") == "relay" and "Our relay sends it for you, so we learn the address, never the key." in a.text("send-path"),
            "the C8 line says who sends it")
    t.check("The fee is public." in a.text("share-step-tari"), "What the chain shows (C9-d)")
    t.check(a.attr("send-kind", "aria-checked") == "false", "They use another Ootle wallet: off by default (kind 3)")
    t.check(a.ax_unnamed() == [], f"every control named ({a.ax_unnamed()[:4]})")
    t.shot(a, "share-1440-tari")
    a.click("send-submit")
    t.check(a.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "Sent")
    tx = a.attr("send-tx", "data-tx")
    t.check(bool(re.fullmatch(r"[0-9a-f]{64}", tx or "")), "the send has a transaction id")
    t.check("It shows up under Received in their drive." in a.text("share-step-sending"), "where it shows up")
    t.shot(a, "share-1440-sent")
    close_dialog(a)
    open_share(a, "for-b.txt")
    a.click("share-tab-links")
    a.wait_for("link-row", 10)
    t.check("Sent by Tari" in a.text("link-row"), "the Links tab says Sent by Tari")
    close_dialog(a)
    t.check(wait_rule(a, "for-b.txt", "sent"), "the row wears the Tari badge: Sent by Tari")
    # Kind 4: for another Ootle wallet.
    open_share(a, "for-wallet.txt")
    a.click("share-choice", "tari")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'tari'", 10)
    a.fill("send-recipient", address)
    a.wait_for("send-safety", 60)
    a.click("send-kind")
    t.check(a.attr("send-kind", "aria-checked") == "true", "kind 4 on")
    a.click("send-submit")
    t.check(a.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "Sent for another wallet")
    t.check("Their view key opens it." in a.text("share-step-sending"), "kind 4: their view key opens it")
    t.shared["send_owner_done"] = True


@scenario("received-list", "Received (step 10): Tari arrivals, By Tari, sender hidden; open one here, Save to my drive; the drop link; the chain offline", features=FEATURES)
def received_list(t):
    address = t.shared.get("received_address")
    b = drive_page(t)
    a = drive_page(t)
    a.wait_for("drive-empty", 30)
    b_address = b.wait("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]'); return e && e.textContent.startsWith('otl_esm_1') ? e.textContent : ''; })()", 90)
    t.realizer.addresses.add(b_address)
    upload_files(t, a, ["arrives.txt"])
    open_share(a, "arrives.txt")
    a.click("share-choice", "tari")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'tari'", 10)
    a.fill("send-recipient", b_address)
    a.wait_for("send-safety", 60)
    a.click("send-submit")
    t.check(a.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "a drive sends a file by Tari to another drive")
    t.realizer.attach(b)
    b.goto(t.origin + "/drive/received")
    b.wait_for("received-drop", 60)
    b.wait("!!document.querySelector('[data-testid=\"received-row\"]')", 180)
    row = b.text("received-row")
    t.check("By Tari, sender hidden" in row and "A locked file" in row, f"the row: a locked file, By Tari, sender hidden ({row[:80]})")
    t.check(address is None or address not in row, "no sender address anywhere on the row")
    t.check(b.attr("received-row", "data-state") == "new" and b.attr("inbox-item", "data-source") == "send", "New, and it came by Tari")
    t.check("Checked" in b.text("inbox-scan") or b.attr("inbox-scan", "data-checked") is not None, "the scan line says this browser checked the chain")
    t.shot(b, "received-1440-list")
    b.click("received-open-button")
    b.wait("document.querySelector('[data-testid=\"received-open\"]')?.dataset.state === 'opened'", 120)
    t.check(b.exists("inbox-opened") and "arrives.txt" in b.text("view-text"), "it opens here, in the drive")
    t.shot(b, "received-1440-open")
    b.click("received-keep")
    b.wait("[...document.querySelectorAll('.toast')].some((e) => e.textContent.includes('Saved to your drive.'))", 120)
    b.key("Escape")
    b.wait("document.querySelector('[data-testid=\"received-row\"]')?.dataset.state === 'saved'", 30)
    t.check(b.text("received-status") == "In my drive", "the row says In my drive")
    b.goto(t.origin + "/drive")
    b.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'arrives.txt')", 60)
    t.check(True, "Save to my drive: it is the drive's own file now, locked again in this browser")
    # The drop link.
    b.goto(t.origin + "/drive/received")
    b.wait_for("drop-create", 60)
    b.click("drop-create")
    b.wait_for("drop-link", 120)
    t.check(re.fullmatch(re.escape(t.origin) + r"/d/[A-Za-z0-9_-]+", b.value("drop-link") or "") is not None, "Make my drop link: a link anyone can leave a file at")
    b.click("drop-copy")
    t.check(b.wait(f"navigator.clipboard.readText().then((x) => x === {json.dumps(b.value('drop-link'))})", 10), "Copy puts the drop link on the clipboard")
    # A purchase this browser made (pay to open's buyer page keeps it on the device): listed with its price.
    b.eval("""(async () => {
      const { loadIdentity } = await import('/app/lib/identity.js');
      const { rememberPurchase } = await import('/app/lib/purchases.js');
      await rememberPurchase(await loadIdentity({ lazy: true }), 'Pp0123456789abcdefghij',
        { url: location.origin + '/p/Pp0123456789abcdefghij#5x', price_ut: 100000, state: 'paid', demo: true });
      return true; })()""")
    b.reload()
    b.wait("!!document.querySelector('[data-testid=\"received-row\"][data-source=\"purchase\"]')", 60)
    bought = b.eval("document.querySelector('[data-testid=\"received-row\"][data-source=\"purchase\"]').textContent")
    t.check("You paid 0.1 tTARI" in bought and "Test money" in bought and b.exists("received-open-purchase"),
            f"a purchase kept on this device: what was paid, with test money, and Open ({bought[:90]})")
    # The chain can't be reached: what was found stays, and the page says so.
    c = t.actor("iphone")
    Intercept(c).add("*/api/v1/chain/utxos*", "Request", api_error("chain_unavailable", 503))
    c.goto(t.origin + "/drive?make")
    c.wait_for("drive-root", 90)
    c.goto(t.origin + "/drive/received")
    c.wait_for("received-offline", 120)
    t.check("We can't reach the chain right now." in c.text("received-offline") and "Your drop link still works." in c.text("received-offline"),
            "offline: the chain can't be reached, and the drop link still works")
    t.check(no_hscroll(c), "no horizontal scroll in Received at 390")
    t.shot(c, "received-390-offline", full_page=True)


# --- §15 step 10: the folder viewer ---------------------------------------------------------------------

def folder_with_files(t, a):
    """Trip/ with map.txt, report.dat and Day one/notes.txt, plus an empty folder Later/. -> the bytes."""
    a.wait_for("drive-empty", 30)
    new_folder(a, "Trip")
    into(a, "Trip")
    report = os.urandom(1_200_000)
    write_fixture(t, "report.dat", report)
    upload_files(t, a, ["map.txt", "report.dat", "photo-gps.jpg"])
    new_folder(a, "Day one")
    new_folder(a, "Later")
    into(a, "Day one")
    upload_files(t, a, ["notes.txt"])
    a.goto(t.origin + "/drive")
    a.wait("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === 'Trip')", 60)
    with open(fixture_files(t, ["map.txt"])[0], "rb") as f:
        return {"map.txt": f.read(), "report.dat": report, "Day one/notes.txt": NOTES.encode()}


def share_folder(t, a, opens="once"):
    open_share(a, "Trip")
    t.check("Anyone who opens it sees all 4 files in it." in a.text("share-folder-note"), "a folder says everyone sees all its files")
    to_opens(a)
    t.check("One visit of 30 minutes. Then the link ends." in a.text("share-step-opens") and not a.exists("share-then-delete"),
            "Once on a folder is one visit of {ticket_min} minutes; a folder's files stay in the drive (no Delete it after)")
    if opens != "once":
        a.click("share-choice", opens)
    url = make_link(a)
    t.check("Each open is one visit of 30 minutes." in a.text("share-say-more"), "the result says what a visit is")
    t.shot(a, f"share-1440-result-folder-{opens}")
    close_dialog(a)
    return url


@scenario("folder-zip", "A folder link (step 10): one visit, the names opened here, Save one, Download all as a ZIP that Python's zipfile checks", features=FEATURES)
def folder_zip(t):
    a = drive_page(t)
    want = folder_with_files(t, a)
    url = share_folder(t, a)
    t.check(wait_rule(a, "Trip", "once"), "the folder card wears its rule")
    v, state = stranger(t, url)
    t.check(state == "ready" and v.attr("view-root", "data-kind") == "folder", f"a folder link's first screen ({state})")
    t.check(v.eval("document.body.dataset.look") == "drive" and v.eval("getComputedStyle(document.body).fontFamily").startswith("Geist"),
            "a folder link takes the drive's look")
    t.check("One visit of 30 minutes." in v.text("view-root") and "6 things inside" in v.text("view-root"), f"what it is, before anything is used ({v.text('view-root')[:120]})")
    t.shot(v, "folder-1440-ready")
    v.click("view-open")
    v.wait_for("folder-view", 60)
    names = v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].map((e) => e.dataset.name)")
    t.check(names == ["Day one", "Later", "map.txt", "photo-gps.jpg", "report.dat"], f"folders first, then files, names opened in this browser ({names})")
    t.check("This visit ends in 30 minutes." in v.text("fv-visit"), "the visit's countdown")
    t.check(v.attr("view-views-left", "data-left") == "0" and "last open" in v.text("view-views-left"), "a Once folder: this was its open")
    t.check(not any("Trip" in r["url"] or "map.txt" in r["url"] for r in v.requests), "no name in any request")
    t.shot(v, "folder-1440-open")
    v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === 'Day one').querySelector('[data-testid=\"fv-open\"]').click()")
    v.wait("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].map((e) => e.dataset.name).join() === 'notes.txt'", 10)
    t.check(v.text("fv-crumbs").replace("\n", "") == "TripDay one", f"breadcrumbs inside the folder ({v.text('fv-crumbs')})")
    before = os.listdir(v.downloads) if os.path.isdir(v.downloads) else []
    v.click("fv-save")
    path = downloaded(v, before, 60)
    t.check(path is not None and open(path, "rb").read() == NOTES.encode(), "Save one file: it is the file")
    v.eval("document.querySelector('[data-testid=\"fv-crumbs\"] button').click()")
    v.wait("document.querySelectorAll('[data-testid=\"fv-row\"]').length === 5", 10)
    before = os.listdir(v.downloads)
    v.click("fv-zip")
    path = downloaded(v, before, 120)
    t.check(path is not None, "Download all gives one file")
    ok = False
    try:
        z = zipfile.ZipFile(path)
        bad = z.testzip()
        got = {i.filename: z.read(i.filename) for i in z.infolist() if not i.is_dir()}
        dirs = sorted(i.filename for i in z.infolist() if i.is_dir())
        ok = bad is None and all(got.get(k) == v_ for k, v_ in want.items()) and "photo-gps.jpg" in got and dirs == ["Later/"] \
            and all(i.compress_type == zipfile.ZIP_STORED and i.flag_bits & 0x800 for i in z.infolist())
        t.check(ok, f"Python's zipfile: every CRC good, the files byte for byte, the empty folder kept ({sorted(got)}, {dirs}, {bad})")
    except zipfile.BadZipFile as e:
        t.check(False, f"the download is a ZIP ({e})")
    w, state = stranger(t, url)
    t.check(state == "burned", f"the link ended with its one visit ({state})")
    a.reload()
    a.wait_for("drive-root", 90)
    t.check(wait_rule(a, "Trip", "ended") and table_names(a) == ["Trip"], "the folder and its files stay in the drive")


@scenario("folder-viewer", "The folder viewer on a phone (step 10): a few visits, one by one beyond zip_max_bytes_phone, a picture opens here; the visit ends", features=FEATURES)
def folder_viewer(t):
    a = drive_page(t)
    folder_with_files(t, a)
    url = share_folder(t, a, opens="few")
    p = t.actor("iphone")
    Intercept(p).add("*/api/v1/config", "Response", lambda body: {**body, "folders": {**body["folders"], "zip_max_bytes_phone": 1024}})
    p.goto(url)
    t.check(p.wait_state("view-root", VIEW_ASK, 60) == "ready", "the phone's first screen")
    t.check("3 visits left. Each visit lasts 30 minutes." in p.text("view-root") and p.attr("view-views-left", "data-left") == "3", "A few times on a folder: visits")
    t.check(no_hscroll(p), "no horizontal scroll at 390 (ready)")
    t.shot(p, "folder-390-ready")
    p.click("view-open")
    p.wait_for("folder-view", 60)
    t.check(not p.exists("fv-zip") and "one by one" in p.text("fv-one-by-one"), "a phone beyond zip_max_bytes_phone: one by one, no Download all")
    t.check("2 visits left." in p.text("view-views-left"), "visits left after this one")
    t.check(no_hscroll(p), "no horizontal scroll at 390 (open)")
    t.shot(p, "folder-390-open", full_page=True)
    p.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === 'photo-gps.jpg').querySelector('[data-testid=\"fv-open\"]').click()")
    p.wait("document.querySelector('[data-testid=\"fv-preview\"] .fv-preview-body')?.dataset.state === 'open'", 60)
    t.check(p.exists("view-image") and p.exists("fv-preview-save"), "a picture opens here, with Save")
    t.shot(p, "folder-390-preview")
    p.key("Escape")
    # The visit's clock: a short visit, to see it end.
    d = t.actor()
    soon = {}
    Intercept(d).add("*/api/v1/config", "Response", lambda body: {**body, "retention": {**body["retention"], "ticket_s": 20}}) \
        .add("*/api/v1/s/*/open", "Response", lambda body: soon.setdefault("body", {**body, "ticket_expires_at": int(time.time()) + 20}))
    d.goto(url)
    d.wait_state("view-root", VIEW_ASK, 60)
    d.click("view-open")
    d.wait_for("folder-view", 60)
    t.check(d.text("fv-visit").startswith("This visit ends in a minute."), f"the countdown counts down ({d.text('fv-visit')})")
    state = d.wait("document.querySelector('[data-testid=\"folder-view\"]')?.dataset.state === 'ended' ? 'ended' : ''", 90)
    t.check(state == "ended" and "This visit ended." in d.text("fv-visit") and d.eval("[...document.querySelectorAll('[data-testid=\"fv-save\"]')].every((b) => b.disabled)"),
            "when the visit ends it says so, and Save stops")
    t.shot(d, "folder-1440-ended")


@scenario("received-folder", "A folder sent by Tari (steps 8 and 10): it arrives as A locked folder, opens here as a visit, and Save to my drive locks the whole tree again as the drive's own", features=FEATURES)
def received_folder(t):
    b = drive_page(t)
    b_address = b.wait("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]'); return e && e.textContent.startsWith('otl_esm_1') ? e.textContent : ''; })()", 90)
    t.realizer.addresses.add(b_address)
    a = drive_page(t)
    want = folder_with_files(t, a)
    open_share(a, "Trip")
    a.click("share-choice", "tari")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'tari'", 10)
    a.fill("send-recipient", b_address)
    a.wait_for("send-safety", 60)
    a.click("send-submit")
    t.check(a.wait_state("send-status", ("delivered", "failed"), 180) == "delivered", "a folder goes by Tari like a file")
    close_dialog(a)
    t.check(wait_rule(a, "Trip", "sent"), "the folder card wears Sent by Tari")
    t.realizer.attach(b)
    b.goto(t.origin + "/drive/received")
    b.wait("!!document.querySelector('[data-testid=\"received-row\"]')", 180)
    t.check("A locked folder" in b.text("received-row") and "By Tari, sender hidden" in b.text("received-row"),
            f"it arrives as a locked folder, sender hidden ({b.text('received-row')[:80]})")
    b.click("received-open-button")
    b.wait("document.querySelector('[data-testid=\"received-open\"]')?.dataset.state === 'opened'", 120)
    names = b.eval("[...document.querySelectorAll('#rec-open [data-testid=\"fv-row\"]')].map((e) => e.dataset.name)")
    t.check(names == ["Day one", "Later", "map.txt", "photo-gps.jpg", "report.dat"], f"it opens here as a visit, names opened in this browser ({names})")
    t.check(b.exists("fv-visit") and b.exists("fv-zip"), "with its visit and Download all")
    t.shot(b, "received-1440-folder")
    b.click("fv-keep")
    b.wait("[...document.querySelectorAll('.toast')].some((e) => e.textContent.includes('Saved to your drive.'))", 180)
    b.key("Escape")
    b.goto(t.origin + "/drive")
    b.wait("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === 'Trip')", 60)
    into(b, "Trip")
    b.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].length === 3", 60)
    t.check(sorted(table_names(b)) == ["Day one", "Later", "map.txt", "photo-gps.jpg", "report.dat"],
            f"Save to my drive: the folder and its folders are the drive's own now ({table_names(b)})")
    into(b, "Day one")
    b.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].map((e) => e.dataset.name).join() === 'notes.txt'", 60)
    t.check(len(want) == 3, "the nested file came along")
