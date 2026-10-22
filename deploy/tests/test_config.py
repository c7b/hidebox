# SPDX-License-Identifier: MIT
"""Static checks of the deploy configuration: the TOML example against the server's config schema,
the Caddyfile against spec §14.2 (verbatim, from tests/e2e/headers_spec.py), and the systemd units."""
import configparser
import fnmatch
import json
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
# Whole lines: a unit must say exactly this (a substring would accept NoExecPaths=/tmp-only or a capability added).
HARDENING = ("NoNewPrivileges=yes", "ProtectSystem=strict", "PrivateTmp=yes", "PrivateDevices=yes",
             "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectKernelLogs=yes", "ProtectControlGroups=yes",
             "ProtectClock=yes", "ProtectHostname=yes", "RestrictNamespaces=yes", "RestrictRealtime=yes",
             "RestrictSUIDSGID=yes", "LockPersonality=yes", "SystemCallFilter=@system-service",
             "SystemCallFilter=~@privileged @resources", "SystemCallArchitectures=native", "CapabilityBoundingSet=",
             "ProtectProc=invisible", "RemoveIPC=yes")
# walletd is Tari's binary: its own allocator and runtime, so only the privileged syscalls are filtered.
HARDENING_WALLETD = tuple("SystemCallFilter=~@privileged" if line.startswith("SystemCallFilter=~") else line
                          for line in HARDENING)
# docs/review/upload-safety-1.md: what a unit can write is never executable in its view.
PRIVATE_WRITABLE = ("/tmp", "/var/tmp", "/dev/shm")
DATA = "/srv/mutis/data"


def lines_of(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines()}


