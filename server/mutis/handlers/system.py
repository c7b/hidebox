# SPDX-License-Identifier: MIT
"""GET /health, GET /config, POST /pow (spec §6.3 System, brand patch P-3)."""
import sqlite3

from .. import cleanup, items, payments, pow as pow_mod, quota
from ..auth import SESSION_TTL_S
from ..http_util import get_enum, get_int, json_response
from .invoices import DEMO_PAY_PER_DAY
from .shares import KDF_MAX_ITER, KDF_MIN_ITER, PW_DELAY_START_S, PW_LOCK_AFTER, PW_PERMANENT_AFTER
from .uploads import ANON_LARGE_PER_HOUR, ANON_SMALL_PER_HOUR


def health(ctx):
    try:
        ctx.db.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
    except sqlite3.Error:
        return json_response(503, {"ok": False})
    return json_response(200, {"ok": True, "version": ctx.app.git_sha, "time": ctx.now})


def limits_block() -> dict:
    def pick(cls: str, keys: tuple) -> dict:
        return {k: quota.CLASSES[cls][k] for k in keys}

    anon = pick("anon", ("max_file_bytes", "small_lane_max_bytes", "max_expiry_s", "default_expiry_s", "max_views"))
    # Sends always leave from a locker; a first-day locker (made silently) gets probation's count.
    anon.update({"courier_per_day": quota.CLASSES["probation"]["sends_per_day"],
                 "uploads_per_hour": ANON_SMALL_PER_HOUR, "large_uploads_per_hour": ANON_LARGE_PER_HOUR})
    return {
        "anon": anon,
        "drop": pick("drop", ("max_file_bytes", "expiry_s", "views")),
        "probation": pick("probation", ("max_file_bytes", "quota_bytes", "max_expiry_s", "default_expiry_s",
                                        "max_views", "sends_per_day")),
        "locker": pick("locker", ("max_file_bytes", "max_expiry_s", "default_expiry_s", "max_views", "sends_per_day")),
        "paid": pick("paid", ("max_file_bytes", "max_expiry_s", "default_expiry_s", "max_views", "sends_per_day")),
        "demo_pay_per_day": DEMO_PAY_PER_DAY,
    }


def build_config(ctx) -> dict:
    cfg, ootle = ctx.cfg, ctx.cfg["ootle"]
    start = ctx.db.execute("SELECT COALESCE(MIN(seq), 1) FROM chain_utxos").fetchone()[0]
    e2e = {"e2e_expiry_s": cfg["e2e_expiry_s"]} if cfg["e2e_expiry_s"] else {}     # spec §17.1, never in production
    return {
        "origin": cfg.origin, "memo_origins": list(cfg["memo_origins"]),
        "network": cfg["network"], "network_byte": 38, "testnet": True,
        "send_mode": cfg["gates"]["send_mode"], "amount_proof": cfg["gates"]["amount_proof"],
        "chunk_size": quota.CHUNK, "text_max_chars": quota.TEXT_MAX_CHARS, "text_max_bytes": quota.TEXT_MAX_BYTES,
        "inline_max_stored": quota.INLINE_MAX_STORED,
        "limits": limits_block(),
        "kdf": {"alg": "PBKDF2-SHA256", "min_iter": KDF_MIN_ITER, "max_iter": KDF_MAX_ITER},
        "pricing": {"unit": "tTARI", "packs": [
            {"id": pid, "bytes": p["bytes"], "days": p["days"], "price_ut": str(p["price_ut"])}
            for pid, p in quota.PACKS.items()]},
        "features": ctx.features(),
        "courier": {"amount_ut": str(ootle["courier_amount_ut"]), "max_fee_ut": str(ootle["max_fee_transfer_ut"]),
                    "jitter_s": list(ootle["jitter_s"])},
        "sponsor_grant_ut": str(ootle["sponsor_grant_ut"]),
        "ootle": {"mirror_start_seq": start, "indexers": list(ootle["indexers"]),
                  "wasm_version": ootle["wasm_version"], "mainnet_date": ootle["mainnet_date"]},
        "security_drop": cfg["security_drop_url"] or None,
        "repo_url": cfg["repo_url"],
        "seal_log": {"checkpoint_interval_s": cfg["seal_log"]["checkpoint_interval_s"],
                     "component": ootle["seallog_component"] or None},
        "retention": {"ticket_s": items.TICKET_S, "tombstone_days": cleanup.TOMBSTONE_DAYS,
                      "db_backup_days": cleanup.DB_BACKUP_DAYS, "inactive_days": cleanup.INACTIVE_DAYS,
                      "lapse_grace_days": cleanup.LAPSE_GRACE_DAYS, "session_s": SESSION_TTL_S},
        "quota": {"floor_bytes": quota.QUOTA_FLOOR, "ceiling_bytes": quota.QUOTA_CEILING,
                  "overcommit": quota.OVERCOMMIT, "active_days": quota.ACTIVE_DAYS},
        "password": {"lock_after": PW_LOCK_AFTER, "lock_s": PW_DELAY_START_S, "permanent_after": PW_PERMANENT_AFTER,
                     "min_chars_link_password": 4, "min_chars_password_only": 10},
        "invoices": {"underpaid_grace_days": payments.UNDERPAID_GRACE_DAYS, "expires_s": payments.INVOICE_TTL_S},
        "hosting": {"snapshots": cfg["hosting"]["snapshots"]},
        "onion": cfg["onion"] or None,
        **e2e,
    }


def config(ctx):
    return json_response(200, ctx.app.cached("config", 60, lambda: build_config(ctx)), "public, max-age=60")


def pow(ctx):
    body = ctx.req.json()
    purpose = get_enum(body, "purpose", tuple(pow_mod.PURPOSES))
    min_difficulty = get_int(body, "min_difficulty", 0, pow_mod.MAX_BITS, optional=True) or 0
    return json_response(200, ctx.app.pow.issue(purpose, ctx.ip64, ctx.now, min_difficulty))

