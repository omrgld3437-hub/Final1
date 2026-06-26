"""
Parametre optimizasyonu için async job registry.

Tek analiz modu (professional_auto). Full CPU + 30dk-6sa (kanıt kalitesine göre).
İş tek HTTP isteğine sığmadığından job modeli: POST -> job_id, GET ile ilerleme/ETA/sonuç poll.

Yürütme:
  * status=fetching : (async) derin geçmiş çekilir (ilerleme akar)
  * status=running  : (thread'de) run_optimization — kendi process pool'unu açar,
                      event loop'u bloklamaz; ilerleme + ETA job'a yazılır
  * status=done/error
Eşzamanlı optimizasyon sayısı semafor ile sınırlı (her biri tüm çekirdekleri
kullanabildiği için aşırı-abonelik olmasın).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.param_optimizer.cancel import ParamOptimizerCancelled
from app.services.param_optimizer.engine import RESULT_SCHEMA_VERSION
from app.services.param_optimizer.tiers import AnalysisTier, get_tier, estimate_seconds

logger = logging.getLogger(__name__)

_JOBS: Dict[str, "OptJob"] = {}
_JOBS_LOCK = asyncio.Lock()
_RUN_SEM = asyncio.Semaphore(1)  # aynı anda 1 optimizasyon
_CANCELLED_JOB_IDS: set[str] = set()
_JOB_TTL_SEC = int(os.getenv("PARAM_OPTIMIZER_JOB_TTL_SEC", str(36 * 3600)))
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_JOB_STORE_DIR = Path(
    os.getenv(
        "PARAM_OPTIMIZER_JOB_DIR",
        str(_PROJECT_ROOT / "data" / "param_optimizer_jobs"),
    )
)
# P2: süreç izlenebilirliği — her iş için ayrı structured JSONL log. JSON sonuç
# kaydı debug için zaten var ama "hangi aşamada ne oldu" akışını göstermiyordu.
_JOB_LOG_DIR = Path(
    os.getenv("PARAM_OPTIMIZER_LOG_DIR", str(_PROJECT_ROOT / "logs" / "param_assistant"))
)
_MAX_AUTO_WORKERS = 4  # kullanılmıyor; gerçek çekirdek politikası parallel.resolve_workers

# Sert güvenlik zaman aşımları: motor kendi bütçesini aşar/takılırsa son emniyet.
# run_optimization zaten kendi içinde time_budget_sec'i deadline ile uyguluyor;
# bu, o da çökerse modalın sonsuza kadar "çalışıyor" kalmaması için backstop.
_RUN_GRACE_SEC = float(os.getenv("PARAM_OPTIMIZER_RUN_GRACE_SEC", "600"))
_FETCH_LIMIT_SEC = float(os.getenv("PARAM_OPTIMIZER_FETCH_TIMEOUT_SEC", "900"))


@contextlib.contextmanager
def _owner_file_lock(owner_key: str):
    """Cross-worker lock: one active Param Assistant job per account."""
    if not owner_key:
        yield
        return
    import fcntl

    _JOB_STORE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(owner_key.encode("utf-8")).hexdigest()[:16]
    lock_path = _JOB_STORE_DIR / f".owner-{digest}.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _reap_pool_children() -> None:
    """Bu süreç altında kalan takılı optimizasyon worker süreçlerini sonlandır.

    Canlı motor (robust_engine) tek-thread çalışır; ama eski/yan kodlardan kalan
    ProcessPool ('multiprocessing-fork'/'spawn_main') çocukları takılırsa burada
    güvenle reap edilir. Trading worker'ı ayrı süreç olduğundan etkilenmez.
    """
    import signal
    import subprocess

    mypid = os.getpid()
    killed = 0
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception as e:
        logger.debug("param_optimizer reap ps: %s", e)
        return
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, ppid_s, cmd = parts
        if ppid_s != str(mypid):
            continue
        if "multiprocessing" not in cmd and "spawn_main" not in cmd:
            continue
        try:
            os.kill(int(pid_s), signal.SIGTERM)
            killed += 1
        except (ProcessLookupError, ValueError, PermissionError):
            pass
    if killed:
        logger.warning(
            "param_optimizer: %d takılı worker süreci sonlandırıldı (zaman aşımı)",
            killed,
        )

# stage -> taban yüzde (ilerleme barı)
_STAGE_BASE = {
    "queued": 1,
    "fetch": 4,
    "features": 14,
    "split": 16,
    "measure": 18,
    "optimize": 19,
    "coarse": 22,
    "refine": 55,
    "converged": 84,
    "validate": 86,
    "forecast": 90,
    "done": 100,
}
_STAGE_ORDER = {stage: idx for idx, stage in enumerate(_STAGE_BASE.keys())}


@dataclass
class OptJob:
    id: str
    symbol: str
    budget: float
    time_budget_sec: float
    tier: str = "professional_auto"
    tier_label: str = ""
    cores: int = 1
    status: str = "queued"  # queued|fetching|running|done|error|cancelled
    percent: int = 0
    stage: str = "queued"
    message: str = "sıraya alındı"
    detail: str = ""
    best_score: Optional[float] = None
    elapsed_sec: float = 0.0
    eta_total_sec: float = 0.0
    eta_remaining_sec: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_run_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    owner_key: str = ""  # hesap/kullanıcı sahipliği: "acc:<id>" | "usr:<id>"
    config_hash: str = ""  # request_config_hash(symbol,budget,tier): bayat-sonuç engeli
    consumed: bool = False  # bitmiş sonuç tek-sefer gösterildi mi (one-shot)
    cancel_requested: bool = False
    completed_at: Optional[float] = None  # done/error damgası (sonuca da yansır)
    meta: Dict[str, Any] = field(default_factory=dict)

    def public(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.status != "done":
            d["result"] = None
        return d


def _touch(job: OptJob) -> None:
    if getattr(job, "id", "") in _CANCELLED_JOB_IDS or getattr(job, "cancel_requested", False):
        try:
            _job_path(job.id).unlink()
        except OSError:
            pass
        return
    job.updated_at = time.time()
    _persist_job(job)


def _job_path(job_id: str) -> Path:
    safe = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in ("_", "-"))
    return _JOB_STORE_DIR / f"{safe}.json"


def _persist_job(job: OptJob) -> None:
    try:
        _JOB_STORE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_job_path(job.id), "w") as fh:
            json.dump(job.public(), fh, ensure_ascii=False, default=str)
    except Exception as e:
        logger.debug("param_optimizer job persist fail %s: %s", job.id, e)


def _job_log_path(job_id: str) -> Path:
    safe = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in ("_", "-"))
    return _JOB_LOG_DIR / f"{safe}.jsonl"


def _append_job_log(job_id: str, record: Dict[str, Any]) -> None:
    """Tek satır structured log ekle. Best-effort: hiçbir hata işi durdurmaz/raise etmez."""
    try:
        _JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"ts": round(time.time(), 3), "job_id": job_id, **record}
        with open(_job_log_path(job_id), "a") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug("param_optimizer job log append fail %s: %s", job_id, e)


def _log_job_gate_and_final(job_id: str, result: Dict[str, Any]) -> None:
    """P2: run_optimization tamamlanınca aday/gate/karar özetini JSONL'e yaz.

    Her validasyondan geçen adayı tek tek loglamak (300-600 aday) hot-path'i
    şişirir; bunun yerine leaderboard (top-12, her biri zaten reject_reason +
    deployable taşır) + final deploy_gate + nihai karar tek seferde yazılır —
    "hangi aday neden elendi, sonuç ne" sorusunu yanıtlamak için yeterli."""
    try:
        for entry in (result.get("leaderboard") or [])[:12]:
            _append_job_log(job_id, {
                "stage": "candidate",
                "structure": entry.get("structure"),
                "deployable": entry.get("deployable"),
                "reject_reason": entry.get("reject_reason"),
                "oos_return_pct": entry.get("oos_return_pct"),
                "combined_score": entry.get("combined_score"),
            })
        rejected = result.get("rejected_best_candidate")
        if rejected:
            _append_job_log(job_id, {
                "stage": "candidate",
                "structure": rejected.get("structure"),
                "deployable": False,
                "reject_reason": rejected.get("reject_reason"),
            })
        gate = result.get("deploy_gate") or {}
        _append_job_log(job_id, {
            "stage": "gate",
            "deploy": gate.get("deploy"),
            "failed_checks": gate.get("reasons"),
            "pbo": result.get("pbo"),
            "deflated_sharpe_ok": result.get("deflated_sharpe_ok"),
            "plateau_ok": result.get("plateau_ok"),
            "stress_ok": result.get("stress_ok"),
        })
        fr = result.get("final_recommendation") or {}
        dec = result.get("decision") or {}
        _append_job_log(job_id, {
            "stage": "final",
            "result_type": result.get("result_type", "ok"),
            "decision": fr.get("decision"),
            "reason_code": dec.get("reason_code"),
            "blocking_reasons": fr.get("blocking_reasons"),
            "headline": fr.get("headline"),
        })
    except Exception as e:
        logger.debug("param_optimizer job log gate/final fail %s: %s", job_id, e)


def _load_persisted_job(job_id: str) -> Optional[OptJob]:
    if str(job_id or "") in _CANCELLED_JOB_IDS:
        return None
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
        if time.time() - float(raw.get("updated_at", 0)) > _JOB_TTL_SEC:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        fields = OptJob.__dataclass_fields__
        payload = {k: raw.get(k) for k in fields.keys() if k in raw}
        job = OptJob(**payload)
        if job.status in ("queued", "fetching", "running") and time.time() - job.updated_at > 180:
            job.status = "error"
            job.error = "Analiz işi sunucu yeniden başlatıldığı veya kesildiği için tamamlanamadı. Lütfen yeniden başlat."
            job.message = "analiz yeniden başlatılmalı"
            _touch(job)
        return job
    except Exception as e:
        logger.debug("param_optimizer job load fail %s: %s", job_id, e)
        return None


def _resolve_worker_count(tier: AnalysisTier, requested: int = 0) -> int:
    """Idle-aware CPU: boştaysa çekirdeklerin neredeyse tümünü (cpu-1) kullan;
    sistem meşgulse (yüksek 1-dk load) güvenli tabana çekil — tek-süreçli sunucunun
    event loop'u aç kalmasın. Env override: PARAM_OPTIMIZER_WORKERS.

    Politika tek yerde (parallel.resolve_workers) toplanır; asıl paralel yürütme de
    aynı fonksiyonu kullandığı için gösterilen çekirdek sayısı gerçekle tutarlıdır."""
    from app.services.param_optimizer import parallel

    return parallel.resolve_workers(requested, idle_aware=True)


def _progress_from(job: OptJob, ev: Dict[str, Any]) -> None:
    """engine/search/fetch progress_cb -> job durumu (thread'den çağrılır)."""
    _raise_if_cancelled(job)
    stage = ev.get("stage") or job.stage
    prev_stage = job.stage
    prev_order = _STAGE_ORDER.get(prev_stage, 0)
    new_order = _STAGE_ORDER.get(stage, prev_order)
    regressed = new_order < prev_order
    if regressed:
        # Eski/gecikmiş bir callback daha ileri aşamadaki canlı işi geriye
        # düşürmesin. Aksi halde UI'da forecast sürerken "test hazırlanıyor"
        # ve skor 0 gibi stale bilgiler yanıp söner.
        elapsed = ev.get("elapsed")
        if elapsed is not None:
            try:
                job.elapsed_sec = max(float(job.elapsed_sec or 0.0), float(elapsed))
            except (TypeError, ValueError):
                pass
        return
    else:
        if stage != prev_stage:
            # P2: her gerçek aşama geçişini structured log'a yaz (tek satır;
            # aynı aşamadaki tekrarlayan ilerleme tikleri YAZILMAZ — gürültü olur).
            _append_job_log(job.id, {
                k: v for k, v in {
                    "stage": stage,
                    "elapsed": ev.get("elapsed"),
                    "message": ev.get("message"),
                    "train_bars": ev.get("train_bars"),
                    "oos_bars": ev.get("oos_bars"),
                    "recent_in_bars": ev.get("recent_in_bars"),
                    "final_holdout_bars": ev.get("final_holdout_bars"),
                    "regime": ev.get("regime"),
                    "candidates": ev.get("candidates"),
                }.items() if v is not None
            })
        job.stage = stage
    base = _STAGE_BASE.get(stage, job.percent)
    pct = base
    elapsed = ev.get("elapsed")
    if elapsed is not None:
        job.elapsed_sec = float(elapsed)
    if ev.get("eta_remaining_sec") is not None:
        job.eta_remaining_sec = float(ev["eta_remaining_sec"])
    # coarse/refine içinde elapsed/bütçe ile ara yüzde
    if (
        stage in ("coarse", "refine")
        and elapsed is not None
        and job.time_budget_sec > 0
    ):
        frac = min(1.0, float(elapsed) / job.time_budget_sec)
        lo = _STAGE_BASE["coarse"] if stage == "coarse" else _STAGE_BASE["refine"]
        hi = _STAGE_BASE["refine"] if stage == "coarse" else _STAGE_BASE["converged"]
        pct = int(
            lo + (hi - lo) * (frac if stage == "coarse" else max(0.0, frac - 0.5) * 2)
        )
        pct = max(base, min(hi, pct))
    elif stage == "validate":
        try:
            total = int(ev.get("candidates") or 0)
            done = int(ev.get("candidates_done") or 0)
        except (TypeError, ValueError):
            total, done = 0, 0
        if total > 0 and done >= 0:
            frac = max(0.0, min(1.0, done / total))
            pct = int(_STAGE_BASE["validate"] + (_STAGE_BASE["forecast"] - _STAGE_BASE["validate"]) * frac)
    elif stage == "forecast":
        try:
            c_total = int(ev.get("mc_candidate_total") or ev.get("candidates") or 0)
            c_idx = int(ev.get("mc_candidate_index") or 1)
            p_total = int(ev.get("mc_total") or ev.get("paths") or 0)
            p_done = int(ev.get("mc_done") or 0)
        except (TypeError, ValueError):
            c_total, c_idx, p_total, p_done = 0, 1, 0, 0
        if c_total > 0 and p_total > 0:
            c_idx = max(1, min(c_idx, c_total))
            p_done = max(0, min(p_done, p_total))
            done_units = (c_idx - 1) * p_total + p_done
            frac = max(0.0, min(1.0, done_units / max(1, c_total * p_total)))
            pct = int(_STAGE_BASE["forecast"] + (99 - _STAGE_BASE["forecast"]) * frac)
    job.percent = max(job.percent, int(pct))
    if ev.get("best_score") is not None:
        job.best_score = ev.get("best_score")
    progress_keys = (
        "stage",
        "message",
        "elapsed",
        "eta_remaining_sec",
        "evaluated",
        "best_score",
        "candidates",
        "candidates_done",
        "bars",
        "appended",
        "paths",
        "mc_done",
        "mc_total",
        "mc_candidate_index",
        "mc_candidate_total",
        "train_bars",
        "oos_bars",
        "recent_in_bars",
        "regime",
        "radius",
        "tier",
        "per_eval_sec",
        "workers",
        "base_score",
    )
    progress = {k: ev.get(k) for k in progress_keys if ev.get(k) is not None}
    progress["stage"] = stage
    progress["percent"] = job.percent
    job.meta["last_progress"] = progress
    msg = ev.get("message")
    if regressed:
        pass
    elif stage == "fetch":
        job.message = "geçmiş veri çekiliyor"
        if msg:
            job.detail = msg
    elif msg:
        job.message = msg
        if stage in ("validate", "forecast"):
            job.detail = msg
    elif stage == "coarse":
        job.message = (
            f"parametre uzayı taranıyor ({ev.get('evaluated', '?')} kombinasyon)"
        )
        job.detail = f"en iyi skor: {ev.get('best_score', '—')}"
    elif stage == "refine":
        job.message = "en iyi adaylar inceltiliyor"
        job.detail = f"en iyi skor: {ev.get('best_score', '—')}"
    elif stage == "validate":
        job.message = "adaylar görülmemiş veride (OOS) doğrulanıyor"
        cand = ev.get("candidates")
        job.detail = f"{cand} aday doğrulanıyor" if cand is not None else ""
    elif stage == "forecast":
        job.message = "gelecek senaryoları simüle ediliyor (Monte Carlo)"
        job.detail = f"{ev.get('candidates', '?')} aday × yüzlerce gelecek yolu"
    # ETA fallback: bütçeye göre
    if job.eta_remaining_sec is None and job.started_run_at and job.time_budget_sec > 0:
        used = time.time() - job.started_run_at
        job.eta_remaining_sec = max(0.0, job.time_budget_sec - used)
    _touch(job)
    _raise_if_cancelled(job)


def _raise_if_cancelled(job: OptJob) -> None:
    if getattr(job, "cancel_requested", False) or job.id in _CANCELLED_JOB_IDS:
        raise ParamOptimizerCancelled("param_optimizer_cancelled")


def _forget_job_file(job_id: str) -> None:
    try:
        _job_path(job_id).unlink()
    except OSError:
        pass


def cancel_job(job_id: str, *, owner_key: str = "") -> Dict[str, Any]:
    """Cancel a job and remove its persisted state."""
    job = get_job(job_id)
    if not job:
        _CANCELLED_JOB_IDS.add(str(job_id or ""))
        _forget_job_file(str(job_id or ""))
        return {"cancelled": False, "removed": True, "job_id": job_id}
    if owner_key and getattr(job, "owner_key", "") != owner_key:
        return {"cancelled": False, "removed": False, "job_id": job_id, "forbidden": True}
    job.cancel_requested = True
    job.status = "cancelled"
    job.message = "kullanıcı tarafından sonlandırıldı"
    job.error = "Analiz kullanıcı tarafından sonlandırıldı."
    _CANCELLED_JOB_IDS.add(job.id)
    _JOBS.pop(job.id, None)
    _forget_job_file(job.id)
    logger.info("param_optimizer job %s cancelled owner=%s", job.id, owner_key or job.owner_key)
    return {"cancelled": True, "removed": True, "job_id": job.id}


def cancel_running_jobs_for_owner(owner_key: str) -> Dict[str, Any]:
    if not owner_key:
        return {"cancelled": 0, "job_ids": []}
    ids = set()
    for j in list(_JOBS.values()):
        if getattr(j, "owner_key", "") == owner_key and j.status in _ACTIVE_STATUSES:
            ids.add(j.id)
    for raw in _iter_persisted_raw() or []:
        if raw.get("owner_key") == owner_key and raw.get("status") in _ACTIVE_STATUSES:
            jid = raw.get("id")
            if jid:
                ids.add(jid)
    out = []
    for jid in ids:
        res = cancel_job(jid, owner_key=owner_key)
        if res.get("cancelled") or res.get("removed"):
            out.append(jid)
    return {"cancelled": len(out), "job_ids": sorted(out)}


async def _run_job(
    job: OptJob, tier: AnalysisTier, *, n_workers: int, fee: float
) -> None:
    from app.services.param_optimizer.history import fetch_history
    from app.services.param_optimizer.engine import run_optimization

    async with _RUN_SEM:
        try:
            _raise_if_cancelled(job)
            job.status = "fetching"
            job.message = "geçmiş veri çekiliyor"
            job.percent = _STAGE_BASE["fetch"]
            _touch(job)

            def fetch_cb(ev: Dict[str, Any]) -> None:
                _progress_from(job, ev)

            try:
                _raise_if_cancelled(job)
                data = await asyncio.wait_for(
                    fetch_history(
                        job.symbol,
                        fine_interval=tier.fine_interval,
                        fine_days=tier.fine_days,
                        coarse_interval=tier.coarse_interval,
                        max_days=tier.max_days,
                        progress_cb=fetch_cb,
                    ),
                    timeout=_FETCH_LIMIT_SEC,
                )
            except asyncio.TimeoutError:
                job.status = "error"
                job.error = (
                    "Geçmiş veri çekme zaman aşımına uğradı (~%d dk). Binance "
                    "bağlantısını kontrol edip tekrar deneyin."
                    % int(_FETCH_LIMIT_SEC / 60)
                )
                job.message = "veri çekme zaman aşımı"
                _touch(job)
                return
            _raise_if_cancelled(job)
            job.meta.update(data.get("meta") or {})
            if (data.get("backtest") and len(data["backtest"]) < 60) or not data.get(
                "daily"
            ):
                job.status = "error"
                job.error = "Yeterli geçmiş veri bulunamadı (parite çok yeni olabilir)."
                _touch(job)
                return

            job.status = "running"
            job.started_run_at = time.time()
            job.message = "optimizasyon başlıyor"
            _touch(job)
            _raise_if_cancelled(job)

            def cb(ev: Dict[str, Any]) -> None:
                _progress_from(job, ev)

            hard_limit = float(job.time_budget_sec) + _RUN_GRACE_SEC
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        run_optimization,
                        job.symbol,
                        job.budget,
                        daily=data["daily"],
                        backtest_candles=data["backtest"],
                        hourly=data.get("hourly"),
                        time_budget_sec=job.time_budget_sec,
                        n_workers=n_workers,
                        fee=fee,
                        tier=tier,
                        progress_cb=cb,
                    ),
                    timeout=hard_limit,
                )
            except ParamOptimizerCancelled:
                logger.info("param_optimizer job %s stopped after cancel signal", job.id)
                cancel_job(job.id, owner_key=job.owner_key)
                return
            except asyncio.TimeoutError:
                # Motor bütçe+payı aşıp takıldı (beklenmedik): güvenle sonlandır.
                _reap_pool_children()
                job.status = "error"
                job.error = (
                    "Analiz güvenlik zaman aşımına uğradı (~%d dk) ve durduruldu. "
                    "Büyük olasılıkla gelecek simülasyonu (Monte Carlo) aşaması "
                    "beklenenden uzun sürdü. Daha düşük bir analiz seviyesiyle "
                    "tekrar deneyebilirsin." % int(hard_limit / 60)
                )
                job.message = "zaman aşımı — analiz durduruldu"
                _touch(job)
                logger.warning(
                    "param_optimizer job %s hard-timeout (%.0fs) — sonlandırıldı",
                    job.id,
                    hard_limit,
                )
                return
            _raise_if_cancelled(job)
            if not result.get("ok"):
                job.status = "error"
                job.error = result.get("error") or "optimizasyon başarısız"
                _touch(job)
                return
            # VERİ BÜTÜNLÜĞÜ: sonuca job-katmanı izlenebilirlik damgalarını ekle.
            # config_hash/market_data_hash/schema_version engine'den gelir; burada
            # job_id ve zaman damgalarını ekleyip config_hash'i garanti altına alırız.
            if isinstance(result, dict):
                result["job_id"] = job.id
                result["created_at"] = job.created_at
                result["completed_at"] = time.time()
                result.setdefault("config_hash", job.config_hash)
                _log_job_gate_and_final(job.id, result)
            job.completed_at = time.time()
            job.result = result
            job.status = "done"
            job.percent = 100
            job.stage = "done"
            job.eta_remaining_sec = 0.0
            job.best_score = (result.get("score") or {}).get("final_score")
            job.message = "tamamlandı"
            job.detail = ""
            _touch(job)
        except ParamOptimizerCancelled:
            logger.info("param_optimizer job %s cancelled", job.id)
            cancel_job(job.id, owner_key=job.owner_key)
        except Exception as e:  # pragma: no cover
            logger.exception("param_optimizer job %s failed", job.id)
            job.status = "error"
            job.error = str(e)
            _touch(job)


