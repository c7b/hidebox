# SPDX-License-Identifier: MIT
"""A browserless client of the mutis API (spec §6), for the log test (D-02), the griefer (E-23) and
API-level steps in the scenarios. Python stdlib only.

It speaks the real protocol with synthetic content: headers with the v1 layout, random bytes for
ciphertext, real proofs of work. It never needs a file key, so nothing it uploads can be opened as a
file; that is all these tests need. Addresses come from the server's own bech32m codec.
"""
import base64
import hashlib
import json
import os
import secrets
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from mutis import ootle_addr  # noqa: E402

CHUNK, TAG = 4 << 20, 16           # plaintext bytes per chunk, and the AES-GCM tag each chunk adds
META_LEN = 12 + 256 + 16          # the shortest meta_ct length the server accepts


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def random_address() -> str:
    """A well-formed Esmeralda address with random keys (accepted by the API, unspendable)."""
    return ootle_addr.encode(ootle_addr.TESTNET_HRP, secrets.token_bytes(64))


def leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte:
            return bits + 8 - byte.bit_length()
        bits += 8
    return bits


class ApiError(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(f"{status} {body.get('error', {}).get('code')}")
        self.status, self.body = status, body
        self.code = body.get("error", {}).get("code")


class Client:
    """One visitor. `base` is the public origin, or http://127.0.0.1:8787 with `real_ip` (griefer)."""

    def __init__(self, base: str, real_ip: str | None = None, origin: str | None = None, judge: str | None = None):
        self.base, self.real_ip, self.judge = base.rstrip("/"), real_ip, judge
        self.origin = origin or self.base
        self.token: str | None = None
        self.last_pow_bits = 0

    def call(self, method: str, path: str, body=None, headers: dict | None = None, raw: bytes | None = None):
        h = {"User-Agent": "mutis-e2e", "Origin": self.origin}
        if self.real_ip:
            h["X-Real-IP"] = self.real_ip
        if self.judge:
            h["X-Mutis-Judge"] = self.judge
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        data = raw
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif raw is not None:
            h["Content-Type"] = "application/octet-stream"
        h.update(headers or {})
        req = urllib.request.Request(self.base + "/api/v1" + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = res.read()
                return res.status, (json.loads(payload) if payload[:1] == b"{" else payload)
        except urllib.error.HTTPError as e:
            payload = e.read()
            raise ApiError(e.code, json.loads(payload) if payload[:1] == b"{" else {}) from None

    def pow(self, purpose: str, max_bits: int = 22) -> dict:
        _, ch = self.call("POST", "/pow", {"purpose": purpose})
        challenge, bits = unb64u(ch["challenge"]), ch["difficulty"]
        self.last_pow_bits = bits
        if bits > max_bits:
            raise ApiError(428, {"error": {"code": "pow_too_hard", "details": {"difficulty": bits}}})
        n = 0
        while leading_zero_bits(hashlib.sha256(challenge + struct.pack(">Q", n)).digest()) < bits:
            n += 1
        return {"challenge": ch["challenge"], "nonce": b64u(struct.pack(">Q", n))}

    # --- uploads and links ------------------------------------------------------------------------

    def create_upload(self, plain_bytes: int = 1000, drop_id: str | None = None, expires_in: int = 3600) -> dict:
        """POST /uploads; the answer plus `chunks`, each chunk's exact stored length (4 MiB + tag each,
        the last one shorter), as the browser would lay a file out."""
        plain = max(1024, plain_bytes)
        count = -(-plain // CHUNK)
        chunks = [CHUNK + TAG] * (count - 1) + [plain - (count - 1) * CHUNK + TAG]
        header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 0, count, 0) + secrets.token_bytes(16)
        body = {"retention": "ephemeral", "header": b64u(header), "meta_ct": b64u(os.urandom(META_LEN)),
                "chunk_count": count, "size_stored": sum(chunks), "owner_wrap": None, "drop_id": drop_id,
                "expires_at": int(time.time()) + (604800 if drop_id else expires_in)}
        if not self.token:
            body["pow"] = self.pow("upload")
        _, up = self.call("POST", "/uploads", body)
        return up | {"item_expires_at": body["expires_at"], "size_stored": body["size_stored"], "chunks": chunks}

    def upload(self, plain_bytes: int = 1000, drop_id: str | None = None, expires_in: int = 3600) -> dict:
        up = self.create_upload(plain_bytes, drop_id, expires_in)
        for index, length in enumerate(up["chunks"]):
            chunk = os.urandom(length)
            self.call("PUT", f"/uploads/{up['upload_id']}/chunks/{index}", raw=chunk,
                      headers={"X-Mutis-Chunk-SHA256": b64u(hashlib.sha256(chunk).digest())})
        self.call("POST", f"/uploads/{up['upload_id']}/complete", {})
        return up

    def share(self, up: dict, max_views: int = 1, with_password: bool = False) -> dict:
        """A link that ends with the file (a link may not outlive its item). with_password makes a
        link + password share: the link proof is then needed before a wrong password counts."""
        access, proof = secrets.token_bytes(32), secrets.token_bytes(32)
        body = {"mode": "link", "wrapped_key": b64u(os.urandom(60)), "access_verifier": b64u(hashlib.sha256(access).digest()),
                "link_verifier": None, "kdf": None, "max_views": max_views, "expires_at": up["item_expires_at"]}
        if with_password:
            body |= {"mode": "link_password", "link_verifier": b64u(hashlib.sha256(proof).digest()),
                     "kdf": {"alg": "PBKDF2-SHA256", "iter": 600000, "salt": b64u(os.urandom(16))}}
        _, sh = self.call("POST", f"/items/{up['item_id']}/shares", body, {"X-Mutis-Manage": up["manage_token"]})
        return sh | {"access": b64u(access), "proof": b64u(proof)}

    def peek(self, share: dict) -> dict:
        return self.call("POST", f"/s/{share['share_id']}/peek", headers={"X-Mutis-Access": share["access"]})[1]

    def open(self, share: dict) -> dict:
        return self.call("POST", f"/s/{share['share_id']}/open", headers={"X-Mutis-Access": share["access"]})[1]

    # --- lockers, drops, courier, abuse -----------------------------------------------------------

    def register(self) -> str:
        auth_key = secrets.token_bytes(32)
        body = {"identity_id": b64u(secrets.token_bytes(16)), "auth_verifier": b64u(hashlib.sha256(auth_key).digest()),
                "pow": self.pow("register")}
        _, res = self.call("POST", "/auth/register", body)
        self.token = res["token"]
        return res["identity_id"]

    def create_drop(self, address: str, label: str = "") -> dict:
        manage = secrets.token_bytes(32)
        body = {"address": address, "tag": b64u(os.urandom(16)), "label": label,
                "manage_verifier": b64u(hashlib.sha256(manage).digest()),
                "pow": self.pow("drop_create")}
        return self.call("POST", "/drops", body)[1] | {"manage": b64u(manage)}

    def courier_to_drop(self, drop_id: str, blob: str | None = None) -> dict:
        body = {"to": "drop", "drop_id": drop_id, "kind": 3, "blob": blob or b64u(os.urandom(125)),
                "pow": self.pow("courier")}
        return self.call("POST", "/courier", body)[1]

    def courier_to_address(self, address: str, blob: str | None = None) -> dict:
        body = {"to": "address", "address": address, "kind": 3, "blob": blob or b64u(os.urandom(125))}
        return self.call("POST", "/courier", body)[1]

    def invoice(self, pack: str = "s30") -> dict:
        return self.call("POST", "/invoices", {"pack": pack})[1]

    def demo_pay(self, invoice_id: str) -> dict:
        return self.call("POST", f"/invoices/{invoice_id}/demo-pay", {"pow": self.pow("demo_pay")})[1]

    def job(self, job_id: str) -> dict:
        return self.call("GET", f"/jobs/{job_id}")[1]

    def report(self, link: str, category: str = "other", details: str = "e2e test report") -> dict:
        body = {"link": link, "category": category, "details": details, "contact": None,
                "pow": self.pow("report")}
        return self.call("POST", "/abuse", body)[1]
