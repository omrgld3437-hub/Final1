"""SQLite-backed param pool store with optional in-memory index mode."""

from __future__ import annotations

import json
import pickle
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.dynamic_param_score.param_pool.manifest import ParamPoolManifest, build_manifest, read_manifest
from app.services.dynamic_param_score.param_pool.models import ParamTemplate, SelectionFeatures

DEFAULT_POOL_DIR = Path(__file__).resolve().parents[4] / "data" / "param_pool" / "v1"
DEFAULT_SQLITE_PATH = DEFAULT_POOL_DIR / "param_pool_v1.sqlite"
DEFAULT_MANIFEST_PATH = DEFAULT_POOL_DIR / "param_pool_v1.manifest.json"
DEFAULT_V2_POOL_DIR = Path(__file__).resolve().parents[4] / "data" / "param_pool" / "v2"
DEFAULT_V2_SQLITE_PATH = DEFAULT_V2_POOL_DIR / "param_pool_v2.sqlite"
DEFAULT_V2_MANIFEST_PATH = DEFAULT_V2_POOL_DIR / "param_pool_v2.manifest.json"
DEFAULT_V3_POOL_DIR = Path(__file__).resolve().parents[4] / "data" / "param_pool" / "v3"
DEFAULT_V3_SQLITE_PATH = DEFAULT_V3_POOL_DIR / "param_pool_v3.sqlite"
DEFAULT_V3_JSONL_PATH = DEFAULT_V3_POOL_DIR / "param_pool_v3.jsonl"
DEFAULT_V3_MANIFEST_PATH = DEFAULT_V3_POOL_DIR / "param_pool_v3.manifest.json"

DEFAULT_V4_POOL_DIR = Path(__file__).resolve().parents[4] / "data" / "param_pool" / "v4"
DEFAULT_V4_SQLITE_PATH = DEFAULT_V4_POOL_DIR / "param_pool_v4.sqlite"
DEFAULT_V4_JSONL_PATH = DEFAULT_V4_POOL_DIR / "param_pool_v4.jsonl"
DEFAULT_V4_MANIFEST_PATH = DEFAULT_V4_POOL_DIR / "param_pool_v4.manifest.json"
DEFAULT_V4_SELECTION_INDEX_PATH = DEFAULT_V4_POOL_DIR / "param_pool_v4.selection_index.json"

_ROUTE_INDEX_DISK_CACHE: Dict[str, Dict[str, List[str]]] = {}


def selection_index_path_for_version(version_id: str) -> Path:
    from app.services.dynamic_param_score.param_pool.defaults import POOL_VERSION_V3, POOL_VERSION_V4

    if version_id == POOL_VERSION_V4:
        return DEFAULT_V4_SELECTION_INDEX_PATH
    if version_id == POOL_VERSION_V3:
        return DEFAULT_V3_POOL_DIR / "param_pool_v3.selection_index.json"
    return DEFAULT_V4_SELECTION_INDEX_PATH


def load_route_index_map(version_id: str) -> Dict[str, List[str]]:
    """Load route_key -> template_key ids from disk (normalized clean 5-part keys)."""
    if version_id in _ROUTE_INDEX_DISK_CACHE:
        return _ROUTE_INDEX_DISK_CACHE[version_id]

    from collections import defaultdict

    from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
        normalize_route_key,
    )

    path = selection_index_path_for_version(version_id)
    if not path.exists():
        _ROUTE_INDEX_DISK_CACHE[version_id] = {}
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    src = raw.get("index_by_route_key") or raw.get("route_index") or raw
    merged: Dict[str, List[str]] = defaultdict(list)
    if isinstance(src, dict):
        for rk, ids in src.items():
            crk = normalize_route_key(str(rk))
            if not crk or not isinstance(ids, list):
                continue
            merged[crk].extend(str(i) for i in ids if i)
    out = {k: list(dict.fromkeys(v)) for k, v in merged.items()}
    _ROUTE_INDEX_DISK_CACHE[version_id] = out
    return out


