# SPDX-License-Identifier: MIT
"""Configuration: /etc/mutis/mutis.toml (spec §15.3) merged over these defaults.

Unknown keys are an error, so a typo in the TOML stops the service instead of being ignored.
"""
import copy
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PINNED_WASM_SHA256 = "57de0088e9b96ecdd47daad41f1c48fcfbf1773358244a4663c1f40766d6d4df"   # spec §3.3 step 7

DEFAULTS: dict = {
    "public_origin": "https://srv2052606.hstgr.cloud",
    "memo_origins": ["https://srv2052606.hstgr.cloud", "https://mutis.sh"],
    "listen": "127.0.0.1:8787",
    "data_dir": "/srv/mutis/data",
    "secret_key": "/etc/mutis/secret.key",
    "network": "esmeralda",
    "single_uid": False,            # read by the deploy scripts (spec D4); the server behaves the same
    "security_drop_url": "",
    "repo_url": "https://github.com/c7b/mutis",
    "onion": "",
    "gates": {"send_mode": "relay", "amount_proof": "wallet", "key_bundle": False},
    "features": {"drops": True, "relay_send": True, "direct_send": False, "demo_pay": True, "sponsor": False,
                 "decoys": True, "kept": True, "seallog": False},
    "limits": {"reserve_min_bytes": 10 << 30, "small_lane_bytes": 1 << 30, "drop_lane_bytes": 2 << 30,
               "anon_lane_max_bytes": 6 << 30},
    "budgets": {
        "public": {"courier": 1500, "demo_pay_ut": 25_000_000, "sponsor_ut": 100_000_000},
        "reserved": {"courier": 500, "decoy": 120, "demo_pay_ut": 10_000_000, "sponsor_ut": 30_000_000},
        # Canary (24 a day), the daily evidence payment and judge passes (20 passes x 5 uses, P-12).
        "evidence": {"courier": 150, "demo_pay_ut": 10_000_000, "sponsor_ut": 10_000_000},
    },
    "ootle": {
        "walletd_url": "http://127.0.0.1:5100/json_rpc",
        "sponsor_account": "sponsor",
        "service_account": "service",
        "operator_account": "operator",
        "receiver_keys": "/home/drive/mutis/receiver.json",
        "robot_keys": "/home/drive/mutis/robot.json",
        "indexers": ["https://ootle-indexer-b.tari.com", "https://ootle-indexer-a.tari.com"],
        "mirror_start_epoch": 0,
        "max_fee_transfer_ut": 30000,
        "courier_amount_ut": 1000,
        "jitter_s": [5, 45],
        "decoy_mean_gap_s": 900,
        "sponsor_grant_ut": 1_000_000,
        "seallog_component": "",
        "wasm_version": "0.45.0",
        "mainnet_date": "2026-11-11",
    },
    "sidecar": {
        "node": "/usr/bin/node",
        "dir": "/srv/mutis/app/current/sidecar",
        "command": [],               # non-empty replaces the Node command (G4 fallback: the Chromium bridge)
        "expected_wasm_sha256": PINNED_WASM_SHA256,
        "canary_every_s": 3600,
    },
    "hosting": {"snapshots": "weekly"},
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    raw: dict

    def __getitem__(self, key: str):
        return self.raw[key]

    @property
    def origin(self) -> str:
        return self.raw["public_origin"]

    @property
    def data_dir(self) -> Path:
        return Path(self.raw["data_dir"])

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "mutis.sqlite3"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    def sidecar_argv(self) -> list[str]:
        sc = self.raw["sidecar"]
        if sc["command"]:
            return list(sc["command"])
        return [sc["node"], "--experimental-permission", f"--allow-fs-read={sc['dir']}",
                "--disallow-code-generation-from-strings", f"{sc['dir']}/sidecar.mjs"]


def _merge(base: dict, over: dict, path: str) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        where = f"{path}{key}"
        if key not in base:
            raise ConfigError(f"unknown config key: {where}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{where} must be a table")
            out[key] = _merge(base[key], value, where + ".")
        elif type(value) is not type(base[key]):
            raise ConfigError(f"{where} has the wrong type")
        else:
            out[key] = value
    return out


def validate(raw: dict, dev: bool = False) -> None:
    if raw["network"] != "esmeralda":
        raise ConfigError("network must be esmeralda (testnet only)")
    origin = raw["public_origin"]
    if not (origin.startswith("https://") or (dev and origin.startswith("http://127.0.0.1:"))):
        raise ConfigError("public_origin must be https://")
    if origin.endswith("/"):
        raise ConfigError("public_origin must not end with /")
    if origin not in raw["memo_origins"]:
        raise ConfigError("public_origin must be one of memo_origins")
    if raw["gates"]["send_mode"] not in ("direct", "relay"):
        raise ConfigError("gates.send_mode must be direct or relay")
    if raw["gates"]["amount_proof"] not in ("sidecar", "chromium", "wallet"):
        raise ConfigError("gates.amount_proof must be sidecar, chromium or wallet")
    if raw["hosting"]["snapshots"] not in ("weekly", "off"):
        raise ConfigError("hosting.snapshots must be weekly or off")
    lo, hi = raw["ootle"]["jitter_s"]
    if not 0 <= lo <= hi:
        raise ConfigError("ootle.jitter_s must be [low, high]")


def from_dict(over: dict, dev: bool = False) -> Config:
    raw = _merge(DEFAULTS, over, "")
    validate(raw, dev)
    return Config(raw)


def load(path: str | None = None) -> Config:
    path = path or os.environ.get("MUTIS_CONFIG", "/etc/mutis/mutis.toml")
    with open(path, "rb") as f:
        return from_dict(tomllib.load(f))


def read_secret(cfg: Config) -> bytes:
    with open(cfg["secret_key"], "rb") as f:
        key = f.read()
    if len(key) != 32:
        raise ConfigError("secret.key must hold exactly 32 bytes")
    return key
