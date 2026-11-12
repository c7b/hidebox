# SPDX-License-Identifier: MIT
"""A drive's shop (docs/shop.md), in headless Chromium, with features.shop on: the owner turns on My shop, lists a file
that sells and prices one from its row menu (never its name: the title starts empty), copies the shop's link; a
visitor on a phone and on a computer sees the shop (names never shown), opens Buy and open, which is the pay link
itself, pays with test money and opens the file; the owner takes one off, a paused link hides its listing, and
turning the shop off leaves a closed page.

The shop's routes are the dev server's own. The pay routes are PayFake's (flows_pay.py), as in every pay flow: it
forwards a pay link to the dev server as a plain link, so ShopPayFake also writes the paid_shares row the real create
would (the shop lists only the drive's own pay links), the pause the real PATCH would, and, when PayFake releases a
claim, the claim row the real open checks. Everything the pages do is the product code."""
import base64
import glob
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request

from flows import close_preview, no_hscroll, scenario
from flows_drive import row_menu, set_device, upload_files
from flows_pay import PAY_LINK, PayFake, attach, close_dialog, sell, wait_pay

FEATURES = ("folders", "pay_to_open", "shop", "market")
SHOP_LINK = r"/shop/([a-z0-9-]{3,30})#6([A-Za-z0-9_-]{43})"     # a private shop: its address, its key after the #


def b64u_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def shop_db(t):
    found = glob.glob(os.path.join(t.work, "data-sidecar-" + "-".join(FEATURES), "**", "mutis.sqlite3"), recursive=True)
    return sqlite3.connect(found[0], timeout=30)


def write(t, sql, args=()):
    con = shop_db(t)
    con.execute(sql, args)
    con.commit()
    con.close()


def read(t, sql, args=()):
    con = shop_db(t)
    rows = con.execute(sql, args).fetchall()
    con.close()
    return rows


class ShopPayFake(PayFake):
    """PayFake, plus what the dev server would hold had it made the pay link itself (see the module's note), and
    `fail_listing`: how many listing writes to refuse (503), for the dialog's clean-up of a pay link it made."""

    fail_listing = 0

    def attach(self, page):
        ic = super().attach(page)
        ic.add("*/api/v1/me/shop/listings/*", "Request", self.listing_gate, "PUT")
        return ic

    def listing_gate(self, _params):
        if self.fail_listing <= 0:
            return None
        self.fail_listing -= 1
        return 503, {"error": {"code": "internal", "message": "internal"}}

    def create_share(self, params):
        out = super().create_share(params)
        if out and out[0] == 201:
            sid, body = out[1]["share_id"], self.share_bodies[-1]
            write(self.t, "INSERT INTO paid_shares(share_id, price_ut, server_half, teaser_ct, buyer_views, buyer_window_s) "
                          "VALUES (?, ?, ?, ?, 3, 604800)", (sid, int(body["price_ut"]), b64u_decode(body["server_half"]),
                                                             b64u_decode(body["teaser_ct"]) if body.get("teaser_ct") else None))
        return out

    def patch_share(self, params):
        out = super().patch_share(params)
        if out and out[0] == 200:
            write(self.t, "UPDATE paid_shares SET paused = ? WHERE share_id = ?", (int(out[1]["paused"]), out[1]["share_id"]))
        return out

    def open_gate(self, params):
        sid = params["request"]["url"].split("/s/")[1].split("/")[0]
        token = next((v for k, v in params["request"]["headers"].items() if k.lower() == "x-mutis-claim"), None)
        out = super().open_gate(params)
        if out is None and sid in self.links and token:
            now = int(time.time())
            cid = next(k for k, c in self.claims.items() if c["share"] == sid and c["status"] == "released")
            write(self.t, "INSERT OR IGNORE INTO claims(id, share_id, token_hash, address, price_ut, received_ut, status, created_at, "
                          "created_seq, expires_at, paid_at, released_at, views_left, open_until, demo) "
                          "VALUES (?, ?, ?, 'test', ?, ?, 'released', ?, 0, ?, ?, ?, 3, ?, 1)",
                  (cid, sid, hashlib.sha256(b64u_decode(token)).digest(), int(self.links[sid]["price_ut"]),
                   int(self.links[sid]["price_ut"]), now, now + 3600, now, now, now + 7 * 86400))
        return out


