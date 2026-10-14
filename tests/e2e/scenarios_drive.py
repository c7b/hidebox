# SPDX-License-Identifier: MIT
"""E2E scenarios of the drive (16-drive-design §12, §15 step 12; 16-drive-architecture §6.3): E-08 moved to
the drive, and E-26, E-27, E-28, E-31. No chain transactions. Selectors come only from the data-testid
contract; the drive's ids are listed in §12 and in web/app/ui/tests/flows_drive.py and flows_share.py.

Pace: each scenario makes one drive (a new identity), and the API allows 5 new ones per network an hour
(README "Pace"): run them in batches."""
import json
import secrets
import shlex

import flows
from harness import REMOTE_DIR, T, poll, scenario

DRIVE_IDS = ("E-08", "E-26", "E-27", "E-28", "E-31")


def make_drive(t: T, device: str = "desktop"):
    """/drive?make: the key is made in this browser at once and the drive opens (Make my drive)."""
    page = t.actor(device)
    page.goto(t.origin + "/drive?make")
    page.wait_for("drive-root", 120)
    page.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    return page


def names(page) -> list[str]:
    return page.eval("[...document.querySelectorAll('[data-testid=\"file-row\"], [data-testid=\"folder-card\"]')]"
                     ".filter((e) => !e.hidden).map((e) => e.dataset.name)")


def wait_names(page, wanted: list[str], timeout: float = 120) -> None:
    page.wait(f"(() => {{ const n = [...document.querySelectorAll('[data-testid=\"file-row\"], [data-testid=\"folder-card\"]')]"
              f".map((e) => e.dataset.name); return {json.dumps(wanted)}.every((x) => n.includes(x)); }})()", timeout)


def remote_tree(t: T, root: str, files: dict[str, bytes]) -> str:
    """Write files under fixtures/<root>/ on the server (the browser runs there); -> the folder's path."""
    base = f"{REMOTE_DIR}/fixtures/{t.sid}-{root}"
    t.env.remote.as_build(f"rm -rf {shlex.quote(base)} && mkdir -p {shlex.quote(base)}")
    for rel, data in files.items():
        path = f"{base}/{rel}"
        t.env.remote.as_build(f"mkdir -p {shlex.quote(path.rsplit('/', 1)[0])} && cat > {shlex.quote(path)}", data)
    return base


def upload_folder(t: T, page, root: str, files: dict[str, bytes]) -> None:
    page.wait("!!document.querySelector('[data-testid=\"upload-dir-input\"]')", 30)
    page.set_files("upload-dir-input", [remote_tree(t, root, files)])
    page.wait(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === {json.dumps(t.sid + '-' + root)})", 180)


def upload_files(t: T, page, files: dict[str, bytes]) -> None:
    base = remote_tree(t, "files-" + secrets.token_hex(3), files)
    page.wait("!!document.querySelector('[data-testid=\"upload-files-input\"]')", 30)
    page.set_files("upload-files-input", [f"{base}/{n}" for n in files])
    wait_names(page, list(files))


def into(page, name: str) -> str:
    fid = page.eval(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === {json.dumps(name)}).dataset.id")
    page.eval(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === {json.dumps(name)}).querySelector('.folder-icon').click()")
    page.wait(f"location.pathname === '/drive/folders/{fid}'", 15)
    page.wait_for("breadcrumbs", 30)
    return fid


def row_menu(page, name: str, value: str) -> None:
    page.eval(f"""(() => {{ const el = [...document.querySelectorAll('[data-testid="file-row"], [data-testid="folder-card"]')]
      .find((e) => e.dataset.name === {json.dumps(name)}); el.querySelector('[data-testid="row-kebab"]').click(); }})()""")
    page.wait("!document.getElementById('row-menu').hidden", 10)
    page.click("menu-" + value)


def share_link(page, name: str, opens: str | None = None) -> str:
    """Share → Anyone with the link → (opens) → Make link; -> the link with its #key."""
    row_menu(page, name, "share")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    page.click("share-next")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
    if opens:
        page.click("share-choice", opens)
    page.click("share-make")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
    url = page.value("share-link")
    page.key("Escape")
    page.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 10)
    return url


