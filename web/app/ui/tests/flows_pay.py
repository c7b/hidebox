# SPDX-License-Identifier: MIT
"""Pay to open, the client (lane app2; 16-drive-design §4, §12, §15 steps 15 and 16), in headless Chromium.

The server lane's pay routes (§15 step 14) aren't merged yet, so PayFake answers them in the annex's shapes
(16-drive-architecture §1.5, §5.1) from CDP Fetch, in front of the real dev server: PUT /me/sales, POST
/items/{id}/shares with mode "pay" (forwarded to the dev server as a plain link, so the open that follows is
the real one), the `paid` summary on /me/items, PATCH /s/{id} {paused}, GET /p/{id}, claims, demo-pay, the
claim's progress, the open gate (X-Mutis-Claim), POST /me/sales/claims/{cid}/confirm. Every key, teaser and
payment the page builds is the product code's; ootle-wasm builds the chain outputs the fake mirror carries
(a funded drive, a genuine sales output, one whose payer kept control), so the owner check runs the real
one-time-key comparison.

share-pay (the seller), pay-page-states (the buyer page, every state), owner-check (R1 and the release gate)."""
import base64
import glob
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from flows import Intercept, scenario
from flows_drive import row_menu, upload_files

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "server"))
from mutis import ootle_addr  # noqa: E402

FEATURES = ("folders", "pay_to_open")
PAY_LINK = r"/p/([A-Za-z0-9_-]{22})#5([A-Za-z0-9_-]{43})"
B32 = "abcdefghijklmnopqrstuvwxyz234567"
UTXO_PREFIX = "utxo_" + "01" * 32 + "_"
MIRROR_SEQ = 900000


def b64u_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def body_of(params):
    raw = params["request"].get("postData")
    return json.loads(raw) if raw else {}


def header(params, name):
    return next((v for k, v in params["request"]["headers"].items() if k.lower() == name.lower()), None)


def err(code, http, **details):
    return http, {"error": {"code": code, "message": code, "details": details}}


# In the page: ootle-wasm builds stealth outputs (what a payer's transaction puts on chain), each as a mirror
# row with the one-time key the indexer would show. spec: {to: 'wallet'|'sales'|'sales-other', amount, memo}.
OUTPUTS_JS = """(async (specs) => {
  const ootle = await import('/app/lib/ootle.js');
  const { hex } = await import('/app/lib/b64.js');
  const { loadIdentity, withOotle } = await import('/app/lib/identity.js');
  const pay = await import('/app/lib/pay.js');
  await ootle.ready();
  const w = ootle.bindings();
  const id = await withOotle(await loadIdentity({ lazy: true }));
  const sales = await pay.salesKeys(id);
  const other = await ootle.newRandomKeys();
  const out = [];
  for (const s of specs) {
    const owner = s.to === 'wallet' ? id.wallet.ownerPk : s.to === 'sales' ? sales.ownerPk : other.ownerPk;
    const view = s.to === 'wallet' ? id.wallet.viewPk : sales.viewPk;
    const wit = w.createStealthOutputWitness(ootle.NETWORK_BYTE, owner, view, BigInt(s.amount), ootle.TARI_RESOURCE, null, s.memo ? JSON.stringify(s.memo) : null, null, 0n);
    const st = w.generateStealthOutputsStatement('[' + wit + ']', 0n, new Uint8Array(32));
    const [o] = JSON.parse(st.statement_json).outputs;
    st.free();
    out.push({ commitment: o.output.commitment, nonce: o.output.sender_public_nonce, enc: o.output.encrypted_data, key: o.auth.Key });
  }
  return out;
})"""


# The seller's drive has stored both checked claims as confirmed (lib/pay.js salesState).
CONFIRMED_JS = """(async () => { const p = await import('/app/lib/pay.js'); const { loadIdentity } = await import('/app/lib/identity.js');
  const s = await p.salesState(await loadIdentity({ lazy: true })); return s.outputs.filter((o) => o.confirmed === 'sent').length === 2; })()"""