def seller(t, fake, device="desktop"):
    """A drive past its first day with notes.txt and song.txt, the fake attached (flows_pay.seller, on this server)."""
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
    upload_files(t, page, ["notes.txt", "song.txt"])
    return page


def owner_state(page):
    return page.eval("document.querySelector('[data-testid=\"shop-owner\"]')?.dataset.state ?? ''")


def go_shop(page):
    page.click("nav-shop")
    page.wait("!!document.querySelector('[data-testid=\"shop-owner\"]')", 60)


def listed(page):
    return page.eval("[...document.querySelectorAll('[data-testid=\"shop-listed-row\"]')].map((r) => [r.querySelector('.item-title .shop-own-text').textContent, r.dataset.selling])")


def dialog_open(page):
    page.wait("!!document.getElementById('shop-list') && !document.getElementById('shop-list').hidden", 20)


def wait_closed(page, box="shop-list"):
    page.wait(f"!document.getElementById({json.dumps(box)}) || document.getElementById({json.dumps(box)}).hidden", 60)


def visit(t, fake, url, device):
    page = t.actor(device)
    attach(t, fake, page)
    page.goto(url)
    page.wait("['ready','empty','incomplete','closed','removed','error'].includes(document.querySelector('[data-testid=\"shop-page\"]')?.dataset.state)", 60)
    return page


def shop_state(page):
    return page.eval("document.querySelector('[data-testid=\"shop-page\"]')?.dataset.state ?? ''")


def items(page):
    return page.eval("""[...document.querySelectorAll('[data-testid="shop-item"]')].map((e) => ({
      title: e.querySelector('[data-testid="shop-item-title"]')?.textContent, desc: e.querySelector('[data-testid="shop-item-desc"]')?.textContent ?? '',
      meta: e.querySelector('[data-testid="shop-item-meta"]')?.textContent, price: e.querySelector('[data-testid="shop-item-price"]')?.textContent,
      buy: e.querySelector('[data-testid="shop-buy"]')?.getAttribute('href') ?? null, share: e.dataset.share }))""")


@scenario("shop", "My shop (docs/shop.md): turn it on with a name and a bio, what's public and what stays private; list a file that sells "
          "(its name shows on its pay page, said first) and price one from its row menu (no name in its preview); the shop's link with its key "
          "after the #; a visitor on a phone and a computer sees titles, never names, and buys through /p/ with test money; Take off, a paused link "
          "hidden, Turn off: a closed page", features=FEATURES)
