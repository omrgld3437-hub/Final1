"""
Cüzdan USD değerlemesi — yalnızca market_data (DataHub cache). Binance REST yok.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.market_data import get_price_map_flat


async def build_wallet_price_map(
    balances: List[Dict[str, Any]],
    *,
    testnet: bool = False,
) -> Dict[str, float]:
    """DataHub fiyat haritası; eksik varlıklar 0 USD sayılır (REST tetiklenmez)."""
    _ = testnet  # fiyatlar global cache; testnet ayrımı DataHub ingest'te
    return get_price_map_flat()