async def _gc() -> None:
    now = time.time()
    stale = [jid for jid, j in _JOBS.items() if now - j.updated_at > _JOB_TTL_SEC]
    for jid in stale:
        _JOBS.pop(jid, None)
        try:
            _job_path(jid).unlink()
        except OSError:
            pass


async def create_job(
    symbol: str,
    budget: float,
    *,
    analysis_level: str = "professional_auto",
    n_workers: int = 0,
    fee: float = 0.001,
    time_budget_override: Optional[float] = None,
    owner_key: str = "",
) -> OptJob:
    symbol = (symbol or "").upper().strip()
    budget = float(budget or 0)
    tier = get_tier(analysis_level)
    nw = _resolve_worker_count(tier, n_workers)
    tb = tier.time_budget_sec
    if time_budget_override is not None:
        tb = max(5.0, min(tier.time_budget_sec, float(time_budget_override)))
    est = estimate_seconds(tier, nw)
    cfg_hash = request_config_hash(symbol, budget, tier.key)
    job = OptJob(
        id=uuid.uuid4().hex[:16],
        symbol=symbol,
        budget=budget,
        time_budget_sec=tb,
        tier=tier.key,
        tier_label=tier.label,
        cores=nw,
        owner_key=owner_key or "",
        config_hash=cfg_hash,
        eta_total_sec=est["eta_high_sec"] if time_budget_override is None else tb + 10,
        eta_remaining_sec=est["eta_high_sec"]
        if time_budget_override is None
        else tb + 10,
    )
    with _owner_file_lock(owner_key):
        async with _JOBS_LOCK:
            await _gc()
            if owner_key:
                # YALNIZ aynı config (sembol+bütçe+seviye) için reuse — aksi halde
                # farklı bir analizi mevcut işe bağlamak bayat/yanlış sonuç gösterir.
                existing = get_running_job_for_owner(owner_key, config_hash=cfg_hash)
                if existing is not None:
                    return existing
            _JOBS[job.id] = job
            _touch(job)
    asyncio.create_task(_run_job(job, tier, n_workers=nw, fee=fee))
    return job


