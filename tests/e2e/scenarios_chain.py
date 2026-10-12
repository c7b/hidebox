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
from scenarios import locker_identity, make_drop_link, safety_emoji

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
    page.goto(t.origin + "/inbox")
    item = poll(lambda: page.eval(f"!!document.querySelector('[data-testid=\"inbox-item\"][data-source=\"{source}\"]')"),
                600, 5)
    t.check(item, f"the inbox lists a delivery from {source}")
    t.check(page.attr("inbox-scan", "data-checked"), "the scan line says how many outputs it checked")
    page.eval(f"document.querySelector('[data-testid=\"inbox-item\"][data-source=\"{source}\"] button, "
              f"[data-testid=\"inbox-item\"][data-source=\"{source}\"] a').click()")
    return page.wait_state("view-root", flows.VIEW_END, 180)


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


@scenario("E-09", "Dead drop on chain: phone makes a drop link, desktop leaves a GPS photo, inbox opens it", CHAIN)
def e09(t: T) -> None:
    a = t.actor("android")
    drop_url = make_drop_link(t, a, "E2E E-09")
    if a.exists("key-later"):
        a.click("key-later")
    a.goto(t.origin + "/locker")
    a.wait_for("locker-safety")
    safety, _ = locker_identity(a)
    b = t.actor("desktop")
    tx = leave_photo(t, b, drop_url, safety)
    tx_view(t, b, tx)
    t.check(open_inbox_item(t, a, "drop") == "opened", "the phone opens the delivery")
    t.check(a.exists("view-image") and a.exists("view-chain-saw"), "it shows the photo and What the chain saw")
    a.click("view-save")
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
    a.goto(t.origin + "/locker")
    a.wait_for("locker-address")
    safety, address = locker_identity(a)
    b = t.actor()
    send_to_address(t, b, "E2E E-10 sent to an address", address, safety)
    t.check(open_inbox_item(t, a, "send") == "opened", "the recipient's inbox opens it")
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
    a.goto(t.origin + "/locker")
    a.wait_for("locker-safety")
    safety, address = locker_identity(a)
    leave_photo(t, t.actor(), drop_url, safety)
    a.goto(t.origin + "/locker")
    a.wait_for("locker-safety", 120)
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
    a.goto(t.origin + "/locker")
    a.wait_for("quota-bar", 60)
    before = int(a.attr("quota-bar", "data-limit") or 0)
    a.goto(t.origin + "/upgrade")
    if direct:
        price = next(int(p["price_ut"]) for p in cfg["pricing"]["packs"] if p["id"] == "s30")
        t.check(poll(lambda: wallet_ut(a) >= price + int(cfg["courier"]["max_fee_ut"]), 600, 10),
                "direct mode: the browser wallet received its sponsor grant")
    a.click("pack-s30")
    a.wait_for("invoice-address", 60)
    a.click("pay-browser" if direct else "demo-pay")
    t.check(a.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 420),
            "the invoice is credited")
    steps = a.eval("[...document.querySelectorAll('[data-testid=\"pay-step\"]')].map(e => e.dataset.step)")
    t.check(steps, f"the stepper shows its steps ({steps})")
    a.goto(t.origin + "/locker")
    a.wait_for("quota-bar", 60)
    t.check(int(a.attr("quota-bar", "data-limit") or 0) >= before + 2 * 1024 ** 3, "the quota grew by 2 GiB")


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


