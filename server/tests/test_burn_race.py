# SPDX-License-Identifier: MIT
"""S-03: the atomic burn. 50 concurrent opens of a Once link: exactly one wins; with N = 3, exactly three."""
import fcntl
import hashlib
import os
import socket
import threading
import time
import unittest

from harness import Stack
from mutis import codec, db, items, storage


def race(s: Stack, link: dict, threads: int = 50) -> list[tuple[int, dict]]:
    results, barrier = [], threading.Barrier(threads)
    lock = threading.Lock()

    def one(i: int) -> None:
        barrier.wait()
        status, _, body = s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"],
                                    ip=f"198.51.100.{i}")
        with lock:
            results.append((status, body))

    workers = [threading.Thread(target=one, args=(i,)) for i in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return results


class BurnRace(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_once_link_fifty_threads(self):
        item = self.s.upload(1 << 20)
        link = self.s.share(item, max_views=1)
        results = race(self.s, link)
        ok = [b for st, b in results if st == 200]
        burned = [b for st, b in results if st == 410]
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(burned), 49)
        self.assertTrue(all(b["error"]["details"]["reason"] == "burned" for b in burned))
        row = self.s.conn.execute("SELECT views_used, state, wrapped_key FROM shares WHERE id = ?",
                                  (link["share_id"],)).fetchone()
        self.assertEqual((row["views_used"], row["state"], row["wrapped_key"]), (1, "exhausted", None))

    def test_three_views_fifty_threads(self):
        item = self.s.upload(1000)
        link = self.s.share(item, max_views=3)
        results = race(self.s, link)
        self.assertEqual(sum(1 for st, _ in results if st == 200), 3)
        self.assertEqual(sum(1 for st, _ in results if st == 410), 47)
        self.assertEqual(self.s.conn.execute("SELECT views_used FROM shares WHERE id = ?",
                                             (link["share_id"],)).fetchone()[0], 3)


class EgressRace(unittest.TestCase):
    """GET /s/{id}/stored charges a file's daily egress from a row it read before its transaction; the charge
    itself must add in place, so racing downloads can't serve more than they count (security-audit-1)."""

    def setUp(self):
        self.s = Stack()
        self.item = self.s.upload(1000)
        self.link = self.s.share(self.item, max_views=1)
        self.size = self.s.conn.execute("SELECT size_stored FROM items WHERE id = ?",
                                        (self.item["item_id"],)).fetchone()[0]

    def tearDown(self):
        self.s.close()

    def set_used(self, used: int) -> None:
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE items SET egress_day = ?, egress_bytes = ? WHERE id = ?",
                                (codec.day(self.s.now), used, self.item["item_id"]))

    def used(self) -> int:
        return self.s.conn.execute("SELECT egress_bytes FROM items WHERE id = ?", (self.item["item_id"],)).fetchone()[0]

    def test_two_charges_from_the_same_stale_row_both_count(self):
        self.set_used(0)
        stale = [self.s.conn.execute("SELECT * FROM items WHERE id = ?", (self.item["item_id"],)).fetchone()
                 for _ in range(2)]
        for row in stale:
            with db.tx(self.s.conn):
                self.assertTrue(items.egress_ok(self.s.conn, row, self.s.now, self.size))
        self.assertEqual(self.used(), 2 * self.size)

    def test_a_stale_row_cant_pass_a_full_cap(self):
        self.set_used(items.EGRESS_PER_ITEM_DAY - self.size)
        stale = [self.s.conn.execute("SELECT * FROM items WHERE id = ?", (self.item["item_id"],)).fetchone()
                 for _ in range(2)]
        with db.tx(self.s.conn):
            self.assertTrue(items.egress_ok(self.s.conn, stale[0], self.s.now, self.size))
        with db.tx(self.s.conn):
            self.assertFalse(items.egress_ok(self.s.conn, stale[1], self.s.now, self.size))
        self.assertEqual(self.used(), items.EGRESS_PER_ITEM_DAY)

    def test_racing_stored_downloads_serve_only_what_is_left(self):
        self.set_used(items.stored_egress_cap() - self.size)     # what stored bytes may take of the day (half)
        results, barrier, lock = [], threading.Barrier(24), threading.Lock()

        def one(i: int) -> None:
            barrier.wait()
            status, _, _ = self.s.request("GET", f"/api/v1/s/{self.link['share_id']}/stored",
                                          headers=self.link["access"], ip=f"198.51.100.{i}")
            with lock:
                results.append(status)

        workers = [threading.Thread(target=one, args=(i,)) for i in range(24)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(429), 23)
        self.assertEqual(self.used(), items.stored_egress_cap())

    def stored(self, ip: str = "203.0.113.5", **headers) -> int:
        return self.s.request("GET", f"/api/v1/s/{self.link['share_id']}/stored",
                              headers={**self.link["access"], **headers}, ip=ip)[0]

    def test_a_range_of_stored_bytes_is_charged_its_own_length(self):
        """Security pass of 2026-11-09: every request was charged the whole file, so one-byte requests, which use
        no view, could spend a file's day of egress and leave its other readers (a paid file's buyers) without."""
        self.set_used(0)
        for _ in range(20):
            self.assertEqual(self.stored(Range="bytes=0-0"), 206)
        self.assertEqual(self.used(), 20)
        self.assertEqual(self.stored(), 200)
        self.assertEqual(self.used(), 20 + self.size)

    def test_stored_bytes_leave_half_the_days_egress_to_opens(self):
        self.set_used(items.stored_egress_cap() - self.size + 1)
        self.assertEqual(self.stored(), 429)
        self.assertEqual(self.stored(Range="bytes=0-0"), 206)                 # what is left of its half
        self.assertEqual(self.used(), items.stored_egress_cap() - self.size + 2)
        status, _, body = self.s.request("POST", f"/api/v1/s/{self.link['share_id']}/open", headers=self.link["access"])
        self.assertEqual(status, 200, body)                                    # opens have the other half

    def test_a_network_takes_a_files_stored_bytes_a_few_times_a_day(self):
        self.set_used(0)
        self.assertEqual([self.stored() for _ in range(4)], [200, 200, 200, 429])          # one /64 or IPv4 address
        self.assertEqual([self.stored(ip=f"203.0.113.{i}") for i in (6, 7, 8, 9)], [200, 200, 200, 429])   # its /24
        self.assertEqual(self.used(), 6 * self.size)                           # a refusal charges nothing
        self.assertEqual(self.stored(ip="198.51.100.1"), 200)                  # another network
        self.s.now += 8 * 3600                                                 # a third of a day: one more
        self.assertEqual([self.stored(), self.stored()], [200, 429])


