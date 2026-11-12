#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Where a mutis deployment lives on the server, for production and for each extra instance beside it.

  instance.py env [NAME]                       shell assignments for the deploy scripts (eval "$(...)")
  instance.py units NAME OUT --walletd NET:PORT [--walletd NET:PORT ...]
                                               the instance's systemd units, rendered from deploy/systemd/
  instance.py caddy NAME CONFIG OUT            the instance's Caddy site, rendered from deploy/caddy/Caddyfile
  instance.py check-name NAME

Production is the instance with no name: /etc/mutis/mutis.toml, /srv/mutis, users mutis and drive, units
mutis-api, mutis-chain, walletd and the rest, and it never changes here. An instance NAME (a-z, 0-9) gets
the same layout under its own names, so nothing it runs can read or write production's files or reach
production's walletd, and production can't reach its: /etc/mutis-NAME/mutis.toml, /srv/mutis-NAME/{app,data,
status}, users mutis-NAME and drive-NAME (in group mutis-NAME), /home/drive-NAME/{mutis,wallet-NETWORK,
wallet-backup}, /usr/local/lib/mutis-NAME, /var/backups/mutis-NAME (root only), units mutis-NAME-api, …,
mutis-NAME-walletd-NETWORK, and the Caddy site /etc/caddy/mutis.d/NAME.caddy, which the main Caddyfile
imports. Its units and its site are rendered from production's own files, so every hardening line there
applies to the instance too; deploy/tests/test_instance.py holds the renders to that.

MUTIS_INSTANCE names the instance for the scripts that read it (activate-release.sh, rollback.sh,
notarize-release.py, mutis-admin); unset or empty, production. Python standard library only.
"""
import argparse
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"[a-z][a-z0-9]{1,15}")
DEPLOY = Path(__file__).resolve().parent.parent
NETWORKS = {"esmeralda": ("esme", "Esmeralda testnet"), "mainnet": ("mainnet", "Ootle mainnet")}


@dataclass(frozen=True)
class Layout:
    name: str                     # "" for production

    @property
    def suffix(self) -> str:
        return f"-{self.name}" if self.name else ""

    @property
    def etc(self) -> str:
        return f"/etc/mutis{self.suffix}"

    @property
    def config(self) -> str:
        return f"{self.etc}/mutis.toml"

    @property
    def srv(self) -> str:
        return f"/srv/mutis{self.suffix}"

    @property
    def mutis_user(self) -> str:
        return f"mutis{self.suffix}"

    @property
    def drive_user(self) -> str:
        return f"drive{self.suffix}"

    @property
    def drive_home(self) -> str:
        return f"/home/drive{self.suffix}"

    @property
    def lib(self) -> str:
        return f"/usr/local/lib/mutis{self.suffix}"

    @property
    def backups(self) -> str:
        return f"/var/backups/mutis{self.suffix}"

    @property
    def admin(self) -> str:
        return f"/usr/local/sbin/mutis-admin{self.suffix}"

    def unit(self, base: str) -> str:
        """mutis-api → mutis-api (production) or mutis-NAME-api."""
        return base.replace("mutis-", f"mutis{self.suffix}-", 1) if base.startswith("mutis-") else base

    def walletd_unit(self, network: str) -> str:
        return f"mutis-{self.name}-walletd-{network}" if self.name else "walletd"

    def wallet_dir(self, network: str) -> str:
        return f"{self.drive_home}/wallet-{network}" if self.name else f"{self.drive_home}/wallet"

    @property
    def wallet_backups(self) -> str:
        return f"{self.drive_home}/wallet-backup" if self.name else f"{self.drive_home}/wallet/backup"

    @property
    def caddy_site(self) -> str:
        return f"/etc/caddy/mutis.d/{self.name}.caddy" if self.name else ""

    def env(self) -> dict:
        return {"MUTIS_INSTANCE": self.name, "INST_SUFFIX": self.suffix, "INST_ETC": self.etc,
                "INST_CONFIG": self.config, "INST_SRV": self.srv, "INST_APP": f"{self.srv}/app",
                "INST_DATA": f"{self.srv}/data", "INST_STATUS": f"{self.srv}/status",
                "INST_MUTIS_USER": self.mutis_user, "INST_DRIVE_USER": self.drive_user,
                "INST_DRIVE_HOME": self.drive_home, "INST_KEYS": f"{self.drive_home}/mutis", "INST_LIB": self.lib,
                "INST_BACKUPS": self.backups, "INST_ADMIN": self.admin, "INST_API_UNIT": self.unit("mutis-api"),
                "INST_CHAIN_UNIT": self.unit("mutis-chain"), "INST_CADDY_SITE": self.caddy_site,
                "INST_WALLET_BACKUPS": self.wallet_backups}


def layout(name: str | None) -> Layout:
    name = name or ""
    if name and not NAME.fullmatch(name):
        raise SystemExit(f"instance: a name is 2 to 16 of a-z and 0-9, starting with a letter: {name!r}")
    if name in ("api", "chain", "admin", "backup", "health"):
        raise SystemExit(f"instance: {name!r} would collide with a production unit name")
    return Layout(name)


# --- units --------------------------------------------------------------------------------------------------

def mount_unit(path: str) -> str:
    """systemd's unit name for a mount point (systemd-escape --path --suffix=mount), for the paths we use."""
    parts = [p.replace("-", "\\x2d") for p in path.strip("/").split("/")]
    return "-".join(parts) + ".mount"


