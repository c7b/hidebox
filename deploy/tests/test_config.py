# SPDX-License-Identifier: MIT
"""Static checks of the deploy configuration: the TOML example against the server's config schema,
the Caddyfile against spec §14.2 (verbatim, from tests/e2e/headers_spec.py), and the systemd units."""
import configparser
import re
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
sys.path.insert(0, str(ROOT / "server"))
import headers_spec  # noqa: E402

UNITS = ROOT / "deploy" / "systemd"
HARDENING = ("NoNewPrivileges=yes", "ProtectSystem=strict", "PrivateTmp=yes", "PrivateDevices=yes",
             "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectControlGroups=yes", "RestrictNamespaces=yes",
             "LockPersonality=yes", "SystemCallFilter=@system-service", "CapabilityBoundingSet=", "ProtectProc=invisible")


def unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    parser.optionxform = str
    parser.read_string((UNITS / name).read_text())
    return parser


class ConfigExampleTest(unittest.TestCase):
    def test_example_parses_with_the_server_config(self):
        try:
            from mutis import config
        except ImportError:
            self.skipTest("server/ is not in this checkout")
        with open(ROOT / "deploy" / "config" / "mutis.toml.example", "rb") as f:
            cfg = config.from_dict(tomllib.load(f))
        self.assertEqual(cfg.origin, "https://srv2052606.hstgr.cloud")
        self.assertNotIn("https://mutis.sh", cfg["memo_origins"])   # fifth pass: an unregistered domain


