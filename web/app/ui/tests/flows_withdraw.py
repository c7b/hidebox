# SPDX-License-Identifier: MIT
"""Withdrawing earnings (docs/withdraw.md), in headless Chromium, with features.withdraw on: Earnings shows what is
ready (settled payments only) and what is still being checked; the dialog refuses an address on another network, one
with a payment reference, the drive's own sales address, too little and too much; the confirm step shows what
arrives, the fee taken from it, what leaves the earnings and the address with its first and last 6 characters set
apart; Send pressed twice submits once; the receipt links What the chain sees; the change is ready again.

The withdrawal routes are the dev server's own: it checks the signed withdrawal (shape, this drive's settled inputs,
nothing on its way), marks it and relays it to its fake indexer. The money is genuine: the page builds stealth outputs
to the drive's sales address with the official library (flows_pay OUTPUTS_JS), PayFake serves them as the indexer's
substates and answers the chain's decision, and the test records them as payments the way the payment checker would.
The test decodes the envelope the page sent and opens its outputs: the address's output with that address's view key,
the change with the sales view key."""
import base64
import glob
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

from flows import no_hscroll, scenario
from flows_drive import set_device, upload_files
from flows_pay import OUTPUTS_JS, PAY_LINK, UTXO_PREFIX, PayFake, attach, close_dialog, sell

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "server"))
from mutis import cbor  # noqa: E402

FEATURES = ("folders", "pay_to_open", "withdraw")


def wdb(t):
    found = glob.glob(os.path.join(t.work, "data-sidecar-" + "-".join(FEATURES), "**", "mutis.sqlite3"), recursive=True)
    return sqlite3.connect(found[0], timeout=30)


def write(t, sql, args=()):
    con = wdb(t)
    con.execute(sql, args)
    con.commit()
    con.close()


def read(t, sql, args=()):
    con = wdb(t)
    rows = con.execute(sql, args).fetchall()
    con.close()
    return rows


class WithdrawFake(PayFake):
    """PayFake, recording each withdrawal the page posts (it still goes to the dev server)."""

    def attach(self, page):
        self.withdrawals = getattr(self, "withdrawals", [])
        ic = super().attach(page)
        ic.add("*/api/v1/me/withdrawals", "Request", self.record, "POST")
        return ic

    def record(self, params):
        raw = params["request"].get("postData")
        self.withdrawals.append(json.loads(raw) if raw else None)
        return None

    def get_sales(self, params):
        """Earnings' totals as the dev server counts the payments this test recorded (PayFake keeps its own)."""
        hdrs = {k: v for k, v in params["request"]["headers"].items() if k.lower() == "authorization"}
        with urllib.request.urlopen(urllib.request.Request(self.t.origin + "/api/v1/me/sales", headers=hdrs), timeout=30) as res:
            return res.status, json.loads(res.read())


def seller(t, fake, device="desktop"):
    page = t.actor(device)
    page.goto(t.origin + "/drive")
    page.wait("!!document.querySelector('script')", 30)
    fake.watch = page.eval("import('/app/lib/ootle.js').then((m) => m.newRandomKeys()).then((k) => k.address)")
    attach(t, fake, page)
    page.goto(t.origin + "/drive?make")
    page.wait_for("drive-root", 90)
    page.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    write(t, "UPDATE identities SET distinct_days = 2")
    page.reload()
    page.wait_for("drive-root", 90)
    upload_files(t, page, ["notes.txt"])
    return page


def pay(t, share_id, utxo_id, value, status="counted"):
    """A buyer's payment as the payment checker records it: test money for the whole price, counted (or still being
    checked)."""
    cid = "clm_" + "".join(re.findall(r"[a-z2-7]", utxo_id[-40:]))[:20].ljust(20, "a")
    now = int(time.time())
    write(t, "INSERT INTO claims(id, share_id, token_hash, address, price_ut, received_ut, status, created_at, created_seq, "
             "expires_at, demo) VALUES (?, ?, ?, 'test', ?, ?, 'released', ?, 0, ?, 1)",
          (cid, share_id, os.urandom(32), value, value, now, now + 3600))
    write(t, "INSERT INTO sale_payments(utxo_id, claim_id, value_ut, seen_at, status, committed) VALUES (?, ?, ?, ?, ?, ?)",
          (utxo_id, cid, value, now, status, int(status != "pending_check")))


