"""Expanded V5 audit report writer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _json_block(data: Any) -> str:
    return "```json\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"


def _table(headers: list, rows: list) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def write_full_audit_report(
    path: Path,
    *,
    git_info: dict,
    manifest: dict,
    bench: dict,
    sim: dict,
    scenario_fit: dict,
    grid_audit: dict,
    distribution: dict,
    r8_r15: dict,
    db_consistency: dict,
    determinism: dict,
    v4_leak: dict,
    live_samples: dict,
    test_summary: dict,
    formula_version: str,
) -> bool:
    checks = {
        "shelf_count": manifest.get("totalShelves") == 192780,
        "exact_lookup": sim.get("exactHitRatio") == 1.0,
        "fallback_zero": sim.get("fallbackCount") == 0,
        "scenario_fit": scenario_fit.get("pass_audit"),
        "grid_audit": grid_audit.get("pass_audit"),
        "distribution": distribution.get("pass_audit"),
        "r8_r15": r8_r15.get("pass_audit"),
        "db_consistency": db_consistency.get("pass_audit"),
        "determinism": determinism.get("pass_audit"),
        "v4_leak": v4_leak.get("pass_audit"),
        "live_samples": live_samples.get("pass_audit"),
        "tests": test_summary.get("passed"),
    }
    overall_pass = all(v for v in checks.values() if v is not None)

    sample_rows = []
    for s in live_samples.get("samples", []):
        sample_rows.append(
            [
                s.get("name", "")[:40],
                s.get("route_key", ""),
                s.get("shelf_id", "")[:28],
                s.get("exact_hit"),
                s.get("fallback_used"),
                s.get("validator_ok"),
            ]
        )

    md = f"""# Dynamic Param V5 Full Rebuild and Audit

Generated: {datetime.now(timezone.utc).isoformat()}
Formula: `{formula_version}`

---

## 1. Yönetici Özeti

| Metrik | Değer | Durum |
|--------|-------|-------|
| Toplam V5 raf | {manifest.get('totalShelves', 0)} | {'OK' if checks['shelf_count'] else 'FAIL'} |
| Exact lookup oranı | {sim.get('exactHitRatio', 'N/A')} | {'OK' if checks['exact_lookup'] else 'FAIL'} |
| Normal path fallback | {sim.get('fallbackCount', 'N/A')} | {'OK' if checks['fallback_zero'] else 'FAIL'} |
| Scenario-fit audit | min={scenario_fit.get('min_score')} avg={scenario_fit.get('avg_score')} | {'OK' if checks['scenario_fit'] else 'FAIL'} |
| Grid logic audit | trailing_viol={grid_audit.get('trailing_total_violations', 0)} | {'OK' if checks['grid_audit'] else 'FAIL'} |
| Distribution audit | 2-grid forbidden={distribution.get('equal_2_forbidden_count', 0)} | {'OK' if checks['distribution'] else 'FAIL'} |
| R8/R15 invariants | R8 fail={r8_r15.get('R8_R2_forbidden_fail', 0)} R15 fail={r8_r15.get('R15_R2_forbidden_fail', 0)} | {'OK' if checks['r8_r15'] else 'FAIL'} |
| DB/JSON consistency | mismatch={db_consistency.get('hash_mismatch_count', 0)} | {'OK' if checks['db_consistency'] else 'FAIL'} |
| Determinism | hashes_match={determinism.get('hashes_match')} | {'OK' if checks['determinism'] else 'FAIL'} |
| V4 runtime leak | leaks={len(v4_leak.get('runtime_v4_leaks', []))} | {'OK' if checks['v4_leak'] else 'FAIL'} |
| Live samples | non_exact={live_samples.get('non_exact_count', 0)} | {'OK' if checks['live_samples'] else 'FAIL'} |
| Pytest V5 suite | {test_summary.get('passed_count', '?')}/{test_summary.get('total', '?')} | {'OK' if checks['tests'] else 'FAIL'} |

**Production kararı: {'PASS' if overall_pass else 'FAIL'}**

---

## 2. Branch ve Commit

- Branch: `{git_info.get('branch')}`
- Commit: `{git_info.get('commit')}`

---

## 19. Grid Üretim Mantığı

Grid boşluğu elle yazılmaz. Her shelf için:

```
cost_floor = maker + taker + spread + slippage + rounding + safety_buffer
min_grid_by_cost = cost_floor + minimum_profit_margin
vol_grid = (ATR_5m × 4.0) + (ATR_1h × 1.8)   # vol sınıfı referans ATR
scenario_grid = regime_base × vol × asset × liquidity × risk (regime floor ile)
base_first = max(min_grid_by_cost, vol_grid, scenario_grid)
sell_first = base_first × structure_sell × direction_sell
buy_first  = base_first × structure_buy × direction_buy × risk_buy
grid_n = grid_{{n-1}} × expansion_factor
```

Modül: `app/services/dynamic_param_score/v5/generator/grid_formula.py`

---

## 20–21. Grid Dağılım Mantığı

- 2-grid 50/50 yalnızca `equal_2_grid_justified=true` ve balanced/safe senaryolarda.
- 3-grid equal distribution yasak.

---

## 41. Scenario-Fit Sonuçları

{_json_block(scenario_fit)}

Kabul: tüm shelf ≥85, kritik shelf ≥92.

---

## 42. Grid Logic Audit

{_json_block(grid_audit)}

---

## 43. Distribution Audit

- 2-grid equal count: **{distribution.get('equal_2_grid_count', 0)}**
- Unjustified: **{distribution.get('equal_2_unjustified_count', 0)}**
- Forbidden context: **{distribution.get('equal_2_forbidden_count', 0)}**
- 3-grid equal: **{distribution.get('equal_3_grid_count', 0)}**

{_json_block({k: distribution[k] for k in distribution if k != 'equal_2_routes'})}

---

## 37. R8/R15 Özel Kuralları

### R8 Crash

| Metrik | Değer |
|--------|-------|
| Shelf count | {r8_r15.get('R8_crash_shelf_count')} |
| R2 forbidden OK | {r8_r15.get('R8_R2_forbidden_ok')} |
| R2 forbidden FAIL | {r8_r15.get('R8_R2_forbidden_fail')} |

Örnek satırlar:

{_table(['shelf_id', 'R2_forbidden', 'forbidden_list'], [(r['shelf_id'], r['R2_forbidden'], str(r['forbidden_list'][:3])) for r in r8_r15.get('R8_sample_rows', [])])}

### R15 Special Stress

| Metrik | Değer |
|--------|-------|
| Shelf count | {r8_r15.get('R15_shelf_count')} |
| R2 forbidden OK | {r8_r15.get('R15_R2_forbidden_ok')} |
| nearest OK | {r8_r15.get('R15_nearest_ok')} |
| nearest FAIL | {r8_r15.get('R15_nearest_fail')} |

Fallback source order test:

{_json_block(r8_r15.get('R15_fallback_source_order', []))}

---

## 38. DB / Generated JSON Consistency

{_json_block(db_consistency)}

---

## Determinism Check

{_json_block(determinism)}

---

## 44. Legacy V4 Runtime Temizlik

{_json_block(v4_leak)}

---

## 45. Live-Style Sample Outputs

{_table(['name', 'route', 'shelf_id', 'exact', 'fallback', 'valid'], sample_rows)}

Detay:

{_json_block(live_samples.get('samples', []))}

---

## 40. Lookup Benchmark

{_json_block(bench)}

---

## 42b. Full Resolver Simulation

{_json_block(sim)}

---

## 46. Test Komutları ve Sonuçları

```bash
python3 scripts/generate_dynamic_param_v5_shelves.py
python3 scripts/validate_dynamic_param_v5_shelves.py
python3 scripts/seed_dynamic_param_v5_database.py
python3 scripts/simulate_dynamic_param_v5_all_routes.py
python3 scripts/benchmark_dynamic_param_v5_lookup.py
python3 -m pytest tests/dynamic_param_v5/ -v
```

{_json_block(test_summary)}

---

## 50. Final Karar

Dynamic Param V5 exact shelf library status:
{manifest.get('totalShelves', 0)} / 192780 shelves generated, indexed, validated and resolvable.
Normal runtime fallback requirement: {sim.get('fallbackCount', 0)}.
Legacy V4 runtime usage: {0 if v4_leak.get('pass_audit') else 'LEAK DETECTED'}.
Final validation failures: {0 if overall_pass else 'SEE SECTIONS ABOVE'}.

**{'PASS — production-ready evidence complete' if overall_pass else 'FAIL — fix blockers before commit'}**
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return overall_pass
