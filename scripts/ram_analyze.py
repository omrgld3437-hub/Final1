#!/usr/bin/env python3
"""
RAM snapshot analysis: parse logs/ram_snapshots.log (JSONL), analyze RSS/object trends,
classify leak type, aggregate tracemalloc offenders, produce Markdown/JSON reports and PNG plots.

Usage: python scripts/ram_analyze.py

Requires: matplotlib (optional; install for PNG graphs: pip install matplotlib).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_DEFAULT_LOG = _PROJECT_ROOT / "logs" / "ram_snapshots.log"
_LOGS_DIR = _PROJECT_ROOT / "logs"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_snapshots(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file; return list of parsed objects. Skip bad lines with log. Fail if file missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"RAM snapshot log not found: {path}. Run with RAM_PROBE=1 to collect snapshots."
        )
    data: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("error"):
                    continue
                data.append(obj)
            except json.JSONDecodeError as e:
                logger.warning("Skip line %d (invalid JSON): %s", i, e)
    return data


def group_by_component(data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group snapshots by component (web, worker). Sort each group by ts."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in data:
        comp = (row.get("component") or "unknown").strip().lower()
        if comp not in ("web", "worker"):
            continue
        if comp not in groups:
            groups[comp] = []
        groups[comp].append(row)
    for comp in groups:
        groups[comp].sort(key=lambda r: r.get("ts") or "")
    return groups


def _rss_series(entries: List[Dict[str, Any]]) -> List[Tuple[float, Optional[float]]]:
    """Return (timestamp_epoch, rss_mb) list. rss_mb None if missing."""
    out: List[Tuple[float, Optional[float]]] = []
    for r in entries:
        ts = r.get("ts")
        if not ts:
            continue
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            t_epoch = dt.timestamp()
        except Exception:
            continue
        rss = r.get("rss_mb")
        if rss is not None:
            try:
                rss = float(rss)
            except (TypeError, ValueError):
                rss = None
        out.append((t_epoch, rss))
    return out


def _object_count(entry: Dict[str, Any]) -> Optional[int]:
    """Extract object count from snapshot (gc.total_objects or num_objects)."""
    gc = entry.get("gc")
    if isinstance(gc, dict) and "total_objects" in gc:
        try:
            return int(gc["total_objects"])
        except (TypeError, ValueError):
            pass
    n = entry.get("num_objects")
    if n is not None:
        try:
            return int(n)
        except (TypeError, ValueError):
            pass
    return None


def analyze_rss_trend(timeseries: List[Tuple[float, Optional[float]]]) -> Dict[str, Any]:
    """
    Analyze RSS time series. Return metrics: start, end, max, mean, growth_mb_per_min,
    correlation (if enough points), is_monotonic.
    """
    valid = [(t, v) for t, v in timeseries if v is not None]
    if not valid:
        return {
            "rss_start_mb": None,
            "rss_end_mb": None,
            "rss_max_mb": None,
            "rss_mean_mb": None,
            "growth_mb_per_min": None,
            "correlation": None,
            "is_monotonic": False,
            "n_points": 0,
        }
    times = [x[0] for x in valid]
    values = [x[1] for x in valid]
    n = len(values)
    rss_start = values[0]
    rss_end = values[-1]
    rss_max = max(values)
    rss_mean = sum(values) / n
    t_span_min = (times[-1] - times[0]) / 60.0 if times[-1] > times[0] else 0.0
    growth = None
    if t_span_min >= 0.016:  # at least ~1 second to avoid division noise
        growth = (rss_end - rss_start) / t_span_min

    is_monotonic = all(values[i] <= values[i + 1] for i in range(n - 1))
    correlation = None
    if n >= 10:
        try:
            import statistics
            mean_t = sum(times) / n
            mean_v = sum(values) / n
            num = sum((t - mean_t) * (v - mean_v) for t, v in zip(times, values))
            den_t = sum((t - mean_t) ** 2 for t in times) ** 0.5
            den_v = sum((v - mean_v) ** 2 for v in values) ** 0.5
            if den_t and den_v:
                correlation = num / (den_t * den_v)
        except Exception:
            pass

    return {
        "rss_start_mb": round(rss_start, 2),
        "rss_end_mb": round(rss_end, 2),
        "rss_max_mb": round(rss_max, 2),
        "rss_mean_mb": round(rss_mean, 2),
        "growth_mb_per_min": round(growth, 4) if growth is not None else None,
        "correlation": round(correlation, 4) if correlation is not None else None,
        "is_monotonic": is_monotonic,
        "n_points": n,
    }


def classify_leak(trend_metrics: Dict[str, Any]) -> str:
    """
    Classify leak: LINEAR_GROWTH, PLATEAU, SPIKE, or NONE.
    LINEAR_GROWTH: monotonic + correlation > 0.8, at least 10 snapshots.
    PLATEAU: after initial rise, RSS stable within ±5%.
    SPIKE: short-term >20% rise then drop back.
    """
    n = trend_metrics.get("n_points", 0)
    if n < 3:
        return "none"

    rss_start = trend_metrics.get("rss_start_mb")
    rss_end = trend_metrics.get("rss_end_mb")
    rss_max = trend_metrics.get("rss_max_mb")
    growth = trend_metrics.get("growth_mb_per_min")
    corr = trend_metrics.get("correlation")
    is_mono = trend_metrics.get("is_monotonic", False)

    if n >= 10 and is_mono and corr is not None and corr > 0.8 and growth is not None and growth > 0:
        return "linear"

    if rss_start is not None and rss_end is not None and rss_max is not None:
        band = max(rss_start, rss_end) * 0.05
        mid = (rss_start + rss_end) / 2
        if abs(rss_end - mid) <= band and abs(rss_max - mid) <= band * 1.5:
            return "plateau"

    values = trend_metrics.get("_values")
    if values and len(values) >= 5:
        v_max = max(values)
        v_min = min(values)
        if v_min > 0 and (v_max - v_min) / v_min > 0.20:
            last_quarter = values[-max(1, len(values) // 4):]
            if max(last_quarter) < v_max * 0.95:
                return "spike"

    return "none"


def aggregate_tracemalloc(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aggregate tracemalloc_top across entries: (file, line) -> total size_kb, total count.
    Supports size_mb (our format) and size_kb/count (example format). Returns top offenders.
    """
    agg: Dict[Tuple[str, Optional[int]], Dict[str, Any]] = {}
    for row in entries:
        top = row.get("tracemalloc_top")
        if not isinstance(top, list):
            continue
        for item in top:
            if not isinstance(item, dict):
                continue
            f = (item.get("file") or "").strip()
            line = item.get("line")
            if line is not None:
                try:
                    line = int(line)
                except (TypeError, ValueError):
                    line = None
            key = (f, line)
            size_kb = item.get("size_kb")
            size_mb = item.get("size_mb")
            count = item.get("count")
            if size_kb is not None:
                try:
                    sk = float(size_kb)
                except (TypeError, ValueError):
                    sk = 0.0
            elif size_mb is not None:
                try:
                    sk = float(size_mb) * 1024
                except (TypeError, ValueError):
                    sk = 0.0
            else:
                sk = 0.0
            if count is None:
                try:
                    count = int(item.get("count", 0))
                except (TypeError, ValueError):
                    count = 0
            if key not in agg:
                agg[key] = {"file": f, "line": line, "size_kb": 0.0, "count": 0}
            agg[key]["size_kb"] += sk
            agg[key]["count"] += count
    out = list(agg.values())
    out.sort(key=lambda x: (-x["size_kb"], -x["count"]))
    return out[:10]


