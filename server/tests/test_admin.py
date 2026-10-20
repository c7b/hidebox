# SPDX-License-Identifier: MIT
"""mutis-admin (spec §15.7) and judge passes (brand patch P-12), driven through the CLI entry point."""
import calendar
import contextlib
import io
import json
import logging
import time
import unittest
from pathlib import Path
from unittest import mock

from harness import ORIGIN, Stack
from mutis import admin, auth, budgets, codec, config, db, jobs
from mutis.fake_chain import fake_keys

FIXTURE = Path(__file__).with_name("fixtures") / "schema-v1.sql"


def toml(raw: dict, prefix: str = "") -> str:
    """Enough TOML for our config: scalars, flat lists and nested tables."""
    def value(v):
        return json.dumps(v) if not isinstance(v, bool) else str(v).lower()

    lines, tables = [], []
    for key, v in raw.items():
        if isinstance(v, dict):
            tables.append((key, v))
        else:
            lines.append(f"{key} = {value(v)}")
    out = "\n".join(lines) + "\n"
    for key, v in tables:
        out += f"\n[{prefix}{key}]\n" + toml(v, f"{prefix}{key}.")
    return out


class Admin(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.path = self.s.tmp / "mutis.toml"
        self.path.write_text(toml(self.s.cfg.raw))

    def tearDown(self):
        self.s.close()
        logging.getLogger("mutis").handlers.clear()      # admin.main() attached the stderr handler

    def run_admin(self, *args) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admin.main(["--config", str(self.path), *args])
        return out.getvalue()

    def one_migration_behind(self):
        """A deployment whose database is one migration behind: the deployed schema-1 fixture through every
        migration but the newest. Returns its config file and its backup folder."""
        raw = dict(self.s.cfg.raw, data_dir=str(self.s.tmp / "behind"))
        path = self.s.tmp / "behind.toml"
        path.write_text(toml(raw))
        db_path = config.from_dict(raw).db_path
        db_path.parent.mkdir(parents=True)
        conn = db.connect(db_path)
        with db.tx(conn):
            for statement in db._statements(FIXTURE.read_text()):
                conn.execute(statement)
            db.set_meta(conn, "schema_version", "1")
        conn.close()
        older = self.s.tmp / "older-migrations"
        older.mkdir()
        for number, file in db._migration_files(db.MIGRATIONS):
            if number < db.SCHEMA_VERSION:
                (older / file.name).write_text(file.read_text())
        self.assertEqual(db.migrate(db_path, older), db.SCHEMA_VERSION - 1)
        return path, Path(raw["data_dir"]) / "backup"

    def test_migrate_check_reports_pending_without_changing(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_admin("migrate", "--check")                 # the test stack's database is current
        self.assertEqual(caught.exception.code, 0)
        self.path, backups = self.one_migration_behind()
        with self.assertRaises(SystemExit) as caught:
            self.run_admin("migrate", "--check")
        self.assertEqual(caught.exception.code, 3)
        self.assertFalse(backups.exists())                       # a check changes nothing and backs nothing up
        self.assertEqual(db.version(config.from_dict(dict(self.s.cfg.raw, data_dir=str(self.s.tmp / "behind"))).db_path),
                         db.SCHEMA_VERSION - 1)

    def test_check_config_and_migrate(self):
        self.assertEqual(self.run_admin("check-config").strip(), "ok")
        backups = self.s.cfg.data_dir / "backup"
        self.assertEqual(self.run_admin("migrate").strip(), f"schema version {db.SCHEMA_VERSION}")
        self.assertFalse(backups.exists())                   # nothing pending: no copy
        self.path, backups = self.one_migration_behind()
        self.assertIn(f"schema version {db.SCHEMA_VERSION} (backup: ", self.run_admin("migrate"))
        copy = next(backups.glob("pre-migrate-*.sqlite3"))
        self.assertEqual(copy.stat().st_mode & 0o777, 0o600)
        self.assertEqual(db.version(copy), db.SCHEMA_VERSION - 1)

    def test_takedown_share_item_drop(self):
        s = self.s
        item = s.upload(1 << 20)
        link = s.share(item)
        s.request("POST", "/api/v1/abuse", {"link": f"{ORIGIN}/s/{link['share_id']}", "category": "malware",
                                            "details": "dropper", "pow": s.solve("report")})
        self.assertIn("removed", self.run_admin("takedown", "share", link["share_id"], "--note", "malware"))
        status, _, body = s.request("GET", f"/api/v1/s/{link['share_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "removed"))
        self.assertFalse(s.app.blobs.exists(item["item_id"]))
        report = s.conn.execute("SELECT state, action_note FROM abuse_reports").fetchone()
        self.assertEqual(tuple(report), ("actioned", "malware"))
        self.assertIn(item["item_id"], self.run_admin("reports"))
        drop = s.drop()
        with db.tx(s.conn):                     # a delivery to it still waiting in the queue
            queued = jobs.enqueue(s.conn, "courier", "public", {"address": drop["keys"]["address"], "memo": "m",
                                                                "drop_id": drop["drop_id"]}, s.now + 30, s.now)
        self.run_admin("takedown", "drop", drop["drop_id"])
        job = s.conn.execute("SELECT state, payload, error FROM jobs WHERE id = ?", (queued,)).fetchone()
        self.assertEqual(tuple(job), ("failed", None, "drop_removed"))   # security-audit-1
        status, _, body = s.request("GET", f"/api/v1/drops/{drop['drop_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "removed"))
        with self.assertRaises(SystemExit):
            self.run_admin("takedown", "item", "Q" * 22)
        with self.assertRaises(SystemExit) as gone:          # an id that starts with '-' goes after `--`
            self.run_admin("takedown", "item", "--note", "x", "--", "-" + "Q" * 21)
        self.assertEqual(gone.exception.code, 1)              # "not found", not an argument error

    def test_reports_show_a_reporters_text_inert(self):
        """security-audit-1: an anonymous report can't add rows to `mutis-admin reports` or send controls to
        the operator's terminal; the contact field is one line."""
        s = self.s
        link = s.share(s.upload(1000))
        url = f"{ORIGIN}/s/{link['share_id']}"
        forged = f"rep_forged0000000000  2026-10-11 11:00  new       csam        share {link['share_id']}  key=yes"
        status, _, body = s.request("POST", "/api/v1/abuse", {"link": url, "category": "other", "details": "x",
                                                              "contact": "a@b.example\n" + forged,
                                                              "pow": s.solve("report")})
        self.assertEqual((status, body["error"]["details"]["field"]), (422, "contact"))
        details = "\u009b1A\u009b2K hidden \u202eevil\u202c \u007f\n" + forged
        status, _, _ = s.request("POST", "/api/v1/abuse", {"link": url, "category": "other", "details": details,
                                                           "contact": "a@b.example", "pow": s.solve("report")})
        self.assertEqual(status, 201)
        out = self.run_admin("reports")
        rows = s.conn.execute("SELECT COUNT(*) FROM abuse_reports").fetchone()[0]
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("rep_")), rows)
        self.assertFalse([c for c in out if not (c.isprintable() or c == "\n")])
        self.assertIn("\\x9b1A", out)
        self.assertIn("    | rep_forged0000000000", out)

    def test_freeze_feature_budget_unfreeze(self):
        s = self.s
        self.run_admin("freeze", "all")
        self.assertEqual(s.start_upload(1000)[0], 503)
        self.run_admin("freeze", "none")
        self.assertEqual(s.start_upload(1000)[0], 201)
        self.run_admin("feature", "drops", "off")
        s.app._features = (0.0, {})
        status, _, body = s.request("POST", "/api/v1/drops", {})
        self.assertEqual((status, body["error"]["code"]), (503, "feature_disabled"))
        self.run_admin("feature", "drops", "clear")
        s.app._features = (0.0, {})
        self.assertIn("courier   public", self.run_admin("budget", "set", "courier", "public", "7"))
        self.assertIn("/ 7", self.run_admin("budget", "show"))
        with db.tx(s.conn):
            db.set_meta(s.conn, "credit_freeze", "1")
            db.set_meta(s.conn, "reconcile_mismatch", "1")
        self.run_admin("unfreeze-credits")
        self.assertEqual((s.meta("credit_freeze"), s.meta("reconcile_mismatch")), (None, None))
        self.run_admin("canary-now")
        self.run_admin("seal-now")
        self.assertEqual(db.get_meta_json(s.conn, "force"), {"canary": True, "seal": True})

    def test_release_pack(self):
        s = self.s
        locker, other = s.register(), s.register()
        until = codec.now() + 30 * 86400
        with db.tx(s.conn):
            s.conn.execute("UPDATE identities SET paid_bytes = ?, paid_until = ?", (2 << 30, until))
        paid = lambda: s.conn.execute("SELECT id, paid_bytes FROM identities WHERE paid_until > ? ORDER BY id",
                                      (codec.now(),)).fetchall()
        self.assertEqual(len(paid()), 2)
        self.assertEqual(self.run_admin("release-pack", "--", locker["id"]).strip(), "released")
        self.assertEqual([tuple(r) for r in paid()], [(other["id"], 2 << 30)])     # only that locker's
        with self.assertRaises(SystemExit):                                       # nothing left to end
            self.run_admin("release-pack", "--", locker["id"])

    def test_judge_pass(self):
        s = self.s
        code = self.run_admin("judge-pass", "new", "--uses", "2", "--pow-skips", "3").strip()
        self.assertRegex(code, r"^judge-[0-9a-hjkmnp-tv-z]{24}$")
        judge = {"X-Mutis-Judge": code}
        drop_body = {"address": s.receiver["address"], "tag": codec.b64u(b"\0" * 16), "label": "",
                     "manage_verifier": codec.b64u(b"\0" * 32)}
        for _ in range(3):                                   # each stands in for a PoW, not for a send
            status, _, resp = s.request("POST", "/api/v1/drops", drop_body, headers=judge)
            self.assertEqual(status, 201, resp)
        status, _, resp = s.request("POST", "/api/v1/drops", drop_body, headers=judge)
        self.assertEqual((status, resp["error"]["details"]), (403, {"judge": "invalid"}))   # review L5: skips run out
        drop = s.drop()
        body = {"to": "drop", "drop_id": drop["drop_id"], "kind": 3, "blob": codec.b64u(b"\0" * 125)}
        with db.tx(s.conn):
            budgets.set_override(s.conn, "courier", "evidence", 0, s.now)
        status, _, resp = s.request("POST", "/api/v1/courier", body, headers=judge)
        self.assertEqual((status, resp["error"]["code"]), (429, "budget_exhausted"))
        uses = s.conn.execute("SELECT uses_left FROM judge_passes").fetchone()[0]
        self.assertEqual(uses, 2)                            # a refused send keeps its use
        with db.tx(s.conn):
            db.del_meta(s.conn, "budget_overrides")
        for _ in range(2):
            status, _, resp = s.request("POST", "/api/v1/courier", body, headers={"X-Mutis-Judge": code.upper()})
            self.assertEqual(status, 202)
            slice_ = s.conn.execute("SELECT slice FROM jobs WHERE id = ?", (resp["job_id"],)).fetchone()[0]
            self.assertEqual(slice_, "evidence")
        status, _, resp = s.request("POST", "/api/v1/courier", body, headers={"X-Mutis-Judge": code})
        self.assertEqual((status, resp["error"]["details"]), (403, {"judge": "invalid"}))
        status, _, resp = s.request("POST", "/api/v1/courier", body)
        self.assertEqual(status, 428)

    def test_a_judge_pass_lifts_the_network_limits_of_grants_and_demo_payments(self):
        """App-core review M1: two judges behind one address each get a sponsor grant and a demo payment."""
        s = self.s
        self.run_admin("feature", "sponsor", "on")
        s.app._features = (0.0, {})
        with db.tx(s.conn):
            db.set_meta(s.conn, "receiver_address", s.receiver["address"])
        judge = {"X-Mutis-Judge": self.run_admin("judge-pass", "new", "--uses", "4").strip()}
        ip = "203.0.113.7"
        for _ in range(2):
            locker = s.register(ip=ip)
            status, _, resp = s.request("POST", "/api/v1/sponsor", {"wallet_address": fake_keys()["address"]},
                                        headers={**locker["auth"], **judge}, ip=ip)
            self.assertEqual(status, 202, resp)
            inv = s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers={**locker["auth"], **judge}, ip=ip)[2]
            status, _, resp = s.request("POST", f"/api/v1/invoices/{inv['invoice_id']}/demo-pay", {},
                                        headers={**locker["auth"], **judge}, ip=ip)
            self.assertEqual(status, 202, resp)
        statuses = []
        for _ in range(3):                                   # without a pass: two grants per /64 a day
            locker = s.register(ip=ip)
            statuses.append(s.request("POST", "/api/v1/sponsor", {"wallet_address": fake_keys()["address"],
                                                                 "pow": s.solve("sponsor", ip)},
                                      headers=locker["auth"], ip=ip)[0])
        self.assertEqual(statuses, [202, 202, 429])

    def test_judge_pass_expires(self):
        s = self.s
        code = self.run_admin("judge-pass", "new").strip()
        with db.tx(s.conn):
            s.conn.execute("UPDATE judge_passes SET created_at = ?", (s.now - auth.JUDGE_PASS_DAYS * 86400,))
        status, _, resp = s.request("POST", "/api/v1/drops", {"address": s.receiver["address"],
                                                              "tag": codec.b64u(b"\0" * 16), "label": "",
                                                              "manage_verifier": codec.b64u(b"\0" * 32)},
                                    headers={"X-Mutis-Judge": code})
        self.assertEqual((status, resp["error"]["details"]), (403, {"judge": "invalid"}))

    def test_judge_pass_extend(self):
        """The same passes, uses kept, valid through the day named; codes come on stdin; unknown codes change
        nothing; a pass already valid longer is never cut short; the output never shows a code."""
        s = self.s
        first, second = (self.run_admin("judge-pass", "new").strip() for _ in range(2))
        with db.tx(s.conn):
            s.conn.execute("UPDATE judge_passes SET created_at = ?, uses_left = 3", (s.now - 29 * 86400,))
        until = time.strftime("%Y-%m-%d", time.gmtime(s.now + 60 * 86400))
        ends = calendar.timegm(time.strptime(until, "%Y-%m-%d")) + 86400

        def extend(codes, day=until):
            with mock.patch("sys.stdin", io.StringIO(codes)):
                return self.run_admin("judge-pass", "extend", "--until", day)

        with self.assertRaises(SystemExit):
            extend(f"{first}\njudge-{'0' * 24}\n")
        self.assertFalse(auth.judge_pass_live(s.conn, first, s.now + 2 * 86400))   # nothing changed
        out = extend(f"# the judges' passes\n{first}\n\n{second.upper()}\n")
        self.assertNotIn(first, out)
        self.assertNotIn(second.lower(), out.lower())
        self.assertIn("2 passes: valid through", out)
        for code in (first, second):
            self.assertTrue(auth.judge_pass_live(s.conn, code, ends - 1))
            self.assertFalse(auth.judge_pass_live(s.conn, code, ends))
        self.assertEqual([r[0] for r in s.conn.execute("SELECT uses_left FROM judge_passes")], [3, 3])
        extend(f"{first}\n", time.strftime("%Y-%m-%d", time.gmtime(s.now + 40 * 86400)))   # earlier: kept as it was
        self.assertTrue(auth.judge_pass_live(s.conn, first, ends - 1))

    def test_budget_overrides_only_lower(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            table = self.run_admin("budget", "set", "courier", "evidence", "100000")
        self.assertIn("can only lower", out.getvalue())
        self.assertIn("courier   evidence            0 / 150", table)

    def test_e2e_forged_payment_is_never_credited(self):
        """E-14 (t/402): a forged 'proven' row for a UTXO that doesn't exist stays uncredited and shows up."""
        s = Stack(chain=True)
        try:
            path = s.tmp / "mutis.toml"
            path.write_text(toml(s.cfg.raw))
            s.now = codec.now()                 # the admin command stamps the row with the real clock, so the
            s.worker.setup()                    # heartbeat, the session and the invoice are made on it too
            db.set_meta(s.conn, "chain_heartbeat", str(s.now))
            locker = s.register()
            inv = s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=locker["auth"])[2]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                admin.main(["--config", str(path), "e2e-forge-payment", inv["invoice_id"]])
            for _ in range(3):
                s.now += 400
                s.worker.tick()
            got = s.request("GET", f"/api/v1/invoices/{inv['invoice_id']}", headers=locker["auth"])[2]
            self.assertNotEqual(got["status"], "credited")
            self.assertEqual(db.get_meta_json(s.conn, "chain_status")["payments_unconfirmed"], 1)
        finally:
            s.close()

    def test_fixture_sanitizer(self):
        raw = {"address": "otl_esm_1abc", "component_address": "component_" + "ab" * 32, "value": "1000",
               "nested": [{"id": "cd" * 32, "token": "eyJhbGciOi"}], "name": "sponsor"}
        clean = admin._sanitize(raw, {})
        self.assertEqual(clean["value"], "1000")
        self.assertEqual(clean["name"], "sponsor")
        self.assertTrue(all(v.startswith("<redacted-") for v in (clean["address"], clean["component_address"],
                                                                 clean["nested"][0]["id"], clean["nested"][0]["token"])))


if __name__ == "__main__":
    unittest.main()
