#!/usr/bin/env python3
"""
Snapshot load stress test.
Spawns 20 concurrent async requests to /api/dashboard/snapshot, 50 iterations.
Prints: avg latency, p95, error rate.
Targets: avg < 800ms local, p95 < 1200ms.
Usage: TOKEN=xxx python scripts/perf_snapshot_test.py [--base http://127.0.0.1:8000] [--account 1]
"""

from __future__ import annotations
import argparse
import asyncio
import os
import statistics
import sys
import time

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT = 1
CONCURRENCY = 20
ITERATIONS = 50
TARGET_AVG_MS = 800
TARGET_P95_MS = 1200


async def fetch_one(
    client: httpx.AsyncClient, url: str, headers: dict
) -> tuple[float, bool]:
    """Single request; returns (latency_ms, success)."""
    t0 = time.perf_counter()
    try:
        r = await client.get(url, headers=headers, timeout=10.0)
        elapsed = (time.perf_counter() - t0) * 1000
        return elapsed, r.status_code == 200
    except Exception:
        elapsed = (time.perf_counter() - t0) * 1000
        return elapsed, False


async def run_iteration(
    client: httpx.AsyncClient, url: str, headers: dict
) -> list[tuple[float, bool]]:
    """20 concurrent requests in one iteration."""
    tasks = [fetch_one(client, url, headers) for _ in range(CONCURRENCY)]
    return await asyncio.gather(*tasks)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("BASE_URL", DEFAULT_BASE))
    parser.add_argument(
        "--account", type=int, default=int(os.getenv("ACCOUNT_ID", DEFAULT_ACCOUNT))
    )
    parser.add_argument("--iterations", type=int, default=ITERATIONS)
    parser.add_argument("--n", type=int, help="Alias for --iterations")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    args = parser.parse_args()
    if args.n is not None:
        args.iterations = args.n

    token = os.getenv("TOKEN") or os.getenv("AUTH_TOKEN")
    if not token:
        print("Set TOKEN or AUTH_TOKEN")
        sys.exit(1)

    url = f"{args.base.rstrip('/')}/api/dashboard/snapshot?account_id={args.account}&fields=prices,kpis"
    headers = {"Authorization": f"Bearer {token}"}

    latencies: list[float] = []
    errors = 0

    async with httpx.AsyncClient() as client:
        for i in range(args.iterations):
            results = await run_iteration(client, url, headers)
            for elapsed, ok in results:
                latencies.append(elapsed)
                if not ok:
                    errors += 1

    total = len(latencies)
    ok_count = total - errors
    error_rate = errors / total * 100 if total else 0
    avg_ms = statistics.mean(latencies) if latencies else 0
    sorted_lat = sorted(latencies)
    p95_ms = (
        sorted_lat[int(0.95 * len(sorted_lat)) - 1]
        if len(sorted_lat) >= 20
        else (sorted_lat[-1] if sorted_lat else 0)
    )

    print("SNAPSHOT_STRESS_RESULTS")
    print(f"  requests: {total}")
    print(f"  ok: {ok_count}  errors: {errors}")
    print(f"  error_rate: {error_rate:.2f}%")
    print(f"  avg_latency_ms: {avg_ms:.2f}")
    print(f"  p95_latency_ms: {p95_ms:.2f}")
    print(f"  target_avg_ms: {TARGET_AVG_MS}")
    print(f"  target_p95_ms: {TARGET_P95_MS}")

    if avg_ms <= TARGET_AVG_MS and p95_ms <= TARGET_P95_MS:
        print("  status: PASS")
    else:
        print("  status: FAIL (exceeds targets)")


if __name__ == "__main__":
    asyncio.run(main())
