# SPDX-License-Identifier: MIT
"""Sixth pass (anti-griefing): space packs and the free-space brakes (server/mutis/packs.py).

The owner's concern: someone buys space from many drives very fast, so the disk saturates, the packs
sell out at once, or free uploads freeze for everyone. Each rule here is one of the decisions taken:
judges' slice of the paid cap, one pack per drive (renewable in its last days), sales brakes per network
and per day, the 5 GiB big pack, the free-space brakes, the numbers the healthcheck and /stats show, and
the kill switch.
"""
import unittest

from harness import GiB, Disk, Stack
from mutis import auth, codec, config, db, packs, payments, quota
from mutis.fake_chain import fake_keys

MiB = 1 << 20
NET = "203.0.113.9"                  # a visitor's IPv4 address (the default 127.0.0.1 is the server's own)


class Base(unittest.TestCase):
    OVERRIDES: dict = {}

    def setUp(self):
        self.s = Stack(self.OVERRIDES)
        self.n = 0
        self.s.disk = Disk(total=100 * GiB, avail=36 * GiB)      # pool 26 GiB: cap 10.4, judges 3.12, public 7.28
        self.s.app.statvfs = self.s.disk
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "receiver_address", fake_keys()["address"])

    def tearDown(self):
        self.s.close()

    def judge(self) -> dict:
        code = auth.new_judge_code()
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO judge_passes(code_hash, uses_left, created_at, pow_skips_left) "
                                "VALUES (?, 5, ?, 100)", (auth.judge_hash(code), self.s.now))
        return {"X-Mutis-Judge": code}

    def new_drive(self) -> dict:
        """A drive made from an address of its own (the hourly registration limit stays out of the way)."""
        self.n += 1
        return self.s.register(ip=f"198.18.{self.n // 200}.{self.n % 200 + 1}")

    def refresh(self, drive: dict) -> dict:
        """A new session after the clock moved weeks ahead."""
        with db.tx(self.s.conn):
            token, _ = auth.create_session(self.s.conn, drive["id"], self.s.now)
        return {**drive, "auth": {"Authorization": "Bearer " + codec.b64u(token)}}

    def buy(self, pack: str, drive: dict | None = None, headers: dict | None = None, ip: str | None = None):
        drive = drive or self.new_drive()
        status, hdrs, body = self.s.request("POST", "/api/v1/invoices", {"pack": pack},
                                            headers={**drive["auth"], **(headers or {})}, ip=ip)
        return status, (body.get("error", {}).get("code") if status >= 400 else body), hdrs

    def grant(self, drive: dict, pack: str, judge: bool = False) -> None:
        with db.tx(self.s.conn):
            payments.grant_pack(self.s.conn, drive["id"], pack, self.s.now, judge)

    def slices(self) -> packs.Slices:
        pool = quota.measure(self.s.conn, self.s.disk, self.s.cfg.data_dir, self.s.cfg["limits"], self.s.now)
        return packs.slices(self.s.conn, pool, self.s.cfg["packs"], self.s.now)


class Slices(Base):
    def test_judges_have_a_slice_the_public_cant_take(self):
        s = self.slices()
        self.assertEqual((s.cap, s.judge_cap), (int(0.4 * 26 * GiB), int(0.3 * int(0.4 * 26 * GiB))))
        self.assertEqual(self.buy("m30")[0], 201)
        self.assertEqual(self.buy("s30")[0], 201)                    # 7 of 7.28 GiB, open invoices count
        self.assertEqual(self.buy("s30")[:2], (409, "sold_out"))       # the public slice is full
        self.assertEqual(self.buy("s30", headers=self.judge())[0], 201)    # the judges' slice still sells
        self.assertEqual(self.buy("s30", headers=self.judge())[:2], (409, "sold_out"))   # its spill finds no room

    def test_judges_spill_into_the_public_slice_when_theirs_is_used(self):
        for _ in range(2):
            self.assertEqual(self.buy("s30", headers=self.judge())[0], 201)    # 4 GiB: 0.88 over the judges' 3.12
        self.assertEqual(self.slices().judge_spill, 4 * GiB - self.slices().judge_cap)
        self.assertEqual(self.buy("m30")[0], 201)                    # 0.88 + 5 of 7.28
        self.assertEqual(self.buy("s30")[:2], (409, "sold_out"))       # 0.88 + 7 > 7.28

    def test_active_packs_count_and_expired_ones_dont(self):
        a, b = self.new_drive(), self.new_drive()
        self.grant(a, "m30")
        self.grant(b, "s30", judge=True)
        s = self.slices()
        self.assertEqual((s.public_active, s.judge_active), (5 * GiB, 2 * GiB))
        self.s.now += 31 * 86400
        self.s.heartbeat()
        self.assertEqual((self.slices().public_active, self.slices().judge_active), (0, 0))

    def test_the_big_pack_is_5_gib_for_1_ttari(self):
        self.assertEqual(quota.PACKS["m30"], {"bytes": 5 * GiB, "days": 30, "price_ut": 1_000_000})
        self.assertEqual(quota.PACKS["s30"], {"bytes": 2 * GiB, "days": 30, "price_ut": 500_000})


