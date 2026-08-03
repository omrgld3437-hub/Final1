"""End-to-end Dynamic Mode V2 analysis service."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from .budget import PortfolioBudgetEngine
from .collector import (
    FeatureSnapshotBuilder,
    MarketDataCollector,
    TIMEFRAME_LIMITS,
)
from .config import DynamicV2Config
from .constraints import ParameterConstraintProjector
from .formula import DynamicFormulaEngine, FormulaCoefficientRepository
from .grid_update import (
    EligibleGridResolver,
    ExchangeReconciliationEngine,
    GridUpdateCoordinator,
)
from .learning import AuditLogEngine, DynamicModeUIAdapter, ShadowEvaluationEngine
from .market import MarketDataQualityEngine, MarketStateEngine
from .models import (
    BalanceSnapshot,
    DynamicParameterCandidate,
    TurnReferenceParameters,
    ZERO,
    decimal_value,
    utc_now,
)
from .scheduler import DynamicModeScheduler
from .validation import ParameterValidationEngine
from .persistence import DynamicV2AuditRepository


D = Decimal


class DynamicModeV2:
    def __init__(
        self,
        config: Optional[DynamicV2Config] = None,
        coefficient_repository: Optional[FormulaCoefficientRepository] = None,
        collector: Optional[MarketDataCollector] = None,
    ):
        self.config = config or DynamicV2Config()
        self.coefficients = coefficient_repository or FormulaCoefficientRepository()
        champion = self.coefficients.get_champion()
        self.collector = collector or MarketDataCollector()
        self.quality = MarketDataQualityEngine(self.config)
        self.features = FeatureSnapshotBuilder()
        self.market_state = MarketStateEngine(champion)
        self.formulas = DynamicFormulaEngine(self.config, champion)
        self.projector = ParameterConstraintProjector(self.config)
        self.validator = ParameterValidationEngine(self.config)
        self.resolver = EligibleGridResolver()
        self.budgets = PortfolioBudgetEngine(self.config)
        self.reconciliation = ExchangeReconciliationEngine()
        self.coordinator = GridUpdateCoordinator(self.resolver)
        self.scheduler = DynamicModeScheduler(self.config)
        self.shadow = ShadowEvaluationEngine()
        self.audit = AuditLogEngine()
        self.ui = DynamicModeUIAdapter()

    @staticmethod
    def _d(value: Any, default: str = "0") -> Decimal:
        try:
            return decimal_value(value)
        except ValueError:
            return D(default)

    # Churn kontrollerini kapatmak için acil çıkış. Üretimde beklenmeyen bir
    # yumuşatma davranışı görülürse kod değişikliği olmadan devre dışı bırakılır.
    @staticmethod
    def _churn_controls_enabled() -> bool:
        import os

        return os.getenv("DYNAMIC_V2_CHURN_CONTROLS", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )

    def previous_applied_candidate(
        self, state: Mapping[str, Any]
    ) -> Optional[DynamicParameterCandidate]:
        """Son GERÇEKTEN uygulanmış adayı geri oku; yoksa None.

        Churn kontrolleri (saatlik değişim limitleri + deadband'ler) bir
        karşılaştırma noktası gerektirir. Referans olarak yalnızca ``APPLIED``
        kararı kullanılır: shadow modda hiçbir şey canlıya geçmediği için gölge
        adaya göre kısıtlamak, gerçekte var olmayan bir geçmişe göre yumuşatma
        yapmak olurdu. Böylece shadow modda davranış birebir korunur.

        Herhangi bir alan eksik/bozuksa None döner ve churn kontrolleri o tur
        atlanır; yarım okunmuş bir geçmişe göre kırpmak sessizce yanlış
        parametre üretmekten daha kötüdür.
        """
        if not self._churn_controls_enabled():
            return None
        raw = state.get("_dynamic_v2_last_applied_candidate")
        if not isinstance(raw, Mapping):
            # Geriye dönük uyum: bu anahtar eklenmeden önce uygulanmış botlarda
            # snapshot hâlâ APPLIED kararını taşıyor olabilir.
            snapshot = state.get("dynamic_v2_snapshot")
            if not isinstance(snapshot, Mapping):
                return None
            if str(snapshot.get("decision") or "").upper() != "APPLIED":
                return None
            raw = snapshot.get("candidate")
            if not isinstance(raw, Mapping):
                return None
        try:
            return self._candidate_from_dict(raw)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            return None

    def _candidate_from_dict(
        self, raw: Mapping[str, Any]
    ) -> Optional[DynamicParameterCandidate]:
        """Snapshot sözlüğünden churn karşılaştırması için aday kur.

        Yalnızca ``_apply_churn_controls``'un okuduğu alanlar gerekir. Bir
        skaler alan eksikse geçmiş güvenilir değildir → None.
        """
        scalars = (
            "target_base_ratio",
            "buy_grid_trailing_percentage",
            "sell_grid_trailing_percentage",
            "profit_buy_trigger_percentage",
            "profit_sell_trigger_percentage",
            "profit_buy_trailing_percentage",
            "profit_sell_trailing_percentage",
        )
        values: Dict[str, Decimal] = {}
        for name in scalars:
            if raw.get(name) is None:
                return None
            values[name] = decimal_value(raw[name])

        def series(name: str) -> list:
            items = raw.get(name)
            if not isinstance(items, (list, tuple)):
                return []
            return [decimal_value(item) for item in items]

        base = values["target_base_ratio"]
        return DynamicParameterCandidate(
            target_base_ratio=base,
            target_quote_ratio=D("1") - base,
            buy_grid_trigger_percentages=series("buy_grid_trigger_percentages"),
            sell_grid_trigger_percentages=series("sell_grid_trigger_percentages"),
            buy_grid_amount_weights=series("buy_grid_amount_weights"),
            sell_grid_amount_weights=series("sell_grid_amount_weights"),
            buy_grid_amounts=series("buy_grid_amounts"),
            sell_grid_amounts=series("sell_grid_amounts"),
            buy_grid_trailing_percentage=values["buy_grid_trailing_percentage"],
            sell_grid_trailing_percentage=values["sell_grid_trailing_percentage"],
            profit_buy_trigger_percentage=values["profit_buy_trigger_percentage"],
            profit_sell_trigger_percentage=values["profit_sell_trigger_percentage"],
            profit_buy_trailing_percentage=values["profit_buy_trailing_percentage"],
            profit_sell_trailing_percentage=values["profit_sell_trailing_percentage"],
            confidence=self._d(raw.get("confidence"), "0"),
        )

    def capture_reference(
        self,
        state: Dict[str, Any],
        raw_config: Mapping[str, Any],
    ) -> TurnReferenceParameters:
        current_cycle = int(state.get("cycle_id") or 1)
        stored = state.get("_dynamic_v2_reference")
        if (
            isinstance(stored, Mapping)
            and int(stored.get("cycle_id") or 0) == current_cycle
        ):
            return self._reference_from_dict(stored["parameters"])

        buy_grids = list(raw_config.get("buy_grids") or [])
        sell_grids = list(raw_config.get("sell_grids") or [])
        base_ratio = self._d(raw_config.get("base_alloc_pct"), "50") / D("100")
        quote_ratio = D("1") - base_ratio
        buy_reference_balance = self._d(
            state.get("grid_reference_quote")
            or state.get("quote_balance")
        )
        sell_reference_balance = self._d(
            state.get("grid_reference_base")
            or state.get("base_balance")
        )
        anchor = self._d(
            state.get("initial_reference_price")
            or state.get("reference_price")
        )
        reference = TurnReferenceParameters(
            target_base_ratio=base_ratio,
            target_quote_ratio=quote_ratio,
            buy_grid_trigger_percentages=[
                self._d(
                    grid.get("buy_grid_pct", grid.get("trigger_pct"))
                )
                for grid in buy_grids
            ],
            sell_grid_trigger_percentages=[
                self._d(
                    grid.get("sell_grid_pct", grid.get("trigger_pct"))
                )
                for grid in sell_grids
            ],
            buy_grid_amounts=[
                buy_reference_balance
                * self._d(
                    grid.get(
                        "buy_qty_pct_of_quote", grid.get("qty_pct")
                    )
                )
                / D("100")
                for grid in buy_grids
            ],
            sell_grid_amounts=[
                sell_reference_balance
                * self._d(
                    grid.get(
                        "sell_qty_pct_of_base", grid.get("qty_pct")
                    )
                )
                / D("100")
                for grid in sell_grids
            ],
            buy_grid_trailing_percentage=self._d(
                raw_config.get("buy_trigger_trailing_pct"), "0.3"
            ),
            sell_grid_trailing_percentage=self._d(
                raw_config.get("sell_trigger_trailing_pct"), "0.3"
            ),
            profit_buy_trigger_percentage=self._d(
                raw_config.get("profit_reentry_drop_pct"), "1"
            ),
            profit_sell_trigger_percentage=self._d(
                raw_config.get("profit_exit_rise_pct"), "1"
            ),
            profit_buy_trailing_percentage=self._d(
                raw_config.get("profit_reentry_rise_pct"), "0.3"
            ),
            profit_sell_trailing_percentage=self._d(
                raw_config.get("profit_exit_drop_pct"), "0.3"
            ),
            buy_anchor_price=anchor,
            sell_anchor_price=anchor,
            created_at=utc_now(),
            formula_version=self.coefficients.get_champion().version,
        )
        state["_dynamic_v2_reference"] = {
            "cycle_id": current_cycle,
            "parameters": reference.to_dict(),
        }
        return reference

    def _reference_from_dict(
        self, value: Mapping[str, Any]
    ) -> TurnReferenceParameters:
        created = datetime.fromisoformat(
            str(value["created_at"]).replace("Z", "+00:00")
        )
        return TurnReferenceParameters(
            target_base_ratio=self._d(value["target_base_ratio"]),
            target_quote_ratio=self._d(value["target_quote_ratio"]),
            buy_grid_trigger_percentages=[
                self._d(x)
                for x in value["buy_grid_trigger_percentages"]
            ],
            sell_grid_trigger_percentages=[
                self._d(x)
                for x in value["sell_grid_trigger_percentages"]
            ],
            buy_grid_amounts=[
                self._d(x) for x in value["buy_grid_amounts"]
            ],
            sell_grid_amounts=[
                self._d(x) for x in value["sell_grid_amounts"]
            ],
            buy_grid_trailing_percentage=self._d(
                value["buy_grid_trailing_percentage"]
            ),
            sell_grid_trailing_percentage=self._d(
                value["sell_grid_trailing_percentage"]
            ),
            profit_buy_trigger_percentage=self._d(
                value["profit_buy_trigger_percentage"]
            ),
            profit_sell_trigger_percentage=self._d(
                value["profit_sell_trigger_percentage"]
            ),
            profit_buy_trailing_percentage=self._d(
                value["profit_buy_trailing_percentage"]
            ),
            profit_sell_trailing_percentage=self._d(
                value["profit_sell_trailing_percentage"]
            ),
            buy_anchor_price=self._d(value["buy_anchor_price"]),
            sell_anchor_price=self._d(value["sell_anchor_price"]),
            reference_buy_utilization=self._d(
                value.get("reference_buy_utilization"), "1"
            ),
            reference_sell_utilization=self._d(
                value.get("reference_sell_utilization"), "1"
            ),
            created_at=created,
            source=str(value.get("source") or "parameter_assistant"),
            formula_version=str(
                value.get("formula_version") or "dynamic-v2.0.0"
            ),
        )

    @staticmethod
    def _balance_snapshot(
        state: Mapping[str, Any],
        mid_price: Decimal,
        balance_limits: Optional[Mapping[str, Any]] = None,
    ) -> BalanceSnapshot:
        limits = dict(balance_limits or {})
        virtual_base = decimal_value(state.get("base_balance") or 0)
        virtual_quote = decimal_value(state.get("quote_balance") or 0)
        free_base = virtual_base
        free_quote = virtual_quote
        if limits.get("free_base") is not None:
            free_base = min(
                virtual_base, decimal_value(limits.get("free_base"))
            )
        if limits.get("free_quote") is not None:
            free_quote = min(
                virtual_quote, decimal_value(limits.get("free_quote"))
            )
        return BalanceSnapshot(
            free_base=free_base,
            locked_base=decimal_value(state.get("locked_base_balance") or 0),
            free_quote=free_quote,
            locked_quote=decimal_value(state.get("locked_quote_balance") or 0),
            mid_price=mid_price,
            snapshot_id=str(
                limits.get("snapshot_id")
                or state.get("balance_snapshot_id")
                or f"state-{int(state.get('state_version') or 0)}"
            ),
            observed_at=utc_now(),
        )

    async def analyze(
        self,
        state: Dict[str, Any],
        raw_config: Mapping[str, Any],
        *,
        exchange_filters: Optional[Mapping[str, Any]] = None,
        balance_limits: Optional[Mapping[str, Any]] = None,
        unresolved_intents: Sequence[Mapping[str, Any]] = (),
        pre_apply_check: Optional[
            Callable[[], Awaitable[Tuple[bool, Sequence[str]]]]
        ] = None,
        force_shadow: Optional[bool] = None,
        db: Any = None,
    ) -> Dict[str, Any]:
        symbol = str(raw_config.get("symbol") or state.get("symbol") or "").upper()
        reference = self.capture_reference(state, raw_config)
        data = await self.collector.collect(symbol)
        expected = {key: limit for key, (_, limit) in TIMEFRAME_LIMITS.items()}
        max_age = {
            "1M": 5356800,
            "1W": 1209600,
            "1D": 172800,
            "4H": 28800,
            "1H": 7200,
            "15M": 1800,
        }
        quality = self.quality.evaluate(
            candles_by_timeframe=data.candles_by_timeframe,
            expected_counts=expected,
            max_age_seconds=max_age,
            ticker_price=data.mid_price,
            best_bid=data.best_bid,
            best_ask=data.best_ask,
            exchange_connected=data.exchange_connected,
            now=data.collected_at,
        )
        runtime = state.setdefault("dynamic_v2_runtime", {})
        runtime["last_analysis_at"] = utc_now().isoformat()
        schedule = self.scheduler.decide(runtime)
        runtime["next_analysis_at"] = schedule.next_full_analysis_at.isoformat()
        if quality.score < self.config.data_quality_limited:
            state["dynamic_v2_snapshot"] = {
                "decision": "REJECTED_DATA_QUALITY",
                "data_quality": quality.to_dict(),
                "next_analysis_at": runtime["next_analysis_at"],
                "applied": copy.deepcopy(
                    (state.get("dynamic_v2_snapshot") or {}).get("applied")
                    or dict(raw_config)
                ),
            }
            if db is not None:
                self._persist_snapshot(
                    db,
                    state,
                    raw_config,
                    reference,
                    state["dynamic_v2_snapshot"],
                )
            return state["dynamic_v2_snapshot"]

        feature_snapshot = self.features.build(
            data, data_quality=quality.score
        )
        continuous_state = self.market_state.build(
            feature_snapshot,
            previous_coin_risk=self._d(
                runtime.get("coin_risk"), "0.5"
            ),
            regime_stability=self._d(
                runtime.get("regime_stability"), "1"
            ),
            change_intensity=self._d(
                runtime.get("change_intensity"), "0"
            ),
        )
        runtime["coin_risk"] = format(continuous_state.coin_risk, "f")
        state_version = int(state.get("state_version") or 0)
        candidate = self.formulas.build_candidate(
            reference,
            continuous_state,
            state_version=state_version,
        )
        spread_percentage_points = data.raw_spread_pct * D("100")
        atr_percentage_points = feature_snapshot.atr_pct * D("100")
        filters = dict(exchange_filters or {})
        tick_size = self._d(filters.get("tick_size"), "0.00000001")
        tick_gap_pct = (
            tick_size / data.mid_price * D("100")
            if data.mid_price > ZERO
            else D("100")
        )
        self.projector.project(
            candidate,
            reference,
            spread_pct=spread_percentage_points,
            atr_pct=atr_percentage_points,
            exchange_tick_gap_pct=tick_gap_pct,
            # Saatlik değişim limitleri ve deadband'ler yalnızca bir önceki
            # uygulanmış paket varsa devreye girer. Bu argüman geçirilmediği
            # sürece config'te tanımlı tüm churn limitleri ölüydü: her tam
            # analiz parametreleri sınırsız oynatabiliyordu.
            current=self.previous_applied_candidate(state),
        )
        balances = self._balance_snapshot(
            state, data.mid_price, balance_limits
        )
        buy_grids, sell_grids = self.resolver.resolve(state, raw_config)
        for grid in buy_grids:
            if grid.status.value != "WAITING_UNTRIGGERED":
                candidate.buy_grid_trigger_percentages[
                    grid.index
                ] = grid.trigger_percentage
        for grid in sell_grids:
            if grid.status.value != "WAITING_UNTRIGGERED":
                candidate.sell_grid_trigger_percentages[
                    grid.index
                ] = grid.trigger_percentage
        buy_ledger, sell_ledger = self.budgets.allocate(
            candidate,
            reference,
            continuous_state,
            balances,
            buy_grids,
            sell_grids,
            reference_portfolio_value=self._d(
                state.get("cycle_start_equity")
            ),
        )
        buy_fee = self._d(
            filters.get("buy_fee_rate", raw_config.get("buy_fee_rate")),
            "0.001",
        )
        sell_fee = self._d(
            filters.get("sell_fee_rate", raw_config.get("sell_fee_rate")),
            "0.001",
        )
        minimum_profit = self.validator.minimum_profit_trigger(
            buy_fee,
            sell_fee,
            data.estimated_buy_slippage_pct,
            data.estimated_sell_slippage_pct,
            self.config.profit_safety_margin,
        ) * D("100")
        candidate.profit_buy_trigger_percentage = max(
            candidate.profit_buy_trigger_percentage, minimum_profit
        )
        candidate.profit_sell_trigger_percentage = max(
            candidate.profit_sell_trigger_percentage, minimum_profit
        )
        minimum_gap = max(
            self.config.absolute_min_gap,
            spread_percentage_points * self.config.spread_gap_factor,
            atr_percentage_points * self.config.atr_gap_factor,
            tick_gap_pct,
        )
        self.validator.validate(
            candidate,
            reference,
            balances,
            buy_grids,
            sell_grids,
            data_quality=quality.score,
            exchange_connected=data.exchange_connected,
            symbol_trading=bool(filters.get("symbol_trading", True)),
            min_notional=self._d(
                filters.get(
                    "min_notional",
                    raw_config.get("min_notional_guard"),
                ),
                "5",
            ),
            min_qty=self._d(filters.get("min_qty"), "0"),
            max_qty=(
                self._d(filters["max_qty"])
                if filters.get("max_qty") is not None
                else None
            ),
            tick_size=tick_size,
            step_size=self._d(filters.get("step_size"), "0.00000001"),
            buy_fee_rate=buy_fee,
            sell_fee_rate=sell_fee,
            expected_buy_slippage_rate=data.estimated_buy_slippage_pct,
            expected_sell_slippage_rate=data.estimated_sell_slippage_pct,
            minimum_gap=minimum_gap,
        )
        reconciliation_ok, reconciliation_reasons = self.reconciliation.check(
            exchange_connected=data.exchange_connected,
            unresolved_intents=unresolved_intents,
        )
        if pre_apply_check is not None:
            try:
                latest_ok, latest_reasons = await pre_apply_check()
            except Exception:
                latest_ok = False
                latest_reasons = ("PRE_APPLY_CHECK_FAILED",)
            if not latest_ok:
                reconciliation_ok = False
            for reason in latest_reasons:
                if reason not in reconciliation_reasons:
                    reconciliation_reasons.append(str(reason))
        shadow_mode = (
            self.config.shadow_mode
            if force_shadow is None
            else bool(force_shadow)
        )
        if shadow_mode or not candidate.validation_result.valid:
            state["dynamic_v2_snapshot"] = {
                "decision": (
                    "SHADOW"
                    if candidate.validation_result.valid
                    else "REJECTED_VALIDATION"
                ),
                "candidate": candidate.to_dict(),
                "market_state": continuous_state.to_dict(),
                "data_quality": quality.to_dict(),
                "buy_budget_ledger": buy_ledger.to_dict(),
                "sell_budget_ledger": sell_ledger.to_dict(),
                "reconciliation_reasons": reconciliation_reasons,
                "next_analysis_at": runtime["next_analysis_at"],
                "applied": copy.deepcopy(
                    (state.get("dynamic_v2_snapshot") or {}).get("applied")
                    or dict(raw_config)
                ),
            }
            if db is not None:
                self._persist_snapshot(
                    db,
                    state,
                    raw_config,
                    reference,
                    state["dynamic_v2_snapshot"],
                )
            return state["dynamic_v2_snapshot"]

        update = self.coordinator.apply(
            state,
            raw_config,
            candidate,
            expected_state_version=state_version,
            reconciliation_ok=reconciliation_ok,
        )
        snapshot = state.get("dynamic_v2_snapshot") or {}
        snapshot.update(
            {
                "decision": "APPLIED" if update.get("applied") else "REJECTED",
                "market_state": continuous_state.to_dict(),
                "data_quality": quality.to_dict(),
                "buy_budget_ledger": buy_ledger.to_dict(),
                "sell_budget_ledger": sell_ledger.to_dict(),
                "reconciliation_reasons": reconciliation_reasons,
                "next_analysis_at": runtime["next_analysis_at"],
            }
        )
        state["dynamic_v2_snapshot"] = snapshot
        if db is not None:
            self._persist_snapshot(
                db, state, raw_config, reference, snapshot
            )
        return snapshot

    def _persist_snapshot(
        self,
        db: Any,
        state: Mapping[str, Any],
        raw_config: Mapping[str, Any],
        reference: TurnReferenceParameters,
        snapshot: Mapping[str, Any],
    ) -> None:
        candidate = snapshot.get("candidate") or {}
        analysis_id = str(
            candidate.get("analysis_run_id")
            or f"quality-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        )
        decision_id = str(
            candidate.get("decision_id") or f"{analysis_id}-decision"
        )
        idempotency_key = str(
            candidate.get("idempotency_key")
            or f"{analysis_id}:{int(state.get('state_version') or 0)}"
        )
        repository = DynamicV2AuditRepository(db)
        formula_id = repository.ensure_champion(
            self.coefficients.get_champion(), self.config
        )
        repository.record_analysis(
            analysis_run_id=analysis_id,
            decision_id=decision_id,
            idempotency_key=idempotency_key,
            state_version=int(state.get("state_version") or 0),
            symbol=str(raw_config.get("symbol") or state.get("symbol") or ""),
            turn_id=int(state.get("cycle_id") or 1),
            formula_version_id=formula_id,
            data_quality_score=(
                (snapshot.get("data_quality") or {}).get("score") or "0"
            ),
            market_state=snapshot.get("market_state") or {},
            reference_parameters=reference.to_dict(),
            previous_parameters=raw_config,
            candidate_parameters=candidate,
            applied_parameters=snapshot.get("applied") or {},
            eligible_grid_ids=snapshot.get("eligible_grid_ids") or [],
            protected_grid_ids=snapshot.get("protected_grid_ids") or [],
            decision=str(snapshot.get("decision") or "UNKNOWN"),
            rejection_reasons=(
                (candidate.get("validation_result") or {}).get("errors")
                or snapshot.get("reconciliation_reasons")
                or []
            ),
            next_analysis_at=snapshot.get("next_analysis_at"),
        )
