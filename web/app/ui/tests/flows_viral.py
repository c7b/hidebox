# SPDX-License-Identifier: MIT
"""viral-1 (docs: CHANGELOG, DESIGN.md's One Sentence A Line Rule, C60 in tools/claim-registry.json): after the value, a
recipient gets one quiet line with one button, never before it and never in a browser that holds a drive; and a tab that
came through Make your own secret or Sell your own files (?from=share) says so once, with its next one-off link or new
drive, and nothing else. The folder, the buyer page and the drop page check their own line in flows_share.py,
flows_pay.py and flows_ux.py."""
import glob
import os
import sqlite3

from flows import VIEW_END, close_preview, home, invite_check, no_hscroll, open_link, scenario, seal_text
from flows_share import FEATURES

# Every create request a page sends that can carry the flag: a link (POST /items/{id}/shares) and a new drive (POST
# /auth/register), with its body as sent. Test-only, in the test browser.
POSTS = r"""(() => {
  const real = window.fetch.bind(window);
  window.__posts = [];
  window.fetch = async (input, init = {}) => {
    const url = String(input instanceof Request ? input.url : input);
    if (String(init.method || 'GET').toUpperCase() === 'POST' && /\/api\/v1\/(items\/[^/]+\/shares|auth\/register)$/.test(url)) {
      window.__posts.push([url.replace(/^.*\/api\/v1/, ''), JSON.parse(init.body)]);
    }
    return real(input, init);
  };
})()"""
FLAG = "sessionStorage.getItem('mutis.from_share')"


def counts(t, data="data"):
    """The two daily counts on one of the dev servers this run started (`data`: its data directory, run.py origin_for)."""
    found = glob.glob(os.path.join(t.work, data, "**", "mutis.sqlite3"), recursive=True)
    con = sqlite3.connect(found[0], timeout=30)
    try:
        return dict(con.execute("SELECT kind, SUM(n) FROM daily_counts GROUP BY kind").fetchall())
    finally:
        con.close()


def posts(page, kind):
    return [body for path, body in page.eval("window.__posts || []") if (kind == "share") == path.endswith("/shares")]


@scenario("viral-invite", "viral-1: the link page's one quiet line comes only after the value (an opened secret), at 390 and "
          "1440: Make your own secret to /?from=share#share, nothing of the link in it, × hides it for the page view; the foot "
          "keeps Make your own secret, with ?from=share; a browser that holds a drive gets no line")
def viral_invite(t):
    for device, w in (("iphone", 390), ("desktop", 1440)):
        m = t.actor()
        home(t, m)
        url = seal_text(m, "Stage door, nine o'clock.")
        sid = url.split("/s/")[1].split("#")[0]
        v = t.actor(device)
        t.check(open_link(v, url, open_it=False) == "ready", f"{w}: ready")
        t.check(not v.exists("invite") and v.attr("view-own", "href") == "/?from=share#share",
                f"{w}: before the value, no line; the foot's Make your own secret carries ?from=share")
        v.click("view-open")
        t.check(v.wait_state("view-root", VIEW_END, 60) == "opened", f"{w}: opened")
        close_preview(v)
        t.check(v.eval("!!(document.querySelector('.a-intact').compareDocumentPosition(document.querySelector('[data-testid=\"invite\"]'))"
                       " & Node.DOCUMENT_POSITION_FOLLOWING)") and v.exists("view-own"),
                f"{w}: the line comes after the secret and its Save, before the foot, which keeps Make your own secret")
        invite_check(t, v, "secret", f"/s/ opened, {w}", shot=f"viral-secret-{w}", secrets=(sid, url.split("#")[1], "Stage door"))
        t.check(v.exists("view-own") and v.attr("view-root", "data-state") == "opened", f"{w}: after ×, the page and its foot stay")
    # A browser that holds a drive already has its own: no line.
    m = t.actor()
    home(t, m)
    url = seal_text(m, "for a drive owner")
    d = t.actor()
    d.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('mutis.drive', '1'); } catch {}"})
    t.check(open_link(d, url) == "opened", "a browser with a drive opens it")
    close_preview(d)
    t.check(d.eval("document.documentElement.hasAttribute('data-has-drive')") and not d.exists("invite") and d.exists("view-own"),
            "a browser that holds a drive: no line (the foot stays)")


