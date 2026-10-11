#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Healthcheck (spec §15.6), every 5 minutes as `mutis` (mutis-health.timer). Python stdlib only.

Writes data/health.json (full detail, not served) and status/status.json (the public subset served at
/status.json: green/amber/red per check, `attention` with fixed reason codes, the mainnet phase).
A red check also writes one CRIT line with its fixed code to the journal. The chain worker's state
comes from the database (meta.chain_status, written by mutis-chain), because `mutis` cannot reach
walletd. No check reads or writes anything that identifies a visitor, a link or an address.
"""
import datetime
import json
import os
import socket
import sqlite3
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GIB = 1 << 30
GREEN, AMBER, RED = "green", "amber", "red"
HEARTBEAT_MAX_S = 60
STATUS_MAX_S = 300
MIRROR_MAX_S = 300
CANARY_MAX_S = 75 * 60
CANARY_VERIFY_S = 20 * 60
SPONSOR_MIN_UT = 200_000_000
CERT_MIN_DAYS = 14


def https_ok(origin: str) -> tuple[str, str]:
    host = urllib.parse.urlsplit(origin).hostname
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as raw, ctx.wrap_socket(raw, server_hostname=host) as tls:
            expires = ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"])
        with urllib.request.urlopen(urllib.request.Request(origin + "/", headers={"User-Agent": "mutis-health"}),
                                    timeout=10) as res:
            status = res.status
    except (OSError, ssl.SSLError, urllib.error.URLError) as e:
        return RED, f"https_unreachable ({type(e).__name__})"
    days = (expires - time.time()) / 86400
    if status != 200:
        return RED, f"home_status_{status}"
    return (GREEN, f"certificate {days:.0f} days") if days > CERT_MIN_DAYS else (RED, "certificate_expiring")


def api_ok(origin: str) -> tuple[str, str]:
    try:
        req = urllib.request.Request(origin + "/api/v1/health", headers={"User-Agent": "mutis-health"})
        with urllib.request.urlopen(req, timeout=10) as res:
            doc = json.load(res)
    except (OSError, ValueError, urllib.error.URLError) as e:
        return RED, f"api_down ({type(e).__name__})"
    return (GREEN, "ok") if doc.get("ok") is True else (RED, "api_not_ok")


def meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return row[0]


def chain_checks(conn: sqlite3.Connection, now: int) -> dict:
    checks = {}
    beat = int(meta(conn, "chain_heartbeat", 0) or 0)
    checks["chain_worker"] = (GREEN, "heartbeat ok") if now - beat < HEARTBEAT_MAX_S else (RED, "chain_worker_stale")
    status = meta(conn, "chain_status", {}) or {}
    fresh = now - int(status.get("updated_at", 0)) < STATUS_MAX_S
    checks["walletd"] = (GREEN, "reachable") if fresh and status.get("walletd_ok") else (RED, "walletd_unreachable")
    checks["sidecar"] = (GREEN, "running") if fresh and status.get("sidecar_ok") else (RED, "sidecar_down")
    balance = int(status.get("sponsor_balance_ut") or 0)
    checks["sponsor_balance"] = (GREEN, f"{balance // 1_000_000} tTARI") if balance > SPONSOR_MIN_UT else \
        (AMBER, "sponsor_low")
    mirror_at = int(status.get("mirror_ok_at") or 0)
    checks["mirror"] = (GREEN, "current") if now - mirror_at < MIRROR_MAX_S else (RED, "mirror_lagging")
    checks["credit_freeze"] = (RED, "credit_freeze_on") if str(meta(conn, "credit_freeze", "")) == "1" else \
        (GREEN, "off")
    log = meta(conn, "canary_log", []) or []
    latest = max(log, key=lambda e: e["sealed_at"], default=None)
    if latest is None or now - latest["sealed_at"] > CANARY_MAX_S:
        checks["canary"] = (RED, "canary_stale")
    elif latest.get("verified"):
        checks["canary"] = (GREEN, f"#{latest['n']} delivered and opened")
    elif now - latest["sealed_at"] > CANARY_VERIFY_S:
        checks["canary"] = (RED, "canary_unverified")
    else:
        checks["canary"] = (AMBER, "canary_in_flight")
    unconfirmed = int(status.get("payments_unconfirmed") or 0)
    checks["payments"] = (GREEN, "all confirmed") if unconfirmed == 0 else (AMBER, "payments_unconfirmed")
    return checks


def disk_check(data_dir: Path, reserve_min: int, statvfs=os.statvfs) -> tuple[str, str]:
    st = statvfs(data_dir)
    total, avail = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    reserve = max(reserve_min, total // 10)
    if avail < reserve + 2 * GIB:
        return RED, "disk_low"
    if avail < reserve + 5 * GIB:
        return AMBER, "disk_tight"
    return GREEN, f"{(avail - reserve) // GIB} GiB above the reserve"


def attention(conn: sqlite3.Connection) -> list[str]:
    reasons = [f"budget.{key.replace(':', '.')}.{level}" for key, level in
               sorted(((meta(conn, "alerts", {}) or {}).get("budgets") or {}).items())]
    if conn.execute("SELECT COUNT(*) FROM abuse_reports WHERE state = 'new'").fetchone()[0]:
        reasons.append("abuse.new_reports")
    return reasons


def phase(now: int, mainnet_date: str) -> str:
    start = datetime.datetime.fromisoformat(mainnet_date).replace(tzinfo=datetime.UTC).timestamp()
    return "mainnet" if now >= start else "pre"


def evaluate(cfg: dict, conn: sqlite3.Connection | None, now: int, probes: dict) -> dict:
    origin = cfg["public_origin"]
    checks = {"https": probes["https"](origin), "api": probes["api"](origin)}
    if conn is None:
        checks["database"] = (RED, "database_unreadable")
        reasons = []
    else:
        checks |= chain_checks(conn, now)
        reasons = attention(conn)
    checks["disk"] = probes["disk"](Path(cfg.get("data_dir", "/srv/mutis/data")),
                                    cfg.get("limits", {}).get("reserve_min_bytes", 10 * GIB))
    states = [state for state, _ in checks.values()]
    overall = RED if RED in states else AMBER if AMBER in states else GREEN
    return {"checked_at": now, "overall": overall, "attention": bool(reasons), "reasons": reasons,
            "phase": phase(now, cfg.get("ootle", {}).get("mainnet_date", "2026-11-11")),
            "checks": {name: {"state": s, "detail": d} for name, (s, d) in sorted(checks.items())}}


def public_subset(report: dict) -> dict:
    return {"updated_at": report["checked_at"], "overall": report["overall"], "attention": report["attention"],
            "reasons": report["reasons"], "phase": report["phase"],
            "checks": {name: c["state"] for name, c in report["checks"].items()}}


def write_json(path: Path, doc: dict, mode: int) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def main() -> int:
    os.umask(0o007)   # SQLite's -wal/-shm files must stay writable for the other users of group mutis
    with open(os.environ.get("MUTIS_CONFIG", "/etc/mutis/mutis.toml"), "rb") as f:
        cfg = tomllib.load(f)
    data = Path(cfg.get("data_dir", "/srv/mutis/data"))
    try:
        conn = sqlite3.connect(f"file:{data / 'db' / 'mutis.sqlite3'}?mode=ro", uri=True, timeout=10)
        conn.execute("SELECT 1 FROM meta LIMIT 1")
    except sqlite3.Error:
        conn = None
    report = evaluate(cfg, conn, int(time.time()), {"https": https_ok, "api": api_ok, "disk": disk_check})
    write_json(data / "health.json", report, 0o640)
    write_json(data.parent / "status" / "status.json", public_subset(report), 0o644)
    for name, check in report["checks"].items():
        if check["state"] == RED:
            print(f"<2>health: red: {check['detail'].split(' ')[0]}", file=sys.stderr)
    print(f"health: {report['overall']}{' (attention)' if report['attention'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
