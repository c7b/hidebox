# SPDX-License-Identifier: MIT
"""The sidecar client (spec §3.4.6): pinned-hash check, request/response matching, restart after a hang."""
import unittest

import harness  # noqa: F401  (puts server/ on sys.path)
from mutis import sidecar as sidecar_mod
from mutis.fake_chain import FAKE_WASM_SHA256, fake_keys
from mutis.fake_sidecar import argv
from mutis.sidecar import Sidecar, SidecarError


class SidecarClient(unittest.TestCase):
    def test_hello_and_commands(self):
        car = Sidecar(argv(), "http://127.0.0.1:9", FAKE_WASM_SHA256)
        try:
            keys = car.request("newKeys")
            self.assertEqual(set(keys), {"id", "ok", "owner_sk", "view_sk", "owner_pk", "view_pk", "address"})
            self.assertEqual(car.info["wasm_sha256"], FAKE_WASM_SHA256)
            self.assertEqual(car.request("scan", view_sk=fake_keys()["view_sk"], utxos=[])["found"], [])
            with self.assertRaises(SidecarError) as err:
                car.request("nope")
            self.assertEqual(err.exception.code, "failed")
            self.assertTrue(car.request("selftest")["passed"])
        finally:
            car.stop()

    def test_refuses_a_different_wasm(self):
        car = Sidecar(argv(), "http://127.0.0.1:9", "00" * 32)
        with self.assertRaises(SidecarError) as err:
            car.request("newKeys")
        self.assertEqual(err.exception.code, "wasm_hash_mismatch")
        self.assertIsNone(car._proc)

    def test_restart_after_timeout(self):
        saved = sidecar_mod.TIMEOUT_S
        sidecar_mod.TIMEOUT_S = 1
        car = Sidecar(argv(), "http://127.0.0.1:9", FAKE_WASM_SHA256)
        try:
            car.request("newKeys")
            first = car._proc.pid
            with self.assertRaises(SidecarError) as err:
                car.request("sleep", seconds=3)
            self.assertEqual(err.exception.code, "timeout")
            self.assertIsNone(car._proc)
            car.request("newKeys")
            self.assertNotEqual(car._proc.pid, first)
        finally:
            sidecar_mod.TIMEOUT_S = saved
            car.stop()

    def test_missing_binary(self):
        car = Sidecar(["/nonexistent/node"], "http://127.0.0.1:9", FAKE_WASM_SHA256)
        with self.assertRaises(SidecarError) as err:
            car.request("hello")
        self.assertEqual(err.exception.code, "protocol")


if __name__ == "__main__":
    unittest.main()
