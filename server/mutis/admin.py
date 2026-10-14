# SPDX-License-Identifier: MIT
"""mutis-admin (spec §15.7): operator commands. Run with sudo as `mutis` (or `drive` for chain commands)."""
import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path

from . import auth, budgets, codec, config, db, indexer, items, logsafe, packs, quota
from .chain_worker import notarize_manifest
from .storage import Blobs
from .walletd import Walletd

FEATURES = ("drops", "relay_send", "direct_send", "demo_pay", "sponsor", "decoys", "kept", "seallog",
            "folders", "pay_to_open", "packs")


def _backup(cfg: config.Config) -> Path | None:
    """A private copy of a database that a migration is about to change (none when nothing is pending)."""
    if not cfg.db_path.exists() or db.version(cfg.db_path) >= db.SCHEMA_VERSION:
        return None
    target = cfg.data_dir / "backup" / time.strftime("pre-migrate-%Y%m%d-%H%M%S.sqlite3", time.gmtime())
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.touch(mode=0o600, exist_ok=False)          # SQLite fills an empty file; it never widens the mode
    src, dst = sqlite3.connect(cfg.db_path), sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return target


def cmd_migrate(cfg, conn, args) -> None:
    backup = _backup(cfg)
    version = db.migrate(cfg.db_path)
    print(f"schema version {version}" + (f" (backup: {backup})" if backup else ""))


def cmd_takedown(cfg, conn, args) -> None:
    now, blobs = codec.now(), Blobs(cfg.blob_dir)
    with db.tx(conn):
        if args.kind == "drop":
            cur = conn.execute("UPDATE drops SET state = 'removed', ended_day = ? WHERE id = ?", (codec.day(now), args.id))
            found = cur.rowcount == 1
            where = ("drop_id = ?", args.id)
        else:
            if args.kind == "share":
                row = conn.execute("SELECT item_id FROM shares WHERE id = ?", (args.id,)).fetchone()
                item_id = row["item_id"] if row else None
            else:
                item_id = args.id if conn.execute("SELECT 1 FROM items WHERE id = ?", (args.id,)).fetchone() else None
            found = item_id is not None
            if found:
                items.remove(conn, blobs, item_id, now)
            where = ("item_id = ? OR share_id = ?", item_id or args.id, args.id)
        if found:
            conn.execute(f"UPDATE abuse_reports SET state = 'actioned', action_note = ? WHERE {where[0]}",
                         (args.note or "takedown", *where[1:]))
    print("removed" if found else "not found")
    if not found:
        sys.exit(1)


def cmd_release_pack(cfg, conn, args) -> None:
    """Ends a locker's pack now, for the lockers an end-to-end run buys packs with: paid space is capped
    (packs.paid_cap_fraction) and a test pack would hold its share for 30 days. The lapse policy of
    spec §9.6 then runs as for a pack that ran out."""
    now = codec.now()
    with db.tx(conn):
        released = conn.execute("UPDATE identities SET paid_bytes = 0, paid_until = ?, paid_pack = NULL, paid_judge = 0 "
                                "WHERE id = ? AND paid_until > ?", (now, args.id, now)).rowcount == 1
    print("released" if released else "no active pack")
    if not released:
        sys.exit(1)


def cmd_packs(cfg, conn, args) -> None:
    """Paid space by slice and today's sales (sixth pass): read-only, no drive and no network."""
    now = codec.now()
    pool = quota.measure(conn, os.statvfs, cfg.data_dir, cfg["limits"], now)
    s = packs.slices(conn, pool, cfg["packs"], now)
    gib = quota.GiB
    print(f"pool {pool.pool / gib:.1f} GiB; paid cap {s.cap / gib:.1f} GiB "
          f"({cfg['packs']['paid_cap_fraction']:.0%}); features.packs {'on' if _features(cfg, conn)['packs'] else 'off'}")
    print(f"public  {s.public_taken / gib:6.1f} / {s.public_cap / gib:.1f} GiB (open invoices {s.public_open / gib:.1f}, "
          f"judges' overflow {s.judge_spill / gib:.1f}); sold today {packs.sold_today(conn, now, False)} / "
          f"{cfg['packs']['public_per_day']}")
    print(f"judges  {(s.judge_active + s.judge_open) / gib:6.1f} / {s.judge_cap / gib:.1f} GiB; sold today "
          f"{packs.sold_today(conn, now, True)} / {cfg['packs']['judge_per_day']}")


