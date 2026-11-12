#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The cut-over check (docs/cutover.md): links and a drive made on the old deployment before the switch, then the same
host after it. Python standard library only; the browser runs on the server as `build` (relay.py), as with run.py.
  python3 -I tests/e2e/cutover.py --site https://hidebox.app --testnet https://testnet.hidebox.app \\
      --old-mainnet https://mainnet.hidebox.app --testnet-instance '' --mainnet-instance NAME \\
      --switch 'the command that runs the switch' [--out DIR] [--keep]
Before the switch, on --site (the testnet then): a text secret (Once), a drive with a file and its link, a pay link
(with pay to open on), a drop link and a judge pass link. --switch runs the switch. After it, on the same host: each
link goes to the testnet with its path, query and #fragment, and opens there; the judge pass lands in the testnet's
/judges; /verify#<share id> follows; the drive gets the handover, and its key file opens it on the testnet with its
file; a link made on the host afterwards stays there; the old mainnet host answers 308 to the host. It only ever opens
what it made, and takes every link it made down by id at the end (mutis-admin takedown) unless --keep.
"""
import argparse
import json
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
import flows  # noqa: E402
import scenarios_chain as chain  # noqa: E402
import scenarios_drive as drv  # noqa: E402
from harness import REMOTE_DIR, SSH_HOST, Env, Failed, Remote, T  # noqa: E402
from scenarios import make_drop_link  # noqa: E402


# The drive's record in IndexedDB "mutis", store "identity", key "current", without its `net` (lib/identity.js recordOf).
UNMARK = """new Promise((resolve, reject) => {
  const open = indexedDB.open('mutis');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result;
    const tx = db.transaction('identity', 'readwrite');
    const store = tx.objectStore('identity');
    const get = store.get('current');
    get.onsuccess = () => { const rec = get.result; delete rec.net; store.put(rec, 'current'); };
    tx.oncomplete = () => { db.close(); resolve(true); };
    tx.onerror = () => reject(tx.error);
  };
})"""


class NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def head(url: str) -> tuple[int, str]:
    """The status and Location of one request, redirects not followed."""
    opener = urllib.request.build_opener(NoFollow)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "mutis-cutover"})
    try:
        with opener.open(req, timeout=20) as res:
            return res.status, res.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def config(origin: str) -> dict:
    req = urllib.request.Request(origin + "/api/v1/config", headers={"User-Agent": "mutis-cutover"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def landed(page, origin: str, path: str, timeout: float = 60) -> str:
    """Waits until the page is at `origin` + `path`; -> its full URL."""
    want = json.dumps(origin + path)
    return page.wait(f"location.origin + location.pathname === {want} ? location.href : ''", timeout)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", required=True, help="the site whose host moves (hidebox.app's role)")
    p.add_argument("--testnet", required=True, help="where the testnet goes (testnet.hidebox.app's role)")
    p.add_argument("--old-mainnet", required=True, help="the mainnet's old host, which answers 308 after the switch")
    p.add_argument("--testnet-instance", default="", help="the testnet's instance name ('' for production)")
    p.add_argument("--mainnet-instance", required=True)
    p.add_argument("--switch", required=True, help="a shell command, run here between the two halves")
    p.add_argument("--host", default=SSH_HOST, help="ssh host of the server (MUTIS_SSH_HOST)")
    p.add_argument("--out", type=Path, default=Path("cutover-artifacts"))
    p.add_argument("--keep", action="store_true", help="leave the test links up")
    p.add_argument("--unmark", action="store_true", help="a rehearsal whose old deployment runs this release: take the "
                   "network mark off the drive's record before the switch, as the October app's record has none")
    args = p.parse_args()
    host, testnet, old = (u.rstrip("/") for u in (args.site, args.testnet, args.old_mainnet))
    out = args.out / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    control = Path(tempfile.mkdtemp(prefix="mutis-cutover-"))
    remote_old = Remote(args.host, control, args.testnet_instance)
    remote_new = Remote(args.host, control, args.mainnet_instance)
    env = Env(host, remote_old, out)
    env.stage()
    t = T(env, "CUT")
    results: list[tuple[str, bool, str]] = []
    made: dict[str, list] = {"old_shares": [], "old_drops": [], "new_shares": []}

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))
        print(f"{'ok  ' if ok else 'FAIL'} {name}{f'  ({detail})' if detail else ''}", flush=True)

    def step(name: str, fn) -> None:
        try:
            fn()
        except Exception as e:  # one link class failing doesn't stop the others
            detail = f"{type(e).__name__}: {str(e)[:300]} @ {traceback.extract_tb(e.__traceback__)[-1].lineno}"
            check(name, False, detail)
            for i, ctx in enumerate(t.contexts):
                for j, page in enumerate(ctx.pages):
                    try:
                        page.screenshot(str(out / f"{name.split(':')[0].replace(' ', '-')}-{i}-{j}.png"))
                    except (cdp.CdpError, OSError, ValueError):
                        pass

    try:
        # --- before: the old deployment on the host -------------------------------------------------------------
        before = config(host)
        check("before: the host is the testnet", before.get("network") == "esmeralda" and not before.get("legacy_origin"),
              f"{before.get('network')}, legacy_origin {before.get('legacy_origin')}")
        a = t.actor()
        flows.home(a, host)
        text_url = flows.seal_text(a, f"E2E cut-over {secrets.token_hex(3)}: a note from before the move")
        made["old_shares"].append(flows.share_id(text_url))
        d = t.actor()
        d.goto(host + "/drive?make")
        d.wait_for("drive-root", 120)
        d.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
        drv.upload_files(t, d, {"cutover.txt": b"E2E cut-over: a file in a drive from before the move.\n"})
        share_url = drv.share_link(d, "cutover.txt")
        made["old_shares"].append(flows.share_id(share_url))
        _, safety = drv.identity(d)
        made_links = {"pay": "", "drop": ""}

        def pay_before():
            made_links["pay"], pay_sid = chain.sell(t, d, "cutover.txt")
            made["old_shares"].append(pay_sid)

        def drop_before():
            made_links["drop"] = make_drop_link(t, d, "E2E cut-over")
            made["old_drops"].append(flows.share_id(made_links["drop"]))
        if (before.get("features") or {}).get("pay_to_open"):
            step("before: a pay link", pay_before)
        step("before: a drop link", drop_before)
        pay_url, drop_url = made_links["pay"], made_links["drop"]
        if args.unmark:
            unmarked = d.eval(UNMARK, await_promise=True)
            check("before: the drive's record has no network mark, as the October app writes it", unmarked is True, str(unmarked))
        # A pass can't be revoked: this one has one use, skips one proof of work and ends by itself.
        judge = remote_old.admin("judge-pass", "new", "--uses", "1", "--pow-skips", "1").strip()
        judge_url = f"{host}/judges#pass={judge}"
        check("before: test links made", True, f"text, share, {'pay link, ' if pay_url else ''}{'drop, ' if drop_url else ''}judge pass")

        # --- the switch ------------------------------------------------------------------------------------------
        started = time.monotonic()
        res = subprocess.run(args.switch, shell=True)
        check("the switch ran", res.returncode == 0, f"exit {res.returncode}, {time.monotonic() - started:.0f} s")
        if res.returncode:
            return 1

        # --- after: the same host ---------------------------------------------------------------------------------
        after = config(host)
        check("after: the host is the new deployment, naming the testnet as legacy_origin",
              after.get("legacy_origin") == testnet and after.get("origin") == host, f"{after.get('network')}, {after.get('origin')}")
        tn = config(testnet)
        check("after: the testnet answers at its own host", tn.get("network") == "esmeralda" and tn.get("origin") == testnet,
              f"{tn.get('origin')}")

        def text_link():
            b = t.actor()
            state = flows.open_link(b, text_url)
            at = b.eval("location.href")
            check("a text secret (/s/, Once) opens on the testnet with its key", state == "opened" and at.startswith(testnet + "/s/"),
                  f"{state} at {at.split('#')[0]}")
        step("text: /s/", text_link)

        def share_link():
            b = t.actor()
            state = flows.open_link(b, share_url)
            at = b.eval("location.href")
            # Opening proves the key after the # arrived; the viewer then takes it out of the address bar.
            check("a drive's file link (/s/) opens on the testnet with its key", state == "opened" and at.startswith(testnet + "/s/"),
                  f"{state} at {at.split('#')[0]}")
        step("share: /s/", share_link)

        if pay_url:
            def pay_link():
                b = t.actor()
                b.goto(pay_url)
                b.wait_for("pay-page", 90)
                state = b.attr("pay-page", "data-state")
                at = b.eval("location.href")
                check("a pay link (/p/) shows its page on the testnet, the half key kept", at.startswith(testnet + "/p/")
                      and at.endswith("#" + flows.fragment(pay_url)), f"{state} at {at.split('#')[0]}")
            step("pay: /p/", pay_link)

        def drop_link():
            if not drop_url:
                raise Failed("no drop link was made before the switch")
            b = t.actor()
            b.goto(drop_url)
            b.wait_for("dd-root", 60)
            check("a drop link (/d/) shows its page on the testnet", b.eval("location.href").startswith(testnet + "/d/"))
        step("drop: /d/", drop_link)

        def judge_link():
            b = t.actor()
            b.goto(judge_url)
            landed(b, testnet, "/judges")
            saved = b.wait("localStorage.getItem('mutis.judge') || ''", 30)
            check("a judge pass link lands on the testnet's /judges, saved there", judge in saved)
        step("judge: /judges#pass=", judge_link)

        def verify_link():
            b = t.actor()
            sid = flows.share_id(share_url)
            b.goto(f"{host}/verify#{sid}")
            at = landed(b, testnet, "/verify")
            check("/verify#<share id> of a testnet link goes to the testnet's /verify", at.endswith("#" + sid), at.split("#")[0])
        step("verify: /verify#", verify_link)

        def handover():
            d.goto(host + "/drive")
            d.wait_for("drive-moved", 60)
            check("the drive saved on the host gets the handover screen, not a mainnet drive",
                  not d.exists("drive-root") and d.exists("drive-make"))
            d.click("moved-save")
            path = t.downloaded(d)
            key_text = t.env.remote.as_build(f"cat {shlex.quote(path)}")
            t.secret("the key file", key_text.strip())
            check("its key file holds the key, and no address worked out on the new network",
                  "Key: MUTIS-" in key_text and "Tari address" not in key_text)
            d.goto(testnet + "/drive?open")
            d.wait_for("open-dialog", 60)
            d.click("restore-open")
            fixture = f"{REMOTE_DIR}/fixtures/CUT-key.txt"
            t.env.remote.as_build(f"cat > {shlex.quote(fixture)}", key_text.encode())
            d.set_files("restore-file", [fixture])
            d.wait("document.querySelector('[data-testid=\"restore-text\"]').value.includes('MUTIS-')", 15)
            d.click("restore-submit")
            d.wait_for("drive-root", 120)
            drv.wait_names(d, ["cutover.txt"])
            _, again = drv.identity(d)
            check("the key file opens the same drive on the testnet, with its file", again == safety)
            d.goto(host + "/drive")
            d.wait_for("drive-moved", 60)
            check("back on the host, the drive set aside is still offered", d.exists("moved-save"))
        step("drive: the handover", handover)

        def new_link():
            b = t.actor()
            flows.home(b, host)
            url = flows.seal_text(b, f"E2E cut-over {secrets.token_hex(3)}: a note from after the move")
            made["new_shares"].append(flows.share_id(url))
            c = t.actor()
            state = flows.open_link(c, url)
            at = c.eval("location.href")
            check("a link made on the host after the switch stays on the host", state == "opened" and at.startswith(host + "/s/"),
                  f"{state} at {at.split('#')[0]}")
        step("new: /s/ on the host", new_link)

        status, where = head(old + "/drive?from=t521")
        check("the old mainnet host answers 308 to the host, path and query kept",
              status == 308 and where == host + "/drive?from=t521", f"{status} {where}")
        status, where = head("http://" + old.removeprefix("https://") + "/x")
        check("…on plain HTTP too", status in (301, 308) and where.startswith(("https://" + old.removeprefix("https://"), host)),
              f"{status} {where}")
    finally:
        if not args.keep:
            if made["old_shares"]:   # the drive's file too, not only its links (the text secret's item went when it opened)
                marks = ", ".join("?" for _ in made["old_shares"])
                try:
                    items = remote_old.sql(f"SELECT DISTINCT item_id FROM shares WHERE id IN ({marks})", *made["old_shares"])
                except Exception as e:   # the links still go below; the report says what was left
                    items, made["purge_error"] = [], f"{type(e).__name__}: {e}"[:300]
                for (item,) in items:
                    remote_old.run(f"sudo mutis-admin{remote_old.suffix} takedown item -- {shlex.quote(item)}", check=False)
            for sid in made["old_shares"]:
                remote_old.run(f"sudo mutis-admin{remote_old.suffix} takedown share -- {shlex.quote(sid)}", check=False)
            for did in made["old_drops"]:
                remote_old.run(f"sudo mutis-admin{remote_old.suffix} takedown drop -- {shlex.quote(did)}", check=False)
            for sid in made["new_shares"]:
                remote_new.run(f"sudo mutis-admin{remote_new.suffix} takedown share -- {shlex.quote(sid)}", check=False)
        (out / "report.json").write_text(json.dumps({"host": host, "testnet": testnet, "made": made,
                                                     "checks": [{"name": n, "ok": ok, "detail": det} for n, ok, det in results]},
                                                    indent=1))
        t.close()
    failed = [n for n, ok, _ in results if not ok]
    print(f"cutover: {'PASS' if not failed else 'FAIL'} ({len(results) - len(failed)} of {len(results)}) → {out}/report.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
