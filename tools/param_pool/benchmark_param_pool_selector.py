"""Benchmark param pool selector performance."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.models import RegimeTag, RiskState, SubScores
from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_ID
from app.services.dynamic_param_score.param_pool.generator import generate_pool
from app.services.dynamic_param_score.param_pool.models import SelectionFeatures
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_SQLITE_PATH,
    load_active_pool,
    query_candidates,
)
from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache
from tests.dynamic_param_score.conftest import constraints, market_bundle, portfolio


def _bench_memory(pool_count: int, iterations: int) -> float:
    clear_pool_cache()
    templates = generate_pool(pool_count)
    from app.services.dynamic_param_score.param_pool import registry

    registry._ACTIVE_VERSION = POOL_VERSION_ID  # noqa: SLF001
    m = market_bundle(symbol="SOLUSDT", price=67.8)
    pf = portfolio(50, 0.44)
    sub = SubScores(
        trend_score=45, volatility_score=40, range_score=44, liquidity_score=78,
        spread_score=95, momentum_score=99, mean_reversion_score=40,
        drawdown_risk_score=36, btc_market_risk_score=55, exposure_safety_score=90,
        fee_efficiency_score=15, data_quality_score=100,
    )
    start = time.perf_counter()
    for _ in range(iterations):
        select_template(61, RegimeTag.BALANCED_RANGE, RiskState.DEFENSIVE.value, sub, __import__(
            "app.services.dynamic_param_score.indicators", fromlist=["compute_indicators"]
        ).compute_indicators(m, pf), pf, constraints(), 50, 5.0)
    return (time.perf_counter() - start) / iterations * 1000


def _bench_sqlite_query(iterations: int) -> float:
    if not DEFAULT_SQLITE_PATH.exists():
        return -1.0
    pool = load_active_pool(POOL_VERSION_ID, memory_index_mode=True)
    features = SelectionFeatures(
        param_score=61,
        regime=RegimeTag.BALANCED_RANGE.value,
        risk_state=RiskState.DEFENSIVE.value,
        budget_tier="SMALL",
        exposure_tier="TARGET_BASE",
        headroom_tier="NO_HEADROOM",
        fee_tier="FEE_BAD",
    )
    start = time.perf_counter()
    for _ in range(iterations):
        query_candidates(pool, features, mode="memory_index_mode")
    return (time.perf_counter() - start) / iterations * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark param pool selector")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--pool-count", type=int, default=50_000)
    args = parser.parse_args()

    mem_ms = _bench_memory(args.pool_count, args.iterations)
    sqlite_ms = _bench_sqlite_query(args.iterations)

    print(f"select_template avg: {mem_ms:.2f} ms ({args.pool_count} templates, {args.iterations} iter)")
    if sqlite_ms >= 0:
        print(f"query_candidates memory_index avg: {sqlite_ms:.2f} ms")
    else:
        print("query_candidates: SQLite pool not built yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
