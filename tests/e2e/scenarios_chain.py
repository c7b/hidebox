# SPDX-License-Identifier: MIT
"""E2E scenarios that make real Esmeralda transactions (@chain, spec §17.2) and the judge script E-J
(the /judges page). Their transaction ids are never published; public evidence comes only from the canary
and the daily evidence payment (spec §8.4)."""
import json
import re
import shlex
import time
import urllib.request

import apiclient
import flows
from harness import CHAIN, Skipped, T, poll, scenario
from scenarios import locker_identity, make_drop_link, open_settings, safety_emoji

TX = re.compile(r"^[0-9a-f]{64}$")
PHOTO_CHECK = ("import sys; d = open(sys.argv[1], 'rb').read(); "
               "print('gps' if (b'GPSLatitude' in d or b'\\x88\\x25' in d) else 'clean', "
               "'oriented' if b'\\x01\\x12\\x00\\x03' in d else 'no-orientation')")


def leave_photo(t: T, page, drop_url: str, safety: list[str]) -> str:
    """Submitter side of a dead drop; returns the delivery transaction id."""
    page.goto(drop_url)
    t.check(page.wait_state("dd-root", ("ready", "closed", "not-found", "error"), 60) == "ready", "the drop page is ready")
    shown = safety_emoji(page, "dd-safety")
    t.check(len(shown) == 12 and shown == safety, "the drop page shows the owner's 12-emoji safety code")
    page.set_files("dd-input", [t.fixture("photo-gps.jpg")])
    page.wait("document.querySelector('[data-testid=\"exif-chip\"]')?.dataset.removed === 'true'", 60)
    t.check(True, "the photo chip says location and camera data were removed")
    t.check(page.wait_state("dd-root", ("delivered", "error"), 300) == "delivered", "Delivered")
    tx = page.attr("dd-tx", "data-tx")
    t.check(tx and TX.match(tx), "the delivery has a transaction id")
    return tx


def open_inbox_item(t: T, page, source: str) -> str:
    """Received (16-drive-design §12, the inbox's place in the drive): wait for a delivery from `source`
    (the drive scans again on its own), open it here; -> 'opened' or the error code it shows."""
    page.goto(t.origin + "/drive/received")
    row = f'[data-testid="received-row"][data-source="{source}"]'
    item = poll(lambda: page.eval(f"!!document.querySelector({json.dumps(row + ' [data-testid=received-open-button]')})"), 600, 5)
    t.check(item, f"Received lists a delivery from {source}, ready to open")
    t.check(page.exists("inbox-item"), "the row keeps the inbox-item id")
    page.eval(f"document.querySelector({json.dumps(row + ' [data-testid=received-open-button]')}).click()")
    return page.wait("(() => { const o = document.querySelector('[data-testid=\"inbox-opened\"]'); if (o) return 'opened';"
                     " const e = document.querySelector('#rec-open [data-testid=\"error-banner\"]'); return e ? (e.dataset.code || 'error') : ''; })()", 180)


def tx_view(t: T, page, tx: str) -> None:
    page.goto(f"{t.origin}/verify/tx/{tx}")
    page.wait("!!document.querySelector('[data-testid=\"tx-fee\"], [data-testid=\"error-banner\"]')", 90)
    t.check(page.exists("tx-fee"), "What the chain sees: the transaction, with its fee (public)")
    amounts = page.eval("[...document.querySelectorAll('[data-testid=\"tx-output\"]')].map(e => e.dataset.amount)")
    t.check(amounts and set(amounts) == {"hidden"}, f"every output amount is hidden ({amounts})")


def send_to_address(t: T, page, text: str, address: str, safety: list[str], direct: bool = False) -> str:
    """Sender side of a send to a Tari address (/send); returns the delivery transaction id. In direct
    mode it does what /judges B3 says: reads the line above Send and waits until this send goes from
    the browser's wallet, then checks that the browser posted the transaction itself."""
    page.goto(t.origin + "/send")
    page.wait_for("drop-input")
    flows.lock_text(page, text)
    page.wait_for("send-recipient", 120)
    page.fill("send-recipient", address)
    page.wait_for("send-safety")
    t.check(safety_emoji(page, "send-safety") == safety, "the send screen shows the recipient's safety code")
    if direct:
        own = page.wait("document.querySelector('[data-testid=\"send-path\"]')?.dataset.path === 'direct'", 240)
        t.check(own, "direct mode: the line above Send says this send goes from the browser's wallet (within 4 minutes)")
        page.collect()
        before = len(page.requests)
    page.click("send-submit")
    t.check(page.wait_state("send-status", ("delivered", "failed"), 420) == "delivered", "Delivered privately")
    tx = page.attr("send-tx", "data-tx")
    t.check(tx and TX.match(tx), "the send has a transaction id")
    if direct:
        page.collect()
        t.check(any(r["method"] == "POST" and r["url"].endswith("/api/v1/chain/ix/transactions") for r in page.requests[before:]),
                "direct mode: the browser built and submitted the send itself")
        t.check("built and paid" in page.text("send-status"), "the sentence after the send says the browser paid for it (C8)")
    tx_view(t, page, tx)
    return tx