_ACTIVE_STATUSES = ("queued", "fetching", "running")


def _iter_persisted_raw():
    """Disk'teki tüm iş JSON'larını oku (çoklu uvicorn worker'ı arası ortak görünüm)."""
    try:
        paths = list(_JOB_STORE_DIR.glob("*.json"))
    except Exception:
        return
    for p in paths:
        try:
            with open(p, "r") as fh:
                yield json.load(fh)
        except Exception:
            continue


def _latest_job_id_for_owner(
    owner_key: str, *, statuses: Optional[set[str]] = None
) -> Optional[str]:
    """Sahibin en güncel işinin id'si (bellek + disk; worker'lar arası güvenli)."""
    if not owner_key:
        return None
    best_id: Optional[str] = None
    best_ts = -1.0
    for j in list(_JOBS.values()):
        if getattr(j, "owner_key", "") != owner_key:
            continue
        if statuses is not None and j.status not in statuses:
            continue
        if j.updated_at > best_ts:
            best_id, best_ts = j.id, j.updated_at
    for raw in _iter_persisted_raw():
        if raw.get("owner_key") != owner_key:
            continue
        if statuses is not None and raw.get("status") not in statuses:
            continue
        ts = float(raw.get("updated_at") or 0)
        if ts > best_ts:
            best_id, best_ts = raw.get("id"), ts
    return best_id


