# SPDX-License-Identifier: MIT
"""Withdrawing earnings (docs/withdraw.md, server/mutis/withdraw.py), behind features.withdraw: the flag; what a drive
may withdraw (settled payments only, the same rule as Earnings, plus change of its own withdrawals) and what still
waits; a signed withdrawal checked (shape, inputs, change), marked before the relay so the same money can't go twice,
relayed; the drive's report of the outcome (commit spends, reject frees); the pending window; a relay that fails frees
everything; the limits. Envelopes are the official library's (fixtures/stealth-envelopes.json) with their inputs
pointed at this test's outputs; our server checks structure, the network checks signatures."""
import base64
import json
import os
import tracemalloc
from pathlib import Path

from harness import Stack
from paid_fixture import V, PaidCase
import cbor_fixture  # noqa: E402,I100 (after harness, which puts server/ on the path)
from mutis import cleanup, codec, db, withdraw
from mutis.fake_chain import fake_keys
from mutis.http_util import ApiError
from mutis.indexer import IndexerError

FIXTURES = Path(__file__).with_name("fixtures")
ENVELOPES = json.loads((FIXTURES / "stealth-envelopes.json").read_text())
RESOURCE = "01" * 32
ON = {"features": {"withdraw": True}}


def utxo() -> str:
    return f"utxo_{RESOURCE}_{os.urandom(32).hex()}"


def envelope(inputs: list[str], outputs: int = 2, fee: int | None = None) -> tuple[str, list[str]]:
    """The fixture withdrawal spending `inputs` (utxo ids) → (base64, its outputs' utxo ids)."""
    env = cbor_fixture.decode(ENVELOPES["two_inputs"])
    unsigned, signatures = env[1][0][0]
    unsigned[3] = [unsigned[3][0]] + [[[8, [[bytes.fromhex(u.split("_")[1]), bytes.fromhex(u.split("_")[2])]]], None, True]
                                      for u in inputs]
    signatures[:] = [signatures[0]] * len(inputs)
    statement = unsigned[1][0][1][1]
    statement[1][0] = (statement[1][0] * 2)[:outputs]
    if fee is not None:
        statement[1][1][0] = fee
    made = [f"utxo_{RESOURCE}_{bytes(o[0][0]).hex()}" for o in statement[1][0]]
    return base64.b64encode(cbor_fixture.encode(env)).decode(), made