@scenario("E-09", "Dead drop on chain: a phone's drive makes a drop link, desktop leaves a GPS photo, Received opens it", CHAIN)
def e09(t: T) -> None:
    a = t.actor("android")
    drop_url = make_drop_link(t, a, "E2E E-09")
    if a.exists("key-later"):
        a.click("key-later")
    safety, _ = locker_identity(a)
    b = t.actor("desktop")
    tx = leave_photo(t, b, drop_url, safety)
    tx_view(t, b, tx)
    t.check(open_inbox_item(t, a, "drop") == "opened", "the phone opens the delivery in Received")
    a.wait_for("received-save-file", 60)
    a.click("received-save-file")
    gps, orientation = t.env.remote.as_build(f"python3 -I -c {shlex.quote(PHOTO_CHECK)} {t.downloaded(a)}").split()
    t.check(gps == "clean", "the decrypted photo has no GPS")
    t.check(orientation == "oriented", "the decrypted photo keeps its orientation")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


@scenario("E-10", "Send to a Tari address on chain; /verify shows hidden amounts; the recipient opens it", CHAIN)
def e10(t: T) -> None:
    a = t.actor()
    make_drop_link(t, a, "E2E E-10 recipient")
    if a.exists("key-later"):
        a.click("key-later")
    safety, address = locker_identity(a)
    b = t.actor()
    send_to_address(t, b, "E2E E-10 sent to an address", address, safety)
    t.check(open_inbox_item(t, a, "send") == "opened", "the recipient's drive opens it in Received")
    if t.env.config().get("send_mode") == "relay":
        left = t.env.remote.sql("SELECT COUNT(*) FROM jobs WHERE payload IS NOT NULL AND state IN ('done', 'failed')")[0][0]
        t.check(left == 0, "relay mode: no finished job keeps its payload (the address is forgotten)")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


def sidecar(t: T, *requests: dict) -> list[dict]:
    """Requests to a fresh copy of the release's verifier sidecar, run as drive (its only user)."""
    lines = "".join(json.dumps({"id": i, **r}) + "\n" for i, r in enumerate(requests)).encode()
    out = t.env.remote.run("cd /tmp && sudo -u drive env -i MUTIS_API=http://127.0.0.1:8787 "
                           "/usr/local/lib/mutis/run-sidecar.sh 2>/dev/null", lines)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def mirror(t: T, after: int, limit: int) -> dict:
    with urllib.request.urlopen(f"{t.origin}/api/v1/chain/utxos?after={after}&limit={limit}", timeout=30) as res:
        return json.load(res)


