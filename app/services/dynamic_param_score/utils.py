"""Shared math helpers for Dynamic Param Score Engine."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def clamp01(x: float) -> float:
    return clamp(x, 0.0, 1.0)


def normalize_score(value: float, lo: float = 0.0, hi: float = 1.0) -> int:
    """Map value in [lo, hi] to 0-100 integer score."""
    if hi <= lo:
        return 50
    t = clamp01((value - lo) / (hi - lo))
    return int(round(100 * t))


def invert_score(raw: int) -> int:
    return int(clamp(100 - raw, 0, 100))


def scale(
    score: float,
    low_score: float,
    high_score: float,
    low_value: float,
    high_value: float,
) -> float:
    if score <= low_score:
        return low_value
    if score >= high_score:
        return high_value
    t = (score - low_score) / (high_score - low_score)
    return low_value + t * (high_value - low_value)


def round_float(v: Optional[float], d: int = 4) -> Optional[float]:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), d)


def json_safe(obj: Any) -> Any:
    """Recursively make object JSON-serializable."""
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 8)
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    if hasattr(obj, "to_dict"):
        return json_safe(obj.to_dict())
    if hasattr(obj, "__dict__"):
        return json_safe(vars(obj))
    return str(obj)


def distribute_weights(n: int, max_per_level: float) -> List[float]:
    """Build normalized buy/sell qty weights, no single level above max_per_level."""
    if n <= 0:
        return []
    raw = [1.0 + i * 0.15 for i in range(n)]
    total = sum(raw)
    weights = [r / total for r in raw]
    # Cap and renormalize
    capped = [min(w, max_per_level) for w in weights]
    s = sum(capped)
    if s <= 0:
        return [1.0 / n] * n
    return [w / s for w in capped]
