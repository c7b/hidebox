#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The judges' demo secret (14-ghost-design §9 and §17 step 9; claim C31): a goodbye that is already on
the Tari chain when a judge reaches /judges, track one, step 4. A release step, run as root on the
server at least one SealLog checkpoint (seal_log.checkpoint_interval_s, 15 minutes) before the git tag,
and again if judging runs past the 30 days a tombstone lives (spec §5.2):

  sudo python3 -I /srv/mutis/app/current/deploy/scripts/demo-gone.py burn    # make it, burn it, serve its id
  sudo python3 -I /srv/mutis/app/current/deploy/scripts/demo-gone.py check   # 0 once its goodbye is in a checkpoint

burn: through this server's public API (its own Caddy, real proofs of work, like any visitor), locks a
small note of random bytes that nobody holds a key for (it is never
meant to open), makes a Once link to it, opens it (that open is the burn), ends the download ticket so
the ciphertext goes at once, then writes `judge_demo_gone = "<share id>"` into /etc/mutis/mutis.toml
(replacing an older value; owner and mode kept), restarts mutis-api, checks that /api/v1/config serves
the id, and prints the earliest time to tag. /judges links /s/<id>: its gone page shows "We wrote its
goodbye on the Tari chain" and See the goodbye, which /verify checks in the judge's browser.
check: asks /api/v1/s/<id>/exit; exits 0 when the exit leaf is in a checkpoint, 1 while it waits.
Python standard library only; nothing here touches walletd, a budget or a limit.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path("/etc/mutis/mutis.toml")
KEY = "judge_demo_gone"
SHARE_ID = re.compile(r"[A-Za-z0-9_-]{22}")
META_LEN = 12 + 256 + 16          # the shortest meta_ct the server accepts
TAG = 16                          # the AES-GCM tag of the one chunk


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte:
            return bits + 8 - byte.bit_length()
        bits += 8
    return bits


def set_key(text: str, share_id: str) -> str:
    """mutis.toml with `judge_demo_gone = "<share_id>"` at the top level: an existing line is replaced;
    otherwise the line goes after repo_url, or before the first [table]. Everything else is kept."""
    if not SHARE_ID.fullmatch(share_id):
        raise ValueError(f"not a share id: {share_id!r}")
    line = f'{KEY} = "{share_id}"'
    lines = text.splitlines()
    first_table = next((i for i, l in enumerate(lines) if l.lstrip().startswith("[")), len(lines))
    for i, l in enumerate(lines[:first_table]):
        if re.match(rf"\s*{KEY}\s*=", l):
            lines[i] = line
            break
    else:
        anchor = next((i + 1 for i, l in enumerate(lines[:first_table]) if re.match(r"\s*repo_url\s*=", l)), None)
        if anchor is None:
            anchor = first_table
            while anchor > 0 and not lines[anchor - 1].strip():
                anchor -= 1
        lines.insert(anchor, line)
    out = "\n".join(lines) + "\n"
    if tomllib.loads(out).get(KEY) != share_id:
        raise ValueError("the edited configuration doesn't read back")
    return out


def write_config(path: Path, text: str) -> None:
    """Replace the file atomically with the same owner and mode."""
    st = path.stat()
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, st.st_mode & 0o7777)
    os.replace(tmp, path)


