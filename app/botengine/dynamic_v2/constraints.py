"""Projection of raw formula output to the nearest safe parameter package."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from .config import DynamicV2Config
from .math_engine import (
    EPSILON,
    apply_deadband,
    clip,
    limit_relative_change,
    normalize_weights,
)
from .models import (
    DynamicParameterCandidate,
    ONE,
    TurnReferenceParameters,
    ZERO,
)


D = Decimal


def _weighted_isotonic(values: Sequence[Decimal]) -> List[Decimal]:
    """Pool-adjacent-violators projection for non-decreasing values."""
    blocks: List[dict] = []
    for index, value in enumerate(values):
        blocks.append(
            {
                "start": index,
                "end": index,
                "weight": ONE,
                "mean": value,
            }
        )
        while len(blocks) >= 2 and blocks[-2]["mean"] > blocks[-1]["mean"]:
            right = blocks.pop()
            left = blocks.pop()
            weight = left["weight"] + right["weight"]
            blocks.append(
                {
                    "start": left["start"],
                    "end": right["end"],
                    "weight": weight,
                    "mean": (
                        left["mean"] * left["weight"]
                        + right["mean"] * right["weight"]
                    )
                    / weight,
                }
            )
    projected = [ZERO for _ in values]
    for block in blocks:
        for index in range(block["start"], block["end"] + 1):
            projected[index] = block["mean"]
    return projected


def project_distances(
    raw: Sequence[Decimal],
    *,
    minimum_distance: Decimal,
    gap: Decimal,
    maximum_distance: Decimal,
) -> List[Decimal]:
    if not raw:
        return []
    transformed = [
        value - D(index) * gap for index, value in enumerate(raw)
    ]
    lower = minimum_distance
    upper = maximum_distance - D(len(raw) - 1) * gap
    if upper < lower:
        raise ValueError("grid constraints are infeasible")
    bounded = [clip(value, lower, upper) for value in transformed]
    isotonic = _weighted_isotonic(bounded)
    projected = [
        clip(value + D(index) * gap, minimum_distance, maximum_distance)
        for index, value in enumerate(isotonic)
    ]
    return projected


def _limit_series(
    old: Sequence[Decimal],
    new: Sequence[Decimal],
    *,
    deadband: Decimal,
    maximum_change: Decimal,
) -> List[Decimal]:
    """Seriyi eleman bazında sınırla; ``new``'in uzunluğunu asla değiştirme.

    ``zip(old, new)`` kullanılamaz: önceki tur bu turdan az grid içeriyorsa
    (kullanıcı grid ekledi ya da önceki paket kısaydı) sonuç listesi kısalır ve
    aday gridler sessizce yok olur. Eşi olmayan yeni elemanlar kıyaslanacak bir
    geçmişe sahip olmadığı için olduğu gibi bırakılır.
    """
    limited: List[Decimal] = []
    for index, value in enumerate(new):
        if index >= len(old):
            limited.append(value)
            continue
        limited.append(
            limit_relative_change(
                old[index],
                apply_deadband(old[index], value, deadband),
                maximum_change,
            )
        )
    return limited


def project_amount_weights(
    weights: Sequence[Decimal],
    *,
    maximum_single: Decimal,
    maximum_adjacent_ratio: Decimal,
) -> List[Decimal]:
    if not weights:
        return []
    projected = normalize_weights(weights)
    for _ in range(32):
        changed = False
        projected = [
            min(maximum_single, max(value, EPSILON)) for value in projected
        ]
        for index in range(len(projected) - 1):
            left, right = projected[index], projected[index + 1]
            if left > right * maximum_adjacent_ratio:
                projected[index] = right * maximum_adjacent_ratio
                changed = True
            elif right > left * maximum_adjacent_ratio:
                projected[index + 1] = left * maximum_adjacent_ratio
                changed = True
        projected = normalize_weights(projected)
        if max(projected) > maximum_single + EPSILON:
            excess = sum(
                (max(ZERO, value - maximum_single) for value in projected), ZERO
            )
            projected = [min(value, maximum_single) for value in projected]
            receivers = [
                index
                for index, value in enumerate(projected)
                if value < maximum_single
            ]
            if receivers:
                room = sum(
                    (maximum_single - projected[index] for index in receivers), ZERO
                )
                for index in receivers:
                    projected[index] += (
                        excess
                        * (maximum_single - projected[index])
                        / max(room, EPSILON)
                    )
                changed = True
        projected = normalize_weights(projected)
        if not changed:
            break
    if max(projected) > maximum_single + D("0.00000001"):
        raise ValueError("single-grid weight cap is infeasible")
    return projected


class ParameterConstraintProjector:
    def __init__(self, config: DynamicV2Config):
        self.config = config

    def project(
        self,
        candidate: DynamicParameterCandidate,
        reference: TurnReferenceParameters,
        *,
        spread_pct: Decimal,
        atr_pct: Decimal,
        exchange_tick_gap_pct: Decimal,
        current: Optional[DynamicParameterCandidate] = None,
    ) -> DynamicParameterCandidate:
        """Adayı borsa ve güvenlik kısıtlarına yansıt.

        BİRİM SÖZLEŞMESİ: ``spread_pct``, ``atr_pct`` ve
        ``exchange_tick_gap_pct`` **yüzde puanı** cinsindendir (%0.05 → 0.05),
        oran değil. Aynı ölçekteki config sabitleriyle (``absolute_min_gap``,
        ``min_distance``, ``max_grid_distance``) doğrudan karşılaştırıldıkları
        için oran verilirse gridler 100 kat sıkışır. Çağıran service.py
        çevrimi yapar; feature katmanındaki 0..1 normalize ``spread_pct``
        buraya geçirilmemelidir.
        """
        # Churn kontrolleri sert kısıtlardan ÖNCE uygulanır. Sonra uygulanırsa
        # her parametreyi bağımsız olarak kırptığı için hemen üstte kurulan
        # invaryantları (gridlerin artan sıralaması, minimum gap, trailing <
        # tetik) bozabilir ve borsa tarafında reddedilen ya da mantıksız bir
        # paket üretir. Bu sırayla yumuşatma önce olur, sert sınırlar son sözü
        # söyler.
        if current is not None:
            self._apply_churn_controls(candidate, current)
        gap = max(
            self.config.absolute_min_gap,
            spread_pct * self.config.spread_gap_factor,
            atr_pct * self.config.atr_gap_factor,
            exchange_tick_gap_pct,
        )
        candidate.buy_grid_trigger_percentages = project_distances(
            candidate.buy_grid_trigger_percentages,
            minimum_distance=self.config.min_distance,
            gap=gap,
            maximum_distance=self.config.max_grid_distance,
        )
        candidate.sell_grid_trigger_percentages = project_distances(
            candidate.sell_grid_trigger_percentages,
            minimum_distance=self.config.min_distance,
            gap=gap,
            maximum_distance=self.config.max_grid_distance,
        )
        candidate.buy_grid_amount_weights = project_amount_weights(
            candidate.buy_grid_amount_weights,
            maximum_single=max(
                self.config.max_single_buy_grid_weight,
                ONE / D(len(candidate.buy_grid_amount_weights)),
            ),
            maximum_adjacent_ratio=self.config.max_adjacent_amount_ratio,
        )
        candidate.sell_grid_amount_weights = project_amount_weights(
            candidate.sell_grid_amount_weights,
            maximum_single=max(
                self.config.max_single_sell_grid_weight,
                ONE / D(len(candidate.sell_grid_amount_weights)),
            ),
            maximum_adjacent_ratio=self.config.max_adjacent_amount_ratio,
        )
        candidate.buy_grid_trailing_percentage = clip(
            candidate.buy_grid_trailing_percentage,
            max(self.config.min_buy_trailing, spread_pct * D("2.5")),
            min(
                self.config.max_buy_trailing,
                min(candidate.buy_grid_trigger_percentages) * D("0.45"),
            ),
        )
        candidate.sell_grid_trailing_percentage = clip(
            candidate.sell_grid_trailing_percentage,
            max(self.config.min_sell_trailing, spread_pct * D("2.5")),
            min(
                self.config.max_sell_trailing,
                min(candidate.sell_grid_trigger_percentages) * D("0.45"),
            ),
        )
        candidate.profit_buy_trailing_percentage = min(
            candidate.profit_buy_trailing_percentage,
            candidate.profit_buy_trigger_percentage
            * self.config.profit_trailing_trigger_ratio,
        )
        candidate.profit_sell_trailing_percentage = min(
            candidate.profit_sell_trailing_percentage,
            candidate.profit_sell_trigger_percentage
            * self.config.profit_trailing_trigger_ratio,
        )
        candidate.explanations.append(
            f"minimum_grid_gap={format(gap, 'f')}"
        )
        return candidate

    def _apply_churn_controls(
        self,
        candidate: DynamicParameterCandidate,
        current: DynamicParameterCandidate,
    ) -> None:
        base = (
            current.target_base_ratio
            if abs(candidate.target_base_ratio - current.target_base_ratio)
            < self.config.base_deadband
            else clip(
                candidate.target_base_ratio,
                current.target_base_ratio - self.config.hourly_base_change,
                current.target_base_ratio + self.config.hourly_base_change,
            )
        )
        candidate.target_base_ratio = base
        candidate.target_quote_ratio = ONE - base
        candidate.buy_grid_trigger_percentages = _limit_series(
            current.buy_grid_trigger_percentages,
            candidate.buy_grid_trigger_percentages,
            deadband=self.config.relative_trigger_deadband,
            maximum_change=self.config.hourly_trigger_change,
        )
        candidate.sell_grid_trigger_percentages = _limit_series(
            current.sell_grid_trigger_percentages,
            candidate.sell_grid_trigger_percentages,
            deadband=self.config.relative_trigger_deadband,
            maximum_change=self.config.hourly_trigger_change,
        )
        candidate.buy_grid_amount_weights = normalize_weights(
            _limit_series(
                current.buy_grid_amount_weights,
                candidate.buy_grid_amount_weights,
                deadband=self.config.relative_amount_deadband,
                maximum_change=self.config.hourly_amount_change,
            )
        )
        candidate.sell_grid_amount_weights = normalize_weights(
            _limit_series(
                current.sell_grid_amount_weights,
                candidate.sell_grid_amount_weights,
                deadband=self.config.relative_amount_deadband,
                maximum_change=self.config.hourly_amount_change,
            )
        )
        scalar_fields = (
            (
                "buy_grid_trailing_percentage",
                self.config.relative_trailing_deadband,
                self.config.hourly_trailing_change,
            ),
            (
                "sell_grid_trailing_percentage",
                self.config.relative_trailing_deadband,
                self.config.hourly_trailing_change,
            ),
            (
                "profit_buy_trigger_percentage",
                self.config.relative_profit_deadband,
                self.config.hourly_profit_change,
            ),
            (
                "profit_sell_trigger_percentage",
                self.config.relative_profit_deadband,
                self.config.hourly_profit_change,
            ),
            (
                "profit_buy_trailing_percentage",
                self.config.relative_trailing_deadband,
                self.config.hourly_trailing_change,
            ),
            (
                "profit_sell_trailing_percentage",
                self.config.relative_trailing_deadband,
                self.config.hourly_trailing_change,
            ),
        )
        for field_name, deadband, maximum in scalar_fields:
            old = getattr(current, field_name)
            new = getattr(candidate, field_name)
            setattr(
                candidate,
                field_name,
                limit_relative_change(
                    old, apply_deadband(old, new, deadband), maximum
                ),
            )
