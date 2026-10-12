# SPDX-License-Identifier: MIT
"""UI steps shared by the scenarios, written only against the data-testid contract of spec §3.4.9
(and the brand patch P-6 ids card-change / card-send-address). Python stdlib only."""
import json
import urllib.parse

from cdp import Page
from harness import Failed

VIEW_END = ("opened", "program-warning", "opened-risky", "integrity-error", "burned", "expired", "revoked",
            "removed", "not-found", "locked", "error", "needs-locker", "wrong-key", "incomplete")
VIEW_ASK = ("ready", "password", "needs-locker", "wrong-key", "incomplete", "burned", "expired", "revoked",
            "removed", "not-found", "locked", "error")


def home(page: Page, origin: str) -> None:
    page.goto(origin + "/")
    page.wait("!!document.querySelector('[data-testid=\"drop-input\"]')", 60)


def wait_link(page: Page, previous: str = "", timeout: float = 180) -> str:
    """The full URL in the sealed card once it is there (and differs from `previous`)."""
    expr = ("(() => { const e = document.querySelector('[data-testid=\"sealed-link\"]'); const v = e && e.value; "
            f"return v && v.startsWith('http') && v !== {json.dumps(previous)} ? v : ''; }})()")
    return page.wait(expr, timeout)


def banner(page: Page) -> str | None:
    """The error banner's code, if one is showing."""
    return page.eval("document.querySelector('[data-testid=\"error-banner\"]')?.dataset.code ?? null")


def lock_text(page: Page, text: str) -> None:
    """Type a note into the drop widget and lock it (on /send the page then asks for the address)."""
    page.click("drop-write")
    page.wait_for("drop-textarea")
    page.fill("drop-textarea", text)
    page.click("drop-seal-text")


def seal_text(page: Page, text: str) -> str:
    lock_text(page, text)
    return wait_link(page)


def seal_file(page: Page, path: str) -> str:
    page.set_files("drop-input", [path])
    return wait_link(page)


def open_rules(page: Page) -> None:
    """Brand P-6 keeps the exit-rule controls in a Change panel; open it when it is closed."""
    if page.exists("card-change") and not page.eval(
            "(() => { const e = document.querySelector('[data-testid=\"who\"]'); return !!e && e.getClientRects().length > 0; })()"):
        page.click("card-change")
        page.wait_for("who")


def rule_version(page: Page) -> str:
    """The sealed card's data-rule counter: it changes every time a rule is applied."""
    return page.eval("document.querySelector('.md-card')?.dataset.rule ?? ''")


def set_rules(page: Page, who: str | None = None, when: str | None = None, views: int | None = None,
              expiry: str | None = None, password: str | None = None, password_mode: str | None = None) -> str:
    """Change the exit rule of the sealed item and return its link: the same link when only the count
    or the expiry changed (spec §5.4 tightens it in place), a new one for a password."""
    before = rule_version(page)
    open_rules(page)
    if who:
        page.choose("who", who)
    if password_mode:
        page.choose("password-mode", password_mode)
    if password is not None:
        page.fill("password-input", password)
    if when:
        page.choose("when", when)
    if views is not None:
        page.fill("views-input", str(views))
    if expiry is not None:
        if not page.exists("expiry-preset", expiry) and page.eval(
                "document.querySelector('[data-testid=\"expiry-preset\"]')?.tagName") != "SELECT":
            raise Failed(f"no expiry preset {expiry}")
        page.choose("expiry-preset", expiry)
    page.click("apply-rules")
    page.wait(f"(document.querySelector('.md-card')?.dataset.rule ?? '') !== {json.dumps(before)}", 60)
    return wait_link(page)


def open_link(page: Page, url: str, password: str | None = None, open_it: bool = True) -> str:
    """Open a link in the viewer and return the final view-root state."""
    page.goto(url)
    state = page.wait_state("view-root", VIEW_ASK, 90)
    if state == "password":
        if password is None:
            return state
        before = page.text("view-root")
        page.fill("view-password", password)
        page.click("view-password-submit")
        # A wrong password keeps the state and says so, with the tries left ("That's not it. {n} tries
        # left…", 11-brand §10.6), so the text changes on every wrong attempt.
        state = page.wait("(() => { const r = document.querySelector('[data-testid=\"view-root\"]');"
                          " const s = r?.dataset.state; const t = r?.textContent || '';"
                          f" const wrong = /not it/i.test(t) && t !== {json.dumps(before)};"
                          " return s !== 'password' ? s : (wrong ? 'password:wrong' : ''); })()", 90)
        if state.startswith("password"):
            return state
    if state == "ready" and open_it:
        page.click("view-open")
        state = page.wait_state("view-root", VIEW_END, 180)
    return state


def share_id(url: str) -> str:
    return urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]


def fragment(url: str) -> str:
    return urllib.parse.urlsplit(url).fragment


def no_horizontal_scroll(page: Page) -> bool:
    return bool(page.eval("document.scrollingElement.scrollWidth <= window.innerWidth"))