class PayFake:
    """The pay routes of 16-drive-architecture §1.5, in memory, for the pages it is attached to."""

    def __init__(self, t):
        self.t = t
        self.links = {}        # share id -> {price_ut, paused, seller_state, kind, size, teaser_ct, server_half, item_id, gone}
        self.claims = {}       # claim id -> {share, verifier, address, status, demo, owner_check, received, queue, views_left, ...}
        self.sales = None      # {address, view_sealed} from PUT /me/sales
        self.sales_puts = 0
        self.watch = None      # a real Ootle address for /config's watch_address
        self.confirms = []     # (claim id, body)
        self.share_bodies = []
        self.pows = []
        self.mirror = []       # fake chain rows ({seq, id, nonce, enc, tag, epoch})
        self.substates = {}    # utxo id -> one-time key
        self.substate_reads = []
        self.txs = []
        self.on_tx = None
        self.direct = False    # /config says direct mode (a funded drive pays from this browser)

    # ---- wiring ----

    def attach(self, page):
        ic = Intercept(page)
        api = "*/api/v1"
        ic.add(f"{api}/config", "Response", self.config)
        ic.add(f"{api}/me/items*", "Response", self.items)
        ic.add(f"{api}/me/sales/claims/*/confirm", "Request", self.confirm, "POST")
        ic.add(f"{api}/me/sales", "Request", self.put_sales, "PUT")
        ic.add(f"{api}/items/*/shares", "Request", self.create_share, "POST")
        ic.add(f"{api}/s/*/open", "Request", self.open_gate, "POST")
        ic.add(f"{api}/s/*", "Request", self.patch_share, "PATCH")
        ic.add(f"{api}/p/*", "Request", self.p_route)
        ic.add(f"{api}/pow", "Request", self.pow, "POST")
        ic.add(f"{api}/chain/ix/substates/utxo_*", "Request", self.substate, "GET")
        ic.add(f"{api}/chain/ix/epoch-manager/stats", "Request", lambda _p: (200, {"current_epoch": 100}), "GET")
        ic.add(f"{api}/chain/ix/transactions", "Request", self.submit, "POST")
        ic.add(f"{api}/chain/ix/transactions/*/result", "Request", lambda _p: (200, {"result": {"Finalized": {"final_decision": "Commit"}}}), "GET")
        return ic

    def forward(self, params, method, path, body):
        hdrs = {k: v for k, v in params["request"]["headers"].items() if k.lower() in ("authorization", "x-mutis-judge")}
        hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self.t.origin + "/api/v1" + path, data=json.dumps(body).encode(), headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    # ---- the seller ----

    def config(self, cfg):
        cfg.setdefault("features", {}).update({"pay_to_open": True, "demo_pay": True})
        if self.direct:
            cfg["send_mode"] = "direct"
            cfg["features"]["direct_send"] = True
        cfg.setdefault("pay_to_open", {})["watch_address"] = self.watch
        return cfg

    def put_sales(self, params):
        body = body_of(params)
        if not ootle_addr.classify(body.get("address", "")) == "ootle_testnet" or len(b64u_decode(body.get("view_sealed", ""))) != 125:
            return err("invalid", 422)
        self.sales = body
        self.sales_puts += 1
        return 200, {}

    def create_share(self, params):
        body = body_of(params)
        if body.get("mode") != "pay":
            return None
        if not self.sales:
            return err("seller_not_registered", 409)
        self.share_bodies.append(body)
        plain = {k: body[k] for k in ("wrapped_key", "access_verifier", "kdf", "link_verifier", "max_views", "expires_at")}
        plain["mode"] = "link"
        item_id = params["request"]["url"].split("/items/")[1].split("/")[0]
        status, res = self.forward(params, "POST", f"/items/{item_id}/shares", plain)
        if status != 201:
            return status, res
        self.links[res["share_id"]] = {"price_ut": body["price_ut"], "paused": False, "seller_state": "pending", "teaser_ct": body.get("teaser_ct"),
                                       "server_half": body["server_half"], "item_id": item_id, "gone": False}
        return 201, {**res, "path": f"/p/{res['share_id']}"}

    def items(self, res):
        for row in res.get("items", []):
            for s in row.get("shares") or []:
                link = self.links.get(s.get("id") or s.get("share_id"))
                if link:
                    count = sum(1 for c in self.claims.values() if c["share"] == (s.get("id") or s.get("share_id")) and c["status"] in ("paid", "released"))
                    s["paid"] = {"price_ut": link["price_ut"], "paused": link["paused"], "seller_state": link["seller_state"], "count": count}
        return res

    def patch_share(self, params):
        sid = params["request"]["url"].split("/s/")[1].split("/")[0].split("?")[0]
        body = body_of(params)
        if sid not in self.links or "paused" not in body:
            return None
        self.links[sid]["paused"] = bool(body["paused"])
        return 200, {"share_id": sid, "paused": self.links[sid]["paused"]}

    def confirm(self, params):
        cid = params["request"]["url"].split("/claims/")[1].split("/")[0]
        body = body_of(params)
        self.confirms.append((cid, body))
        c = self.claims.get(cid)
        if not c:
            return err("not_found", 404)
        if c["status"] != "paid" or c["owner_check"] != "pending":
            return err("conflict", 409, status=c["status"])
        c["owner_check"] = "ok" if body.get("spendable") else "bad"
        if c["owner_check"] == "bad":
            c["status"] = "void"
        return 200, {"status": c["status"], "owner_check": c["owner_check"]}

    # ---- the buyer ----

    def pow(self, params):
        purpose = body_of(params).get("purpose")
        self.pows.append(purpose)
        if purpose in ("claim", "demo_pay"):  # the fake checks no PoW; the dev server's cheapest challenge stands in
            return self.forward(params, "POST", "/pow", {"purpose": "upload"})
        return None

    def new_claim(self, sid, verifier):
        cid = "clm_" + "".join(secrets.choice(B32) for _ in range(20))
        c = {"share": sid, "verifier": verifier, "address": ootle_addr.with_pay_ref(self.sales["address"], cid.encode()),
             "status": "pending", "demo": False, "owner_check": "none", "received": 0, "queue": [], "views_left": 3,
             "expires_at": int(time.time()) + 3600, "open_until": None, "opened": 0}
        self.claims[cid] = c
        return cid, c

    def claim_json(self, cid, c):
        price = int(self.links[c["share"]]["price_ut"])
        out = {"status": c["status"], "amount_ut": str(price), "received_ut": str(c["received"]), "expires_at": c["expires_at"],
               "payments": [{"value_ut": str(c["received"]), "seen_at": int(time.time()), "checks": {"amount_proven": True, "committed_on_chain": c["status"] != "seen"}}] if c["received"] else [],
               "demo": c["demo"], "owner_check": c["owner_check"]}
        if c["status"] == "released":
            out.update(server_half=self.links[c["share"]]["server_half"], views_left=c["views_left"], open_until=c["open_until"])
        return out

    def advance(self, c):
        price = int(self.links[c["share"]]["price_ut"])
        if c["queue"]:
            c["status"] = c["queue"].pop(0)
            if c["status"] in ("seen", "paid"):
                c["received"] = price if c["status"] == "paid" or not c.get("partial") else price // 2
            if c["status"] == "paid" and not c["demo"]:
                c["owner_check"] = "pending"
        elif c["status"] == "paid" and (c["demo"] or c["owner_check"] == "ok"):
            c["status"] = "released"
            c["open_until"] = int(time.time()) + 7 * 86400

    def p_route(self, params):
        url = params["request"]["url"].split("?")[0]
        method = params["request"]["method"]
        parts = url.split("/api/v1/p/")[1].split("/")
        sid = parts[0]
        link = self.links.get(sid)
        if not link:
            return err("not_found", 404)
        if link["gone"]:
            return err("gone", 410, reason="revoked")
        if len(parts) == 1 and method == "GET":
            return 200, {"state": "paused" if link["paused"] else "selling", "price_ut": link["price_ut"], "fee_ut": "30000", "buyer_views": 3,
                         "buyer_window_s": 604800, "kind": "file", "size_stored": 4096, "child_count": None, "teaser_ct": link["teaser_ct"],
                         "seller": {"address": self.sales["address"], "ready": link["seller_state"] == "ok"}, "testnet": True}
        if len(parts) == 2 and method == "POST":
            if header(params, "Authorization"):
                return err("bad_request", 400)  # the page must never send its drive's session here
            if link["paused"]:
                return err("not_for_sale", 409)
            cid, c = self.new_claim(sid, body_of(params).get("claim_verifier"))
            return 201, {"claim_id": cid, "address": c["address"], "amount_ut": link["price_ut"], "expires_at": c["expires_at"], "status": "pending"}
        cid = parts[2] if len(parts) > 2 else None
        c = self.claims.get(cid)
        token = header(params, "X-Mutis-Claim")
        if not c or c["share"] != sid:
            return err("not_found", 404)
        if not token or base64.urlsafe_b64encode(hashlib.sha256(b64u_decode(token)).digest()).decode().rstrip("=") != c["verifier"]:
            return err("bad_claim", 403)
        if len(parts) == 3 and method == "GET":
            self.advance(c)
            return 200, self.claim_json(cid, c)
        if len(parts) == 4 and parts[3] == "demo-pay" and method == "POST":
            if c["status"] not in ("pending", "seen", "underpaid") or c["demo"]:
                return err("conflict", 409)
            c["demo"] = True
            c["queue"] = ["seen", "paid"]
            return 202, {"job_id": "job_" + secrets.token_hex(8)}
        return err("bad_request", 400)

    def open_gate(self, params):
        sid = params["request"]["url"].split("/s/")[1].split("/")[0]
        if sid not in self.links:
            return None
        token = header(params, "X-Mutis-Claim")
        verifier = base64.urlsafe_b64encode(hashlib.sha256(b64u_decode(token)).digest()).decode().rstrip("=") if token else None
        c = next((c for c in self.claims.values() if c["share"] == sid and c["verifier"] == verifier), None)
        if not c or c["status"] != "released":
            return err("payment_required", 402)
        if c["views_left"] <= 0:
            return err("claim_used", 410, reason="no_opens_left")
        c["views_left"] -= 1
        c["opened"] += 1
        return None  # the real open, on the dev server

    # ---- the chain ----

    def add_outputs(self, outputs):
        for o in outputs:
            uid = UTXO_PREFIX + o["commitment"]
            self.mirror.append({"seq": MIRROR_SEQ + len(self.mirror) + 1, "id": uid, "nonce": o["nonce"], "enc": o["enc"], "tag": None, "epoch": 100})
            self.substates[uid] = o
        return [UTXO_PREFIX + o["commitment"] for o in outputs]

    def substate(self, params):
        uid = params["request"]["url"].rsplit("/", 1)[1].split("?")[0]
        self.substate_reads.append(uid)
        o = self.substates.get(uid)
        if not o:
            return err("not_found", 404)
        return 200, {"substate": {"Utxo": {"output": {"auth": {"Key": o["key"]}, "output": {"public_nonce": o["nonce"], "encrypted_data": o["enc"]}}, "is_frozen": False}}}

    def submit(self, params):
        self.txs.append(body_of(params))
        if self.on_tx:
            self.on_tx()
        return 200, {"transaction_id": secrets.token_hex(32)}