def _common(text: str, lay: Layout) -> str:
    s = lay.suffix
    text = text.replace("/srv/mutis/", f"/srv/mutis{s}/").replace("/etc/mutis/mutis.toml", lay.config)
    text = text.replace("/usr/local/lib/mutis/", f"{lay.lib}/").replace("/home/drive/mutis", f"{lay.drive_home}/mutis")
    text = re.sub(r"^User=mutis$", f"User={lay.mutis_user}", text, flags=re.M)
    text = re.sub(r"^Group=mutis$", f"Group={lay.mutis_user}", text, flags=re.M)
    text = re.sub(r"^SupplementaryGroups=mutis$", f"SupplementaryGroups={lay.mutis_user}", text, flags=re.M)
    text = re.sub(r"^User=drive$", f"User={lay.drive_user}", text, flags=re.M)
    text = re.sub(r"^Group=drive$", f"Group={lay.drive_user}", text, flags=re.M)
    text = re.sub(r"^SyslogIdentifier=mutis-", f"SyslogIdentifier=mutis{s}-", text, flags=re.M)
    text = re.sub(r"^Description=mutis ", f"Description=mutis{s} ", text, flags=re.M)
    return text


def render_units(lay: Layout, walletds: list[tuple[str, int]], systemd: Path | None = None) -> dict[str, str]:
    """{unit file name: content} for instance `lay`, from production's units. `walletds` lists the instance's
    walletd daemons, (network, loopback port) each."""
    if not lay.name:
        raise SystemExit("instance: production's units are deploy/systemd/ as they are")
    systemd = systemd or DEPLOY / "systemd"
    out: dict[str, str] = {}
    l1_db = f"{lay.drive_home}/l1wallet-mainnet/mainnet/data/wallet/db"      # deploy/ootle/l1-wallet-mainnet.sh
    dbs = [f"{lay.wallet_dir(n)}/{n}/data/wallet.sqlite" for n, _ in walletds] + [f"l1wallet-mainnet={l1_db}/console_wallet.db"]
    backup_env = (f"Environment=MUTIS_WALLET_DBS={':'.join(dbs)}\n"
                  f"Environment=MUTIS_WALLET_BACKUPS={lay.wallet_backups}\n"
                  f"Environment=MUTIS_KEYS={lay.drive_home}/mutis\n"
                  f"Environment=MUTIS_ROOT_BACKUPS={lay.backups}\n"
                  f"Environment=MUTIS_CONFIG={lay.config}\n")
    walletd_units = [f"{lay.walletd_unit(n)}.service" for n, _ in walletds]
    for path in sorted(systemd.glob("*")):
        if not path.is_file() or path.suffix not in (".service", ".timer", ".mount"):
            continue
        text = path.read_text()
        if path.name == "walletd.service":
            for network, port in walletds:
                out[f"{lay.walletd_unit(network)}.service"] = _walletd(text, lay, network, port)
            continue
        if path.suffix == ".mount":
            where = re.search(r"^Where=(\S+)$", text, re.M).group(1)
            name = mount_unit(where.replace("/srv/mutis/", f"/srv/mutis{lay.suffix}/"))
            out[name] = _common(text, lay).replace("deploy/scripts/provision.sh", "deploy/scripts/provision-instance.sh")
            continue
        text = text.replace("/home/drive/wallet/backup", lay.wallet_backups)
        text = _common(text, lay)
        if path.name == "mutis-backup-wallet.service":
            # The L1 wallet's database is in WAL mode: reading it needs its -shm, so its directory is writable here.
            text = re.sub(r"^ReadWritePaths=(.*)$", lambda m: f"ReadWritePaths={m.group(1)} -{l1_db}", text, count=1, flags=re.M)
        if path.name == "mutis-chain.service":
            # Ordering only: the instance's walletds are enabled one by one (the network its config names).
            text = re.sub(r"^After=.*$", "After=network-online.target " + " ".join(walletd_units)
                          + f" {lay.unit('mutis-api')}.service", text, flags=re.M)
            text = re.sub(r"^Wants=.*$", "Wants=network-online.target", text, flags=re.M)
        if path.name in ("mutis-backup.service", "mutis-backup-wallet.service"):
            text = re.sub(r"^(Environment=MUTIS_CONFIG=.*\n)?(ExecStartPre=|ExecStart=)", lambda m: backup_env + m.group(2),
                          text, count=1, flags=re.M)
        out[lay.unit(path.stem) + path.suffix] = text
    return out


