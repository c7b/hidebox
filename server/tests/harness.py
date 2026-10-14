# SPDX-License-Identifier: MIT
"""Test harness: a real mutis-api on 127.0.0.1 with a temporary data dir, a settable clock and disk,
the fake chain/indexer/walletd, and helpers that build valid uploads (random bytes as ciphertext)."""
import hashlib
import http.client
import json
import os
import secrets
import shutil
import struct
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutis import api, cleanup, codec, config, db, pow as pow_mod, quota  # noqa: E402
from mutis.chain_worker import Worker  # noqa: E402
from mutis.fake_chain import FAKE_WASM_SHA256, FakeChain, FakeIndexer, fake_keys  # noqa: E402
from mutis.fake_sidecar import argv as fake_sidecar_argv  # noqa: E402
from mutis.fake_walletd import FakeWalletd  # noqa: E402
from mutis.indexer import Indexers  # noqa: E402
from mutis.sidecar import Sidecar  # noqa: E402
from mutis.walletd import Walletd  # noqa: E402

ORIGIN = "https://test.mutis.invalid"
GiB = 1 << 30
START = 1_791_720_000           # 2026-10-11 14:40 UTC


class Disk:
    """A settable os.statvfs stand-in (bytes, with a 1-byte fragment size)."""

    def __init__(self, total: int = 100 * GiB, avail: int = 80 * GiB):
        self.total, self.avail = total, avail

    def __call__(self, path):
        return SimpleNamespace(f_blocks=self.total, f_frsize=1, f_bavail=self.avail)


