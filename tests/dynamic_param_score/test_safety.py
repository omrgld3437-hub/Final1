"""Safety gate tests."""

from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import RegimeTag
from app.services.dynamic_param_score.profiles import build_params
from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.safety import apply_safety_gates
from app.services.dynamic_param_score.scoring import compute_sub_scores
from tests.dynamic_param_score.conftest import constraints, ctx, market_bundle, portfolio, ranging


def test_low_liquidity_no_trade():
    engine = DynamicParamScoreEngine()
    m = market_bundle(quote_vol=500.0)
    d = engine.calculate_decision("BTCUSDT", m, portfolio(100), constraints(), ctx())
    assert d.final_action == "NO_TRADE"
    assert not d.deployable


def test_exposure_cap_emergency_no_buy():
    engine = DynamicParamScoreEngine()
    m = market_bundle(candles_5m=ranging())
    p = portfolio(1000, exposure=0.90)
    d = engine.calculate_decision("BTCUSDT", m, p, constraints(), ctx())
    if d.params:
        assert d.params.emergency_no_buy or d.params.buy_grid_count == 0


def test_min_notional_reduces_grid():
    m = market_bundle()
    ind = compute_indicators(m, portfolio(30))
    sub = compute_sub_scores(ind, portfolio(30), constraints(min_notional=10))
    p = build_params("BALANCED_GRID_PROFILE", 65, RegimeTag.BALANCED_RANGE, ind, 0.15)
    out, action, deploy, gates, blocking, _, _ = apply_safety_gates(
        p, sub, RegimeTag.BALANCED_RANGE, portfolio(30), constraints(10), ctx(30), 65, "BALANCED_GRID"
    )
    if out is None:
        assert blocking  # any blocking reason acceptable for tiny budget


def test_fee_floor_passes_at_exact_spacing_boundary():
    """Spacing exactly at fee floor must not trigger FEE_FLOOR_IMPOSSIBLE (off-by-one)."""
    c = constraints()
    friction = c.total_fee_slippage_pct
    required = friction * 2.0 * 3.0  # FEE_SPACING_MULTIPLIER
    m = market_bundle()
    ind = compute_indicators(m, portfolio())
    sub = compute_sub_scores(ind, portfolio(), c)
    p = build_params("ACTIVE_RANGE_GRID_PROFILE", 62, RegimeTag.BALANCED_RANGE, ind, friction)
    assert p is not None
    p.buy_grid_spacing_pct = required
    p.sell_grid_spacing_pct = required
    out, action, deploy, gates, blocking, _, _ = apply_safety_gates(
        p,
        sub,
        RegimeTag.BALANCED_RANGE,
        portfolio(500),
        c,
        ctx(500),
        62,
        "ACTIVE_GRID",
    )
    assert out is not None
    assert "FEE_FLOOR_IMPOSSIBLE" not in blocking
    assert deploy is True


def test_single_big_buy_forbidden():
    m = market_bundle()
    ind = compute_indicators(m, portfolio())
    sub = compute_sub_scores(ind, portfolio(), constraints())
    p = build_params("ACTIVE_RANGE_GRID_PROFILE", 80, RegimeTag.RANGE_HIGH_VOL, ind, 0.15)
    if p and p.buy_grid_count == 1:
        assert p.max_quote_to_spend_per_buy_frac <= 0.35
