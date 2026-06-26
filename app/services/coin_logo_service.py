"""On-demand coin logo fetch — Trust Wallet, CoinCap, CoinGecko fallbacks."""

from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_RAW = "https://raw.githubusercontent.com/trustwallet/assets/master"
COINCAP_ICON = "https://assets.coincap.io/assets/icons/{sym}@2x.png"
COINGECKO_SEARCH = "https://api.coingecko.com/api/v3/search"

NORMALIZE_SYMBOL = {
    "XBT": "BTC",
    "LUNA2": "LUNA",
    "1000SHIB": "SHIB",
    "1000PEPE": "PEPE",
    "1000FLOKI": "FLOKI",
    "1000LUNC": "LUNC",
    "1000BONK": "BONK",
    "1000RATS": "RATS",
    "1000SATS": "SATS",
}

_tw_paths_cache: Optional[Dict[str, str]] = None
_memory_missing: set[str] = set()


def coins_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "ui" / "assets" / "coins"


def normalize_logo_symbol(symbol: str) -> Optional[str]:
    if not symbol:
        return None
    s = str(symbol).upper().strip()
    quote_only = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP"}
    if s in quote_only:
        return s
    for q in ("USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"):
        if s.endswith(q):
            s = s[: -len(q)]
            break
    s = NORMALIZE_SYMBOL.get(s, s)
    if not s or not re.fullmatch(r"[A-Z0-9]{1,20}", s):
        return None
    return s


def _missing_marker(key: str) -> Path:
    return coins_dir() / f".missing_{key}"


def is_logo_missing(key: str) -> bool:
    if key in _memory_missing:
        return True
    return _missing_marker(key).is_file()


def _mark_missing(key: str) -> None:
    _memory_missing.add(key)
    try:
        coins_dir().mkdir(parents=True, exist_ok=True)
        _missing_marker(key).write_text("1", encoding="utf-8")
    except OSError as e:
        logger.debug("coin logo missing marker write failed %s: %s", key, e)


def _tw_paths() -> Dict[str, str]:
    global _tw_paths_cache
    if _tw_paths_cache is not None:
        return _tw_paths_cache
    merged: Dict[str, str] = {}
    try:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "maintenance"
            / "fetch_binance_coin_logos.py"
        )
        if script.is_file():
            spec = importlib.util.spec_from_file_location("_tw_logo_paths", script)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                merged.update(getattr(mod, "NATIVE_CHAIN_PATHS", {}) or {})
                merged.update(getattr(mod, "TOKEN_PATHS", {}) or {})
    except Exception as e:
        logger.debug("Trust Wallet path map load failed: %s", e)
    _tw_paths_cache = merged
    return merged


def _save_bytes(out: Path, content: bytes) -> bool:
    if len(content) < 80:
        return False
    if content[:8] == b"<html" or content[:5] == b"<?xml":
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return True


def _download_url(url: str, out: Path, client: httpx.Client) -> bool:
    try:
        r = client.get(url, timeout=15.0, follow_redirects=True)
        if r.status_code != 200:
            return False
        return _save_bytes(out, r.content)
    except Exception as e:
        logger.debug("logo download failed %s: %s", url, e)
        return False


def _try_trustwallet(key: str, out: Path, client: httpx.Client) -> bool:
    rel = _tw_paths().get(key)
    if not rel:
        return False
    return _download_url(f"{GITHUB_RAW}/{rel}", out, client)


def _try_coincap(key: str, out: Path, client: httpx.Client) -> bool:
    return _download_url(COINCAP_ICON.format(sym=key.lower()), out, client)


def _try_coingecko(key: str, out: Path, client: httpx.Client) -> bool:
    try:
        r = client.get(COINGECKO_SEARCH, params={"query": key}, timeout=12.0)
        if r.status_code != 200:
            return False
        for coin in r.json().get("coins") or []:
            if (coin.get("symbol") or "").upper() != key:
                continue
            img = coin.get("large") or coin.get("thumb") or coin.get("small")
            if img and _download_url(img, out, client):
                return True
        return False
    except Exception as e:
        logger.debug("coingecko logo search failed %s: %s", key, e)
        return False


def ensure_coin_logo(symbol: str) -> bool:
    """Fetch logo once and save as ui/assets/coins/{SYMBOL}.png. Returns True if file exists."""
    key = normalize_logo_symbol(symbol)
    if not key:
        return False
    out = coins_dir() / f"{key}.png"
    if out.is_file() and out.stat().st_size > 80:
        return True
    if is_logo_missing(key):
        return False

    headers = {"User-Agent": "TradeTrailing-CoinLogo/1.0"}
    with httpx.Client(headers=headers) as client:
        if _try_trustwallet(key, out, client):
            logger.info("coin logo saved (trustwallet) %s", key)
            return True
        if _try_coincap(key, out, client):
            logger.info("coin logo saved (coincap) %s", key)
            return True
        if _try_coingecko(key, out, client):
            logger.info("coin logo saved (coingecko) %s", key)
            return True

    _mark_missing(key)
    logger.info("coin logo unavailable %s — initials fallback", key)
    return False


def logo_public_path(symbol: str) -> Optional[str]:
    key = normalize_logo_symbol(symbol)
    if not key:
        return None
    out = coins_dir() / f"{key}.png"
    if out.is_file():
        return f"/ui/assets/coins/{key}.png"
    return None