class Client:
    """HTTP helpers that build valid requests (random bytes stand in for ciphertext)."""

    def __init__(self, port: int):
        self.port = port

    # --- HTTP ----------------------------------------------------------------------------------------

    def request(self, method: str, path: str, body=None, headers: dict | None = None, raw: bytes | None = None,
                ip: str | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = dict(headers or {})
        if ip:
            hdrs["X-Real-IP"] = ip
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        ctype = resp.getheader("Content-Type") or ""
        parsed = json.loads(payload) if payload and ctype.startswith("application/json") else payload
        return resp.status, dict(resp.getheaders()), parsed

    def solve(self, purpose: str, ip: str | None = None) -> dict:
        _, _, ch = self.request("POST", "/api/v1/pow", {"purpose": purpose}, ip=ip)
        challenge = codec.unb64u(ch["challenge"])
        n = 0
        while not pow_mod.solved(challenge, struct.pack(">Q", n), ch["difficulty"]):
            n += 1
        return {"challenge": ch["challenge"], "nonce": codec.b64u(struct.pack(">Q", n))}

    # --- lockers ---------------------------------------------------------------------------------------

    def register(self, ip: str | None = None) -> dict:
        auth_key = secrets.token_bytes(32)
        identity_id = codec.b64u(secrets.token_bytes(16))
        status, _, body = self.request("POST", "/api/v1/auth/register", {
            "identity_id": identity_id, "auth_verifier": codec.b64u(hashlib.sha256(auth_key).digest()),
            "pow": self.solve("register", ip)}, ip=ip)
        assert status == 201, body
        return {"id": identity_id, "auth_key": auth_key, "token": body["token"],
                "auth": {"Authorization": "Bearer " + body["token"]}}

    # --- uploads ---------------------------------------------------------------------------------------

    @staticmethod
    def layout(plaintext: int) -> tuple[int, int]:
        padded = quota.padme(plaintext)
        n = max(1, -(-padded // quota.CHUNK))
        return n, padded + 16 * n

    def start_upload(self, plaintext: int = 1000, headers: dict | None = None, ip: str | None = None,
                     **fields) -> tuple[int, dict]:
        n, size = self.layout(plaintext)
        header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 0, n, 0) + secrets.token_bytes(16)
        body = {"retention": "ephemeral", "header": codec.b64u(header), "meta_ct": codec.b64u(os.urandom(284)),
                "chunk_count": n, "size_stored": size, "owner_wrap": None, "drop_id": None}
        body.update(fields)
        if "Authorization" not in (headers or {}) and "X-Mutis-Canary" not in (headers or {}) and "pow" not in body:
            body["pow"] = self.solve("upload", ip)
        status, _, resp = self.request("POST", "/api/v1/uploads", body, headers=headers, ip=ip)
        return status, resp

    def put_chunks(self, upload_id: str, size: int, n: int, ip: str | None = None) -> bytes:
        blob = b""
        for i in range(n):
            length = quota.chunk_length(size, n, i)
            chunk = os.urandom(length)
            status, _, body = self.request("PUT", f"/api/v1/uploads/{upload_id}/chunks/{i}", raw=chunk, ip=ip,
                                           headers={"Content-Type": "application/octet-stream",
                                                    "X-Mutis-Chunk-SHA256": codec.b64u(hashlib.sha256(chunk).digest())})
            assert status == 204, body
            blob += chunk
        return blob

    def upload(self, plaintext: int = 1000, headers: dict | None = None, ip: str | None = None, **fields) -> dict:
        n, size = self.layout(plaintext)
        status, up = self.start_upload(plaintext, headers=headers, ip=ip, **fields)
        assert status == 201, up
        blob = self.put_chunks(up["upload_id"], size, n, ip=ip)
        status, _, done = self.request("POST", f"/api/v1/uploads/{up['upload_id']}/complete", {}, ip=ip)
        assert status == 200, done
        return {**up, "blob": blob, "size": size, "n": n, "manage": {"X-Mutis-Manage": up["manage_token"]}}

    def share(self, item: dict, mode: str = "link", max_views=1, expires_at=None, headers=None) -> dict:
        s = secrets.token_bytes(32)
        access = codec.hkdf(s, b"mutis/v1", b"share-access", 32)
        body = {"mode": mode, "wrapped_key": codec.b64u(os.urandom(60)),
                "access_verifier": codec.b64u(hashlib.sha256(access).digest()), "link_verifier": None, "kdf": None,
                "max_views": max_views, "expires_at": expires_at}
        proof = None
        if mode != "link":
            body["kdf"] = {"alg": "PBKDF2-SHA256", "iter": 600000, "salt": codec.b64u(os.urandom(16))}
        if mode == "link_password":
            proof = secrets.token_bytes(32)
            body["link_verifier"] = codec.b64u(hashlib.sha256(proof).digest())
        status, _, resp = self.request("POST", f"/api/v1/items/{item['item_id']}/shares", body,
                                       headers=headers or item["manage"])
        assert status == 201, resp
        hdrs = {"X-Mutis-Access": codec.b64u(access)}
        if proof:
            hdrs["X-Mutis-Link"] = codec.b64u(proof)
        return {**resp, "access": hdrs, "s": s}

    def drop(self, label: str = "tips") -> dict:
        keys = fake_keys()
        manage = secrets.token_bytes(32)
        status, _, resp = self.request("POST", "/api/v1/drops", {
            "address": keys["address"], "tag": codec.b64u(os.urandom(16)), "label": label,
            "manage_verifier": codec.b64u(hashlib.sha256(manage).digest()), "pow": self.solve("drop_create")})
        assert status == 201, resp
        return {**resp, "keys": keys, "manage": {"X-Mutis-Manage": codec.b64u(manage)}}


class Stack(Client):
    """A real mutis-api on 127.0.0.1:0 over a temporary data dir, with a settable clock and disk and the fake
    chain, indexer and walletd; `chain=True` also builds a chain worker driven by the same clock."""

    def __init__(self, overrides: dict | None = None, pow_bits: int = 1, chain: bool = False):
        self.tmp = Path(tempfile.mkdtemp(prefix="mutis-test-"))
        self.now = START
        self.secret = secrets.token_bytes(32)
        (self.tmp / "secret.key").write_bytes(self.secret)
        self.chain = FakeChain()
        self.indexer = FakeIndexer(self.chain)
        self.walletd_fake = FakeWalletd(self.chain)
        self.receiver, self.robot = fake_keys(), fake_keys()
        for name, keys in (("receiver.json", self.receiver), ("robot.json", self.robot)):
            (self.tmp / name).write_text(json.dumps(keys))
        raw = {
            "public_origin": ORIGIN, "memo_origins": [ORIGIN, "https://mutis.sh"], "listen": "127.0.0.1:0",
            "data_dir": str(self.tmp / "data"), "secret_key": str(self.tmp / "secret.key"),
            "gates": {"send_mode": "relay", "amount_proof": "sidecar", "key_bundle": True},
            "ootle": {"walletd_url": self.walletd_fake.url, "indexers": [self.indexer.url],
                      "receiver_keys": str(self.tmp / "receiver.json"), "robot_keys": str(self.tmp / "robot.json"),
                      "jitter_s": [5, 45]},
            "sidecar": {"command": fake_sidecar_argv(), "expected_wasm_sha256": FAKE_WASM_SHA256},
            # The drive's features are off in config.py until the routes switch over; tests run with them on.
            "features": {"folders": True, "pay_to_open": True},
        }
        for key, value in (overrides or {}).items():
            if isinstance(value, dict):
                raw.setdefault(key, {}).update(value)
            else:
                raw[key] = value
        self.cfg = config.from_dict(raw)
        db.migrate(self.cfg.db_path)
        self.disk = Disk()
        self.app = api.App(self.cfg, self.secret, pow_bits=pow_bits)
        self.app.statvfs = self.disk
        self.app.clock = lambda: self.now
        self.server = api.make_server(self.app, "127.0.0.1", 0)
        super().__init__(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.conn = db.connect(self.cfg.db_path)
        self.heartbeat()
        self.worker = None
        if chain:
            self.start_worker()

    # --- lifecycle ------------------------------------------------------------------------------------

    def start_worker(self) -> Worker:
        cfg = config.from_dict({**self.cfg.raw, "listen": f"127.0.0.1:{self.port}"})
        self.worker = Worker(cfg, self.secret, Walletd(self.walletd_fake.url),
                             Indexers([self.indexer.url], rate=1000),
                             Sidecar(fake_sidecar_argv(), f"http://127.0.0.1:{self.port}", FAKE_WASM_SHA256),
                             clock=lambda: self.now)
        return self.worker

    def close(self) -> None:
        if self.worker:
            self.worker.sidecar.stop()
            self.worker.conn.close()
        self.server.shutdown()
        self.server.server_close()
        for fake in (self.indexer, self.walletd_fake):
            fake.shutdown()
            fake.server_close()
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def heartbeat(self) -> None:
        with db.tx(self.conn):
            db.set_meta(self.conn, "chain_heartbeat", str(self.now))

    # --- database helpers ------------------------------------------------------------------------------

    def quiet_chain(self) -> None:
        """No canary and no evidence payment for now, so a test's worker sees only the test's own jobs."""
        with db.tx(self.conn):
            db.set_meta(self.conn, "evidence_pay_day", codec.day(self.now))
            db.set_meta(self.conn, "canary_log", [{"n": 1, "item_id": "", "share_id": "", "job_id": "",
                                                   "sealed_at": self.now + 10 ** 6, "delivery_tx": "", "utxo_ids": [],
                                                   "verified": True, "fk": "-"}])

    def graduate(self, locker: dict) -> None:
        """End a locker's probation (a second active day)."""
        with db.tx(self.conn):
            self.conn.execute("UPDATE identities SET distinct_days = 2, created_day = '2026-10-01' WHERE id = ?",
                              (locker["id"],))

    def meta(self, key: str):
        return db.get_meta(self.conn, key)

    def run_cleanup(self) -> dict:
        return cleanup.run(self.conn, self.cfg, self.app.blobs, self.disk, self.now)