def _features(cfg, conn) -> dict:
    return {**cfg["features"], **{k: v for k, v in db.get_meta_json(conn, "features", {}).items() if k in cfg["features"]}}


def cmd_reports(cfg, conn, args) -> None:
    sql = "SELECT * FROM abuse_reports" + (" WHERE state = 'new'" if args.new else "") + " ORDER BY created_at"
    for r in conn.execute(sql):
        target = r["share_id"] and f"share {r['share_id']}" or r["drop_id"] and f"drop {r['drop_id']}" or "-"
        print(f"{r['id']}  {time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['created_at']))}  {r['state']:8}  "
              f"{r['category']:10}  {target}  item={r['item_id'] or '-'}  key={'yes' if r['included_key'] else 'no'}")
        print("    " + r["details"].replace("\n", "\n    "))
        if r["contact"]:
            print("    contact: " + r["contact"])


def cmd_freeze(cfg, conn, args) -> None:
    with db.tx(conn):
        db.set_meta(conn, "uploads_frozen", args.scope)
    print(f"uploads_frozen = {args.scope}")


def cmd_feature(cfg, conn, args) -> None:
    with db.tx(conn):
        overrides = db.get_meta_json(conn, "features", {})
        if args.state == "clear":
            overrides.pop(args.name, None)
        else:
            overrides[args.name] = args.state == "on"
        db.set_meta(conn, "features", overrides)
    print(json.dumps({**cfg["features"], **overrides}, sort_keys=True))


def cmd_budget(cfg, conn, args) -> None:
    now = codec.now()
    if args.action == "set":
        if args.kind not in budgets.KINDS or args.slice not in budgets.SLICES or args.value is None:
            sys.exit("usage: budget set <courier|decoy|demo_pay|sponsor> <public|reserved|evidence> <value>")
        with db.tx(conn):
            budgets.set_override(conn, args.kind, args.slice, args.value, now)
        if args.value > budgets.limit(conn, cfg["budgets"], args.kind, args.slice, now):
            print("note: an override can only lower a limit; raise it in mutis.toml and restart the services",
                  file=sys.stderr)
    for row in budgets.table(conn, cfg["budgets"], now):
        print(f"{row['kind']:9} {row['slice']:8} {row['used']:>12} / {row['limit']}")


def cmd_unfreeze_credits(cfg, conn, args) -> None:
    with db.tx(conn):
        db.del_meta(conn, "credit_freeze")
        db.del_meta(conn, "reconcile_mismatch")
    print("credits unfrozen")


def _force(conn, name: str) -> None:
    with db.tx(conn):
        forced = db.get_meta_json(conn, "force", {})
        forced[name] = True
        db.set_meta(conn, "force", forced)
    print(f"requested: {name} (the chain worker runs it on its next tick)")


def cmd_judge_pass(cfg, conn, args) -> None:
    now = codec.now()
    with db.tx(conn):
        for _ in range(args.count):
            code = auth.new_judge_code()
            conn.execute("INSERT INTO judge_passes(code_hash, uses_left, created_at, pow_skips_left) "
                         "VALUES (?, ?, ?, ?)", (auth.judge_hash(code), args.uses, now, args.pow_skips))
            print(code)


def _sanitize(obj, names: dict):
    """Replace keys, addresses and ids in a walletd response with stable placeholders."""
    if isinstance(obj, dict):
        return {k: _sanitize(v, names) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v, names) for v in obj]
    if isinstance(obj, str) and (re.fullmatch(r"[0-9a-f]{32,}", obj) or obj.startswith(("otl_", "component_", "utxo_"))
                                 or obj.startswith("eyJ")):
        return names.setdefault(obj, f"<redacted-{len(names) + 1}>")
    return obj


def cmd_walletd_fixture(cfg, conn, args) -> None:
    result = Walletd(cfg["ootle"]["walletd_url"]).call(args.method, json.loads(args.params))
    print(json.dumps(_sanitize(result, {}), indent=1, sort_keys=True))


def cmd_notarize(cfg, conn, args) -> None:
    """Brand patch P-9: timestamp a release manifest hash on SealLog from the operator account."""
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256) or not cfg["ootle"]["seallog_component"]:
        sys.exit("need a 64-hex sha256 and ootle.seallog_component in the config")
    w = Walletd(cfg["ootle"]["walletd_url"])
    operator = w.account(cfg["ootle"]["operator_account"])["account"]["component_address"]
    tx_id = w.submit_manifest(notarize_manifest(args.sha256),
                              {"account": operator, "log": cfg["ootle"]["seallog_component"]}, 1_000_000)
    outcome = w.wait_result(tx_id, 120)
    print(json.dumps({"tx_id": tx_id, "committed": outcome["committed"]}))


