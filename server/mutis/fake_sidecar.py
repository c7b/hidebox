# SPDX-License-Identifier: MIT
"""A fake verifier sidecar speaking the spec §3.4.6 protocol over stdin/stdout, for tests and --dev mode.

It opens FakeChain outputs instead of real ones and uploads a canary whose bytes are random, so it
proves nothing about cryptography; it lets the server's side of the protocol be tested end to end.
Start it with `argv()`.
"""
import json
import os
import re
import secrets
import struct
import sys
import time
import urllib.request
from pathlib import Path

from . import codec, quota
from .fake_chain import FAKE_WASM_SHA256, fake_keys, open_output

_MEMO = re.compile(r"/t#3([A-Za-z0-9_-]{167})$")
_canaries: dict[int, dict] = {}


def argv() -> list[str]:
    server_dir = str(Path(__file__).resolve().parents[1])
    return [sys.executable, "-I", "-c",
            f"import sys; sys.path.insert(0, {server_dir!r}); from mutis.fake_sidecar import main; main()"]


def _api(method: str, path: str, token: str, body=None, raw: bytes | None = None, headers=None) -> dict:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(os.environ["MUTIS_API"] + path, data=data, method=method,
                                 headers={"X-Mutis-Canary": token, "Content-Type": "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read()
    return json.loads(text) if text else {}


def canary(n: int, token: str, robot_address: str) -> dict:
    codec.unb64u(token, 32)
    now = _api("GET", "/api/v1/health", token)["time"]       # the server's clock (tests move it)
    size = quota.stored_size(quota.padme(4000))
    header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 0, 1, 0) + secrets.token_bytes(16)
    up = _api("POST", "/api/v1/uploads", token, {
        "retention": "ephemeral", "header": codec.b64u(header), "meta_ct": codec.b64u(secrets.token_bytes(284)),
        "chunk_count": 1, "size_stored": size, "expires_at": now + quota.CANARY_MAX_EXPIRY_S - 60})
    chunk = secrets.token_bytes(size)
    _api("PUT", f"/api/v1/uploads/{up['upload_id']}/chunks/0", token, raw=chunk,
         headers={"Content-Type": "application/octet-stream", "X-Mutis-Chunk-SHA256": codec.b64u(codec.sha256(chunk))})
    _api("POST", f"/api/v1/uploads/{up['upload_id']}/complete", token, {})
    s = secrets.token_bytes(32)
    access = codec.hkdf(s, b"mutis/v1", b"share-access", 32)
    share = _api("POST", f"/api/v1/items/{up['item_id']}/shares", token, {
        "mode": "link", "wrapped_key": codec.b64u(secrets.token_bytes(60)),
        "access_verifier": codec.b64u(codec.sha256(access)), "max_views": 3, "expires_at": now + 86400})
    inner = codec.unb64u(share["share_id"], 16) + s + b"\x00" + bytes(16)
    job = _api("POST", "/api/v1/courier", token, {"to": "address", "address": robot_address, "kind": 3,
                                                  "blob": codec.b64u(inner + bytes(60)), "evidence": True})
    _canaries[n] = {"fk": secrets.token_bytes(32), "sealed_at": now}
    return {"item_id": up["item_id"], "share_id": share["share_id"], "sealed_at": now, "job_id": job["job_id"]}


def open_delivery(memo, origins: list[str]) -> dict:
    text = memo.get("Message") if isinstance(memo, dict) else memo
    m = _MEMO.search(text or "")
    if not m or not any(text.startswith(o + "/t#") for o in origins):
        raise ValueError("not a delivery")
    inner = codec.unb64u(m.group(1), 125)[:65]
    access = codec.hkdf(inner[16:48], b"mutis/v1", b"share-access", 32)
    return {"share_id": codec.b64u(inner[:16]), "flags": inner[48], "ref": inner[49:65].hex(),
            "access_token": codec.b64u(access)}


def scan(view_sk: str, utxos: list[dict]) -> list[dict]:
    found = []
    for u in utxos:
        opened = open_output(bytes.fromhex(view_sk), bytes.fromhex(u["id"].rsplit("_", 1)[1]),
                             bytes.fromhex(u["nonce"]), bytes.fromhex(u["enc"]))
        if opened:
            found.append({"id": u["id"], "value_ut": str(opened[0]), "memo": opened[1]})
    return found


def handle(req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "hello":
        return {"version": "fake", "wasm_sha256": FAKE_WASM_SHA256, "node": "python", "permission": False}
    if cmd == "newKeys":
        return fake_keys()
    if cmd == "decoyAddress":
        return {"address": fake_keys()["address"]}
    if cmd == "scan":
        return {"found": scan(req["view_sk"], req["utxos"])}
    if cmd == "selftest":
        return {"passed": True, "cases": 0}
    if cmd == "canary":
        return canary(int(req["n"]), req["canary_token"], req["robot_address"])
    if cmd == "openDelivery":
        return open_delivery(req["memo"], req["origins"])
    if cmd == "reveal":
        c = _canaries[int(req["n"])]
        return {"n": req["n"], "sealed_at": c["sealed_at"], "fk": codec.b64u(c["fk"])}
    if cmd == "sleep":                       # test hook: never answers in time
        time.sleep(float(req["seconds"]))
        return {}
    raise KeyError(cmd)


def main() -> None:
    for line in sys.stdin:
        req = json.loads(line)
        try:
            reply = {"id": req["id"], "ok": True, **handle(req)}
        except (KeyError, ValueError, OSError):
            reply = {"id": req.get("id"), "ok": False, "error": "not_found" if req.get("cmd") == "reveal" else "failed"}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