def _leak_annotations(
    entries: List[Dict[str, Any]],
    leak_type: str,
    timeseries: List[Tuple[float, Optional[float]]],
) -> List[Tuple[float, float, str]]:
    """Points to annotate on plot (t_epoch, rss_mb, label)."""
    if leak_type == "none" or not timeseries:
        return []
    valid = [(t, v) for t, v in timeseries if v is not None]
    if not valid:
        return []
    if leak_type == "linear":
        return [(valid[-1][0], valid[-1][1], "linear growth")]
    if leak_type == "spike":
        idx = max(range(len(valid)), key=lambda i: valid[i][1])
        return [(valid[idx][0], valid[idx][1], "spike")]
    return []


def render_plots(component_data: Dict[str, Dict[str, Any]]) -> None:
    """
    Produce 4 PNGs: ram_rss_web, ram_rss_worker, ram_objects_web, ram_objects_worker.
    X=time, Y=RSS (MB) or object count. Annotate leak points.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from datetime import datetime, timezone
    except ImportError:
        logger.warning("matplotlib not installed; skipping plots.")
        return

    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    for comp in ("web", "worker"):
        if comp not in component_data:
            continue
        cd = component_data[comp]
        entries = cd.get("entries") or []
        if not entries:
            continue
        ts_epoch = []
        rss = []
        objs = []
        for r in entries:
            t = r.get("ts")
            if not t:
                continue
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                ts_epoch.append(dt)
            except Exception:
                continue
            rss.append(r.get("rss_mb") if r.get("rss_mb") is not None else float("nan"))
            objs.append(_object_count(r) if _object_count(r) is not None else float("nan"))

        if not ts_epoch:
            continue

        trend = cd.get("rss_trend", {})
        leak_type = trend.get("leak_type", "none")
        timeseries_rss = _rss_series(entries)
        ann = _leak_annotations(entries, leak_type, timeseries_rss)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(ts_epoch, rss, "b-", label="RSS (MB)")
        for t_epoch, rss_val, label in ann:
            try:
                dt = datetime.fromtimestamp(t_epoch, tz=timezone.utc)
                ax.annotate(label, (dt, rss_val), fontsize=8, alpha=0.8)
            except Exception:
                pass
        ax.set_xlabel("Time")
        ax.set_ylabel("RSS (MB)")
        ax.set_title(f"RAM RSS — {comp}")
        ax.legend(loc="upper left")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig.autofmt_xdate()
        out_path = _LOGS_DIR / f"ram_rss_{comp}.png"
        fig.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        logger.info("Wrote %s", out_path)

        fig2, ax2 = plt.subplots(figsize=(10, 4))
        ax2.plot(ts_epoch, objs, "g-", label="Object count")
        ax2.set_xlabel("Time")
        ax2.set_ylabel("Objects")
        ax2.set_title(f"RAM object count — {comp}")
        ax2.legend(loc="upper left")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig2.autofmt_xdate()
        out_path2 = _LOGS_DIR / f"ram_objects_{comp}.png"
        fig2.savefig(out_path2, dpi=100, bbox_inches="tight")
        plt.close(fig2)
        logger.info("Wrote %s", out_path2)


def write_markdown_report(
    component_data: Dict[str, Dict[str, Any]],
    global_assessment: Dict[str, Any],
    out_path: Path,
) -> None:
    """Write logs/ram_report.md: summary table, leak assessment, web vs worker, top offenders, root-cause."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# RAM Snapshot Analysis Report")
    lines.append("")
    lines.append("## Summary by component")
    lines.append("")
    lines.append("| Component | RSS start (MB) | RSS end (MB) | RSS max (MB) | RSS mean (MB) | Growth (MB/min) | Leak type |")
    lines.append("|-----------|----------------|--------------|--------------|---------------|-----------------|------------|")
    for comp in ("web", "worker"):
        if comp not in component_data:
            continue
        cd = component_data[comp]
        t = cd.get("rss_trend", {})
        lt = t.get("leak_type", "none")
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (
                comp,
                t.get("rss_start_mb") if t.get("rss_start_mb") is not None else "—",
                t.get("rss_end_mb") if t.get("rss_end_mb") is not None else "—",
                t.get("rss_max_mb") if t.get("rss_max_mb") is not None else "—",
                t.get("rss_mean_mb") if t.get("rss_mean_mb") is not None else "—",
                t.get("growth_mb_per_min") if t.get("growth_mb_per_min") is not None else "—",
                lt.upper() if lt != "none" else "NONE",
            )
        )
    lines.append("")
    lines.append("## Leak assessment")
    lines.append("")
    primary = global_assessment.get("primary_leak_component") or "—"
    conf = global_assessment.get("confidence")
    conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)
    lines.append(f"- **Primary leak component:** {primary}")
    lines.append(f"- **Confidence:** {conf_str}")
    lines.append("")
    lines.append("## Web vs Worker")
    lines.append("")
    web_t = component_data.get("web", {}).get("rss_trend", {})
    worker_t = component_data.get("worker", {}).get("rss_trend", {})
    web_end = web_t.get("rss_end_mb")
    worker_end = worker_t.get("rss_end_mb")
    if web_end is not None and worker_end is not None:
        lines.append(f"- Web RSS end: {web_end} MB")
        lines.append(f"- Worker RSS end: {worker_end} MB")
        if worker_end > web_end:
            lines.append("- Worker uses more RSS than web in this sample.")
        else:
            lines.append("- Web uses more RSS than worker in this sample.")
    else:
        lines.append("- Insufficient data for comparison.")
    lines.append("")
    lines.append("## Top 10 suspicious file/line (tracemalloc aggregate)")
    lines.append("")
    all_offenders: List[Tuple[str, Dict[str, Any]]] = []
    for comp in ("web", "worker"):
        if comp not in component_data:
            continue
        for o in component_data[comp].get("top_offenders") or []:
            all_offenders.append((comp, o))
    all_offenders.sort(key=lambda x: (-x[1].get("size_kb", 0), -x[1].get("count", 0)))
    lines.append("| Component | File | Line | Size (KB) | Count |")
    lines.append("|-----------|------|------|-----------|-------|")
    for comp, o in all_offenders[:10]:
        f = (o.get("file") or "—")[:60]
        ln = o.get("line") if o.get("line") is not None else "—"
        sk = o.get("size_kb", 0)
        ct = o.get("count", 0)
        lines.append(f"| {comp} | {f} | {ln} | {sk:.1f} | {ct} |")
    lines.append("")
    lines.append("## Root-cause candidate")
    lines.append("")
    rc = global_assessment.get("root_cause_comment") or ""
    if rc:
        lines.append(rc)
    else:
        if primary and primary != "—":
            lines.append(f"Evidence points to **{primary}** as the main contributor to RAM growth. ")
            lines.append("Review the top offenders above and the corresponding source files.")
        else:
            lines.append("No clear linear leak in this sample. Check plateau/spike behavior and tracemalloc offenders.")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_path)


