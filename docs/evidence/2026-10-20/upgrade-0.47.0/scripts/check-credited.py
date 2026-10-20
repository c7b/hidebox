# SPDX-License-Identifier: MIT
# Read-only: each credited pack payment (and counted sale payment) as the new code reads it on both indexers.
import collections, sys
sys.path.insert(0, sys.argv[1])
from mutis import indexer, payments
ix = indexer.Indexers(["https://ootle-indexer-b.tari.com", "https://ootle-indexer-a.tari.com"], rate=4)
tally = collections.Counter()
for line in open(sys.argv[2]):
    kind, uid = line.split()
    a = [payments.utxo_on_indexer(ix, uid, i)[0] for i in range(2)]
    anywhere = payments.committed_anywhere(ix, uid)
    tally[(kind, tuple(a), anywhere)] += 1
for k, v in sorted(tally.items()): print(k, v)
