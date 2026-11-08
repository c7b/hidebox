# SPDX-License-Identifier: MIT
# upgrade-0.50.md §4: what is in flight, from mutis's database, read-only (as mutis).
import sqlite3
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
for what, sql in (("jobs sending (must be 0)", "SELECT count(*) FROM jobs WHERE state = 'sending'"),
                  ("checkpoints pending (must be 0)", "SELECT count(*) FROM seal_checkpoints WHERE state = 'pending'"),
                  ("jobs queued (wait for the resume)", "SELECT count(*) FROM jobs WHERE state = 'queued'"),
                  ("invoices open", "SELECT count(*) FROM invoices WHERE status IN ('pending','seen','proven') AND expires_at > unixepoch()"),
                  ("pack payments pending_check", "SELECT count(*) FROM payments WHERE status = 'pending_check'"),
                  ("claims open", "SELECT count(*) FROM claims WHERE status IN ('pending','seen') AND expires_at > unixepoch()"),
                  ("sale payments pending_check", "SELECT count(*) FROM sale_payments WHERE status = 'pending_check'")):
    print(f"{c.execute(sql).fetchone()[0]:6d}  {what}")
row = c.execute("SELECT idx, state, chain_index, substr(tx_id, 1, 8), submitted_at FROM seal_checkpoints ORDER BY idx DESC LIMIT 1").fetchone()
print("latest checkpoint (idx, state, chain_index, tx, submitted_at):", tuple(row) if row else None)
