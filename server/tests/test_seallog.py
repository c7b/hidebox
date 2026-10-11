# SPDX-License-Identifier: MIT
"""SealLog storage and exit receipts (spec §11, brand patch P-8): RFC 9162 trees, padding, hidden leaf
order, proofs end to end, and the worker's own checkpoint schedule."""
import hashlib
import random
import unittest

from harness import Stack
from mutis import chain_worker, codec, db, seallog

COMPONENT = "component_" + "ab" * 32


def reference_mth(leaves: list[bytes]) -> bytes:
    """RFC 9162 §2.1.1 written recursively, as the RFC states it."""
    if not leaves:
        return hashlib.sha256(b"").digest()
    if len(leaves) == 1:
        return leaves[0]
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    return hashlib.sha256(b"\x01" + reference_mth(leaves[:k]) + reference_mth(leaves[k:])).digest()


def reference_path(index: int, leaves: list[bytes]) -> list[bytes]:
    """RFC 9162 §2.1.3.1 PATH(m, D[n]), recursively."""
    if len(leaves) <= 1:
        return []
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    if index < k:
        return reference_path(index, leaves[:k]) + [reference_mth(leaves[k:])]
    return reference_path(index - k, leaves[k:]) + [reference_mth(leaves[:k])]


class Tree(unittest.TestCase):
    def test_root_and_proofs_match_rfc_9162(self):
        leaves = [hashlib.sha256(b"\x00" + bytes([i])).digest() for i in range(70)]
        for n in list(range(0, 71)) + [192]:
            part = (leaves * 3)[:n]
            root = seallog.root(part)
            self.assertEqual(root, reference_mth(part), n)
            tree = seallog.levels(part) if part else None
            for i in range(n):
                path = seallog.inclusion_proof(tree, i)
                self.assertEqual(path, reference_path(i, part), (n, i))
                self.assertTrue(seallog.verify_inclusion(part[i], i, n, path, root), (n, i))
                if path:
                    bad = [path[0][:-1] + bytes([path[0][-1] ^ 1])] + path[1:]
                    self.assertFalse(seallog.verify_inclusion(part[i], i, n, bad, root))

    def test_leaf_encodings(self):
        item_id = codec.b64u(bytes(range(16)))
        ct = bytes(32)
        self.assertEqual(seallog.stored_leaf(item_id, ct),
                         hashlib.sha256(b"\x00mutis-leaf-v1" + bytes(range(16)) + ct).digest())
        self.assertEqual(seallog.exit_leaf(item_id, 3600 * 497_700),
                         hashlib.sha256(b"\x00mutis-exit-v1" + bytes(range(16)) + (497_700).to_bytes(4, "big")).digest())


class LeafOrder(unittest.TestCase):
    """Review M1: a leaf index must not count uploads (spec §11.3: volume only in steps of 64)."""

    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def add(self, n: int) -> list[bytes]:
        hashes = [hashlib.sha256(codec.new_id().encode()).digest() for _ in range(n)]
        with db.tx(self.s.conn):
            for h in hashes:
                seallog.append(self.s.conn, "stored", h)
        return hashes

    def test_new_leaves_have_no_index_until_a_checkpoint_shuffles_them(self):
        conn = self.s.conn
        first = self.add(10)
        self.assertEqual({seallog.leaf_index(conn, h) for h in first}, {None})
        with db.tx(conn):
            cp = seallog.make_checkpoint(conn, self.s.now, random.Random(7))
        self.assertEqual(cp["tree_size"], 64)
        placed = [seallog.leaf_index(conn, h) for h in first]
        self.assertEqual(len(set(placed)), 10)
        self.assertTrue(all(0 <= i < 64 for i in placed))
        self.assertNotEqual(placed, list(range(10)))                  # not in arrival order
        second = self.add(3)
        with db.tx(conn):
            cp = seallog.make_checkpoint(conn, self.s.now, random.Random(8))
        self.assertEqual(cp["tree_size"], 128)
        self.assertTrue(all(64 <= seallog.leaf_index(conn, h) < 128 for h in second))
        self.assertEqual(cp["root"], reference_mth(seallog.leaf_hashes(conn, 128)))

    def test_an_empty_interval_repeats_the_same_size(self):
        with db.tx(self.s.conn):
            self.assertEqual(seallog.make_checkpoint(self.s.conn, self.s.now)["tree_size"], 0)
        self.add(64)
        with db.tx(self.s.conn):
            self.assertEqual(seallog.make_checkpoint(self.s.conn, self.s.now)["tree_size"], 64)
            self.assertEqual(seallog.make_checkpoint(self.s.conn, self.s.now)["tree_size"], 64)