def load_templates_by_keys(
    sqlite_path: Path,
    template_keys: Sequence[str],
    *,
    pool_version: str | None = None,
    manifest_path: Path | None = None,
) -> List[ParamTemplate]:
    """Fetch only the templates needed for a route shelf (lazy load)."""
    keys = [str(k) for k in template_keys if k]
    if not keys or not sqlite_path.exists():
        return []

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    out: List[ParamTemplate] = []
    try:
        chunk = 400
        for i in range(0, len(keys), chunk):
            batch = keys[i : i + chunk]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT * FROM param_templates WHERE status = 'active' AND template_key IN ({placeholders})",
                batch,
            ).fetchall()
            if not rows:
                continue
            needed_ids = [int(r["id"]) for r in rows]
            id_placeholders = ",".join("?" for _ in needed_ids)
            tag_rows = conn.execute(
                f"SELECT template_id, tag_type, tag_value FROM template_tags WHERE template_id IN ({id_placeholders})",
                needed_ids,
            ).fetchall()
            tags_by_id: Dict[int, Dict[str, List[str]]] = {}
            for tr in tag_rows:
                tid = int(tr["template_id"])
                tags_by_id.setdefault(tid, {}).setdefault(tr["tag_type"], []).append(tr["tag_value"])
            for r in rows:
                out.append(_template_from_row(r, tags_by_id.get(int(r["id"]))))
    finally:
        conn.close()
    return out


def pool_cache_path(sqlite_path: Path) -> Path:
    return sqlite_path.with_suffix(".pkl")