def mirror_patch(fake):
    """GET /chain/utxos?after=N: the dev server's page plus the fake chain's rows after N."""
    def patch(params):
        m = re.search(r"after=(\d+)", params["request"]["url"])
        after = int(m[1]) if m else 0
        rows = [r for r in fake.mirror if r["seq"] > after]
        head = max([r["seq"] for r in fake.mirror] or [0])
        return 200, {"items": rows[:1000], "next": rows[-1]["seq"] if rows else after, "head": head}
    return patch


def attach(t, fake, page):
    ic = fake.attach(page)
    # The fake chain replaces the dev server's (empty) mirror for these pages: Request stage, so it's
    # answered before the dev server is asked (its rule is checked first).
    ic.rules.insert(0, ("*/api/v1/chain/utxos*", "GET", "Request", mirror_patch(fake)))
    page.cmd("Fetch.enable", {"patterns": [{"urlPattern": p, "requestStage": st} for p, _, st, _ in ic.rules]})
    return ic


def db(t):
    found = glob.glob(os.path.join(t.work, "data-sidecar-" + "-".join(FEATURES), "**", "mutis.sqlite3"), recursive=True)
    return sqlite3.connect(found[0], timeout=30)


def seller(t, fake, device="desktop"):
    """A drive past its first day with notes.txt, the fake attached, and a watch address made by ootle-wasm."""
    page = t.actor(device)
    page.goto(t.origin + "/drive")
    if not fake.watch:
        page.wait("!!document.querySelector('script')", 30)
        fake.watch = page.eval("import('/app/lib/ootle.js').then((m) => m.newRandomKeys()).then((k) => k.address)")
    attach(t, fake, page)
    page.goto(t.origin + "/drive?make")
    page.wait_for("drive-root", 90)
    page.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
    con = db(t)
    con.execute("UPDATE identities SET distinct_days = 2")
    con.commit()
    con.close()
    page.reload()
    page.wait_for("drive-root", 90)
    upload_files(t, page, ["notes.txt", "song.txt"])
    return page


