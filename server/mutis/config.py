# SPDX-License-Identifier: MIT
"""Configuration: /etc/mutis/mutis.toml (spec §15.3) merged over these defaults.

Unknown keys are an error, so a typo in the TOML stops the service instead of being ignored.
"""
import copy
import ipaddress
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import network as networks
from . import s3

PINNED_WASM_SHA256 = "072f77c11de0ab34e0cae1cc9ffc3f732995fbed3ffb03ddfdb7027b1164c3ae"   # spec §3.3 step 7

DEFAULTS: dict = {
    "public_origin": "https://srv2052606.hstgr.cloud",
    "memo_origins": ["https://srv2052606.hstgr.cloud"],   # not mutis.sh: that domain is unregistered
    "listen": "127.0.0.1:8787",
    "data_dir": "/srv/mutis/data",
    "secret_key": "/etc/mutis/secret.key",
    "network": "esmeralda",         # or "mainnet" (server/mutis/network.py): real TARI, no test money
    # A rehearsal of a mainnet deployment on the testnet: the site and the app say so on every page.
    "staging": False,
    # The testnet deployment (https://host) a staging rehearsal names as the live service, and a mainnet deployment as
    # the contest entry (/judges). Needed by both; production leaves it empty.
    "testnet_origin": "",
    # The deployment that served this host before it moved here (https://host): the links and drives made on this host
    # before the move belong to it (docs/cutover.md). Caddy sends the frozen set of its link ids there, and the app hands
    # a drive saved in the browser over to it. Empty unless this host took over another deployment's.
    "legacy_origin": "",
    # Hosts that answer 308 to public_origin with the same path and query: a host this deployment served before
    # (docs/cutover.md). Read by the deploy scripts only (deploy/scripts/instance.py renders them).
    "redirect_hosts": [],
    "single_uid": False,            # read by the deploy scripts (spec D4); the server behaves the same
    "security_drop_url": "",
    "repo_url": "https://github.com/c7b/hidebox",
    "onion": "",
    "e2e_expiry_s": 0,              # > 0 only on a deployment the E2E suite runs against (spec §17.1)
    # A share id the release burns at least a checkpoint before the tag (deploy/scripts/demo-gone.py):
    # /judges, track one, step 4 opens it, so a judge sees a goodbye already on the chain (14 §9).
    "judge_demo_gone": "",
    # The built site the API reads app/shop.html from, to fill a public shop's page (shop_page.py). Empty: the dist/
    # beside the server code that runs (a release's own, /srv/mutis[-<name>]/app/current/dist).
    "site_dir": "",
    "gates": {"send_mode": "relay", "amount_proof": "wallet", "key_bundle": False},
    # The drive (16-drive-design §15): folders, Trash and Delete it after; pay to open; a drive's shop of pay links
    # (docs/shop.md, it needs pay_to_open too); withdrawing earnings (docs/withdraw.md, it needs pay_to_open too); a
    # sale that opens without the seller's drive, checked by our payment checker with the sales view key
    # (docs/mvp-november.md §2, away_release: pay_to_open in sidecar mode); the market of public shops (docs/market.md,
    # it needs shop and pay_to_open). Off until the routes switch over; the tests
    # turn them on.
    "features": {"drops": True, "relay_send": True, "direct_send": False, "demo_pay": True, "sponsor": False,
                 "decoys": True, "kept": True, "seallog": False, "folders": False, "pay_to_open": False,
                 "packs": True, "judge_passes": True, "shop": False, "withdraw": False, "away_release": False,
                 "market": False},
    # capacity_bytes: 0 measures the pool on the disk under data_dir; with storage.backend = "s3" it is the space we
    # rent there (docs/storage.md). disk_cap_bytes: with the disk, the most of it the pool may use (0: all of it), for a
    # deployment that shares its disk with another. The free share each drive gets moves between quota_floor_bytes and
    # quota_ceiling_bytes with the pool and the drives using it (quota.compute).
    "limits": {"reserve_min_bytes": 10 << 30, "small_lane_bytes": 1 << 30, "drop_lane_bytes": 2 << 30,
               "anon_lane_max_bytes": 6 << 30, "capacity_bytes": 0, "disk_cap_bytes": 0, "quota_floor_bytes": 256 << 20,
               "quota_ceiling_bytes": 5 << 30},
    # Where ciphertext lives (docs/storage.md): "local", the disk under data_dir; or "s3", an S3-compatible store (its
    # name, `provider`, is shown on /fine-print as a third party),
    # with our disk for uploads in flight and for blobs up to keep_local_max_bytes. s3_key_file holds the access key id
    # and the secret on two lines (root:mutis 0640). staging_free_min_bytes: an upload that would leave less free on
    # our disk waits (503 uploads_frozen) until the offloader catches up.
    "storage": {"backend": "local", "provider": "", "s3_endpoint": "", "s3_region": "", "s3_bucket": "", "s3_prefix": "blobs/",
                "s3_addressing": "path", "s3_key_file": "/etc/mutis/s3.key", "keep_local_max_bytes": 256 << 10,
                "staging_free_min_bytes": 4 << 30},
    # Space packs (spec §9.6, against griefing; server/mutis/packs.py). Paid space is capped at
    # paid_cap_fraction of the pool; judge_fraction of that cap is a slice only purchases made with a judge
    # pass draw from (they spill into the public slice when it is used up). A drive holds one pack at a
    # time and may buy the same pack again in its last renew_days days (days stack, bytes don't). Sales a
    # UTC day: per network (in memory) and for the whole deployment (counted from the invoices).
    # catalog: the packs on sale, [{id, bytes, days, price_ut}, …] (docs/pricing.md); empty sells the built-in two
    # (quota.PACKS). An invoice keeps the terms it was made with, so a change here never alters one already open.
    "packs": {"paid_cap_fraction": 0.40, "judge_fraction": 0.30, "renew_days": 3, "per_network_day": 1,
              "judge_per_network_day": 2, "public_per_day": 3, "judge_per_day": 10, "catalog": []},
    # Free space brakes, a UTC day each, in memory (a restart forgets them): new drives and drive upload
    # bytes per IPv6 /64 or IPv4 address, and per /48 or IPv4 /24. A judge pass skips the drive brakes and
    # has its own upload allowance; drives with an active pack are bounded by their pack instead.
    # exempt_addresses: the server's own addresses (its end-to-end tests run there), addresses or CIDR.
    "brakes": {"drives_per_network_day": 5, "drives_per_wide_network_day": 20,
               "upload_bytes_per_network_day": 2 << 30, "upload_bytes_per_wide_network_day": 6 << 30,
               "judge_upload_bytes_per_network_day": 8 << 30, "exempt_addresses": []},
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
        "operator_account": "service",   # G5 failed: walletd 0.45 signs manifests with service's key
        "receiver_keys": "/home/drive/mutis/receiver.json",
        # Where pack payments go (docs/currencies.md §1): empty, our receiving address (receiver_keys, on this server);
        # or the owner's own Ootle address, made on his own device, with only its view secret here (revenue_view_key: a
        # file of 64 hex characters, root:drive 0640). Then the chain worker sees what arrives and checks it is the
        # owner's to spend, the watch-only check, and this server never holds a key that spends our revenue.
        "revenue_address": "",
        "revenue_view_key": "",
        "robot_keys": "/home/drive/mutis/robot.json",
        "indexers": ["https://ootle-indexer-b.tari.com", "https://ootle-indexer-a.tari.com"],
        "mirror_start_epoch": 0,
        "max_fee_transfer_ut": 30000,
        "courier_amount_ut": 1000,
        "jitter_s": [5, 45],
        "decoy_mean_gap_s": 900,
        "sponsor_grant_ut": 1_000_000,
        "sponsor_min_ut": 200_000_000,   # the healthcheck's sponsor balance turns amber below this
        "seallog_component": "",
        "wasm_version": "0.53.2",
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
    "seal_log": {"checkpoint_interval_s": 900},
}

