#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Sidecar tests (gate G4, sidecar half), Python stdlib only. Runs the sidecar the way the chain worker
will (Debian node 20, permission model, MUTIS_API as the only environment variable) and speaks the
§3.4.6 protocol over its pipes. A small fake of the API takes the canary's requests.

  python3 -I web/app/tests/sidecar_test.py
"""
import base64
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NODE = shutil.which("node") or "/usr/bin/node"
FLAGS = ["--experimental-permission", "--disallow-code-generation-from-strings"]
WASM_SHA256 = "2856d86b688959fc6620ac8cf2cb4629ee554c94bd81a6baaa2a71a7e7a393f2"
results = []
SHARE_ID = base64.urlsafe_b64encode(bytes(range(16))).rstrip(b"=").decode()  # ids are b64u of 16 bytes


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


class FakeApi(BaseHTTPRequestHandler):
    """Just enough of §6 for the canary: uploads, chunks, complete, shares, courier."""
    calls = []
    uploads = {}

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.handle_call("POST")

    def do_PUT(self):
        self.handle_call("PUT")

    def handle_call(self, method):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.loads(raw) if self.headers.get("Content-Type", "").startswith("application/json") else raw
        FakeApi.calls.append({"method": method, "path": self.path, "headers": dict(self.headers), "body": body})
        p = self.path[len("/api/v1"):]
        if p == "/uploads":
            FakeApi.uploads["u1"] = {"hashes": {}, "count": body["chunk_count"]}
            # As the server: expires_at is when the upload session ends (2 h), not the item's expiry.
            return self.reply(201, {"upload_id": "u" * 22, "item_id": "i" * 22, "manage_token": b64u(b"m" * 32), "expires_at": int(time.time()) + 7200})
        if "/chunks/" in p:
            FakeApi.uploads["u1"]["hashes"][int(p.rsplit("/", 1)[1])] = hashlib.sha256(raw).digest()
            self.send_response(204)
            self.end_headers()
            return None
        if p.endswith("/complete"):
            h = FakeApi.uploads["u1"]["hashes"]
            ct = hashlib.sha256(b"".join(h[i] for i in sorted(h))).digest()
            return self.reply(200, {"item_id": "i" * 22, "ct_hash": b64u(ct), "size_stored": 0})
        if p.endswith("/shares"):
            return self.reply(201, {"share_id": SHARE_ID, "path": "/s/" + SHARE_ID, "state": "active", "max_views": body["max_views"], "expires_at": body["expires_at"]})
        if p == "/courier":
            return self.reply(202, {"job_id": "j" * 22, "not_before": int(time.time()) + 10})
        return self.reply(404, {"error": {"code": "not_found"}})


class Sidecar:
    def __init__(self, app_dir, api):
        self.p = subprocess.Popen([NODE, *FLAGS, f"--allow-fs-read={app_dir}", os.path.join(app_dir, "sidecar", "sidecar.mjs")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env={"MUTIS_API": api}, text=True)
        self.next_id = 0

    def ask(self, cmd, **fields):
        self.next_id += 1
        self.p.stdin.write(json.dumps({"id": self.next_id, "cmd": cmd, **fields}) + "\n")
        self.p.stdin.flush()
        res = json.loads(self.p.stdout.readline())
        assert res["id"] == self.next_id, "responses in request order"
        return res

    def raw(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def close(self):
        self.p.stdin.close()
        self.p.wait(10)
        return self.p.stderr.read()


def main():
    wrap = json.load(open(os.path.join(APP, "tests", "vectors", "wrap-v2.json"), encoding="utf-8"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{server.server_address[1]}"

    sc = Sidecar(APP, api)
    hello = sc.ask("hello")
    check("hello: version, pinned wasm hash, node 20, permission model on",
          hello["ok"] and hello["wasm_sha256"] == WASM_SHA256 and hello["node"].startswith("v20.") and hello["permission"] is True,
          f"{hello.get('node')} {hello.get('version')}")

    keys = sc.ask("newKeys")
    check("newKeys: four 32-byte hex keys and an otl_esm_ address",
          keys["ok"] and all(len(keys[k]) == 64 for k in ("owner_sk", "view_sk", "owner_pk", "view_pk")) and keys["address"].startswith("otl_esm_1"))
    decoy = sc.ask("decoyAddress")
    check("decoyAddress: a fresh address each time", decoy["ok"] and decoy["address"] != sc.ask("decoyAddress")["address"])

    st = sc.ask("selftest")
    check("selftest: real outputs open, every forgery is rejected (G4)", st["ok"] and st["passed"],
          "; ".join(f"{c['name'][:48]}={'ok' if c['passed'] else 'NO'}" for c in st.get("cases", [])))

    own = json.load(open(os.path.join(APP, "sidecar", "selftest.json"), encoding="utf-8"))["ownership"]
    otk = {n: sc.ask("oneTimeKey", owner_sk=own["owner_sk"], nonce=own[n]["nonce"]) for n in ("genuine", "not_ours")}
    check("oneTimeKey (R1): our owner key derives the genuine output's one-time key, not the other one's",
          otk["genuine"].get("public_key") == own["genuine"]["auth_key"]
          and otk["not_ours"]["ok"] and otk["not_ours"].get("public_key") != own["not_ours"]["auth_key"])
    bad = sc.ask("oneTimeKey", owner_sk=own["owner_sk"], nonce="ff" * 32)
    check("oneTimeKey: a nonce that isn't a point is refused", not bad["ok"] and bad["error"] == "bad_point", bad.get("error", ""))

    wallet_rows = [r for r in wrap["real_outputs"] if r["owner"] == "gate wallet"]
    mixed = [{k: r[k] for k in ("id", "nonce", "enc")} for r in wrap["real_outputs"]] + [{k: c[k] for k in ("id", "nonce", "enc")} for c in wrap["crafted"]]
    found = sc.ask("scan", view_sk=wallet_rows[0]["view_sk"], utxos=mixed)
    got = sorted((f["id"], f["value_ut"]) for f in found["found"])
    want = sorted((r["id"], r["value_ut"]) for r in wallet_rows)
    check("scan: finds exactly this view key's real outputs with proven values; crafted rows skipped", got == want, str([v for _, v in got]))

    rows = json.loads(subprocess.run([NODE, os.path.join(APP, "tests", "make-rows.mjs"), "3000"], check=True,
                                     capture_output=True, text=True).stdout)
    rates = []
    for _ in range(3):
        t0 = time.perf_counter()
        r = sc.ask("scan", view_sk=keys["view_sk"], utxos=rows)
        rates.append(len(rows) / (time.perf_counter() - t0))
        assert r["ok"] and r["found"] == []
    rate = statistics.median(rates)
    check("scan speed ≥ 2,000 UTXOs/s (3,000 foreign rows, median of 3)", rate >= 2000, f"{rate:,.0f} rows/s")

    robot = sc.ask("newKeys")
    token = b64u(os.urandom(32))
    canary = sc.ask("canary", n=812, canary_token=token, robot_address=robot["address"])
    calls = FakeApi.calls
    up = next(c for c in calls if c["path"] == "/api/v1/uploads")
    share = next(c for c in calls if c["path"].endswith("/shares"))
    courier = next(c for c in calls if c["path"] == "/api/v1/courier")
    now = int(time.time())
    check("canary: uploads with the canary token, no PoW, a text item living ≤ 48 h",
          canary["ok"] and all(c["headers"].get("X-Mutis-Canary") == token for c in calls) and "pow" not in up["body"]
          and up["body"]["expires_at"] <= now + 172800 and up["body"]["retention"] == "ephemeral")
    check("canary: one link, 3 views, 24 h; courier kind 3 to the robot locker as evidence",
          share["body"]["mode"] == "link" and share["body"]["max_views"] == 3 and share["body"]["expires_at"] <= now + 86400
          and courier["body"]["to"] == "address" and courier["body"]["address"] == robot["address"] and courier["body"]["kind"] == 3
          and courier["body"]["evidence"] is True and len(unb64u(courier["body"]["blob"])) == 125
          and canary["share_id"] == SHARE_ID and canary["job_id"] == "j" * 22)
    secrets_seen = json.dumps([c["body"] if isinstance(c["body"], dict) else "<bytes>" for c in calls])
    check("canary: no request carries the canary's text", "If you can read this" not in secrets_seen)

    memo = "https://srv2052606.hstgr.cloud/t#3" + courier["body"]["blob"]
    opened = sc.ask("openDelivery", memo={"Message": memo}, owner_sk=robot["owner_sk"], view_sk=robot["view_sk"],
                    origins=["https://srv2052606.hstgr.cloud", "https://mutis.sh"])
    verifier = hashlib.sha256(unb64u(opened.get("access_token", ""))).digest()
    check("openDelivery: the robot keys unwrap the delivery to the canary's link, whose access token the server accepts",
          opened["ok"] and opened["share_id"] == SHARE_ID and b64u(verifier) == share["body"]["access_verifier"])
    wrong = sc.ask("openDelivery", memo=memo, owner_sk=keys["owner_sk"], view_sk=keys["view_sk"])
    check("openDelivery: another locker's keys can't open it", not wrong["ok"] and wrong["error"] == "cannot_open")

    rev = sc.ask("reveal", n=812)
    check("reveal (P1): the canary's file key stays in memory and can be published later",
          rev["ok"] and len(unb64u(rev["fk"])) == 32 and not sc.ask("reveal", n=1)["ok"])

    errs = [sc.raw("{not json"), sc.ask("rm -rf"), sc.ask("scan", view_sk="zz", utxos=[]), sc.ask("canary", n=1, canary_token="x", robot_address="nope")]
    check("protocol errors are fixed codes", [e.get("error") for e in errs] == ["bad_json", "unknown_cmd", "bad_request", "bad_request"],
          str([e.get("error") for e in errs]))
    stderr = sc.close()
    node_notice = ("ExperimentalWarning: Permission is an experimental feature", "(Use `node --trace-warnings")
    lines = [l for l in stderr.splitlines() if not any(n in l for n in node_notice)]
    check("stderr carries fixed strings only (ours, plus Node's own permission notice)", lines == ["mutis-sidecar: ready"], repr(stderr[:160]))

    with tempfile.TemporaryDirectory() as tmp:
        probe = os.path.join(tmp, "probe.mjs")
        with open(probe, "w") as f:
            f.write("import fs from 'node:fs'; import cp from 'node:child_process'; import { Worker } from 'node:worker_threads';\n"
                    "const r = [];\n"
                    "try { fs.writeFileSync('/tmp/mutis-sidecar-probe', 'x'); r.push('write:allowed'); } catch (e) { r.push('write:' + e.code); }\n"
                    "try { cp.spawnSync('id'); r.push('spawn:allowed'); } catch (e) { r.push('spawn:' + e.code); }\n"
                    "try { new Worker('0', { eval: true }); r.push('worker:allowed'); } catch (e) { r.push('worker:' + e.code); }\n"
                    "try { fs.readFileSync('/etc/hostname'); r.push('read-outside:allowed'); } catch (e) { r.push('read-outside:' + e.code); }\n"
                    "try { eval('1'); r.push('eval:allowed'); } catch (e) { r.push('eval:' + e.name); }\n"
                    "console.log(r.join(' '));\n")
        out = subprocess.run([NODE, *FLAGS, f"--allow-fs-read={tmp}", probe], capture_output=True, text=True).stdout.strip()
        check("permission model: writes, child processes, workers, reads outside, eval all denied",
              out == "write:ERR_ACCESS_DENIED spawn:ERR_ACCESS_DENIED worker:ERR_ACCESS_DENIED read-outside:ERR_ACCESS_DENIED eval:EvalError", out)

        tampered = os.path.join(tmp, "app")
        for d in ("lib", "sidecar", "vendor"):
            shutil.copytree(os.path.join(APP, d), os.path.join(tampered, d))
        wasm = os.path.join(tampered, "vendor", "ootle-wasm-0.46.0", "ootle_wasm_bg.wasm")
        data = bytearray(open(wasm, "rb").read())
        data[len(data) // 2] ^= 1
        open(wasm, "wb").write(bytes(data))
        p = subprocess.run([NODE, *FLAGS, f"--allow-fs-read={tampered}", os.path.join(tampered, "sidecar", "sidecar.mjs")],
                           input='{"id":1,"cmd":"hello"}\n', capture_output=True, text=True, env={"MUTIS_API": api}, timeout=30)
        check("a wasm file that isn't the pinned build: the sidecar refuses to start",
              p.returncode == 2 and p.stdout == "" and "hash mismatch" in p.stderr, f"exit {p.returncode}")

    server.shutdown()
    failed = [n for n, ok, _ in results if not ok]
    print(f"{'SIDECAR PASS' if not failed else 'SIDECAR FAIL'} {len(results) - len(failed)}/{len(results)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