@scenario("E-11", "Kind 4 to another Ootle wallet: its memo is a /t#4 link that opens with the view key alone", CHAIN)
def e11(t: T) -> None:
    # The "other wallet" is a key pair the sidecar makes here: walletd 0.45 can't export a view key.
    keys = sidecar(t, {"cmd": "newKeys"})[0]
    t.secret("the other wallet's view key", keys["view_sk"])
    t.secret("the other wallet's owner key", keys["owner_sk"])
    head = mirror(t, 0, 1)["head"]
    b = t.actor()
    b.goto(t.origin + "/send")
    b.wait_for("drop-input")
    flows.lock_text(b, "E2E E-11 for another wallet")
    b.wait_for("send-recipient", 120)
    b.fill("send-recipient", keys["address"])
    b.choose("send-kind", "4")
    b.click("send-submit")
    t.check(b.wait_state("send-status", ("delivered", "failed"), 420) == "delivered", "Delivered")

    def memo_link() -> str:
        rows = [{k: u[k] for k in ("id", "nonce", "enc")} for u in mirror(t, head, 1000)["items"]]
        found = sidecar(t, {"cmd": "scan", "view_sk": keys["view_sk"], "utxos": rows})[0].get("found", []) if rows else []
        return next((f["memo"].get("Message", "") for f in found if isinstance(f.get("memo"), dict)), "")
    link = poll(memo_link, 600, 10)
    t.check(link.startswith(t.origin + "/t#4"), "the output's memo, read with the view key alone, is a /t#4 link")
    c = t.actor("iphone")
    c.goto(link)
    t.check(c.wait_state("view-root", flows.VIEW_ASK, 90) == "needs-locker", "a browser without a locker is asked for a key")
    if not c.exists("t-viewkey"):
        raise Skipped("opening with a pasted view key needs the t-viewkey / t-viewkey-submit test ids (NOTES, app-ui)")
    c.fill("t-viewkey", keys["view_sk"])
    c.click("t-viewkey-submit")
    # needs-locker is a VIEW_END state too (the page the key was pasted into): wait for the state after it.
    state = c.wait_state("view-root", tuple(s for s in flows.VIEW_ASK if s != "needs-locker"), 120)
    t.check(state == "ready", f"the view key alone unlocks the link (got {state})")
    c.click("view-open")
    t.check(c.wait_state("view-root", flows.VIEW_END, 120) == "opened", "the view key alone opens a kind-4 file")
    t.check("E2E E-11 for another wallet" in c.text("view-text"), "it is the text that was sent")
    t.check(not t.hygiene(), "no secret in any request (E-03)")


@scenario("E-12", "A view key sees the delivery and can open no file", CHAIN)
def e12(t: T) -> None:
    a = t.actor("iphone")
    drop_url = make_drop_link(t, a, "E2E E-12")
    if a.exists("key-later"):
        a.click("key-later")
    safety, address = locker_identity(a)
    leave_photo(t, t.actor(), drop_url, safety)
    open_settings(a)
    a.click("export-view-key")
    a.wait_for("view-key-value")
    view_key = a.eval("(() => { const e = document.querySelector('[data-testid=\"view-key-value\"]');"
                      " return (e.value || e.textContent).trim(); })()")
    t.secret("the view key", view_key)
    c = t.actor()
    c.goto(t.origin + "/watch")
    c.fill("watch-address", address)
    c.fill("watch-viewkey", view_key)
    c.click("watch-run")
    c.wait("Number(document.querySelector('[data-testid=\"watch-summary\"]')?.dataset.deliveries || 0) >= 1", 600)
    t.check(c.attr("watch-summary", "data-readable") == "0", "0 files readable with the view key")
    t.check(not t.hygiene(), "the view key never left the tab (E-03)")


def wallet_ut(page) -> int:
    """The browser wallet's spendable µT after a fresh scan, as /upgrade's "Pay … from this browser" sees it."""
    return int(page.eval("(async () => { const [{ loadIdentity }, { scan }, { balance }] = await Promise.all(["
                         "import('/app/lib/identity.js'), import('/app/lib/scan.js'), import('/app/lib/wallet.js')]);"
                         " const identity = await loadIdentity(); await scan(identity);"
                         " return String(await balance(identity)); })()", await_promise=True, timeout=180))


def release_pack(t: T, page) -> None:
    """Ends the pack this page's locker bought: paid space is capped (40 % of the pool), and a test pack
    would hold its 2 GiB for 30 days and leave the next visitor's B6 "sold out"."""
    locker = page.eval("import('/app/lib/identity.js').then(async ({ loadIdentity }) => (await loadIdentity()).id)",
                       await_promise=True)
    t.check(t.env.remote.admin("release-pack", "--", locker).strip() == "released", "the test pack is released")