def dialog_step(page):
    return page.eval("document.getElementById('share-dialog')?.dataset.step || ''")


def choices(page):
    return page.eval("[...document.querySelectorAll('#share-dialog [data-testid=\"share-choice\"]')].map((e) => e.dataset.value)")


def pick(page, value):
    page.eval(f"document.querySelector('#share-dialog [data-testid=\"share-choice\"][data-value={json.dumps(value)}]').click()")
    page.wait(f"document.querySelector('#share-dialog [data-testid=\"share-choice\"][data-value={json.dumps(value)}]')?.dataset.state === 'checked'", 5)


def sell(page, name, price=None, names=True):
    row_menu(page, name, "share")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    pick(page, "pay")
    page.click("share-next")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'pay'", 10)
    if price:
        pick(page, price)
    if not names:
        page.click("pay-names")
    page.click("pay-make")
    page.wait("document.getElementById('share-dialog')?.dataset.step === 'result' || !!document.querySelector('#share-dialog [data-testid=\"error-banner\"]')", 120)
    return page.value("share-link") if dialog_step(page) == "result" else None


def close_dialog(page):
    page.key("Escape")
    page.wait("!document.getElementById('share-dialog') || document.getElementById('share-dialog').hidden", 10)


def row_rule(page, name):
    return page.eval(f"""(() => {{ const r = [...document.querySelectorAll('[data-testid="file-row"]')].find((e) => e.dataset.name === {json.dumps(name)});
      const b = r?.querySelector('[data-rule]'); return b ? [b.dataset.rule, b.textContent.trim(), r.textContent] : null; }})()""")


