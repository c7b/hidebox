# SPDX-License-Identifier: MIT
"""S-07 (real half) and the sidecar contract: the server's client against the app builder's real Node
sidecar (official ootle-wasm 0.45.0 under Node's permission model), and the canary sealed with the real
lib/format.js through this server's API. Opt-in, on the server as `build`:

    MUTIS_SIDECAR_DIR=/path/to/web/app python3 -I -m unittest discover -s server/tests -p test_real_sidecar.py
"""
import json
import os
import re
import time
import unittest
from pathlib import Path

from harness import Stack
from mutis import codec, db, jobs, ootle_addr
from mutis.config import PINNED_WASM_SHA256
from mutis.sidecar import Sidecar, SidecarError

SIDECAR_DIR = os.environ.get("MUTIS_SIDECAR_DIR", "")
NODE = "/usr/bin/node"


def argv() -> list[str]:
    root = Path(SIDECAR_DIR)
    script = root / "sidecar" / "sidecar.mjs" if (root / "sidecar").is_dir() else root / "sidecar.mjs"
    return [NODE, "--experimental-permission", f"--allow-fs-read={root}", "--disallow-code-generation-from-strings",
            str(script)]


@unittest.skipUnless(SIDECAR_DIR and os.path.exists(NODE), "set MUTIS_SIDECAR_DIR (needs Debian nodejs)")
class RealSidecar(unittest.TestCase):
    def test_pinned_wasm_selftest_and_scan(self):
        car = Sidecar(argv(), "http://127.0.0.1:9", PINNED_WASM_SHA256)
        try:
            result = car.request("selftest")
            self.assertTrue(result["passed"])
            self.assertTrue(any(c["name"].startswith("rejected") for c in result["cases"]))
            self.assertTrue(all(c["passed"] for c in result["cases"]))
            self.assertEqual(car.info["wasm_sha256"], PINNED_WASM_SHA256)
            keys = car.request("newKeys")
            self.assertEqual(ootle_addr.classify(keys["address"]), "ootle_testnet")
            self.assertEqual(ootle_addr.classify(car.request("decoyAddress")["address"]), "ootle_testnet")
            foreign = [{"id": f"utxo_{'01' * 32}_{os.urandom(32).hex()}", "nonce": os.urandom(32).hex(),
                        "enc": os.urandom(80).hex()} for _ in range(50)]
            self.assertEqual(car.request("scan", view_sk=keys["view_sk"], utxos=foreign)["found"], [])
            with self.assertRaises(SidecarError) as err:
                car.request("reveal", n=999)
            self.assertEqual(err.exception.code, "not_found")
            print(json.dumps({"sidecar": car.info, "selftest_cases": len(result["cases"])}))
        finally:
            car.stop()

    def test_wrong_pin_refused(self):
        with self.assertRaises(SidecarError) as err:
            Sidecar(argv(), "http://127.0.0.1:9", "00" * 32).request("hello")
        self.assertEqual(err.exception.code, "wasm_hash_mismatch")

    def test_canary_sealed_through_this_api_and_opened_with_robot_keys(self):
        s = Stack(chain=True)
        s.now = int(time.time())           # the real sidecar stamps the canary with its own clock, so the API
        s.app.clock = codec.now            # must read the real one too: a frozen one may lag a second behind
        s.heartbeat()
        car = Sidecar(argv(), f"http://127.0.0.1:{s.port}", PINNED_WASM_SHA256)
        try:
            for name in ("receiver.json", "robot.json"):
                (s.tmp / name).write_text(json.dumps(car.request("newKeys")))
            robot = json.loads((s.tmp / "robot.json").read_text())
            w = s.worker
            w.sidecar = car
            w.setup()
            w.seal_canary(s.now, [])
            entry = db.get_meta_json(s.conn, "canary_log")[0]
            item = s.conn.execute("SELECT * FROM items WHERE id = ?", (entry["item_id"],)).fetchone()
            self.assertEqual((item["state"], item["canary"], item["lane"], item["chunk_count"]), ("ready", 1, "small", 1))
            self.assertEqual(item["header"][:4], b"MTS1")
            share = s.conn.execute("SELECT * FROM shares WHERE id = ?", (entry["share_id"],)).fetchone()
            self.assertEqual((share["mode"], share["max_views"]), ("link", 3))
            job = s.conn.execute("SELECT * FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
            payload = json.loads(job["payload"])
            self.assertEqual((job["evidence"], payload["address"]), (1, ootle_addr.base_address(robot["address"])))
            self.assertTrue(jobs.memo_regex(list(s.cfg["memo_origins"])).match(payload["memo"]))
            opened = car.request("openDelivery", memo={"Message": payload["memo"]}, owner_sk=robot["owner_sk"],
                                 view_sk=robot["view_sk"], origins=list(s.cfg["memo_origins"]))
            self.assertEqual(opened["share_id"], entry["share_id"])
            self.assertTrue(w._open_link(opened["share_id"], opened["access_token"]))
            stranger = car.request("newKeys")
            with self.assertRaises(SidecarError) as err:
                car.request("openDelivery", memo={"Message": payload["memo"]}, owner_sk=stranger["owner_sk"],
                            view_sk=stranger["view_sk"], origins=list(s.cfg["memo_origins"]))
            self.assertEqual(err.exception.code, "cannot_open")
            with self.assertRaises(SidecarError):           # the view key alone can't open a kind-3 delivery
                car.request("openDelivery", memo={"Message": payload["memo"]}, owner_sk=stranger["owner_sk"],
                            view_sk=robot["view_sk"], origins=list(s.cfg["memo_origins"]))
            fk = car.request("reveal", n=entry["n"])["fk"]
            self.assertEqual(len(codec.unb64u(fk)), 32)
            self.assertRegex(payload["memo"], re.escape(s.cfg.origin) + r"/t#3[A-Za-z0-9_-]{167}$")
        finally:
            car.stop()
            s.close()


if __name__ == "__main__":
    unittest.main()
