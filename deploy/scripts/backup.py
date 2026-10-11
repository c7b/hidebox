#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Backups (spec §8.3) and the restore drill (D-06). Python standard library only.

  backup.py db              as mutis: data/backup/mutis-YYYYMMDD.sqlite3
  backup.py wallet          as drive: walletd's database and the receiver/robot keys into
                            /home/drive/wallet/backup/ (0600)
  backup.py restore-drill   as mutis or drive: restores the newest backup of the database(s) this user
                            can read into a temporary directory and checks it (integrity, tables, rows)

Every copy is deleted once it is KEEP_DAYS old (the db_backup_days that /privacy and /how publish),
mutis-admin migrate's pre-migrate copies included, and so are side files (-wal, -shm, .part) that
nothing holds open. Blobs are never backed up: mutis isn't a backup service, and a file that made its
exit must not live on in our backups. Each copy uses SQLite's online backup API, so a live database
is copied consistently, and is then a single self-contained file (rollback journal, no -wal).
One installed copy of this script (/usr/local/lib/mutis/backup.py) serves both backup units.
"""
import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import tomllib
from pathlib import Path

KEEP_DAYS = 7          # server/mutis/cleanup.py DB_BACKUP_DAYS; deploy/tests checks they agree
SLACK_S = 12 * 3600    # the daily run that falls on day 7 removes the day-0 copy despite timer jitter
WALLET_DB = Path("/home/drive/wallet/esmeralda/data/wallet.sqlite")
WALLET_BACKUPS = Path("/home/drive/wallet/backup")
KEYS = Path("/home/drive/mutis")


def data_dir() -> Path:
    with open(os.environ.get("MUTIS_CONFIG", "/etc/mutis/mutis.toml"), "rb") as f:
        return Path(tomllib.load(f).get("data_dir", "/srv/mutis/data"))


def today() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%d")


def copy_sqlite(src: Path, dst: Path, immutable: bool = False) -> None:
    """`immutable` for a source nothing writes (a backup), so opening it leaves no -shm behind."""
    tmp = dst.with_name(dst.name + ".part")
    tmp.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{src}?{'immutable=1' if immutable else 'mode=ro'}", uri=True)
    target = sqlite3.connect(tmp)
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
    finally:
        target.close()
        source.close()
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)


def copy_file(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".part")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out, open(src, "rb") as f:
        shutil.copyfileobj(f, out)
    os.replace(tmp, dst)


def prune(folder: Path, pattern: str, now: float) -> None:
    """Delete copies matching `pattern` that are KEEP_DAYS old, and any beyond the newest KEEP_DAYS."""
    copies = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)
    for i, old in enumerate(copies):
        if now - old.stat().st_mtime >= KEEP_DAYS * 86400 - SLACK_S or i < len(copies) - KEEP_DAYS:
            old.unlink()


def remove_side_files(folder: Path) -> None:
    """SQLite -wal/-shm files and unfinished .part copies: nothing keeps a backup open between runs."""
    for side in folder.iterdir():
        if side.name.endswith(("-wal", "-shm", ".part")):
            side.unlink()


def backup_db(now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    data = data_dir()
    out = data / "backup"
    remove_side_files(out)
    target = out / f"mutis-{today()}.sqlite3"
    copy_sqlite(data / "db" / "mutis.sqlite3", target)
    for migrated in out.glob("pre-migrate-*.sqlite3"):   # mutis-admin migrate's own copies
        os.chmod(migrated, 0o600)
    prune(out, "mutis-????????.sqlite3", now)
    prune(out, "pre-migrate-*.sqlite3", now)
    return [target.name]


def backup_wallet(now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    remove_side_files(WALLET_BACKUPS)
    done = []
    target = WALLET_BACKUPS / f"wallet-{today()}.sqlite"
    copy_sqlite(WALLET_DB, target)
    prune(WALLET_BACKUPS, "wallet-????????.sqlite", now)
    done.append(target.name)
    for key in sorted(KEYS.glob("*.json")):
        target = WALLET_BACKUPS / f"{key.stem}-{today()}.json"
        copy_file(key, target)
        prune(WALLET_BACKUPS, f"{key.stem}-????????.json", now)
        done.append(target.name)
    return done


def check_copy(path: Path) -> dict:
    """Restore one backup into a scratch directory and prove it opens and is whole."""
    with tempfile.TemporaryDirectory(prefix="mutis-restore-") as scratch:
        restored = Path(scratch) / path.name
        copy_sqlite(path, restored, immutable=True)
        db = sqlite3.connect(restored)
        try:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            rows = {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        finally:
            db.close()
    return {"backup": path.name, "integrity": integrity, "tables": len(tables), "rows": sum(rows.values())}


def restore_drill() -> list[dict]:
    results = []
    for folder, prefix, suffix in ((None, "mutis", ".sqlite3"), (WALLET_BACKUPS, "wallet", ".sqlite")):
        try:
            folder = folder or data_dir() / "backup"
            copies = sorted(folder.glob(f"{prefix}-????????{suffix}"))
        except OSError:
            continue
        if copies:
            results.append(check_copy(copies[-1]) | {"copies": len(copies)})
    return results


def main() -> int:
    os.umask(0o007)   # SQLite's -wal/-shm files must stay writable for the other users of group mutis
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("what", choices=("db", "wallet", "restore-drill"))
    args = p.parse_args()
    if args.what == "restore-drill":
        results = restore_drill()
        print(json.dumps(results, indent=1))
        ok = bool(results) and all(r["integrity"] == "ok" and r["tables"] > 0 for r in results)
        print(f"restore-drill: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    names = backup_db() if args.what == "db" else backup_wallet()
    print(f"backup {args.what}: wrote {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