def wait_badge(page, name, text, timeout=30):
    page.wait(f"""[...document.querySelectorAll('[data-testid="file-row"]')].find((e) => e.dataset.name === {json.dumps(name)})
      ?.querySelector('[data-rule]')?.textContent.trim() === {json.dumps(text)}""", timeout)
    return True


def buyer(t, fake, url, device="desktop"):
    page = t.actor(device)
    attach(t, fake, page)
    page.goto(url)
    page.wait("['wait','paying','seen','check','unlocking','open','opened','expired','void','used','gone','incomplete','not-found','integrity-error','error']"
              ".includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)", 60)
    return page


def pay_state(page):
    return page.eval("document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state ?? ''")


def wait_pay(page, states, timeout=60):
    page.wait(f"{json.dumps(list(states))}.includes(document.querySelector('[data-testid=\"pay-page\"]')?.dataset.state)", timeout)
    return pay_state(page)


def steps(page):
    return page.eval("[...document.querySelectorAll('[data-testid=\"pay-claim-step\"] li')].map((l) => l.dataset.step + ':' + l.dataset.state)")


# --- §15 step 15: the seller ----------------------------------------------------------------------------

@scenario("share-pay", "Sell a file (step 15): Someone who pays you, the price chips, the name switch, C35 the first time; the pay link with C34; Getting ready, then Pay with its count; Stop selling and Sell again", features=FEATURES)
def share_pay(t):
    fake = PayFake(t)
    a = seller(t, fake)
    row_menu(a, "notes.txt", "share")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    t.check(choices(a) == ["link", "tari", "pay"], f"Who can open it? adds Someone who pays you when pay to open is on ({choices(a)})")
    pick(a, "pay")
    a.click("share-next")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'pay'", 10)
    step = a.text("share-step-pay")
    t.check(choices(a) == ["100000", "250000", "500000"] and "0.1 tTARI" in step and "0.25 tTARI" in step and "0.5 tTARI" in step,
            f"three price chips from /config, with the number ({choices(a)})")
    t.check("The money goes straight to your Tari address. We never hold it." in step, "the seller's C33 line")
    t.check(a.attr("pay-names", "aria-checked") == "true", "Show the name before they pay: on by default")
    t.check(a.exists("pay-key-note") and "we keep your sales view key" in a.text("pay-key-note"), "C35, the first time this drive sells")
    t.check(a.ax_unnamed() == [], f"every control has a name ({a.ax_unnamed()[:4]})")
    t.shot(a, "pay-share-1440")
    pick(a, "250000")
    a.click("pay-make")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'result' || !!document.querySelector('#share-dialog [data-testid=\"error-banner\"]')", 120)
    t.check(dialog_step(a) == "result", f"Make pay link makes it ({a.eval('document.querySelector(\"#share-dialog [data-testid=error-banner]\")?.textContent ?? \"\"')})")
    url = a.value("share-link")
    m = re.fullmatch(re.escape(t.origin) + PAY_LINK, url or "")
    t.check(m is not None, f"a /p/ link with half of the key after the # (kind 5: {url[-60:] if url else url})")
    t.check(fake.sales_puts == 1 and ootle_addr.classify(fake.sales["address"]) == "ootle_testnet" and len(b64u_decode(fake.sales["view_sealed"])) == 125,
            "the sales address and its sealed view key went to our server once (PUT /me/sales, 125 bytes)")
    body = fake.share_bodies[-1]
    half = b64u_decode(body["server_half"])
    t.check(body["price_ut"] == "250000" and len(half) == 32 and m and b64u_decode(m[2]) != half and body["server_half"] not in url,
            "the server half (32 bytes) is not the link's half, and the link doesn't carry it")
    t.check(len(b64u_decode(body["teaser_ct"])) == 12 + 256 + 16, "the teaser is sealed and padded to 256 bytes")
    t.check(a.text("share-say") == "It opens after they pay you 0.25 tTARI.", f"the rule in one sentence ({a.text('share-say')})")
    t.check(a.text("pay-split") == "We keep half of the key and give it to each buyer once the chain shows their payment. The other half is in the link. "
            "Neither half opens it alone. If the link leaks, our server could open it too.", "C34, the seller's form, with its boundary")
    t.shot(a, "pay-share-1440-result")
    close_dialog(a)
    t.check(wait_badge(a, "notes.txt", "Getting ready"), "the row says Getting ready until our payment checker has the sales key")
    fake.links[m[1]]["seller_state"] = "ok"
    a.reload()
    a.wait_for("drive-root", 90)
    t.check(wait_badge(a, "notes.txt", "Pay 0.25 tTARI") and "0 paid" in row_rule(a, "notes.txt")[2], f"then Pay 0.25 tTARI, 0 paid ({row_rule(a, 'notes.txt')})")
    # A second sale from the same drive: no C35, and the item that sells already offers no second paid link.
    url2 = sell(a, "song.txt", names=False)
    t.check(url2 is not None and fake.sales_puts == 1, "a second pay link: the sales address isn't sent again")
    close_dialog(a)
    row_menu(a, "song.txt", "share")
    a.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
    a.click("share-tab-new")
    t.check("pay" not in choices(a), "one paid link per item: Someone who pays you is gone from its dialog")
    close_dialog(a)
    # Stop selling, then Sell again, from the Links tab.
    fake.links[m[1]]["seller_state"] = "ok"
    row_menu(a, "notes.txt", "share")
    a.wait("!document.getElementById('share-dialog').hidden", 20)
    a.click("share-tab-links")
    a.click("link-pause")
    a.wait("!!document.querySelector('[data-testid=\"link-resume\"]')", 30)
    t.check(fake.links[m[1]]["paused"] is True, "Stop selling: PATCH /s/{id} {paused: true}")
    close_dialog(a)
    t.check(wait_badge(a, "notes.txt", "Not selling"), "the row says Not selling")
    row_menu(a, "notes.txt", "share")
    a.wait("!document.getElementById('share-dialog').hidden", 20)
    a.click("share-tab-links")
    a.click("link-resume")
    a.wait("!!document.querySelector('[data-testid=\"link-pause\"]')", 30)
    t.check(fake.links[m[1]]["paused"] is False, "Sell again")
    close_dialog(a)
    t.shared["pay"] = {"url": url, "url2": url2}