def values(path: Path, key: str) -> list[str]:
    """Every value of `key` in a unit (configparser keeps only the last of repeated keys)."""
    return [line.split("=", 1)[1] for line in path.read_text().splitlines() if line.startswith(key + "=")]


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
        self.assertNotIn("https://mutis.sh", cfg["memo_origins"])   # an unregistered domain


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

    def test_the_loops_preview_is_gone(self):
        """/v2, the home with the product loops (docs/review/home-v2.md), left with its loops (docs/review/perf-1.md): no
        route serves it, /v2 and /v2/ answer 301 to / (REDIRECTS, compared above). The stills and the 404 art keep their
        plain names under /site/media/, kept a day, ahead of the catch-all."""
        self.assertNotIn("@preview ", self.text)
        self.assertNotIn("/v2/index.html", self.text)
        self.assertEqual(re.search(r'(?m)^\tredir @old_loops "([^"]+)" 301$', self.text).group(1), "/")
        self.assertEqual(headers_spec.REDIRECTS["/v2"], "/")
        self.assertNotIn("/v2", headers_spec.ROUTES)
        self.assertFalse([path for path in headers_spec.MEDIA if "/motion/" in path])
        self.assertEqual(re.search(r"(?m)^\t@media path (.+)$", self.text).group(1), "/site/media/*")
        media = re.search(r"(?ms)^\thandle @media \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn(f'header Cache-Control "{headers_spec.MEDIA_CACHE["cache-control"]}"', media)
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        self.assertLess(site.index("handle @media"), re.search(r"(?m)^\thandle \{$", site).start(), "before the catch-all")

    def test_the_v3_preview_became_the_home(self):
        """/v3 (docs/review/home-v3.md) became the home (docs/review/promote-v3.md): no route serves it any more, /v3 and
        /v3/ answer 301 to / (headers_spec.REDIRECTS, which the test above compares), and its stills, now the home's,
        stay under /site/media/ (kept a day, the @media route ahead of the catch-all)."""
        self.assertNotIn("@preview3", self.text)
        self.assertNotIn("/v3/index.html", self.text)
        self.assertEqual(re.search(r'(?m)^\tredir @old_preview "([^"]+)" 301$', self.text).group(1), "/")
        self.assertEqual(sorted(re.search(r"(?m)^\t@old_preview path (.+)$", self.text).group(1).split()), ["/v3", "/v3/"])
        self.assertEqual(headers_spec.REDIRECTS["/v3"], "/")
        self.assertNotIn("/v3", headers_spec.ROUTES)
        self.assertTrue(any(path.startswith("/site/media/v3/") for path in headers_spec.MEDIA))

    def test_previews_and_crawlers(self):
        """docs/review/seo-1.md: the share cards and icons (headers_spec.CARDS) are kept a day and loadable from any
        origin; robots.txt and the sitemap (CRAWL) have their types and are kept an hour; the API and the drive's
        files under /app/ are noindex like the app's routes. Each route sits before the catch-all."""
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        catch_all = re.search(r"(?m)^\thandle \{$", site).start()
        cards = re.search(r"(?m)^\t@cards path (.+)$", self.text).group(1).split()
        self.assertEqual(sorted(cards), sorted(headers_spec.CARDS))
        manifest = json.loads((ROOT / "web" / "site" / "static" / "manifest.webmanifest").read_text())
        self.assertLessEqual({icon["src"] for icon in manifest["icons"]}, set(headers_spec.CARDS))   # every app icon too
        body = re.search(r"(?ms)^\thandle @cards \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn("import site_csp", body)
        for name, value in headers_spec.CARD_HEADERS.items():
            self.assertTrue(re.search(rf'(?im)^\s*header {re.escape(name)} "{re.escape(value)}"$', body), name)
        crawl = re.search(r"(?m)^\t@crawl path (.+)$", self.text).group(1).split()
        self.assertEqual(sorted(crawl), sorted(headers_spec.CRAWL))
        body = re.search(r"(?ms)^\thandle @crawl \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn(f'header Cache-Control "{headers_spec.CRAWL_CACHE["cache-control"]}"', body)
        for path, ctype in headers_spec.CRAWL.items():
            matcher = re.search(rf"(?m)^\t@(\w+) path {re.escape(path)}$", self.text).group(1)
            self.assertIn(f'header @{matcher} Content-Type "{ctype}"', self.text)
        for route in ("@cards", "@crawl"):
            self.assertLess(site.index(f"handle {route}"), catch_all, route)
        encode = re.search(r"(?ms)^\tencode \{\n(.*?)^\t\}", self.text).group(1)
        patterns = re.findall(r"header Content-Type (\S+)", encode)
        for path, ctype in headers_spec.CRAWL.items():
            self.assertTrue(any(fnmatch.fnmatchcase(ctype, p) for p in patterns), f"{path} ({ctype}) is compressed")
        noindex = f'header X-Robots-Tag "{headers_spec.NOINDEX["x-robots-tag"]}"'
        for route in ("@api", "@appfiles", "@viewer", "@paylink", "@droplink", "@approute", "@drive"):
            body = re.search(rf"(?ms)^\thandle {route} \{{\n(.*?)^\t\}}", self.text).group(1)
            self.assertIn(noindex, body, route)
        for path in headers_spec.INDEXABLE:
            self.assertNotIn("x-robots-tag", headers_spec.ROUTES[path][1], path)

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
                self.assertRegex(body, r"import (revalidate|immutable)|Cache-Control", matcher or "default handle")
        # A year, immutable, only for the fingerprinted names (test below): the plain ones (fonts, stills, icons) carry
        # no version.
        self.assertEqual(len(re.findall(r'Cache-Control "[^"]*immutable', self.text)), 1)
        self.assertEqual(sorted(m for m, body in handles if "import immutable" in body), [" @hashed", " @hashed_app"])
        errors = site.split("handle_errors {", 1)[1]
        self.assertRegex(errors, r"^\s*root \* /srv/mutis/app/current/dist", "error pages come from the release")
        self.assertIn('header Cache-Control "no-store"', errors)
        self.assertRegex(self.text, r"(?s)http://\{\$MUTIS_HOST\} \{\s*header -Server\s*redir https://")
        self.assertIn("buffer_requests", self.text)

    def test_fingerprinted_files_are_kept_a_year(self):
        """docs/review/perf-1.md: names with a hash of their bytes (tools/assets.py, whose pattern the matcher repeats) are
        kept a year, immutable, by two routes ahead of every other file route: /app/ and /vendor/ with the app policy and
        noindex, everything else with the site policy. Every route that serves text serves the precompressed copies."""
        sys.path.insert(0, str(ROOT / "tools"))
        import assets
        site = self.text.split("\n{$MUTIS_HOST} {", 1)[1]
        self.assertRegex(self.text, r'(?s)\(immutable\) \{\s*header Cache-Control "%s"\s*\}' % re.escape(headers_spec.IMMUTABLE["cache-control"]))
        app = re.search(r"(?ms)^\t@hashed_app \{\n\t\tpath (.+?)\n\t\tpath_regexp (\S+)\n\t\}", site)
        self.assertEqual(app.group(1).split(), ["/app/*", "/vendor/*"])
        self.assertEqual(app.group(2), assets.HASHED_NAME.pattern)
        self.assertEqual(re.search(r"(?m)^\t@hashed path_regexp (\S+)$", site).group(1), assets.HASHED_NAME.pattern)
        bodies = {m: b for m, b in re.findall(r"(?ms)^\thandle (@\w+) \{\n(.*?)^\t\}", site)}
        self.assertEqual(bodies["@hashed_app"].split(), ["import", "app_csp", "import", "immutable", "header", "X-Robots-Tag",
                                                         '"noindex,', 'nofollow"', "import", "files"])
        self.assertEqual(bodies["@hashed"].split(), ["import", "site_csp", "import", "immutable", "import", "files"])
        order = [m for m in re.findall(r"(?m)^\thandle (@\w+) \{", site)]
        self.assertEqual(order[:4], ["@api", "@notread", "@hashed_app", "@hashed"], "ahead of every file route")
        self.assertRegex(self.text, r"(?s)\(files\) \{\s*file_server \{\s*precompressed br gzip\s*\}\s*\}")
        for matcher in ("@viewer", "@paylink", "@droplink", "@approute", "@drive", "@appfiles", "@cards", "@crawl", "@home"):
            self.assertIn("import files", bodies[matcher], matcher)
        self.assertIn("import files", re.search(r"(?ms)^\thandle \{\n(.*?)^\t\}", site).group(1), "the catch-all")
        self.assertRegex(site.split("handle_errors {", 1)[1], r"(?s)rewrite \* /404\.html\s*file_server \{\s*status 404\s*precompressed br gzip")

    def test_every_api_answer_carries_the_sandbox_policy(self):
        """docs/review/upload-safety-1.md: the API's JSON and the stored bytes it serves are data, never a page."""
        self.assertIn(f'header Content-Security-Policy "{headers_spec.API_CSP}"', self.text)
        self.assertTrue(headers_spec.API_CSP.endswith("; sandbox"))
        api = re.search(r"(?ms)^\thandle @api \{\n(.*?)^\t\}", self.text).group(1)
        self.assertIn("import api_csp", api)
        self.assertNotIn("import site_csp", api)
        self.assertNotIn("import app_csp", api)
        self.assertIn("header_down -X-Content-Type-Options", api, "Caddy's nosniff, sent once")
        self.assertNotRegex(self.text, r"(?m)^\s*root \* /srv/mutis/data", "Caddy never serves the data directory")

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
                have = lines_of(path)
                for line in (HARDENING_WALLETD if path.name == "walletd.service" else HARDENING):
                    self.assertIn(line, have)
                self.assertEqual(values(path, "CapabilityBoundingSet"), [""])

    def test_nothing_a_unit_can_write_is_executable(self):
        """NoExecPaths names the private /tmp, /var/tmp and /dev/shm and every path the unit may write; no ExecPaths
        (it would lift ProtectSystem's read-only flag from what it names); and no unit grants a capability back."""
        for path in [*UNITS.glob("*.service"), UNITS / "caddy.service.d" / "mutis.conf"]:
            with self.subTest(path.name):
                noexec = " ".join(values(path, "NoExecPaths")).split()
                writable = " ".join(values(path, "ReadWritePaths") + values(path, "BindPaths")).split()
                self.assertTrue(noexec, "no NoExecPaths")
                for place in (*PRIVATE_WRITABLE, *writable):
                    self.assertIn(place, noexec)
                self.assertNotIn("/", noexec)
                self.assertEqual(values(path, "ExecPaths"), [])
                self.assertEqual(values(path, "AmbientCapabilities"),
                                 ["CAP_NET_BIND_SERVICE"] if path.name == "mutis.conf" else [])

    def test_root_runs_only_the_backup_prune(self):
        """Claims review item 22: the one "+" (full privileges) step deletes root's database copies
        before the backup; no other unit escalates."""
        for path in UNITS.glob("*.service"):
            lines = [line for line in path.read_text().splitlines() if "=+" in line]
            expected = ["ExecStartPre=+/usr/bin/python3 -I /usr/local/lib/mutis/backup.py prune-root"] \
                if path.name == "mutis-backup.service" else []
            self.assertEqual(lines, expected, path.name)

    def test_units_that_use_the_data_directory_need_its_noexec_mount(self):
        """Every unit that reads the database or the blobs starts only once the noexec mount is up."""
        for path in UNITS.glob("*.service"):
            if "MUTIS_CONFIG" in path.read_text():
                self.assertEqual(unit(path.name)["Unit"].get("RequiresMountsFor"), DATA, path.name)

    def test_the_data_mount_is_noexec_nosuid_nodev(self):
        mount = unit("srv-mutis-data.mount")
        self.assertEqual((mount["Mount"]["What"], mount["Mount"]["Where"]), (DATA, DATA))
        self.assertEqual(set(mount["Mount"]["Options"].split(",")), {"bind", "noexec", "nosuid", "nodev"})
        self.assertEqual(mount["Install"]["WantedBy"], "local-fs.target")
        provision = (ROOT / "deploy" / "scripts" / "provision.sh").read_text()
        self.assertIn("systemctl enable --now srv-mutis-data.mount", provision)
        self.assertIn('"$DEPLOY"/systemd/*.mount', provision)
        check = (ROOT / "deploy" / "scripts" / "privilege-check.sh").read_text()
        self.assertIn("mounted noexec,nosuid,nodev", check)

    def test_the_status_directory_follows_no_symlink(self):
        """security-audit-1: Caddy serves /srv/mutis/status and mutis, drive and root write it; mounted
        nosymfollow, a link placed there is followed by no process (Caddy can't be made to publish its key)."""
        mount = unit("srv-mutis-status.mount")
        status = "/srv/mutis/status"
        self.assertEqual((mount["Mount"]["What"], mount["Mount"]["Where"]), (status, status))
        self.assertEqual(set(mount["Mount"]["Options"].split(",")), {"bind", "nosymfollow", "noexec", "nosuid", "nodev"})
        self.assertEqual(mount["Install"]["WantedBy"], "local-fs.target")
        provision = (ROOT / "deploy" / "scripts" / "provision.sh").read_text()
        self.assertIn("systemctl enable --now srv-mutis-status.mount", provision)
        self.assertRegex(provision, r"\ndata_mount\nstatus_mount\n")
        check = (ROOT / "deploy" / "scripts" / "privilege-check.sh").read_text()
        self.assertIn("mounted nosymfollow,noexec", check)
        self.assertIn("a link in /srv/mutis/status is not followed, even by root", check)

    def test_write_access_only_where_needed(self):
        rw = {name: unit(name)["Service"]["ReadWritePaths"].split() for name in
              ("mutis-api.service", "mutis-cleanup.service", "mutis-backup.service", "mutis-chain.service",
               "mutis-evidence.service")}
        self.assertEqual(rw["mutis-api.service"], [f"{DATA}/db", f"{DATA}/blobs"])
        self.assertEqual(rw["mutis-cleanup.service"], [f"{DATA}/db", f"{DATA}/blobs"])
        self.assertEqual(rw["mutis-backup.service"], [f"{DATA}/db", f"{DATA}/backup"])
        self.assertEqual(rw["mutis-chain.service"], [f"{DATA}/db", "/srv/mutis/status"])
        self.assertEqual(rw["mutis-evidence.service"], ["/srv/mutis/status", f"{DATA}/db"])
        walletd = unit("walletd.service")["Service"]
        self.assertIn("/srv/mutis", walletd["InaccessiblePaths"].split())
        self.assertIn("-/etc/mutis/secret.key", walletd["InaccessiblePaths"].split())

    def test_caddy_runs_in_a_sandbox(self):
        path = UNITS / "caddy.service.d" / "mutis.conf"
        have = lines_of(path)
        for line in HARDENING + ("ReadWritePaths=/var/lib/caddy", "MemoryDenyWriteExecute=yes", "ProtectHome=yes"):
            if line != "CapabilityBoundingSet=":
                self.assertIn(line, have)
        self.assertEqual(values(path, "CapabilityBoundingSet"), ["CAP_NET_BIND_SERVICE"])

    def test_kernel_settings(self):
        path = ROOT / "deploy" / "sysctl" / "90-mutis.conf"
        text = path.read_text()
        self.assertIn("SPDX-License-Identifier: MIT", text.splitlines()[0])
        settings = dict(line.replace(" ", "").split("=", 1) for line in text.splitlines() if re.match(r"^[a-z]", line))
        for key, value in {"kernel.kptr_restrict": "2", "kernel.yama.ptrace_scope": "1", "kernel.kexec_load_disabled": "1",
                           "kernel.unprivileged_bpf_disabled": "1", "dev.tty.ldisc_autoload": "0",
                           "kernel.io_uring_disabled": "2", "fs.protected_regular": "2", "net.ipv4.tcp_syncookies": "1",
                           "net.ipv4.conf.*.rp_filter": "1"}.items():
            self.assertEqual(settings.get(key), value, key)
        self.assertFalse(any("log_martians" in key for key in settings), "it would log source addresses")
        self.assertIn("/usr/lib/systemd/systemd-sysctl", (ROOT / "deploy" / "scripts" / "provision.sh").read_text())

    def test_jit_only_where_needed(self):
        self.assertEqual(unit("mutis-api.service")["Service"].get("MemoryDenyWriteExecute"), "yes")
        self.assertIsNone(unit("mutis-chain.service")["Service"].get("MemoryDenyWriteExecute"))
        self.assertIsNone(unit("walletd.service")["Service"].get("MemoryDenyWriteExecute"))
        for name in ("mutis-cleanup.service", "mutis-health.service", "mutis-backup.service", "mutis-backup-wallet.service",
                     "mutis-evidence.service"):
            self.assertEqual(unit(name)["Service"].get("MemoryDenyWriteExecute"), "yes", name)

    def test_walletd_password_never_on_the_command_line(self):
        svc = unit("walletd.service")["Service"]
        self.assertNotIn("keyring", svc["ExecStart"])
        self.assertTrue(svc["LoadCredential"].startswith("keyring-pass:/etc/mutis/credentials/"))
        self.assertNotIn("--override-keyring-password", (ROOT / "deploy" / "ootle" / "run-walletd.sh").read_text().split("set -euo")[1])

    def test_the_upgrade_drill_tries_walletd_under_its_unit_sandbox(self):
        """deploy/ootle/upgrade-drill.md §3 runs a new walletd on a copy of the wallet under walletd.service's own
        sandbox (its paths pointing at the copy) and with no network, so a directive the new version can't live
        with shows on the copy first; the copy holds keys, so nothing in the exit trap may fail before `rm -rf`."""
        import shlex
        drill = (ROOT / "deploy" / "ootle" / "upgrade-drill.md").read_text()
        start = drill.index("systemd-run --unit=walletd-drill")
        words = shlex.split(drill[start:drill.index("run-walletd.sh", start)].replace("\\\n", " "))
        props = {words[i + 1] for i, w in enumerate(words) if w == "-p"}
        service = (UNITS / "walletd.service").read_text().split("[Service]")[1].split("[Install]")[0]
        how = {"Type", "ExecStart", "Restart", "RestartSec", "TimeoutStopSec", "KillSignal", "StandardOutput",
               "StandardError", "SyslogIdentifier"}             # how the service runs, not its sandbox
        moved = {"RuntimeDirectory", "BindPaths", "NoExecPaths"}   # the same directive, at the copy's paths
        for line in (l.strip() for l in service.splitlines()):
            key = line.split("=", 1)[0]
            if not line or line.startswith("#") or key in how:
                continue
            if key in moved:
                self.assertTrue(any(p.startswith(key + "=") for p in props), f"the drill sets no {key}")
            else:
                self.assertIn(line, props, "the drill's walletd runs without this directive of walletd.service")
        self.assertIn("PrivateNetwork=yes", props)
        self.assertIn("""trap 'systemctl stop walletd-drill 2>/dev/null || true; rm -rf "$T"' EXIT""", drill)

    def test_every_timer_has_its_service(self):
        for timer in UNITS.glob("*.timer"):
            self.assertTrue((UNITS / timer.name.replace(".timer", ".service")).is_file(), timer.name)


if __name__ == "__main__":
    unittest.main()
