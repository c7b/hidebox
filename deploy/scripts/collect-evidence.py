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
import contextlib
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import tomllib
from pathlib import Path

STATUS = Path("/srv/mutis/status")
# SealLog components we wrote to before the live one (template NOTES §1.5): the 1.0.0 log, never
# appended to, and the research log, with one test checkpoint. Listed so that a reader who finds
# them on chain knows they are ours and retired; /api/v1/config names the live one.
RETIRED_LOGS = ("component_0ff7e892de37ee65d60e37a5e55cdfe24b11bd9e84cb5af49831e309f6bd22aa",
                "component_32dae273fb4c4c63c77cd1c70ef4e53e07cb56aaa378730fabcd228e45a7e36e")


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
    row = conn.execute("SELECT chain_index, tree_size, tx_id, epoch FROM seal_checkpoints "
                       "WHERE state = 'committed' AND component = ? ORDER BY idx DESC LIMIT 1", (component,)).fetchone()
    # `index` is the log's own checkpoint number, the one a reader finds on chain (null when the
    # worker couldn't read it from the append's event), as in the API's checkpoint objects.
    latest = {"index": row[0], "component": component, "tree_size": row[1], "tx_id": row[2], "epoch": row[3]} \
        if row else None
    return {"component": component, "latest_checkpoint": latest, "retired": list(RETIRED_LOGS)}


def collect(cfg: dict, conn: sqlite3.Connection, robot_file: Path, now: datetime.datetime) -> dict:
    sidecar = (meta(conn, "chain_status", {}) or {}).get("sidecar") or {}
    robot = json.loads(robot_file.read_text())["address"] if robot_file.is_file() else None
    return {
        "network": cfg.get("network", "esmeralda"),
        "ootle_version": cfg.get("ootle", {}).get("wasm_version", "0.46.0"),
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
    """Write `path` in the shared status directory through a new file of a random name, created exclusively,
    its mode set on the open file, then renamed over `path`: a name another service user planted there (a
    symlink to some other file) is never opened or followed (security-audit-1)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


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
        write(archived, doc)
        print(f"evidence: archived {archived.name}")
    print(f"evidence: {len(doc['deliveries'])} deliveries, {len(doc['payments'])} payments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
