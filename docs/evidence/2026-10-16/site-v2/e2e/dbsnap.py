# SPDX-License-Identifier: MIT
# read-only id snapshot of the production database (run as mutis): python3 -I - < dbsnap.py > snap.json
import json, sqlite3
con = sqlite3.connect("file:/srv/mutis/data/db/mutis.sqlite3?mode=ro", uri=True)
q = lambda sql: [list(r) for r in con.execute(sql)]
print(json.dumps({
    "items": q("select id, state, canary, owner_id is not null from items"),
    "shares": q("select id, item_id from shares"),
    "paid_shares": q("select share_id, paused from paid_shares"),
    "drops": q("select id, state from drops"),
    "identities": q("select id, paid_bytes, paid_until from identities"),
    "invoices": q("select id, identity_id, status from invoices"),
    "claims": q("select id, share_id, status from claims"),
    "judge_passes": q("select count(*) from judge_passes")[0][0],
    "security_drop": q("select state from drops where id = '3w7m8k2v5t'"),
    "canary_ready": q("select count(*) from items where canary = 1 and state = 'ready'")[0][0],
    "meta_keys": [r[0] for r in q("select key from meta")],
}))
