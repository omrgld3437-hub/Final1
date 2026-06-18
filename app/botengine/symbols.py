"""Bot trading pair symbol normalization (SOL → SOLUSDT)."""

from __future__ import annotations

import re

_QUOTE_SUFFIXES = ("USDT", "FDUSD", "BUSD", "USDC", "TUSD")
_BASE_ONLY_RE = re.compile(r"^[A-Z0-9]{2,12}$")


def normalize_bot_trading_symbol(symbol: str) -> str:
    """BTCUSDT aynen; SOL/BTC gibi base-only → SOLUSDT/BTCUSDT. MULTI dokunulmaz."""
    sym = (symbol or "").upper().strip()
    if not sym or sym == "MULTI":
        return sym
    if any(sym.endswith(s) for s in _QUOTE_SUFFIXES):
        return sym
    if _BASE_ONLY_RE.match(sym):
        return sym + "USDT"
    return sym