def cmd_e2e_forge_payment(cfg, conn, args) -> None:
    """E-14 on staging: a proven-looking payment for a UTXO that doesn't exist. It must never be credited."""
    invoice = conn.execute("SELECT price_ut FROM invoices WHERE id = ?", (args.invoice_id,)).fetchone()
    if invoice is None:
        sys.exit("no such invoice")
    utxo_id = indexer.utxo_id(secrets.token_hex(32))
    with db.tx(conn):
        conn.execute("INSERT INTO payments(utxo_id, invoice_id, value_ut, seen_at, proven, status) "
                     "VALUES (?, ?, ?, ?, 1, 'pending_check')", (utxo_id, args.invoice_id, invoice["price_ut"],
                                                                  codec.now()))
    print(utxo_id)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mutis-admin")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate, needs_db=False)
    sub.add_parser("check-config").set_defaults(fn=lambda cfg, conn, args: print("ok"), needs_db=False)
    t = sub.add_parser("takedown", usage="mutis-admin takedown {share,item,drop} [--note NOTE] -- id")
    t.add_argument("kind", choices=("share", "item", "drop"))
    t.add_argument("id", help="put it after `--`: a base64url id may start with '-'")
    t.add_argument("--note")
    t.set_defaults(fn=cmd_takedown)
    rp = sub.add_parser("release-pack", usage="mutis-admin release-pack -- identity_id")
    rp.add_argument("id", help="put it after `--`: a base64url id may start with '-'")
    rp.set_defaults(fn=cmd_release_pack)
    sub.add_parser("packs").set_defaults(fn=cmd_packs)
    r = sub.add_parser("reports")
    r.add_argument("--new", action="store_true")
    r.set_defaults(fn=cmd_reports)
    f = sub.add_parser("freeze")
    f.add_argument("scope", choices=("all", "free", "none"))
    f.set_defaults(fn=cmd_freeze)
    ft = sub.add_parser("feature")
    ft.add_argument("name", choices=FEATURES)
    ft.add_argument("state", choices=("on", "off", "clear"))
    ft.set_defaults(fn=cmd_feature)
    b = sub.add_parser("budget")
    b.add_argument("action", choices=("set", "show"))
    b.add_argument("kind", nargs="?")
    b.add_argument("slice", nargs="?")
    b.add_argument("value", nargs="?", type=int)
    b.set_defaults(fn=cmd_budget)
    sub.add_parser("unfreeze-credits").set_defaults(fn=cmd_unfreeze_credits)
    for name, flag in (("canary-now", "canary"), ("evidence-pay-now", "evidence_pay"), ("seal-now", "seal")):
        sub.add_parser(name).set_defaults(fn=lambda cfg, conn, args, flag=flag: _force(conn, flag))
    j = sub.add_parser("judge-pass")
    j.add_argument("action", choices=("new",))
    j.add_argument("--uses", type=int, default=5, help="budgeted sends (courier, demo-pay, sponsor)")
    j.add_argument("--pow-skips", type=int, default=100, help=f"proofs of work it stands in for "
                                                               f"(valid {auth.JUDGE_PASS_DAYS} days)")
    j.add_argument("--count", type=int, default=1)
    j.set_defaults(fn=cmd_judge_pass)
    w = sub.add_parser("walletd-fixture")
    w.add_argument("method")
    w.add_argument("params", nargs="?", default="{}")
    w.set_defaults(fn=cmd_walletd_fixture, needs_db=False)
    e = sub.add_parser("e2e-forge-payment", help="staging only: E-14 payment forgery")
    e.add_argument("invoice_id")
    e.set_defaults(fn=cmd_e2e_forge_payment)
    n = sub.add_parser("notarize")
    n.add_argument("sha256")
    n.set_defaults(fn=cmd_notarize, needs_db=False)
    return p


def main(argv: list[str] | None = None) -> None:
    logsafe.setup()
    args = parser().parse_args(argv)
    cfg = config.load(args.config)
    if not getattr(args, "needs_db", True):
        args.fn(cfg, None, args)
        return
    conn = db.connect(cfg.db_path)
    try:
        args.fn(cfg, conn, args)
    finally:
        conn.close()
