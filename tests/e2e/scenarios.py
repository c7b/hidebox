# SPDX-License-Identifier: MIT
"""E2E scenarios without chain transactions (spec §17.2). Each one names its spec id; run.py runs them.
Selectors come only from the data-testid contract (spec §3.4.9)."""
import secrets
import time

import apiclient
import flows
from harness import STAGING, T, big_fixture_sha256, poll, scenario

ALL_PAGES = ["/", "/how", "/security", "/pricing", "/faq", "/judges", "/terms", "/privacy", "/abuse", "/es/",
             "/locker", "/inbox", "/send", "/watch", "/upgrade", "/t", "/verify/tx/" + "0" * 64, "/no-such-page"]
INSTRUMENTED = ("E-01", "E-02", "E-05", "E-08", "E-09", "E-10", "E-12")    # E-03 searches their traffic


def item_of(t: T, url: str) -> str:
    rows = t.env.remote.sql("SELECT item_id FROM shares WHERE id = ?", flows.share_id(url))
    t.check(rows, "the link's item is in the database")
    return rows[0][0]


def text_once(t: T, device: str, jitless: bool = False) -> None:
    a = t.actor(device, jitless=jitless)
    flows.home(a, t.origin)
    text = f"E2E {t.sid} plain text {secrets.token_hex(6)}"
    t.secret("the plaintext", text)
    url = flows.seal_text(a, text)
    t.secret("the link key", flows.fragment(url))
    t.shot(a, "sealed")
    b = t.actor(device, jitless=jitless)
    t.check(flows.open_link(b, url) == "opened", "B opens the link")
    t.check(b.text("view-text").strip() == text, "B reads exactly the sealed text")
    t.shot(b, "opened")
    b.reload()
    t.check(b.wait_state("view-root", flows.VIEW_ASK, 60) == "burned", "B's reload shows burned")
    c = t.actor(device, jitless=jitless)
    t.check(flows.open_link(c, url) == "burned", "C sees burned")
    t.shot(c, "burned")
    item = item_of(t, url)
    gone = poll(lambda: t.env.remote.sql("SELECT state FROM items WHERE id = ?", item)[0][0] == "deleted", 180, 10)
    t.check(gone, "the item is deleted after a cleanup cycle")


@scenario("E-01", "Text secret, Once: B reads it; reload and C see burned; item deleted")
def e01(t: T) -> None:
    text_once(t, "desktop")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


