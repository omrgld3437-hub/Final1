"""Human-readable V6 profile IDs — spec §20."""

from __future__ import annotations

from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile


def build_profile_ids(
    profile: V6CatalogProfile,
    adjuster_tags: list[str],
) -> tuple[str, str, str]:
    s = profile.scenario
    catalog_id = (
        f"DPLV6_{s.regime_id}-{s.sub_id}-{s.micro_id}_{s.behavior_id}_{s.severity}"
    )
    adj_suffix = "_".join(adjuster_tags[:8]) if adjuster_tags else "NONE"
    final_id = f"{catalog_id}__ADJ_{adj_suffix}_FINAL"
    ba = f"BA{profile.base_allocation_pct:02d}"
    qa = f"QA{profile.quote_allocation_pct:02d}"
    nb = f"NB{len(profile.buy_grids)}"
    bg = "".join(
        f"BG{abs(g.distance_pct)}-Q{g.amount_pct}" for g in profile.buy_grids
    )
    sg = "".join(
        f"G{g.distance_pct}-Q{g.amount_pct}" for g in profile.sell_grids
    )
    full = (
        f"{catalog_id}_{ba}_{qa}_{nb}_{bg}_BT{profile.buy_trailing_code}"
        f"_SG{len(profile.sell_grids)}_{sg}_ST{profile.sell_trailing_code}"
        f"_KA{profile.buyback_trigger_code}_KS{profile.profit_sell_trigger_code}"
    )
    return catalog_id, final_id, full