class OnePackPerDrive(Base):
    def test_a_drive_with_a_pack_is_refused_until_its_last_days(self):
        drive = self.new_drive()
        self.grant(drive, "s30")
        until = self.s.now + 30 * 86400
        status, code, _ = self.buy("s30", drive)
        self.assertEqual((status, code), (409, "pack_active"))
        body = self.s.request("POST", "/api/v1/invoices", {"pack": "m30"}, headers=drive["auth"])[2]["error"]
        self.assertEqual(body["details"], {"pack": "s30", "bytes": 2 * GiB, "until": until,
                                           "renew_from": until - 3 * 86400})
        self.assertTrue(body["message"].startswith("You already have 2 GiB until "))
        me = self.s.request("GET", "/api/v1/me", headers=drive["auth"])[2]
        self.assertEqual(me["pack"], {"id": "s30", "bytes": 2 * GiB, "until": until, "renew_from": until - 3 * 86400})
        self.s.now = until - 3 * 86400 + 60                           # the renewal window
        self.s.heartbeat()
        drive = self.refresh(drive)
        self.assertEqual(self.buy("m30", drive)[:2], (409, "pack_active"))   # renew with the same pack only
        self.assertEqual(self.buy("s30", drive)[0], 201)

    def test_a_renewal_stacks_days_not_bytes(self):
        drive = self.new_drive()
        self.grant(drive, "s30")
        until = self.s.now + 30 * 86400
        self.s.now = until - 86400
        self.grant(drive, "s30")
        row = self.s.conn.execute("SELECT paid_bytes, paid_until, paid_pack FROM identities WHERE id = ?",
                                  (drive["id"],)).fetchone()
        self.assertEqual(tuple(row), (2 * GiB, until + 30 * 86400, "s30"))

    def test_a_renewal_reserves_no_bytes_and_passes_a_full_slice(self):
        drive = self.new_drive()
        self.grant(drive, "s30")
        self.grant(self.new_drive(), "m30")                          # 2 + 5 of 7.28 GiB, active
        self.assertEqual(self.buy("s30")[:2], (409, "sold_out"))
        self.s.now += 28 * 86400
        self.s.heartbeat()
        self.assertEqual(self.buy("s30")[:2], (409, "sold_out"))
        self.assertEqual(self.buy("s30", self.refresh(drive))[0], 201)   # its own 2 GiB are already counted

    def test_an_open_invoice_is_handed_back_and_a_swap_costs_no_second_sale(self):
        drive = self.s.register(ip=NET)
        status, first, _ = self.buy("s30", drive, ip=NET)
        self.assertEqual(status, 201)
        status, again, _ = self.buy("s30", drive, ip=NET)
        self.assertEqual((status, again["invoice_id"]), (200, first["invoice_id"]))
        status, swapped, _ = self.buy("m30", drive, ip=NET)               # the drive changed its mind
        self.assertEqual(status, 201)
        old = self.s.conn.execute("SELECT status FROM invoices WHERE id = ?", (first["invoice_id"],)).fetchone()[0]
        self.assertEqual(old, "expired")
        self.assertEqual(packs.sold_today(self.s.conn, self.s.now, False), 1)
        self.s.disk = Disk(total=100 * GiB, avail=14 * GiB)      # a refused swap keeps the invoice it would replace
        self.s.app.statvfs = self.s.disk
        status, code, _ = self.buy("s30", drive, ip=NET)
        self.assertEqual((status, code), (409, "sold_out"))
        self.assertEqual(self.buy("m30", drive, ip=NET)[:2], (200, swapped))


