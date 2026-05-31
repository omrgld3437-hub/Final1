"""
Sunucu dış (egress) IP keşfi — startup'ta bir kez + periyodik yenileme.
Binance API whitelist için GET /settings ve connectivity-check'te kullanılır.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = float(os.environ.get("SERVER_PUBLIC_IP_CACHE_TTL_SEC", "3600"))
_REFRESH_INTERVAL_SEC = float(os.environ.get("SERVER_PUBLIC_IP_REFRESH_SEC", "21600"))

_cached_ip: Optional[str] = None
_cached_at: float = 0.0
_refresh_task: Optional[asyncio.Task] = None
_lock = asyncio.Lock()


def _parse_public_ip_response(text: str, is_json: bool = False) -> Optional[str]:
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if is_json:
        try:
            data = json.loads(s)
            ip = (data.get("ip") or "").strip()
            return ip if ip and len(ip) <= 45 else None
        except (TypeError, ValueError):
            return None
    if "\n" in s:
        s = s.split("\n")[0].strip()
    if s and len(s) <= 45 and all(c.isalnum() or c in ".:" for c in s):
        return s
    return None


async def _fetch_fresh_ip() -> Optional[str]:
    timeout = 5.0

    async def _get(client: httpx.AsyncClient, url: str, as_json: bool = False) -> Optional[str]:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                return _parse_public_ip_response(r.text, is_json=as_json)
        except Exception:
            pass
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(
            _get(client, "https://api.ipify.org?format=json", as_json=True),
            _get(client, "https://api.ipify.org?format=text"),
            _get(client, "https://ifconfig.me/ip"),
            _get(client, "https://icanhazip.com"),
        )
    for ip in results:
        if ip:
            return ip
    return None


async def refresh_server_public_ip(*, force: bool = False) -> Optional[str]:
    global _cached_ip, _cached_at
    now = time.time()
    if not force and _cached_ip and (now - _cached_at) < _CACHE_TTL_SEC:
        return _cached_ip
    async with _lock:
        if not force and _cached_ip and (time.time() - _cached_at) < _CACHE_TTL_SEC:
            return _cached_ip
        ip = await _fetch_fresh_ip()
        if ip:
            _cached_ip = ip
            _cached_at = time.time()
            logger.info("server_public_ip resolved: %s", ip)
        else:
            logger.warning("server_public_ip discovery failed (all providers)")
        return _cached_ip


async def get_server_public_ip() -> Optional[str]:
    if _cached_ip and (time.time() - _cached_at) < _CACHE_TTL_SEC:
        return _cached_ip
    return await refresh_server_public_ip()


async def _periodic_refresh_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_REFRESH_INTERVAL_SEC)
            await refresh_server_public_ip(force=True)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("server_public_ip periodic refresh error: %s", e)


def start_server_public_ip_refresh() -> None:
    global _refresh_task

    async def _boot():
        await refresh_server_public_ip(force=True)
        global _refresh_task
        _refresh_task = asyncio.create_task(_periodic_refresh_loop())

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_boot())
    except RuntimeError:
        pass


def stop_server_public_ip_refresh() -> None:
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
    _refresh_task = None