@scenario("E-13", "Pack purchase on chain: Waiting → Seen → Amount proven → Added; quota +2 GiB", CHAIN)
def e13(t: T) -> None:
    cfg = t.env.config()
    direct = cfg.get("send_mode") == "direct" and (cfg.get("features") or {}).get("direct_send")
    # Direct mode: the browser pays from its sponsor grant, two a day per network; every locker of a run
    # shares the server's /64, so the buyer holds a one-use judge pass, as E-J does, and waits for the grant.
    judge = t.env.remote.admin("judge-pass", "new", "--uses", "1").strip() if direct else None
    a = t.actor(judge_pass=judge)
    make_drop_link(t, a, "E2E E-13")
    if a.exists("key-later"):
        a.click("key-later")
    a.goto(t.origin + "/drive/storage#more")
    a.wait_for("storage-meter", 60)
    before = int(a.attr("storage-meter", "data-limit") or 0)
    a.click("pack-s30")                   # the pack's dialog asks for today's sponsor grant in direct mode
    a.wait_for("invoice-address", 60)
    if direct:
        price = next(int(p["price_ut"]) for p in cfg["pricing"]["packs"] if p["id"] == "s30")
        t.check(poll(lambda: wallet_ut(a) >= price + int(cfg["courier"]["max_fee_ut"]), 600, 10),
                "direct mode: the browser wallet received its sponsor grant")
    a.click("pay-browser" if direct else "demo-pay")
    t.check(a.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 420),
            "the invoice is credited")
    steps = a.eval("[...document.querySelectorAll('[data-testid=\"pay-step\"]')].map(e => e.dataset.step)")
    t.check(steps, f"the stepper shows its steps ({steps})")
    a.goto(t.origin + "/drive/storage")
    a.wait_for("storage-meter", 60)
    t.check(int(a.attr("storage-meter", "data-limit") or 0) >= before + 2 * 1024 ** 3, "the quota grew by 2 GiB")
    release_pack(t, a)


@scenario("E-14", "Payment forgery: a payment row for a UTXO that doesn't exist is never credited", CHAIN)
def e14(t: T) -> None:
    buyer = apiclient.Client(t.origin)
    buyer.register()
    _, invoice = buyer.call("POST", "/invoices", {"pack": "s30"})
    t.env.remote.admin("e2e-forge-payment", invoice["invoice_id"])
    flagged = poll(lambda: json.loads(t.env.remote.sql("SELECT value FROM meta WHERE key = 'chain_status'")[0][0])
                   .get("payments_unconfirmed", 0) > 0, 900, 30)
    t.check(flagged, "health counts the unconfirmed payment")
    _, status = buyer.call("GET", f"/invoices/{invoice['invoice_id']}")
    t.check(status["status"] != "credited", "the forged payment was never credited")


@scenario("E-25", "Canary: forced run is delivered, found in the mirror, opened; /canary and evidence show it", CHAIN)
def e25(t: T) -> None:
    started = int(time.time())
    t.env.remote.admin("canary-now")

    def verified():
        log = json.loads(t.env.remote.sql("SELECT value FROM meta WHERE key = 'canary_log'")[0][0])
        return next((e for e in log if e["sealed_at"] >= started and e.get("verified")), None)
    entry = poll(verified, 900, 20)
    t.check(entry, "within 15 minutes the delivery is in the mirror and opens with the robot keys")
    client = apiclient.Client(t.origin)
    _, canary = client.call("GET", "/canary")
    t.check(canary.get("delivery_tx") == entry["delivery_tx"], "/api/v1/canary shows the delivery")
    t.env.remote.run("sudo systemctl start mutis-evidence.service")
    with urllib.request.urlopen(urllib.request.Request(t.origin + "/evidence.json", headers={"User-Agent": "mutis-e2e"}),
                                timeout=20) as res:
        evidence = json.load(res)
    t.check(entry["delivery_tx"] in [d["tx_id"] for d in evidence["deliveries"]], "/evidence.json lists the delivery")


# --- integration, pass 2: pay to open on Esmeralda (16-drive-design §4, §10, §15 step 17) -----------------

PAY_LINK = re.compile(r"/p/([A-Za-z0-9_-]{22})#5[A-Za-z0-9_-]{43}$")
PAY_STATES = "['wait','paying','seen','check','unlocking','open','opened','expired','void','used','gone','incomplete','not-found','integrity-error','error']"


def pay_to_open(t: T) -> dict:
    cfg = t.env.config()
    if not (cfg.get("features") or {}).get("pay_to_open"):
        raise Skipped("pay to open is off in this deployment (features.pay_to_open)")
    return cfg


def sell(t: T, page, name: str) -> tuple[str, str]:
    """Share → Someone who pays you → the first price → Make pay link; -> (the /p/ link with its #5 half, the share id)."""
    import scenarios_drive as drv
    drv.row_menu(page, name, "share")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    page.click("share-choice", "pay")
    page.click("share-next")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'pay'", 10)
    page.click("pay-make")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'result'"
              " || !!document.querySelector('#share-dialog [data-testid=\"error-banner\"]')", 180)
    url = page.value("share-link") if page.exists("share-link") else ""
    m = PAY_LINK.search(url)
    t.check(bool(m and url.startswith(t.origin) and page.wait("!!document.querySelector('[data-testid=\"share-qr\"] svg')", 30)),
            f"Make pay link: a /p/ link with half of the key after the #, and a code to scan ({m[1] if m else page.text('share-dialog')[-120:]})")
    page.key("Escape")
    page.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 10)
    return url, m[1]