def _walletd(text: str, lay: Layout, network: str, port: int) -> str:
    arg, label = NETWORKS[network]
    base = lay.wallet_dir(network)
    text = text.replace("/home/drive/wallet", base).replace("/home/drive/", f"{lay.drive_home}/")
    text = text.replace("Description=Ootle wallet daemon for mutis (Esmeralda testnet)",
                        f"Description=Ootle wallet daemon for mutis{lay.suffix} ({label})")
    text = re.sub(r"^# The official Ootle wallet daemon \(Esmeralda testnet\).*$",
                  f"# The official Ootle wallet daemon ({label}) for instance {lay.name}, as {lay.drive_user}, "
                  f"on 127.0.0.1:{port} only.", text, flags=re.M)
    text = re.sub(r"^LoadCredential=keyring-pass:.*$",
                  f"LoadCredential=keyring-pass:{lay.etc}/credentials/walletd-{network}-keyring-pass", text, flags=re.M)
    text = re.sub(r"^RuntimeDirectory=walletd$", f"RuntimeDirectory=mutis{lay.suffix}-walletd-{network}", text, flags=re.M)
    text = re.sub(r"^SyslogIdentifier=walletd$", f"SyslogIdentifier={lay.walletd_unit(network)}", text, flags=re.M)
    text = re.sub(r"^User=drive$", f"User={lay.drive_user}", text, flags=re.M)
    text = re.sub(r"^Group=drive$", f"Group={lay.drive_user}", text, flags=re.M)
    # Nothing of production's or of this instance's service data, keys or config, whatever the paths' owners.
    text = re.sub(r"^InaccessiblePaths=.*$", f"InaccessiblePaths=-/srv/mutis -{lay.srv} -/etc/mutis -{lay.etc}/secret.key "
                  f"-{lay.config}", text, flags=re.M)
    env = (f"Environment=WALLETD_NETWORK={network}\nEnvironment=WALLETD_BASE={base}\n"
           f"Environment=WALLETD_LISTEN=127.0.0.1:{port}\nEnvironment=WALLETD_LOG_CONFIG={lay.etc}/walletd-log4rs.yml\n"
           f"Environment=WALLETD_BIN={lay.lib}/tari_ootle_walletd-{network}\n")
    text = re.sub(r"^ExecStart=/usr/local/lib/mutis/run-walletd.sh$", env + f"ExecStart={lay.lib}/run-walletd.sh",
                  text, flags=re.M)
    assert arg  # walletd's --network value is chosen in run-walletd.sh from WALLETD_NETWORK
    return text


# --- Caddy --------------------------------------------------------------------------------------------------

def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """Top-level blocks of our Caddyfile as (first line, lines): a block opens with a column-0 line ending in "{" and
    closes at the next line that is exactly "}" (the file is written that way; deploy/tests check it)."""
    blocks, lines, current = [], text.split("\n"), None
    for line in lines:
        if current is None:
            if line.endswith("{") and line and not line[0].isspace() and not line.startswith("#"):
                current = [line]
        else:
            current.append(line)
            if line == "}":
                blocks.append((current[0], current))
                current = None
    return blocks


INDEXER_CSP = "https://ootle-indexer-a.tari.com https://ootle-indexer-b.tari.com"