class Receipts(unittest.TestCase):
    def stack(self, on: bool = True) -> Stack:
        overrides = {"features": {"seallog": True}, "ootle": {"seallog_component": COMPONENT}} if on else {}
        s = Stack(overrides, chain=True)
        s.worker.setup()
        s.quiet_chain()
        return s

    def test_stored_and_exit_receipts_end_to_end(self):
        s = self.stack()
        try:
            item = s.upload(1000)
            link = s.share(item)
            s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])
            rows = s.conn.execute("SELECT kind, idx FROM seal_leaves").fetchall()
            self.assertEqual(sorted((r["kind"], r["idx"]) for r in rows), [("exit", None), ("stored", None)])
            status, _, early = s.request("GET", f"/api/v1/seallog/proof/{item['item_id']}")
            self.assertEqual((status, early["leaf_index"], early["proof"]["pending"]), (200, None, True))
            s.worker.tick()              # pads, roots, submits and (the fake commits at once) settles
            checkpoint = s.conn.execute("SELECT * FROM seal_checkpoints").fetchone()
            self.assertEqual((checkpoint["tree_size"], checkpoint["state"]), (64, "committed"))
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM seal_leaves WHERE kind = 'pad'").fetchone()[0], 62)
            self.assertIn("transactions.submit_manifest", s.walletd_fake.calls)
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)   # never a queued job
            status, _, proof = s.request("GET", f"/api/v1/seallog/proof/{item['item_id']}")
            self.assertEqual(status, 200)
            root = bytes.fromhex(proof["checkpoint"]["root"])
            path = [bytes.fromhex(h) for h in proof["proof"]]
            self.assertTrue(seallog.verify_inclusion(bytes.fromhex(proof["leaf_hash"]), proof["leaf_index"], 64,
                                                     path, root))
            status, _, receipt = s.request("GET", f"/api/v1/s/{link['share_id']}/exit")
            self.assertEqual((status, receipt["reason"], receipt["item_id"]), (200, "burned", item["item_id"]))
            leaf = seallog.exit_leaf(receipt["item_id"], receipt["exit_hour"])      # what /verify recomputes
            self.assertEqual(leaf.hex(), receipt["leaf_hash"])
            self.assertTrue(seallog.verify_inclusion(leaf, receipt["leaf_index"], 64,
                                                     [bytes.fromhex(h) for h in receipt["proof"]], root))
            status, _, page = s.request("GET", "/api/v1/seallog/checkpoints")
            self.assertEqual(page["checkpoints"][0]["tree_size"], 64)
            self.assertEqual(s.request("GET", "/api/v1/stats")[2]["seal_log"]["tree_size"], 64)
            s.now += 3600
            s.worker.tick()
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM seal_checkpoints").fetchone()[0], 1)  # 6 h cadence
        finally:
            s.close()

    def test_off_means_no_receipts_at_all(self):
        """Review M2: while SealLog is off, nothing may promise a checkpoint that will never come."""
        s = self.stack(on=False)
        try:
            item = s.upload(1000)
            link = s.share(item)
            s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])
            for path in (f"/api/v1/seallog/proof/{item['item_id']}", f"/api/v1/s/{link['share_id']}/exit",
                         "/api/v1/seallog/checkpoints"):
                status, _, body = s.request("GET", path)
                self.assertEqual((status, body["error"]["code"], body["error"]["details"]), (503, "feature_disabled",
                                                                                            {"feature": "seallog"}))
            s.worker.tick()
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM seal_checkpoints").fetchone()[0], 0)
        finally:
            s.close()

    def test_failed_submission_retries_in_ten_minutes_and_force_is_rate_limited(self):
        """Review M8: the worker alone decides when a root is published, and it can't be hurried."""
        s = self.stack()
        try:
            s.walletd_fake.fail_next = 2          # accounts.get and submit_manifest
            s.worker.tick()
            self.assertEqual([r[0] for r in s.conn.execute("SELECT state FROM seal_checkpoints")], ["failed"])
            s.now += chain_worker.SEAL_RETRY_S - 1
            s.worker.tick()
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM seal_checkpoints").fetchone()[0], 1)
            s.now += 1
            s.worker.tick()
            states = [r[0] for r in s.conn.execute("SELECT state FROM seal_checkpoints ORDER BY idx")]
            self.assertEqual(states, ["failed", "committed"])
            with db.tx(s.conn):
                db.set_meta(s.conn, "force", {"seal": True})
            for _ in range(5):                    # a flag set every tick still waits out the gap
                s.now += 60
                s.worker.tick()
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM seal_checkpoints").fetchone()[0], 2)
            s.now += chain_worker.SEAL_FORCE_GAP_S
            s.worker.tick()
            self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM seal_checkpoints").fetchone()[0], 3)
        finally:
            s.close()

    def test_restart_settles_a_half_made_checkpoint(self):
        s = self.stack()
        try:
            s.walletd_fake.wait_outcome = "timeout"
            s.worker.tick()
            row = s.conn.execute("SELECT state, tx_id FROM seal_checkpoints").fetchone()
            self.assertEqual(row["state"], "pending")
            self.assertIsNotNone(row["tx_id"])
            with db.tx(s.conn):                   # a checkpoint the previous run made but never submitted
                s.conn.execute("INSERT INTO seal_checkpoints(tree_size, root, created_at, state) "
                               "VALUES (64, x'00', ?, 'pending')", (s.now,))
            s.worker.recover(s.now)
            states = [r[0] for r in s.conn.execute("SELECT state FROM seal_checkpoints ORDER BY idx")]
            self.assertEqual(states, ["pending", "failed"])
            s.walletd_fake.wait_outcome = "commit"
            s.now += 1
            s.worker.tick()
            states = [r[0] for r in s.conn.execute("SELECT state FROM seal_checkpoints ORDER BY idx")]
            self.assertEqual(states, ["committed", "failed"])
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
