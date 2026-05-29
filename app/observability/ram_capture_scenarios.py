"""
RAM capture senaryo tanımları — 6 saatlik yük testi (harici koşucu).

Her senaryo HTTP adımları üretir; sonuçlar logs/ram_scenario_{session}.jsonl dosyasına yazılır.
Bot tick'lerine dokunmaz; yalnızca API/cache yükü simüle eder.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOGS_DIR = _PROJECT_ROOT / "logs"


@dataclass
class ScenarioStep:
    method: str
    path: str
    params: Optional[Dict[str, Any]] = None
    json_body: Optional[Dict[str, Any]] = None
    repeat: int = 1
    label: str = ""


@dataclass
class ScenarioDef:
    id: str
    title: str
    description: str
    steps: List[ScenarioStep] = field(default_factory=list)
    pause_after_sec: float = 2.0


def _p(path: str, account_id: int, bot_id: int) -> str:
    return (
        path.replace("{account_id}", str(account_id))
        .replace("{bot_id}", str(bot_id))
    )


def build_scenario_catalog(account_id: int, bot_id: int) -> List[ScenarioDef]:
    aid, bid = account_id, bot_id
    return [
        ScenarioDef(
            "S00_baseline",
            "Baseline",
            "Yalnızca health / public — düşük yük referansı",
            [
                ScenarioStep("GET", "/api/health", label="health"),
                ScenarioStep("GET", "/api/config/public", label="config_public"),
                ScenarioStep("GET", "/api/health/marketdata", label="health_market"),
            ],
            pause_after_sec=5.0,
        ),
        ScenarioDef(
            "S01_market_public",
            "Market (public)",
            "DataHub okuma — slim + hub + coin-list",
            [
                ScenarioStep("GET", "/api/data/prices", params={"slim": 1}, repeat=3, label="prices_slim"),
                ScenarioStep("GET", "/api/data/prices", repeat=1, label="prices_full"),
                ScenarioStep("GET", "/api/data/hub", label="data_hub"),
                ScenarioStep("GET", "/api/data/coin-list", params={"scope": "usdt"}, label="coin_list"),
                ScenarioStep("GET", "/api/datahub/status", label="datahub_status"),
            ],
        ),
        ScenarioDef(
            "S02_market_stress",
            "Market stress",
            "Ardışık fiyat/hub istekleri (dashboard poll simülasyonu)",
            [
                ScenarioStep("GET", "/api/data/prices", params={"slim": 1}, repeat=8, label="prices_burst"),
                ScenarioStep("GET", "/api/data/hub", repeat=4, label="hub_burst"),
            ],
            pause_after_sec=3.0,
        ),
        ScenarioDef(
            "S03_dashboard_snapshot",
            "Dashboard snapshot",
            "Snapshot alanları — kpis + prices + wallet",
            [
                ScenarioStep(
                    "GET",
                    _p("/api/dashboard/snapshot?account_id={account_id}&fields=prices,kpis", aid, bid),
                    repeat=5,
                    label="snapshot_kpis_prices",
                ),
                ScenarioStep(
                    "GET",
                    _p("/api/dashboard/snapshot?account_id={account_id}&fields=prices,wallet,bots,kpis", aid, bid),
                    repeat=3,
                    label="snapshot_full",
                ),
            ],
        ),
        ScenarioDef(
            "S04_transaction_history",
            "Transaction history",
            "Revision poll + sayfalı liste (sync yok)",
            [
                ScenarioStep(
                    "GET",
                    _p("/api/accounts/{account_id}/transaction-history/revision", aid, bid),
                    repeat=6,
                    label="tx_revision",
                ),
                ScenarioStep(
                    "GET",
                    _p(
                        "/api/accounts/{account_id}/transaction-history?period=weekly&type_filter=buysell&page=1",
                        aid,
                        bid,
                    ),
                    repeat=3,
                    label="tx_list_weekly",
                ),
                ScenarioStep(
                    "GET",
                    _p(
                        "/api/accounts/{account_id}/transaction-history?period=daily&type_filter=buysell&page=1",
                        aid,
                        bid,
                    ),
                    label="tx_list_daily",
                ),
            ],
        ),
        ScenarioDef(
            "S05_bot_engine",
            "Bot engine API",
            "Health, live, perf, events — çalışan bota okuma",
            [
                ScenarioStep("GET", _p("/api/bots-engine/{bot_id}/health", aid, bid), label="bot_health"),
                ScenarioStep("GET", _p("/api/bots-engine/{bot_id}/live", aid, bid), repeat=4, label="bot_live"),
                ScenarioStep(
                    "GET",
                    _p("/api/bots-engine/{bot_id}/performance?period=daily", aid, bid),
                    label="bot_perf_daily",
                ),
                ScenarioStep(
                    "GET",
                    _p("/api/bots-engine/{bot_id}/events?limit=30", aid, bid),
                    label="bot_events",
                ),
            ],
        ),
        ScenarioDef(
            "S06_spot_aux",
            "Spot aux",
            "Fiyat/commission — bot sayfası yan istekleri",
            [
                ScenarioStep("GET", "/api/spot/price", params={"symbol": "BTCUSDT"}, repeat=4, label="spot_price"),
                ScenarioStep("GET", "/api/spot/commission", label="spot_commission"),
            ],
        ),
        ScenarioDef(
            "S07_finance_light",
            "Finance light",
            "Özet endpoint (ağır trades yok)",
            [
                ScenarioStep(
                    "GET",
                    _p("/api/finance/summary?account_id={account_id}", aid, bid),
                    label="finance_summary",
                ),
            ],
        ),
        ScenarioDef(
            "S08_ram_diagnostics",
            "RAM diagnostics",
            "Capture aktifken probe endpoint'leri",
            [
                ScenarioStep("GET", "/api/health/ram", label="health_ram"),
                ScenarioStep("GET", "/api/debug/ram-snapshot", label="debug_ram"),
            ],
        ),
        ScenarioDef(
            "S09_mixed_realistic",
            "Mixed realistic",
            "Tipik kullanıcı 90 sn döngüsü kısaltılmış",
            [
                ScenarioStep("GET", "/api/health", label="health"),
                ScenarioStep(
                    "GET",
                    _p("/api/dashboard/snapshot?account_id={account_id}&fields=prices,kpis", aid, bid),
                    repeat=2,
                    label="snapshot",
                ),
                ScenarioStep("GET", "/api/data/prices", params={"slim": 1}, repeat=2, label="prices"),
                ScenarioStep(
                    "GET",
                    _p("/api/accounts/{account_id}/transaction-history/revision", aid, bid),
                    label="tx_rev",
                ),
                ScenarioStep("GET", _p("/api/bots-engine/{bot_id}/live", aid, bid), label="bot_live"),
            ],
            pause_after_sec=8.0,
        ),
    ]


def scenario_schedule_6h() -> List[str]:
    """6 saat: ~25 dk'da bir tam tur (14 tur), senaryolar dönüşümlü."""
    catalog = [
        "S00_baseline",
        "S01_market_public",
        "S02_market_stress",
        "S03_dashboard_snapshot",
        "S04_transaction_history",
        "S05_bot_engine",
        "S06_spot_aux",
        "S07_finance_light",
        "S08_ram_diagnostics",
        "S09_mixed_realistic",
    ]
    # 6h = 21600s, phase every 25 min = 1500s → ~14 phases
    phases: List[str] = []
    for i in range(14):
        phases.append(catalog[i % len(catalog)])
    return phases


def get_scenario_by_id(scenario_id: str, account_id: int, bot_id: int) -> Optional[ScenarioDef]:
    for s in build_scenario_catalog(account_id, bot_id):
        if s.id == scenario_id:
            return s
    return None


def scenario_log_path(session_id: str) -> Path:
    return _LOGS_DIR / f"ram_scenario_{session_id}.jsonl"


def append_scenario_record(session_id: str, record: Dict[str, Any]) -> None:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", datetime.now(timezone.utc).isoformat())
    record.setdefault("session_id", session_id)
    path = scenario_log_path(session_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