class Brakes(Base):
    def setUp(self):
        super().setUp()
        self.s.disk = Disk()                                  # room enough: only the brakes say no here
        self.s.app.statvfs = self.s.disk

    def test_one_pack_a_day_per_network_and_two_with_a_judge_pass(self):
        self.assertEqual(self.buy("s30", self.s.register(ip=NET), ip=NET)[0], 201)
        status, code, hdrs = self.buy("s30", self.s.register(ip=NET), ip=NET)
        self.assertEqual((status, code), (429, "packs_limited"))
        self.assertEqual(int(hdrs["Retry-After"]), codec.next_utc_midnight(self.s.now) - self.s.now)
        other = "203.0.113.10"
        self.assertEqual(self.buy("s30", self.s.register(ip=other), ip=other)[0], 201)   # another network
        judge = self.judge()
        net = "198.51.100.4"
        for expected in (201, 201, 429):
            self.assertEqual(self.buy("s30", self.s.register(ip=net), headers=judge, ip=net)[0], expected)
        # Two a day per pass as well, from any network (the devil's finding: one pass over many networks).
        self.assertEqual(self.buy("s30", self.new_drive(), headers=judge, ip="198.51.100.5")[:2], (429, "packs_limited"))
        self.assertEqual(self.buy("s30", self.new_drive(), headers=self.judge(), ip="198.51.100.5")[0], 201)
        self.s.now = codec.next_utc_midnight(self.s.now) + 60     # a new UTC day forgets the networks
        self.s.heartbeat()
        self.assertEqual(self.buy("s30", self.s.register(ip=NET), ip=NET)[0], 201)

    def test_three_public_packs_a_day_and_ten_with_judge_passes(self):
        nets = iter(f"192.0.2.{i}" for i in range(1, 200))         # each purchase from a network of its own

        def buy(**kw):
            return self.buy("s30", ip=next(nets), **kw)[:2]
        for _ in range(3):
            self.assertEqual(buy()[0], 201)
        self.assertEqual(buy(), (429, "packs_limited"))
        self.assertEqual(self.buy("s30")[0], 201)                  # the server's own address isn't held to it...
        self.assertEqual(packs.sold_today(self.s.conn, self.s.now, False), 4)   # ...but what it buys counts
        for _ in range(10):
            self.assertEqual(buy(headers=self.judge())[0], 201)    # their own ceiling (one pass each)
        self.assertEqual(buy(headers=self.judge()), (429, "packs_limited"))
        self.s.now += payments.INVOICE_TTL_S + 1                    # unpaid invoices ran out: their places free up
        self.s.heartbeat()
        self.assertEqual(buy()[0], 201)

    def test_our_evidence_invoice_and_a_refused_purchase_dont_count(self):
        with db.tx(self.s.conn):                                    # chain_worker.evidence_payment's row
            self.s.conn.execute("INSERT INTO invoices(id, identity_id, pack, price_ut, address, status, created_at, "
                                "expires_at) VALUES ('inv_evidence', NULL, 's30', 500000, 'a', 'pending', ?, ?)",
                                (self.s.now, self.s.now + 3600))
        self.assertEqual(packs.sold_today(self.s.conn, self.s.now, False), 0)
        self.s.disk = Disk(total=100 * GiB, avail=14 * GiB)      # pool 4 GiB: a 1.12 GiB public slice
        self.s.app.statvfs = self.s.disk
        drive = self.s.register(ip=NET)
        self.assertEqual(self.buy("s30", drive, ip=NET)[:2], (409, "sold_out"))
        self.s.disk = Disk()
        self.s.app.statvfs = self.s.disk
        self.assertEqual(self.buy("s30", drive, ip=NET)[0], 201)      # the refusal gave the network's sale back

    def test_the_kill_switch_stops_sales_and_test_money_at_once(self):
        drive = self.new_drive()
        status, inv, _ = self.buy("s30", drive)
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "features", {"packs": False})
        self.s.app._features = (0.0, {})
        status, _, body = self.s.request("POST", "/api/v1/invoices", {"pack": "s30"}, headers=self.new_drive()["auth"])
        self.assertEqual((status, body["error"]["code"], body["error"]["details"]), (503, "feature_disabled",
                                                                                     {"feature": "packs"}))
        status, _, body = self.s.request("POST", f"/api/v1/invoices/{inv['invoice_id']}/demo-pay",
                                         {"pow": self.s.solve("demo_pay")}, headers=drive["auth"])
        self.assertEqual((status, body["error"]["details"]), (503, {"feature": "packs"}))
        config = self.s.request("GET", "/api/v1/config")[2]
        self.assertFalse(config["features"]["packs"])


