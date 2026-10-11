#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Public testnet evidence (spec §15.6), hourly as `drive` (mutis-evidence.timer) and on demand.

  collect-evidence.py              write /srv/mutis/status/evidence.json
  collect-evidence.py --archive    also keep a dated copy, evidence-archive-YYYYMMDD.json (reset playbook)

Only evidence jobs are read: the hourly canary delivery to our own robot locker and the daily
evidence payment to our own receiver (spec §8.4, §10.4). Never a user's job, transaction, invoice or
address, and no count of sends of any kind: with the canaries listed here, a daily decoy count would
let a chain observer subtract its way to the number of real sends, the volume decoys exist to hide.
Every field is something observed: wasm_sha256 is what the running sidecar reported, null before
it has. Python stdlib only.
"""
import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tomllib
from pathlib import Path

STATUS = Path("/srv/mutis/status")


def meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return row[0]


def evidence_jobs(conn: sqlite3.Connection, kind: str, limit: int) -> list[dict]:
    rows = conn.execute("SELECT result, updated_at FROM jobs WHERE evidence = 1 AND kind = ? AND state = 'done' "
                        "ORDER BY updated_at DESC LIMIT ?", (kind, limit)).fetchall()
    out = []
    for result, updated_at in rows:
        doc = json.loads(result or "{}")
        ids = doc.get("utxo_ids") or []
        epochs = [r[0] for r in conn.execute(
            f"SELECT epoch FROM chain_utxos WHERE id IN ({','.join('?' * len(ids))})", ids)] if ids else []
        out.append({"tx_id": doc.get("tx_id"), "epoch": min((e for e in epochs if e is not None), default=None),
                    "at": updated_at})
    return out


def seallog(conn: sqlite3.Connection, cfg: dict) -> dict | None:
    component = cfg.get("ootle", {}).get("seallog_component", "")
    if not (cfg.get("features", {}).get("seallog") and component):
        return None
    row = conn.execute("SELECT tree_size, tx_id, epoch FROM seal_checkpoints WHERE state = 'committed' "
                       "ORDER BY idx DESC LIMIT 1").fetchone()
    latest = {"tree_size": row[0], "tx_id": row[1], "epoch": row[2]} if row else None
    return {"component": component, "latest_checkpoint": latest}


def collect(cfg: dict, conn: sqlite3.Connection, robot_file: Path, now: datetime.datetime) -> dict:
    sidecar = (meta(conn, "chain_status", {}) or {}).get("sidecar") or {}
    robot = json.loads(robot_file.read_text())["address"] if robot_file.is_file() else None
    return {
        "network": cfg.get("network", "esmeralda"),
        "ootle_version": cfg.get("ootle", {}).get("wasm_version", "0.45.0"),
        "wasm_sha256": sidecar.get("wasm_sha256"),
        "receiver_address": meta(conn, "receiver_address"),
        "robot_address": robot,
        "deliveries": evidence_jobs(conn, "courier", 5),
        "payments": evidence_jobs(conn, "demo_pay", 3),
        "seallog": seallog(conn, cfg),
        "archive": sorted(p.name for p in STATUS.glob("evidence-archive-*.json")),
        "updated_at": int(now.timestamp()),
    }


def write(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main() -> int:
    os.umask(0o007)   # SQLite's -wal/-shm files must stay writable for the other users of group mutis
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--archive", action="store_true", help="also write evidence-archive-YYYYMMDD.json")
    args = p.parse_args()
    with open(os.environ.get("MUTIS_CONFIG", "/etc/mutis/mutis.toml"), "rb") as f:
        cfg = tomllib.load(f)
    data = Path(cfg.get("data_dir", "/srv/mutis/data"))
    robot = Path(cfg.get("ootle", {}).get("robot_keys", "/home/drive/mutis/robot.json"))
    conn = sqlite3.connect(f"file:{data / 'db' / 'mutis.sqlite3'}?mode=ro", uri=True, timeout=10)
    now = datetime.datetime.now(datetime.UTC)
    doc = collect(cfg, conn, robot, now)
    write(STATUS / "evidence.json", doc)
    if args.archive:
        archived = STATUS / f"evidence-archive-{now.strftime('%Y%m%d')}.json"
        shutil.copyfile(STATUS / "evidence.json", archived)
        os.chmod(archived, 0o644)
        print(f"evidence: archived {archived.name}")
    print(f"evidence: {len(doc['deliveries'])} deliveries, {len(doc['payments'])} payments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
