# SPDX-License-Identifier: MIT
"""Pay to open: the numbers /config publishes (research 16-drive-design §4, annex §1.4, §1.5).

A paid link splits its key: half after the `#` in the link, half (`server_half`) here, handed to one
buyer's browser once the chain shows that buyer's payment to the owner's sales address. The money goes
to the owner; we never hold it. The routes and the worker's scan arrive with the feature
(`features.pay_to_open`, off until then).
"""
PRICES_UT = (100_000, 250_000, 500_000)     # 0.1 / 0.25 / 0.5 tTARI: each at least three fees
BUYER_VIEWS = 3                              # opens a paid claim gives
BUYER_WINDOW_S = 7 * 86400                   # within this long after its release
CLAIM_TTL_S = 3600                           # time to pay a claim
LATE_GRACE_S = 86400                         # top-ups of an underpaid claim still count this long
DEMO_MAX_UT = 500_000                        # our demo wallet pays at most this per claim (test money)
MAX_OPEN_CLAIMS_PER_SHARE = 20


def config_block(fee_ut: int, watch_address: str | None) -> dict:
    return {"prices_ut": [str(p) for p in PRICES_UT], "fee_ut": str(fee_ut), "buyer_views": BUYER_VIEWS,
            "buyer_window_s": BUYER_WINDOW_S, "claim_ttl_s": CLAIM_TTL_S, "late_grace_s": LATE_GRACE_S,
            "demo_max_ut": str(DEMO_MAX_UT), "watch_address": watch_address,
            "max_open_claims_per_share": MAX_OPEN_CLAIMS_PER_SHARE}
