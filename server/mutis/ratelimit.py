# SPDX-License-Identifier: MIT
"""In-memory rate limits (spec §6.2): GCRA token buckets keyed by IP key, locker or a keyed hash.

Nothing here touches disk; a restart forgets every counter (accepted by the spec). A rule is
(name, key, limit, period_s, cost): `limit` units per `period_s`, all of them available at once.
"""
import math
import threading
from collections import OrderedDict

Rule = tuple[str, object, float, float, float]


class Limiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._tat: dict[tuple[str, object], float] = {}

    def _wait(self, rule: Rule, now: float) -> tuple[float, float]:
        name, key, limit, period, cost = rule
        tat = max(self._tat.get((name, key), now), now)
        new_tat = tat + period / limit * cost
        return new_tat - period - now, new_tat

    def hit(self, rules: list[Rule], now: float) -> int:
        """Charge every rule, or none of them. Returns 0, or the whole seconds to wait."""
        with self._lock:
            results = [self._wait(rule, now) for rule in rules]
            worst = max((wait for wait, _ in results), default=0.0)
            if worst > 0:
                return max(1, math.ceil(worst))
            for rule, (_, new_tat) in zip(rules, results):
                self._tat[(rule[0], rule[1])] = new_tat
            if len(self._tat) > 200_000:
                self._tat = {k: v for k, v in self._tat.items() if v > now}
            return 0

    def refund(self, rule: Rule, now: float) -> None:
        """Give back what a rule charged (used when a later check refuses the request)."""
        name, key, limit, period, cost = rule
        with self._lock:
            if (name, key) in self._tat:
                self._tat[(name, key)] = max(now, self._tat[(name, key)] - period / limit * cost)

    def clear(self) -> None:
        with self._lock:
            self._tat.clear()


class Recent:
    """A small in-memory table that forgets its least recently written keys past `cap` entries,
    so rotating IPv6 addresses can't grow it without bound. Cleared with the day key."""

    def __init__(self, cap: int):
        self.cap = cap
        self._lock = threading.Lock()
        self._data: OrderedDict = OrderedDict()

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def update(self, key, fn, default):
        """Store fn(current value or default) and return it."""
        with self._lock:
            value = fn(self._data.get(key, default))
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.cap:
                self._data.popitem(last=False)
            return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