def earnings(page):
    page.click("nav-earnings")
    page.wait("!!document.querySelector('[data-testid=\"withdraw-ready\"]')", 60)


def ready_ut(page):
    return page.eval("document.querySelector('[data-testid=\"withdraw-ready\"]')?.dataset.ut ?? ''")


def dialog_step(page):
    return page.eval("document.getElementById('withdraw-dialog')?.dataset.step ?? ''")


def try_address(page, address, amount="0.3"):
    page.eval(f"""(() => {{ const to = document.getElementById('wd-to'); to.value = {json.dumps(address)}; to.dispatchEvent(new Event('input'));
      const a = document.getElementById('wd-amount'); a.value = {json.dumps(amount)}; a.dispatchEvent(new Event('input')); }})()""")
    page.click("withdraw-next")
    page.wait("!document.querySelector('[data-testid=\"withdraw-next\"]')?.disabled", 60)   # Continue answered
    page.wait("document.getElementById('withdraw-dialog')?.dataset.step === 'confirm' || !!document.querySelector('#withdraw-dialog [data-testid=\"withdraw-error\"], #withdraw-dialog [data-testid=\"error-banner\"]')", 60)
    return page.eval("document.querySelector('#withdraw-dialog [data-testid=\"withdraw-error\"]')?.textContent ?? ''")


@scenario("withdraw", "Withdraw earnings (docs/withdraw.md): ready and still being checked; refused addresses (another network, a payment "
          "reference, the drive's own) and amounts; the confirm step (what arrives, the fee from it, what leaves, the address "
          "set apart); Send twice submits once, the dev server checks and relays it; the receipt; the change is ready again", features=FEATURES)