class WithdrawCase(PaidCase):
    chain = False

    def setUp(self):
        self.s = Stack(ON)
        self.s.quiet_chain()
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.sales_keys = fake_keys()
        self.ready_seller()
        self.link = self.sell(self.kept()["item_id"])

    def payment(self, value=100000, status="counted", demo=True, owner_ok=None, d=None, link=None) -> str:
        """A sale payment to this drive's pay link, as the payment checker records it."""
        link = link or self.link
        uid = utxo()
        cid = "clm_" + codec.random_chars("abcdefghijklmnopqrstuvwxyz234567", 20)
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO claims(id, share_id, token_hash, address, price_ut, received_ut, status, created_at, "
                                "created_seq, expires_at, demo) VALUES (?, ?, ?, 'a', ?, ?, 'released', ?, 0, ?, ?)",
                                (cid, link["share_id"], os.urandom(32), value, value, self.s.now, self.s.now + 3600, int(demo)))
            self.s.conn.execute("INSERT INTO sale_payments(utxo_id, claim_id, value_ut, seen_at, status, committed, owner_ok) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)", (uid, cid, value, self.s.now, status,
                                                                 int(status != "pending_check"), owner_ok))
        return uid

    def listing(self, d=None) -> dict:
        status, _, body = self.s.request("GET", f"{V}/me/sales/outputs", headers=(d or self.d)["auth"])
        self.assertEqual(status, 200, body)
        return body

    def submit(self, inputs, expect=201, outputs=2, fee=None, d=None) -> dict:
        text, _made = envelope(inputs, outputs, fee)
        status, _, resp = self.s.request("POST", f"{V}/me/withdrawals", {"transaction": text}, headers=(d or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return resp

    def report(self, tx, outcome, expect=200, d=None) -> dict:
        status, _, resp = self.s.request("POST", f"{V}/me/withdrawals/{tx}", {"outcome": outcome}, headers=(d or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return resp

    def row(self, uid):
        return self.s.conn.execute("SELECT withdraw_tx, withdraw_at, withdrawn FROM sale_payments WHERE utxo_id = ?", (uid,)).fetchone()


class FeatureFlag(PaidCase):
    chain = False

    def test_off_by_default(self):
        cfg = self.s.request("GET", f"{V}/config")[2]
        self.assertIs(cfg["features"]["withdraw"], False)
        self.assertEqual(cfg["withdraw"], {"fee_ut": "30000", "min_ut": "60000", "dust_ut": "30000", "max_inputs": 8,
                                           "pending_s": 600})
        for method, path in (("GET", "/me/sales/outputs"), ("POST", "/me/withdrawals"), ("POST", "/me/withdrawals/" + "0" * 64)):
            status, _, resp = self.s.request(method, V + path, {} if method == "POST" else None, headers=self.d["auth"])
            self.assertEqual((status, resp["error"]["details"]), (503, {"feature": "withdraw"}), path)


class Outputs(WithdrawCase):
    def test_only_settled_money_of_this_drive(self):
        demo = self.payment(100000)
        checked = self.payment(250000, demo=False, owner_ok=1)
        extra = self.payment(5000, status="extra", demo=False, owner_ok=1)
        self.payment(500000, status="pending_check")                 # still being counted
        self.payment(70000, demo=False, owner_ok=None)               # waiting for the owner's check
        self.payment(80000, demo=False, owner_ok=0)                  # the payer kept it: never this drive's
        other = self.s.register()
        self.s.graduate(other)
        self.register_seller(d=other, keys=fake_keys())
        with db.tx(self.s.conn):
            self.s.conn.execute("UPDATE sellers SET state = 'ok'")
        theirs = self.sell(self.kept(d=other)["item_id"], d=other)
        mine_too = self.payment(999000, link=theirs)
        got = self.listing()
        self.assertEqual({o["utxo_id"]: o["value_ut"] for o in got["outputs"]}, {demo: "100000", checked: "250000", extra: "5000"})
        self.assertTrue(all(o["source"] == "sale" and o["pending_tx"] is None for o in got["outputs"]))
        self.assertEqual(got["waiting"], {"payments": 2, "value_ut": "570000"})
        self.assertEqual((got["fee_ut"], got["min_ut"], got["max_inputs"]), ("30000", "60000", 8))
        self.assertEqual([o["utxo_id"] for o in self.listing(d=other)["outputs"]], [mine_too])   # each drive sees its own
        self.assertEqual(self.s.request("GET", f"{V}/me/sales/outputs")[0], 401)


class Submit(WithdrawCase):
    def test_a_withdrawal_is_marked_relayed_and_settled_by_the_drives_report(self):
        a, b = self.payment(100000), self.payment(250000)
        text, made = envelope([a, b])
        status, _, resp = self.s.request("POST", f"{V}/me/withdrawals", {"transaction": text,
                                         "change": {"utxo_id": made[1], "value_ut": "20000"}}, headers=self.d["auth"])
        self.assertEqual(status, 201, resp)
        tx = resp["tx_id"]
        self.assertRegex(tx, r"^[0-9a-f]{64}$")
        self.assertEqual(resp["inputs"], [a, b])
        self.assertEqual([self.row(u)["withdraw_tx"] for u in (a, b)], [tx, tx])
        listed = {o["utxo_id"]: o for o in self.listing()["outputs"]}
        self.assertEqual((listed[a]["pending_tx"], listed[made[1]]["source"], listed[made[1]]["pending_tx"]), (tx, "change", tx))
        # The same money again, while it is on its way: refused, and nothing else is marked.
        c = self.payment(40000)
        again = self.submit([c, a], expect=409)
        self.assertEqual((again["error"]["code"], again["error"]["details"]), ("withdraw_pending", {"utxo_id": a}))
        self.assertIsNone(self.row(c)["withdraw_tx"])
        # Change can't be spent before its withdrawal committed.
        self.assertEqual(self.submit([made[1]], expect=409)["error"]["code"], "not_withdrawable")
        self.report(tx, "commit")
        self.assertEqual([self.row(u)["withdrawn"] for u in (a, b)], [1, 1])
        listed = {o["utxo_id"]: o for o in self.listing()["outputs"]}
        self.assertEqual(set(listed), {c, made[1]})
        self.assertEqual((listed[made[1]]["value_ut"], listed[made[1]]["pending_tx"]), ("20000", None))
        second = self.submit([made[1], c])
        self.report(second["tx_id"], "commit")
        self.assertEqual(self.listing()["outputs"], [])
        self.assertEqual(self.s.conn.execute("SELECT withdrawn FROM sales_change").fetchone()[0], 1)

    def test_a_rejected_withdrawal_frees_its_money_and_drops_its_change(self):
        a = self.payment(100000)
        text, made = envelope([a])
        tx = self.s.request("POST", f"{V}/me/withdrawals", {"transaction": text, "change": {"utxo_id": made[0], "value_ut": "1"}},
                            headers=self.d["auth"])[2]["tx_id"]
        self.report(tx, "reject")
        self.assertEqual(tuple(self.row(a)), (None, None, 0))
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM sales_change").fetchone()[0], 0)
        self.submit([a])
        self.report("0" * 64, "commit", expect=404)
        other = self.s.register()
        self.report(tx, "commit", expect=404, d=other)
        status, _, resp = self.s.request("POST", f"{V}/me/withdrawals/{tx}", {"outcome": "maybe"}, headers=self.d["auth"])
        self.assertEqual(status, 422)

    def test_a_pending_withdrawal_that_was_never_reported_frees_after_the_window(self):
        a = self.payment(100000)
        self.submit([a])
        self.submit([a], expect=409)
        self.s.now += withdraw.PENDING_S + 1
        self.submit([a])

    def test_only_settled_outputs_of_this_drive(self):
        waiting = self.payment(70000, demo=False, owner_ok=None)
        counting = self.payment(500000, status="pending_check")
        kept = self.payment(80000, demo=False, owner_ok=0)
        unknown = utxo()
        good = self.payment(100000)
        for bad in (waiting, counting, kept, unknown):
            got = self.submit([good, bad], expect=409)
            self.assertEqual((got["error"]["code"], got["error"]["details"]), ("not_withdrawable", {"utxo_id": bad}))
            self.assertIsNone(self.row(good)["withdraw_tx"])                  # the refusal marked nothing
        other = self.s.register()
        self.assertEqual(self.submit([good], expect=409, d=other)["error"]["code"], "not_withdrawable")
        self.assertEqual(self.s.request("POST", f"{V}/me/withdrawals", {"transaction": envelope([good])[0]})[0], 401)

    def test_shape_and_change_are_checked(self):
        a = self.payment(100000)
        nine = [self.payment(1000) for _ in range(withdraw.MAX_INPUTS + 1)]
        self.submit(nine, expect=422)
        self.submit(nine[:withdraw.MAX_INPUTS])                               # eight inputs is a withdrawal
        self.submit([a], fee=30001, expect=422)
        self.submit([a], outputs=3, expect=422)
        for body in ({"transaction": "!!"}, {"transaction": "AAAA"}, {"transaction": envelope([a])[0], "x": 1}, {"x": 1},
                     {"transaction": envelope([a])[0], "change": {"utxo_id": utxo(), "value_ut": "1"}},
                     {"transaction": envelope([a])[0], "change": {"utxo_id": envelope([a])[1][0], "value_ut": "100000"}},
                     {"transaction": envelope([a])[0], "change": {"utxo_id": envelope([a])[1][0], "value_ut": 5}},
                     {"transaction": envelope([a])[0], "change": {"utxo_id": envelope([a])[1][0], "value_ut": "0"}}):
            status, _, resp = self.s.request("POST", f"{V}/me/withdrawals", body, headers=self.d["auth"])
            self.assertEqual((status, resp["error"]["code"]), (422, "invalid"), body)
        self.assertIsNone(self.row(a)["withdraw_tx"])
        self.submit([a, a], expect=422)                                       # the same output twice

    def test_an_output_commitment_that_isnt_32_bytes_is_refused_before_anything_is_made_from_it(self):
        """Security pass of 2026-11-09: a commitment written as a CBOR integer n made `bytes(n)` allocate n bytes
        and their hex, so one 153-byte envelope from any drive took the API past its memory limit (2^62: a 500)."""
        a = self.payment(100000)

        def with_commitment(value) -> bytes:
            env = cbor_fixture.decode(ENVELOPES["two_inputs"])
            unsigned = env[1][0][0][0]
            unsigned[3] = [unsigned[3][0], [[8, [[bytes.fromhex(a.split("_")[1]), bytes.fromhex(a.split("_")[2])]]], None, True]]
            env[1][0][0][1][:] = env[1][0][0][1][:1]
            unsigned[1][0][1][1][1][0][0][0][0] = value
            return cbor_fixture.encode(env)

        self.assertEqual(len(withdraw.parse_envelope(with_commitment(b"\x07" * 32), 30000)[1]), 2)   # the control
        for bad in (300_000_000, 2 ** 62, 32, -1, [0] * 32, b"\0" * 31, b"\0" * 33, "A" * 32, None, True):
            raw = with_commitment(bad)
            tracemalloc.start()
            try:
                with self.assertRaises(ApiError) as refused:
                    withdraw.parse_envelope(raw, 30000)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertEqual((refused.exception.status, refused.exception.code), (422, "invalid"), repr(bad)[:40])
            self.assertLess(peak, 1 << 20, repr(bad)[:40])
            status, _, resp = self.s.request("POST", f"{V}/me/withdrawals",
                                             {"transaction": base64.b64encode(raw).decode()}, headers=self.d["auth"])
            self.assertEqual((status, resp["error"]["code"]), (422, "invalid"), repr(bad)[:40])
        self.assertIsNone(self.row(a)["withdraw_tx"])
        status, _, resp = self.s.request("POST", f"{V}/me/withdrawals", {
            "transaction": envelope([a])[0], "change": {"utxo_id": envelope([a])[1][0], "value_ut": "9" * 5000}},
            headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["code"]), (422, "invalid"))

    def test_every_request_is_counted_before_its_envelope_is_read(self):
        for _ in range(withdraw.TRIES_PER_HOUR):
            status, _, resp = self.s.request("POST", f"{V}/me/withdrawals", {"transaction": "AAAA"}, headers=self.d["auth"])
            self.assertEqual(status, 422, resp)
        status, _, resp = self.s.request("POST", f"{V}/me/withdrawals", {"transaction": "AAAA"}, headers=self.d["auth"])
        self.assertEqual((status, resp["error"]["code"]), (429, "rate_limited"))

    def test_a_relay_that_fails_frees_everything(self):
        a = self.payment(100000)

        class Down:
            upstreams = [("x", "x")]

            def call(self, *args, **kwargs):
                raise IndexerError(503, "chain_unavailable")

        real = self.s.app.indexers
        self.s.app.indexers = Down()
        try:
            self.assertEqual(self.submit([a], expect=503)["error"]["code"], "chain_unavailable")
        finally:
            self.s.app.indexers = real
        self.assertEqual(tuple(self.row(a)), (None, None, 0))
        self.submit([a])

    def test_withdrawals_are_limited_per_drive(self):
        for _ in range(withdraw.SUBMITS_PER_HOUR):
            self.submit([self.payment(1000)])
        self.assertEqual(self.submit([self.payment(1000)], expect=429)["error"]["code"], "rate_limited")

    def test_deleting_the_drive_takes_its_change(self):
        a = self.payment(100000)
        text, made = envelope([a])
        tx = self.s.request("POST", f"{V}/me/withdrawals", {"transaction": text, "change": {"utxo_id": made[0], "value_ut": "5"}},
                            headers=self.d["auth"])[2]["tx_id"]
        self.report(tx, "commit")
        self.assertEqual(self.s.request("DELETE", f"{V}/me", {"auth_key": codec.b64u(self.d["auth_key"])}, headers=self.d["auth"])[0], 204)
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM sales_change").fetchone()[0], 0)

    def test_what_is_kept_names_no_destination(self):
        cols = [r[1] for r in self.s.conn.execute("PRAGMA table_info(sales_change)")]
        self.assertEqual(cols, ["utxo_id", "identity_id", "value_ut", "from_tx", "committed", "created_at", "withdraw_tx",
                                "withdraw_at", "withdrawn"])
        self.assertFalse(any("address" in c or "dest" in c for c in cols))


class NotesOfLinksThatHoldMoney(WithdrawCase):
    """Security pass of 2026-11-09: a payment is tied to its drive only through its claim, its link and the link's
    file, and their notes were purged TOMBSTONE_DAYS after the link ended. Money not yet withdrawn then left Earnings
    and the relay refused it. The notes stay while such money waits, and go once it is withdrawn."""

    def later(self, days: int) -> None:
        self.s.now += days * 86400
        self.s.run_cleanup()
        status, _, body = self.s.request("POST", f"{V}/auth/session", {"identity_id": self.d["id"],
                                                                       "auth_key": codec.b64u(self.d["auth_key"])})
        self.assertEqual(status, 201, body)                       # the session idled out meanwhile
        self.d["auth"] = {"Authorization": "Bearer " + body["token"]}

    def count(self, table: str, where: str = "1", *args) -> int:
        return self.s.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]

    def test_money_not_yet_withdrawn_outlives_its_links_note(self):
        owed = self.payment(250000, demo=False, owner_ok=1)
        self.payment(70000, demo=False, owner_ok=None)            # never checked: nobody's money by our rule
        kept_by_payer = self.payment(5000, demo=False, owner_ok=0)
        with db.tx(self.s.conn):
            self.s.conn.execute("INSERT INTO share_opens(share_id, hour, n) VALUES (?, ?, 3)",
                                (self.link["share_id"], self.s.now - self.s.now % 3600))
        other = self.sell(self.kept()["item_id"])                 # a second link whose money was all withdrawn
        spent = self.payment(100000, link=other)
        self.report(self.submit([spent])["tx_id"], "commit")
        for link in (self.link, other):
            self.assertEqual(self.s.request("DELETE", f"{V}/s/{link['share_id']}", headers=self.d["auth"])[0], 204)
        self.later(cleanup.TOMBSTONE_DAYS + 1)
        self.assertEqual(self.count("shares", "id = ?", other["share_id"]), 0)       # nothing waits on it: gone
        self.assertEqual(self.count("shares", "id = ?", self.link["share_id"]), 1)   # this one's note stays
        self.assertEqual(self.count("claims", "share_id = ?", self.link["share_id"]), 1)   # only the claim it came by
        self.assertEqual(self.count("share_opens"), 0)
        self.assertEqual([o["utxo_id"] for o in self.listing()["outputs"]], [owed])
        sales = self.s.request("GET", f"{V}/me/sales", headers=self.d["auth"])[2]
        self.assertEqual((sales["total"]["received_ut"], sales["total"]["payments"]), ("250000", 1))
        self.submit([kept_by_payer], expect=409)
        tx = self.submit([owed])["tx_id"]
        self.later(1)                                             # relayed, not yet reported: it still waits
        self.assertEqual(self.count("shares", "id = ?", self.link["share_id"]), 1)
        self.report(tx, "commit")
        self.s.run_cleanup()
        self.assertEqual(self.count("shares", "id = ?", self.link["share_id"]), 0)   # withdrawn: the note goes
        self.assertEqual(self.count("claims"), 0)
        self.assertEqual(tuple(self.s.conn.execute("SELECT claim_id, withdrawn FROM sale_payments WHERE utxo_id = ?",
                                                   (owed,)).fetchone()), (None, 1))

    def test_a_deleted_files_note_stays_too_while_its_links_money_waits(self):
        item = self.kept()
        link = self.sell(item["item_id"])
        owed = self.payment(100000, link=link)                    # test money for the whole price: vouched
        self.assertEqual(self.s.request("DELETE", f"{V}/items/{item['item_id']}", headers=self.d["auth"])[0], 204)
        self.later(cleanup.TOMBSTONE_DAYS + 1)
        self.assertEqual(self.count("items", "id = ? AND state = 'deleted'", item["item_id"]), 1)
        self.assertEqual([o["utxo_id"] for o in self.listing()["outputs"]], [owed])
        self.report(self.submit([owed])["tx_id"], "commit")
        self.s.run_cleanup()
        self.assertEqual(self.count("items", "id = ?", item["item_id"]), 0)
        self.assertEqual(self.count("shares", "id = ?", link["share_id"]), 0)

