# SPDX-License-Identifier: MIT
# Compare mutis's seal_checkpoints rows with the SealLog component's state on both indexers (read-only).
import json, sqlite3, sys
chains = []
for f in sys.argv[1:3]:
    d = json.load(open(f)); comp = d["substate"]["Component"]
    entries, first = comp["body"]["state"]
    chains.append({first + i: (e[0], e[1]["hex"], e[2]) for i, e in enumerate(entries)})
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
comp_db = None; ok = True
print("idx  state      tx        tree_size  root(db)  | chain index: epoch  root(a=b)  leaf_count  match")
for idx, size, root, state, tx, component, epoch, cidx in c.execute(
        "SELECT idx, tree_size, root, state, tx_id, component, epoch, chain_index FROM seal_checkpoints WHERE idx BETWEEN 139 AND 159 ORDER BY idx"):
    rhex = root.hex() if isinstance(root, bytes) else str(root)
    i = idx - 1
    a, b = chains[0].get(i), chains[1].get(i)
    match = a is not None and a == b and a[1] == rhex and a[2] == size
    ok &= match or idx not in range(141, 159)
    print(f"#{idx}  {state:9s}  {str(tx)[:8]}  {size:6d}  {rhex[:8]}…  |  {i}: {a[0] if a else '-'}  {a[1][:8] if a else '-'}…  {a[2] if a else '-'}  {'same' if match else 'DIFFERENT'}   (db epoch {epoch}, chain_index {cidx})")
print("component in db rows == the live log:", {r[0] for r in c.execute("SELECT DISTINCT component FROM seal_checkpoints WHERE idx BETWEEN 141 AND 158")} == {sys.argv[3]})
print("ALL 18 MATCH" if ok else "MISMATCH")
