"""Deterministic math helpers for V5 shelf generation."""

from __future__ import annotations

from typing import List


def round2(n: float) -> float:
    return round(n + 1e-12, 2)


def round4(n: float) -> float:
    return round(n + 1e-12, 4)


def clamp(n: float, lo: float, hi: float) -> float:
    if n != n:  # NaN check without math import
        raise ValueError("Cannot clamp NaN")
    return min(hi, max(lo, n))


def sum_values(values: List[float]) -> float:
    return sum(values)


def assert_percent_range(n: float, name: str) -> None:
    if not (n == n and abs(n) != float("inf")):
        raise ValueError(f"{name} is not finite")
    if n < 0 or n > 100:
        raise ValueError(f"{name} out of percent range: {n}")


def normalize_distribution(values: List[float]) -> List[float]:
    total = sum_values(values)
    if total <= 0:
        raise ValueError("Invalid distribution total")
    normalized = [round2((v / total) * 100) for v in values]
    diff = round2(100 - sum_values(normalized))
    normalized[-1] = round2(normalized[-1] + diff)
    return normalized


def is_approx_100(values: List[float], tolerance: float = 0.02) -> bool:
    return abs(sum_values(values) - 100) <= tolerance


def is_strictly_increasing(values: List[float]) -> bool:
    for i in range(1, len(values)):
        if not (values[i] > values[i - 1]):
            return False
    return True
