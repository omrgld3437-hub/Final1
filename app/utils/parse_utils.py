"""Small, dependency-free parsing helpers shared across config / gate layers.

Centralised here so that boolean config flags (e.g. ``dynamic_mode``) are parsed
identically everywhere. Python truthiness is NOT safe for this: ``bool("false")``
is ``True``, so a string ``"false"`` coming from an API / migration / legacy
config JSON would otherwise be treated as enabled.
"""

from __future__ import annotations
from typing import Any

_TRUTHY = {"1", "true", "yes", "on", "y", "t"}
_FALSY = {"0", "false", "no", "off", "n", "f", "", "none", "null"}


def parse_bool(value: Any, default: bool = False) -> bool:
    """Robust boolean parse.

    - Real bools pass through.
    - Numbers: non-zero → True.
    - Strings: case/space-insensitive match against truthy/falsy sets;
      unknown strings fall back to ``default``.
    - None → ``default``.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUTHY:
            return True
        if s in _FALSY:
            return False
        return default
    return bool(value)
