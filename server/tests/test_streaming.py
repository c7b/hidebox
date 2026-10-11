# SPDX-License-Identifier: MIT
"""S-09: a 2 GiB upload and a Range download complete with the API's peak RSS under 96 MiB.

The API runs in a child process so its memory is measured alone (VmHWM in /proc). This moves 4 GiB
through loopback and needs 2 GiB of free disk, so it runs only with MUTIS_BIG=1 (on ultron).
"""
import hashlib
import http.client
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from harness import Client
from mutis import codec

TESTS = Path(__file__).resolve().parent
CHILD = (f"import sys; sys.path.insert(0, {str(TESTS)!r}); from harness import Stack; s = Stack(); "
         "print(s.port, s.cfg.db_path, flush=True); sys.stdin.read(); s.close()")
RSS_LIMIT_KIB = 96 * 1024


@unittest.skipUnless(os.environ.get("MUTIS_BIG") == "1", "set MUTIS_BIG=1 to move 2 GiB through the API")
class Streaming(unittest.TestCase):
    def test_two_gib_round_trip_under_96_mib(self):
        child = subprocess.Popen([sys.executable, "-I", "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 text=True)
        try:
            port, db_path = child.stdout.readline().split()
            api = Client(int(port))
            locker = api.register()
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("UPDATE identities SET distinct_days = 2, paid_bytes = ?, paid_until = 4102444800 "
                             "WHERE id = ?", (2 << 30, locker["id"]))
            conn.close()
            n, size = api.layout(2 << 30)
            self.assertEqual((n, size), (512, (2 << 30) + 512 * 16))
            chunk = os.urandom((4 << 20) + 16)
            digest = hashlib.sha256(chunk).digest()
            status, up = api.start_upload(2 << 30, headers=locker["auth"])
            self.assertEqual(status, 201, up)
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=120)
            for i in range(n):
                conn.request("PUT", f"/api/v1/uploads/{up['upload_id']}/chunks/{i}", body=chunk,
                             headers={"X-Mutis-Chunk-SHA256": codec.b64u(digest)})
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 204)
            status = api.request("POST", f"/api/v1/uploads/{up['upload_id']}/complete", {})[0]
            self.assertEqual(status, 200)
            link = api.share({"item_id": up["item_id"], "manage": {"X-Mutis-Manage": up["manage_token"]}})
            opened = api.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])[2]
            conn.request("GET", f"/api/v1/blobs/{opened['ticket']}")
            resp = conn.getresponse()
            total, h = 0, hashlib.sha256()
            while data := resp.read(1 << 20):
                total += len(data)
                h.update(data)
            self.assertEqual((resp.status, total), (200, size))
            expected = hashlib.sha256()
            for _ in range(n):
                expected.update(chunk)
            self.assertEqual(h.digest(), expected.digest())
            conn.request("GET", f"/api/v1/blobs/{opened['ticket']}", headers={"Range": f"bytes={size - (1 << 20)}-"})
            resp = conn.getresponse()
            tail = resp.read()
            self.assertEqual((resp.status, tail), (206, chunk[-(1 << 20):]))
            conn.close()
            peak = int(next(line.split()[1] for line in Path(f"/proc/{child.pid}/status").read_text().splitlines()
                            if line.startswith("VmHWM:")))
            print(json.dumps({"size_stored": size, "api_peak_rss_kib": peak}), file=sys.stderr)
            self.assertLess(peak, RSS_LIMIT_KIB)
        finally:
            child.stdin.close()
            child.wait(timeout=60)


if __name__ == "__main__":
    unittest.main()
