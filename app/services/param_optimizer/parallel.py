"""
CPU parallelism for the param optimizer — idle-aware, deadline-respecting,
deterministic, with an unconditional serial fallback.

Design constraints
------------------
* The optimizer was 100% single-threaded (the engine even noted "tek-thread MC").
  On an N-core box that left N-1 cores idle. This module lets the two
  embarrassingly-parallel hot loops (candidate validation + Monte-Carlo paths)
  fan out across cores.
* Idle-aware (`resolve_workers`): when the machine is idle use nearly all cores
  (cpu-1); when it is busy back off toward a safe floor so the single-process
  web server stays responsive. Honour `PARAM_OPTIMIZER_WORKERS` / explicit
  request.
* Deadline-safe (`pmap`): the engine guarantees a hard wall-clock budget. The
  pool NEVER blocks past the deadline — on timeout it cancels in-flight futures
  and returns partial results.
* Fail-safe: any pool/pickling/spawn failure → transparent serial execution.
  A worker problem can never fail or hang the optimization.

Workers read large read-only inputs (candle arrays, scenario config) from a
process-global set once by the pool `initializer`, so per-task payloads stay
tiny (just params / a seed).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Process-global shared payload (set by the pool initializer in each worker).
SHARED: Dict[str, Any] = {}


def _init_worker(payload: Dict[str, Any]) -> None:
    """Pool initializer: stash the read-only payload in this worker's globals."""
    global SHARED
    SHARED = payload or {}


def resolve_workers(
    requested: int = 0,
    *,
    idle_aware: bool = True,
    hard_min: int = 1,
) -> int:
    """Resolve the worker count.

    Priority: explicit `requested` > env PARAM_OPTIMIZER_WORKERS > policy.
    Idle-aware policy: free ≈ cpu − load1.
      * idle  → cpu-1 (use almost everything, leave 1 for the event loop)
      * busy  → round(free)-1, floored at 2, capped at cpu-1
    Non-idle policy mirrors the legacy "leave 2 for the server" reservation.
    """
    cpu = max(1, os.cpu_count() or 1)
    if requested and int(requested) > 0:
        return max(hard_min, min(int(requested), cpu))
    raw = os.getenv("PARAM_OPTIMIZER_WORKERS", "").strip()
    if raw:
        try:
            return max(hard_min, min(int(raw), cpu))
        except ValueError:
            logger.warning("PARAM_OPTIMIZER_WORKERS invalid: %r", raw)
    if cpu <= 2:
        return max(hard_min, 1)
    if not idle_aware:
        return max(hard_min, cpu - 2)
    try:
        load1 = float(os.getloadavg()[0])
    except (OSError, AttributeError, ValueError):
        load1 = 0.0
    free = max(0.0, cpu - load1)
    if free >= cpu - 1.0:  # essentially idle
        return max(hard_min, cpu - 1)
    w = int(round(free)) - 1
    return max(hard_min, min(cpu - 1, max(2, w)))


def _run_serial(
    fn: Callable[[Any], Any],
    items: Sequence[Any],
    init: Optional[Callable[..., None]],
    init_args: tuple,
    deadline: Optional[float],
    min_items: int,
) -> List[Any]:
    if init is not None:
        try:
            init(*init_args)
        except Exception as e:  # pragma: no cover
            logger.warning("serial init failed: %s", e)
    out: List[Any] = [None] * len(items)
    for i, it in enumerate(items):
        if deadline is not None and i >= min_items and time.time() >= deadline:
            break
        try:
            out[i] = fn(it)
        except Exception as e:  # pragma: no cover
            logger.debug("serial task %d failed: %s", i, e)
            out[i] = None
    return out


def pmap(
    fn: Callable[[Any], Any],
    items: Sequence[Any],
    *,
    workers: int,
    init: Optional[Callable[..., None]] = None,
    init_args: tuple = (),
    deadline: Optional[float] = None,
    min_items: int = 1,
    serial_threshold: int = 2,
) -> List[Any]:
    """Map `fn` over `items` across `workers` processes, preserving input order.

    `fn` / `init` must be top-level (picklable) callables. Results are aligned to
    `items`; an item that errored or did not finish before `deadline` is `None`.
    Guarantees:
      * never blocks past `deadline` (cancels in-flight futures, returns partial);
      * always runs at least `min_items` (so a forecast is never fully empty);
      * any pool failure → full serial fallback.
    """
    items = list(items)
    n = len(items)
    if n == 0:
        return []
    if workers < 2 or n < max(2, serial_threshold):
        return _run_serial(fn, items, init, init_args, deadline, min_items)

    ex: Optional[ProcessPoolExecutor] = None
    try:
        ex = ProcessPoolExecutor(
            max_workers=int(workers), initializer=init, initargs=init_args
        )
        results: List[Any] = [None] * n
        fut_to_idx = {ex.submit(fn, it): i for i, it in enumerate(items)}
        done = 0
        for fut in list(fut_to_idx):
            i = fut_to_idx[fut]
            if deadline is not None and done >= min_items and time.time() >= deadline:
                break
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.time())
                if remaining <= 0 and done >= min_items:
                    break
            try:
                results[i] = fut.result(timeout=remaining)
            except FutureTimeout:
                break
            except Exception as e:  # task raised
                logger.debug("pmap task %d failed: %s", i, e)
                results[i] = None
            done += 1
        return results
    except Exception as e:
        logger.warning("pmap pool unavailable (%s) — serial fallback", e)
        return _run_serial(fn, items, init, init_args, deadline, min_items)
    finally:
        if ex is not None:
            # Never wait past the deadline: drop in-flight work immediately.
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except TypeError:  # Python < 3.9
                ex.shutdown(wait=False)
