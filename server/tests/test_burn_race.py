# SPDX-License-Identifier: MIT
"""S-03: the atomic burn. 50 concurrent opens of a Once link: exactly one wins; with N = 3, exactly three."""
import threading
import unittest

from harness import Stack


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


if __name__ == "__main__":
    unittest.main()
