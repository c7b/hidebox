# SPDX-License-Identifier: MIT
"""S-10: input safety — body limits, ids checked before any DB or file access, constant-time comparisons,
no path built from user input, header limits, Origin checks, trusted X-Real-IP only from loopback."""
import http.client
import json
import re
import socket
import unittest
from pathlib import Path

from harness import ORIGIN, Stack
from mutis import api, codec, config
from mutis.ipkeys import client_ip
from mutis.storage import Blobs

SERVER = Path(__file__).resolve().parents[1]


class InputSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Stack()

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_oversized_json_is_413(self):
        status, _, body = self.s.request("POST", "/api/v1/pow", raw=b"{" + b" " * 70_000 + b"}")
        self.assertEqual((status, body["error"]["code"]), (413, "too_large"))

    def test_chunk_longer_than_expected_is_rejected(self):
        status, up = self.s.start_upload(1000)
        status, _, body = self.s.request("PUT", f"/api/v1/uploads/{up['upload_id']}/chunks/0", raw=b"x" * 5000,
                                         headers={"X-Mutis-Chunk-SHA256": codec.b64u(b"\0" * 32)})
        self.assertEqual((status, body["error"]["code"]), (400, "bad_length"))

    def test_malformed_ids_fail_before_any_db_access(self):
        def no_db():
            raise AssertionError("touched the database")

        original = self.s.app.connect
        self.s.app.connect = no_db
        try:
            for path in ("/api/v1/s/..%2F..%2Fetc%2Fpasswd", "/api/v1/s/" + "A" * 21,
                         "/api/v1/uploads/..%2Fx/chunks/0", "/api/v1/uploads/" + "A" * 22 + "/chunks/9999999",
                         "/api/v1/drops/ILOU000000", "/api/v1/invoices/inv_UPPER", "/api/v1/blobs/short",
                         "/api/v1/chain/tx/XYZ/view", "/api/v1/seallog/proof/" + "%00" * 22):
                method = "PUT" if "chunks" in path else "GET"
                status, _, body = self.s.request(method, path, raw=b"" if method == "PUT" else None)
                self.assertEqual((status, body["error"]["code"]), (400, "bad_request"), path)
        finally:
            self.s.app.connect = original

    def test_non_canonical_ticket_is_not_found(self):
        """Review L1: 43 base64url characters that don't encode 32 bytes canonically are a 404, not a 500."""
        with self.assertNoLogs("mutis", "ERROR"):
            ticket = "A" * 42 + "B"
            for method, path in (("GET", f"/api/v1/blobs/{ticket}"), ("POST", f"/api/v1/blobs/{ticket}/done")):
                status, _, body = self.s.request(method, path, raw=b"" if method == "POST" else None)
                self.assertEqual((status, body["error"]["code"]), (404, "not_found"), path)

    def test_blob_paths_only_from_valid_ids(self):
        blobs = Blobs(self.s.app.blobs.root)
        for bad in ("../../etc/passwd", "A" * 21, "A" * 21 + "/", ""):
            with self.assertRaises(ValueError):
                blobs.part(bad)

    def test_secret_comparisons_are_constant_time(self):
        pattern = re.compile(r"(access_hash|link_hash|manage_hash|auth_verifier|token_hash|code_hash|canary_token)"
                             r"\"?\]?\s*[!=]=|[!=]=\s*\w*\[?\"?(access_hash|link_hash|manage_hash|auth_verifier)")
        for path in (SERVER / "mutis").rglob("*.py"):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                self.assertIsNone(pattern.search(line), f"{path.name}:{number}: {line.strip()}")

    def test_headers_over_16_kib(self):
        status = self.s.request("GET", "/api/v1/health", headers={f"X-Pad-{i}": "x" * 1000 for i in range(17)})[0]
        self.assertEqual(status, 400)

    def test_origin_check_on_state_changes(self):
        status, _, body = self.s.request("POST", "/api/v1/pow", {"purpose": "upload"},
                                         headers={"Origin": "https://evil.example"})
        self.assertEqual((status, body["error"]["code"]), (403, "bad_origin"))
        self.assertEqual(self.s.request("POST", "/api/v1/pow", {"purpose": "upload"}, headers={"Origin": ORIGIN})[0],
                         200)

    def test_malformed_json_and_chunked_bodies(self):
        self.assertEqual(self.s.request("POST", "/api/v1/pow", raw=b"{nope")[0], 400)
        self.assertEqual(self.s.request("POST", "/api/v1/pow", raw=b"[1, 2]")[0], 400)
        self.assertEqual(self.s.request("POST", "/api/v1/pow", raw=json.dumps({"purpose": 5}).encode())[0], 422)
        conn = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=10)
        conn.putrequest("POST", "/api/v1/pow")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        conn.send(b"0\r\n\r\n")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()

    def test_a_chunked_body_closes_the_connection_with_one_answer(self):
        """security-audit-1: the API reads bodies by Content-Length only; a chunked one (Caddy forwards it
        as chunked) must not stay on the connection to be answered as a second request."""
        for method, path, status in (("POST", "/api/v1/pow", 400), ("GET", "/api/v1/health", 200)):
            with self.subTest(method=method), socket.create_connection(("127.0.0.1", self.s.port), timeout=10) as sock:
                sock.sendall(f"{method} {path} HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
                             "14\r\n{\"purpose\":\"upload\"}\r\n0\r\n\r\n".encode())
                data = b""
                while chunk := sock.recv(65536):
                    data += chunk
                head, _, rest = data.partition(b"\r\n\r\n")
                self.assertTrue(head.startswith(f"HTTP/1.1 {status} ".encode()), head[:40])
                self.assertIn(b"\r\nConnection: close", head)
                length = int(re.search(rb"Content-Length: (\d+)", head).group(1))
                self.assertEqual(len(rest), length, "nothing after the one answer")

    def test_bad_query_values(self):
        for query in ("after=-1", "after=x", "limit=0", "limit=99999"):
            self.assertEqual(self.s.request("GET", f"/api/v1/chain/utxos?{query}")[0], 400, query)

    def test_x_real_ip_only_from_loopback(self):
        self.assertEqual(client_ip("127.0.0.1", "203.0.113.5"), "203.0.113.5")
        self.assertEqual(client_ip("::1", "2001:db8::1"), "2001:db8::1")
        self.assertEqual(client_ip("198.51.100.1", "203.0.113.5"), "198.51.100.1")
        self.assertEqual(client_ip("127.0.0.1", None), "127.0.0.1")

    def test_binds_to_loopback_only(self):
        with self.assertRaises(config.ConfigError):
            api.make_server(self.s.app, "0.0.0.0", 0)

    def test_requests_in_flight_are_capped_per_network(self):
        """Deploy review M6: slow downloads from one /64 (or /48) can't hold every API thread."""
        ip64, ip48 = self.s.app.ipkeys.keys("203.0.113.9", self.s.now)
        caps = ((ip64, api.IN_FLIGHT_64), (ip48, api.IN_FLIGHT_48))
        for _ in range(api.IN_FLIGHT_64):
            self.assertTrue(self.s.app.inflight.acquire_slot(caps))
        try:
            status, _, body = self.s.request("GET", "/api/v1/health", ip="203.0.113.9")
            self.assertEqual((status, body["error"]["code"], body["error"]["retry_after"]), (429, "rate_limited", 1))
            self.assertEqual(self.s.request("GET", "/api/v1/health", ip="203.0.113.10")[0], 200)   # same /24
        finally:
            for _ in range(api.IN_FLIGHT_64):
                self.s.app.inflight.release_slot(caps)
        self.assertEqual(self.s.request("GET", "/api/v1/health", ip="203.0.113.9")[0], 200)
        self.s.app.inflight.wait_idle(5)       # the server thread releases its slot just after it answers
        self.assertEqual(self.s.app.inflight.count, 0)

    def test_config_rules(self):
        raw = {"public_origin": ORIGIN, "memo_origins": [ORIGIN]}
        for bad in ({"seal_log": {"checkpoint_interval_s": 599}}, {"e2e_expiry_s": -1}):
            with self.assertRaises(config.ConfigError, msg=bad):
                config.from_dict({**raw, **bad})
        with self.assertRaises(config.ConfigError):
            config.from_dict({**raw, "seal_log": {"checkpoint_interval": 900}})       # unknown keys stop us
        release = self.s.tmp / "releases" / "r1" / "sidecar"
        release.mkdir(parents=True)
        (self.s.tmp / "current").symlink_to(release.parent)
        argv = config.from_dict({**raw, "sidecar": {"dir": str(self.s.tmp / "current" / "sidecar")}}).sidecar_argv()
        self.assertIn(f"--allow-fs-read={release.resolve()}", argv)         # Node resolves symlinks itself
        self.assertEqual(argv[-1], f"{release.resolve()}/sidecar.mjs")


if __name__ == "__main__":
    unittest.main()