def shop_flow(t):
    fake = ShopPayFake(t)
    a = seller(t, fake)
    url = sell(a, "notes.txt", price="250000")
    sid = re.search(PAY_LINK, url)[1]
    fake.links[sid]["seller_state"] = "ok"
    close_dialog(a)
    t.check(a.exists("nav-shop") and a.text("nav-shop") == "My shop", "the sidebar has My shop where the shop is on")

    # ---- turn it on ----
    go_shop(a)
    t.check(owner_state(a) == "off" and a.exists("shop-off"), f"My shop starts off ({owner_state(a)})")
    facts = a.text("shop-public") + " " + a.text("shop-private")
    t.check("For each thing you list: your title and line, file or folder, its size and price." in facts
            and "File names and what's inside. Your drive and its address." in facts, f"what's public and what stays private ({facts!r})")
    t.check(a.ax_unnamed() == [], f"every control has a name ({a.ax_unnamed()[:4]})")
    a.click("shop-on")
    t.check(a.wait("document.getElementById('shop-name')?.getAttribute('aria-invalid') !== null", 10) is not None
            and a.eval("document.getElementById('shop-name-err').textContent") == "Give your shop a name.", "a shop needs a name, said under it")
    a.fill("shop-name", "Mila's zines")
    a.click("shop-on")
    t.check(a.wait("document.getElementById('shop-username')?.getAttribute('aria-invalid') !== null", 10) is not None
            and a.eval("document.getElementById('shop-username-err').textContent") == "Give your shop an address.", "a shop needs an address, said under it")
    for typed, said in (("mila zines", "Use only the letters a to z, digits and hyphens."), ("m\u0430la", "Use only the letters a to z, digits and hyphens."),
                        ("-mila", "Put a hyphen between letters or digits, one at a time."), ("ab", "Use at least 3 characters.")):
        a.fill("shop-username", typed)
        a.click("shop-on")
        t.check(a.wait(f"document.getElementById('shop-username-err').textContent === {json.dumps(said)}", 10) is not None,
                f"the address {typed!r}: {said}")
    t.check(read(t, "SELECT COUNT(*) FROM shops")[0][0] == 0, "no shop made from a bad address")
    a.fill("shop-username", "Mila-Zines")
    a.fill("shop-bio-input", "Zines and prints from Monterrey.\nNew ones each month.")
    t.check(a.eval("document.querySelector('[data-testid=\"shop-mode-private\"]').dataset.state") == "checked", "Private is the default")
    t.shot(a, "shop-owner-off-1440")
    a.click("shop-on")
    a.wait("document.querySelector('[data-testid=\"shop-owner\"]')?.dataset.state === 'open'", 60)
    link = a.value("shop-link")
    m = re.fullmatch(re.escape(t.origin) + SHOP_LINK, link or "")
    t.check(m is not None and m[1] == "mila-zines", f"the shop's link: its address, folded, its key after the # (kind 6: {link[-70:] if link else link})")
    shop_id, key_b64 = m[1], m[2]
    row = read(t, "SELECT username, identity_id, title, bio, key_wrap, mode, published_key, token_hash FROM shops")[0]
    t.check(row[0] == shop_id and row[2] == "Mila's zines" and row[3] == "Zines and prints from Monterrey.\nNew ones each month."
            and len(row[4]) == 60 and b64u_decode(key_b64) not in row[4] and row[5] == "private" and row[6] is None and len(row[7]) == 32,
            "our server holds the name, the address, the bio, the key only wrapped and a hash of its token")
    t.check(a.exists("shop-listed-empty"), "nothing listed yet")

    # ---- list a file that sells ----
    a.click("shop-add")
    dialog_open(a)
    t.check(a.eval("[...document.querySelectorAll('[data-testid=\"shop-pick-item\"]')].map((e) => e.dataset.name)") == ["notes.txt"],
            "List something offers what sells (notes.txt), by its name, to its owner only")
    t.check("Our server never stores it." in a.text("shop-split"), "the listing dialog says what the shop's link carries, and what that means")
    a.eval("document.querySelector('[data-testid=\"shop-pick-item\"][data-name=\"notes.txt\"]').click()")
    a.wait("!document.getElementById('shop-title').closest('.field').hidden", 20)
    a.wait("!!document.querySelector('[data-testid=\"shop-name-shows\"]')", 20)
    t.check(a.value("shop-title-input") == "", "the title starts empty: never the file's name")
    t.check("notes.txt" in a.text("shop-name-shows") and a.text("shop-list-go") == "List it with its name",
            f"its pay page shows its name: said first, and the button says so ({a.text('shop-name-shows')!r})")
    a.click("shop-list-go")
    t.check(a.eval("document.getElementById('shop-title-err').textContent") == "Give it a title buyers will see.", "a listing needs a title")
    a.fill("shop-title-input", "Zine no. 3")
    a.fill("shop-line-input", "Twelve pages, scanned.")
    t.shot(a, "shop-list-1440")
    a.click("shop-list-go")
    wait_closed(a)
    a.wait("document.querySelectorAll('[data-testid=\"shop-listed-row\"]').length === 1", 30)
    t.check(listed(a) == [["Zine no. 3", "true"]], f"listed and selling ({listed(a)})")

    # ---- price one from its row menu and list it ----
    a.click("nav-mine")
    a.wait_for("file-row", 30)
    row_menu(a, "song.txt", "shop")
    dialog_open(a)
    t.check(a.exists("shop-new-pay") and a.eval("[...document.querySelectorAll('[data-testid=\"shop-price-chip\"]')].map((e) => e.dataset.value)") == ["100000", "250000", "500000"],
            "a file without a pay link: its price is set here, from /config")
    pick_price = "document.querySelector('[data-testid=\"shop-price-chip\"][data-value=\"100000\"]')"
    a.eval(f"{pick_price}.click()")
    a.fill("shop-title-input", "Field recordings")
    # The listing step fails once: the pay link this dialog just made is stopped again, so nothing sells unlisted.
    fake.fail_listing = 1
    a.click("shop-list-go")
    a.wait("!!document.querySelector('#shop-list [data-testid=\"shop-made-stopped\"]')", 60)
    orphan = list(fake.links)[-1]
    state = read(t, "SELECT state FROM shares WHERE id = ?", (orphan,))
    t.check(state == [("revoked",)] and a.exists("error-banner"),
            f"a failed listing: its error, and the pay link the dialog made is stopped (server: {state})")
    a.click("shop-list-go")
    wait_closed(a)
    body = fake.share_bodies[-1]
    song = list(fake.links)[-1]
    t.check(body["price_ut"] == "100000" and len(fake.share_bodies) == 3 and song != orphan,
            "Try again makes a fresh pay link, at the price picked, and lists it")
    a.wait_for("file-row", 30)
    row_menu(a, "song.txt", "shop")
    dialog_open(a)
    t.check(a.value("shop-title-input") == "Field recordings" and "Edit the listing" in a.eval("document.querySelector('#shop-list .dialog-title').textContent"),
            "List in my shop on a listed file edits its listing")
    a.key("Escape")
    wait_closed(a)
    go_shop(a)
    t.check(sorted(x[0] for x in listed(a)) == ["Field recordings", "Zine no. 3"], f"both listed ({listed(a)})")
    metas = a.eval("[...document.querySelectorAll('[data-testid=\"shop-listed-meta\"]')].map((e) => e.textContent).sort()")
    t.check(metas == ["0.1 tTARI · song.txt", "0.25 tTARI · notes.txt"], f"each listing shows its owner the price and which file it is ({metas})")
    t.check(no_hscroll(a), "My shop: no sideways scroll at 1440")
    # The pictures show the page alone: the upload panel closed with its ×, the toasts gone by themselves.
    a.eval("document.querySelector('.uploads-head button[aria-label=\"Close\"]')?.click()")
    a.wait("!document.querySelector('.toaster .toast')", 15)
    t.shot(a, "shop-owner-1440")
    set_device(a, "iphone")
    t.check(no_hscroll(a) and a.ax_unnamed() == [], "My shop on a phone: no sideways scroll, every control named")
    t.shot(a, "shop-owner-390", full_page=True)
    set_device(a, "desktop")
    stored = read(t, "SELECT title, description, kind, price_ut, length(link_ct) FROM shop_listings ORDER BY created_at")
    t.check(sorted(stored) == sorted([("Zine no. 3", "Twelve pages, scanned.", "file", 250000, 60), ("Field recordings", "", "file", 100000, 60)]),
            f"our server keeps what the owner published, and each half of a key only sealed ({stored})")
    names = read(t, "SELECT COUNT(*) FROM shop_listings WHERE title LIKE '%notes%' OR title LIKE '%song%'")[0][0]
    t.check(names == 0, "no file name went to the shop")

    # ---- a visitor ----
    for device, width in (("iphone", 390), ("desktop", 1440)):
        v = visit(t, fake, link, device)
        t.check(shop_state(v) == "ready", f"{device}: the shop opens ({shop_state(v)})")
        got = items(v)
        titles = sorted(x["title"] for x in got)
        t.check(v.text("shop-title") == "Mila's zines" and v.eval("document.querySelector('[data-testid=\"shop-bio\"]').innerText")
                == "Zines and prints from Monterrey.\nNew ones each month.", f"{device}: the name and the bio, with its own line break")
        t.check(titles == ["Field recordings", "Zine no. 3"], f"{device}: the titles the owner wrote ({titles})")
        zine = next(x for x in got if x["title"] == "Zine no. 3")
        t.check(zine["desc"] == "Twelve pages, scanned." and zine["price"] == "0.25 tTARI" and zine["meta"].startswith("File · About "),
                f"{device}: its line, file and about how big, its price in the currency /config names ({zine})")
        t.check(re.fullmatch(re.escape(t.origin) + PAY_LINK, zine["buy"] or "") is not None and zine["buy"].startswith(f"{t.origin}/p/{sid}#5"),
                f"{device}: Buy and open is the pay link itself, its half of the key opened here from the shop's key")
        html = v.eval("document.documentElement.outerHTML")
        t.check("notes.txt" not in html and "song.txt" not in html, f"{device}: no file name anywhere on the page")
        t.check("Its owner wrote this page. The server doesn't check it." in v.text("shop-owner-note"), f"{device}: who wrote it")
        report = v.attr("shop-report", "href")
        t.check(report == "/fine-print#link=" + urllib.parse.quote(f"{t.origin}/shop/{shop_id}", safe="") and key_b64 not in report,
                f"{device}: Report this shop fills the report form with the shop's link, without its key ({report})")
        t.check(no_hscroll(v) and v.ax_unnamed() == [] and v.csp_violations() == [], f"{device}: no sideways scroll, every control named, no CSP violation")
        sent = [r["url"] for r in v.requests]
        t.check(not any(key_b64 in u for u in sent) and any(f"/api/v1/shop/{shop_id}" in u for u in sent),
                f"{device}: the page asks for /shop/{{id}}; the shop's key never leaves the browser")
        t.shot(v, f"shop-{width}", full_page=True)
        if device == "iphone":
            # The listing priced from the row menu: its preview carries no name (read with its half, as a buyer would).
            rec = next(x for x in got if x["title"] == "Field recordings")
            sA = rec["buy"].split("#5")[1]
            teaser = v.eval(f"""(async () => {{ const p = await import('/app/lib/pay.js'); const b = await import('/app/lib/b64.js');
              return p.openTeaser(b.b64uDecode({json.dumps(sA)}), b.b64uDecode({json.dumps(body['teaser_ct'])})); }})()""")
            t.check(teaser.get("kind") == "file" and "name" not in teaser, f"a pay link made for the shop has no name in its preview ({teaser})")
            # Buy and open, on the phone: the pay page, test money, the open.
            v.eval(f"document.querySelector('[data-testid=\"shop-item\"][data-share=\"{sid}\"] [data-testid=\"shop-buy\"]').click()")
            t.check(wait_pay(v, ("wait",), 60) == "wait", "Buy and open lands on the pay page, waiting for a payment")
            t.check(v.text("pay-name") == "notes.txt", "the pay page's preview names it, as its owner allowed when selling")
            v.click("pay-test")
            t.check(wait_pay(v, ("open",), 90) == "open", "paid with test money: ready to open")
            v.click("pay-open")
            v.wait_for("pay-file", 60)
            t.check(v.text("pay-file").startswith("notes.txt"), "opened: the file the listing sells")
            v.wait("!!document.getElementById('lightbox')", 30)
            t.shot(v, "shop-bought-390")
            close_preview(v)

    # ---- public: anyone can read it, search engines too, and it is in the market; the key stays in the drive. A visitor
    # at the address asks; the owner's open drive answers; the visitor pays and opens. Then private again, same key ----
    go_shop(a)
    t.check(a.text("shop-mode-now") == "Private", "My shop says who can see it: Private")
    a.click("shop-mode-switch")
    a.wait("!!document.getElementById('shop-mode-dialog') && !document.getElementById('shop-mode-dialog').hidden", 20)
    said = a.eval("document.getElementById('shop-mode-dialog').textContent")
    t.check("search engines" in said and "never gets your shop's key" in said and "it could ask too" in said,
            f"Make it public says what it means, before, our server's half included ({said[:200]!r})")
    a.click("shop-mode-confirm")
    a.wait("document.querySelector('[data-testid=\"shop-mode-now\"]')?.textContent === 'Public'", 30)
    address = f"{t.origin}/shop/{shop_id}"
    t.check(a.value("shop-link") == link and a.value("shop-address") == address,
            f"public: the whole link still buys at once, and the address is shown for the market ({a.value('shop-address')})")
    row = read(t, "SELECT mode, published_key FROM shops")[0]
    t.check(row == ("public", None), "public: our server holds no key")
    with urllib.request.urlopen(address, timeout=30) as res:
        robots, html = res.headers.get("X-Robots-Tag"), res.read().decode()
    t.check(robots == "index, follow" and '<meta name="robots" content="index, follow">' in html
            and f'<link rel="canonical" href="{address}">' in html and "<title>Mila&#x27;s zines · hidebox</title>" in html
            and "Zine no. 3" in html and "application/ld+json" in html and "notes.txt" not in html and key_b64 not in html,
            "the public page as served, before any script: indexable, its canonical, its title and listings; no file name, no key")
    with urllib.request.urlopen(f"{t.origin}/api/v1/shops/sitemap.xml", timeout=30) as res:
        mapped = res.read().decode()
    t.check(f"<loc>{address}</loc>" in mapped and f"<loc>{t.origin}/market</loc>" in mapped, "the sitemap lists it, and the market")
    pub = visit(t, fake, address, "iphone")
    got = items(pub)
    pub.wait(f"document.querySelectorAll('[data-testid=\"market-ask-go\"]').length === {len(got)}", 30)
    t.check(shop_state(pub) == "ready" and got and all(x["buy"] is None for x in got)
            and pub.eval("document.querySelectorAll('[data-testid=\"market-ask-go\"]').length") == len(got),
            f"at the address, no key in it: no pay link, Ask for it on each ({[x['title'] for x in got]})")
    t.check(no_hscroll(pub) and pub.csp_violations() == [], "the public page on a phone: no sideways scroll, no CSP violation")
    t.shot(pub, "shop-public-390", full_page=True)
    pub.eval(f"document.querySelector('[data-testid=\"shop-item\"][data-share=\"{sid}\"] [data-testid=\"market-ask-go\"]').click()")
    pub.wait("document.querySelector('[data-testid=\"market-ask\"]')?.dataset.state === 'waiting'", 60)
    t.check(read(t, "SELECT COUNT(*) FROM market_asks WHERE share_id = ? AND answer IS NULL", (sid,))[0][0] == 1,
            "asked: one ask waits on our server")
    back = pub.eval("document.querySelector('[data-testid=\"market-come-back\"]')?.getAttribute('href') ?? ''")
    t.check(re.fullmatch(re.escape(t.origin) + r"/market#8[A-Za-z0-9_-]{43}", back) is not None, f"a link to come back with the ask's secret after the # ({back[:40]})")
    t.shot(pub, "market-ask-waiting-390")
    a.eval("document.dispatchEvent(new Event('visibilitychange'))")       # the owner's drive answers on its next round
    pub.wait("document.querySelector('[data-testid=\"market-ask\"]')?.dataset.state === 'answered'", 120)
    answer = read(t, "SELECT answer FROM market_asks WHERE share_id = ?", (sid,))[0][0]
    sA = pub.eval("document.querySelector('[data-testid=\"market-go-pay\"]').getAttribute('href')").split("#5")[1]
    t.check(answer is not None and len(answer) == 125 and b64u_decode(sA) not in answer and b64u_decode(key_b64) not in answer,
            "the owner's drive answered: 125 sealed bytes our server can't read, no key half in them")
    pub.click("market-go-pay")
    t.check(wait_pay(pub, ("wait",), 60) == "wait" and pub.eval("location.pathname") == f"/p/{sid}",
            "Go to pay is the pay link itself, waiting for a payment")
    pub.click("pay-test")
    t.check(wait_pay(pub, ("open",), 90) == "open", "paid with test money: ready to open, as through the shop's link")
    with urllib.request.urlopen(f"{t.origin}/market", timeout=30) as res:
        robots, html = res.headers.get("X-Robots-Tag"), res.read().decode()
    t.check(robots == "index, follow" and "Zine no. 3" in html and f'<link rel="canonical" href="{t.origin}/market">' in html
            and key_b64 not in html, "/market as served: indexable, the newest listings, no key")
    mk = t.actor("desktop")
    attach(t, fake, mk)
    mk.goto(f"{t.origin}/market")
    mk.wait("['ready','empty','error'].includes(document.querySelector('[data-testid=\"market-page\"]')?.dataset.state)", 60)
    titles = mk.eval("[...document.querySelectorAll('[data-testid=\"market-item-title\"]')].map((e) => e.textContent)")
    shops = mk.eval("[...document.querySelectorAll('[data-testid=\"market-item-shop\"]')].map((e) => e.getAttribute('href'))")
    t.check(sorted(titles) == ["Field recordings", "Zine no. 3"] and set(shops) == {f"/shop/{shop_id}"},
            f"the market lists the public shop's listings, each with its shop ({titles})")
    t.check(mk.eval("document.querySelectorAll('[data-testid=\"market-ask-go\"]').length") == 2, "each with Ask for it")
    mk.fill("market-q", "recordings")
    mk.click("market-search-go")
    mk.wait("document.querySelectorAll('[data-testid=\"market-item\"]').length === 1", 30)
    t.check(mk.eval("document.querySelector('[data-testid=\"market-item-title\"]').textContent") == "Field recordings",
            "search by words (the shop's own name, Mila's zines, would match both)")
    t.check(no_hscroll(mk) and mk.ax_unnamed() == [] and mk.csp_violations() == [], "the market: no sideways scroll, every control named, no CSP violation")
    t.shot(mk, "market-1440", full_page=True)
    other = t.actor("iphone")
    attach(t, fake, other)
    other.goto(back)
    other.wait("document.querySelector('[data-testid=\"market-ask\"]')?.dataset.state === 'answered'", 60)
    t.check(other.eval("location.hash") == "" and other.eval("document.querySelector('[data-testid=\"market-go-pay\"]').getAttribute('href')").endswith(sA),
            "the link to come back, on another device: the answered ask, and the secret gone from the address bar")
    t.shot(other, "market-ask-answered-390")
    a.click("shop-mode-switch")
    a.wait("!!document.getElementById('shop-mode-dialog') && !document.getElementById('shop-mode-dialog').hidden", 20)
    said = a.eval("document.getElementById('shop-mode-dialog').textContent")
    t.check("leaves the market" in said and "link keeps working" in said, f"Make it private says it leaves the market ({said[:160]!r})")
    a.click("shop-mode-confirm")
    a.wait("document.querySelector('[data-testid=\"shop-mode-now\"]')?.textContent === 'Private'", 30)
    t.check(a.value("shop-link") == link, "private again: the same link and key")
    t.check(read(t, "SELECT mode, published_key FROM shops")[0] == ("private", None), "still no key on our server")
    with urllib.request.urlopen(address, timeout=30) as res:
        t.check(res.headers.get("X-Robots-Tag") == "noindex, nofollow" and "Zine no. 3" not in res.read().decode(),
                "the address alone shows nothing again, noindex")
    v = visit(t, fake, link, "desktop")
    t.check(any(x["buy"] and x["buy"].startswith(f"{t.origin}/p/{sid}#5") for x in items(v)), "the link sells as before")

    # ---- take one off; a paused link hides; turn it off ----
    a.eval("document.querySelector('[data-testid=\"shop-listed-row\"][data-share=\"" + sid + "\"] [data-testid=\"shop-unlist\"]').click()")
    a.wait("document.querySelectorAll('[data-testid=\"shop-listed-row\"]').length === 1", 30)
    t.check(listed(a) == [["Field recordings", "true"]], f"Take off: it leaves the shop ({listed(a)})")
    v = visit(t, fake, link, "desktop")
    t.check([x["title"] for x in items(v)] == ["Field recordings"], "the visitor's next look shows one")
    fake.links[song]["seller_state"] = "ok"
    a.click("nav-mine")
    a.wait_for("file-row", 30)
    row_menu(a, "song.txt", "stop-sell")
    deadline = time.time() + 30
    while time.time() < deadline and not fake.links[song]["paused"]:
        a.b.drain(0.25)
    go_shop(a)
    t.check(listed(a) == [["Field recordings", "false"]] and "Hidden while it isn't selling." in a.text("shop-listed"),
            f"Stop selling hides it: Not selling, and why ({listed(a)})")
    v.reload()
    v.wait("['ready','empty'].includes(document.querySelector('[data-testid=\"shop-page\"]')?.dataset.state)", 60)
    t.check(shop_state(v) == "empty" and "Nothing for sale right now." in v.text("shop-empty"), "the visitor sees nothing for sale while it doesn't sell")
    t.shot(v, "shop-empty-1440")
    a.click("shop-off")
    a.wait("!!document.getElementById('shop-off-dialog') && !document.getElementById('shop-off-dialog').hidden", 20)
    t.check("Your pay links keep selling." in a.eval("document.getElementById('shop-off-dialog').textContent"), "Turn off says the pay links stay")
    a.click("shop-off-confirm")
    a.wait("document.querySelector('[data-testid=\"shop-owner\"]')?.dataset.state === 'off'", 30)
    t.check(read(t, "SELECT COUNT(*) FROM shops")[0][0] == 0 and read(t, "SELECT COUNT(*) FROM shop_listings")[0][0] == 0,
            "turned off: the shop and its listings are gone from our server")
    v.reload()
    v.wait("['closed'].includes(document.querySelector('[data-testid=\"shop-page\"]')?.dataset.state)", 60)
    t.check(shop_state(v) == "closed" and "This shop is closed." in v.eval("document.getElementById('main').textContent"), "the shop's link now says it's closed")
    nokey = visit(t, fake, link.split("#")[0], "iphone")
    t.check(shop_state(nokey) == "incomplete", "a shop's link without its key says it lost its key")
