"""
Olay Merkezi — dosya tabanlı depo (kalıcı RAM havuzu yok).

.run/issues/
  active.json    — AÇIK / ONAYLI / ÇÖZÜLDÜ
  archived.json  — kullanıcı arşivi (Arşiv sekmesi)
  backup.jsonl   — kapasite taşması / yerel yedek (BACKUP sekmesi)
  meta.json      — sayaç + özet istatistik (hızlı summary)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUN_DIR = _PROJECT_ROOT / ".run"
_ISSUES_DIR = _RUN_DIR / "issues"
_ACTIVE_FILE = _ISSUES_DIR / "active.json"
_ARCHIVED_FILE = _ISSUES_DIR / "archived.json"
_BACKUP_FILE = _ISSUES_DIR / "backup.jsonl"
_META_FILE = _ISSUES_DIR / "meta.json"
_LEGACY_ACTIVE = _RUN_DIR / "issues_active.json"
_LEGACY_BACKUP = _RUN_DIR / "issues_archive.jsonl"

MAX_ISSUES = 300
MAX_ISSUE_SAMPLES = 3
ISSUE_COMMENT_MAX = 15
ISSUE_STATUS_HIST_MAX = 15
MAX_ISSUES_ARCHIVE = 10000
ARCHIVE_QUERY_SCAN = 2500
JSONL_COUNT_CACHE_TTL = 60.0

_lock = threading.RLock()
_jsonl_count_cache: dict[str, tuple[int, float]] = {}


def _now_tr_iso() -> str:
    from manager_server.state import _now_tr_iso as _iso

    return _iso()


def _ensure_dirs() -> None:
    _ISSUES_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict) -> None:
    _ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_issue_id_num(issue_id: Optional[str]) -> int:
    if not issue_id or not str(issue_id).startswith("ISS-"):
        return 0
    try:
        return int(str(issue_id)[4:])
    except ValueError:
        return 0


def _issue_from_disk(raw: dict) -> dict:
    i = dict(raw)
    if not isinstance(i.get("comments"), deque):
        i["comments"] = deque(i.get("comments") or [], maxlen=ISSUE_COMMENT_MAX)
    if not isinstance(i.get("status_history"), deque):
        i["status_history"] = deque(i.get("status_history") or [], maxlen=ISSUE_STATUS_HIST_MAX)
    i.setdefault("assignee", None)
    i.setdefault("labels", [])
    i.setdefault("sla_note", None)
    return i


def _issue_to_dict(i: dict) -> dict:
    out = dict(i)
    out.setdefault("assignee", None)
    out.setdefault("labels", [])
    out.setdefault("sla_note", None)
    if isinstance(out.get("comments"), deque):
        out["comments"] = list(out["comments"])
    else:
        out.setdefault("comments", [])
    if isinstance(out.get("status_history"), deque):
        out["status_history"] = list(out["status_history"])
    else:
        out.setdefault("status_history", [])
    if isinstance(out.get("labels"), list) and len(out["labels"]) > 10:
        out["labels"] = out["labels"][:10]
    return out


def _serialize_issue(i: dict) -> dict:
    return _issue_to_dict(i)


def _load_meta() -> dict:
    meta = _read_json(_META_FILE)
    meta.setdefault("counter", 0)
    meta.setdefault("revision", 0)
    meta.setdefault("counts", {})
    return meta


def _bump_revision(meta: dict) -> None:
    meta["revision"] = int(meta.get("revision") or 0) + 1
    meta["updated_at"] = _now_tr_iso()


def _save_meta(meta: dict) -> None:
    _atomic_write_json(_META_FILE, meta)


def _load_bucket(path: Path) -> Tuple[dict, Deque[str], int]:
    data = _read_json(path)
    counter = int(data.get("counter") or 0)
    order_raw = data.get("order") or []
    raw_issues = data.get("issues") or {}
    issues: Dict[str, dict] = {}
    order: Deque[str] = deque()
    if isinstance(raw_issues, dict):
        for fp in order_raw if isinstance(order_raw, list) else []:
            if fp in raw_issues:
                issues[str(fp)] = _issue_from_disk(raw_issues[fp])
                order.append(str(fp))
        for fp, raw in raw_issues.items():
            fp = str(fp)
            if fp not in issues:
                issues[fp] = _issue_from_disk(raw)
                order.append(fp)
    return issues, order, counter


def _save_bucket(path: Path, issues: Dict[str, dict], order: Deque[str], counter: int) -> None:
    payload = {
        "counter": counter,
        "order": list(order),
        "issues": {fp: _serialize_issue(i) for fp, i in issues.items()},
        "saved_at": _now_tr_iso(),
    }
    _atomic_write_json(path, payload)


def _count_bucket(path: Path) -> int:
    issues, _, _ = _load_bucket(path)
    return len(issues)


def _recompute_active_counts(issues: Dict[str, dict]) -> dict:
    counts = {"open": 0, "ack": 0, "resolved": 0, "archived": 0, "total": 0}
    for i in issues.values():
        counts["total"] += 1
        st = (i.get("status") or "OPEN").upper()
        if st == "OPEN":
            counts["open"] += 1
        elif st == "ACK":
            counts["ack"] += 1
        elif st == "RESOLVED":
            counts["resolved"] += 1
        elif st == "ARCHIVED":
            counts["archived"] += 1
    counts["active"] = counts["open"] + counts["ack"] + counts["resolved"]
    return counts


def _refresh_meta_counts(meta: dict) -> None:
    active_issues, _, _ = _load_bucket(_ACTIVE_FILE)
    archived_n = _count_bucket(_ARCHIVED_FILE)
    backup_n = _count_jsonl_lines_cached(_BACKUP_FILE)
    counts = _recompute_active_counts(active_issues)
    counts["archived"] = archived_n
    counts["backup"] = backup_n
    counts["max_active"] = MAX_ISSUES
    meta["counts"] = counts


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        n = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    n += 1
        return n
    except Exception:
        return 0


def _count_jsonl_lines_cached(path: Path) -> int:
    key = str(path)
    import time

    now = time.time()
    cached = _jsonl_count_cache.get(key)
    if cached and (now - cached[1]) < JSONL_COUNT_CACHE_TTL:
        return cached[0]
    n = _count_jsonl_lines(path)
    _jsonl_count_cache[key] = (n, now)
    return n


def _invalidate_jsonl_count_cache(path: Path) -> None:
    _jsonl_count_cache.pop(str(path), None)


def _read_file_tail_text(path: Path, max_bytes: int = 1_048_576) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        if size <= 0:
            return ""
        with open(path, "rb") as f:
            read_size = min(size, max_bytes)
            f.seek(-read_size, 2)
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _trim_jsonl_file(path: Path, max_lines: int) -> None:
    if not path.exists():
        return
    try:
        total = _count_jsonl_lines(path)
        if total <= max_lines:
            return
        skip = total - max_lines
        tmp = path.with_suffix(path.suffix + ".tmp")
        kept = 0
        with open(path, "r", encoding="utf-8", errors="replace") as src, open(tmp, "w", encoding="utf-8") as dst:
            for line in src:
                if not line.strip():
                    continue
                if skip > 0:
                    skip -= 1
                    continue
                dst.write(line if line.endswith("\n") else line + "\n")
                kept += 1
        tmp.replace(path)
        import time

        _jsonl_count_cache[str(path)] = (kept, time.time())
    except Exception:
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _append_backup(record: dict, reason: str = "capacity") -> None:
    try:
        _ensure_dirs()
        rec = dict(record)
        rec["_backup_reason"] = reason
        rec["_backup_at"] = _now_tr_iso()
        with open(_BACKUP_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        _invalidate_jsonl_count_cache(_BACKUP_FILE)
        _trim_jsonl_file(_BACKUP_FILE, MAX_ISSUES_ARCHIVE)
    except Exception as e:
        logger.debug("append backup issue failed: %s", e)


def _query_jsonl_archive(
    path: Path,
    limit: int,
    offset: int,
    match_fn: Callable[[dict], bool],
    max_scan: int = ARCHIVE_QUERY_SCAN,
) -> Tuple[List[dict], int]:
    if not path.exists():
        return [], 0
    text = _read_file_tail_text(path, max_bytes=ARCHIVE_QUERY_SCAN * 512)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > max_scan:
        lines = lines[-max_scan:]
    need = max(0, offset) + max(0, limit)
    matched: List[dict] = []
    extra = 0
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not match_fn(rec):
            continue
        if len(matched) < need:
            matched.append(rec)
        else:
            extra += 1
    total = len(matched) + extra
    return matched[offset : offset + limit], total


def _pick_eviction_fingerprint(issues: Dict[str, dict], order: Deque[str]) -> Optional[str]:
    if not issues:
        return None
    rank = {"ARCHIVED": 0, "RESOLVED": 1, "ACK": 2, "OPEN": 3}
    candidates: List[tuple] = []
    for fp in list(order):
        i = issues.get(fp)
        if not i:
            continue
        st = (i.get("status") or "OPEN").upper()
        candidates.append((rank.get(st, 9), i.get("last_seen") or "", fp))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _evict_for_capacity(issues: Dict[str, dict], order: Deque[str]) -> None:
    fp = _pick_eviction_fingerprint(issues, order)
    if not fp:
        return
    try:
        order.remove(fp)
    except ValueError:
        pass
    old = issues.pop(fp, None)
    if old:
        _append_backup(_serialize_issue(old), "capacity")


def _find_issue_in_buckets(issue_id: str) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    for bucket, path in (("active", _ACTIVE_FILE), ("archived", _ARCHIVED_FILE)):
        issues, _, _ = _load_bucket(path)
        for fp, i in issues.items():
            if i.get("id") == issue_id:
                return bucket, fp, i
    return None, None, None


def _filter_issues(
    issues: Dict[str, dict],
    *,
    service: Optional[str],
    status_filter: Optional[str],
    q: Optional[str],
) -> List[dict]:
    out = [_issue_to_dict(i) for i in issues.values()]
    if service:
        out = [i for i in out if i.get("tags", {}).get("service") == service]
    sf = (status_filter or "").strip().upper()
    if sf == "ACTIVE":
        out = [i for i in out if (i.get("status") or "OPEN").upper() != "ARCHIVED"]
    elif sf:
        out = [i for i in out if (i.get("status") or "").upper() == sf]
    if q:
        needle = q.strip().lower()
        if needle:

            def _match(issue: dict) -> bool:
                parts = [
                    str(issue.get("id") or ""),
                    str(issue.get("status") or ""),
                    str(issue.get("severity") or ""),
                    str(issue.get("assignee") or ""),
                    " ".join(issue.get("labels") or []),
                    str((issue.get("tags") or {}).get("service") or ""),
                ]
                parts.extend(str(s) for s in (issue.get("samples") or [])[:3])
                return needle in " ".join(parts).lower()

            out = [i for i in out if _match(i)]
    status_rank = {"OPEN": 0, "ACK": 1, "RESOLVED": 2, "ARCHIVED": 3}
    out.sort(key=lambda x: x.get("last_seen") or "", reverse=True)
    out.sort(key=lambda x: status_rank.get((x.get("status") or "OPEN").upper(), 9))
    return out


def migrate_legacy() -> None:
    """Eski .run/issues_active.json + issues_archive.jsonl → .run/issues/."""
    _ensure_dirs()
    if _LEGACY_ACTIVE.exists() and not _ACTIVE_FILE.exists():
        try:
            data = json.loads(_LEGACY_ACTIVE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data.get("issues") or {}
                active_raw: Dict[str, Any] = {}
                archived_raw: Dict[str, Any] = {}
                active_order: List[str] = []
                archived_order: List[str] = []
                for fp in data.get("order") or list(raw.keys()):
                    rec = raw.get(fp)
                    if not rec:
                        continue
                    st = (rec.get("status") or "OPEN").upper()
                    if st == "ARCHIVED":
                        archived_raw[fp] = rec
                        archived_order.append(fp)
                    else:
                        active_raw[fp] = rec
                        active_order.append(fp)
                for fp, rec in raw.items():
                    if fp in active_raw or fp in archived_raw:
                        continue
                    st = (rec.get("status") or "OPEN").upper()
                    if st == "ARCHIVED":
                        archived_raw[fp] = rec
                        archived_order.append(fp)
                    else:
                        active_raw[fp] = rec
                        active_order.append(fp)
                counter = int(data.get("counter") or 0)
                _atomic_write_json(
                    _ACTIVE_FILE,
                    {"counter": counter, "order": active_order, "issues": active_raw, "saved_at": _now_tr_iso()},
                )
                _atomic_write_json(
                    _ARCHIVED_FILE,
                    {"counter": counter, "order": archived_order, "issues": archived_raw, "saved_at": _now_tr_iso()},
                )
        except Exception as e:
            logger.warning("legacy issues_active migration failed: %s", e)
    if _LEGACY_BACKUP.exists() and not _BACKUP_FILE.exists():
        try:
            _BACKUP_FILE.write_bytes(_LEGACY_BACKUP.read_bytes())
        except Exception as e:
            logger.warning("legacy issues_archive migration failed: %s", e)
    meta = _load_meta()
    if not meta.get("counter"):
        active_issues, _, active_counter = _load_bucket(_ACTIVE_FILE)
        archived_issues, _, archived_counter = _load_bucket(_ARCHIVED_FILE)
        max_id = max(active_counter, archived_counter, 0)
        for i in list(active_issues.values()) + list(archived_issues.values()):
            max_id = max(max_id, _parse_issue_id_num(i.get("id")))
        meta["counter"] = max_id
    _refresh_meta_counts(meta)
    _bump_revision(meta)
    _save_meta(meta)


def init_store() -> None:
    migrate_legacy()


def get_issue_stats() -> dict:
    with _lock:
        meta = _load_meta()
        counts = dict(meta.get("counts") or {})
        if not counts:
            _refresh_meta_counts(meta)
            counts = dict(meta.get("counts") or {})
        return counts


def get_issues(
    service: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    q: Optional[str] = None,
) -> List[dict]:
    limit = max(1, min(200, limit))
    sf = (status_filter or "").strip().upper()
    with _lock:
        if sf == "ARCHIVED":
            issues, _, _ = _load_bucket(_ARCHIVED_FILE)
        else:
            issues, _, _ = _load_bucket(_ACTIVE_FILE)
        out = _filter_issues(issues, service=service, status_filter=status_filter, q=q)
        return out[:limit]


def get_issues_archive(
    limit: int = 100,
    q: Optional[str] = None,
    offset: int = 0,
    service: Optional[str] = None,
) -> dict:
    limit = max(1, min(500, limit))
    offset = max(0, offset)
    needle = (q or "").strip().lower()

    def _match(rec: dict) -> bool:
        if service and (rec.get("tags") or {}).get("service") != service:
            return False
        if needle:
            hay = " ".join([
                str(rec.get("id") or ""),
                str(rec.get("status") or ""),
                str(rec.get("severity") or ""),
                str((rec.get("tags") or {}).get("service") or ""),
                " ".join(str(s) for s in (rec.get("samples") or [])[:2]),
            ]).lower()
            if needle not in hay:
                return False
        return True

    with _lock:
        items, scanned_total = _query_jsonl_archive(_BACKUP_FILE, limit, offset, _match)
        return {
            "items": items,
            "total": _count_jsonl_lines_cached(_BACKUP_FILE) if not needle and not service else scanned_total,
            "limit": limit,
            "offset": offset,
            "path": str(_BACKUP_FILE),
        }


def get_issue_by_id(issue_id: str) -> Optional[dict]:
    with _lock:
        _, _, issue = _find_issue_in_buckets(issue_id)
        if issue:
            return _issue_to_dict(issue)
        items, _ = _query_jsonl_archive(
            _BACKUP_FILE,
            limit=50,
            offset=0,
            match_fn=lambda rec: rec.get("id") == issue_id,
            max_scan=ARCHIVE_QUERY_SCAN,
        )
        return items[0] if items else None


def ingest_issue(key: str, line: str, level: str, *, on_new_error=None) -> None:
    from manager_server.state import _fingerprint_line, _push_status_history, _truncate_line, LOG_LINE_MAX

    fp = _fingerprint_line(line)
    now_iso = _now_tr_iso()
    with _lock:
        meta = _load_meta()
        issues, order, counter = _load_bucket(_ACTIVE_FILE)
        if fp in issues:
            i = issues[fp]
            i["last_seen"] = now_iso
            i["count"] = i.get("count", 0) + 1
            samples = i.get("samples", [])
            if line not in samples[-MAX_ISSUE_SAMPLES:]:
                samples.append(_truncate_line(line, LOG_LINE_MAX))
                i["samples"] = samples[-MAX_ISSUE_SAMPLES:]
        else:
            while len(issues) >= MAX_ISSUES:
                _evict_for_capacity(issues, order)
            counter = max(counter, int(meta.get("counter") or 0)) + 1
            meta["counter"] = counter
            iid = "ISS-%06d" % counter
            order.append(fp)
            issues[fp] = {
                "id": iid,
                "fingerprint": fp,
                "severity": level,
                "status": "OPEN",
                "first_seen": now_iso,
                "last_seen": now_iso,
                "count": 1,
                "samples": [_truncate_line(line, LOG_LINE_MAX)],
                "tags": {"service": key},
                "assignee": None,
                "labels": [],
                "sla_note": None,
                "comments": deque(maxlen=ISSUE_COMMENT_MAX),
                "status_history": deque(maxlen=ISSUE_STATUS_HIST_MAX),
            }
            _push_status_history(issues[fp], "OPEN")
            if level == "ERROR" and on_new_error:
                on_new_error(iid, key, line)
        _save_bucket(_ACTIVE_FILE, issues, order, counter)
        _refresh_meta_counts(meta)
        _bump_revision(meta)
        _save_meta(meta)


def _mutate_issue(issue_id: str, mutator: Callable[[dict], None]) -> Optional[dict]:
    with _lock:
        bucket, fp, issue = _find_issue_in_buckets(issue_id)
        if not issue or not bucket or not fp:
            return None
        path = _ACTIVE_FILE if bucket == "active" else _ARCHIVED_FILE
        issues, order, counter = _load_bucket(path)
        target = issues.get(fp)
        if not target or target.get("id") != issue_id:
            return None
        mutator(target)
        _save_bucket(path, issues, order, counter)
        meta = _load_meta()
        _refresh_meta_counts(meta)
        _bump_revision(meta)
        _save_meta(meta)
        return _issue_to_dict(target)


def issue_ack(issue_id: str) -> Optional[dict]:
    from manager_server.state import _push_status_history

    def _m(i: dict) -> None:
        i["status"] = "ACK"
        _push_status_history(i, "ACK")

    return _mutate_issue(issue_id, _m)


def issue_resolve(issue_id: str) -> Optional[dict]:
    from manager_server.state import _push_status_history

    def _m(i: dict) -> None:
        i["status"] = "RESOLVED"
        _push_status_history(i, "RESOLVED")

    return _mutate_issue(issue_id, _m)


def issue_archive(issue_id: str) -> Optional[dict]:
    from manager_server.state import _push_status_history

    with _lock:
        bucket, fp, issue = _find_issue_in_buckets(issue_id)
        if not issue or not bucket or not fp or bucket != "active":
            return None
        active_issues, active_order, active_counter = _load_bucket(_ACTIVE_FILE)
        target = active_issues.pop(fp, None)
        if not target:
            return None
        try:
            active_order.remove(fp)
        except ValueError:
            pass
        target["status"] = "ARCHIVED"
        target["archived_at"] = _now_tr_iso()
        _push_status_history(target, "ARCHIVED")
        archived_issues, archived_order, archived_counter = _load_bucket(_ARCHIVED_FILE)
        archived_issues[fp] = target
        if fp not in archived_order:
            archived_order.append(fp)
        archived_counter = max(archived_counter, active_counter)
        _save_bucket(_ACTIVE_FILE, active_issues, active_order, active_counter)
        _save_bucket(_ARCHIVED_FILE, archived_issues, archived_order, archived_counter)
        meta = _load_meta()
        _refresh_meta_counts(meta)
        _bump_revision(meta)
        _save_meta(meta)
        return _issue_to_dict(target)


def issue_reopen(issue_id: str) -> Optional[dict]:
    from manager_server.state import _push_status_history

    with _lock:
        bucket, fp, issue = _find_issue_in_buckets(issue_id)
        if not issue or not bucket or not fp or bucket != "archived":
            return None
        archived_issues, archived_order, archived_counter = _load_bucket(_ARCHIVED_FILE)
        target = archived_issues.pop(fp, None)
        if not target:
            return None
        try:
            archived_order.remove(fp)
        except ValueError:
            pass
        target["status"] = "OPEN"
        target.pop("archived_at", None)
        _push_status_history(target, "REOPENED")
        active_issues, active_order, active_counter = _load_bucket(_ACTIVE_FILE)
        while len(active_issues) >= MAX_ISSUES:
            _evict_for_capacity(active_issues, active_order)
        active_issues[fp] = target
        if fp not in active_order:
            active_order.append(fp)
        active_counter = max(active_counter, archived_counter)
        _save_bucket(_ARCHIVED_FILE, archived_issues, archived_order, archived_counter)
        _save_bucket(_ACTIVE_FILE, active_issues, active_order, active_counter)
        meta = _load_meta()
        _refresh_meta_counts(meta)
        _bump_revision(meta)
        _save_meta(meta)
        return _issue_to_dict(target)


def issue_assign(issue_id: str, assignee: Optional[str]) -> Optional[dict]:
    val = (assignee or "").strip() or None

    def _m(i: dict) -> None:
        i["assignee"] = val

    return _mutate_issue(issue_id, _m)


def issue_labels(issue_id: str, labels: list) -> Optional[dict]:
    clean = [str(x).strip()[:64] for x in (labels or [])[:10]]

    def _m(i: dict) -> None:
        i["labels"] = clean

    return _mutate_issue(issue_id, _m)


def issue_comment(issue_id: str, text: str, author: str = "local") -> Optional[dict]:
    text = (text or "").strip()[:500]
    if not text:
        return get_issue_by_id(issue_id)
    now_iso = _now_tr_iso()
    entry = {"ts": now_iso, "author": (author or "local")[:64], "text": text}

    def _m(i: dict) -> None:
        comm = i.get("comments")
        if not isinstance(comm, deque):
            i["comments"] = deque(maxlen=ISSUE_COMMENT_MAX)
            comm = i["comments"]
        comm.append(entry)

    return _mutate_issue(issue_id, _m)


def issue_sla(issue_id: str, sla_note: Optional[str]) -> Optional[dict]:
    val = (sla_note or "").strip() or None

    def _m(i: dict) -> None:
        i["sla_note"] = val

    return _mutate_issue(issue_id, _m)
