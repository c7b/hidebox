# SPDX-License-Identifier: MIT
# One transaction: mark checkpoints #141..#158 committed with the epoch and chain index the SealLog
# component holds for them, only where the row still says failed and its tx, tree size, root and
# component equal what both indexers show. Any surprise rolls the whole thing back.
import json, sqlite3, sys
chains = []
for f in sys.argv[1:3]:
    d = json.load(open(f)); comp = d["substate"]["Component"]
    entries, first = comp["body"]["state"]
    chains.append({first + i: (e[0], e[1]["hex"], e[2]) for i, e in enumerate(entries)})
component = sys.argv[3]
c = sqlite3.connect("/srv/mutis/data/db/mutis.sqlite3", isolation_level=None, timeout=30)
c.execute("PRAGMA busy_timeout=30000")
c.execute("BEGIN IMMEDIATE")
try:
    n = 0
    for idx in range(141, 159):
        a, b = chains[0][idx - 1], chains[1][idx - 1]
        assert a == b, idx
        epoch, root_hex, size = a
        row = c.execute("SELECT state, tree_size, root, component, tx_id FROM seal_checkpoints WHERE idx = ?", (idx,)).fetchone()
        assert row and row[0] == "failed" and row[1] == size and row[2].hex() == root_hex and row[3] == component and row[4], (idx, row and row[0])
        cur = c.execute("UPDATE seal_checkpoints SET state = 'committed', epoch = ?, chain_index = ? "
                        "WHERE idx = ? AND state = 'failed' AND tree_size = ? AND root = ? AND component = ?",
                        (epoch, idx - 1, idx, size, bytes.fromhex(root_hex), component))
        assert cur.rowcount == 1, idx
        n += 1
    c.execute("COMMIT")
    print(f"committed: {n} rows (#141..#158)")
except BaseException:
    c.execute("ROLLBACK")
    raise
for r in c.execute("SELECT idx, state, epoch, chain_index FROM seal_checkpoints WHERE idx BETWEEN 140 AND 159 ORDER BY idx"):
    print(" ", r)
