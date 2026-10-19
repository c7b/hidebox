# SPDX-License-Identifier: MIT
"""Rows of the UTXO mirror (spec §10.6). The chain worker pulls the indexers' streams; the outputs of a
transaction known to have committed are added at once, because the streams list an output only once
the network's consensus epoch reaches it (about 20 minutes on Esmeralda), and a delivery
shouldn't wait that long for an inbox to find it."""
import sqlite3

from . import db, indexer
from .indexer import IndexerError, Indexers


def insert(conn: sqlite3.Connection, out: dict, epoch: int | None, now: int) -> int:
    """One output as indexer.parse_fetched gives it; 1 if it is new to the mirror."""
    return conn.execute(
        "INSERT OR IGNORE INTO chain_utxos(id, nonce, enc, tag, epoch, first_seen, promise, viewable, auth) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (indexer.utxo_id(out["commitment"]), bytes.fromhex(out["nonce"]), bytes.fromhex(out["enc"]),
         out["tag"].to_bytes(4, "big"), epoch, now, out["promise"], out["viewable"], out["auth"])).rowcount


def add_committed(conn: sqlite3.Connection, indexers: Indexers, substate_ids: list[str], epoch: int | None,
                  now: int) -> int:
    """The TARI outputs among a committed transaction's new substates, read from the indexers; one the
    indexers can't show yet is left to the stream."""
    found = []
    for substate_id in substate_ids:
        commitment = substate_id.rsplit("_", 1)[-1]
        if indexer.utxo_id(commitment) != substate_id:
            continue
        try:
            status, obj, _ = indexers.get_json(f"/substates/{substate_id}")
        except IndexerError:
            continue
        utxo = (obj.get("substate") or {}).get("Utxo") if status == 200 and isinstance(obj, dict) else None
        out = indexer.parse_fetched([commitment, utxo]) if isinstance(utxo, dict) else None
        if out is not None:
            found.append(out)
    with db.tx(conn):
        return sum(insert(conn, out, epoch, now) for out in found)
