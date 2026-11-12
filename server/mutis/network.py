# SPDX-License-Identifier: MIT
"""The Ootle networks a deployment can run on (mutis.toml `network`), and what changes with each.

Esmeralda is the testnet and the default. The mainnet moves real TARI, so a deployment there runs without
anything that hands out test money or skips our limits: the demo payment, sponsor grants and judge passes
(`TEST_MONEY`), whatever the TOML or `mutis-admin feature` say. web/app/lib/network.js holds the same values
for the browser and the sidecar.

Values: tari-ootle v0.50.0 crates/ootle_network (the network byte, equal to the L1's), crates/ootle_address
hrp.rs (the address prefix), tari_ootle_app_utilities genesis_resources.rs (the coin's symbol) and
config_presets/e_wallet_daemon.toml (the mainnet indexers).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    name: str           # mutis.toml and /config: "esmeralda" | "mainnet"
    label: str          # for people: "Esmeralda", "Mainnet"
    byte: int           # the network byte inside transactions, addresses and the stealth derivation
    hrp: str            # the bech32m prefix of an Ootle address, separator excluded
    coin: str           # the symbol of the native coin
    testnet: bool
    walletd: str        # tari_ootle_walletd --network
    indexers: tuple[str, ...]   # the public Tari-run indexers (the browser's CSP and the defaults)


NETWORKS = {
    "esmeralda": Network("esmeralda", "Esmeralda", 0x26, "otl_esm_", "tTARI", True, "esme",
                         ("https://ootle-indexer-b.tari.com", "https://ootle-indexer-a.tari.com")),
    "mainnet": Network("mainnet", "Mainnet", 0x00, "otl_", "TARI", False, "mainnet",
                       ("https://indexer-a.ootle.tari.com", "https://indexer-b.ootle.tari.com")),
}
DEFAULT = "esmeralda"

# Features that only make sense with test money; forced off on the mainnet (validated in config.py, and applied
# over any runtime override in api.App.features and the chain worker).
TEST_MONEY = ("demo_pay", "sponsor", "judge_passes")

# Every Tari-run indexer host we know, by network: a deployment must not mix them up (config.validate).
_HOSTS = {
    "esmeralda": ("ootle-indexer-a.tari.com", "ootle-indexer-b.tari.com", "esme-indexer-a.ootle.tari.com",
                  "esme-indexer-b.ootle.tari.com"),
    "mainnet": ("indexer-a.ootle.tari.com", "indexer-b.ootle.tari.com"),
}


def get(name: str) -> Network:
    try:
        return NETWORKS[name]
    except KeyError:
        raise ValueError(f"unknown Ootle network: {name!r}") from None


def foreign_indexer(name: str, url: str) -> bool:
    """True when `url` is a Tari-run indexer of another network than `name`."""
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    return any(host in hosts for other, hosts in _HOSTS.items() if other != name)


def forced_features(name: str) -> dict:
    """The features this network forbids, as overrides: {} on the testnet."""
    return {} if get(name).testnet else {f: False for f in TEST_MONEY}