class FreeSpaceBrakes(Base):
    # The numbers scaled down a tenth (a reservation makes a real file of its size): 200 MiB a network,
    # 600 MiB a /48, 800 MiB with a judge pass.
    OVERRIDES = {"brakes": {"upload_bytes_per_network_day": 200 * MiB, "upload_bytes_per_wide_network_day": 600 * MiB,
                            "judge_upload_bytes_per_network_day": 800 * MiB}}

    def setUp(self):
        super().setUp()
        self.s.disk = Disk()
        self.s.app.statvfs = self.s.disk
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "free_quota_bytes", str(5 * GiB))

    def test_five_new_drives_a_day_per_network_unless_a_judge_pass(self):
        for _ in range(5):
            self.s.register(ip=NET)
        self.s.now += 7200                                     # past the hourly limit: the daily one answers
        status, _, body = self.s.request("POST", "/api/v1/auth/register", {
            "identity_id": codec.b64u(b"x" * 16), "auth_verifier": codec.b64u(b"y" * 32),
            "pow": self.s.solve("register", NET)}, ip=NET)
        self.assertEqual((status, body["error"]["code"]), (429, "drives_limited"))
        status, _, body = self.s.request("POST", "/api/v1/auth/register", {
            "identity_id": codec.b64u(b"x" * 16), "auth_verifier": codec.b64u(b"y" * 32)},
            headers=self.judge(), ip=NET)
        self.assertEqual(status, 201, body)

    def test_twenty_new_drives_a_day_per_48_whatever_its_64s(self):
        for i in range(20):
            self.s.register(ip=f"2001:db8:aa:{i:x}::1")
        self.s.now += 7200                                     # past the hourly limit: the daily one answers
        status, _, body = self.s.request("POST", "/api/v1/auth/register", {
            "identity_id": codec.b64u(b"z" * 16), "auth_verifier": codec.b64u(b"y" * 32),
            "pow": self.s.solve("register", "2001:db8:aa:99::1")}, ip="2001:db8:aa:99::1")
        self.assertEqual((status, body["error"]["code"]), (429, "drives_limited"))

    def drive(self, ip: str = NET, judge: dict | None = None) -> dict:
        d = self.s.register(ip=ip)
        self.s.graduate(d)
        return {**d, "auth": {**d["auth"], **(judge or {})}}

    def reserve(self, drive: dict, mib: int, ip: str = NET) -> tuple[int, str | None]:
        status, up = self.s.start_upload(mib * MiB - 4096, headers=drive["auth"], ip=ip)
        return status, (up["error"]["code"] if status >= 400 else None)

    def test_a_network_s_free_uploads_a_day(self):
        a, b = self.drive(), self.drive()
        for drive in (a, a, b, b):
            self.assertEqual(self.reserve(drive, 45), (201, None))   # 180 MiB of 200
        self.assertEqual(self.reserve(b, 45), (429, "uploads_limited"))
        self.assertEqual(self.reserve(b, 15), (201, None))           # what's left still fits
        other = "203.0.113.77"
        self.assertEqual(self.reserve(self.drive(other), 45, other), (201, None))
        self.s.now = codec.next_utc_midnight(self.s.now) + 60        # a new UTC day
        self.assertEqual(self.reserve(b, 45), (201, None))

    def test_a_judge_pass_has_its_own_and_a_paid_drive_its_pack(self):
        judge = self.judge()
        d = self.drive(judge=judge)
        for _ in range(6):
            self.assertEqual(self.reserve(d, 45), (201, None))   # 270 MiB: past the public allowance
        other = self.drive("203.0.113.88", judge=judge)              # the same pass elsewhere shares its 800 MiB
        results = [self.reserve(other, 45, "203.0.113.88")[1] for _ in range(14)]
        self.assertEqual((results.count(None), results[-1]), (11, "uploads_limited"))
        paid = self.drive()
        self.grant(paid, "m30")
        for _ in range(6):
            self.assertEqual(self.reserve(paid, 45), (201, None))   # bounded by its pack, not the network
        self.assertEqual(self.reserve(self.drive(), 45), (201, None))   # the network's own allowance untouched

    def test_a_refused_upload_gives_its_bytes_back(self):
        d = self.drive()
        with db.tx(self.s.conn):
            db.set_meta(self.s.conn, "free_quota_bytes", str(64 * MiB))
        self.assertEqual(self.reserve(d, 45), (201, None))
        self.assertEqual(self.reserve(d, 45)[0], 507)             # quota_exceeded: over the drive's quota
        self.assertEqual(self.s.app.daily.used("upbytes64", self.s.app.ipkeys.keys(NET, self.s.now)[0]),
                         quota.stored_size(quota.padme(45 * MiB - 4096)))


