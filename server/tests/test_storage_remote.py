# SPDX-License-Identifier: MIT
"""Blobs in an S3-compatible store (storage.TieredBlobs, docs/storage.md): our disk while an upload arrives, the store
after; deletions queued without the network and carried out by the offloader; the store down; the pool measured on
the space rented. Against the local stand-in (fake_s3.py), which checks every signature and payload hash."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import GiB, Stack  # noqa: E402
from mutis import config, db, quota, storage  # noqa: E402
from mutis.fake_s3 import FakeS3  # noqa: E402

V = "/api/v1"
ITEM = "AbCdEfGhIjKlMnOpQrStUv"
KiB = 1 << 10


def roomy(path):
    return SimpleNamespace(f_blocks=100 * GiB, f_frsize=1, f_bavail=80 * GiB)


class Tiered(unittest.TestCase):
    def setUp(self):
        self.fake = FakeS3(min_part=1024)
        self.tmp = tempfile.TemporaryDirectory()
        from mutis import s3
        self.blobs = storage.TieredBlobs(Path(self.tmp.name) / "blobs", s3.Store(self.fake.settings()),
                                         keep_local_max=256 * KiB, staging_free_min=1 * GiB, statvfs=roomy)

    def tearDown(self):
        self.fake.close()
        self.tmp.cleanup()

    def put(self, item_id: str, data: bytes) -> None:
        self.blobs.create_part(item_id, len(data))
        self.blobs.write_at(item_id, 0, [data])
        self.blobs.finalize(item_id)

    def test_a_big_blob_moves_to_the_store_and_is_read_from_there(self):
        data = os.urandom(300 * KiB)
        self.put(ITEM, data)
        self.assertEqual([i for i, _ in self.blobs.queued(".offload")], [ITEM])
        self.assertTrue(self.blobs.bin(ITEM).exists())
        self.assertEqual(self.blobs.offload_once(), {"deleted": 0, "offloaded": 1, "failed": 0})
        self.assertFalse(self.blobs.bin(ITEM).exists())
        self.assertEqual(self.blobs.marker(ITEM).read_text(), f"{len(data)}\n")
        self.assertEqual(self.fake.objects["blobs/" + ITEM], data)
        self.assertTrue(self.blobs.exists(ITEM))
        self.assertEqual(b"".join(self.blobs.read_range(ITEM, 5, 70_000)), data[5:70_005])
        self.assertEqual(self.blobs.read_all(ITEM), data)
        self.assertEqual(self.blobs.queued(".offload"), [])

    def test_a_small_blob_stays_on_our_disk(self):
        self.put(ITEM, os.urandom(256 * KiB))
        self.assertEqual(self.blobs.queued(".offload"), [])
        self.assertEqual(self.blobs.offload_once()["offloaded"], 0)
        self.assertTrue(self.blobs.bin(ITEM).exists())
        self.assertEqual(self.fake.requests, {})

    def test_deleting_is_queued_offline_then_done(self):
        self.put(ITEM, os.urandom(300 * KiB))
        self.blobs.offload_once()
        self.fake.close()                              # the cleanup pass has no network: unlink must not need it
        self.blobs.unlink(ITEM)
        self.assertFalse(self.blobs.exists(ITEM))
        self.assertEqual([i for i, _ in self.blobs.queued(".delete")], [ITEM])
        self.assertEqual(self.blobs.offload_once()["failed"], 1)          # the store is unreachable: it stays queued
        self.assertEqual(len(self.blobs.queued(".delete")), 1)
        self.fake = FakeS3(min_part=1024)
        from mutis import s3
        self.blobs.store = s3.Store(self.fake.settings())
        self.fake.objects["blobs/" + ITEM] = b"still there"
        self.assertEqual(self.blobs.offload_once()["deleted"], 1)
        self.assertNotIn("blobs/" + ITEM, self.fake.objects)
        self.assertEqual(self.blobs.queued(".delete"), [])

    def test_deleted_before_its_turn_never_reaches_the_store(self):
        self.put(ITEM, os.urandom(300 * KiB))
        self.blobs.unlink(ITEM)
        self.blobs.offload_once()
        self.blobs.offload_once()
        self.assertEqual(self.fake.objects, {})
        self.assertEqual((self.blobs.queued(".offload"), self.blobs.queued(".delete")), ([], []))
        self.assertEqual(self.fake.requests["PUT"], 0)

    def test_deleted_while_it_is_copied(self):
        data = os.urandom(300 * KiB)
        self.put(ITEM, data)
        real_put = self.blobs.store.put

        def put_then_delete(item_id, fd, size):
            real_put(item_id, fd, size)
            self.blobs.unlink(item_id)                 # the owner deletes it mid-copy
        self.blobs.store.put = put_then_delete
        self.blobs.offload_once()
        self.blobs.store.put = real_put
        self.assertFalse(self.blobs.exists(ITEM))
        self.assertEqual(self.blobs.offload_once()["deleted"], 1)
        self.assertEqual(self.fake.objects, {})
        self.assertFalse(self.blobs.marker(ITEM).exists())

    def test_a_store_that_fails_leaves_the_blob_local_and_queued(self):
        data = os.urandom(300 * KiB)
        self.put(ITEM, data)
        self.fake.fail_next(5, 500)
        self.assertEqual(self.blobs.offload_once()["failed"], 1)
        self.assertTrue(self.blobs.bin(ITEM).exists())
        self.assertFalse(self.blobs.marker(ITEM).exists())
        self.assertEqual(b"".join(self.blobs.read_range(ITEM, 0, 10)), data[:10])
        backlog = self.blobs.backlog(os.stat(self.blobs.root / ".offload" / ITEM).st_mtime + 4000)
        self.assertEqual(backlog["offload"], {"count": 1, "oldest_s": 4000})
        self.fake.fail_next(0)
        self.assertEqual(self.blobs.offload_once()["offloaded"], 1)

    def test_a_full_disk_refuses_new_uploads(self):
        self.blobs.statvfs = lambda path: SimpleNamespace(f_blocks=10 * GiB, f_frsize=1, f_bavail=1 * GiB + 100)
        with self.assertRaises(OSError):
            self.blobs.create_part(ITEM, 200)
        self.blobs.create_part(ITEM, 100)

    def test_the_queues_take_only_ids(self):
        (self.blobs.root / ".delete").mkdir(parents=True)
        (self.blobs.root / ".delete" / "..%2Fetc").write_text("")
        (self.blobs.root / ".delete" / "not-an-id").write_text("")
        self.assertEqual(self.blobs.queued(".delete"), [])

    def test_blobs_from_before_the_store_are_queued_on_request(self):
        big, small = ITEM, "ZyXwVuTsRqPoNmLkJiHgFe"
        for item_id, n in ((big, 300 * KiB), (small, 10 * KiB)):
            Path(self.blobs.bin(item_id)).parent.mkdir(parents=True, exist_ok=True)
            self.blobs.bin(item_id).write_bytes(os.urandom(n))
        self.blobs.create_part("Aa" + "b" * 20, 300 * KiB)          # an upload in flight
        self.assertEqual(self.blobs.enqueue_existing(), 1)
        self.assertEqual([i for i, _ in self.blobs.queued(".offload")], [big])
        self.assertEqual(self.blobs.enqueue_existing(), 0)
        self.assertEqual(self.blobs.offload_once()["offloaded"], 1)

    def test_an_offload_that_finishes_while_it_is_deleted_leaves_nothing_in_the_store(self):
        self.put(ITEM, os.urandom(300 * KiB))
        real = storage.Blobs.unlink

        def offload_then_unlink(blobs, item_id):
            self.blobs.offload_once()                   # the copy finishes between unlink's first look and the local delete
            real(blobs, item_id)
        with mock.patch.object(storage.Blobs, "unlink", offload_then_unlink):
            self.blobs.unlink(ITEM)
        self.assertEqual([i for i, _ in self.blobs.queued(".delete")], [ITEM])
        self.blobs.offload_once()
        self.assertEqual(self.fake.objects, {})
        self.assertFalse(self.blobs.exists(ITEM))

    def test_a_store_that_holds_another_size_keeps_the_local_copy_and_the_queue_moves(self):
        data = os.urandom(300 * KiB)
        self.put(ITEM, data)
        other = "ZyXwVuTsRqPoNmLkJiHgFe"
        self.put(other, os.urandom(300 * KiB))
        real_head = self.blobs.store.head
        with mock.patch.object(self.blobs.store, "head", lambda i: len(data) - 1 if i == ITEM else real_head(i)):
            done = self.blobs.offload_once()
            self.assertEqual((done["mismatched"], done["offloaded"], done["failed"]), (1, 1, 0))   # the next one went on
            for _ in range(self.blobs.MISMATCH_TRIES):
                self.blobs.offload_once()
        self.assertTrue(self.blobs.bin(ITEM).exists())
        self.assertFalse(self.blobs.marker(ITEM).exists())
        self.assertEqual(self.blobs.mismatches[ITEM], self.blobs.MISMATCH_TRIES)   # then left alone, still queued
        self.assertEqual([i for i, _ in self.blobs.queued(".offload")], [ITEM])

    def test_an_id_with_a_newline_is_no_queue_entry(self):
        (self.blobs.root / ".delete").mkdir(parents=True)
        (self.blobs.root / ".delete" / (ITEM + "\n")).write_text("")
        self.assertEqual(self.blobs.queued(".delete"), [])
        with self.assertRaises(ValueError):
            self.blobs._queued(".delete", ITEM + "\n")

    def test_offline_queues_without_the_stores_key(self):
        cfg = config.from_dict({"public_origin": "https://x.example", "memo_origins": ["https://x.example"],
                                "data_dir": self.tmp.name,
                                "storage": {"backend": "s3", "s3_endpoint": "https://s3.example.com", "s3_region": "x-1",
                                            "s3_bucket": "hidebox-test", "s3_key_file": "/nonexistent/s3.key"},
                                "limits": {"capacity_bytes": 1 << 40}})
        blobs = storage.from_config(cfg, offline=True)
        self.assertIsInstance(blobs, storage.TieredBlobs)
        with self.assertRaises(OSError):
            storage.from_config(cfg)                    # the API needs the key; the cleanup pass doesn't

    def test_a_marker_that_isnt_a_size_opens_nothing(self):
        self.put(ITEM, os.urandom(300 * KiB))
        self.blobs.offload_once()
        self.blobs.marker(ITEM).write_text("../../x\n")
        with self.assertRaises(OSError):
            self.blobs.read_all(ITEM)


class ThroughTheApi(unittest.TestCase):
    """An upload, an open and a download through the real API, with the blob in the stand-in store."""

    def setUp(self):
        self.fake = FakeS3()
        self.keys = tempfile.NamedTemporaryFile("w", delete=False, suffix=".key")
        self.keys.write(f"{self.fake.access_key}\n{self.fake.secret_key}\n")
        self.keys.close()
        self.s = Stack({"storage": {"backend": "s3", "s3_endpoint": self.fake.url, "s3_region": self.fake.region,
                                    "s3_bucket": self.fake.bucket, "s3_key_file": self.keys.name,
                                    "staging_free_min_bytes": 0},
                        "limits": {"capacity_bytes": 50 * GiB}})

    def tearDown(self):
        self.s.close()
        self.fake.close()
        os.unlink(self.keys.name)

    def test_upload_offload_open_download_delete(self):
        s = self.s
        self.assertIsInstance(s.app.blobs, storage.TieredBlobs)
        item = s.upload(1 << 20)
        self.assertEqual(s.app.blobs.offload_once()["offloaded"], 1)
        self.assertEqual(self.fake.objects["blobs/" + item["item_id"]], item["blob"])
        link = s.share(item, max_views=2)
        status, _, opened = s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        self.assertEqual(status, 200, opened)
        status, _, data = s.request("GET", f"{V}/blobs/{opened['ticket']}")
        self.assertEqual((status, data), (200, item["blob"]))
        status, headers, data = s.request("GET", f"{V}/blobs/{opened['ticket']}", headers={"Range": "bytes=10-19"})
        self.assertEqual((status, data), (206, item["blob"][10:20]))
        # The store down: a 503 before anything is sent, and the ticket isn't charged for it.
        served = s.conn.execute("SELECT bytes_served FROM tickets").fetchone()[0]
        self.fake.fail_next(1, 500)
        status, headers, body = s.request("GET", f"{V}/blobs/{opened['ticket']}")
        self.assertEqual((status, body["error"]["code"]), (503, "store_unavailable"))
        self.assertEqual(s.conn.execute("SELECT bytes_served FROM tickets").fetchone()[0], served)
        # Its link ends and its ticket closes: the cleanup pass (no network) queues the deletion, the offloader does it.
        s.request("POST", f"{V}/blobs/{opened['ticket']}/done")
        s.request("DELETE", f"{V}/items/{item['item_id']}", headers=item["manage"])
        s.run_cleanup()
        self.assertFalse(s.app.blobs.exists(item["item_id"]))
        self.assertEqual(s.app.blobs.offload_once()["deleted"], 1)
        self.assertNotIn("blobs/" + item["item_id"], self.fake.objects)
        self.assertIsNotNone(db.get_meta_json(s.conn, "storage"))

    def test_a_small_file_stays_local_and_opens_inline(self):
        s = self.s
        item = s.upload(1000)
        self.assertEqual(s.app.blobs.offload_once()["offloaded"], 0)
        self.assertTrue(s.app.blobs.bin(item["item_id"]).exists())
        link = s.share(item)
        status, _, opened = s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        self.assertEqual(status, 200, opened)
        self.assertEqual(self.fake.requests, {})

    def test_a_missing_bucket_is_try_again_not_lost(self):
        s = self.s
        item = s.upload(1 << 20)
        s.app.blobs.offload_once()
        link = s.share(item)
        _, _, opened = s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        self.fake.bucket = "another-bucket"              # the store answers NoSuchBucket for ours
        status, _, body = s.request("GET", f"{V}/blobs/{opened['ticket']}")
        self.assertEqual((status, body["error"]["code"]), (503, "store_unavailable"))

    def test_a_blob_the_store_has_lost_is_not_found_not_try_again(self):
        s = self.s
        item = s.upload(1 << 20)
        s.app.blobs.offload_once()
        self.fake.objects.clear()                       # the provider lost it
        link = s.share(item)
        status, _, opened = s.request("POST", f"{V}/s/{link['share_id']}/open", headers=link["access"])
        status, _, body = s.request("GET", f"{V}/blobs/{opened['ticket']}")
        self.assertEqual((status, body["error"]["code"]), (404, "not_found"))

    def test_the_pool_is_the_space_rented(self):
        s = self.s
        s.disk.avail = 1 * GiB                          # our own disk is small: it no longer sets the pool
        pool = quota.measure(s.conn, s.disk, s.cfg.data_dir, s.cfg["limits"], s.now)
        self.assertEqual((pool.d_total, pool.d_avail), (50 * GiB, 50 * GiB))
        s.upload(1 << 20)
        pool = quota.measure(s.conn, s.disk, s.cfg.data_dir, s.cfg["limits"], s.now)
        self.assertEqual(pool.d_total - pool.d_avail, pool.stored)


class DiskCap(unittest.TestCase):
    """Our disk with `limits.disk_cap_bytes` (the mainnet beta's 20 GiB of a disk it shares with production): the pool is
    at most the cap, never takes the disk below its reserve, and the freezes come at the cap as at a full disk."""

    def setUp(self):
        self.s = Stack({"limits": {"disk_cap_bytes": 20 * GiB, "reserve_min_bytes": 10 * GiB}})
        self.s.disk.total, self.s.disk.avail = 100 * GiB, 80 * GiB

    def tearDown(self):
        self.s.close()

    def pool(self):
        return quota.measure(self.s.conn, self.s.disk, self.s.cfg.data_dir, self.s.cfg["limits"], self.s.now)

    def test_the_pool_is_the_cap_while_the_disk_has_room(self):
        self.assertEqual(self.pool().pool, 20 * GiB)
        self.s.upload(1 << 20)
        self.assertEqual(self.pool().pool, 20 * GiB)                 # what is stored is taken from the cap

    def test_a_disk_that_fills_wins_over_the_cap(self):
        self.s.disk.avail = 15 * GiB                                 # another deployment filled the disk
        self.assertEqual(self.pool().pool, 5 * GiB)                  # 15 free - 10 reserve

    def hold(self, size: int) -> None:
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO items(id, manage_hash, retention, lane, canary, state, header, meta_ct, "
                                "chunk_count, size_stored, created_hour) VALUES ('AAAAAAAAAAAAAAAAAAAAAA', ?, 'kept', "
                                "'locker', 0, 'ready', x'00', x'00', 1, ?, 0)", (os.urandom(32), size))

    def test_free_uploads_freeze_near_the_cap(self):
        from mutis import lanes
        self.hold(19 * GiB)                                          # 19 GiB of the 20 already held
        self.assertEqual(lanes.freeze_state(self.s.conn, self.pool()), "free")

    def test_what_is_stored_beyond_the_cap_freezes_everything(self):
        from mutis import lanes
        self.hold(21 * GiB)                                          # a cap lowered below what is already stored
        self.assertEqual(self.pool().pool, 21 * GiB)                 # nothing more than what is there
        self.assertEqual(lanes.freeze_state(self.s.conn, self.pool()), "all")

    def test_new_bounds_on_the_free_share_hold_at_once(self):
        """The mainnet's 1 GiB share (2026-11-12): a Q kept from before the ceiling came down is read under it, and the
        hourly step stores it so, instead of creeping down 0.4 % an hour."""
        from mutis import cleanup
        s = Stack({"limits": {"disk_cap_bytes": 20 * GiB, "reserve_min_bytes": 10 * GiB,
                              "quota_floor_bytes": GiB, "quota_ceiling_bytes": GiB}})
        try:
            s.disk.total, s.disk.avail = 100 * GiB, 80 * GiB
            with db.tx(s.conn):
                db.set_meta(s.conn, "free_quota_bytes", str(3 * GiB // 2))
            pool = quota.measure(s.conn, s.disk, s.cfg.data_dir, s.cfg["limits"], s.now)
            self.assertEqual(quota.free_quota(s.conn, pool), GiB)
            cleanup.hourly(s.conn, pool, s.now)
            self.assertEqual(db.get_meta(s.conn, "free_quota_bytes"), str(GiB))
            self.assertEqual(s.request("GET", "/api/v1/stats")[2]["free_quota_bytes"], GiB)
        finally:
            s.close()

    def test_the_stats_show_our_share_of_the_disk(self):
        """/stats (and /made's "free of" line) count the cap and the room left in it, not the whole shared disk."""
        st = self.s.request("GET", "/api/v1/stats")[2]
        self.assertLess(abs(st["disk_total_bytes"] - 20 * GiB), GiB // 10)
        self.assertLess(abs(st["disk_free_bytes"] - 20 * GiB), GiB // 10)
        self.assertEqual(st["disk_used_pct"], 0)

    def test_the_cap_is_for_the_disk(self):
        base = {"public_origin": "https://x.example", "memo_origins": ["https://x.example"]}
        with self.assertRaises(config.ConfigError):
            config.from_dict({**base, "limits": {"disk_cap_bytes": -1}})
        with self.assertRaises(config.ConfigError):
            config.from_dict({**base, "limits": {"disk_cap_bytes": 1 << 30, "capacity_bytes": 1 << 40},
                              "storage": {"backend": "s3", "s3_endpoint": "https://s3.example.com", "s3_region": "x-1",
                                          "s3_bucket": "hidebox-test"}})


class Settings(unittest.TestCase):
    def raw(self, **storage_kw):
        base = {"public_origin": "https://x.example", "memo_origins": ["https://x.example"],
                "storage": {"backend": "s3", "s3_endpoint": "https://s3.eu-central-003.backblazeb2.com",
                            "s3_region": "eu-central-003", "s3_bucket": "hidebox-blobs", **storage_kw},
                "limits": {"capacity_bytes": 1 << 40}}
        return base

    def test_an_s3_store_needs_its_capacity_and_a_real_endpoint(self):
        config.from_dict(self.raw())
        bad = self.raw()
        bad["limits"] = {"capacity_bytes": 0}
        for raw in (bad, self.raw(s3_endpoint="http://s3.example.com"), self.raw(s3_bucket=""),
                    self.raw(s3_key_file="relative.key"), self.raw(keep_local_max_bytes=1024), self.raw(backend="ftp")):
            with self.subTest(raw=raw["storage"]), self.assertRaises(config.ConfigError):
                config.from_dict(raw)

    def test_the_free_share_bounds_are_whole_steps(self):
        base = {"public_origin": "https://x.example", "memo_origins": ["https://x.example"]}
        for floor, ceiling in ((100 << 20, 1 << 30), (1 << 30, (1 << 30) + 1), (0, 1 << 30)):
            with self.subTest(floor=floor, ceiling=ceiling), self.assertRaises(config.ConfigError):
                config.from_dict({**base, "limits": {"quota_floor_bytes": floor, "quota_ceiling_bytes": ceiling}})

    def test_config_and_quota_agree_on_their_shared_numbers(self):
        self.assertEqual((config.INLINE_MAX_STORED, config.QUOTA_STEP), (quota.INLINE_MAX_STORED, quota.QUOTA_STEP))

    def test_the_disk_takes_no_capacity(self):
        with self.assertRaises(config.ConfigError):
            config.from_dict({"public_origin": "https://x.example", "memo_origins": ["https://x.example"],
                              "limits": {"capacity_bytes": 1 << 40}})

    def test_the_free_share_bounds(self):
        cfg = config.from_dict({"public_origin": "https://x.example", "memo_origins": ["https://x.example"],
                                "limits": {"quota_floor_bytes": 1 * GiB, "quota_ceiling_bytes": 10 * GiB}})
        limits = cfg["limits"]
        small = quota.compute(100 * GiB, 1 * GiB, 0, 0, 100, {**limits, "reserve_min_bytes": 0})
        big = quota.compute(1 << 42, 1 << 42, 0, 0, 100, limits)
        self.assertEqual((small.q_target, big.q_target), (1 * GiB, 10 * GiB))
        with self.assertRaises(config.ConfigError):
            config.from_dict({"public_origin": "https://x.example", "memo_origins": ["https://x.example"],
                              "limits": {"quota_floor_bytes": 2 * GiB, "quota_ceiling_bytes": 1 * GiB}})


if __name__ == "__main__":
    unittest.main()
