# SPDX-License-Identifier: MIT
"""mutis-admin (spec §15.7) and judge passes (brand patch P-12), driven through the CLI entry point."""
import contextlib
import io
import json
import logging
import unittest

from harness import ORIGIN, Stack
from mutis import admin, auth, budgets, codec, db


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

    def test_check_config_and_migrate(self):
        self.assertEqual(self.run_admin("check-config").strip(), "ok")
        self.assertIn(f"schema version {db.SCHEMA_VERSION}", self.run_admin("migrate"))
        self.assertTrue(any((self.s.cfg.data_dir / "backup").glob("pre-migrate-*.sqlite3")))

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
        self.run_admin("takedown", "drop", drop["drop_id"])
        status, _, body = s.request("GET", f"/api/v1/drops/{drop['drop_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "removed"))
        with self.assertRaises(SystemExit):
            self.run_admin("takedown", "item", "Q" * 22)

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
        self.run_admin("unfreeze-credits")
        self.assertIsNone(s.meta("credit_freeze"))
        self.run_admin("canary-now")
        self.run_admin("seal-now")
        self.assertEqual(db.get_meta_json(s.conn, "force"), {"canary": True, "seal": True})

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
            s.worker.setup()
            locker = s.register()
            inv = s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=locker["auth"])[2]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                admin.main(["--config", str(path), "e2e-forge-payment", inv["invoice_id"]])
            s.now = codec.now()                 # the admin command stamps the row with the real clock
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