class Visibility(Base):
    def test_stats_show_the_public_slice_in_whole_gib(self):
        a, j = self.new_drive(), self.new_drive()
        self.grant(a, "s30")
        self.grant(j, "m30", judge=True)                       # 5 of 3.12: 1.88 spills into the public slice
        stats = self.s.request("GET", "/api/v1/stats")[2]
        cap = int(0.4 * 26 * GiB) - int(0.3 * int(0.4 * 26 * GiB))
        self.assertEqual(stats["packs_cap_public"], cap - cap % GiB)
        sold = 2 * GiB + 5 * GiB - int(0.3 * int(0.4 * 26 * GiB))
        self.assertEqual(stats["packs_sold_public"], sold - sold % GiB)

    def test_cleanup_writes_what_the_healthcheck_reads(self):
        self.s.disk = Disk()
        self.s.app.statvfs = self.s.disk
        self.s.run_cleanup()
        note = db.get_meta_json(self.s.conn, "packs", {})
        self.assertEqual((note["public_80"], note["ceiling_hit"], note["day"]), (False, False, codec.day(self.s.now)))
        for _ in range(3):
            self.buy("s30")
        self.s.run_cleanup()
        self.assertTrue(db.get_meta_json(self.s.conn, "packs", {})["ceiling_hit"])
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE invoices SET status = 'expired', expires_at = ?", (self.s.now,))
        self.s.disk = Disk(total=100 * GiB, avail=22 * GiB)     # pool 12 GiB: 3.36 public, 2 GiB held is 60 %
        self.grant(self.new_drive(), "s30")
        self.s.run_cleanup()
        self.assertFalse(db.get_meta_json(self.s.conn, "packs", {})["public_80"])
        self.grant(self.new_drive(), "s30")                    # 4 of 3.36: over 80 %
        self.s.run_cleanup()
        self.assertTrue(db.get_meta_json(self.s.conn, "packs", {})["public_80"])


class Config(unittest.TestCase):
    def test_brake_settings_are_checked(self):
        base = {"public_origin": "https://x.example", "memo_origins": ["https://x.example"]}
        with self.assertRaises(config.ConfigError):
            config.from_dict({**base, "brakes": {"exempt_addresses": ["not an address"]}})
        with self.assertRaises(config.ConfigError):
            config.from_dict({**base, "packs": {"judge_fraction": 1.5}})
        cfg = config.from_dict({**base, "brakes": {"exempt_addresses": ["192.0.2.1", "2001:db8::/64"]}})
        self.assertEqual(cfg["packs"]["public_per_day"], 3)


if __name__ == "__main__":
    unittest.main()
