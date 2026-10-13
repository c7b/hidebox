# SPDX-License-Identifier: MIT
# Read-only snapshot of the rows an E2E run can add (sqlite mode=ro, as mutis): ids and states only, no
# key material (judge passes by rowid, never their hashes). JSON on stdout; the purge plan is the diff of
# two of these. A summary line goes to stderr.
import json, sqlite3, sys, time
c = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
rows = lambda s: [list(r) for r in c.execute(s)]
snap = {
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "items": rows("SELECT id, state, canary, owner_id, created_hour FROM items"),
    "drops": rows("SELECT id, state, label, created_day FROM drops"),
    "identities": rows("SELECT id, created_day, paid_until FROM identities"),
    "invoices": rows("SELECT id, identity_id, status FROM invoices"),
    "payments": rows("SELECT utxo_id, invoice_id, status FROM payments"),
    "judge_passes": rows("SELECT rowid, created_at, uses_left FROM judge_passes"),
    "shares": rows("SELECT id, item_id, state FROM shares"),
}
active = c.execute("SELECT COUNT(*) FROM identities WHERE paid_until > strftime('%s','now')").fetchone()[0]
sec = c.execute("SELECT state FROM drops WHERE id = '3w7m8k2v5t'").fetchone()
json.dump(snap, sys.stdout)
print(f"{snap['at']}: judge passes {len(snap['judge_passes'])} | security drop 3w7m8k2v5t {sec[0] if sec else None} | "
      f"identities {len(snap['identities'])} (active packs {active}) | items {len(snap['items'])} | drops {len(snap['drops'])} | "
      f"shares {len(snap['shares'])} | invoices {len(snap['invoices'])} | payments {len(snap['payments'])}", file=sys.stderr)
