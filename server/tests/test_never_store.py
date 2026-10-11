# SPDX-License-Identifier: MIT
"""S-05: never store. The schema has none of the forbidden columns, and no log line carries request data.

The log check runs the whole contract suite with every `mutis` log record and all of stderr captured,
then requires each line to match the only two formats logsafe can produce. A targeted flow with
known IP, ids, tokens and addresses also checks that none of those strings appears anywhere.
"""
import contextlib
import hashlib
import io
import logging
import os
import re
import unittest

import test_contract
from harness import Stack
from mutis import codec, db
from mutis.fake_chain import fake_keys

LINE = re.compile(r"^(INFO|WARNING|ERROR|CRITICAL) (route=[a-z_]+(\.[a-z_]+)* status=\d{3} ms=\d+|"
                  r"event=[a-z_]+\.[a-z_0-9]+( n=\d+)?)$")
FORBIDDEN_COLUMNS = {"email", "name", "ip", "ip_address", "remote_ip", "user_agent", "file_name", "filename", "mime",
                     "mime_type", "content_type", "public_key", "pubkey", "owner_pk", "view_pk", "seed", "password",
                     "plaintext", "plaintext_size", "recipient", "sender", "grant", "grantee", "locker_address"}


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


@contextlib.contextmanager
def captured():
    logger = logging.getLogger("mutis")
    handler, stderr = Capture(), io.StringIO()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with contextlib.redirect_stderr(stderr):
            yield handler, stderr
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


class Schema(unittest.TestCase):
    def test_forbidden_columns_absent(self):
        s = Stack()
        try:
            tables = [r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                                   "AND name NOT LIKE 'sqlite_%'")]
            addresses = []
            for table in tables:
                for col in s.conn.execute(f"PRAGMA table_info({table})"):
                    self.assertNotIn(col["name"], FORBIDDEN_COLUMNS, f"{table}.{col['name']}")
                    if "address" in col["name"]:
                        addresses.append(f"{table}.{col['name']}")
            self.assertEqual(sorted(addresses), ["drops.address", "invoices.address"])
            item_cols = {c["name"] for c in s.conn.execute("PRAGMA table_info(items)")}
            self.assertNotIn("drop_id", item_cols)          # which drop a file came from is never stored
        finally:
            s.close()


class Logs(unittest.TestCase):
    def test_contract_suite_logs_only_fixed_formats(self):
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_contract)
        with captured() as (handler, stderr):
            result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertGreater(len(handler.lines), 200)
        bad = [line for line in handler.lines if not LINE.match(line)]
        self.assertEqual(bad, [])
        noise = [line for line in stderr.getvalue().splitlines() if line.strip() and not LINE.match(line)
                 and "ResourceWarning" not in line and "tracemalloc" not in line and not line.startswith("  ")]
        self.assertEqual(noise, [])

    def test_known_values_never_logged(self):
        ip = "203.0.113.77"
        with captured() as (handler, stderr):
            s = Stack()
            try:
                locker = s.register(ip=ip)
                item = s.upload(300_000, ip=ip)
                link = s.share(item, max_views=2)
                s.request("POST", f"/api/v1/s/{link['share_id']}/peek", headers=link["access"], ip=ip)
                opened = s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"], ip=ip)[2]
                s.request("GET", f"/api/v1/blobs/{opened['ticket']}", ip=ip)
                s.request("POST", f"/api/v1/s/{link['share_id']}/open",
                          headers={"X-Mutis-Access": codec.b64u(os.urandom(32))}, ip=ip)
                drop = s.drop()
                raw = os.urandom(125)
                job = s.request("POST", "/api/v1/courier", {"to": "drop", "drop_id": drop["drop_id"], "kind": 3,
                                                            "blob": codec.b64u(raw), "pow": s.solve("courier")}, ip=ip)[2]
                address = fake_keys()["address"]
                s.request("POST", "/api/v1/courier", {"to": "address", "address": address, "kind": 3,
                                                      "blob": codec.b64u(raw)}, headers=locker["auth"], ip=ip)
                with db.tx(s.conn):
                    db.set_meta(s.conn, "receiver_address", s.receiver["address"])
                inv = s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=locker["auth"], ip=ip)[2]
                s.request("GET", "/api/v1/s/" + "Z" * 22, ip=ip)
                s.request("PATCH", f"/api/v1/s/{link['share_id']}", {"max_views": 1}, ip=ip,
                          headers={"X-Mutis-Manage": item["manage_token"], "Origin": "https://evil.example"})
            finally:
                s.close()
        text = "\n".join(handler.lines) + stderr.getvalue()
        secrets_seen = [ip, item["upload_id"], item["item_id"], item["manage_token"], link["share_id"],
                        link["access"]["X-Mutis-Access"], opened["ticket"], locker["token"], locker["id"],
                        codec.b64u(locker["auth_key"]), drop["drop_id"], drop["keys"]["address"], job["job_id"],
                        codec.b64u(raw), address, inv["invoice_id"], inv["address"], "evil.example",
                        hashlib.sha256(locker["auth_key"]).hexdigest()]
        for value in secrets_seen:
            self.assertNotIn(value, text)
        self.assertTrue(all(LINE.match(line) for line in handler.lines))


if __name__ == "__main__":
    unittest.main()
