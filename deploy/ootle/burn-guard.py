#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Say yes to a mainnet burn only when it can be claimed, then print the console wallet's exact steps.

  sudo env MUTIS_INSTANCE=<name> python3 -I deploy/ootle/burn-guard.py --claim-key <64 hex> --sidechain-key '' \\
      --amount-xtm <N> [--max-xtm 200] [--start-heights deploy/ootle/mainnet-start-height.json]

It refuses (exit 1, one line per reason) unless every one of these holds:
  1. the final MAINNET_START_HEIGHT is known: the installed mainnet walletd's version (tari_ootle_walletd-mainnet
     --version) has an entry in mainnet-start-height.json marked final, and the Ootle source at that entry's
     source_ref still says the same value (fetched from GitHub; a placeholder is never final);
  2. the L1 mainnet tip (the Tari explorer's best_block_height) is at or above it, so the burn's block will be too;
  3. the claim key is the account_public_key of one of the instance's mainnet walletd accounts (service or
     sponsor, deploy/ootle/mainnet-walletd.sh), and, when walletd answers, an owner key it holds;
  4. the sidechain key is empty (empty means the Ootle; anything else burns to another sidechain for good);
  5. the amount is a positive number of XTM, at most --max-xtm (keep amounts small).
It burns nothing and runs no wallet: deploy/ootle/l1-burn.py runs it before each burn it makes, and its steps below are
the by-hand fallback in the TUI. Python standard library only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import instance  # noqa: E402

EXPLORER = "https://textexplore.tari.com/?json"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{file}"
CONFIRMATIONS = 780          # base_layer_confirmations on the mainnet: about a day of 2-minute blocks
# 380,400 was called a placeholder by tari-ootle #3322 (2026-11-04) until MainNet launched on it (2026-11-10): the
# source says the value is fixed once MainNet runs, so it is final (mainnet-start-height.json). Values here are refused.
PLACEHOLDERS: set[int] = set()


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mutis-burn-guard"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def start_height(pins_path: Path, walletd: Path, problems: list) -> int | None:
    try:
        version = subprocess.run([str(walletd), "--version"], capture_output=True, text=True, check=True).stdout.split()[1]
    except (OSError, subprocess.CalledProcessError, IndexError):
        problems.append(f"no mainnet walletd at {walletd} (deploy/ootle/mainnet-walletd.sh install)")
        return None
    pins = json.loads(pins_path.read_text())
    pin = next((p for p in pins["pins"] if p["ootle_version"] == version), None)
    if pin is None:
        problems.append(f"{pins_path.name} has no entry for the installed walletd {version}")
        return None
    if not pin["final"] or pin["start_height"] in PLACEHOLDERS:
        problems.append(f"MAINNET_START_HEIGHT is not final for Ootle {version} ({pin['start_height']}: {pin['why']})")
        return None
    try:
        source = fetch(RAW.format(repo=pins["repository"], ref=pin["source_ref"], file=pins["file"])).decode()
    except OSError as e:
        problems.append(f"could not read {pins['file']} at {pin['source_ref']} ({e})")
        return None
    m = re.search(r"pub const MAINNET_START_HEIGHT: u64 = ([0-9_]+);", source)
    value = int(m.group(1).replace("_", "")) if m else None
    if value != pin["start_height"]:
        problems.append(f"the source at {pin['source_ref']} says {value}, the pin says {pin['start_height']}")
        return None
    print(f"ok  MAINNET_START_HEIGHT {value:,} (Ootle {version}, {pin['source_ref']}: {pin['why']})")
    return value