@scenario("viral-count", "viral-1 (C60): ?from=share leaves the address bar at once and the #share arrival still glows; the tab keeps "
          "one flag in sessionStorage (no cookie, nothing in localStorage); its next one-off link says from_share: true once, then "
          "never again; the same for a new drive from Sell your own files; the server adds one to that day's number")
def viral_count(t):
    before = counts(t)
    # From a link page's foot: Make your own secret, in the same tab.
    m = t.actor()
    home(t, m)
    url = seal_text(m, "The office key is under the plant.")
    a = t.actor("desktop")
    a.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": POSTS})
    t.check(open_link(a, url) == "opened", "a stranger opens a secret")
    close_preview(a)
    a.click("view-own")
    a.wait("!!document.querySelector('#mutis-drop.share-glow .md-zone')", 60)
    t.check(a.eval("location.pathname + location.search + location.hash") == "/#share",
            f"the home at /#share: ?from=share left the address bar ({a.eval('location.href')})")
    t.check(a.eval(FLAG) == "1" and a.eval("Object.keys(localStorage).filter((k) => /share/i.test(k)).length") == 0
            and a.eval("document.cookie") == "", "one flag in this tab's sessionStorage; nothing in localStorage, no cookie")
    t.check(a.eval("document.getElementById('mutis-drop').classList.contains('share-glow')"), "and the arrival still glows")
    first = seal_text(a, "my own secret")
    sent = posts(a, "share")
    t.check(first.startswith(t.origin + "/s/") and len(sent) == 1 and sent[0].get("from_share") is True,
            f"the first link from this tab says from_share: true ({[b.get('from_share') for b in sent]})")
    t.check(a.eval(FLAG) is None, "then the flag is gone")
    a.goto(t.origin + "/")   # the same tab, the next link
    a.wait_for("drop-input", 60)
    seal_text(a, "and another")
    sent = posts(a, "share")
    t.check(len(sent) == 1 and "from_share" not in sent[0], f"the next link says nothing ({sent and sorted(sent[0])})")
    after = counts(t)
    t.check(after.get("secret_from_share", 0) - before.get("secret_from_share", 0) == 1,
            f"the server counted one link for the day ({before} → {after})")


@scenario("viral-count-drive", "viral-1 (C60): Sell your own files (/drive?make&from=share) makes a drive at once, from=share "
          "out of the address bar; its register says from_share: true once and the server counts one drive for the day; a drive "
          "made without the invitation says nothing", features=FEATURES)
def viral_count_drive(t):
    data = "data-sidecar-" + "-".join(FEATURES)
    before = counts(t, data)
    d = t.actor("iphone")
    d.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": POSTS})
    d.goto(t.origin + "/drive?make&from=share")
    d.wait_for("drive-root", 120)
    t.check("from=share" not in d.eval("location.href") and d.eval("location.pathname") == "/drive",
            f"?make made the drive at once; from=share is out of the address bar ({d.eval('location.href')})")
    reg = posts(d, "drive")
    t.check(len(reg) == 1 and reg[0].get("from_share") is True and d.eval(FLAG) is None,
            f"the new drive says from_share: true once, then the flag is gone ({reg and reg[0].get('from_share')})")
    t.check(counts(t, data).get("drive_from_share", 0) - before.get("drive_from_share", 0) == 1, "the server counted one drive for the day")
    # Without the flag, nothing is said.
    e = t.actor()
    e.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": POSTS})
    e.goto(t.origin + "/drive?make")
    e.wait_for("drive-root", 120)
    reg = posts(e, "drive")
    t.check(len(reg) == 1 and "from_share" not in reg[0], "a drive made without the invitation says nothing")
    t.check(counts(t, data).get("drive_from_share", 0) - before.get("drive_from_share", 0) == 1, "and isn't counted")
    t.check(no_hscroll(d), "no horizontal scroll")