# --- §15 steps 15 and 16: the buyer page -----------------------------------------------------------------

@scenario("pay-page-states", "The buyer page (steps 15 and 16): teaser, price and fee, C39, C37, one primary; the address only after a claim; test money to Unlocked and the open; resume; the owner's check; Pay from my drive; paused, gone, no key", features=FEATURES)
def pay_page_states(t):
    fake = PayFake(t)
    a = seller(t, fake)
    url = sell(a, "notes.txt", price="100000")
    sid = re.search(PAY_LINK, url)[1]
    fake.links[sid]["seller_state"] = "ok"
    close_dialog(a)

    b = buyer(t, fake, url)
    t.check(pay_state(b) == "wait", f"a stranger's first screen: waiting, nothing claimed ({pay_state(b)})")
    t.check(b.eval("document.querySelector('#buy-h').textContent") == "Pay to open this file." and b.text("pay-name") == "notes.txt",
            "the title, and the name the owner allowed (read from the teaser with the link's half)")
    t.check(b.text("pay-price").replace("\n", " ").startswith("0.1") and b.text("pay-fee") == "Plus a network fee of 0.03 tTARI. The fee is public.",
            f"the price and the public fee ({b.text('pay-price')!r}, {b.text('pay-fee')!r})")
    t.check(re.fullmatch(r"Paying lets you open it 3 times until \w+ \d+\. Anyone who opens a file can pass it on\. The owner can still delete it\.", b.text("pay-get")) is not None,
            f"what you get (C39: {b.text('pay-get')})")
    t.check(b.text("pay-final") == "Payments can't be taken back, by us or by Tari. Pay only if what you see here is enough.", "no take-backs, before Pay (C37)")
    t.check(b.eval("document.querySelectorAll('[data-testid=\"pay-page\"] .btn[data-size=\"lg\"]:not([data-variant])').length") == 1 and b.exists("pay-test"),
            "one primary: Pay with test money")
    t.check(not b.exists("pay-browser"), "no Pay from my drive without a drive here")
    t.check(not b.exists("pay-address") and not fake.claims, "Another Ootle wallet shows no address before a claim exists")
    t.check("What's inside stays locked until you pay." in b.text("pay-locked"), "the content stays locked")
    t.check(b.ax_unnamed() == [] and b.csp_violations() == [], "names on every control; no CSP violation")
    t.shot(b, "pay-wait-1440")
    b.eval("document.querySelector('[data-testid=\"pay-other\"] summary').click()")
    b.wait_for("pay-address", 60)
    cid = next(iter(fake.claims))
    c = fake.claims[cid]
    t.check(b.value("pay-address") == c["address"] and c["address"] != fake.sales["address"]
            and ootle_addr.base_address(c["address"]) == ootle_addr.base_address(fake.sales["address"]),
            "Another Ootle wallet: the address just for this claim (the owner's sales address with the claim's reference), after the claim")
    t.check("claim" in fake.pows, "the claim asked for its proof of work (claim)")
    t.check("Paid from your own wallet? It opens after the owner's drive checks it." in b.text("pay-other"), "C38 under the other wallet")
    t.shot(b, "pay-other-1440")
    # Test money: the same claim, our demo wallet pays it; the steps run to Unlocked, no owner step.
    b.click("pay-test")
    t.check(wait_pay(b, ("paying", "seen", "unlocking", "open"), 30) in ("paying", "seen", "unlocking", "open"), "Pay with test money starts the steps")
    t.check(len(fake.claims) == 1 and fake.claims[cid]["demo"], "test money pays the claim that exists")
    t.check(wait_pay(b, ("open",), 60) == "open", "released: the page has both halves")
    t.check(not any("owner" in s for s in steps(b)) and all(s.endswith(":done") for s in steps(b)), f"test money skips the owner's check ({steps(b)})")
    t.check(re.fullmatch(r"3 opens left until \w+ \d+\.", b.text("pay-left")) is not None, f"{b.text('pay-left')}")
    t.check("grouped with our other payments" in b.text("pay-chain"), "what the chain shows, with test money's grouping (C36)")
    t.shot(b, "pay-open-1440")
    b.click("pay-open")
    b.wait_for("pay-file", 60)
    t.check(b.text("pay-file").startswith("notes.txt") and fake.claims[cid]["opened"] == 1, "Open it: the real open, with the claim's token, decrypts here")
    t.check(b.text("pay-left").startswith("2 opens left"), f"one open used ({b.text('pay-left')})")
    b.reload()
    t.check(wait_pay(b, ("open",), 60) == "open", "a reload resumes the claim kept in this browser")
    t.check(b.csp_violations() == [], "no CSP violation")

    # Another wallet, a payment our demo wallet didn't build: it waits for the owner's drive (C38).
    p = buyer(t, fake, url, device="iphone")
    p.eval("document.querySelector('[data-testid=\"pay-other\"] summary').click()")
    p.wait_for("pay-address", 60)
    cid2 = [k for k in fake.claims if k != cid][0]
    fake.claims[cid2]["queue"] = ["seen", "paid"]
    t.check(wait_pay(p, ("seen",), 30) == "seen", "Payment seen: the steps take over")
    t.check(wait_pay(p, ("check",), 30) == "check", "paid from another wallet: the owner's drive checks it")
    t.check("owner:now" in steps(p) and "The owner's drive checks it next time it opens." in p.text("pay-status"), f"the owner step, and C38 ({steps(p)})")
    t.check(p.eval("document.scrollingElement.scrollWidth <= window.innerWidth"), "no sideways scroll at 390")
    t.shot(p, "pay-check-390")
    fake.claims[cid2]["owner_check"] = "ok"
    t.check(wait_pay(p, ("open",), 30) == "open", "after the owner's drive confirms, it opens")

    # Expired, paused, gone, no key.
    e = buyer(t, fake, url)
    e.eval("document.querySelector('[data-testid=\"pay-other\"] summary').click()")
    e.wait_for("pay-address", 60)
    cid3 = [k for k in fake.claims if k not in (cid, cid2)][0]
    fake.claims[cid3]["queue"] = ["expired"]
    t.check(wait_pay(e, ("expired",), 30) == "expired" and e.exists("pay-again"), "a closed payment window: Start again")
    e.click("pay-again")
    t.check(wait_pay(e, ("wait",), 10) == "wait" and not e.exists("pay-address"), "Start again: a fresh page, no old address")
    fake.links[sid]["paused"] = True
    q = buyer(t, fake, url)
    t.check(q.exists("pay-closed") and not q.exists("pay-test"), "Not selling: no Pay, and why")
    fake.links[sid]["paused"] = False
    g = buyer(t, fake, url.split("#")[0])
    t.check(pay_state(g) == "incomplete", "a link without its half of the key says so")
    fake.links[sid]["gone"] = True
    g2 = buyer(t, fake, url)
    t.check(pay_state(g2) == "gone", "an ended paid link says it ended")
    fake.links[sid]["gone"] = False

    # Pay from my drive: a drive in this browser with test money of its own.
    fake.direct = True
    d = t.actor()
    attach(t, fake, d)
    d.goto(t.origin + "/drive?make")
    d.wait_for("drive-root", 90)
    rows = d.eval(OUTPUTS_JS + "([{ to: 'wallet', amount: '1000000' }])", timeout=120)
    fake.add_outputs(rows)

    def paid_from_drive():
        mine = [k for k, v in fake.claims.items() if k not in (cid, cid2, cid3) and v["status"] == "pending"]
        if mine:
            fake.claims[mine[-1]]["queue"] = ["seen", "paid"]
    fake.on_tx = paid_from_drive
    d.goto(url)
    d.wait_for("pay-browser", 120)
    t.check(d.exists("pay-test") and "Paid from your own wallet?" in d.text("pay-page"), "a funded drive here: Pay from my drive, with C38 under it")
    t.shot(d, "pay-drive-1440")
    d.click("pay-browser")
    t.check(wait_pay(d, ("check",), 120) == "check" and len(fake.txs) == 1, "Pay from my drive: this browser built and sent the payment; it waits for the owner's check")
    t.check(d.csp_violations() == [], "no CSP violation")
    fake.direct = False


