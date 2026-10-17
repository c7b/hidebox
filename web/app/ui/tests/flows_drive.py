# SPDX-License-Identifier: MIT
"""The drive's flows (lane app1; 16-drive-design §2, §12; 16-drive-architecture §6.2, §6.4), against the
real API (`--dev`) in headless Chromium, with the server lane's folder API faked in front of it until it is
merged (drivefake.py; the fake turns itself off when the dev server reports features.folders).

drive-shell, drive-make, drive-open-keyfile, drive-folders, storage-meter and drive-budget (A-06d) are
§15 steps 3 and 5."""
import gzip
import json
import os
import re
import time

from drivefake import DriveFake
from flows import downloaded, no_hscroll, same_origin, scenario

# The drive's features (off in config.py until the routes switch over). run.py starts a dev server with
# them on for a flow that asks (lane app2's run.py); until then the flows run on drivefake.py.
FEATURES = ("folders",)


def make_drive(t, device="desktop", fake=None, **kw):
    """/drive?make: the key is made in this browser at once and the drive opens (the home page's Make my
    drive lands here). -> (page, fake)"""
    page = t.actor(device, **kw)
    fake = (fake or DriveFake(t.origin)).attach(page)
    page.goto(t.origin + "/drive?make")
    page.wait_for("drive-root", 90)
    page.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    return page, fake


def eventually(page, expr, timeout=5):
    """A check on something the page does a moment later (focus after a dialog opens): its value, or False."""
    try:
        return page.wait(expr, timeout)
    except TimeoutError:
        return False


def table_names(page):
    return page.eval("[...document.querySelectorAll('[data-testid=\"file-row\"], [data-testid=\"folder-card\"]')]"
                     ".filter((e) => !e.hidden).map((e) => e.dataset.name)")