def render_caddy(lay: Layout, cfg: dict, caddyfile: Path | None = None) -> str:
    """The instance's site, self-contained: Caddy reads mutis.d/*.caddy before the main file defines its snippets,
    so the site carries copies of the ones it uses, under names of its own."""
    if not lay.name:
        raise SystemExit("instance: production's site is deploy/caddy/Caddyfile itself")
    from urllib.parse import urlsplit
    origin = urlsplit(cfg["public_origin"])
    host = origin.hostname
    if origin.scheme != "https" or not host or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise SystemExit(f"instance: public_origin must be https://host: {cfg['public_origin']!r}")
    listen = cfg.get("listen", "")
    m = re.fullmatch(r"127\.0\.0\.1:(\d+)", listen)
    if not m or m.group(1) == "8787":
        raise SystemExit(f"instance: listen must be 127.0.0.1:<port>, not production's 8787: {listen!r}")
    indexers = sorted(u.rstrip("/") for u in cfg.get("ootle", {}).get("indexers", []))   # as production lists its pair
    if not indexers or not all(re.fullmatch(r"https://[a-z0-9.-]+", u) for u in indexers):
        raise SystemExit("instance: ootle.indexers must be https://host URLs (the app's CSP allows them)")
    text = (caddyfile or DEPLOY / "caddy" / "Caddyfile").read_text()
    blocks = _blocks(text)
    snippets = {first[1:first.index(")")]: lines for first, lines in blocks if first.startswith("(")}
    site = next(lines for first, lines in blocks if first == "{$MUTIS_HOST} {")
    redirect = next(lines for first, lines in blocks if first == "http://{$MUTIS_HOST} {")
    prefix = f"mutis_{lay.name}_"
    used: list[str] = []

    def rename(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            m = re.fullmatch(r"(\s*)import (\S+)", line)
            if m and m.group(2) in snippets:
                if m.group(2) not in used:
                    used.append(m.group(2))
                line = f"{m.group(1)}import {prefix}{m.group(2)}"
            out.append(line)
        return out

    def localize(line: str) -> str:
        line = line.replace("/srv/mutis/", f"{lay.srv}/").replace("127.0.0.1:8787", listen)
        return line.replace(INDEXER_CSP, " ".join(indexers))

    site = [localize(line) for line in rename(site)]
    site[0] = f"{host} {{"
    if cfg.get("staging"):
        # A rehearsal: no search engine may index a copy of the site under another name.
        at = next(i for i, line in enumerate(site) if line.strip() == f"import {prefix}security_headers")
        site.insert(at + 1, '\theader X-Robots-Tag "noindex, nofollow"')
    redirect = [localize(line) for line in rename(redirect)]
    redirect[0] = f"http://{host} {{"
    for name in list(used):                      # snippets that import snippets
        rename(snippets[name])
    parts = [f"# SPDX-License-Identifier: MIT\n# The {lay.name} instance of mutis at {host}: rendered by deploy/scripts/"
             f"instance.py from deploy/caddy/Caddyfile\n# (its site block, its HTTP redirect and the snippets they use, renamed "
             f"{prefix}*). Don't edit: activate-release.sh writes it again.\n"]
    for name in used:
        body = [localize(line) for line in rename(snippets[name])]
        body[0] = f"({prefix}{name}) {{"
        if INDEXER_CSP in "\n".join(snippets[name]) and " ".join(indexers) not in "\n".join(body):
            raise SystemExit("instance: could not set the indexers in the CSP")
        parts.append("\n".join(body))
    parts += ["\n".join(redirect), "\n".join(site)]
    out = "\n\n".join(parts) + "\n"
    for leftover in ("{$MUTIS_HOST}", "/srv/mutis/", "127.0.0.1:8787"):
        if leftover in out:
            raise SystemExit(f"instance: the rendered site still has {leftover}")
    return out


# --- command line -------------------------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("env")
    e.add_argument("name", nargs="?", default="")
    u = sub.add_parser("units")
    u.add_argument("name")
    u.add_argument("out", type=Path)
    u.add_argument("--walletd", action="append", default=[], help="NETWORK:PORT, once per walletd of the instance")
    c = sub.add_parser("caddy")
    c.add_argument("name")
    c.add_argument("config", type=Path)
    c.add_argument("out", type=Path)
    n = sub.add_parser("check-name")
    n.add_argument("name")
    args = p.parse_args()
    if args.cmd == "env":
        for key, value in layout(args.name).env().items():
            print(f"{key}={shlex.quote(value)}")
        return 0
    lay = layout(args.name)
    if args.cmd == "check-name":
        if not lay.name:
            raise SystemExit("instance: give a name")
        return 0
    if args.cmd == "units":
        walletds = []
        for spec in args.walletd:
            network, _, port = spec.partition(":")
            if network not in NETWORKS or not port.isdigit() or not 1024 < int(port) < 65536 or int(port) == 5100:
                raise SystemExit(f"instance: --walletd NETWORK:PORT (esmeralda|mainnet, not production's 5100): {spec!r}")
            walletds.append((network, int(port)))
        args.out.mkdir(parents=True, exist_ok=True)
        for name, text in render_units(lay, walletds).items():
            (args.out / name).write_text(text)
            print(name)
        return 0
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    args.out.write_text(render_caddy(lay, cfg))
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