def l1_tip(problems: list) -> int | None:
    try:
        tip = int(json.loads(fetch(EXPLORER))["tipInfo"]["metadata"]["best_block_height"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        problems.append(f"could not read the L1 tip from {EXPLORER} ({e})")
        return None
    print(f"ok  L1 mainnet tip {tip:,} (explorer)")
    return tip


def account_keys(lay, walletd_url: str | None) -> dict:
    keys = {}
    for path in sorted(Path(lay.wallet_dir("mainnet")).glob("account-*.json")):
        a = json.loads(path.read_text())
        keys[a["account_public_key"]] = path.stem.removeprefix("account-")
    held = None
    if walletd_url:
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "auth.request",
                               "params": {"permissions": ["Admin"], "credentials": "None"}}).encode()
            req = urllib.request.Request(walletd_url, data=body, headers={"Content-Type": "application/json"})
            token = json.load(urllib.request.urlopen(req, timeout=10))["result"]["token"]
            body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "accounts.list",
                               "params": {"offset": 0, "limit": 100}}).encode()
            req = urllib.request.Request(walletd_url, data=body, headers={"Content-Type": "application/json",
                                                                          "Authorization": "Bearer " + token})
            held = {e["account"]["owner_public_key"]: e["account"]["name"]
                    for e in json.load(urllib.request.urlopen(req, timeout=10))["result"]["accounts"]}
        except (OSError, ValueError, KeyError):
            held = None
    return {"files": keys, "walletd": held}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--claim-key", required=True)
    p.add_argument("--sidechain-key", required=True, help="must be given, and empty: --sidechain-key ''")
    p.add_argument("--amount-xtm", required=True, type=float)
    p.add_argument("--max-xtm", type=float, default=200)
    p.add_argument("--start-heights", type=Path, default=HERE / "mainnet-start-height.json")
    args = p.parse_args()
    lay = instance.layout(os.environ.get("MUTIS_INSTANCE"))
    if not lay.name:
        raise SystemExit("burn-guard: MUTIS_INSTANCE names no instance")
    problems: list[str] = []
    walletd = Path(lay.lib) / "tari_ootle_walletd-mainnet"
    start = start_height(args.start_heights, walletd, problems)
    tip = l1_tip(problems)
    if start is not None and tip is not None and tip < start:
        problems.append(f"the L1 tip {tip:,} is below MAINNET_START_HEIGHT {start:,}: a burn now would be lost "
                        f"(wait {start - tip:,} blocks, about {(start - tip) * 2 / 60:.1f} h)")
    key = args.claim_key.strip().lower()
    port = next((line.split(":")[1] for line in Path(lay.etc, "instance.conf").read_text().splitlines()
                 if line.startswith("walletd=mainnet:")), None)
    known = account_keys(lay, f"http://127.0.0.1:{port}/json_rpc" if port else None)
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        problems.append("the claim key must be 64 hex characters (an account public key, not an otl_ address)")
    elif key not in known["files"]:
        problems.append(f"the claim key is none of this instance's mainnet accounts ({', '.join(known['files'].values()) or 'none set up'})")
    elif known["walletd"] is not None and key not in known["walletd"]:
        problems.append("the claim key is in the account files but the running walletd doesn't hold it")
    else:
        print(f"ok  claim key = account {known['files'][key]}" + (" (walletd holds it)" if known["walletd"] else
                                                                   " (walletd not answering; checked the account files)"))
    if args.sidechain_key != "":
        problems.append("the sidechain key must be empty: a non-empty one burns to another sidechain and nobody can claim it")
    else:
        print("ok  sidechain key empty (the Ootle)")
    if not 0 < args.amount_xtm <= args.max_xtm:
        problems.append(f"the amount must be more than 0 and at most {args.max_xtm:g} XTM (--max-xtm): keep it small")
    else:
        print(f"ok  amount {args.amount_xtm:g} XTM")
    if problems:
        for line in problems:
            print(f"NO  {line}")
        print("burn-guard: refused. Burn nothing.")
        return 1
    print(f"""
burn-guard: yes. In the mainnet console wallet, exactly this (deploy/ootle/burn-mainnet.md):
  1. sudo MUTIS_INSTANCE={lay.name} bash deploy/ootle/l1-wallet-mainnet.sh tui
     (it stops the wallet's service, opens its TUI in this terminal, and starts the service again when you quit).
     Wait until it is synced and shows the XTM.
  2. Press Tab until the Burn tab is selected. Type into one field at a time: outside a field, letters are commands.
  3. C  Claim Public Key: {key}
        Sidechain Key: leave EMPTY
     A  Amount: {args.amount_xtm:g}T
     F  Fee-per-gram: keep the default (5)
     P  Payment-id: leave empty
  4. Check the claim key against this line once more, then S, then y.
  5. The proof file lands in {lay.drive_home}/.local/share/tari/mainnet/burn_proofs a few minutes after the burn is
     mined; walletd (mutis-{lay.name}-walletd-mainnet) claims it by itself after {CONFIRMATIONS} confirmations (about a
     day) in a later epoch, as a stealth output; the launch trigger reveals what it needs into the public vault.
     Burn block ≥ {start:,}; claimable from about block (burn block + {CONFIRMATIONS}).""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