# --- §15 step 16: the owner check -----------------------------------------------------------------------

@scenario("owner-check", "The owner check (step 16, R1): the seller's drive finds its sales outputs, compares each one-time key with its own, confirms the genuine one and voids the one the payer kept; Received lists both", features=FEATURES)
def owner_check(t):
    fake = PayFake(t)
    a = seller(t, fake)
    url = sell(a, "notes.txt")
    sid = re.search(PAY_LINK, url)[1]
    fake.links[sid]["seller_state"] = "ok"
    close_dialog(a)
    good, _ = fake.new_claim(sid, "x")
    bad, _ = fake.new_claim(sid, "y")
    early, _ = fake.new_claim(sid, "z")
    for cid in (good, bad):
        fake.claims[cid].update(status="paid", owner_check="pending", received=100000)
    rows = a.eval(OUTPUTS_JS + f"""([{{ to: 'sales', amount: '100000', memo: {{ Message: '{good}' }} }},
      {{ to: 'sales-other', amount: '100000', memo: {{ Message: '{bad}' }} }}, {{ to: 'sales', amount: '100000', memo: {{ Message: '{early}' }} }}])""", timeout=120)
    ids = fake.add_outputs(rows)
    a.reload()
    a.wait_for("drive-root", 90)
    deadline = time.time() + 120
    while time.time() < deadline and len(fake.confirms) < 3:
        a.eval("new Promise((r) => setTimeout(r, 500))")
    t.check(a.wait(CONFIRMED_JS, 60), "the drive kept what it confirmed")
    got = {cid: body for cid, body in fake.confirms}
    t.check(got.get(good) == {"utxo_id": ids[0], "spendable": True}, f"the genuine payment: its one-time key is ours, confirmed ({got.get(good)})")
    t.check(got.get(bad) == {"utxo_id": ids[1], "spendable": False}, f"the payer kept control: the claim is voided ({got.get(bad)})")
    t.check(fake.claims[good]["owner_check"] == "ok" and fake.claims[bad]["status"] == "void", "the release gate moved: one to release, one void")
    t.check(set(ids) <= set(fake.substate_reads), "each output's one-time key was read from the indexer")
    t.check(early in got and fake.claims[early]["status"] == "pending", "a claim not paid yet stays as it is (409), and is asked again next time")
    a.goto(t.origin + "/drive/received")
    a.wait("document.querySelectorAll('[data-testid=\"sales-row\"]').length === 3", 60)
    checks = a.eval("[...document.querySelectorAll('[data-testid=\"sales-row\"]')].map((r) => r.dataset.check).sort()")
    t.check(checks == ["bad", "ok", "ok"], f"Received lists the payments with their check ({checks})")
    t.check("The payer kept control of this payment" in a.text("sales-root") and "Yours to spend" in a.text("sales-root"), "in words")
    t.shot(a, "pay-received-1440")
    a.wait(CONFIRMED_JS, 60)
    before = len(fake.confirms)
    a.reload()
    a.wait_for("drive-root", 90)
    a.eval("new Promise((r) => setTimeout(r, 4000))")
    t.check([c for c, _ in fake.confirms[before:]] == [early], "the next opening asks again only about the claim that wasn't paid yet")
