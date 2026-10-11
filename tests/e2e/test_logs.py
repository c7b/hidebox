#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""D-02: nothing that identifies a visitor or a link reaches a log, tested from outside (spec §14.3),
and the relay (our walletd) keeps no destination or memo (the /how claim "sees, never stores").

  python3 -I tests/e2e/test_logs.py [--origin URL] [--host ultron] [--relay]
  python3 -I tests/e2e/test_logs.py --walletd-probe [--host ultron]

Run on the jarvis box. 1) A scripted session against the public origin, once over IPv6 (an address
this machine never uses for SSH) and once over IPv4: anonymous upload, link, peek and open with
X-Mutis-Access; a locker, a dead drop, a drop delivery; a relay send to an address (with --relay
it waits until the chain worker has sent it through walletd). 2) mutis-api is stopped while requests
carrying X-Mutis-Access are in flight, so Caddy logs real 502s, then started again. 3) As root on
ultron: every journal entry (all units, export format), every file under /var/log, and every file
under /home/drive/wallet (walletd's database and its -wal, its logs, its backups) is searched for
this machine's addresses, every id, token and address of the session, the destination's public keys
(hex and as JSON byte arrays) and each memo blob (base64url, base64 and hex). Our own key files'
backups (backup/robot-*.json, backup/receiver-*.json) are skipped: they hold the destination used
here, the robot locker, by design. The needles reach ultron on stdin, never on a command line (sudo
logs command lines). Zero hits pass. Hits for the IPv4 address in sshd, logind or login records are
operator SSH access, not visitor traffic; they are listed apart and don't fail the test.

--walletd-probe needs neither the API nor the chain worker: as drive, with the server's own code
(jobs.courier_memo, Walletd.stealth_transfer, Sidecar), it makes one relay-shaped send from the
sponsor account (courier amount plus fee) to a throwaway address the sidecar makes, then searches
the same places for that address, its keys and the memo. As a control, the same search must find
the send's transaction id in walletd's database (walletd keeps its own transactions), which shows the
search reaches the place where a destination would be.
"""
import argparse
import base64
import ipaddress
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apiclient  # noqa: E402

OPERATOR_SOURCES = ("sshd", "sshd-session", "systemd-logind", "/var/log/wtmp", "/var/log/btmp",
                    "/var/log/lastlog", "/var/log/wtmp.db")

# Runs as root on the server, read from stdin by `python3 -I -`; NEEDLES is filled in before sending.
GREP = r'''
import json, subprocess
needles = json.loads(NEEDLES)
hits = []
journal = subprocess.run(["journalctl", "--no-pager", "-o", "json"], capture_output=True, text=True).stdout
for line in journal.splitlines():
    found = [n for n in needles if n["value"] in line]
    if found:
        entry = json.loads(line)
        where = entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or entry.get("_SYSTEMD_UNIT", "?")
        hits += [{"needle": n["name"], "where": where, "file": "journal"} for n in found]
patterns = "\n".join(n["value"] for n in needles) + "\n"
for root in ("/var/log", "/home/drive/wallet"):
    out = subprocess.run(["grep", "-rlaF", "--exclude-dir=journal", "--exclude=robot-*.json",
                          "--exclude=receiver-*.json", "-f", "/dev/stdin", root],
                         input=patterns, capture_output=True, text=True).stdout.split()
    for path in out:
        data = open(path, "rb").read().decode("latin-1")
        hits += [{"needle": n["name"], "where": path, "file": path} for n in needles if n["value"] in data]
print(json.dumps(hits))
'''

# Runs as drive on the server (stdin), with the release's own server code: one send exactly as the
# relay makes it, to a throwaway address. Prints only public values.
PROBE = r'''
import json, os, sys
sys.path.insert(0, "/srv/mutis/app/current/server")
from mutis import config, jobs
from mutis.sidecar import Sidecar
from mutis.walletd import Walletd
cfg = config.load("/etc/mutis/mutis.toml")
o = cfg["ootle"]
sidecar = Sidecar(cfg.sidecar_argv(), "http://127.0.0.1:8787", config.PINNED_WASM_SHA256)
keys = sidecar.request("newKeys")
sidecar.stop()
blob = os.urandom(125)
memo = jobs.courier_memo(cfg.origin, 3, blob)
walletd = Walletd(o["walletd_url"])
tx = walletd.stealth_transfer(o["sponsor_account"], keys["address"], o["courier_amount_ut"], memo, o["max_fee_transfer_ut"])
done = walletd.wait_result(tx, 180)
print(json.dumps({"tx_id": tx, "committed": done["committed"], "address": keys["address"],
                  "owner_pk": keys["owner_pk"], "view_pk": keys["view_pk"], "blob_hex": blob.hex()}))
'''


def key_needles(label: str, owner_pk: str, view_pk: str) -> list[tuple[str, str]]:
    """A public key as walletd might store it: hex, or a JSON array of its bytes."""
    out = []
    for name, hex_key in (("owner key", owner_pk), ("view key", view_pk)):
        raw = bytes.fromhex(hex_key)
        out += [(f"{label} {name} (hex)", hex_key), (f"{label} {name} (bytes)", json.dumps(list(raw)).replace(" ", "")),
                (f"{label} {name} (bytes, spaced)", json.dumps(list(raw)))]
    return out


def blob_needles(label: str, blob: bytes) -> list[tuple[str, str]]:
    return [(f"{label} (base64url)", apiclient.b64u(blob)), (f"{label} (base64)", base64.b64encode(blob).decode()),
            (f"{label} (hex)", blob.hex())]


def source_address(host: str, family: int) -> str | None:
    """The address this machine sends from to `host` (no packet is sent)."""
    try:
        target = socket.getaddrinfo(host, 443, family, socket.SOCK_DGRAM)[0][4]
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect(target)
            return s.getsockname()[0]
    except OSError:
        return None


@contextmanager
def only_family(family: int):
    real = socket.getaddrinfo

    def filtered(*args, **kwargs):
        return [a for a in real(*args, **kwargs) if a[0] == family]
    socket.getaddrinfo = filtered
    try:
        yield
    finally:
        socket.getaddrinfo = real


def session(origin: str, destination: str, relay_wait: bool) -> list[tuple[str, str]]:
    """Run the scripted session; return the (name, value) pairs that must never be logged."""
    secret = []
    a = apiclient.Client(origin)
    up = a.upload(3000)
    sh = a.share(up, max_views=2)
    a.peek(sh)
    opened = a.open(sh)
    secret += [("item id", up["item_id"]), ("upload id", up["upload_id"]), ("manage token", up["manage_token"]),
               ("share id", sh["share_id"]), ("access token", sh["access"])]
    if opened.get("ticket"):
        secret.append(("download ticket", opened["ticket"]))
    owner = apiclient.Client(origin)
    owner.register()
    secret.append(("session token", owner.token))
    drop = owner.create_drop(destination, "log test")
    secret += [("drop id", drop["drop_id"]), ("drop manage token", drop["manage"])]
    sub = apiclient.Client(origin)
    up2 = sub.upload(2000, drop_id=drop["drop_id"])
    secret.append(("drop item id", up2["item_id"]))
    jobs = {}
    for kind, send in (("drop", lambda blob: sub.courier_to_drop(drop["drop_id"], blob)),
                       ("relay", lambda blob: owner.courier_to_address(destination, blob))):
        raw = os.urandom(125)
        secret += blob_needles(f"{kind} memo blob", raw)
        try:
            jobs[kind] = send(apiclient.b64u(raw))["job_id"]
            secret.append((f"{kind} job id", jobs[kind]))
        except apiclient.ApiError as e:
            if e.code != "chain_unavailable":
                raise
            print(f"note: the {kind} delivery was refused with chain_unavailable (mutis-chain is not running)")
    if relay_wait and "relay" in jobs:
        end = time.time() + 300
        while time.time() < end and owner.job(jobs["relay"])["state"] not in ("done", "failed"):
            time.sleep(5)
        job = owner.job(jobs["relay"])
        if job.get("result") and job["result"].get("tx_id"):
            secret.append(("relay tx id", job["result"]["tx_id"]))
    return secret


def force_502s(origin: str, ssh: list[str], access_share: dict) -> int:
    """Stop mutis-api while requests with X-Mutis-Access are in flight; return how many got 502."""
    count = {"502": 0}
    stop = threading.Event()
    client = apiclient.Client(origin)

    def hammer():
        while not stop.is_set():
            try:
                client.peek(access_share)
            except apiclient.ApiError as e:
                count["502"] += e.status == 502
            except OSError:
                pass
            time.sleep(0.05)
    t = threading.Thread(target=hammer)
    t.start()
    time.sleep(1)
    subprocess.run(ssh + ["sudo systemctl stop mutis-api"], check=True)
    time.sleep(4)
    subprocess.run(ssh + ["sudo systemctl start mutis-api"], check=True)
    time.sleep(3)
    stop.set()
    t.join()
    return count["502"]


def walletd_probe(ssh: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    out = subprocess.run(ssh + ["cd /tmp && sudo -u drive python3 -I -"], input=PROBE, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"walletd probe failed: {out.stderr.strip()[-300:]}")
    sent = json.loads(out.stdout.strip().splitlines()[-1])
    print(f"walletd probe: relay-shaped send {sent['tx_id'][:12]}… committed={sent['committed']}")
    if not sent["committed"]:
        raise SystemExit("walletd probe: the send did not commit; nothing to search for")
    blob = bytes.fromhex(sent["blob_hex"])
    needles = ([("probe destination address", sent["address"])] + key_needles("probe destination", sent["owner_pk"], sent["view_pk"])
               + blob_needles("probe memo blob", blob))
    return needles, [("the probe transaction id", sent["tx_id"])]


def main() -> int:
    p = argparse.ArgumentParser(description="D-02 log hygiene, tested from outside")
    p.add_argument("--origin", default="https://srv2052606.hstgr.cloud")
    p.add_argument("--host", default="ultron", help="ssh host of the server")
    p.add_argument("--relay", action="store_true", help="wait for the relay send (needs mutis-chain and a sponsor)")
    p.add_argument("--walletd-probe", action="store_true",
                   help="only: one relay-shaped send straight through walletd, then search (no API needed)")
    args = p.parse_args()
    origin = args.origin.rstrip("/")
    hostname = urllib.parse.urlsplit(origin).hostname
    # One multiplexed connection: ufw's `limit 22/tcp` drops a seventh new connection within 30 s.
    control = tempfile.mkdtemp(prefix="mutis-logs-")
    ssh = ["ssh", "-o", "ControlMaster=auto", "-o", f"ControlPath={control}/cm", "-o", "ControlPersist=5m",
           "-o", "ClearAllForwardings=yes", args.host]
    if args.walletd_probe:
        return search(ssh, *walletd_probe(ssh))
    if subprocess.run(ssh + ["systemctl is-active --quiet mutis-api"]).returncode != 0:
        print("SKIP mutis-api is not running on the server; start it (systemctl start mutis-api) and run again")
        return 2
    # Our own robot locker is the destination: a real, spendable address. Only its public part leaves ultron.
    robot = subprocess.run(ssh + ["sudo python3 -I -c 'import json; r = json.load(open(\"/home/drive/mutis/robot.json\")); "
                                  "print(json.dumps({k: r[k] for k in (\"address\", \"owner_pk\", \"view_pk\")}))'"],
                           capture_output=True, text=True, check=True)
    public = json.loads(robot.stdout)
    destination = public["address"]

    needles = [("destination address", destination)] + key_needles("destination", public["owner_pk"], public["view_pk"])
    for family, label in ((socket.AF_INET6, "IPv6"), (socket.AF_INET, "IPv4")):
        ip = source_address(hostname, family)
        if not ip:
            print(f"SKIP no {label} route to {hostname}")
            continue
        needles.append((f"this machine's {label} address", ip))
        if family == socket.AF_INET6:
            needles.append(("this machine's IPv6 address, expanded", ipaddress.ip_address(ip).exploded))
            net = ipaddress.ip_network(ip + "/64", strict=False).network_address
            needles.append(("this machine's IPv6 /64", net.exploded[:20]))
            needles.append(("this machine's IPv6 /64, compressed", str(net).rstrip(":") + ":"))
        with only_family(family):
            needles += [(f"{name} ({label})", value) for name, value in session(origin, destination, args.relay)]
            target = apiclient.Client(origin)
            share = target.share(target.upload(1000), max_views=10)
            needles += [(f"502-test share id ({label})", share["share_id"]), (f"502-test access token ({label})", share["access"])]
            print(f"session over {label} from {ip}: done; 502s forced: {force_502s(origin, ssh, share)}")
    return search(ssh, needles)


def search(ssh: list[str], needles: list[tuple[str, str]], controls: list[tuple[str, str]] = ()) -> int:
    """Search for `needles` (any hit fails) and `controls` (each must be found in walletd's database)."""
    script = GREP.replace("NEEDLES", repr(json.dumps([{"name": n, "value": v} for n, v in [*needles, *controls]])))
    out = subprocess.run(ssh + ["sudo python3 -I -"], input=script, capture_output=True, text=True, check=True).stdout
    found = json.loads(out)
    control_names = {n for n, _ in controls}
    missing = [n for n in control_names if not any(h["needle"] == n and "wallet.sqlite" in h["where"] for h in found)]
    for name in sorted(control_names - set(missing)):
        print(f"control {name}: found in walletd's database, as expected")
    hits = [h for h in found if h["needle"] not in control_names]
    operator = [h for h in hits if "IPv4 address" in h["needle"] and h["where"].startswith(OPERATOR_SOURCES)]
    visitor = [h for h in hits if h not in operator]
    print(f"searched the journal, /var/log and /home/drive/wallet (database, logs, backups) for {len(needles)} values")
    for h in visitor:
        print(f"FAIL {h['needle']} found in {h['where']}")
    for h in operator:
        print(f"note {h['needle']} in {h['where']} (operator SSH access, not visitor traffic)")
    for name in missing:
        print(f"FAIL control {name} not found: the search did not reach walletd's database")
    ok = not visitor and not missing
    print(f"test_logs: {'PASS' if ok else 'FAIL'} ({len(visitor)} hits)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