def save_key_file(t: T, page, passphrase: str | None) -> str:
    """Account → Save key file, locked with `passphrase` (or in plain form with None); -> its text."""
    page.eval("document.querySelector('[data-testid=\"acct-key\"]').click()")
    page.wait_for("key-dialog", 15)
    if passphrase:
        page.fill("key-passphrase", passphrase)
    else:
        page.eval("document.querySelector('[data-testid=\"key-protect\"]').click()")
    page.click("key-save-file")
    path = t.downloaded(page)
    text = t.env.remote.as_build(f"cat {shlex.quote(path)}")
    page.key("Escape")
    return text


def open_drive(t: T, key_text: str, passphrase: str | None = None, device: str = "desktop"):
    """A clean browser: /drive?open, the key pasted (and its passphrase); -> the page with the drive open."""
    b = t.actor(device)
    b.goto(t.origin + "/drive?open")
    b.wait_for("open-dialog", 60)
    b.fill("restore-text", key_text)
    b.click("restore-submit")
    if passphrase:
        b.wait("!document.getElementById('open-pass')?.closest('.field')?.hidden", 30)
        b.fill("restore-passphrase", passphrase)
        b.click("restore-submit")
    b.wait_for("drive-root", 120)
    b.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    return b


def identity(page) -> tuple[str, str]:
    """Settings: the drive's Tari address and its safety code (its text)."""
    page.eval("document.querySelector('[data-testid=\"acct-settings\"]').click()")
    page.wait("!!document.querySelector('[data-testid=\"settings\"] [data-testid=\"locker-safety\"]')", 60)
    out = page.eval("(() => { const s = document.querySelector('[data-testid=\"settings\"]');"
                    " return [s.querySelector('[data-testid=\"locker-address\"]').textContent.trim(),"
                    " s.querySelector('[data-testid=\"locker-safety\"]').textContent.trim()]; })()")
    page.key("Escape")
    return out[0], out[1]


@scenario("E-08", "Drive: Make my drive at once; the key file locked with a passphrase; restored in a clean browser (same address and safety code)")
def e08(t: T) -> None:
    a = make_drive(t)
    t.shot(a, "drive")
    passphrase = "E2E orchid lantern " + secrets.token_hex(4)
    t.secret("the key passphrase", passphrase)
    key_text = save_key_file(t, a, passphrase)
    t.secret("the key file", key_text.strip())
    t.check("Locked key:" in key_text and "MUTIS-" not in key_text, "the key file holds the key locked with the passphrase")
    address, safety = identity(a)
    t.check(address.startswith("otl_esm_1") and safety, f"Settings shows the drive's Tari address and safety code ({address[:16]}…)")
    b = open_drive(t, key_text, passphrase)
    t.check(identity(b) == (address, safety), "the restored drive has the same address and safety code")
    t.check(b.exists("quota-bar"), "/me answers for the restored drive (the storage meter is shown)")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


TREE = {"plan-of-the-trip.txt": b"E2E plan: the night train at nine.\n",
        "budget-for-trip.txt": b"E2E budget: two hundred, cash.\n",
        "day-one/map-of-old-town.txt": b"E2E map: the third gate on the left.\n"}


@scenario("E-26", "Drive: upload a folder (3 files, 1 subfolder) with the folder picker; restored in a clean browser with the key file: the same tree")
def e26(t: T) -> None:
    a = make_drive(t)
    for rel, data in TREE.items():
        t.secret("a file's name", rel.rsplit("/", 1)[-1])
        t.secret("a file's bytes", data)
    folder = f"{t.sid}-holiday"
    upload_folder(t, a, "holiday", TREE)
    t.check(names(a) == [folder], f"one folder at the root ({names(a)})")
    into(a, folder)
    wait_names(a, ["day-one", "budget-for-trip.txt", "plan-of-the-trip.txt"])
    t.check(sorted(names(a)) == ["budget-for-trip.txt", "day-one", "plan-of-the-trip.txt"], f"inside: a folder and two files ({names(a)})")
    into(a, "day-one")
    wait_names(a, ["map-of-old-town.txt"])
    t.shot(a, "tree")
    a.goto(t.origin + "/drive")
    a.wait_for("drive-root", 60)
    key_text = save_key_file(t, a, None)
    t.secret("the key file", key_text.strip())
    t.check("Key: MUTIS-" in key_text, "with the lock off, the file holds the key in plain form")
    b = t.actor()
    b.goto(t.origin + "/drive?open")
    b.wait_for("open-dialog", 60)
    b.click("restore-open")
    path = f"{REMOTE_DIR}/fixtures/{t.sid}-key.txt"
    t.env.remote.as_build(f"cat > {shlex.quote(path)}", key_text.encode())
    b.set_files("restore-file", [path])
    b.wait("document.querySelector('[data-testid=\"restore-text\"]').value.includes('MUTIS-')", 15)
    b.click("restore-submit")
    b.wait_for("drive-root", 120)
    wait_names(b, [folder])
    into(b, folder)
    wait_names(b, ["day-one", "budget-for-trip.txt", "plan-of-the-trip.txt"])
    into(b, "day-one")
    wait_names(b, ["map-of-old-town.txt"])
    t.check(True, "the restored drive shows the same tree, named in this browser")
    t.check(not t.hygiene(), "no name, byte or key in any request (E-03)")


