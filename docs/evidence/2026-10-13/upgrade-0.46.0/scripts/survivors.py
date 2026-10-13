# SPDX-License-Identifier: MIT
import sqlite3, time
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
q = lambda s, *a: c.execute(s, a).fetchone()[0]
print("==", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "(read-only)")
print("judge passes", q("SELECT COUNT(*) FROM judge_passes"))
print("security drop 3w7m8k2v5t", q("SELECT state FROM drops WHERE id = '3w7m8k2v5t'"))
print("identities", q("SELECT COUNT(*) FROM identities"), "| items", q("SELECT COUNT(*) FROM items"), "| drops", q("SELECT COUNT(*) FROM drops"),
      "| shares", q("SELECT COUNT(*) FROM shares"), "| invoices", q("SELECT COUNT(*) FROM invoices"), "| payments", q("SELECT COUNT(*) FROM payments"))
print("seal_checkpoints by state", dict(c.execute("SELECT state, COUNT(*) FROM seal_checkpoints GROUP BY state").fetchall()),
      "| latest committed", c.execute("SELECT idx, chain_index, epoch FROM seal_checkpoints WHERE state='committed' ORDER BY idx DESC LIMIT 1").fetchone())