def write_json_report(
    component_data: Dict[str, Dict[str, Any]],
    global_assessment: Dict[str, Any],
    out_path: Path,
) -> None:
    """Write logs/ram_report.json with components and global_assessment."""
    out = {
        "components": {},
        "global_assessment": global_assessment,
    }
    for comp in ("web", "worker"):
        if comp not in component_data:
            continue
        cd = component_data[comp]
        t = cd.get("rss_trend", {})
        out["components"][comp] = {
            "rss_start_mb": t.get("rss_start_mb"),
            "rss_end_mb": t.get("rss_end_mb"),
            "rss_max_mb": t.get("rss_max_mb"),
            "growth_mb_per_min": t.get("growth_mb_per_min"),
            "leak_type": t.get("leak_type", "none"),
            "top_offenders": cd.get("top_offenders") or [],
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("Wrote %s", out_path)


def main() -> None:
    log_path = _DEFAULT_LOG
    snapshots = load_snapshots(log_path)
    if not snapshots:
        logger.warning("No valid snapshots in %s", log_path)
        sys.exit(0)

    grouped = group_by_component(snapshots)
    component_data: Dict[str, Dict[str, Any]] = {}

    for comp in ("web", "worker"):
        if comp not in grouped:
            continue
        entries = grouped[comp]
        timeseries = _rss_series(entries)
        trend = analyze_rss_trend(timeseries)
        trend["_values"] = [v for _, v in timeseries if v is not None]
        trend["leak_type"] = classify_leak(trend)
        del trend["_values"]
        top_offenders = aggregate_tracemalloc(entries)
        component_data[comp] = {
            "entries": entries,
            "rss_trend": trend,
            "top_offenders": top_offenders,
        }

    primary_leak = "none"
    confidence = 0.0
    for comp in ("worker", "web"):
        if comp not in component_data:
            continue
        lt = component_data[comp]["rss_trend"].get("leak_type", "none")
        if lt == "linear":
            primary_leak = comp
            confidence = 0.9
            break
        if lt == "plateau" and primary_leak == "none":
            primary_leak = comp
            confidence = 0.6
        if lt == "spike" and primary_leak == "none":
            primary_leak = comp
            confidence = 0.5
    if primary_leak == "none" and component_data:
        comps = list(component_data.keys())
        primary_leak = comps[0] if comps else "—"
        confidence = 0.3

    root_comment = ""
    if primary_leak != "none":
        root_comment = (
            f"Primary RAM growth candidate: {primary_leak}. "
            "Check tracemalloc top offenders and recent code changes in that process."
        )
    global_assessment = {
        "primary_leak_component": primary_leak,
        "confidence": confidence,
        "root_cause_comment": root_comment,
    }

    render_plots(component_data)
    write_markdown_report(component_data, global_assessment, _LOGS_DIR / "ram_report.md")
    write_json_report(component_data, global_assessment, _LOGS_DIR / "ram_report.json")
    logger.info("RAM analysis complete.")


if __name__ == "__main__":
    main()