def seller_ready(t: T, sid: str, timeout: float = 600) -> dict:
    """GET /p/{id} until the chain worker has opened the drive's sealed sales key (seller.ready)."""
    client = apiclient.Client(t.origin)
    info = poll(lambda: (lambda b: b if b.get("seller", {}).get("ready") else None)(client.call("GET", f"/p/{sid}")[1]), timeout, 10)
    t.check(bool(info), "the payment checker opened the drive's sealed sales key: the seller is ready")
    t.check("otl_" not in json.dumps(info), "the pay page's data never carries the seller's address")
    return info


def pay_page(page, url: str) -> str:
    page.goto(url)
    page.wait(f"{PAY_STATES}.includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)", 90)
    return page.attr("pay-page", "data-state")


def pay_wait(page, states: tuple[str, ...], timeout: float) -> str:
    page.wait(f"{json.dumps(list(states))}.includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)", timeout)
    return page.attr("pay-page", "data-state")


def pay_steps(page) -> list[str]:
    return page.eval("[...document.querySelectorAll('[data-testid=\"pay-claim-step\"] li')].map((l) => l.dataset.step + ':' + l.dataset.state)")


def paid_402(t: T, sid: str) -> None:
    try:
        apiclient.Client(t.origin).call("POST", f"/s/{sid}/open", {})
        t.check(False, "a stranger without a paid claim can't open it")
    except apiclient.ApiError as e:
        t.check(e.status == 402, f"a stranger with the same link and no payment: 402 payment_required ({e.status})")


def open_paid_folder(t: T, page, wanted: list[str], one: str) -> None:
    page.click("pay-open")
    page.wait_for("folder-view", 90)
    names = sorted(page.eval("[...document.querySelectorAll('[data-testid=\"fv-row\"]')].map((e) => e.dataset.name)"))
    t.check(names == sorted(wanted), f"the folder lists its names ({names})")
    page.eval(f"[...document.querySelectorAll('[data-testid=\"fv-row\"]')].find((e) => e.dataset.name === {json.dumps(one)}).querySelector('[data-testid=\"fv-open\"]').click()")
    page.wait("document.querySelector('[data-testid=\"fv-preview\"] .fv-preview-body')?.dataset.state === 'open'", 90)
    t.check(page.exists("fv-preview-save"), f"{one} opens on the phone, with Save")


@scenario("E-29", "Pay to open a folder with test money: a drive sells a folder of three; a phone with no drive pays; Waiting → Unlocked; three names, one opens; a reload keeps its opens; a second stranger gets 402", CHAIN)
def e29(t: T) -> None:
    import scenarios_drive as drv
    pay_to_open(t)
    judge = t.env.remote.admin("judge-pass", "new", "--uses", "4").strip()
    desk = t.actor("desktop", judge_pass=judge)
    desk.goto(t.origin + "/drive?make")
    desk.wait_for("drive-root", 120)
    desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    files = {"minutes.txt": b"E2E E-29 the council minutes.\n", "agenda.txt": b"E2E E-29 agenda.\n", "budget.txt": b"E2E E-29 budget.\n"}
    drv.upload_folder(t, desk, "council", files)
    folder = f"{t.sid}-council"
    url, sid = sell(t, desk, folder)
    info = seller_ready(t, sid)
    t.check(info["kind"] == "folder" and info["child_count"] == 3, f"the page knows a folder of three ({info['kind']}, {info['child_count']})")
    phone = t.actor("iphone", judge_pass=judge)
    t.check(pay_page(phone, url) == "wait" and phone.text("pay-name") == folder and "3" in phone.text("pay-what"),
            f"the phone: the folder's name, three files, about how big, the price and the fee ({phone.text('pay-what')})")
    t.check(not phone.exists("folder-view") and not phone.exists("pay-address"), "the names inside stay locked; no address before a claim")
    t.shot(phone, "1-teaser")
    started = time.monotonic()
    phone.click("pay-test")
    t.check(pay_wait(phone, ("open", "expired", "void", "error"), 420) == "open", f"Pay with test money: Waiting → Seen → On the chain → Unlocked ({pay_steps(phone)})")
    t.note(f"test money to Unlocked: {time.monotonic() - started:.0f} s")
    t.check(all(s.endswith(":done") for s in pay_steps(phone)), f"every step done ({pay_steps(phone)})")
    t.shot(phone, "2-unlocked")
    open_paid_folder(t, phone, list(files), "minutes.txt")
    t.shot(phone, "3-open")
    phone.reload()
    t.check(pay_wait(phone, ("open",), 90) == "open" and phone.text("pay-left").startswith("2 opens left"), f"a reload keeps the claim ({phone.text('pay-left')})")
    tx = phone.attr("pay-tx", "data-tx") if phone.exists("pay-tx") else None
    t.check(bool(tx and TX.match(tx)), "the page links the test money's transaction")
    if tx:
        tx_view(t, phone, tx)
    sent = " ".join(r["url"] + json.dumps(r.get("headers", {})) for r in phone.requests + desk.requests)
    t.check(url.split("#")[1] not in sent and "minutes.txt" not in sent and folder not in sent, "no name and not the link's half of the key in any request (E-03)")
    paid_402(t, sid)
    other = t.actor()
    t.check(pay_page(other, url) == "wait" and not other.exists("folder-view"), "a second stranger sees the price and no files")
    desk.reload()
    desk.wait_for("drive-root", 120)
    badge = desk.wait(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].find((e) => e.dataset.name === {json.dumps(folder)})"
                      "?.querySelector('[data-rule=\"pay\"]')?.textContent.trim() ?? ''", 120)
    t.check(badge.startswith("Pay "), f"the seller's folder wears its price ({badge})")
    t.env.remote.admin("takedown", "share", "--", sid)                  # ends the link and its claims