def write_pool_cache(
    templates: List[ParamTemplate],
    cache_path: Path,
    *,
    checksum: str,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checksum": checksum,
        "templates": [t.model_dump() for t in templates if t.status == "active"],
    }
    with cache_path.open("wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)


def load_pool_cache(cache_path: Path, expected_checksum: str) -> Optional[List[ParamTemplate]]:
    if not cache_path.exists():
        return None
    try:
        with cache_path.open("rb") as fh:
            payload = pickle.load(fh)
        if not isinstance(payload, dict) or payload.get("checksum") != expected_checksum:
            return None
        raw = payload.get("templates") or []
        return [ParamTemplate.model_validate(d) for d in raw]
    except Exception:
        return None


def load_templates_from_sqlite(
    sqlite_path: Path,
    pool_version: str | None = None,
    *,
    manifest_path: Path | None = None,
) -> List[ParamTemplate]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Param pool SQLite not found: {sqlite_path}")

    mp = manifest_path
    if mp is None:
        if "v4" in sqlite_path.name:
            mp = DEFAULT_V4_MANIFEST_PATH
        elif "v3" in sqlite_path.name:
            mp = DEFAULT_V3_MANIFEST_PATH
        elif "v2" in sqlite_path.name:
            mp = DEFAULT_V2_MANIFEST_PATH
        else:
            mp = DEFAULT_MANIFEST_PATH
    checksum = ""
    if mp.exists():
        try:
            checksum = read_manifest(mp).checksum
        except Exception:
            checksum = ""

    cache_path = pool_cache_path(sqlite_path)
    if checksum:
        cached = load_pool_cache(cache_path, checksum)
        if cached:
            return cached

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM param_templates WHERE status = 'active'"
        ).fetchall()
        tag_rows = conn.execute("SELECT template_id, tag_type, tag_value FROM template_tags").fetchall()
        tags_by_id: Dict[int, Dict[str, List[str]]] = {}
        for tr in tag_rows:
            tags_by_id.setdefault(int(tr["template_id"]), {}).setdefault(tr["tag_type"], []).append(tr["tag_value"])
        templates = [_template_from_row(r, tags_by_id.get(int(r["id"]))) for r in rows]
        if checksum:
            write_pool_cache(templates, cache_path, checksum=checksum)
        return templates
    finally:
        conn.close()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS param_templates (
    id INTEGER PRIMARY KEY,
    template_key TEXT UNIQUE NOT NULL,
    pool_version TEXT NOT NULL,
    profile_family TEXT NOT NULL,
    final_action TEXT NOT NULL,
    score_min INTEGER NOT NULL,
    score_max INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    params_json TEXT,
    hard_limits_json TEXT,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS template_tags (
    template_id INTEGER NOT NULL,
    tag_type TEXT NOT NULL,
    tag_value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS template_metrics (
    template_id INTEGER NOT NULL,
    validation_quality_score REAL,
    safety_score REAL,
    complexity_score REAL,
    min_notional_safe INTEGER,
    exposure_safe INTEGER,
    fee_floor_safe INTEGER,
    runtime_enabled INTEGER
);
CREATE TABLE IF NOT EXISTS pool_manifest (
    pool_version TEXT PRIMARY KEY,
    template_count INTEGER,
    active_template_count INTEGER,
    checksum TEXT,
    created_at TEXT,
    schema_version TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_templates_score ON param_templates(score_min, score_max);
CREATE INDEX IF NOT EXISTS idx_templates_action ON param_templates(final_action);
CREATE INDEX IF NOT EXISTS idx_templates_profile ON param_templates(profile_family);
CREATE INDEX IF NOT EXISTS idx_templates_status ON param_templates(status);
CREATE INDEX IF NOT EXISTS idx_tags_type_value ON template_tags(tag_type, tag_value);
CREATE INDEX IF NOT EXISTS idx_tags_template ON template_tags(template_id);
"""


def _template_from_row(row: sqlite3.Row, tags: Dict[str, List[str]] | None = None) -> ParamTemplate:
    meta = json.loads(row["metadata_json"] or "{}")
    tags = tags or {}
    return ParamTemplate(
        template_key=row["template_key"],
        version=row["pool_version"],
        profile_family=row["profile_family"],
        final_action=row["final_action"],
        supported_regimes=tags.get("regime", meta.get("supported_regimes", [])),
        allowed_risk_states=tags.get("risk_state", meta.get("allowed_risk_states", [])),
        score_min=int(row["score_min"]),
        score_max=int(row["score_max"]),
        budget_tiers=tags.get("budget_tier", meta.get("budget_tiers", [])),
        exposure_tiers=tags.get("exposure_tier", meta.get("exposure_tiers", [])),
        headroom_tiers=tags.get("headroom_tier", meta.get("headroom_tiers", [])),
        fee_tiers=tags.get("fee_tier", meta.get("fee_tiers", [])),
        liquidity_tiers=tags.get("liquidity_tier", meta.get("liquidity_tiers", [])),
        volatility_tiers=tags.get("volatility_tier", meta.get("volatility_tiers", [])),
        btc_risk_tiers=tags.get("btc_risk_tier", meta.get("btc_risk_tiers", [])),
        order_reality_tiers=tags.get("order_reality_tier", meta.get("order_reality_tiers", [])),
        min_equity_usdt=float(meta.get("min_equity_usdt", 0)),
        max_equity_usdt=meta.get("max_equity_usdt"),
        min_notional_multiple=float(meta.get("min_notional_multiple", 0)),
        min_headroom_multiple=float(meta.get("min_headroom_multiple", 0)),
        min_trend_score=int(meta.get("min_trend_score", 0)),
        min_range_score=int(meta.get("min_range_score", 0)),
        min_liquidity_score=int(meta.get("min_liquidity_score", 0)),
        min_spread_score=int(meta.get("min_spread_score", 0)),
        min_momentum_score=int(meta.get("min_momentum_score", 0)),
        min_fee_efficiency_score=int(meta.get("min_fee_efficiency_score", 0)),
        min_exposure_safety_score=int(meta.get("min_exposure_safety_score", 0)),
        min_data_quality_score=int(meta.get("min_data_quality_score", 0)),
        min_btc_market_risk_score=int(meta.get("min_btc_market_risk_score", 0)),
        min_drawdown_risk_score=int(meta.get("min_drawdown_risk_score", 0)),
        min_mean_reversion_score=int(meta.get("min_mean_reversion_score", 0)),
        min_volatility_score=int(meta.get("min_volatility_score", 0)),
        max_spread_pct=meta.get("max_spread_pct"),
        max_total_friction_pct=meta.get("max_total_friction_pct"),
        max_volatility_pct=meta.get("max_volatility_pct"),
        requires_sellable_base=bool(meta.get("requires_sellable_base", False)),
        allows_buy_grid=bool(meta.get("allows_buy_grid", True)),
        allows_sell_grid=bool(meta.get("allows_sell_grid", True)),
        deployable=bool(meta.get("deployable", True)),
        params=json.loads(row["params_json"] or "{}"),
        hard_limits=json.loads(row["hard_limits_json"] or "{}"),
        priority=int(row["priority"]),
        validation_quality_score=float(meta.get("validation_quality_score", 0)),
        coverage_score=float(meta.get("coverage_score", 0)),
        precision_score=float(meta.get("precision_score", 0)),
        safety_score=float(meta.get("safety_score", 0)),
        complexity_score=float(meta.get("complexity_score", 0)),
        selection_priority=int(meta.get("selection_priority", 0)),
        profile_subfamily=meta.get("profile_subfamily"),
        status=row["status"],
        notes=meta.get("notes"),
    )


def _tag_rows(template_id: int, tag_type: str, values: Sequence[str]) -> List[tuple]:
    return [(template_id, tag_type, v) for v in values if v]


def insert_param_templates(
    sqlite_path: Path,
    templates: List[ParamTemplate],
    *,
    pool_version: str = "v4.0.0",
) -> int:
    """Insert new active templates (clone seed). Skips duplicate template_key."""
    if not templates:
        return 0
    conn = sqlite3.connect(str(sqlite_path))
    try:
        inserted = 0
        for t in templates:
            exists = conn.execute(
                "SELECT 1 FROM param_templates WHERE template_key = ? LIMIT 1",
                (t.template_key,),
            ).fetchone()
            if exists:
                continue
            meta = t.model_dump()
            for drop in (
                "template_key",
                "version",
                "profile_family",
                "final_action",
                "score_min",
                "score_max",
                "priority",
                "status",
                "params",
                "hard_limits",
            ):
                meta.pop(drop, None)
            cur = conn.execute(
                """
                INSERT INTO param_templates (
                    template_key, pool_version, profile_family, final_action,
                    score_min, score_max, priority, status,
                    params_json, hard_limits_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t.template_key,
                    pool_version,
                    t.profile_family,
                    t.final_action,
                    t.score_min,
                    t.score_max,
                    t.priority,
                    t.status,
                    json.dumps(t.params, separators=(",", ":")),
                    json.dumps(t.hard_limits, separators=(",", ":")),
                    json.dumps(meta, separators=(",", ":")),
                ),
            )
            tid = int(cur.lastrowid)
            tag_rows: List[tuple] = []
            tag_rows.extend(_tag_rows(tid, "regime", t.supported_regimes))
            tag_rows.extend(_tag_rows(tid, "risk_state", t.allowed_risk_states))
            tag_rows.extend(_tag_rows(tid, "budget_tier", t.budget_tiers))
            tag_rows.extend(_tag_rows(tid, "exposure_tier", t.exposure_tiers))
            tag_rows.extend(_tag_rows(tid, "headroom_tier", t.headroom_tiers))
            tag_rows.extend(_tag_rows(tid, "fee_tier", t.fee_tiers))
            tag_rows.extend(_tag_rows(tid, "liquidity_tier", t.liquidity_tiers))
            tag_rows.extend(_tag_rows(tid, "volatility_tier", t.volatility_tiers))
            tag_rows.extend(_tag_rows(tid, "btc_risk_tier", t.btc_risk_tiers))
            tag_rows.extend(_tag_rows(tid, "order_reality_tier", t.order_reality_tiers))
            conn.executemany(
                "INSERT INTO template_tags (template_id, tag_type, tag_value) VALUES (?, ?, ?)",
                tag_rows,
            )
            buy_n = int(t.params.get("buy_grid_count") or 0)
            sell_n = int(t.params.get("sell_grid_count") or 0)
            conn.execute(
                """
                INSERT INTO template_metrics (
                    template_id, validation_quality_score, safety_score, complexity_score,
                    min_notional_safe, exposure_safe, fee_floor_safe, runtime_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    t.validation_quality_score,
                    t.safety_score or (1.0 if t.deployable else 0.0),
                    t.complexity_score or float(buy_n + sell_n),
                    1,
                    1,
                    1,
                    1 if t.status == "active" else 0,
                ),
            )
            inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()


@dataclass
class ParamPool:
    pool_version: str
    templates: List[ParamTemplate]
    manifest: Optional[ParamPoolManifest] = None
    score_index: Dict[int, List[ParamTemplate]] = field(default_factory=dict)
    profile_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    regime_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    budget_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    fee_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    headroom_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    risk_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    exposure_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    dps_signature_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    route_key_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    structure_index: Dict[str, List[ParamTemplate]] = field(default_factory=dict)
    lazy_mode: bool = False
    _route_key_ids: Dict[str, List[str]] = field(default_factory=dict, repr=False)
    _sqlite_path: Optional[Path] = field(default=None, repr=False)
    _shelf_cache: Dict[str, List[ParamTemplate]] = field(default_factory=dict, repr=False)

    def _load_shelf_for_route(self, route_key: str) -> List[ParamTemplate]:
        """Lazy mode: load only templates for one route_key shelf from SQLite."""
        rk = route_key or ""
        if rk in self._shelf_cache:
            return self._shelf_cache[rk]
        if not self.lazy_mode or not self._sqlite_path:
            return list(self.route_key_index.get(rk, []))

        ids = self._route_key_ids.get(rk) or []
        if not ids:
            self._shelf_cache[rk] = []
            return []

        templates = load_templates_by_keys(
            self._sqlite_path,
            ids[:500],
            pool_version=self.pool_version,
        )
        from app.services.dynamic_param_score.param_pool.versioning import (
            _normalize_loaded_templates,
        )

        templates = _normalize_loaded_templates(templates)
        self._shelf_cache[rk] = templates
        self.route_key_index[rk] = templates
        return templates

    def build_memory_indexes(self) -> None:
        from app.services.dynamic_param_score.param_generator.param_index_builder import (
            index_key_for_signature,
        )

        self.score_index.clear()
        self.profile_index.clear()
        self.regime_index.clear()
        self.budget_index.clear()
        self.fee_index.clear()
        self.headroom_index.clear()
        self.risk_index.clear()
        self.exposure_index.clear()
        self.dps_signature_index.clear()
        self.route_key_index.clear()
        self.structure_index.clear()
        for t in self.templates:
            if t.status != "active":
                continue
            for b in range(t.score_min // 10, min(t.score_max // 10, 9) + 1):
                self.score_index.setdefault(b, []).append(t)
            self.profile_index.setdefault(t.profile_family, []).append(t)
            for regime in t.supported_regimes:
                self.regime_index.setdefault(regime, []).append(t)
            for bt in t.budget_tiers:
                self.budget_index.setdefault(bt, []).append(t)
            for ft in t.fee_tiers:
                self.fee_index.setdefault(ft, []).append(t)
            for ht in t.headroom_tiers:
                self.headroom_index.setdefault(ht, []).append(t)
            for rs in t.allowed_risk_states:
                self.risk_index.setdefault(rs, []).append(t)
            for et in t.exposure_tiers:
                self.exposure_index.setdefault(et, []).append(t)
            dps = (t.params or {}).get("dps_profile")
            if dps:
                from app.services.dynamic_param_score.param_generator.param_index_builder import (
                    index_key_for_signature,
                    route_key_for_signature,
                )

                sig = {
                    "asset_class": dps.get("asset_class"),
                    "budget_class": dps.get("budget_class"),
                    "regime": dps.get("regime"),
                    "risk_level": dps.get("risk_class", dps.get("risk_level", "NORMAL")),
                    "volatility_bin": dps.get("volatility_bin"),
                    "structure": dps.get("structure"),
                    "fee_class": dps.get("fee_class"),
                    "route_key": dps.get("route_key"),
                    "asset_code": dps.get("asset_code"),
                    "budget_code": dps.get("budget_code"),
                    "regime_code": dps.get("regime_code"),
                    "structure_code": dps.get("structure_code"),
                    "vol_code": dps.get("vol_code"),
                    "fee_code": dps.get("fee_code"),
                }
                self.dps_signature_index.setdefault(index_key_for_signature(sig), []).append(t)
                rk = dps.get("route_key") or route_key_for_signature(sig)
                from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
                    normalize_route_key,
                )

                rk = normalize_route_key(str(rk))
                self.route_key_index.setdefault(rk, []).append(t)
                sc = str(dps.get("structure_code") or "")
                if sc:
                    self.structure_index.setdefault(sc, []).append(t)

    @staticmethod
    def _deployable_route_hits(hits: List[ParamTemplate]) -> List[ParamTemplate]:
        """Templates that can be rendered for first-start / Param Assistant bot creation."""
        from app.services.dynamic_param_score.models import FinalAction

        out: List[ParamTemplate] = []
        for t in hits:
            if not t.deployable:
                continue
            if t.final_action in (
                FinalAction.NO_TRADE.value,
                FinalAction.WAIT.value,
                FinalAction.SAFE_WAIT.value,
            ):
                continue
            out.append(t)
        return out

    def query_route_shelf_with_trace(
        self, signature: Dict[str, Any]
    ) -> Tuple[List[ParamTemplate], Dict[str, Any]]:
        """Route index lookup with exact vs fallback shelf counts for selection telemetry."""
        from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
            clean_fallback_keys,
            is_forbidden_fallback,
            normalize_route_key,
        )
        from app.services.dynamic_param_score.param_generator.param_index_builder import (
            route_key_for_signature,
        )

        rk = normalize_route_key(route_key_for_signature(signature))
        exact_hits = self._load_shelf_for_route(rk)
        trace: Dict[str, Any] = {
            "exact_route_key": rk,
            "exact_route_candidate_count": len(exact_hits),
            "route_index_fallback_used": False,
            "fallback_route": None,
            "fallback_candidate_count": 0,
            "coverage_gap": False,
            "requested_risk_class": str(signature.get("risk_class") or "NORMAL"),
        }

        def _sig_route_parts(sig: Dict[str, Any]) -> tuple[str, str]:
            rk_sig = normalize_route_key(
                str(sig.get("route_key") or route_key_for_signature(sig))
            )
            parts = rk_sig.split("|")
            if len(parts) >= 5:
                return parts[0], parts[1]
            return (
                str(sig.get("asset_code") or ""),
                str(sig.get("regime_code") or sig.get("regime") or ""),
            )

        def _filter_forbidden(sig: Dict[str, Any], hits: List[ParamTemplate]) -> List[ParamTemplate]:
            from_asset, from_regime_code = _sig_route_parts(sig)
            out: List[ParamTemplate] = []
            for t in hits:
                dps = (t.params or {}).get("dps_profile") or {}
                to_rk = normalize_route_key(str(dps.get("route_key") or ""))
                to_parts = to_rk.split("|")
                to_regime_code = to_parts[1] if len(to_parts) >= 5 else str(
                    dps.get("regime_code") or dps.get("regime") or ""
                )
                to_asset = to_parts[0] if len(to_parts) >= 5 else str(dps.get("asset_code") or "")
                if is_forbidden_fallback(
                    from_regime_code,
                    to_regime_code,
                    from_asset=from_asset,
                    to_asset=to_asset,
                    from_structure=str(sig.get("structure_code") or ""),
                    to_structure=to_parts[2] if len(to_parts) >= 5 else "",
                    from_vol=str(sig.get("vol_code") or ""),
                    to_vol=to_parts[3] if len(to_parts) >= 5 else "",
                ):
                    continue
                out.append(t)
            return out

        exact_filtered = _filter_forbidden(signature, exact_hits)
        trace["exact_route_candidate_count"] = len(exact_filtered)
        requested_risk = str(signature.get("risk_class") or "NORMAL")
        needs_deployable = requested_risk in ("DEFENSIVE", "CAUTION")
        if exact_filtered:
            if not needs_deployable or self._deployable_route_hits(exact_filtered):
                return exact_filtered[:500], trace
            trace["exact_route_wait_only"] = True

        def _accept_route_hits(
            route_key: str,
            filtered: List[ParamTemplate],
            *,
            fallback: bool,
        ) -> Optional[List[ParamTemplate]]:
            if not filtered:
                return None
            deployable = self._deployable_route_hits(filtered)
            if needs_deployable and not deployable:
                if fallback:
                    trace.setdefault("wait_only_fallback_routes", []).append(route_key)
                return None
            trace["route_index_fallback_used"] = bool(fallback)
            if fallback:
                trace["fallback_route"] = route_key
                trace["fallback_candidate_count"] = len(filtered)
                trace["coverage_gap"] = True
                fb_parts = route_key.split("|")
                fb_risk = fb_parts[4] if len(fb_parts) >= 5 else ""
                trace["defensive_fallback_overlay"] = (
                    requested_risk in ("DEFENSIVE", "CAUTION") and fb_risk == "NORMAL"
                )
            else:
                trace["exact_route_candidate_count"] = len(filtered)
            return filtered[:500]

        for fb in signature.get("fallback_keys") or clean_fallback_keys(rk):
            fb = normalize_route_key(fb)
            hits = self._load_shelf_for_route(fb)
            if not hits:
                continue
            filtered = _filter_forbidden(signature, hits)
            accepted = _accept_route_hits(fb, filtered, fallback=True)
            if accepted is not None:
                return accepted, trace

        # Last resort: DEFENSIVE/CAUTION shelves may only contain WAIT profiles — use
        # same asset/regime/structure/vol NORMAL route for deployable library templates.
        if needs_deployable:
            parts = rk.split("|")
            if len(parts) >= 5:
                normal_route = normalize_route_key(
                    "|".join([parts[0], parts[1], parts[2], parts[3], "NORMAL"])
                )
                hits = self._load_shelf_for_route(normal_route)
                if hits:
                    filtered = _filter_forbidden(signature, hits)
                    deployable = self._deployable_route_hits(filtered)
                    if deployable:
                        trace["route_index_fallback_used"] = True
                        trace["fallback_route"] = normal_route
                        trace["fallback_candidate_count"] = len(deployable)
                        trace["coverage_gap"] = True
                        trace["defensive_fallback_overlay"] = True
                        trace["wait_only_escalation"] = True
                        return deployable[:500], trace

        trace["coverage_gap"] = requested_risk in ("DEFENSIVE", "CAUTION")
        return [], trace

    def query_dps_signature_candidates(self, signature: Dict[str, Any]) -> List[ParamTemplate]:
        templates, _trace = self.query_route_shelf_with_trace(signature)
        return templates

    def _intersect_lists(self, lists: List[List[ParamTemplate]]) -> List[ParamTemplate]:
        if not lists:
            return list(self.templates)
        sets = [set(id(t) for t in lst) for lst in lists if lst]
        if not sets:
            return list(self.templates)
        common = sets[0]
        for s in sets[1:]:
            common &= s
        id_to_t = {id(t): t for t in self.templates}
        return [id_to_t[i] for i in common if i in id_to_t]

    def query_candidates_memory(self, features: SelectionFeatures) -> List[ParamTemplate]:
        bucket = features.param_score // 10
        score_lists = [self.score_index.get(b, []) for b in (bucket - 1, bucket, bucket + 1)]
        score_candidates = []
        for lst in score_lists:
            score_candidates.extend(lst)
        if not score_candidates:
            score_candidates = list(self.templates)

        narrow_sets = [
            self.regime_index.get(features.regime, []),
            self.budget_index.get(features.budget_tier, []),
            self.fee_index.get(features.fee_tier, []),
            self.headroom_index.get(features.headroom_tier, []),
            self.exposure_index.get(features.exposure_tier, []),
            self.risk_index.get(features.risk_state, []),
        ]
        narrowed = self._intersect_lists(narrow_sets)
        if narrowed:
            narrowed_ids = {id(t) for t in narrowed}
            candidates = [t for t in score_candidates if id(t) in narrowed_ids]
        else:
            candidates = [
                t for t in score_candidates
                if features.regime in t.supported_regimes
            ]

        if not candidates:
            candidates = list(self.templates)

        return [
            t for t in candidates
            if t.status == "active"
            and t.score_min <= features.param_score <= t.score_max
            and features.regime in t.supported_regimes
            and features.risk_state in t.allowed_risk_states
            and features.budget_tier in t.budget_tiers
            and features.exposure_tier in t.exposure_tiers
            and (not t.headroom_tiers or features.headroom_tier in t.headroom_tiers)
            and (not t.fee_tiers or features.fee_tier in t.fee_tiers)
            and (not t.liquidity_tiers or features.liquidity_tier in t.liquidity_tiers)
            and (not t.volatility_tiers or features.volatility_tier in t.volatility_tiers)
            and (not t.btc_risk_tiers or features.btc_risk_tier in t.btc_risk_tiers)
            and (not t.order_reality_tiers or features.order_reality_tier in t.order_reality_tiers)
        ] or candidates


def write_pool_sqlite(
    templates: List[ParamTemplate],
    sqlite_path: Path,
    pool_version: str,
    *,
    manifest: ParamPoolManifest | None = None,
) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists():
        sqlite_path.unlink()

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA_SQL)
        for t in templates:
            meta = t.model_dump()
            for drop in ("template_key", "version", "profile_family", "final_action", "score_min", "score_max", "priority", "status", "params", "hard_limits"):
                meta.pop(drop, None)
            cur = conn.execute(
                """
                INSERT INTO param_templates (
                    template_key, pool_version, profile_family, final_action,
                    score_min, score_max, priority, status,
                    params_json, hard_limits_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t.template_key,
                    pool_version,
                    t.profile_family,
                    t.final_action,
                    t.score_min,
                    t.score_max,
                    t.priority,
                    t.status,
                    json.dumps(t.params, separators=(",", ":")),
                    json.dumps(t.hard_limits, separators=(",", ":")),
                    json.dumps(meta, separators=(",", ":")),
                ),
            )
            tid = int(cur.lastrowid)
            tag_rows: List[tuple] = []
            tag_rows.extend(_tag_rows(tid, "regime", t.supported_regimes))
            tag_rows.extend(_tag_rows(tid, "risk_state", t.allowed_risk_states))
            tag_rows.extend(_tag_rows(tid, "budget_tier", t.budget_tiers))
            tag_rows.extend(_tag_rows(tid, "exposure_tier", t.exposure_tiers))
            tag_rows.extend(_tag_rows(tid, "headroom_tier", t.headroom_tiers))
            tag_rows.extend(_tag_rows(tid, "fee_tier", t.fee_tiers))
            tag_rows.extend(_tag_rows(tid, "liquidity_tier", t.liquidity_tiers))
            tag_rows.extend(_tag_rows(tid, "volatility_tier", t.volatility_tiers))
            tag_rows.extend(_tag_rows(tid, "btc_risk_tier", t.btc_risk_tiers))
            tag_rows.extend(_tag_rows(tid, "order_reality_tier", t.order_reality_tiers))
            conn.executemany(
                "INSERT INTO template_tags (template_id, tag_type, tag_value) VALUES (?, ?, ?)",
                tag_rows,
            )
            buy_n = int(t.params.get("buy_grid_count") or 0)
            sell_n = int(t.params.get("sell_grid_count") or 0)
            conn.execute(
                """
                INSERT INTO template_metrics (
                    template_id, validation_quality_score, safety_score, complexity_score,
                    min_notional_safe, exposure_safe, fee_floor_safe, runtime_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    t.validation_quality_score,
                    t.safety_score or (1.0 if t.deployable else 0.0),
                    t.complexity_score or float(buy_n + sell_n),
                    1,
                    1,
                    1,
                    1 if t.status == "active" else 0,
                ),
            )

        mf = manifest or build_manifest(templates, pool_version)
        conn.execute(
            """
            INSERT INTO pool_manifest (
                pool_version, template_count, active_template_count,
                checksum, created_at, schema_version, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mf.pool_version,
                mf.template_count,
                mf.active_template_count,
                mf.checksum,
                mf.created_at,
                mf.schema_version,
                mf.notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_active_pool(
    pool_version: str,
    *,
    sqlite_path: Path | None = None,
    memory_index_mode: bool = True,
) -> ParamPool:
    path = sqlite_path or DEFAULT_SQLITE_PATH
    manifest_path = DEFAULT_V2_MANIFEST_PATH if "v2" in path.name else DEFAULT_MANIFEST_PATH
    templates = load_templates_from_sqlite(path, pool_version, manifest_path=manifest_path)
    mf_path = manifest_path if manifest_path.exists() else DEFAULT_MANIFEST_PATH
    manifest = read_manifest(mf_path) if mf_path.exists() else build_manifest(templates, pool_version)
    pool = ParamPool(pool_version=pool_version, templates=templates, manifest=manifest)
    if memory_index_mode:
        pool.build_memory_indexes()
    return pool


def query_candidates(
    pool: ParamPool,
    features: SelectionFeatures,
    *,
    mode: str = "memory_index_mode",
) -> List[ParamTemplate]:
    if mode == "memory_index_mode" and pool.score_index:
        return pool.query_candidates_memory(features)
    if mode == "sqlite_query_mode":
        return pool.query_candidates_memory(features)
    return [
        t for t in pool.templates
        if t.status == "active"
        and t.score_min <= features.param_score <= t.score_max
        and features.regime in t.supported_regimes
    ]


def get_template(pool: ParamPool, template_key: str) -> ParamTemplate | None:
    for t in pool.templates:
        if t.template_key == template_key:
            return t
    return None


def get_manifest(pool_version: str, manifest_path: Path | None = None) -> ParamPoolManifest:
    path = manifest_path or DEFAULT_MANIFEST_PATH
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return read_manifest(path)


def write_jsonl(templates: List[ParamTemplate], jsonl_path: Path) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for t in templates:
            fh.write(json.dumps(t.model_dump(), ensure_ascii=False, separators=(",", ":")) + "\n")
