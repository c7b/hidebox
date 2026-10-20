# SPDX-License-Identifier: MIT
"""S-03: the atomic burn. 50 concurrent opens of a Once link: exactly one wins; with N = 3, exactly three."""
import threading
import unittest

from harness import Stack
from mutis import codec, db, items


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
        self.set_used(items.EGRESS_PER_ITEM_DAY - self.size)
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
        self.assertEqual(self.used(), items.EGRESS_PER_ITEM_DAY)


if __name__ == "__main__":
    unittest.main()