@scenario("E-30", "Pay from my drive: a phone's drive pays a paid file from its own wallet; it waits for the owner's drive; the seller's drive opens and checks it; the phone opens it; the seller's Received says Yours to spend", CHAIN)
def e30(t: T) -> None:
    import scenarios_drive as drv
    cfg = pay_to_open(t)
    judge = t.env.remote.admin("judge-pass", "new", "--uses", "4").strip()
    desk = t.actor("desktop", judge_pass=judge)
    desk.goto(t.origin + "/drive?make")
    desk.wait_for("drive-root", 120)
    desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    drv.upload_files(t, desk, {"report.txt": b"E2E E-30 the quarterly report.\n"})
    url, sid = sell(t, desk, "report.txt")
    seller_ready(t, sid)
    phone = t.actor("iphone", judge_pass=judge)
    phone.goto(t.origin + "/drive?make")
    phone.wait_for("drive-root", 120)
    block = cfg.get("pay_to_open") or {}
    price, fee = int((block.get("prices_ut") or ["100000"])[0]), int(block.get("fee_ut") or cfg["courier"]["max_fee_ut"])
    t.check(poll(lambda: wallet_ut(phone) >= price + fee, 600, 10),
            "the phone's drive received its sponsor grant (enough for the price and the fee)")
    pay_page(phone, url)
    phone.wait_for("pay-browser", 180)
    t.shot(phone, "1-pay-from-drive")
    phone.click("pay-browser")
    t.check(pay_wait(phone, ("check", "open", "expired", "void", "error"), 600) == "check",
            f"paid from the drive: it waits for the owner's drive ({pay_steps(phone)})")
    t.shot(phone, "2-owner-check")
    desk.goto(t.origin + "/drive/received")                            # the owner check runs as the drive opens
    t.check(bool(desk.wait("document.querySelector('[data-testid=\"sales-row\"]')?.dataset.check === 'ok'", 300)),
            "the seller's drive checks the payment: Yours to spend")
    t.shot(desk, "3-received")
    t.check(pay_wait(phone, ("open", "void", "error"), 300) == "open", "the owner's drive confirmed it: the phone can open it")
    phone.click("pay-open")
    phone.wait_for("pay-file", 90)
    t.check(phone.text("pay-file").startswith("report.txt"), "the file opens on the phone")
    t.env.remote.admin("takedown", "share", "--", sid)


