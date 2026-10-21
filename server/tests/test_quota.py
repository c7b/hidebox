# SPDX-License-Identifier: MIT
"""S-04: quota math (spec §9.2 worked examples), lanes, concurrent reservations, freeze, probation, N."""
import json
import threading
import unittest
from pathlib import Path

from harness import GiB, Stack
from mutis import codec, db, lanes, quota

VECTORS = json.loads((Path(__file__).parent / "vectors" / "quota.json").read_text())
MiB = 1 << 20


class Formula(unittest.TestCase):
    def test_vectors(self):
        for case in VECTORS["cases"]:
            i = case["in"]
            p = quota.compute(i["d_total"], i["d_avail"], i["stored"], i["paid"], i["n_active"], VECTORS["limits"])
            got = {"reserve": p.reserve, "pool": p.pool, "anon": p.anon, "free_pool": p.free_pool, "n": p.n,
                   "q_target": p.q_target}
            self.assertEqual(got, case["out"], case["name"])

    def test_spec_worked_examples(self):
        q = {c["name"]: c["out"]["q_target"] for c in VECTORS["cases"]}
        self.assertEqual(q["99 GB disk, 20 GB used, nothing stored, N=100 (spec §9.2)"], 2240 * MiB)   # 2.19 GiB
        self.assertEqual(q["same disk, N=300"], 704 * MiB)
        self.assertEqual(q["same disk, N=1000 hits the 256 MiB floor"], 256 * MiB)
        first = VECTORS["cases"][0]["out"]
        self.assertAlmostEqual(first["pool"] / 1e9, 68.3, places=1)
        self.assertAlmostEqual(first["anon"] / 1e9, 5.5, places=1)
        self.assertAlmostEqual(first["free_pool"] / 1e9, 59.6, places=1)

    def test_padme(self):
        for n, padded in VECTORS["padme"]:
            self.assertEqual(quota.padme(n), padded)
        self.assertEqual(quota.padme(1_000_000), 1_015_808)
        self.assertEqual(quota.padme(5_000_000), 5_111_808)
        self.assertEqual(quota.padme(4097), 4352)
        for n in range(1025, 200_000, 997):
            self.assertLessEqual(quota.padme(n) / n, 1.12)

    def test_smoothing(self):
        for old, target, new in VECTORS["smooth_hourly"]:
            self.assertEqual(quota.smooth(old, target), new)
        self.assertEqual(quota.smooth(1000, 2000), 1008)
        self.assertEqual(quota.smooth(1000, 0), 996)