def withdraw_flow(t):
    fake = WithdrawFake(t)
    a = seller(t, fake)
    url = sell(a, "notes.txt", price="250000")
    sid = re.search(PAY_LINK, url)[1]
    fake.links[sid]["seller_state"] = "ok"
    close_dialog(a)
    # Three payments to the sales address, genuine outputs: two settled, one still being checked.
    built = a.eval(f"({OUTPUTS_JS})({json.dumps([{'to': 'sales', 'amount': 250000}, {'to': 'sales', 'amount': 100000}, {'to': 'sales', 'amount': 500000}])})")
    ids = fake.add_outputs(built)
    for uid, value, status in zip(ids, (250000, 100000, 500000), ("counted", "counted", "pending_check")):
        pay(t, sid, uid, value, status)

    earnings(a)
    t.check(ready_ut(a) == "350000" and "0.35" in a.text("withdraw-ready"), f"ready to withdraw: the two settled payments ({a.text('withdraw-ready')!r})")
    t.check("Still being checked: 0.5 tTARI." in a.text("withdraw-waiting"), "the payment still being checked is said apart, not offered")
    t.check("never holds a key that can move it" in a.text("withdraw") and "null" not in a.text("withdraw"), "how it works, in one line")
    t.check("0.35" in a.text("earn-amount"), f"Earnings counts the two settled payments ({a.text('earn-amount')!r})")
    a.eval("document.querySelector('.uploads-head button[aria-label=\"Close\"]')?.click()")   # the picture shows the page alone
    t.shot(a, "withdraw-earnings-1440")

    a.click("withdraw-go")
    a.wait("!!document.getElementById('withdraw-dialog') && !document.getElementById('withdraw-dialog').hidden", 20)
    rules = a.text("withdraw-rules")
    t.check("The network fee is 0.03 tTARI, paid from this amount." in rules and "Withdraw at least 0.06 tTARI." in rules
            and "up to 8 payments" in rules, f"the rules, before anything is typed ({rules!r})")
    t.check(a.ax_unnamed() == [], f"every control has a name ({a.ax_unnamed()[:4]})")
    keys = a.eval("""(async () => { const o = await import('/app/lib/ootle.js'); const b = await import('/app/lib/b64.js');
      const { loadIdentity } = await import('/app/lib/identity.js'); const p = await import('/app/lib/pay.js');
      const k = await o.newRandomKeys(); const sales = await p.salesKeys(await loadIdentity({ lazy: true }));
      return { to: await o.addressFromKeys(k.ownerPk, k.viewPk), viewSk: b.hex(k.viewSk), salesViewSk: b.hex(sales.viewSk),
        withRef: await o.addressFromKeys(k.ownerPk, k.viewPk, new Uint8Array([1, 2, 3, 4])), own: sales.address,
        other: o.encodeBech32m('otl_', new Uint8Array([...k.ownerPk, ...k.viewPk])) }; })()""")
    said = try_address(a, keys["other"])
    t.check("That's not a testnet address." in said, f"an address on another network is refused, in the app's words ({said!r})")
    said = try_address(a, keys["withRef"])
    t.check(said == "Use the address without a payment reference.", f"a payment reference is refused ({said!r})")
    said = try_address(a, keys["own"])
    t.check(said == "That's this drive's own sales address. Use another one.", f"the drive's own sales address is refused ({said!r})")
    said = try_address(a, keys["to"], "0.01")
    t.check(said == "Withdraw at least 0.06 tTARI.", f"too little ({said!r})")
    said = try_address(a, keys["to"], "5")
    t.check(said == "That's more than is ready (0.35 tTARI).", f"too much ({said!r})")
    t.check(fake.withdrawals == [], "nothing was sent while anything was refused")
    t.shot(a, "withdraw-refused-1440")

    said = try_address(a, keys["to"], "0.3")
    t.check(dialog_step(a) == "confirm" and said == "", f"a good address and amount reach the confirm step ({said!r})")
    t.check(a.text("withdraw-arrives").replace("\n", " ").endswith("0.27 tTARI") and a.text("withdraw-fee").endswith("0.03 tTARI")
            and a.text("withdraw-leaves").endswith("0.3 tTARI"), "what arrives, the fee taken from it, what leaves the earnings")
    marks = a.eval("[...document.querySelectorAll('#withdraw-dialog .wd-mark')].map((m) => m.textContent)")
    body = keys["to"][len("otl_esm_1"):]
    t.check(marks == [body[:6], body[-6:]] and a.text("withdraw-address") == keys["to"],
            f"the whole address, its first and last 6 characters set apart ({marks})")
    t.check("nobody can undo it" in a.text("withdraw-check") and "null" not in a.eval("document.getElementById('withdraw-dialog').textContent"),
            "check the address first: nobody can undo it")
    t.check(no_hscroll(a), "no sideways scroll at 1440")
    t.shot(a, "withdraw-confirm-1440")
    set_device(a, "iphone")
    t.check(no_hscroll(a), "the confirm step on a phone: no sideways scroll")
    t.shot(a, "withdraw-confirm-390")
    set_device(a, "desktop")

    # Send, pressed twice: one withdrawal.
    a.eval("(() => { const s = document.querySelector('[data-testid=\"withdraw-send\"]'); s.click(); s.click(); })()")
    a.wait("document.getElementById('withdraw-dialog')?.dataset.step === 'done' || !!document.querySelector('#withdraw-dialog [data-testid=\"withdraw-error\"], #withdraw-dialog [data-testid=\"error-banner\"]')", 120)
    err = a.eval("document.querySelector('#withdraw-dialog [data-testid=\"withdraw-error\"], #withdraw-dialog [data-testid=\"error-banner\"]')?.textContent ?? ''")
    t.check(dialog_step(a) == "done" and not err, f"sent, and the chain says it committed ({err!r})")
    posts = [r for r in a.requests if r["url"].endswith("/api/v1/me/withdrawals") and r["method"] == "POST"]
    t.check(len(posts) == 1 and len(fake.withdrawals) == 1, f"Send pressed twice: one withdrawal posted ({len(posts)})")
    link = a.attr("withdraw-chain-link", "href") or ""
    m = re.fullmatch(r"/verify/tx/([0-9a-f]{64})", link)
    t.check(m is not None and "0.27 tTARI is on its way to this address." in a.text("withdraw-receipt-now"),
            f"the receipt: what arrives, the address, What the chain sees ({link})")
    tx = m[1] if m else ""
    t.shot(a, "withdraw-done-1440")

    # What the page sent, decoded: our two payments in, the amount to the address, the change back, the fee.
    sent = fake.withdrawals[0]
    env = cbor.loads(base64.b64decode(sent["transaction"]))
    unsigned = env[1][0][0][0]
    inputs = [cbor.substate_id(i[0]) for i in unsigned[3][1:]]
    statement = unsigned[1][0][1][1]
    outputs, (fee, _seal), _proof = statement[1]
    t.check(sorted(inputs) == sorted(ids[:2]) and fee == 30000 and len(outputs) == 2,
            f"the withdrawal spends the two settled payments, pays the fee, has two outputs ({len(inputs)} in, fee {fee})")
    opened = a.eval(f"""(async (outs) => {{ const o = await import('/app/lib/ootle.js'); const b = await import('/app/lib/b64.js');
      const dest = b.unhex({json.dumps(keys['viewSk'])}), sales = b.unhex({json.dumps(keys['salesViewSk'])});
      const res = [];
      for (const x of outs) {{ const id = 'utxo_' + '01'.repeat(32) + '_' + x[0];
        const to = await o.tryDecryptUtxo(dest, {{ id, nonce: x[1], enc: x[2] }}); const back = await o.tryDecryptUtxo(sales, {{ id, nonce: x[1], enc: x[2] }});
        res.push([id, to ? String(to.value) : null, back ? String(back.value) : null]); }}
      return res; }})""" + f"({json.dumps([[bytes(o[0][0]).hex(), bytes(o[0][1]).hex(), bytes(o[0][2]).hex()] for o in outputs])})")
    to_them = [x for x in opened if x[1]]
    back = [x for x in opened if x[2]]
    t.check(len(to_them) == 1 and to_them[0][1] == "270000" and not to_them[0][2], f"0.27 goes to the address: only its view key opens it ({opened})")
    t.check(len(back) == 1 and back[0][2] == "50000" and sent.get("change") == {"utxo_id": back[0][0], "value_ut": "50000"},
            "the change, 0.05, comes back to the sales address, and the page told our server which output it is")
    rows = read(t, "SELECT utxo_id, withdraw_tx, withdrawn FROM sale_payments ORDER BY value_ut")
    t.check(sorted((r[1], r[2]) for r in rows if r[0] in ids[:2]) == [(tx, 1), (tx, 1)] and [r for r in rows if r[0] == ids[2]][0][1:] == (None, 0),
            f"on our server: both payments spent by this withdrawal, the one being checked untouched ({rows})")
    change = read(t, "SELECT utxo_id, value_ut, from_tx, committed FROM sales_change")
    t.check(change == [(back[0][0], 50000, tx, 1)], f"the change is kept, committed, withdrawable later ({change})")

    a.click("withdraw-close")
    a.wait("document.getElementById('withdraw-dialog')?.hidden !== false", 20)
    a.wait("document.querySelector('[data-testid=\"withdraw-ready\"]')?.dataset.ut === '50000'", 30)
    t.check(ready_ut(a) == "50000" and "less than the minimum of 0.06 tTARI" in a.text("withdraw-too-little")
            and a.attr("withdraw-go", "disabled") is not None,
            "back in Earnings: the change is ready, too little for a withdrawal of its own, said so, and Withdraw is off")
    receipts = a.eval("[...document.querySelectorAll('[data-testid=\"withdraw-receipt\"]')].map((r) => [r.dataset.state, r.textContent])")
    t.check(len(receipts) == 1 and receipts[0][0] == "done" and "0.27 tTARI" in receipts[0][1],
            f"this browser lists the withdrawal, its address kept here only ({receipts})")
    t.check(not any(keys["to"] in (r.get("url") or "") for r in a.requests), "the address never went to our server in an address bar")
    t.check(keys["to"] not in json.dumps(fake.withdrawals), "nor in the withdrawal posted")
    t.shot(a, "withdraw-after-1440")
    set_device(a, "iphone")
    t.check(no_hscroll(a), "Earnings with its withdrawal on a phone: no sideways scroll")
    t.shot(a, "withdraw-after-390", full_page=True)
    set_device(a, "desktop")