class Api:
    def __init__(self, origin: str):
        self.origin = origin.rstrip("/")

    def call(self, method: str, path: str, body=None, headers: dict | None = None, raw: bytes | None = None):
        h = {"User-Agent": "mutis-demo-gone", "Origin": self.origin}
        data = raw
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif raw is not None:
            h["Content-Type"] = "application/octet-stream"
        h.update(headers or {})
        req = urllib.request.Request(self.origin + "/api/v1" + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = res.read()
                return json.loads(payload) if payload[:1] == b"{" else None
        except urllib.error.HTTPError as e:
            raise SystemExit(f"demo-gone: {method} {path}: {e.code} {e.read()[:200]!r}") from None

    def pow(self, purpose: str) -> dict:
        ch = self.call("POST", "/pow", {"purpose": purpose})
        challenge, n = unb64u(ch["challenge"]), 0
        while zero_bits(hashlib.sha256(challenge + struct.pack(">Q", n)).digest()) < ch["difficulty"]:
            n += 1
        return {"challenge": ch["challenge"], "nonce": b64u(struct.pack(">Q", n))}


def burn(api: Api) -> str:
    """A Once link to random bytes, opened once: its share id."""
    expires = int(time.time()) + 3600
    stored = 1024 + TAG
    header = struct.pack(">4sBBHII", b"MTS1", 1, 22, 0, 1, 0) + secrets.token_bytes(16)
    up = api.call("POST", "/uploads", {
        "retention": "ephemeral", "header": b64u(header), "meta_ct": b64u(os.urandom(META_LEN)), "chunk_count": 1,
        "size_stored": stored, "owner_wrap": None, "drop_id": None, "expires_at": expires, "pow": api.pow("upload")})
    chunk = os.urandom(stored)
    api.call("PUT", f"/uploads/{up['upload_id']}/chunks/0", raw=chunk,
             headers={"X-Mutis-Chunk-SHA256": b64u(hashlib.sha256(chunk).digest())})
    api.call("POST", f"/uploads/{up['upload_id']}/complete", {})
    access = secrets.token_bytes(32)
    share = api.call("POST", f"/items/{up['item_id']}/shares", {
        "mode": "link", "wrapped_key": b64u(os.urandom(60)), "access_verifier": b64u(hashlib.sha256(access).digest()),
        "link_verifier": None, "kdf": None, "max_views": 1, "expires_at": expires}, {"X-Mutis-Manage": up["manage_token"]})
    opened = api.call("POST", f"/s/{share['share_id']}/open", headers={"X-Mutis-Access": b64u(access)})
    if not opened.get("burned"):
        raise SystemExit("demo-gone: the open didn't burn the link")
    if opened.get("ticket"):
        api.call("POST", f"/blobs/{opened['ticket']}/done", {})
    return share["share_id"]


def served(api: Api, share_id: str, tries: int = 30) -> bool:
    for _ in range(tries):
        try:
            if api.call("GET", "/config").get(KEY) == share_id:
                return True
        except SystemExit:
            pass
        time.sleep(2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("burn", "check"))
    ap.add_argument("--config", type=Path, default=CONFIG)
    args = ap.parse_args()
    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    api = Api(cfg.get("public_origin", "https://srv2052606.hstgr.cloud"))
    interval = int(cfg.get("seal_log", {}).get("checkpoint_interval_s", 900))
    if args.action == "check":
        share_id = cfg.get(KEY, "")
        if not SHARE_ID.fullmatch(share_id):
            print("demo-gone: no judge_demo_gone in the configuration; run `burn` first")
            return 1
        r = api.call("GET", f"/s/{share_id}/exit")
        if r.get("leaf_index") is not None and r.get("checkpoint"):
            print(f"demo-gone: {share_id} said bye at checkpoint #{r['checkpoint'].get('index', '?')}; ready to tag")
            return 0
        print(f"demo-gone: {share_id} waits for the next checkpoint (reason {r.get('reason')})")
        return 1
    if os.geteuid() != 0:
        print("demo-gone: burn writes /etc/mutis/mutis.toml and restarts mutis-api: run it as root", file=sys.stderr)
        return 2
    if not cfg.get("features", {}).get("seallog"):
        print("demo-gone: features.seallog is off, so no goodbye would reach the chain; nothing done", file=sys.stderr)
        return 2
    share_id = burn(api)
    write_config(args.config, set_key(args.config.read_text(encoding="utf-8"), share_id))
    subprocess.run(["systemctl", "restart", "mutis-api"], check=True)
    if not served(api, share_id):
        print(f"demo-gone: /api/v1/config doesn't serve {share_id}", file=sys.stderr)
        return 1
    at = datetime.datetime.now(datetime.timezone.utc)
    ready = (at + datetime.timedelta(seconds=interval)).strftime("%Y-%m-%d %H:%M UTC")
    print(f"demo-gone: burned {share_id} at {at:%Y-%m-%d %H:%M:%S} UTC; /judges links /s/{share_id}")
    print(f"demo-gone: tag no earlier than {ready}, after `demo-gone.py check` says ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