@scenario("E-J", "The judge script (/judges, 16-drive-design §10): track one, six steps on a computer and a phone; track two, six with a pay link and test money (with pay to open off: Send by Tari and Get more space), each step timed", CHAIN)
def ej(t: T) -> None:
    import scenarios_drive as drv
    cfg = t.env.config()
    direct = cfg.get("send_mode") == "direct" and (cfg.get("features") or {}).get("direct_send")
    # Direct mode: both contexts share one /64 (the server's), like two judges in one office, and earlier
    # drives of this run took that network's daily sponsor grant; so, like a judge, they use a pass.
    pay = bool((cfg.get("features") or {}).get("pay_to_open"))
    # With pay to open on, track two is §10's (a pay link, test money); the judge pass also lifts the test-money caps.
    judge = t.env.remote.admin("judge-pass", "new", "--uses", "6" if pay else "3").strip() if direct or pay else None
    phone, desk = t.actor("iphone", judge_pass=judge), t.actor("desktop", judge_pass=judge)
    started = mark = time.monotonic()
    seconds: dict[str, float] = {}

    def done(step: str) -> None:
        nonlocal mark
        seconds[step], mark = time.monotonic() - mark, time.monotonic()
        t.note(f"{step}: {seconds[step]:.0f} s")

    # Track one: a computer and a phone with the drive (16-drive-design §10), no wallet, no sign-up
    flows.home(desk, t.origin)
    desk.click("home-make")
    desk.wait_for("drive-root", 120)
    desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    t.check(True, "1: Make my drive: the drive opens, its key made in this browser")
    done("1")
    folder = f"{t.sid}-council"
    drv.upload_folder(t, desk, "council", {"minutes.txt": b"E2E E-J the council minutes.\n", "agenda.txt": b"E2E E-J agenda.\n",
                                          "notes.txt": b"E2E E-J notes for the buyer.\n"})
    done("2")
    drv.into(desk, folder)
    drv.wait_names(desk, ["minutes.txt", "agenda.txt"])
    drv.row_menu(desk, "minutes.txt", "share")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    desk.click("share-next")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
    desk.click("share-then-delete")
    desk.click("share-make")
    desk.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
    url = desk.value("share-link")
    t.check("#" in url and bool(desk.wait("!!document.querySelector('[data-testid=\"share-qr\"] svg')", 30)),
            "3: Share, Once, Delete it from my drive after, Make link: a link and a code to scan")
    desk.key("Escape")
    done("3")
    t.check(flows.open_link(phone, url) == "opened", "4: the phone taps Open it and has the file")
    phone.reload()
    t.check(phone.wait_state("view-root", flows.VIEW_ASK, 60) == "burned" and "This link has ended." in phone.text("view-root"),
            "4: the phone reloads: “This link has ended.”")
    t.shot(phone, "1-4-gone")
    done("4")
    desk.goto(t.origin + "/drive/activity")
    desk.wait_for("activity-feed", 60)
    left = desk.wait("(() => { const e = [...document.querySelectorAll('[data-event=\"left\"]')].find((x) => x.dataset.name === 'minutes.txt');"
                     " return e ? e.textContent : ''; })()", 120)
    opened = desk.eval("[...document.querySelectorAll('[data-event=\"opened\"]')].some((x) => x.dataset.name === 'minutes.txt')")
    t.check("It left your drive" in left and opened, f"5: Activity: Opened, then It left your drive ({left[:80]}, opened {opened})")
    t.shot(desk, "1-5-activity")
    done("5")
    desk.click("open-known")
    desk.wait_for("known-sheet", 15)
    t.check("What it never stores" in desk.text("known-sheet"), "6: What our server knows: what it keeps, and what it never stores")
    desk.key("Escape")
    done("6")
    track_one = time.monotonic() - started
    if pay:
        # Track two (16-drive-design §10): a pay link for the folder, test money on the phone, Received, the tx
        desk.goto(t.origin + "/drive")
        desk.wait_for("drive-root", 120)
        drv.wait_names(desk, [folder])
        url, sid = sell(t, desk, folder)
        seller_ready(t, sid)
        t.shot(desk, "2-1-pay-link")
        desk.goto(t.origin + "/drive/received")            # fifth pass: Received is open before the phone pays
        desk.wait_for("drive-root", 120)
        done("T1")
        t.check(pay_page(phone, url) == "wait" and phone.text("pay-name") == folder and "2" in phone.text("pay-what"),
                f"T2: the phone scans it: the folder's name, how many files, about how big, the price and the fee ({phone.text('pay-what')})")
        t.check(not phone.exists("folder-view"), "T2: the names inside stay locked")
        t.shot(phone, "2-2-teaser")
        done("T2")
        phone.click("pay-test")
        t.check(pay_wait(phone, ("open", "expired", "void", "error"), 420) == "open", f"T3: Pay with test money: the steps run to Ready to open ({pay_steps(phone)})")
        t.shot(phone, "2-3-unlocked")
        done("T3")
        open_paid_folder(t, phone, ["agenda.txt", "notes.txt"], "notes.txt")
        t.shot(phone, "2-4-open")
        done("T4")
        row = ("(() => { const r = document.querySelector('[data-testid=\"sales-row\"]'); return !!r && r.dataset.check === 'ok'"
               " && !!r.querySelector('[data-testid=\"sales-test\"]') && !!r.querySelector('[data-testid=\"sales-checked\"]')"
               " && !!r.querySelector('[data-testid=\"sales-tx\"]'); })()")
        t.check(bool(desk.wait(row, 300)),
                "T5: Received, Payments (open since T1, no reload): the payment, marked Test money, Checked and Yours to spend, with its tx")
        t.shot(desk, "2-5-received")
        done("T5")
        phone.reload()
        pay_wait(phone, ("open",), 90)
        tx = phone.attr("pay-tx", "data-tx") if phone.exists("pay-tx") else None
        t.check(bool(tx and TX.match(tx)), "T6: the phone has What the chain sees")
        tx_view(t, phone, tx or "0" * 64)
        t.shot(phone, "2-6-chain")
        done("T6")
        t.env.remote.admin("takedown", "share", "--", sid)              # ends the link and its claim
        t.note("seconds per step: " + json.dumps({k: round(v) for k, v in seconds.items()}))
        two = time.monotonic() - started - track_one
        t.note(f"track one {track_one:.0f} s, track two {two:.0f} s")
        t.check(track_one <= 180 and two <= 420, f"track one {track_one / 60:.1f} min (≤ 3), track two {two / 60:.1f} min (≤ 7)")
        return

    # The Tari part, on the same two: the drive's address code carries the phone's send to the computer
    opened = time.monotonic()
    safety, address = locker_identity(desk)
    t.check(len(safety) == 12 and address.startswith("otl_esm_1") and bool(desk.wait("!!document.querySelector('[data-testid=\"locker-qr\"] svg')", 30)),
            "B1: My Tari address, Settings: the drive's address, its safety code and a code to scan")
    t.shot(desk, "B1-settings")
    desk.key("Escape")
    done("B1")
    phone.goto(f"{t.origin}/#to={address}")
    phone.wait("!!document.querySelector('[data-testid=\"drop-input\"]') && !!document.querySelector('[data-testid=\"to-address\"]')", 60)
    flows.lock_text(phone, "E2E E-J sent to the computer")
    phone.wait(f"document.querySelector('[data-testid=\"send-recipient\"]')?.value === {json.dumps(address)} && !!document.querySelector('[data-testid=\"send-safety\"]')", 180)
    t.check(safety_emoji(phone, "send-safety") == safety, "B2: the send step has the scanned address and its safety code")
    if direct:
        phone.wait("['direct', 'relay'].includes(document.querySelector('[data-testid=\"send-path\"]')?.dataset.path)", 240)
    phone.click("send-submit")
    t.check(phone.wait_state("send-status", ("delivered", "failed"), 420) == "delivered", "B2: it goes by Tari")
    tx = phone.attr("send-tx", "data-tx")
    t.check(bool(tx and TX.match(tx)), "B2: the send has a transaction id")
    tx_view(t, phone, tx)
    done("B2")
    t.check(open_inbox_item(t, desk, "send") == "opened", "B3: Received: the computer opens what the phone sent")
    t.shot(desk, "B3-received")
    desk.key("Escape")
    done("B3")
    desk.goto(t.origin + "/drive/storage#more")
    desk.wait_for("storage-meter", 60)
    desk.click("pack-s30")
    desk.wait_for("invoice-address", 60)
    if direct:
        price = next(int(p["price_ut"]) for p in cfg["pricing"]["packs"] if p["id"] == "s30")
        funded = poll(lambda: wallet_ut(desk) >= price + int(cfg["courier"]["max_fee_ut"]), 600, 10)
        cold = time.monotonic() - opened
        t.note(f"cold start: the sponsor grant was spendable {cold:.0f} s after the drive opened")
        t.check(funded, "direct mode: the computer's browser wallet received its sponsor grant")
    desk.click("pay-browser" if direct else "demo-pay")
    t.check(desk.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 300),
            "B4: Get more space: checked on the chain, then added")
    done("B4")
    t.note("seconds per step: " + json.dumps({k: round(v) for k, v in seconds.items()}))
    t.note(f"track one {track_one:.0f} s, the Tari part {time.monotonic() - started - track_one:.0f} s")
    minutes = (time.monotonic() - started) / 60
    t.check(minutes <= 6, f"both tracks took {minutes:.1f} minutes (≤ 6)")
    release_pack(t, desk)