ALBUM = {"one-sunset.txt": b"E2E album: the sunset, first.\n", "two-harbour.txt": b"E2E album: the harbour.\n",
         "three-market.txt": b"E2E album: the market at noon.\n", "later/four-night.txt": b"E2E album: the night bus.\n"}


@scenario("E-27", "Folder link, Once: a phone opens it, lists 4 things, saves one, downloads all (zipfile checks it); a second phone sees it ended")
def e27(t: T) -> None:
    a = make_drive(t)
    folder = f"{t.sid}-album"
    upload_folder(t, a, "album", ALBUM)
    url = share_link(a, folder)
    t.secret("the folder link's key", flows.fragment(url))
    v = t.actor("iphone")
    v.goto(url)
    state = v.wait_state("view-root", flows.VIEW_ASK, 60)
    t.check(state == "ready" and v.attr("view-root", "data-kind") == "folder", f"a folder link's first screen ({state})")
    v.click("view-open")
    v.wait_for("folder-view", 90)
    rows = v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].map((e) => e.dataset.name)")
    t.check(sorted(rows) == ["later", "one-sunset.txt", "three-market.txt", "two-harbour.txt"], f"4 things, named in this browser ({rows})")
    t.shot(v, "folder")
    v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === 'one-sunset.txt').querySelector('[data-testid=\"fv-save\"]').click()")
    one = t.downloaded(v)
    t.check(t.env.remote.as_build(f"cat {shlex.quote(one)}").encode() == ALBUM["one-sunset.txt"], "Save one: the file, byte for byte")
    v.click("fv-zip")
    z = t.downloaded(v)
    check = ("import json, sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); "
             "print(json.dumps([z.testzip(), {i.filename: z.read(i.filename).decode() for i in z.infolist() if not i.is_dir()}]))")
    bad, got = json.loads(t.env.remote.as_build(f"python3 -I -c {shlex.quote(check)} {shlex.quote(z)}"))
    want = {k: v_.decode() for k, v_ in ALBUM.items()}
    t.check(bad is None and got == want, f"Download all: Python's zipfile finds every CRC good and the files byte for byte ({sorted(got)})")
    w = t.actor("android")
    w.goto(url)
    t.check(w.wait_state("view-root", flows.VIEW_ASK, 60) == "burned", "a second phone: the link ended with its one visit")
    t.check(not t.hygiene(), "no name or key in any request (E-03)")