def fixture_files(t, names):
    paths = []
    for name in names:
        path = t.fixture(name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{name}: a small file for the drive's flows.\n")
        paths.append(path)
    return paths


def upload_files(t, page, names, count_before=None):
    """New → Upload files, through the real file input; waits until each one is listed."""
    page.wait("!!document.querySelector('[data-testid=\"upload-files-input\"]')", 30)
    page.set_files("upload-files-input", fixture_files(t, names))
    page.wait(f"(() => {{ const n = [...document.querySelectorAll('[data-testid=\"file-row\"]')].map((e) => e.dataset.name);"
              f" return {json.dumps(names)}.every((x) => n.includes(x)); }})()", 120)


@scenario("drive-shell", "The drive's shell (step 3): sidebar, header, search, Upgrade, the look; Geist only, pinned; no ootle-wasm before the list", features=FEATURES)
def drive_shell(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    early = [r["url"] for r in a.requests]
    t.check(not any("ootle_wasm" in u for u in early), "the drive's first screen renders before ootle-wasm loads (A-06d: lazy Tari keys)")
    nav = a.eval("[...document.querySelectorAll('aside .sidebar-menu-button[data-view]')].map((e) => e.textContent.trim())")
    t.check(nav == ["My drive", "Received", "Shared", "Activity", "Trash", "Storage"], f"the sidebar names its six places ({nav})")
    t.check(a.attr("nav-mine", "aria-current") == "page", "My drive is the current page")
    t.check(a.exists("upgrade") and a.exists("drive-search") and a.exists("new-button"), "the header has search and Upgrade; the sidebar has New")
    t.check(int(a.attr("quota-bar", "data-limit") or 0) > 0, "the storage meter shows the drive's limit")
    t.check(a.eval("document.querySelectorAll('.btn:not([data-variant])').length") == 1,
            "one filled primary on the screen (the empty drive's Upload a folder)")
    t.check(a.exists("empty-upload-dir") and a.exists("empty-upload"), "a computer: Upload a folder first, Upload files beside it")
    addr = a.wait("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]'); return e && e.textContent.startsWith('otl_esm_1') ? e.textContent : ''; })()", 90)
    t.check(addr.startswith("otl_esm_1"), "the Tari address row fills in once the Tari keys load, after the list")
    a.click("copy-address")
    t.check(a.wait(f"navigator.clipboard.readText().then((x) => x === {json.dumps(addr)})", 10), "Copy puts the address on the clipboard")
    fonts = a.wait("document.fonts.ready.then(() => document.fonts.check('14px Geist') && getComputedStyle(document.body).fontFamily.startsWith('Geist'))", 20)
    t.check(fonts, "the drive is set in Geist")
    woff = sorted({r["url"][len(t.origin):] for r in a.requests if r["url"].endswith((".woff2", ".woff", ".ttf", ".otf"))})
    t.check(woff == ["/shared/fonts/geist/Geist-Variable.woff2"], f"one font file, the pinned Geist ({woff})")
    t.check(not same_origin(t, a), f"no third-party request ({same_origin(t, a)[:3]})")
    t.check(a.ax_unnamed() == [], f"every control has a name ({a.ax_unnamed()[:5]})")
    t.shot(a, "drive-1440-empty")
    a.key("b", modifiers=2)
    t.check(a.wait("document.querySelector('.sidebar-wrapper').dataset.state === 'collapsed'", 5), "Ctrl+B folds the sidebar")
    a.key("b", modifiers=2)
    a.eval("document.querySelector('[aria-controls=\"theme-menu\"]').click()")
    a.wait("!document.getElementById('theme-menu').hidden", 5)
    a.eval("document.querySelector('#theme-menu [data-value=\"dark\"]').click()")
    t.check(a.wait("document.documentElement.dataset.theme === 'dark' && localStorage.getItem('mutis.theme') === 'dark'", 5),
            "the look: dark, remembered in this browser")
    t.check(a.eval("getComputedStyle(document.body).backgroundColor") != "rgb(255, 255, 255)", "dark paints the page")
    t.shot(a, "drive-1440-dark")
    a.eval("document.querySelector('[aria-controls=\"theme-menu\"]').click()")
    a.wait("!document.getElementById('theme-menu').hidden", 5)
    a.eval("document.querySelector('#theme-menu [data-value=\"system\"]').click()")
    for view, title in (("shared", "Nothing is shared."), ("trash", "Trash is empty."), ("activity", "Nothing happened yet.")):
        a.click(f"nav-{view}")
        a.wait(f"location.pathname === '/drive/{view}' && document.querySelector('[data-testid=\"locker-root\"]')?.textContent.includes({json.dumps(title)})", 30)
        t.check(a.attr(f"nav-{view}", "aria-current") == "page", f"/drive/{view} in the page, its place marked")
    a.eval("history.back()")
    a.wait("location.pathname === '/drive/trash'", 10)
    t.check(True, "the back button walks the drive's places")
    a.goto(t.origin + "/drive/nothing-here")
    a.wait("document.querySelector('[data-testid=\"locker-root\"]')?.textContent.includes(\"This page isn't here.\")", 30)
    t.check(True, "an unknown drive address says so inside the drive")


@scenario("drive-make", "Make my drive on a phone (step 5): the key at once, the drive opens, Save key file (locked), reload opens it again", features=FEATURES)
def drive_make(t):
    a = t.actor("iphone")
    DriveFake(t.origin).attach(a)
    a.goto(t.origin + "/drive")
    a.wait_for("drive-start", 60)
    first = a.text("drive-start")
    t.check("Make my drive" in first and "Open my drive" in first and "No email, no password." in first,
            "a browser without a drive: Make my drive or Open my drive (C17)")
    t.check(no_hscroll(a), "no horizontal scroll on the start screen at 390")
    t.shot(a, "drive-390-start")
    a.click("drive-make")
    a.wait_for("drive-root", 90)
    a.wait_for("drive-empty", 60)
    t.check(a.exists("key-banner"), "the drive opens with the Save-my-key reminder (an outline action, never a primary)")
    t.check(a.exists("empty-upload") and not a.exists("empty-upload-dir"), "a phone: Upload files first (iOS has no folder picker)")
    t.check(a.visible("drive-root") and a.eval("getComputedStyle(document.querySelector('.fab')).display") != "none",
            "the floating New button on a phone")
    t.check(no_hscroll(a), "no horizontal scroll in the drive at 390")
    t.shot(a, "drive-390-empty", full_page=True)
    a.eval("document.querySelector('[data-sidebar-trigger]').click()")
    a.wait("!document.getElementById('side-sheet').hidden", 10)
    t.check(a.eval("document.querySelector('#side-sheet .sidebar-menu-button[href=\"/drive/storage\"]') !== null"), "the sidebar opens as a sheet on a phone")
    t.shot(a, "drive-390-sheet")
    a.key("Escape")
    a.wait("document.getElementById('side-sheet').hidden", 10)
    a.click("key-reminder-save")
    a.wait_for("key-dialog", 10)
    a.click("key-save-file")
    t.check(a.wait("document.querySelector('[data-testid=\"key-dialog\"]').textContent.includes('Type a passphrase first')", 5),
            "the key file is locked with a passphrase unless the lock is turned off (P-15)")
    a.fill("key-passphrase", "orchid lantern quiet river")
    a.click("key-save-file")
    path = downloaded(a, timeout=20)
    key_text = open(path, encoding="utf-8").read() if path else ""
    t.check("Locked key:" in key_text and "MUTIS-" not in key_text, "the key file holds the key locked, never in plain form")
    t.check(a.wait("!document.querySelector('[data-testid=\"key-banner\"]')", 10), "the reminder goes once the key is saved")
    t.shared["drive_key"] = key_text
    t.check(a.eval("localStorage.getItem('mutis.drive')") == "1", "a new drive sets the site's flag, never the key (the home paints Open my drive)")
    stored = a.eval("JSON.stringify(localStorage)")
    t.check("MUTIS-" not in stored and "Locked key" not in stored, "localStorage holds no key material")
    a.reload()
    a.wait_for("drive-root", 60)
    t.check(not a.exists("drive-start"), "a reload opens the drive again (the key lives in this browser)")
    n = t.actor("narrow")
    n.goto(t.origin + "/drive")
    n.wait_for("drive-start", 60)
    t.check(no_hscroll(n), "no horizontal scroll at 360")


@scenario("drive-open-keyfile", "Open my drive with the key file in a clean browser (step 5): the same drive, the same files", features=FEATURES)
def drive_open_keyfile(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    a.eval("document.querySelector('[data-testid=\"acct-key\"]').click()")
    a.wait_for("key-dialog", 10)
    a.eval("document.querySelector('[data-testid=\"key-protect\"]').click()")
    a.click("key-save-file")
    path = downloaded(a, timeout=20)
    key_text = open(path, encoding="utf-8").read() if path else ""
    t.check("Key: MUTIS-" in key_text, "with the lock off, the file holds the key in plain form (the owner chose)")
    a.key("Escape")
    upload_files(t, a, ["passport.txt", "lease.txt"])
    b = t.actor("desktop")
    fake.attach(b)
    b.goto(t.origin + "/drive?open")
    b.wait_for("open-dialog", 60)
    b.click("restore-open")
    with open(t.fixture("drive-key.txt"), "w", encoding="utf-8") as f:
        f.write(key_text)
    b.set_files("restore-file", [t.fixture("drive-key.txt")])
    b.wait("document.querySelector('[data-testid=\"restore-text\"]').value.includes('MUTIS-')", 10)
    b.click("restore-submit")
    b.wait_for("drive-root", 60)
    b.wait("document.querySelectorAll('[data-testid=\"file-row\"]').length === 2", 60)
    t.check(sorted(table_names(b)) == ["lease.txt", "passport.txt"], f"restored elsewhere: the same files, named in this browser ({table_names(b)})")
    t.check(b.eval("localStorage.getItem('mutis.drive')") == "1", "an opened drive sets the site's flag (the home paints Open my drive)")
    b.eval("document.querySelector('[data-testid=\"acct-lock\"]').click()")
    b.wait_for("forget-device", 10)
    b.click("forget-device")
    t.check(b.wait("location.pathname === '/' && localStorage.getItem('mutis.drive') === null", 20),
            "Lock my drive clears the flag (the home paints Make my drive again)")
    bad = t.actor("desktop")
    bad.goto(t.origin + "/drive?open")
    bad.wait_for("open-dialog", 60)
    bad.fill("restore-text", "MUTIS-00000-00000")
    bad.click("restore-submit")
    t.check(bad.wait("document.querySelector('[data-testid=\"open-dialog\"] [data-testid=\"error-banner\"]')?.textContent.includes('does not open a drive')", 10),
            "a wrong key: That key does not open a drive")


@scenario("drive-folders", "Folders (step 5): New folder, open it, breadcrumbs, a file inside, counts, search in place", features=FEATURES)
def drive_folders(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    a.eval("document.dispatchEvent(new CustomEvent('drive:new', { detail: 'folder' }))")
    a.wait_for("new-folder-dialog", 10)
    a.fill("folder-name", "Trip")
    a.click("folder-create")
    a.wait("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === 'Trip')", 30)
    t.check(("POST", "/folders") in fake.calls or fake.native, "POST /folders made the folder (its name sealed in this browser)")
    card = a.eval("document.querySelector('[data-testid=\"folder-card\"]').dataset.id")
    a.eval("document.querySelector('[data-testid=\"folder-card\"] .folder-icon').click()")
    a.wait(f"location.pathname === '/drive/folders/{card}'", 10)
    a.wait_for("breadcrumbs", 30)
    t.check(a.text("breadcrumbs").replace("\n", "") == "My driveTrip", f"breadcrumbs: My drive › Trip ({a.text('breadcrumbs')})")
    t.check("Trip" in a.eval("document.title"), "the tab names the folder (in this browser)")
    a.wait_for("drive-empty", 10)
    upload_files(t, a, ["map.txt"])
    t.check(table_names(a) == ["map.txt"], "the file lands in the open folder")
    t.shot(a, "drive-1440-folder")
    a.eval("document.querySelector('[data-testid=\"breadcrumbs\"] a').click()")
    a.wait("location.pathname === '/drive'", 10)
    a.wait("!!document.querySelector('[data-testid=\"folder-card\"]')", 30)
    t.check(table_names(a) == ["Trip"], f"My drive shows the folder, not the file inside it ({table_names(a)})")
    t.check("1 item" in a.text("folder-card"), "the folder card counts what it holds")
    upload_files(t, a, ["notes.txt"])
    a.fill("drive-search", "zzz")
    a.wait("!document.querySelector('[data-no-match]').hidden", 5)
    t.check(table_names(a) == [], "search filters in place: nothing matches")
    a.fill("drive-search", "tri")
    a.wait("document.querySelector('[data-no-match]').hidden", 5)
    t.check(table_names(a) == ["Trip"], f"search: Tri finds the folder ({table_names(a)})")
    note = a.eval("document.getElementById('search-note').textContent")
    t.check(note == "Search runs in this browser. Our server can't read your file names.", "search says where it runs (C43)")
    t.check(not any("zzz" in r["url"] or "tri" in r["url"].lower().split("?", 1)[-1] for r in a.requests if "/api/" in r["url"]),
            "search terms never reach our server")
    t.shot(a, "drive-1440-search")


@scenario("storage-meter", "Storage (step 5): the meter in padded sizes, Get more space with test money, the rules of space", features=FEATURES)
def storage_meter(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["photo-gps.jpg", "notes.txt"])
    before = int(a.attr("quota-bar", "data-limit"))
    a.click("upgrade")
    a.wait_for("storage-meter", 60)
    t.check(a.eval("location.pathname + location.hash") == "/drive/storage#more", "Upgrade opens Storage at Get more space")
    used = int(a.attr("storage-meter", "data-used"))
    t.check(used > 0 and used == int(a.attr("quota-bar", "data-used")), f"the meter counts the padded sizes the server counts ({used} B)")
    rules = a.eval("document.querySelector('#how-h').closest('.card').textContent")
    t.check(all(x in rules for x in ("fair share", "On your first day", "Files in the trash still use space", "Any file can delete itself",
                                    "we delete what's in it", "nothing goes for")), "the rules of space, with their numbers from /config")
    packs = a.eval("document.querySelectorAll('[data-testid=\"storage-pack\"]').length")
    t.check(packs >= 1, f"the packs from /config ({packs})")
    t.shot(a, "storage-1440", full_page=True)
    a.click("pack-s30")
    a.wait_for("invoice-address", 60)
    t.check(a.value("invoice-address").startswith("otl_esm_1"), "the invoice: our address with its reference inside")
    t.check("tTARI is test money, worth nothing" in a.text("invoice-dialog"), "the testnet line on the money screen (C19-k)")
    t.check(a.eval("document.querySelectorAll('[data-testid=\"invoice-dialog\"] .dialog-footer .btn:not([data-variant])').length") == 1,
            "one primary: Pay with test money")
    t.shot(a, "storage-1440-invoice")
    a.click("demo-pay")
    a.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 180)
    steps = a.eval("[...document.querySelectorAll('[data-testid=\"pay-step\"]')].map(e => e.dataset.step + ':' + e.dataset.done)")
    t.check(steps == ["waiting:true", "seen:true", "proven:true", "added:true"], f"the steps reach Added, naming this mode's checks ({steps})")
    a.wait(f"Number(document.querySelector('[data-testid=\"quota-bar\"]').dataset.limit) >= {before + 2 * 1024 ** 3}", 30)
    t.check(True, "the sidebar meter grows by the pack")
    a.key("Escape")
    a.wait("!document.querySelector('[data-testid=\"invoice-dialog\"]') || document.querySelector('[data-testid=\"invoice-dialog\"]').hidden", 10)
    legend = a.wait("document.querySelector('.legend')?.textContent ?? ''", 30)
    t.check("Space you paid for" in legend, "the legend names the paid space (violet only for space paid with tTARI)")
    # Sixth pass: one pack at a time. The pack held says until when and can't be bought again before its last
    # days; the other pack waits; the rule and the renewal date are said in words.
    a.wait("document.querySelector('[data-testid=\"pack-s30\"]')?.disabled === true", 30)
    t.check("Yours until" in a.text("pack-s30") and a.eval("document.querySelector('[data-testid=\"pack-m30\"]').disabled"),
            "one pack at a time: the pack held says until when, the other waits")
    t.check(a.exists("pack-renew-from") and "One pack at a time" in a.text("pack-rule"), "the rule and the renewal date, in words")
    t.shot(a, "storage-1440-paid", full_page=True)


# A-06d (16-drive-architecture §6.4): from navigation to /drive until the file table renders for a drive
# of 20 items, phone profile: gzip -9 of every /app/, /shared/ and /vendor/ file requested, without the
# Geist file (at most 2 font files, asserted apart) and without ootle-wasm (it must not load before then).
# First measured on the merged drive (integration pass 1, 2026-10-13): 109,318 B in 36 files. The ceiling
# (§15 step 12) keeps about a fifth of headroom for what the drive's first screen still gains.
A06D_CEILING = 128 * 1024


@scenario("drive-budget", "A-06d: what /drive loads until the file table renders for 20 items (phone); no ootle-wasm before it", features=FEATURES)
def drive_budget(t):
    a, fake = make_drive(t, "iphone")
    a.wait_for("drive-empty", 30)
    made = a.eval("""(async () => {
      const { loadIdentity } = await import('/app/lib/identity.js');
      const session = await import('/app/lib/session.js');
      const { sealItem } = await import('/app/lib/seal.js');
      const identity = await loadIdentity({ lazy: true });
      await session.ensureSession(identity);
      for (let i = 0; i < 20; i++) await sealItem({ text: 'note ' + i }, { headers: session.authHeaders(), keepFor: identity });
      return 20; })()""", timeout=180)
    a.requests.clear()
    a.goto(t.origin + "/drive")
    a.wait("document.querySelectorAll('[data-testid=\"file-row\"]').length === 20", 60)
    seen = [r["url"] for r in a.requests]
    dist = os.path.join(t.work, "dist")
    total, files, fonts = 0, [], set()
    for u in sorted({u.split("?")[0] for u in seen if u.startswith((t.origin + "/app/", t.origin + "/shared/", t.origin + "/vendor/"))}):
        rel = u[len(t.origin) + 1:]
        if rel.endswith(".woff2"):
            fonts.add(rel)
            continue
        if "ootle-wasm" in rel or "ootle_wasm" in rel:
            continue
        path = os.path.join(dist, rel)
        if os.path.isfile(path):
            total += len(gzip.compress(open(path, "rb").read(), 9))
            files.append(rel)
    t.check(made == 20, "a drive of 20 items")
    t.check(not any("ootle_wasm" in u for u in seen), "no ootle-wasm before the file table renders")
    t.check(len(fonts) <= 2, f"at most 2 font files ({sorted(fonts)})")
    t.check(total <= A06D_CEILING, f"A-06d: {total} B compressed until the table renders, {len(files)} files (≤ {A06D_CEILING} B)")
    print(f"  A-06d measured: {total} B gzip -9, files: {', '.join(files)}")


# --- §15 step 7: uploads, move, rename, trash, Delete it after ----------------------------------------

def row_menu(page, name, value):
    """Opens the ⋮ menu of the row or folder card named `name` and picks `value`."""
    page.eval(f"""(() => {{ const el = [...document.querySelectorAll('[data-testid="file-row"], [data-testid="folder-card"]')]
      .find((e) => e.dataset.name === {json.dumps(name)}); el.querySelector('[data-testid="row-kebab"]').click(); }})()""")
    page.wait("!document.getElementById('row-menu').hidden", 10)
    page.click("menu-" + value)


def text_of(path):
    with open(path, "rb") as f:
        return f.read()


@scenario("drive-upload-files", "Upload files (step 7): each locks here, then uploads; the panel says so; the owner downloads the same bytes, the photo without its location", features=FEATURES)
def drive_upload_files(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    names = ["notes.txt", "photo-gps.jpg", "report.dat"]
    upload_files(t, a, names)
    a.wait_for("upload-panel", 10)
    stages = a.eval("[...document.querySelectorAll('[data-testid=\"upload-row\"] .stage')].map((e) => e.textContent.trim())")
    t.check(stages == ["Locked and saved"] * 3, f"the panel: each file Locked and saved ({stages})")
    t.check("3 uploads done" in a.text("upload-panel"), "the panel's head counts them")
    t.check(a.eval("document.querySelector('[data-testid=\"upload-panel\"] [aria-live]').textContent") == "3 files locked and saved.",
            "a screen reader hears it once")
    t.shot(a, "drive-1440-uploaded")
    a.eval("document.documentElement.dataset.theme = 'dark'")
    t.shot(a, "drive-1440-uploaded-dark")
    a.eval("delete document.documentElement.dataset.theme")
    before = os.listdir(a.downloads) if os.path.isdir(a.downloads) else []
    a.eval("[...document.querySelectorAll('[data-testid=\"file-row\"]')].find((e) => e.dataset.name === 'notes.txt').querySelector('.name').click()")
    got = downloaded(a, before, 30)
    t.check(got and text_of(got) == text_of(t.fixture("notes.txt")), "the owner's download is the same bytes, decrypted here")
    before = os.listdir(a.downloads)
    row_menu(a, "photo-gps.jpg", "download")
    photo = downloaded(a, before, 30)
    t.check(photo and text_of(photo) != text_of(t.fixture("photo-gps.jpg")) and b"GPS" not in text_of(photo)[:4096],
            "the photo went up without its location data (§4.13)")
    t.check(no_hscroll(a), "no horizontal scroll with files")
    p, _ = make_drive(t, "iphone")
    p.wait_for("drive-empty", 30)
    upload_files(t, p, ["notes.txt"])
    t.check(no_hscroll(p), "a phone: rows are two lines, no horizontal scroll")
    t.shot(p, "drive-390-files", full_page=True)
    p.eval("document.documentElement.dataset.theme = 'dark'")
    t.shot(p, "drive-390-files-dark", full_page=True)


@scenario("drive-upload-folder-input", "Upload a folder with the folder picker (step 7): folders top-down, files inside, names here only", features=FEATURES)
def drive_upload_folder_input(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    root = os.path.join(t.work, "fixtures", "Trip")
    os.makedirs(os.path.join(root, "day one"), exist_ok=True)
    for rel, body in (("plan.txt", "the plan"), ("day one/map.txt", "the map"), ("day one/.DS_Store", "junk")):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(body)
    a.wait("!!document.querySelector('[data-testid=\"upload-dir-input\"]')", 30)
    a.set_files("upload-dir-input", [root])
    a.wait("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === 'Trip')", 120)
    t.check(table_names(a) == ["Trip"], f"one folder at the root ({table_names(a)})")
    t.check(sum(1 for c in fake.calls if c == ("POST", "/folders")) == 2 or fake.native, "two folders made, parents first")
    a.eval("document.querySelector('[data-testid=\"folder-card\"] .folder-icon').click()")
    a.wait("document.querySelectorAll('[data-testid=\"folder-card\"], [data-testid=\"file-row\"]').length === 2", 30)
    t.check(sorted(table_names(a)) == ["day one", "plan.txt"], f"inside Trip: day one and plan.txt ({table_names(a)})")
    a.eval("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === 'day one').querySelector('.folder-icon').click()")
    a.wait("document.querySelectorAll('[data-testid=\"file-row\"]').length === 1", 30)
    t.check(table_names(a) == ["map.txt"], "inside day one: map.txt, and no .DS_Store")
    t.check(a.text("breadcrumbs").replace("\n", "") == "My driveTripday one", "breadcrumbs: My drive › Trip › day one")
    sent = " ".join(str(r.get("headers")) + r["url"] for r in a.requests)
    t.check("Trip" not in sent and "map.txt" not in sent, "no folder or file name in any request")


@scenario("drive-upload-folder-drop", "Drop a folder (step 7): the entries are read inside the drop, every batch walked, the overlay names the folder", features=FEATURES)
def drive_upload_folder_drop(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    a.wait("!!document.querySelector('[data-testid=\"drop-overlay\"]')", 30)
    a.eval("""(() => {
      const file = (name) => ({ isFile: true, isDirectory: false, name, file: (ok) => ok(new File(['dropped ' + name], name, { type: 'text/plain' })) });
      const dir = (name, children) => ({ isDirectory: true, isFile: false, name, createReader() { let i = 0;
        return { readEntries: (ok) => { const out = children.slice(i, i + 2); i += 2; setTimeout(() => ok(out), 5); } }; } });
      const tree = dir('Box', [file('one.txt'), file('two.txt'), dir('Inner', [file('three.txt')]), file('Thumbs.db')]);
      const dt = { types: ['Files'], items: [{ kind: 'file', webkitGetAsEntry: () => tree }], files: [] };
      const ev = (type) => { const e = new Event(type, { bubbles: true, cancelable: true }); Object.defineProperty(e, 'dataTransfer', { value: dt }); return e; };
      document.body.dispatchEvent(ev('dragenter'));
      window.__overlay = !document.querySelector('[data-testid="drop-overlay"]').hidden && document.querySelector('[data-testid="drop-overlay"]').textContent;
      document.body.dispatchEvent(ev('drop'));
    })()""")
    overlay = a.eval("window.__overlay")
    t.check(overlay and "Drop to lock and upload" in overlay and "Into My drive" in overlay, f"the overlay: Drop to lock and upload, Into My drive ({overlay})")
    a.wait("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === 'Box')", 120)
    a.wait("document.querySelector('[data-testid=\"upload-panel\"]')?.textContent.includes('3 uploads done')", 60)
    a.eval("document.querySelector('[data-testid=\"folder-card\"] .folder-icon').click()")
    a.wait("document.querySelectorAll('[data-testid=\"folder-card\"], [data-testid=\"file-row\"]').length === 3", 30)
    t.check(sorted(table_names(a)) == ["Inner", "one.txt", "two.txt"], f"Box holds Inner, one.txt and two.txt; Thumbs.db skipped ({table_names(a)})")
    t.check(a.eval("document.querySelector('[data-testid=\"drop-overlay\"]').hidden"), "the overlay goes after the drop")


@scenario("drive-move-rename", "Move and rename (step 7): This shares it too, Move here, Undo; a new name sealed here", features=FEATURES)
def drive_move_rename(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    for name in ("Shared box", "Private box"):
        # wait out the last folder's closing dialog first (the race a2d3dd7 fixed in flows_share.py)
        a.wait("![...document.querySelectorAll('[data-testid=\"new-folder-dialog\"]')].some((d) => !d.hidden)", 10)
        a.eval("document.dispatchEvent(new CustomEvent('drive:new', { detail: 'folder' }))")
        a.wait("[...document.querySelectorAll('[data-testid=\"new-folder-dialog\"]')].some((d) => !d.hidden && d.dataset.state === 'open')", 10)
        a.fill("folder-name", name)
        a.click("folder-create")
        a.wait(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === {json.dumps(name)})", 30)
    shared = a.eval("[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === 'Shared box').dataset.id")
    if fake.native:       # lane S's folder links: one made with the product's own lib (lane A2's dialog does the same)
        a.eval("""(async () => {
          const { loadIdentity } = await import('/app/lib/identity.js');
          const session = await import('/app/lib/session.js');
          const { listAll } = await import('/app/lib/api-drive.js');
          const { openRow } = await import('/app/lib/folder.js');
          const { createLink } = await import('/app/lib/seal.js');
          const identity = await loadIdentity({ lazy: true });
          await session.ensureSession(identity);
          const rows = await listAll({ view: 'all' }, session.authHeaders());
          const it = await openRow(identity.vaultKey, rows.find((r) => r.item_id === %s));
          await createLink({ itemId: it.id, headerHash: it.headerHash, fk: it.fk, headers: session.authHeaders() }, { maxViews: 3 });
          return true; })()""" % json.dumps(shared), timeout=60)
    else:                 # the fake: a link the server lists
        fake.folders[shared]["shares"] = [{"id": "Q" * 22, "mode": "link", "state": "active", "created_hour": 0, "expires_at": None,
                                           "max_views": 3, "views_used": 0, "views_left": 3}]
    a.goto(t.origin + "/drive")
    a.wait_for("drive-root", 60)
    upload_files(t, a, ["notes.txt"])
    row_menu(a, "notes.txt", "move")
    a.wait_for("move-dialog", 10)
    a.eval("[...document.querySelectorAll('[data-testid=\"move-target\"]')].find((e) => e.dataset.name === 'Private box').click()")
    t.check(a.eval("document.querySelector('[data-testid=\"move-shares\"]').hidden"), "a folder without a link: no warning")
    a.eval("[...document.querySelectorAll('[data-testid=\"move-target\"]')].find((e) => e.dataset.name === 'Shared box').click()")
    a.wait("!document.querySelector('[data-testid=\"move-shares\"]').hidden", 5)
    warn = a.text("move-shares")
    t.check("This shares it too." in warn and "Shared box has a link. Anyone who opens it will see this file." in warn,
            f"into a folder with a link: This shares it too, before Move here ({warn})")
    t.shot(a, "drive-1440-move-shares")
    a.click("move-go")
    a.wait("!document.querySelectorAll('[data-testid=\"file-row\"]').length", 30)
    t.check(any(c[0] == "PATCH" for c in fake.calls) or fake.native, "PATCH moved it, with its key wrapped under the folder's")
    a.wait("!!document.querySelector('.toast-action')", 10)
    a.eval("document.querySelector('.toast-action').click()")
    a.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'notes.txt')", 30)
    t.check(True, "Undo brings it back")
    row_menu(a, "notes.txt", "rename")
    a.wait_for("rename-dialog", 10)
    a.fill("rename-input", "meeting notes.txt")
    a.click("rename-go")
    a.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'meeting notes.txt')", 30)
    a.reload()
    a.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'meeting notes.txt')", 60)
    t.check(True, "renamed: the new name was sealed here and opens after a reload")
    sent = " ".join(r["url"] for r in a.requests)
    t.check("meeting" not in sent, "the new name never travels in clear")


@scenario("drive-trash-restore", "Trash and restore (step 7): Move to trash with Undo, the trash view, Bring back, Delete now", features=FEATURES)
def drive_trash_restore(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["notes.txt", "report.dat"])
    row_menu(a, "notes.txt", "trash")
    a.wait_for("trash-dialog", 10)
    desc = a.text("trash-dialog")
    t.check("Its links stop working now. You can bring it back for 30 days." in desc, f"C47 before it goes ({desc[:120]})")
    t.check(eventually(a, "document.activeElement?.dataset.cancel !== undefined"), "the alert focuses Cancel first")
    a.click("trash-go")
    a.wait("![...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'notes.txt')", 30)
    a.click("nav-storage")
    a.wait_for("storage-meter", 30)
    legend = a.eval("document.querySelector('.legend')?.textContent || ''")
    t.check("In the trash" in legend, f"Storage counts the trash until it empties ({legend[:100]})")
    a.click("nav-trash")
    a.wait_for("trash-row", 30)
    t.check(a.text("trash-row").startswith("notes.txt") and "Leaves" in a.text("trash-row"), "the trash lists it, with the day it leaves")
    t.shot(a, "drive-1440-trash")
    a.click("trash-restore")
    a.wait("!document.querySelector('[data-testid=\"trash-row\"]')", 30)
    a.click("nav-mine")
    a.wait("[...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'notes.txt')", 30)
    t.check(True, "Bring back: it is in My drive again")
    row_menu(a, "report.dat", "trash")
    a.wait_for("trash-dialog", 10)
    a.click("trash-go")
    a.click("nav-trash")
    a.wait_for("trash-delete", 30)
    a.click("trash-delete")
    a.wait_for("delete-dialog", 10)
    a.click("delete-go")
    a.wait("!document.querySelector('[data-testid=\"trash-row\"]')", 30)
    t.check(any(c[0] == "DELETE" for c in fake.calls) or fake.native, "Delete now deletes it on our server")


@scenario("drive-delete-account", "Delete my drive: the count, the tick before the button, each file into the can, the check, the done screen", features=FEATURES)
def drive_delete_account(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["one.txt", "two.txt", "three.txt"])
    row_menu(a, "three.txt", "trash")
    a.wait_for("trash-dialog", 10)
    a.click("trash-go")
    a.wait("![...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'three.txt')", 30)
    a.eval("document.querySelector('[data-testid=\"acct-settings\"]').click()")
    a.wait_for("settings", 20)
    a.click("delete-locker")
    a.wait_for("delete-drive", 10)
    a.wait("/3 files/.test(document.querySelector('[data-testid=\"wipe-count\"]')?.textContent || '')", 30)
    count = a.text("wipe-count")
    t.check("3 files" in count and "can't be undone" in count, f"the alert says how many files go, the Trash's too ({count[:140]})")
    t.check(a.eval("document.querySelector('[data-testid=\"delete-locker-confirm\"]').disabled") is True, "the button waits for the tick")
    t.check(a.text("delete-locker-confirm") == "Yes, delete my account and files", "the button says what it does")
    a.click("wipe-sure")
    a.wait("document.querySelector('[data-testid=\"delete-locker-confirm\"]').disabled === false", 5)
    t.shot(a, "drive-1440-delete-account-ask")
    t.check(a.eval("(() => { const d = document.getElementById('delete-drive').getBoundingClientRect(); return [...document.querySelectorAll('#delete-drive .dialog-footer .btn')].every((b) => { const r = b.getBoundingClientRect(); return r.left >= d.left && r.right <= d.right; }); })()"), "the alert fits its width (the long button wraps)")
    a.click("delete-locker-confirm")
    a.wait_for("wipe-progress", 10)
    a.wait("/of 3 deleted/.test(document.querySelector('[data-testid=\"wipe-progress\"]')?.textContent || '')", 30)
    t.shot(a, "drive-1440-delete-account-run")
    a.wait_for("wipe-done", 60)
    done = a.text("wipe-done-text")
    t.check("We deleted 3 files" in done, f"the done screen says what went ({done[:120]})")
    t.check(sum(1 for c in fake.calls if c[0] == "DELETE") >= 3 or fake.native, "each file is deleted on our server")
    t.shot(a, "drive-1440-delete-account-done")
    a.click("wipe-done")
    a.wait("location.pathname === '/drive' && !!document.querySelector('[data-testid=\"drive-make\"], [data-testid=\"drive-start\"], main')", 30)
    t.check(True, "Done goes back to /drive with no drive in this browser")


@scenario("drive-delete-after", "Delete it after… (step 7): a day, a week or the most; the Leaves badge; Keep it", features=FEATURES)
def drive_delete_after(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["notes.txt"])
    row_menu(a, "notes.txt", "later")
    a.wait_for("delete-after", 10)
    opts = a.eval("[...document.querySelectorAll('[data-testid=\"delete-after\"] .choice-title')].map((e) => e.textContent)")
    t.check(opts == ["A day", "A week", "30 days"], f"three choices, the last from /config ({opts})")
    t.check("We write that on the Tari chain." in a.text("delete-after"), "it says the file leaves and its receipt goes on chain (C42)")
    t.shot(a, "drive-1440-delete-after")
    a.click("later-go")
    visible_badge = "[...document.querySelectorAll('[data-testid=\"leaves-badge\"]')].find((e) => e.getClientRects().length)?.textContent ?? ''"
    badge = a.wait(visible_badge, 30)
    want = time.strftime("%b %-d", time.gmtime(time.time() + 7 * 86400))
    t.check(badge.startswith("Leaves ") and badge.split("Leaves ")[1] in (want, time.strftime("%b %-d", time.localtime(time.time() + 7 * 86400))),
            f"the row wears Leaves and the day ({badge})")
    row_menu(a, "notes.txt", "later")
    a.wait_for("later-keep", 10)
    a.click("later-keep")
    a.wait("!document.querySelector('[data-testid=\"leaves-badge\"]')", 30)
    t.check(True, "Keep it: the file stays until its owner deletes it")


# --- §15 step 9: Activity and What our server knows ---------------------------------------------------

@scenario("seller-activity", "Activity of a file (step 9): links made, opened, ended; C40; What our server knows, with this file's values", features=FEATURES)
def seller_activity(t):
    a, fake = make_drive(t)
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["notes.txt"])
    url = a.eval("""(async () => {
      const { loadIdentity } = await import('/app/lib/identity.js');
      const session = await import('/app/lib/session.js');
      const { listAll } = await import('/app/lib/api-drive.js');
      const { openRow } = await import('/app/lib/folder.js');
      const { createLink } = await import('/app/lib/seal.js');
      const identity = await loadIdentity({ lazy: true });
      await session.ensureSession(identity);
      const rows = await listAll({ view: 'all' }, session.authHeaders());
      const it = await openRow(identity.vaultKey, rows[0]);
      const item = { itemId: it.id, headerHash: it.headerHash, fk: it.fk, headers: session.authHeaders() };
      await createLink(item, { maxViews: 3, expiresAt: Math.floor(Date.now() / 1000) + 86400 });
      return (await createLink(item, { maxViews: 1, expiresAt: Math.floor(Date.now() / 1000) + 86400 })).url; })()""", timeout=60)
    b = t.actor("iphone")
    b.goto(url)
    b.wait_state("view-root", ("ready",), 60)
    b.click("view-open")
    b.wait_state("view-root", ("opened",), 60)
    a.goto(t.origin + "/drive")
    a.wait_for("file-row", 60)
    row_menu(a, "notes.txt", "activity")
    a.wait_for("activity-sheet", 10)
    events = a.eval("[...document.querySelectorAll('[data-testid=\"activity-sheet\"] [data-event]')].map((e) => e.dataset.event)")
    t.check(sorted(events) == sorted(["made", "made", "opened", "ended", "uploaded"]), f"made twice, opened, the once link ended, uploaded ({events})")
    sheet = a.text("activity-sheet")
    t.check("The file stays in your drive." in sheet and "Tari chain" not in sheet, "a link that ends on a kept file: no chain line (C42)")
    t.check("We count opens per hour. We never store who opened it or their IP address." in sheet, "C40 under the timeline")
    t.shot(a, "drive-1440-activity-sheet")
    a.click("open-known")
    a.wait_for("known-sheet", 10)
    known = a.text("known-sheet")
    size = a.eval("document.querySelector('[data-testid=\"known-size\"] .t-meta').textContent")
    t.check(all(x in known for x in ("A padded size, so the real size stays hidden", "The hour it arrived", "Its rule and how many opens are left",
                                    "How many times it opened each hour", "Which folder it is in, and how many files sit beside it")),
            "the glass box lines (C44, C41)")
    t.check("The name, the type, what's inside, the key, who opened it, or their IP address." in known, "what it never stores (C44 + C40)")
    t.check("Our server sees your IP address while you're connected. We don't write it to disk." in known, "the live-IP line (C4)")
    t.check(size.endswith("KB") or size.endswith("B"), f"with this file's padded size ({size})")
    t.shot(a, "drive-1440-known")


@scenario("activity-gone", "The drive's Activity (step 9): newest first; a file that left: It left your drive, and its chain line (C42)", features=FEATURES)
def activity_gone(t):
    a, fake = make_drive(t, fake=DriveFake(t.origin, seallog=True))
    a.wait_for("drive-empty", 30)
    upload_files(t, a, ["notes.txt", "report.dat"])
    row_menu(a, "report.dat", "trash")
    a.wait_for("trash-dialog", 10)
    a.click("trash-go")
    a.click("nav-trash")
    a.wait_for("trash-delete", 30)
    a.click("trash-delete")
    a.wait_for("delete-dialog", 10)
    a.click("delete-go")
    a.wait("!document.querySelector('[data-testid=\"trash-row\"]')", 30)
    a.click("nav-activity")
    a.wait_for("activity-feed", 60)
    left = a.wait("(() => { const e = [...document.querySelectorAll('[data-event=\"left\"]')].find((x) => x.dataset.name === 'report.dat'); return e ? e.textContent : ''; })()", 30)
    t.check("It left your drive" in left, f"the file that left is listed by name, here ({left[:80]})")
    state = a.wait("document.querySelector('[data-testid=\"exit-receipt\"]')?.dataset.state || ''", 30)
    line = a.text("exit-receipt")
    t.check(state == "pending" and "That goes on the Tari chain within" in line, f"before the checkpoint: within its minutes (C42) ({line[:90]})")
    fake.exit_tx = "ab" * 32
    a.click("nav-mine")
    a.wait_for("file-row", 30)
    a.click("nav-activity")
    state = a.wait("document.querySelector('[data-testid=\"exit-receipt\"]')?.dataset.state === 'onchain'", 30)
    line = a.text("exit-receipt")
    t.check("We wrote that on the Tari chain." in line and a.attr("exit-tx", "href") == "/verify/tx/" + "ab" * 32,
            f"after it: We wrote that on the Tari chain, with its transaction (C42) ({line[:90]})")
    kept = a.eval("[...document.querySelectorAll('[data-event=\"left\"]')].map((e) => e.dataset.name)")
    t.check(kept == ["report.dat"], f"only the file that left gets a chain line ({kept})")
    t.check(any(e == "uploaded" for e in a.eval("[...document.querySelectorAll('[data-event]')].map((e) => e.dataset.event)")), "uploads are listed too")
    t.check("We count opens per hour." in a.text("locker-root"), "C40 on the view")
    a.click("open-known")
    a.wait_for("known-sheet", 10)
    t.check("What it never stores" in a.text("known-sheet"), "What our server knows opens from the view")
    t.shot(a, "drive-1440-activity", full_page=True)