if __name__ == "__main__":
    unittest.main()


class ChunkAcrossComplete(unittest.TestCase):
    """A chunk still arriving when its upload is completed would change the stored bytes after their hash was
    sealed (security pass, 2026-11-09): the file is locked while a chunk is written, and completing waits for it."""

    def setUp(self):
        self.s = Stack()
        self.s.app.blobs.FINALIZE_WAIT_S = 0.2
        status, self.up = self.s.start_upload(1000)
        self.assertEqual(status, 201, self.up)
        self.size = self.s.conn.execute("SELECT size_stored FROM items WHERE id = ?",
                                        (self.up["item_id"],)).fetchone()[0]
        self.path = f"/api/v1/uploads/{self.up['upload_id']}"

    def tearDown(self):
        self.s.close()

    def wait_until_held(self) -> None:
        """Until the API's handler holds the upload's file for the chunk it is reading."""
        fd = os.open(self.s.app.blobs.part(self.up["item_id"]), os.O_RDONLY)
        try:
            for _ in range(200):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                fcntl.flock(fd, fcntl.LOCK_UN)
                time.sleep(0.01)
        finally:
            os.close(fd)
        self.fail("the chunk's handler never held the file")

    def put(self, data: bytes) -> int:
        return self.s.request("PUT", f"{self.path}/chunks/0", raw=data,
                              headers={"X-Mutis-Chunk-SHA256": codec.b64u(hashlib.sha256(data).digest())})[0]

    def test_an_upload_isnt_completed_while_a_chunk_is_still_arriving(self):
        first, late = b"A" * self.size, b"B" * self.size
        self.assertEqual(self.put(first), 204)
        with socket.create_connection(("127.0.0.1", self.s.port), timeout=10) as sock:
            sock.sendall((f"PUT {self.path}/chunks/0 HTTP/1.1\r\nHost: x\r\nContent-Length: {self.size}\r\n"
                          f"X-Mutis-Chunk-SHA256: {codec.b64u(hashlib.sha256(late).digest())}\r\n\r\n").encode()
                         + late[:1])
            self.wait_until_held()
            status, _, body = self.s.request("POST", f"{self.path}/complete", {})
            self.assertEqual((status, body["error"]["code"]), (409, "upload_busy"))
            item = self.s.conn.execute("SELECT state, ct_hash FROM items WHERE id = ?", (self.up["item_id"],)).fetchone()
            self.assertEqual((item["state"], item["ct_hash"]), ("uploading", None))
            sock.sendall(late[1:])
            self.assertTrue(sock.recv(100).startswith(b"HTTP/1.1 204 "))
        status, _, done = self.s.request("POST", f"{self.path}/complete", {})
        self.assertEqual(status, 200, done)
        stored = self.s.app.blobs.read_all(self.up["item_id"])
        self.assertEqual(stored, late)
        self.assertEqual(codec.unb64u(done["ct_hash"]), hashlib.sha256(hashlib.sha256(stored).digest()).digest())

    def test_a_chunk_that_reaches_the_file_after_it_was_completed_is_written_nowhere(self):
        first = b"A" * self.size
        self.assertEqual(self.put(first), 204)
        blobs, real = self.s.app.blobs, storage.fcntl.flock

        def complete_first(fd, operation):                     # the upload is completed between open and lock
            if operation == storage.fcntl.LOCK_SH:
                storage.fcntl.flock = real
                blobs.finalize(self.up["item_id"])
            return real(fd, operation)

        storage.fcntl.flock = complete_first
        try:
            with self.assertRaises(storage.Completed):
                blobs.write_at(self.up["item_id"], 0, iter([b"B" * self.size]))
        finally:
            storage.fcntl.flock = real
        self.assertEqual(blobs.read_all(self.up["item_id"]), first)

    def test_two_copies_of_a_chunk_are_written_one_after_the_other(self):
        """Written at once, the slower copy's tail landed over the faster one's: a mix on disk under one copy's hash."""
        first, second, out = b"A" * self.size, b"B" * self.size, []
        with socket.create_connection(("127.0.0.1", self.s.port), timeout=10) as sock:
            sock.sendall((f"PUT {self.path}/chunks/0 HTTP/1.1\r\nHost: x\r\nContent-Length: {self.size}\r\n"
                          f"X-Mutis-Chunk-SHA256: {codec.b64u(hashlib.sha256(first).digest())}\r\n\r\n").encode()
                         + first[:self.size // 2])
            self.wait_until_held()
            other = threading.Thread(target=lambda: out.append(self.put(second)))
            other.start()
            other.join(0.3)
            self.assertTrue(other.is_alive(), "the second copy waits for the first")
            sock.sendall(first[self.size // 2:])
            self.assertTrue(sock.recv(100).startswith(b"HTTP/1.1 204 "))
        other.join(10)
        self.assertEqual(out, [204])
        row = self.s.conn.execute("SELECT sha256 FROM chunks WHERE item_id = ? AND idx = 0", (self.up["item_id"],)).fetchone()
        self.assertEqual(self.s.app.blobs.part(self.up["item_id"]).read_bytes(), second)
        self.assertEqual(row[0], hashlib.sha256(second).digest())
        self.assertEqual(self.s.app.blobs._writing, {})