class Lanes(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def _fill(self, lane: str, size: int) -> None:
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO items(id, manage_hash, retention, lane, state, header, meta_ct, "
                                "chunk_count, size_stored, created_hour) VALUES (?, x'00', 'ephemeral', ?, 'ready', "
                                "x'00', x'00', 1, ?, 0)", (codec.new_id(), lane, size))

    def test_concurrent_reservations_never_exceed_the_lane(self):
        self.s = Stack({"limits": {"small_lane_bytes": 5 * MiB}})
        _, size = self.s.layout(500_000)
        statuses, lock = [], threading.Lock()
        solutions = [self.s.solve("upload", ip=f"203.0.113.{i}") for i in range(20)]

        def one(i: int) -> None:
            status, _ = self.s.start_upload(500_000, ip=f"203.0.113.{i}", pow=solutions[i])
            with lock:
                statuses.append(status)

        threads = [threading.Thread(target=one, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        used = self.s.conn.execute("SELECT SUM(size_stored) FROM items WHERE lane = 'small'").fetchone()[0]
        self.assertEqual(statuses.count(201), (5 * MiB) // size)
        self.assertEqual(statuses.count(507), 20 - (5 * MiB) // size)
        self.assertLessEqual(used, 5 * MiB)

    def test_small_lane_demo_reserve(self):
        self.s = Stack({"limits": {"small_lane_bytes": 200 * MiB}})
        self._fill("small", 100 * MiB)
        status, body = self.s.start_upload(2 * MiB)
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]), (507, "lane_full",
                                                                                     {"lane": "small"}))
        status, _ = self.s.start_upload(500_000)
        self.assertEqual(status, 201)

    def test_freeze_thresholds(self):
        self.s = Stack()
        locker = self.s.register()
        reserve = 10 * GiB          # max(10 GiB, 10 % of a 100 GiB disk)
        self.s.disk.avail = reserve + GiB
        status, body = self.s.start_upload(6 * MiB)
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["scope"]),
                         (503, "uploads_frozen", "free"))
        self.assertEqual(self.s.start_upload(1000)[0], 201)                     # SMALL keeps working
        status, body = self.s.start_upload(1000, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"]), (503, "uploads_frozen"))
        self.assertEqual(self.s.request("GET", "/api/v1/stats")[2]["uploads_frozen"], "free")
        self.s.disk.avail = reserve + 100 * MiB
        status, body = self.s.start_upload(1000)
        self.assertEqual((status, body["error"]["details"]["scope"]), (503, "all"))
        self.s.disk.avail = 80 * GiB
        self.assertEqual(self.s.start_upload(1000)[0], 201)

    def test_n_counts_only_lockers_active_on_two_days_that_store_something(self):
        """Review L6: lockers made only to be counted (a request on a second day, nothing stored) don't
        push the free quota down."""
        self.s = Stack()
        today = codec.day(self.s.now)
        with db.tx(self.s.conn):
            for _ in range(300):
                self.s.conn.execute("INSERT INTO identities(id, auth_verifier, created_day, last_seen_day, "
                                    "distinct_days) VALUES (?, x'00', ?, ?, 1)", (codec.new_id(), today, today))
        pool = quota.measure(self.s.conn, self.s.disk, ".", self.s.cfg["limits"], self.s.now)
        self.assertEqual(pool.n, 100)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET distinct_days = 2")
        pool = quota.measure(self.s.conn, self.s.disk, ".", self.s.cfg["limits"], self.s.now)
        self.assertEqual(pool.n, 100)
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET used_bytes = 1024")
        pool = quota.measure(self.s.conn, self.s.disk, ".", self.s.cfg["limits"], self.s.now)
        self.assertEqual(pool.n, 300)

    def test_paid_locker_limits(self):
        """Even the small pack lifts a drive's largest file past a free drive's 512 MiB."""
        self.s = Stack()
        locker = self.s.register()
        self.s.graduate(locker)
        status, body = self.s.start_upload(600 * MiB, headers=locker["auth"])
        self.assertEqual((status, body["error"]["details"]["class"]), (413, "locker"))
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET paid_bytes = ?, paid_until = ?, paid_pack = 's30' WHERE id = ?",
                                (quota.PACKS["s30"]["bytes"], self.s.now + 86400, locker["id"]))
        status, body = self.s.start_upload(600 * MiB, headers=locker["auth"])
        self.assertEqual(status, 201)

    def test_a_paid_drive_s_largest_file_must_also_fit_its_room(self):
        """The paid class takes files up to 2 GiB, more than either pack (256 MiB, 1 GiB). That cap is per
        file, like a free drive's 512 MiB under a free quota that can be 256 MiB: the file must also fit the
        drive's room, the free quota plus its pack. With the small pack, a 2 GiB file fits while the free
        quota is 2 GiB (the deployment's today) and is refused when it is 1 GiB, with 507 quota_exceeded and
        the room, not 413 too_large, before any byte is reserved. /config and /me say both numbers."""
        self.s = Stack()
        locker = self.s.register()
        self.s.graduate(locker)
        small = quota.PACKS["s30"]["bytes"]
        self.assertLess(max(p["bytes"] for p in quota.PACKS.values()), quota.CLASSES["paid"]["max_file_bytes"])
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE identities SET paid_bytes = ?, paid_until = ?, paid_pack = 's30' WHERE id = ?",
                                (small, self.s.now + 86400, locker["id"]))
            db.set_meta(self.s.conn, "free_quota_bytes", str(GiB))
        status, body = self.s.start_upload(2 * GiB, headers=locker["auth"])
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]), (507, "quota_exceeded",
                                                                                     {"limit_bytes": GiB + small}))
        me = self.s.request("GET", "/api/v1/me", headers=locker["auth"])[2]
        self.assertEqual((me["plan"], me["limits"]["max_file_bytes"], me["quota"]["limit_bytes"], me["quota"]["reserved_bytes"]),
                         ("paid", 2 * GiB, GiB + small, 0))
        config = self.s.request("GET", "/api/v1/config")[2]
        self.assertEqual(config["limits"]["paid"]["max_file_bytes"], 2 * GiB)
        status, body = self.s.start_upload(2 * GiB + 1, headers=locker["auth"])     # past the cap: too large
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]["class"]), (413, "too_large", "paid"))
        # With a 2 GiB free quota there is room: admitted (checked here without allocating a 2 GiB file).
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "free_quota_bytes", str(2 * GiB))
        _, size = self.s.layout(2 * GiB)
        identity = self.s.conn.execute("SELECT * FROM identities WHERE id = ?", (locker["id"],)).fetchone()
        pool = quota.measure(self.s.conn, self.s.disk, ".", self.s.cfg["limits"], self.s.now)
        lanes.check_file_size("paid", size)
        lanes.admit_locker(self.s.conn, pool, identity, size, "none", self.s.now)
        self.assertLessEqual(size, 2 * GiB + small)


if __name__ == "__main__":
    unittest.main()
