# SPDX-License-Identifier: MIT
"""The only way server code writes logs (spec §14.3).

A log line may hold a route name, a status code, a duration and a fixed event code. Nothing that
came from a request, the database or the chain can reach this module's output, because every
argument is checked against a closed vocabulary before it is formatted.
"""
import logging
import re
import sys

_log = logging.getLogger("mutis")
_ROUTE = re.compile(r"^[a-z_]+(\.[a-z_]+)*$")

EVENTS = frozenset({
    # API
    "api.start", "api.stop", "api.internal_error", "api.request_rejected", "api.connection_error",
    # chain worker
    "chain.start", "chain.stop", "chain.loop_error", "chain.walletd_down", "chain.walletd_up",
    "chain.indexer_error", "chain.mirror_error", "chain.sidecar_restart", "chain.sidecar_error",
    "chain.sidecar_hash_mismatch", "chain.job_failed", "chain.job_done", "chain.budget_50",
    "chain.budget_90", "chain.credit_freeze", "chain.reconcile_ok", "chain.canary_sealed",
    "chain.canary_failed", "chain.canary_verified", "chain.seal_checkpoint", "chain.seal_failed",
    "chain.config_missing", "chain.job_interrupted", "chain.reconcile_unknown", "chain.reconcile_mismatch",
    "chain.payment_not_ours", "chain.seller_bad_key",
    # cleanup
    "cleanup.run", "cleanup.error",
})
_LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR, "critical": logging.CRITICAL}


def setup(stream=None) -> None:
    """Send mutis log lines to stderr (journald) in one fixed format."""
    if _log.handlers:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    _log.addHandler(handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def request(route: str, status: int, ms: int) -> None:
    if not _ROUTE.match(route) or type(status) is not int or type(ms) is not int:
        raise ValueError("logsafe: refused a request line")
    _log.info("route=%s status=%d ms=%d", route, status, ms)


def event(code: str, level: str = "info", count: int | None = None) -> None:
    """Log a fixed event code, optionally with a plain count (never an id or an amount)."""
    if code not in EVENTS or level not in _LEVELS or (count is not None and type(count) is not int):
        raise ValueError("logsafe: refused an event")
    if count is None:
        _log.log(_LEVELS[level], "event=%s", code)
    else:
        _log.log(_LEVELS[level], "event=%s n=%d", code, count)