@scenario("E-J", "The judge script (/judges, tracks A and B) on a phone and a desktop, each step timed", CHAIN)
def ej(t: T) -> None:
    cfg = t.env.config()
    direct = cfg.get("send_mode") == "direct" and (cfg.get("features") or {}).get("direct_send")
    # Direct mode: both contexts share one /64 (the server's), like two judges in one office, and earlier
    # lockers of this run took that network's daily sponsor grant; so, like a judge, they use a pass.
    judge = t.env.remote.admin("judge-pass", "new", "--uses", "3").strip() if direct else None
    phone, desk = t.actor("iphone", judge_pass=judge), t.actor("desktop", judge_pass=judge)
    started = mark = time.monotonic()
    seconds: dict[str, float] = {}

    def done(step: str) -> None:
        nonlocal mark
        seconds[step], mark = time.monotonic() - mark, time.monotonic()
        t.note(f"{step}: {seconds[step]:.0f} s")

    # Track A · 60 seconds, no wallet
    flows.home(desk, t.origin)
    flows.seal_file(desk, t.fixture("notes.txt"))
    url = flows.wait_link(desk)
    t.check("#" in url, "A1: a link whose part after # is the key")
    done("A1")
    t.check(flows.open_link(phone, url) == "opened", "A2: the phone opens the file")
    done("A2")
    phone.reload()
    t.check(phone.wait_state("view-root", flows.VIEW_ASK, 60) == "burned", "A3: reload → This secret already made its exit")
    t.shot(phone, "A3-exit")
    done("A3")
    size = apiclient.Client(t.origin).call("GET", "/canary")[1]["size_stored"]
    flows.home(phone, t.origin)
    phone.eval("document.querySelector('a[href=\"/api/v1/canary/raw\"]').click()")
    stored = int(t.env.remote.as_build(f"stat -c %s {shlex.quote(t.downloaded(phone))}"))
    t.check(stored == size, f"A4: Download the stored bytes saves our latest canary as stored ({stored} bytes)")
    done("A4")
    track_a = time.monotonic() - started

    # Track B · 5 minutes, the Tari part
    drop_url = make_drop_link(t, phone, "Council")
    opened = time.monotonic()
    phone.click("key-later")
    phone.goto(t.origin + "/locker")
    phone.wait_for("locker-safety")
    safety, address = locker_identity(phone)
    t.check(len(safety) == 12 and address.startswith("otl_esm_1"), "B1: a locker with a 12-emoji safety code and a Tari address")
    t.shot(phone, "B1-locker")
    if direct:
        # /judges B1, direct mode: the computer opens its locker now, so by B3 it holds the grant it sends from.
        make_drop_link(t, desk, "Council computer")
        if desk.exists("key-later"):
            desk.click("key-later")
    done("B1")
    leave_photo(t, desk, drop_url, safety)
    t.shot(desk, "B2-chain-sees")
    done("B2")
    send_to_address(t, desk, "E2E E-J sent to the phone", address, safety, direct=bool(direct))
    done("B3")
    t.check(open_inbox_item(t, phone, "drop") == "opened", "B4 (and B2): the phone's inbox opens what was left in its drop")
    t.check(open_inbox_item(t, phone, "send") == "opened", "B4: the phone's inbox opens what the computer sent")
    t.shot(phone, "B4-inbox-opened")
    done("B4")
    phone.goto(t.origin + "/locker")
    phone.click("watch-mine")
    phone.wait("Number(document.querySelector('[data-testid=\"watch-summary\"]')?.dataset.deliveries || 0) >= 2", 600)
    t.check(phone.attr("watch-summary", "data-readable") == "0", "B5: 0 files readable with the view key")
    done("B5")
    phone.goto(t.origin + "/upgrade")
    if direct:
        price = next(int(p["price_ut"]) for p in cfg["pricing"]["packs"] if p["id"] == "s30")
        funded = poll(lambda: wallet_ut(phone) >= price + int(cfg["courier"]["max_fee_ut"]), 600, 10)
        cold = time.monotonic() - opened
        t.note(f"cold start: the sponsor grant was spendable {cold:.0f} s after the locker opened")
        t.check(funded, "direct mode: the phone's browser wallet received its sponsor grant")
        t.check(cold <= 195, f"cold start {cold:.0f} s: the grant is there within 3:15 (spec §18.2 step 5)")
    phone.click("pack-s30")
    phone.wait_for("invoice-address", 60)
    phone.click("pay-browser" if direct else "demo-pay")
    t.check(phone.wait("document.querySelector('[data-testid=\"invoice-status\"]')?.dataset.status === 'credited'", 300),
            "B6: Amount proven → Added")
    if direct:
        phone.collect()
        t.check(any(r["method"] == "POST" and r["url"].endswith("/api/v1/chain/ix/transactions") for r in phone.requests),
                "B6: the browser built and submitted the payment itself (direct)")
    done("B6")
    if (cfg.get("features") or {}).get("seallog"):
        desk.goto(t.origin + "/verify")
        desk.wait("document.querySelectorAll('[data-testid=\"verify-item\"]').length >= 2 && ![...document.querySelectorAll("
                  "'[data-testid=\"verify-stored\"], [data-testid=\"verify-exit\"]')].some((e) => /Checking/.test(e.textContent))", 120)
        items = desk.eval("[...document.querySelectorAll('[data-testid=\"verify-item\"]')].map((e) => e.textContent)")
        receipts = re.compile(r"included at checkpoint #\d+ \(epoch \d+\)|not on the record yet")
        t.check(all(receipts.search(i) for i in items), f"B7: each receipt is on the record or waits for the next checkpoint ({items})")
        t.check(any("Exit:" in i for i in items), "B7: the exit receipt from A3 is listed")
        t.check("has no owner" in desk.text("verify-log"), "B7: the page says the log has no owner and names its writer")
        t.shot(desk, "B7-verify")
        done("B7")
    t.note("seconds per step: " + json.dumps({k: round(v) for k, v in seconds.items()}))
    t.note(f"track A {track_a:.0f} s, track B {time.monotonic() - started - track_a:.0f} s")
    minutes = (time.monotonic() - started) / 60
    t.check(minutes <= 6, f"both tracks took {minutes:.1f} minutes (≤ 6)")