INLINE_MAX_STORED = 256 << 10       # quota.INLINE_MAX_STORED (test_storage_remote pins them equal)
QUOTA_STEP = 64 << 20               # quota.QUOTA_STEP (the same)
SEAL_MIN_INTERVAL_S = 600            # with seal-now's own gap: at most one SealLog fee every 10 minutes
SHARE_ID = re.compile(r"[A-Za-z0-9_-]{22}")


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
    def net(self) -> networks.Network:
        return networks.get(self.raw["network"])

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
        # Node's permission model resolves symlinks, so a release's `current` link must be resolved here.
        directory = os.path.realpath(sc["dir"])
        return [sc["node"], "--experimental-permission", f"--allow-fs-read={directory}",
                "--disallow-code-generation-from-strings", f"{directory}/sidecar.mjs"]


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
    if raw["network"] not in networks.NETWORKS:
        raise ConfigError(f"network must be one of {', '.join(networks.NETWORKS)}")
    net = networks.get(raw["network"])
    if not net.testnet:
        on = [f for f in networks.TEST_MONEY if raw["features"][f]]
        if on:
            raise ConfigError(f"features {', '.join(on)} must be false on the {net.name} (no test money there)")
        if raw["staging"]:
            raise ConfigError("staging is a rehearsal on the testnet: set it to false on the mainnet")
    testnet = raw["testnet_origin"]
    if testnet and not (testnet.startswith("https://") and re.fullmatch(r"https://[a-z0-9.-]+", testnet)):
        raise ConfigError("testnet_origin must be empty or https://host")
    if (raw["staging"] or not net.testnet) and not testnet:
        raise ConfigError("testnet_origin must name the testnet deployment (https://host) on staging and on the mainnet")
    legacy = raw["legacy_origin"]
    if legacy and not re.fullmatch(r"https://[a-z0-9.-]+", legacy):
        raise ConfigError("legacy_origin must be empty or https://host")
    if legacy and legacy == raw["public_origin"]:
        raise ConfigError("legacy_origin names the deployment that served this host before, never this one")
    hosts = raw["redirect_hosts"]
    if not isinstance(hosts, list) or not all(isinstance(h, str) and re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", h)
                                              for h in hosts) or len(set(hosts)) != len(hosts):
        raise ConfigError("redirect_hosts takes distinct host names")
    if f"https://{raw['public_origin'].removeprefix('https://')}" in (f"https://{h}" for h in hosts):
        raise ConfigError("redirect_hosts can't name public_origin's own host")
    foreign = [u for u in raw["ootle"]["indexers"] if networks.foreign_indexer(net.name, u)]
    if foreign:
        raise ConfigError(f"ootle.indexers lists another network's indexer: {foreign[0]}")
    if not raw["ootle"]["indexers"]:
        raise ConfigError("ootle.indexers must name at least one indexer")
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
    if raw["seal_log"]["checkpoint_interval_s"] < SEAL_MIN_INTERVAL_S:
        raise ConfigError(f"seal_log.checkpoint_interval_s must be at least {SEAL_MIN_INTERVAL_S}")
    if raw["site_dir"] and not raw["site_dir"].startswith("/"):
        raise ConfigError("site_dir must be empty or an absolute path")
    if raw["e2e_expiry_s"] < 0:
        raise ConfigError("e2e_expiry_s must be 0 (off) or a number of seconds")
    revenue = raw["ootle"]["revenue_address"]
    if revenue:
        if not re.fullmatch(rf"{re.escape(net.hrp)}1[a-z0-9]{{60,300}}", revenue):
            raise ConfigError(f"ootle.revenue_address must be an address on the {net.name} ({net.hrp}…), or empty")
        if not raw["ootle"]["revenue_view_key"].startswith("/"):
            raise ConfigError("ootle.revenue_view_key must be the absolute path of its view key file")
    elif raw["ootle"]["revenue_view_key"]:
        raise ConfigError("ootle.revenue_view_key goes with ootle.revenue_address")
    store, limits = raw["storage"], raw["limits"]
    if store["backend"] not in ("local", "s3"):
        raise ConfigError("storage.backend must be local or s3")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .-]{0,39}|", store["provider"]):
        raise ConfigError("storage.provider is the store's name as /fine-print shows it: up to 40 letters, digits, spaces, dots, hyphens")
    if store["backend"] == "s3":
        if limits["capacity_bytes"] <= 0:
            raise ConfigError("limits.capacity_bytes must be the space rented in the store (bytes) with storage.backend = s3")
        try:
            s3.Settings(store["s3_endpoint"], store["s3_region"], store["s3_bucket"], store["s3_prefix"],
                        "CHECKONLY00", "x" * 16, store["s3_addressing"]).check()
        except ValueError as e:
            raise ConfigError(str(e)) from None
        if not store["s3_key_file"].startswith("/"):
            raise ConfigError("storage.s3_key_file must be an absolute path")
    elif limits["capacity_bytes"] != 0:
        raise ConfigError("limits.capacity_bytes is for storage.backend = s3; 0 measures the disk")
    if limits["disk_cap_bytes"] < 0 or (limits["disk_cap_bytes"] and store["backend"] != "local"):
        raise ConfigError("limits.disk_cap_bytes caps the disk (storage.backend = local): 0 or a number of bytes")
    if store["keep_local_max_bytes"] < INLINE_MAX_STORED or store["staging_free_min_bytes"] < 0:
        # A blob that small is read whole on every open (its link's inline ciphertext): it stays on our disk.
        raise ConfigError(f"storage.keep_local_max_bytes must be at least {INLINE_MAX_STORED}, "
                          "and storage.staging_free_min_bytes at least 0")
    if not 0 < limits["quota_floor_bytes"] <= limits["quota_ceiling_bytes"] or limits["quota_floor_bytes"] % QUOTA_STEP \
            or limits["quota_ceiling_bytes"] % QUOTA_STEP:
        # quota.compute rounds the share down to a QUOTA_STEP: a bound off the step would put the share below the floor
        raise ConfigError("limits.quota_floor_bytes and quota_ceiling_bytes are multiples of 64 MiB, the floor above 0 "
                          "and at most the ceiling")
    packs = raw["packs"]
    if not (0 < packs["paid_cap_fraction"] <= 1 and 0 <= packs["judge_fraction"] <= 1):
        raise ConfigError("packs.paid_cap_fraction must be in (0, 1] and packs.judge_fraction in [0, 1]")
    check_catalog(packs["catalog"])
    if min(packs[k] for k in ("renew_days", "per_network_day", "judge_per_network_day", "public_per_day",
                              "judge_per_day")) < 0 or min(v for k, v in raw["brakes"].items() if k != "exempt_addresses") < 0:
        raise ConfigError("packs and brakes take numbers of at least 0")
    for entry in raw["brakes"]["exempt_addresses"]:
        try:
            ipaddress.ip_network(entry, strict=False)
        except (TypeError, ValueError):
            raise ConfigError("brakes.exempt_addresses takes addresses or CIDR networks") from None
    if raw["judge_demo_gone"] and not SHARE_ID.fullmatch(raw["judge_demo_gone"]):
        raise ConfigError("judge_demo_gone must be empty or a share id (22 base64url characters)")


