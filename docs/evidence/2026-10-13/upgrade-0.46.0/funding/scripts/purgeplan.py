# SPDX-License-Identifier: MIT
# The purge plan: what an E2E run added, from two dbsnap.py snapshots (before, after). Read-only; runs
# on the workstation. Canary items are the service's own (the hourly canary and E-25's forced one) and
# stay; empty test lockers have no admin removal and stay; credited invoices and their payments stay
# (the pack was paid on chain and released by the scenario). Prints the plan as JSON on stdout.
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ids = lambda s, k: {r[0] for r in s[k]}
new = {k: [r for r in b[k] if r[0] not in ids(a, k)] for k in ("items", "drops", "identities", "invoices", "payments", "judge_passes", "shares")}
plan = {
    "before": a["at"], "after": b["at"],
    "items": [r[0] for r in new["items"] if not r[2] and r[1] != "deleted"],
    "canary_items_kept": [r[0] for r in new["items"] if r[2]],
    "drops": [r[0] for r in new["drops"] if r[1] == "active"],
    "drops_already_ended": [r[0] for r in new["drops"] if r[1] != "active"],
    "judge_passes_rowids": [r[0] for r in new["judge_passes"]],
    "new_identities": len(new["identities"]),
    "active_packs_among_new": sum(1 for r in new["identities"] if r[2] and r[2] > 0),
    "new_invoices": [[r[0], r[2]] for r in new["invoices"]],
    "new_payments": [[r[1], r[2]] for r in new["payments"]],
    "new_items_by_state": {s: sum(1 for r in new["items"] if r[1] == s) for s in {r[1] for r in new["items"]}},
}
json.dump(plan, sys.stdout, indent=1)
print()