class CaddyfileTest(unittest.TestCase):
    text = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()

    def test_old_pages_answer_301_to_their_new_place(self):
        """14-ghost-design §17 step 4: the pages the ghost folded together redirect, with or without a
        trailing slash, exactly as tests/e2e/headers_spec.py REDIRECTS says (D-01 asks the live site)."""
        matchers = dict(re.findall(r"^\s*@(old_[a-z]+) path (.+)$", self.text, re.M))
        found = {}
        for name, target in re.findall(r'^\s*redir @(old_[a-z]+) "([^"]+)" 301$', self.text, re.M):
            paths = matchers[name].split()
            self.assertEqual(len(paths), 2, name)
            self.assertEqual(paths[1], paths[0] + "/", name)
            found[paths[0]] = target
        self.assertEqual(found, headers_spec.REDIRECTS)
        site = self.text[self.text.index("{$MUTIS_HOST} {"):]
        self.assertLess(site.index("import security_headers"), site.index("redir @old_"), "the redirects carry the security headers")

    def test_csp_and_headers_are_the_spec_text(self):
        self.assertIn(f'header Content-Security-Policy "{headers_spec.SITE_CSP}"', self.text)
        self.assertIn(f'header Content-Security-Policy "{headers_spec.APP_CSP}"', self.text)
        for name, value in headers_spec.COMMON.items():
            self.assertTrue(re.search(rf'^\s*{name}\s+"{re.escape(value)}"$', self.text, re.I | re.M), name)
        self.assertIn("header -Server", self.text)

    def test_the_home_page_gets_the_app_policy(self):
        home = re.search(r"(?m)^\t@home path (.+)$", self.text).group(1).split()
        self.assertEqual(sorted(home), ["/", "/index.html"])
        self.assertIs(headers_spec.ROUTES["/"][0], headers_spec.APP_CSP, "the drop widget runs on /")

    def test_the_preview_gets_the_app_policy_and_its_loops_a_day(self):
        """/v2 (docs/review/home-v2.md) carries the drop widget and plays video: the app policy (media-src 'self'),
        noindex as its page says; the loops under /site/media/ are kept a day, never immutable."""
        preview = re.search(r"(?m)^\t@preview path (.+)$", self.text).group(1).split()
        self.assertEqual(sorted(preview), ["/v2", "/v2/", "/v2/index.html"])
        body = re.search(r"(?ms)^\thandle @preview \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn("import app_csp", body)
        self.assertIn('header X-Robots-Tag "noindex"', body)
        self.assertIn("media-src 'self'", headers_spec.APP_CSP)
        for route in ("/v2", "/v2/"):
            self.assertIs(headers_spec.ROUTES[route][0], headers_spec.APP_CSP, route)
        self.assertEqual(re.search(r"(?m)^\t@media path (.+)$", self.text).group(1), "/site/media/*")
        media = re.search(r"(?ms)^\thandle @media \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn(f'header Cache-Control "{headers_spec.MEDIA_CACHE["cache-control"]}"', media)
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        catch_all = re.search(r"(?m)^\thandle \{$", site).start()
        self.assertLess(site.index("handle @preview"), catch_all, "before the catch-all")
        self.assertLess(site.index("handle @media"), catch_all, "before the catch-all")

    def test_the_v3_preview_gets_the_app_policy(self):
        """/v3 (docs/review/home-v3.md), v2 with stills: the drop widget again, so the app policy, noindex as its page
        says, ahead of the catch-all; its stills are under /site/media/, kept a day like the loops."""
        preview = re.search(r"(?m)^\t@preview3 path (.+)$", self.text).group(1).split()
        self.assertEqual(sorted(preview), ["/v3", "/v3/", "/v3/index.html"])
        body = re.search(r"(?ms)^\thandle @preview3 \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn("import app_csp", body)
        self.assertIn('header X-Robots-Tag "noindex"', body)
        self.assertIn("rewrite * /v3/index.html", body)
        for route in ("/v3", "/v3/"):
            self.assertIs(headers_spec.ROUTES[route][0], headers_spec.APP_CSP, route)
            self.assertEqual(headers_spec.ROUTES[route][1], {"x-robots-tag": "noindex"}, route)
        self.assertTrue(any(path.startswith("/site/media/v3/") for path in headers_spec.MEDIA))
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        catch_all = re.search(r"(?m)^\thandle \{$", site).start()
        self.assertLess(site.index("handle @preview3"), catch_all, "before the catch-all")

    def test_no_access_log_and_filtered_errors(self):
        site = self.text.split("{$MUTIS_HOST} {", 1)[1]
        self.assertNotRegex(site, r"(?m)^\s*log\b")
        for field in ("remote_ip", "client_ip", "remote_port", "host", "uri", "headers"):
            self.assertIn(f"request>{field} delete", self.text)
        self.assertIn("admin unix//run/caddy/admin.sock", self.text)


    def test_caching_and_error_pages(self):
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        handles = re.findall(r"(?ms)^\thandle( @\w+)? \{\n(.*?)^\t\}", site)
        self.assertGreaterEqual(len(handles), 8)
        for matcher, body in handles:
            if matcher.strip() == "@api":
                proxied = re.sub(r"(?ms)^\t\thandle @too_large \{.*?^\t\t\}", "", body)   # the 413 mirrors the API's no-store
                self.assertNotIn("Cache-Control", proxied, "the API sets its own Cache-Control (spec §6)")
            else:
                self.assertRegex(body, r"import revalidate|Cache-Control", matcher or "default handle")
        self.assertNotRegex(self.text, r'Cache-Control "[^"]*immutable', "font names carry no version")
        errors = site.split("handle_errors {", 1)[1]
        self.assertRegex(errors, r"^\s*root \* /srv/mutis/app/current/dist", "error pages come from the release")
        self.assertIn('header Cache-Control "no-store"', errors)
        self.assertRegex(self.text, r"(?s)http://\{\$MUTIS_HOST\} \{\s*header -Server\s*redir https://")
        self.assertIn("buffer_requests", self.text)

    def test_a_declared_body_over_the_limit_is_a_413_in_the_api_shape(self):
        """Claims review item 24: never a bare 502 for a 6 MB chunk."""
        api = re.search(r"(?ms)^\thandle @api \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn("max_size 5MB", api)
        self.assertRegex(api, r"@too_large expression .*Content-Length.* > 5242880")
        self.assertIn('respond `{"error":{"code":"too_large","message":"Request body too large.","details":{"max_bytes":5242880}}}` 413', api)
        self.assertLess(api.index("handle @too_large"), api.index("reverse_proxy"), "refused before the proxy reads it")

    def test_pages_and_files_take_only_get_and_head(self):
        """Security review: a TRACE or PUT on a page answered 200 with the page."""
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        self.assertRegex(site, r"(?s)@notread not method GET HEAD\s*handle @notread \{\s*import site_csp\s*header Allow \"GET, HEAD\"\s*header Cache-Control \"no-store\"\s*respond 405\s*\}")
        self.assertLess(site.index("handle @api"), site.index("handle @notread"), "the API keeps its own methods")
        self.assertLess(site.index("handle @notread"), site.index("handle @viewer"), "before every page route")

    def test_any_other_host_gets_a_421_with_the_headers(self):
        """Claims review item 23: no bare 200 and no redirect to a made-up Host, on either port."""
        self.assertRegex(self.text, r"(?s)\(misdirected\) \{\s*import security_headers\s*import site_csp\s*header Cache-Control \"no-store\"\s*respond 421\s*\}")
        for block in ("https://", "http://"):
            self.assertRegex(self.text, rf"(?m)^{re.escape(block)} \{{\n\timport misdirected\n\}}$", block)
        self.assertLess(self.text.index("\n{$MUTIS_HOST} {"), self.text.index("\nhttps:// {"), "after the site")


class PinnedWasmTest(unittest.TestCase):
    def test_every_copy_of_the_pinned_hash_agrees(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import build
        from mutis import config
        pinned = build.PINNED["ootle-wasm-0.46.0/ootle_wasm_bg.wasm"]
        sums = (ROOT / "web" / "app" / "vendor" / "ootle-wasm-0.46.0" / "SHA256SUMS").read_text()
        self.assertIn(f"{pinned}  ootle_wasm_bg.wasm", sums)
        self.assertEqual(config.PINNED_WASM_SHA256, pinned)
        for script in ("activate-release.sh", "init-keys.sh"):
            text = (ROOT / "deploy" / "scripts" / script).read_text()
            self.assertEqual(re.findall(r"(?m)^pinned=([0-9a-f]{64})", text), [pinned], script)


class UnitsTest(unittest.TestCase):
    def test_every_unit_is_licensed(self):
        for path in UNITS.rglob("*"):
            if path.is_file():
                self.assertIn("SPDX-License-Identifier: MIT", path.read_text().splitlines()[0], path.name)

    def test_services_are_hardened_and_never_root(self):
        for path in UNITS.glob("*.service"):
            with self.subTest(path.name):
                svc = unit(path.name)["Service"]
                self.assertIn(svc.get("User"), ("mutis", "drive"))
                text = path.read_text()
                for line in HARDENING:
                    self.assertIn(line, text)

    def test_root_runs_only_the_backup_prune(self):
        """Claims review item 22: the one "+" (full privileges) step deletes root's database copies
        before the backup; no other unit escalates."""
        for path in UNITS.glob("*.service"):
            lines = [line for line in path.read_text().splitlines() if "=+" in line]
            expected = ["ExecStartPre=+/usr/bin/python3 -I /usr/local/lib/mutis/backup.py prune-root"] \
                if path.name == "mutis-backup.service" else []
            self.assertEqual(lines, expected, path.name)

    def test_jit_only_where_needed(self):
        self.assertEqual(unit("mutis-api.service")["Service"].get("MemoryDenyWriteExecute"), "yes")
        self.assertIsNone(unit("mutis-chain.service")["Service"].get("MemoryDenyWriteExecute"))
        self.assertIsNone(unit("walletd.service")["Service"].get("MemoryDenyWriteExecute"))

    def test_walletd_password_never_on_the_command_line(self):
        svc = unit("walletd.service")["Service"]
        self.assertNotIn("keyring", svc["ExecStart"])
        self.assertTrue(svc["LoadCredential"].startswith("keyring-pass:/etc/mutis/credentials/"))
        self.assertNotIn("--override-keyring-password", (ROOT / "deploy" / "ootle" / "run-walletd.sh").read_text().split("set -euo")[1])

    def test_every_timer_has_its_service(self):
        for timer in UNITS.glob("*.timer"):
            self.assertTrue((UNITS / timer.name.replace(".timer", ".service")).is_file(), timer.name)


if __name__ == "__main__":
    unittest.main()