PACK_ID = re.compile(r"[a-z][a-z0-9]{1,7}")
CATALOG_MAX = 6
PRICE_MAX_UT = 10 ** 15                 # a billion TARI: past any price, still exact as a JSON number's string


def check_catalog(catalog: list) -> None:
    """`packs.catalog`: at most CATALOG_MAX packs, each {id, bytes, days, price_ut} with a short lower-case id (the
    invoices name it), at least 1 MiB, 1 to 366 days and a price above 0; ids unique."""
    if len(catalog) > CATALOG_MAX:
        raise ConfigError(f"packs.catalog takes at most {CATALOG_MAX} packs")
    seen = set()
    for entry in catalog:
        if not isinstance(entry, dict) or set(entry) != {"id", "bytes", "days", "price_ut"}:
            raise ConfigError("each packs.catalog entry is {id, bytes, days, price_ut}")
        if not isinstance(entry["id"], str) or not PACK_ID.fullmatch(entry["id"]) or entry["id"] in seen:
            raise ConfigError("a packs.catalog id is 2 to 8 lower-case letters and digits, starting with a letter, once")
        if any(type(entry[k]) is not int for k in ("bytes", "days", "price_ut")) or not (1 << 20) <= entry["bytes"] <= (1 << 50) \
                or not 1 <= entry["days"] <= 366 or not 0 < entry["price_ut"] <= PRICE_MAX_UT:
            raise ConfigError("a packs.catalog pack takes bytes from 1 MiB to 1 PiB, days 1 to 366 and price_ut > 0")
        seen.add(entry["id"])


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
