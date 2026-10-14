# SPDX-License-Identifier: MIT
"""Helpers for the pay-to-open tests (test_paid_shares, test_sales_worker, test_release_gate): a drive with
a registered sales address, a kept file or folder, a paid link and a buyer's claim, all on the fake chain."""
import hashlib
import os
import secrets
import struct
import unittest

from harness import Stack
from mutis import codec, db, sales
from mutis.fake_chain import fake_keys

V = "/api/v1"


def b64(n: int) -> str:
    return codec.b64u(os.urandom(n))


def watch_blob(address: str, view_sk: bytes, flags: int = sales.WATCH_FLAG, ref_address: str | None = None) -> bytes:
    """The fake chain's kind-3 seal of a sales view key: the inner payload in clear, padded to 125 B."""
    return bytes(16) + view_sk + bytes([flags]) + sales.watch_ref(ref_address or address) + bytes(60)


class PaidCase(unittest.TestCase):
    chain = True

    def setUp(self):
        self.s = Stack(chain=self.chain)
        self.s.quiet_chain()
        if self.chain:
            self.s.worker.setup()
        self.d = self.s.register()
        self.s.graduate(self.d)
        self.sales_keys = fake_keys()

    def tearDown(self):
        self.s.close()

    # --- the seller ---------------------------------------------------------------------------------------

    def register_seller(self, d: dict | None = None, keys: dict | None = None, **blob) -> tuple[int, dict]:
        keys = keys or self.sales_keys
        sealed = watch_blob(keys["address"], bytes.fromhex(keys["view_sk"]), **blob)
        status, _, body = self.s.request("PUT", f"{V}/me/sales", {"address": keys["address"],
                                                                  "view_sealed": codec.b64u(sealed)},
                                         headers=(d or self.d)["auth"])
        return status, body

    def ready_seller(self) -> None:
        self.assertEqual(self.register_seller()[0], 204)
        if self.chain:
            self.ticks(1)
        else:
            with db.tx(self.s.conn):
                self.s.conn.execute("UPDATE sellers SET state = 'ok'")

    def kept(self, plaintext: int = 1000, d: dict | None = None) -> dict:
        return self.s.upload(plaintext, headers=(d or self.d)["auth"], retention="kept", owner_wrap=b64(60))

    def folder(self) -> str:
        header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 1, 0, 0) + os.urandom(16)
        status, _, resp = self.s.request("POST", f"{V}/folders", {
            "parent_id": None, "header": codec.b64u(header), "meta_ct": b64(284), "owner_wrap": b64(60)},
            headers=self.d["auth"])
        self.assertEqual(status, 201, resp)
        return resp["item_id"]

    def sell(self, item_id: str, price="100000", expect: int = 201, d: dict | None = None, **extra) -> dict:
        s = secrets.token_bytes(32)                     # in the app: HKDF(sA ‖ sB); the server never sees it
        access = codec.hkdf(s, b"mutis/v1", b"share-access", 32)
        half = secrets.token_bytes(32)
        body = {"mode": "pay", "wrapped_key": b64(60), "access_verifier": codec.b64u(hashlib.sha256(access).digest()),
                "server_half": codec.b64u(half), "price_ut": price, "teaser_ct": b64(512), **extra}
        status, _, resp = self.s.request("POST", f"{V}/items/{item_id}/shares", body, headers=(d or self.d)["auth"])
        self.assertEqual(status, expect, resp)
        return {**resp, "access": {"X-Mutis-Access": codec.b64u(access)}, "half": half}

    # --- the buyer ----------------------------------------------------------------------------------------

    def claim(self, link: dict, expect: int = 201, ip: str | None = None) -> dict:
        t = secrets.token_bytes(32)
        status, _, resp = self.s.request("POST", f"{V}/p/{link['share_id']}/claims", {
            "claim_verifier": codec.b64u(hashlib.sha256(t).digest()), "pow": self.s.solve("claim", ip)}, ip=ip)
        self.assertEqual(status, expect, resp)
        return {**resp, "t": t, "hdr": {"X-Mutis-Claim": codec.b64u(t)}, "share_id": link["share_id"]}

    def poll(self, claim: dict, expect: int = 200) -> dict:
        status, _, resp = self.s.request("GET", f"{V}/p/{claim['share_id']}/claims/{claim['claim_id']}",
                                         headers=claim["hdr"])
        self.assertEqual(status, expect, resp)
        return resp

    def open(self, link: dict, claim: dict | None, expect: int = 200) -> dict:
        headers = {**link["access"], **(claim["hdr"] if claim else {})}
        status, _, resp = self.s.request("POST", f"{V}/s/{link['share_id']}/open", headers=headers)
        self.assertEqual(status, expect, resp)
        return resp

    def pay(self, claim: dict, value: int | None = None, spender: str | None = None, memo=None) -> str:
        """An output to the claim's address (its reference in the memo), as any Ootle wallet would send."""
        return self.s.chain.add_output(claim["address"], int(claim["amount_ut"]) if value is None else value, memo,
                                       spender=spender)

    def ticks(self, n: int = 3) -> None:
        for _ in range(n):
            self.s.now += 10
            self.s.heartbeat()
            self.s.worker.tick()

    def row(self, claim: dict):
        return self.s.conn.execute("SELECT * FROM claims WHERE id = ?", (claim["claim_id"],)).fetchone()
