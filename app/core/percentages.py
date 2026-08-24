"""Percentage rounding for distribution stats.

Naively rounding each bucket's `count / total * 100` to one decimal place
can make the reported percentages sum to 99.9 or 100.1 — e.g. three
buckets of 1/3 each round to 33.3 + 33.3 + 33.3 = 99.9. That's a real bug
for a product whose whole pitch is "trustworthy structured stats", so we
use the largest-remainder method (a.k.a. Hare quota) instead: allocate
whole tenths-of-a-percent by flooring, then hand out the leftover tenths
one at a time to the buckets with the largest rounded-down remainder.
This guarantees the reported percentages always sum to exactly 100.0
(for any non-empty distribution) while staying as close as possible to
the true proportional value.
"""

import math
from collections.abc import Mapping
from typing import TypeVar

K = TypeVar("K")

_SCALE = 1000  # tenths-of-a-percent per 100.0%


def distribution_with_percentages(
    counts: Mapping[K, int], total: int
) -> dict[K, dict[str, float | int]]:
    """Return `{key: {"count": n, "percentage": p}}` where percentages sum to 100.0.

    `total` is passed explicitly rather than derived from `sum(counts.values())`
    so callers can pass a total that's known correct even if some bucket
    keys were never queried (there are none such today, but this keeps the
    function honest about what "100%" means).
    """
    if total <= 0:
        return {key: {"count": count, "percentage": 0.0} for key, count in counts.items()}

    raw = {key: (count / total) * _SCALE for key, count in counts.items()}
    floors = {key: math.floor(value) for key, value in raw.items()}
    remainder = _SCALE - sum(floors.values())

    # Hand out the leftover tenths to the buckets with the largest
    # fractional remainder first (ties broken by key order, which is
    # stable/deterministic since `counts` preserves insertion order).
    ranked = sorted(counts.keys(), key=lambda key: raw[key] - floors[key], reverse=True)
    for i in range(remainder):
        floors[ranked[i % len(ranked)]] += 1

    return {key: {"count": counts[key], "percentage": floors[key] / 10} for key in counts}