@scenario("E-02", "10 MB file, 3 views: B, C, D save identical files; E sees burned")
def e02(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    flows.seal_file(a, t.fixture("ten-mb.bin"))
    t.secret("the file name", "ten-mb.bin")
    url = flows.set_rules(a, when="views", views=3)
    t.secret("the link key", flows.fragment(url))
    want = big_fixture_sha256("ten-mb.bin")
    for who in "BCD":
        page = t.actor()
        t.check(flows.open_link(page, url) == "opened", f"{who} opens the file")
        page.click("view-save")
        t.check(t.download_sha256(page) == want, f"{who}'s saved file has the original SHA-256")
    t.check(flows.open_link(t.actor(), url) == "burned", "E sees burned after three views")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


@scenario("E-03", "Secret hygiene across E-01, E-02, E-05, E-08, E-09, E-10, E-12")
def e03(t: T) -> None:
    ran = [(sid, problems) for sid, problems in t.env.hygiene if sid in INSTRUMENTED]
    if not ran:
        t.skip("none of the instrumented scenarios ran in this session")
    for sid, problems in ran:
        t.check(not problems, f"{sid}: no secret in any URL, header or body ({'; '.join(problems[:3])})")


@scenario("E-04", "Link + password and password-only; path-only attempts never lock a link")
def e04(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    flows.seal_text(a, "E2E E-04 behind a password")
    password = "correct horse " + secrets.token_hex(3)
    t.secret("the password", password)
    url = flows.set_rules(a, who="password", password_mode="link_password", password=password)
    probe = apiclient.Client(t.origin)
    codes = set()
    for _ in range(60):
        try:
            probe.call("POST", f"/s/{flows.share_id(url)}/peek", headers={"X-Mutis-Access": apiclient.b64u(secrets.token_bytes(32))})
        except apiclient.ApiError as e:
            codes.add(e.code)
    t.check(codes == {"bad_link"}, f"60 path-only attempts answer bad_link (got {sorted(codes)})")
    _, status = probe.call("GET", f"/s/{flows.share_id(url)}")
    t.check(status.get("state") == "active", "the link is still active after them")
    b = t.actor()
    for attempt in ("wrong one", "wrong two"):
        t.check(flows.open_link(b, url, attempt) == "password:wrong", f"'{attempt}' is refused with \"That's not it\"")
    t.check(flows.open_link(b, url, password) == "opened", "the right password opens it")
    flows.home(a, t.origin)
    flows.seal_text(a, "E2E E-04 password only")
    only = flows.set_rules(a, who="password", password_mode="password", password=password)
    c = t.actor()
    t.check(flows.open_link(c, only.split("#")[0], password) == "opened", "a password-only link opens without a fragment")


@scenario("E-05", "Expiry 60 s: after 65 s the link is expired")
def e05(t: T) -> None:
    preset = t.env.config().get("e2e_expiry_s")
    if not preset:
        t.skip("this deployment offers no short expiry preset (config e2e_expiry_s = 60, tests/e2e/README.md)")
    a = t.actor()
    flows.home(a, t.origin)
    flows.seal_text(a, "E2E E-05 leaves in a minute")
    url = flows.set_rules(a, expiry=str(preset))
    t.secret("the link key", flows.fragment(url))
    time.sleep(preset + 5)
    t.check(flows.open_link(t.actor(), url) == "expired", "the link is expired")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


@scenario("E-06", "Tamper: one flipped byte of a 5 MB blob gives integrity-error and saves nothing")
def e06(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    url = flows.seal_file(a, t.fixture("five-mb.bin"))
    item = item_of(t, url)
    path = f"/srv/mutis/data/blobs/{item[:2]}/{item[2:4]}/{item}.bin"
    flip = f"f = open({path!r}, 'r+b'); f.seek(4096); b = f.read(1); f.seek(4096); f.write(bytes([b[0] ^ 1])); f.close()"
    t.env.remote.run("cd /tmp && sudo -u mutis sh -c 'umask 007; exec python3 -I -'", flip.encode())
    b = t.actor()
    t.check(flows.open_link(b, url) == "integrity-error", "B gets integrity-error")
    b.b.drain(5)
    t.check(not [e for e in b.b.events if e.get("method") == "Browser.downloadWillBegin"], "nothing was saved")


@scenario("E-07", "A link without its #key shows incomplete")
def e07(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    url = flows.seal_text(a, "E2E E-07")
    t.check(flows.open_link(t.actor(), url.split("#")[0]) == "incomplete", "the viewer says the key is missing")


def make_drop_link(t: T, page, label: str) -> str:
    """From /locker: open a locker silently by asking for a drop link; return the short URL."""
    page.goto(t.origin + "/locker")
    page.wait_for("locker-root")
    if page.exists("drop-label"):
        page.fill("drop-label", label)
    page.click("drop-create")
    return page.wait("(() => { const e = document.querySelector('[data-testid=\"drop-link\"]');"
                     " const v = e && (e.value || e.textContent || '').trim(); return v && v.includes('/d/') ? v : ''; })()", 120)


def safety_emoji(page, testid: str) -> list[str]:
    """The emoji of a safety code, one grapheme each (the hex for screen readers and labels left out)."""
    return page.eval(f"[...new Intl.Segmenter().segment(document.querySelector('[data-testid=\"{testid}\"]')"
                     ".textContent)].map(s => s.segment).filter(g => /\\p{Extended_Pictographic}/u.test(g))")


def locker_identity(page) -> tuple[list[str], str]:
    address = page.eval("(() => { const e = document.querySelector('[data-testid=\"locker-address\"]');"
                        " return (e?.value || e?.textContent || '').trim(); })()")
    return safety_emoji(page, "locker-safety"), address


@scenario("E-08", "Locker: lazy creation from Leave me a file; key saved; restored in a clean browser")
def e08(t: T) -> None:
    a = t.actor()
    make_drop_link(t, a, "E2E E-08")
    a.wait_for("key-save-file", 60)
    # Brand P-15: the key file is locked with a passphrase by default.
    passphrase = "E2E orchid lantern " + secrets.token_hex(4)
    t.secret("the key passphrase", passphrase)
    a.fill("key-passphrase", passphrase)
    a.click("key-save-file")
    key_text = t.env.remote.as_build(f"cat {t.downloaded(a)}")
    t.secret("the key file", key_text.strip())
    t.check("Locked key:" in key_text, "the key file is locked with the passphrase")
    if a.exists("key-saved-check"):
        a.click("key-saved-check")
    a.goto(t.origin + "/locker")
    a.wait_for("locker-safety")
    safety, address = locker_identity(a)
    t.check(len(safety) == 12 and address.startswith("otl_esm_1"),
            f"the locker shows its 12-emoji safety code and Tari address ({len(safety)} emoji)")
    t.shot(a, "locker")
    b = t.actor()
    b.goto(t.origin + "/locker")
    b.wait_for("restore-text")
    b.fill("restore-text", key_text)
    b.click("restore-submit")
    b.wait_for("restore-passphrase", 30)
    b.fill("restore-passphrase", passphrase)
    b.click("restore-submit")
    b.wait_for("locker-safety", 120)
    t.check(locker_identity(b) == (safety, address), "the restored locker has the same safety code and address")
    b.wait_for("quota-bar", 60)
    t.check(b.attr("quota-bar", "data-limit"), "/me answers for the restored locker (quota shown)")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


@scenario("E-15", "Burn race: five browsers press Open it together; exactly one opens")
def e15(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    url = flows.seal_text(a, "E2E E-15 race")
    pages = [t.actor() for _ in range(5)]
    for p in pages:
        t.check(flows.open_link(p, url, open_it=False) == "ready", "a racer reaches ready")
    for p in pages:
        p.eval("document.querySelector('[data-testid=\"view-open\"]').click()")
    states = [p.wait_state("view-root", flows.VIEW_END, 120) for p in pages]
    t.check(sorted(states) == ["burned"] * 4 + ["opened"], f"one opened, four burned (got {states})")


@scenario("E-16", "Limits: a 26 MiB anonymous file is refused before upload; the server refuses it too")
def e16(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    a.set_files("drop-input", [t.fixture("too-big.bin")])
    a.wait("!!document.querySelector('[data-testid=\"error-banner\"]') || /locker/i.test(document.querySelector('#mutis-drop')?.textContent || '')", 30)
    a.collect()
    t.check(not [r for r in a.requests if r["url"].endswith("/api/v1/uploads") and r["method"] == "POST"],
            "the browser offered a locker without uploading")
    c = apiclient.Client(t.origin)
    try:
        c.upload(26 * 1024 * 1024 + 1)
        t.check(False, "the API accepted a 26 MiB anonymous file")
    except apiclient.ApiError as e:
        t.check(e.status == 413 and e.code == "too_large", f"the API answers 413 too_large (got {e.status} {e.code})")


@scenario("E-16s", "Limits under a freeze: uploads_frozen banner, downloads still work", STAGING)
def e16s(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    earlier = flows.seal_text(a, "E2E E-16 before the freeze")
    t.env.remote.admin("freeze", "all")
    try:
        flows.home(a, t.origin)
        a.click("drop-write")
        a.fill("drop-textarea", "E2E E-16 during the freeze")
        a.click("drop-seal-text")
        a.wait("document.querySelector('[data-testid=\"error-banner\"]')?.dataset.code === 'uploads_frozen'", 60)
        t.check(True, "the widget shows uploads_frozen")
        t.check(flows.open_link(t.actor(), earlier) == "opened", "an existing link still opens")
    finally:
        t.env.remote.admin("freeze", "none")


@scenario("E-17", "Abuse: a reported link and drop are taken down by id")
def e17(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    url = flows.seal_text(a, "E2E E-17 to be reported")
    owner = apiclient.Client(t.origin)
    owner.register()
    drop = owner.create_drop(apiclient.random_address(), "E2E E-17")
    reporter = apiclient.Client(t.origin)
    for link in (url.split("#")[0], drop["url"]):
        t.check(reporter.report(link, "other").get("report_id", "").startswith("rep_"), f"report accepted for {link[-24:]}")
    # "--": a base64url id may begin with "-", which the admin CLI would read as an option.
    t.env.remote.admin("takedown", "share", "--", flows.share_id(url))
    t.env.remote.admin("takedown", "drop", "--", drop["drop_id"])
    b = t.actor()
    t.check(flows.open_link(b, url) == "removed", "the link shows removed")
    b.goto(drop["url"])
    t.check(b.wait_state("dd-root", ("closed", "not-found", "ready", "error"), 60) == "closed", "the drop page shows closed")


@scenario("E-18", "Every page: only same-origin requests and no CSP or Trusted Types violation")
def e18(t: T) -> None:
    for device in ("desktop", "iphone"):
        page = t.actor(device)
        for path in ALL_PAGES:
            page.goto(t.origin + path)
            page.b.drain(3)
            page.collect()
        foreign = sorted({r["url"][:100] for r in page.requests
                          if not r["url"].startswith((t.origin, "data:", "blob:", "about:"))})
        t.check(not foreign, f"{device}: no third-party request ({foreign[:3]})")
        violations = page.csp_violations()
        t.check(not violations, f"{device}: no CSP or Trusted Types violation ({violations[:2]})")


@scenario("E-19", "Phones: E-01 at 390×844 and 412×915; reduced motion; no horizontal scroll at 360 px")
def e19(t: T) -> None:
    text_once(t, "iphone")
    text_once(t, "android")
    calm = t.actor("iphone", reduced_motion=True)
    flows.home(calm, t.origin)
    t.check(calm.eval("matchMedia('(prefers-reduced-motion: reduce)').matches"), "reduced motion is on")
    t.shot(calm, "home-reduced-motion")
    narrow = t.actor("narrow")
    wide = []
    for path in ALL_PAGES:
        narrow.goto(t.origin + path)
        narrow.b.drain(1)
        if not flows.no_horizontal_scroll(narrow):
            wide.append(path)
    t.check(not wide, f"no horizontal scroll at 360 px ({wide})")


def unnamed_controls(page) -> list[str]:
    roles = {"button", "link", "textbox", "checkbox", "radio", "combobox", "switch", "tab", "menuitem", "searchbox"}
    page.cmd("Accessibility.enable")
    bad = []
    for node in page.ax_tree():
        role = (node.get("role") or {}).get("value")
        name = (node.get("name") or {}).get("value", "")
        if role in roles and not node.get("ignored") and not str(name).strip():
            bad.append(role)
    return bad


@scenario("E-20", "Accessibility: every control named; keyboard-only seal and copy; the live region speaks")
def e20(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    t.check(not unnamed_controls(a), f"home: every control has an accessible name ({unnamed_controls(a)[:5]})")
    for _ in range(60):
        a.key("Tab")
        if a.eval("document.activeElement?.dataset?.testid") == "drop-write":
            break
    t.check(a.eval("document.activeElement?.dataset?.testid") == "drop-write", "Tab reaches 'or paste text'")
    a.key("Enter")
    a.wait_for("drop-textarea")
    a.eval("document.querySelector('[data-testid=\"drop-textarea\"]').focus()")
    a.cmd("Input.insertText", {"text": "E2E E-20 keyboard only"})
    a.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "modifiers": 2, "windowsVirtualKeyCode": 13})
    a.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "modifiers": 2, "windowsVirtualKeyCode": 13})
    flows.wait_link(a)
    t.check(a.eval("(document.querySelector('.md-live,[role=status]')?.textContent || '').trim().length > 0"),
            "the live region announces the sealed state")
    t.check(not unnamed_controls(a), "sealed card: every control has an accessible name")
    owner = apiclient.Client(t.origin)
    owner.register()
    drop = owner.create_drop(apiclient.random_address(), "E2E E-20")
    a.goto(drop["url"])
    a.wait_state("dd-root", ("ready",), 60)
    t.check(not unnamed_controls(a), "drop page: every control has an accessible name")


@scenario("E-22", "Programs: an anonymous .exe is refused; a locker's .exe opens behind the program warning")
def e22(t: T) -> None:
    a = t.actor()
    flows.home(a, t.origin)
    a.set_files("drop-input", [t.fixture("setup.exe")])
    a.b.drain(5)
    a.collect()
    uploaded = [r for r in a.requests if r["url"].endswith("/api/v1/uploads") and r["method"] == "POST"]
    t.check(not uploaded and flows.banner(a), f"the widget refuses the program before upload (banner {flows.banner(a)})")
    k = t.actor()
    k.goto(t.origin + "/locker")
    k.wait_for("locker-root")
    if not k.exists("drop-input"):
        t.skip("the locker page has no drop widget to seal a program as a locker")
    url = flows.seal_file(k, t.fixture("setup.exe"))
    b = t.actor()
    state = flows.open_link(b, url)
    t.check(state in ("program-warning", "opened-risky"), f"the viewer shows the program warning (got {state})")
    t.check(b.exists("view-save-anyway") and not b.exists("view-image"), "no preview, Save anyway offered")


@scenario("E-24", "Tor-like browser (--jitless, no WebAssembly): E-01 passes; locker pages say needs_wasm")
def e24(t: T) -> None:
    text_once(t, "desktop", jitless=True)
    page = t.actor(jitless=True)
    for path in ("/locker", "/d/" + "0" * 10):
        page.goto(t.origin + path)
        page.b.drain(3)
        t.check(page.eval("!!document.querySelector('[data-code=\"needs_wasm\"]')"), f"{path} shows needs_wasm")
