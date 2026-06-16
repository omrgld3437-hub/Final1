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
        state = {}
        try:
            from app.botengine.state_store import load_state

            state = load_state(db, bot_id) or {}
        except Exception:
            pass
        start_balance, start_price = _capture_run_baseline_values(
            db, bot, state, raw, is_trdca=is_trdca
        )
        baseline: dict = {"bot0": 0.0, "parite0": 0.0, "ts0": now_sec}
        if start_balance is not None and start_balance > 0:
            baseline["start_balance_usd"] = round(float(start_balance), 2)
        if start_price is not None and start_price > 0:
            baseline["start_coin_price"] = round(float(start_price), 8)

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


def _config_initial_capital(raw: dict) -> float:
    try:
        return float(
            raw.get("initial_capital_usdt")
            or raw.get("budget_usd")
            or raw.get("bot_budget_usdt")
            or raw.get("bot_budget_quote")
            or 0
        )
    except (TypeError, ValueError):
        return 0.0


def compute_alpha_performance_pct(
    start_balance_usd: float,
    start_coin_price: float,
    current_balance_usd: float,
    current_coin_price: float,
) -> dict | None:
    """Bot alpha = bakiye % − coin % (bot başlangıcından itibaren)."""
    if start_balance_usd <= 0 or start_coin_price <= 0:
        return None
    balance_pct = (current_balance_usd - start_balance_usd) / start_balance_usd * 100.0
    coin_pct = (current_coin_price - start_coin_price) / start_coin_price * 100.0
    alpha_pct = balance_pct - coin_pct
    return {
        "start_balance_usd": round(start_balance_usd, 2),
        "start_coin_price": round(start_coin_price, 8),
        "current_balance_usd": round(current_balance_usd, 2),
        "current_coin_price": round(current_coin_price, 8),
        "balance_pct": round(balance_pct, 2),
        "coin_pct": round(coin_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
    }


def build_bot_alpha_performance(
    db: Session,
    bot: Bot,
    state: dict | None,
    *,
    current_usd: float | None = None,
    current_price: float | None = None,
    chart_payload: dict | None = None,
    pnl_data: dict | None = None,
) -> dict | None:
    """
    Run-start baseline'dan bot performansı (alpha) hesapla.
    baseline: bot_perf_chart_state.baseline.start_balance_usd / start_coin_price
    TRDCA: coin_pct = ağırlıklı portföy parite %.
    """
    from app.services.bot_equity import compute_bot_equity_usd, get_bot_last_price

    state = state or {}
    try:
        raw = json.loads(bot.config_json or "{}")
    except Exception:
        raw = {}
    strategy_id = (raw.get("strategy_id") or "").strip().lower()
    is_trdca = strategy_id == "trdca_pro"
    quote_asset = (raw.get("quote_asset") or "USDT").strip().upper()
    initial_capital = _config_initial_capital(raw)

    if pnl_data is None:
        try:
            from app.services.pnl_service import PnlService

            pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id) or {}
        except Exception:
            pnl_data = {}
    if pnl_data.get("error"):
        pnl_data = {}

    if current_usd is None:
        current_usd = compute_bot_equity_usd(
            db, bot, state, pnl_data, initial_usd=initial_capital
        )
    try:
        current_usd = float(current_usd or 0)
    except (TypeError, ValueError):
        current_usd = 0.0

    sym = (bot.symbol or "").strip().upper()
    if current_price is None:
        current_price = get_bot_last_price(sym, state, pnl_data)
    try:
        current_price = float(current_price or 0)
    except (TypeError, ValueError):
        current_price = 0.0

    if chart_payload is None:
        try:
            row = db.execute(
                text(
                    "SELECT chart_payload FROM bot_perf_chart_state WHERE bot_id = :bid"
                ),
                {"bid": bot.id},
            ).fetchone()
            chart_payload = json.loads(row[0]) if row and row[0] else {}
        except Exception:
            chart_payload = {}

    baseline = (chart_payload or {}).get("baseline") or {}
    run_base = (
        state.get("perf_run_baseline")
        if isinstance(state.get("perf_run_baseline"), dict)
        else {}
    )

    start_balance = baseline.get("start_balance_usd")
    if start_balance is None and run_base.get("usd") is not None:
        start_balance = run_base.get("usd")
    try:
        start_balance = float(start_balance or 0)
    except (TypeError, ValueError):
        start_balance = 0.0
    if start_balance <= 0 and initial_capital > 0:
        start_balance = initial_capital

    coin_pct: float | None = None
    if is_trdca:
        initial_prices = baseline.get("initial_prices") or {}
        coin_weights = baseline.get("coin_weights") or {}
        if initial_prices and coin_weights:
            current_prices = _fetch_prices_for_assets(
                list(coin_weights.keys()), quote_asset
            )
            coin_pct = compute_trdca_parite_pct(
                initial_prices, coin_weights, current_prices, quote_asset
            )
        if coin_pct is not None and start_balance > 0 and current_usd >= 0:
            balance_pct = (current_usd - start_balance) / start_balance * 100.0
            return {
                "start_balance_usd": round(start_balance, 2),
                "start_coin_price": None,
                "current_balance_usd": round(current_usd, 2),
                "current_coin_price": round(current_price, 8)
                if current_price > 0
                else None,
                "balance_pct": round(balance_pct, 2),
                "coin_pct": round(float(coin_pct), 2),
                "alpha_pct": round(balance_pct - float(coin_pct), 2),
            }
        return None

    start_price = baseline.get("start_coin_price")
    if start_price is None and run_base.get("price") is not None:
        start_price = run_base.get("price")
    try:
        start_price = float(start_price or 0)
    except (TypeError, ValueError):
        start_price = 0.0
    if start_price <= 0:
        ref = state.get("reference_price")
        try:
            start_price = float(ref or 0)
        except (TypeError, ValueError):
            start_price = 0.0
    if start_price <= 0 and current_price > 0:
        start_price = current_price

    if start_balance <= 0 or start_price <= 0 or current_price <= 0:
        return None
    return compute_alpha_performance_pct(
        start_balance, start_price, current_usd, current_price
    )


def _capture_run_baseline_values(
    db: Session,
    bot: Bot,
    state: dict | None,
    raw: dict,
    *,
    is_trdca: bool,
) -> tuple[float | None, float | None]:
    """Bot start anında equity + coin fiyatı (config fallback)."""
    from app.services.bot_equity import compute_bot_equity_usd, get_bot_last_price

    state = state or {}
    initial_capital = _config_initial_capital(raw)
    pnl_data: dict = {}
    try:
        from app.services.pnl_service import PnlService

        pnl_data = PnlService.calculate_bot_pnl(db, bot.id, bot.account_id) or {}
    except Exception:
        pass
    if pnl_data.get("error"):
        pnl_data = {}

    equity = compute_bot_equity_usd(
        db, bot, state, pnl_data, initial_usd=initial_capital
    )
    start_balance = (
        equity if equity > 0 else (initial_capital if initial_capital > 0 else None)
    )

    start_price = None
    if not is_trdca:
        sym = (bot.symbol or "").strip().upper()
        start_price = get_bot_last_price(sym, state, pnl_data)
        if (start_price is None or start_price <= 0) and state.get("reference_price"):
            try:
                start_price = float(state["reference_price"])
            except (TypeError, ValueError):
                start_price = None

    return start_balance, start_price


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