@scenario("E-28", "Move and rename: a file moved into a shared folder shows through its link; one moved out mid-visit is refused (403)")
def e28(t: T) -> None:
    a = make_drive(t)
    folder = f"{t.sid}-box"
    upload_folder(t, a, "box", {"inside-already.txt": b"E2E inside.\n"})
    upload_files(t, a, {"moved-in-later.txt": b"E2E moved in.\n"})
    url = share_link(a, folder, "few")
    row_menu(a, "moved-in-later.txt", "move")
    a.wait_for("move-dialog", 15)
    a.eval(f"[...document.querySelectorAll('[data-testid=\"move-target\"]')].find((e) => e.dataset.name === {json.dumps(folder)}).click()")
    a.wait("!document.querySelector('[data-testid=\"move-shares\"]').hidden", 10)
    t.check("This shares it too." in a.text("move-shares"), "moving into a folder with a link warns: This shares it too.")
    a.click("move-go")
    a.wait("![...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'moved-in-later.txt')", 30)
    v = t.actor()
    v.goto(url)
    v.wait_state("view-root", flows.VIEW_ASK, 60)
    v.click("view-open")
    v.wait_for("folder-view", 90)
    rows = v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].map((e) => e.dataset.name)")
    t.check(sorted(rows) == ["inside-already.txt", "moved-in-later.txt"], f"the moved file shows through the folder's link ({rows})")
    into(a, folder)
    wait_names(a, ["inside-already.txt"])
    row_menu(a, "inside-already.txt", "move")
    a.wait_for("move-dialog", 15)
    targets = a.eval("[...document.querySelectorAll('[data-testid=\"move-target\"]')].map((e) => e.dataset.name)")
    root = next((i for i, name in enumerate(targets) if name == ""), None)     # My drive: the root has no name
    t.check(root is not None, f"the move dialog offers My drive ({targets})")
    a.eval(f"document.querySelectorAll('[data-testid=\"move-target\"]')[{root}].click()")
    a.click("move-go")
    a.wait("![...document.querySelectorAll('[data-testid=\"file-row\"]')].some((e) => e.dataset.name === 'inside-already.txt')", 30)
    v.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === 'inside-already.txt').querySelector('[data-testid=\"fv-save\"]').click()")
    code = v.wait("document.querySelector('[data-testid=\"folder-view\"] [data-testid=\"error-banner\"]')?.dataset.code ?? ''", 60)
    t.check(code == "not_in_folder", f"the running visit can't fetch a file moved out (403 not_in_folder; banner {code})")
    a.goto(t.origin + "/drive")
    a.wait_for("drive-root", 60)
    wait_names(a, ["inside-already.txt"])
    row_menu(a, "inside-already.txt", "rename")
    a.wait_for("rename-dialog", 10)
    a.fill("rename-input", "renamed-here.txt")
    a.click("rename-go")
    wait_names(a, ["renamed-here.txt"])
    t.secret("a new name", "renamed-here.txt")
    a.reload()
    a.wait_for("drive-root", 60)
    wait_names(a, ["renamed-here.txt"])
    t.check(not t.hygiene(), "the new name was sealed here and never sent in clear (E-03)")


@scenario("E-31", "Activity hygiene: the owner sees opens per hour; the database and its backups hold no IP address, user agent or name")
def e31(t: T) -> None:
    a = make_drive(t)
    upload_files(t, a, {"activity-probe-file.txt": b"E2E activity probe.\n"})
    url = share_link(a, "activity-probe-file.txt", "few")
    for device in ("iphone", "android"):
        v = t.actor(device)
        t.check(flows.open_link(v, url) == "opened", f"the {device} opens the link")
        ua = v.eval("navigator.userAgent")
    a.goto(t.origin + "/drive/activity")
    a.wait_for("activity-feed", 60)
    feed = a.text("activity-feed")
    t.check(a.wait("(document.querySelector('[data-testid=\"activity-feed\"]')?.textContent || '').length > 0", 30), "the drive's Activity lists what happened")
    t.shot(a, "activity")
    sid = flows.share_id(url)
    opens = poll(lambda: t.env.remote.sql("SELECT SUM(n) FROM share_opens WHERE share_id = ?", sid)[0][0] or 0, 60, 5)
    t.check(opens and opens >= 2, f"share_opens counts the opens per hour ({opens}); the feed: {feed[:80]!r}")
    ips = [x for x in t.env.remote.run("hostname -I").split() if x]
    needles = [("a visitor's user agent", ua), ("a file name", "activity-probe-file.txt")] + [("the visitors' address", ip) for ip in ips]
    script = ("import json, os, sys; needles = json.load(sys.stdin); hits = []\n"
              "for top in ('/srv/mutis/data/db', '/srv/mutis/data/backup', '/var/backups/mutis'):\n"
              "    for d, _, fs in os.walk(top):\n"
              "        for f in fs:\n"
              "            p = os.path.join(d, f)\n"
              "            try: data = open(p, 'rb').read()\n"
              "            except OSError: continue\n"
              "            for name, n in needles:\n"
              "                for form in {n.encode(), n.encode('utf-16-le')}:\n"
              "                    if form and form in data: hits.append([name, p])\n"
              "print(json.dumps(hits))\n")
    t.env.remote.as_build(f"cat > {REMOTE_DIR}/{t.sid}-search.py", script.encode())
    hits = json.loads(t.env.remote.run(f"cd /tmp && sudo python3 -I {REMOTE_DIR}/{t.sid}-search.py", json.dumps(needles).encode()))
    t.check(not hits, f"no IP address, user agent or name in the database, its WAL or the backups ({hits[:3]})")