def request_config_hash(symbol: str, budget: float, tier_key: str) -> str:
    """İstek kimliği (sembol+bütçe+seviye). engine.config_hash ile AYNI değeri üretir;
    böylece job-katmanı reuse kararı ile sonuca gömülen hash birebir tutarlıdır."""
    from app.services.param_optimizer.engine import config_hash

    return config_hash(symbol, budget, tier_key)


def get_running_job_for_owner(
    owner_key: str, *, config_hash: Optional[str] = None
) -> Optional[OptJob]:
    """Sahibin halen AKTİF (çalışan) işi varsa döndür (yoksa None).

    config_hash verilirse YALNIZ aynı config'li işi döndürür: farklı sembol/bütçe/
    seviye için çalışan bir işi reuse etmek (bayat/yanlış sonuç) engellenir.
    """
    jid = _latest_job_id_for_owner(owner_key, statuses=set(_ACTIVE_STATUSES))
    if not jid:
        return None
    job = get_job(jid)  # disk'te bayatlamış aktif iş -> error'a çevrilir
    if job and job.status in _ACTIVE_STATUSES:
        if config_hash is not None and getattr(job, "config_hash", "") != config_hash:
            return None
        return job
    return None


def get_owner_attach_state(owner_key: str) -> Dict[str, Any]:
    """Modal yeniden açıldığında ne göstereceğini söyler:
      - running : devam eden işe yeniden bağlan (ilerlemeyi izle)
      - finished: bitmiş öneriyi TEK SEFER göster (sonra consumed)
      - error   : başarısız sonucu+sebebi TEK SEFER göster
      - none    : temiz/boş ekran
    """
    jid = _latest_job_id_for_owner(owner_key)
    if not jid:
        return {"state": "none", "job": None}
    job = get_job(jid)
    if not job:
        return {"state": "none", "job": None}
    if job.status in _ACTIVE_STATUSES:
        return {"state": "running", "job": job.public()}
    if getattr(job, "consumed", False):
        return {"state": "none", "job": None}
    # terminal (done/error) ve henüz tüketilmemiş -> tek-sefer göster, işaretle
    job.consumed = True
    _touch(job)
    return {
        "state": "finished" if job.status == "done" else "error",
        "job": job.public(),
    }


def get_job(job_id: str) -> Optional[OptJob]:
    if str(job_id or "") in _CANCELLED_JOB_IDS:
        return None
    job = _JOBS.get(job_id)
    if job:
        return job
    job = _load_persisted_job(job_id)
    if job:
        _JOBS[job.id] = job
    return job


def running_count() -> int:
    return sum(
        1 for j in _JOBS.values() if j.status in ("queued", "fetching", "running")
    )


def estimate_for(analysis_level: str, n_workers: int = 0) -> Dict[str, Any]:
    """Başlamadan önce tahmini süre + tier bilgisi (onay diyaloğu için)."""
    tier = get_tier(analysis_level)
    nw = _resolve_worker_count(tier, n_workers)
    est = estimate_seconds(tier, nw)
    return {
        "tier": tier.key,
        "label": tier.label,
        "description": tier.description,
        "requires_confirm": tier.requires_confirm,
        "cap_sec": tier.time_budget_sec,
        "cores": nw,
        **est,
    }
