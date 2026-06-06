"""
Bot performans grafiği state: bot başladığında sıfırlama (seed).
API ve orchestrator tarafından kullanılır; döngüsel import önlenir.
TRDCA: Rebalance portföyündeki coinlerin ilk fiyatları referans; ağırlıklı ortalama % değişim = parite.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.models import Bot

logger = logging.getLogger(__name__)
BINANCE_PUBLIC = "https://api.binance.com"


def _fetch_prices_for_assets(assets: list, quote_asset: str = "USDT") -> dict:
    """DataHub cache only. No per-symbol Binance REST."""
    out = {}
    try:
        from app.services.data_hub import data_hub

        for a in assets:
            if a == quote_asset:
                out[a] = 1.0
                continue
            sym = f"{a}{quote_asset}"
            p = data_hub.get_price(sym.upper())
            if p is not None and float(p) > 0:
                out[a] = float(p)
    except Exception:
        pass
    return out


def seed_perf_chart_state_on_bot_start(db: Session, bot_id: int) -> None:
    """Bot başladığında grafik state'ini tohumla (baseline + boş samples).
    TRDCA: Portföy coinlerinin ilk fiyatlarını ve ağırlıklarını baseline'a kaydet."""
    try:
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot:
            return
        raw = json.loads(bot.config_json or "{}")
        strategy_id = (raw.get("strategy_id") or "").strip().lower()
        is_trdca = strategy_id == "trdca_pro"
        quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()

        now_sec = int(datetime.now(timezone.utc).timestamp())
        baseline = {"bot0": 0.0, "parite0": 0.0, "ts0": now_sec}

        if is_trdca:
            target_weights = (
                (raw.get("trb") or {}).get("target_weights_all")
                or (raw.get("dca") or {}).get("coin_weights")
                or {}
            )
            if not target_weights and raw.get("assets"):
                for a in raw["assets"]:
                    sym = (
                        (a.get("symbol") or "")
                        .upper()
                        .replace("USDT", "")
                        .replace("FDUSD", "")
                        .strip()
                    )
                    if sym:
                        target_weights[sym] = float(a.get("target_pct") or 0) / 100.0
            base_assets = [
                a for a in target_weights if a and str(a).strip().upper() != quote_asset
            ]
            if base_assets:
                initial_prices = _fetch_prices_for_assets(base_assets, quote_asset)
                weights = {}
                total_w = sum(float(target_weights.get(a) or 0) for a in base_assets)
                if total_w > 0:
                    for a in base_assets:
                        weights[a] = float(target_weights.get(a) or 0) / total_w
                if initial_prices and weights:
                    baseline["initial_prices"] = initial_prices
                    baseline["coin_weights"] = weights

        payload = {
            "baseline": baseline,
            "samples": [],
            "range": "4h",
        }
        now = datetime.utcnow()
        db.execute(
            text("""
                INSERT INTO bot_perf_chart_state (bot_id, chart_payload, updated_at)
                VALUES (:bid, :payload, :upd)
                ON CONFLICT(bot_id) DO UPDATE SET chart_payload = :payload, updated_at = :upd
            """),
            {
                "bid": bot_id,
                "payload": json.dumps(payload, ensure_ascii=False),
                "upd": now,
            },
        )
        db.commit()
        logger.info(
            "BOT_PERF_CHART_SEEDED bot_id=%s baseline_ts0=%s trdca=%s",
            bot_id,
            now_sec,
            is_trdca,
        )
    except Exception as e:
        logger.debug("seed_perf_chart_state_on_bot_start bot_id=%s: %s", bot_id, e)
        try:
            db.rollback()
        except Exception:
            pass


def compute_trdca_parite_pct(
    initial_prices: dict,
    coin_weights: dict,
    current_prices: dict,
    quote_asset: str = "USDT",
) -> float | None:
    """
    TRDCA parite % = coinlerin ağırlıklı ortalama % değişimi.
    Parite % = Σ (weight_i × (current_i - initial_i) / initial_i × 100)
    """
    if not initial_prices or not coin_weights or not current_prices:
        return None
    total = 0.0
    for asset, w in coin_weights.items():
        if asset == quote_asset:
            continue
        init_p = initial_prices.get(asset)
        curr_p = current_prices.get(asset)
        if init_p is None or curr_p is None or init_p <= 0:
            continue
        pct = (curr_p - init_p) / init_p * 100.0
        total += float(w) * pct
    return total
