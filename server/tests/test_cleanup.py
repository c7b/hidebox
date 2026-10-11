# SPDX-License-Identifier: MIT
"""S-08: cleanup (spec §8.2) — expiry, unlinking after tickets end, abandoned uploads, tombstones, quota, lapse."""
import unittest

from harness import GiB, Stack
from mutis import db, quota


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def item_state(self, item_id: str) -> str:
        return self.s.conn.execute("SELECT state FROM items WHERE id = ?", (item_id,)).fetchone()[0]

    def test_expiry_answers_410_expired_and_scrubs(self):
        s = self.s
        item = s.upload(1000)
        link = s.share(item, max_views=3, expires_at=s.now + 60)
        s.now += 61
        status, _, body = s.request("GET", f"/api/v1/s/{link['share_id']}")
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "expired"))
        status, _, body = s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])
        self.assertEqual((status, body["error"]["details"]["reason"]), (410, "expired"))
        s.run_cleanup()
        row = s.conn.execute("SELECT state, wrapped_key, access_hash FROM shares WHERE id = ?",
                             (link["share_id"],)).fetchone()
        self.assertEqual(tuple(row), ("expired", None, None))
        self.assertEqual(self.item_state(item["item_id"]), "deleted")
        self.assertFalse(s.app.blobs.exists(item["item_id"]))

    def test_doomed_blob_waits_for_its_ticket(self):
        s = self.s
        item = s.upload(1 << 20)
        link = s.share(item)
        opened = s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])[2]
        self.assertEqual(self.item_state(item["item_id"]), "doomed")
        s.run_cleanup()
        self.assertTrue(s.app.blobs.exists(item["item_id"]))          # the download may still be running
        self.assertEqual(s.request("GET", f"/api/v1/blobs/{opened['ticket']}")[0], 200)
        s.now += 1801
        s.run_cleanup()
        self.assertFalse(s.app.blobs.exists(item["item_id"]))
        self.assertEqual(self.item_state(item["item_id"]), "deleted")

    def test_done_unlinks_at_once(self):
        s = self.s
        item = s.upload(1 << 20)
        link = s.share(item)
        opened = s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])[2]
        s.request("POST", f"/api/v1/blobs/{opened['ticket']}/done")
        self.assertFalse(s.app.blobs.exists(item["item_id"]))

    def test_abandoned_upload_releases_its_reservation(self):
        s = self.s
        locker = s.register()
        status, up = s.start_upload(5 << 20, headers=locker["auth"])
        self.assertEqual(status, 201)
        reserved = s.conn.execute("SELECT reserved_bytes FROM identities WHERE id = ?", (locker["id"],)).fetchone()[0]
        self.assertGreater(reserved, 5 << 20)
        s.now += 7201
        s.run_cleanup()
        reserved = s.conn.execute("SELECT reserved_bytes FROM identities WHERE id = ?", (locker["id"],)).fetchone()[0]
        self.assertEqual(reserved, 0)
        self.assertFalse(s.app.blobs.part(up["item_id"]).exists())
        self.assertIsNone(s.conn.execute("SELECT 1 FROM uploads WHERE id = ?", (up["upload_id"],)).fetchone())
        self.assertEqual(self.item_state(up["item_id"]), "deleted")

    def test_tombstones_and_closed_drops_purged_after_30_days(self):
        s = self.s
        item = s.upload(1000)
        link = s.share(item)
        s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])
        drop = s.drop()
        s.request("DELETE", f"/api/v1/drops/{drop['drop_id']}", headers=drop["manage"])
        s.now += 29 * 86400
        s.run_cleanup()
        self.assertEqual(s.request("GET", f"/api/v1/s/{link['share_id']}")[0], 410)
        self.assertEqual(s.request("GET", f"/api/v1/drops/{drop['drop_id']}")[0], 410)
        s.now += 2 * 86400
        s.run_cleanup()
        self.assertEqual(s.request("GET", f"/api/v1/s/{link['share_id']}")[0], 404)
        self.assertEqual(s.request("GET", f"/api/v1/drops/{drop['drop_id']}")[0], 404)
        self.assertIsNone(s.conn.execute("SELECT 1 FROM items WHERE id = ?", (item["item_id"],)).fetchone())

    def test_unshared_ephemeral_item_waits_then_is_doomed(self):
        s = self.s
        item = s.upload(1000)
        s.run_cleanup()
        self.assertEqual(self.item_state(item["item_id"]), "ready")       # its link may be a second away
        s.now += 3 * 3600
        s.run_cleanup()
        self.assertEqual(self.item_state(item["item_id"]), "deleted")

    def test_hourly_quota_step(self):
        s = self.s
        s.run_cleanup()
        first = int(s.meta("free_quota_bytes"))
        pool = quota.measure(s.conn, s.disk, ".", s.cfg["limits"], s.now)
        self.assertEqual(first, pool.q_target)
        s.disk.avail = 40 * GiB
        s.run_cleanup()
        self.assertEqual(int(s.meta("free_quota_bytes")), first)          # once an hour
        s.now += 3600
        s.run_cleanup()
        self.assertEqual(int(s.meta("free_quota_bytes")), quota.smooth(first, quota.measure(
            s.conn, s.disk, ".", s.cfg["limits"], s.now).q_target))

    def test_lapse_deletes_oldest_kept_files_after_grace(self):
        s = self.s
        locker = s.register()
        s.graduate(locker)
        kept = [s.upload(1000, headers=locker["auth"], retention="kept", owner_wrap="A" * 80) for _ in range(3)]
        q = 1024 + 16 + 1          # a free quota just over one file
        with db.tx(s.conn):
            db.set_meta(s.conn, "free_quota_bytes", str(q))
            db.set_meta(s.conn, "cleanup_hour", str(s.now - s.now % 3600))
            s.conn.execute("UPDATE identities SET paid_bytes = ?, paid_until = ? WHERE id = ?",
                           (2 * GiB, s.now - 31 * 86400, locker["id"]))
        s.run_cleanup()
        states = [self.item_state(k["item_id"]) for k in kept]
        self.assertEqual(states, ["deleted", "deleted", "ready"])


if __name__ == "__main__":
    unittest.main()
