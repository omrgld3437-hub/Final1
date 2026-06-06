"""
FILE: binance_assets.py
Account keys resolution: decrypt api_key/api_secret, return BinanceKeys (testnet from mode).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from app.services.encryption import decrypt_text

# Error codes for API response (global standard)
ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
ACCOUNT_KEYS_MISSING = "ACCOUNT_KEYS_MISSING"  # legacy; prefer ACCOUNT_KEYS_EMPTY / ACCOUNT_KEYS_DECRYPT_FAIL
ACCOUNT_KEYS_EMPTY = "ACCOUNT_KEYS_EMPTY"
ACCOUNT_KEYS_DECRYPT_FAIL = "ACCOUNT_KEYS_DECRYPT_FAIL"

# All key-related error codes (for callers that treat them alike)
KEY_ERROR_CODES = (ACCOUNT_KEYS_MISSING, ACCOUNT_KEYS_EMPTY, ACCOUNT_KEYS_DECRYPT_FAIL)


@dataclass
class BinanceKeys:
    api_key: str
    api_secret: str
    testnet: bool


async def get_account_keys(account_id: int, db) -> BinanceKeys:
    """
    Load account by id, decrypt api_key_enc / api_secret_enc, return BinanceKeys.
    mode == "testnet" -> testnet=True.
    Raises ValueError with error_code:
      ACCOUNT_NOT_FOUND - record missing
      ACCOUNT_KEYS_EMPTY - api_key_enc or api_secret_enc empty (len=0)
      ACCOUNT_KEYS_DECRYPT_FAIL - len>0 but decrypt raises or result empty
    """
    from app.db.models import Account
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise ValueError(ACCOUNT_NOT_FOUND)
    enc_key = getattr(account, "api_key_enc", None)
    enc_secret = getattr(account, "api_secret_enc", None)
    key_len = len(enc_key or "")
    secret_len = len(enc_secret or "")
    if key_len == 0 or secret_len == 0:
        raise ValueError(ACCOUNT_KEYS_EMPTY)
    if (isinstance(enc_key, str) and not enc_key.strip()) or (isinstance(enc_secret, str) and not enc_secret.strip()):
        raise ValueError(ACCOUNT_KEYS_EMPTY)
    try:
        api_key = decrypt_text(account.api_key_enc).strip()
        api_secret = decrypt_text(account.api_secret_enc).strip()
    except Exception:
        raise ValueError(ACCOUNT_KEYS_DECRYPT_FAIL)
    if not api_key or not api_secret:
        raise ValueError(ACCOUNT_KEYS_DECRYPT_FAIL)
    mode = (getattr(account, "mode", None) or "live").strip().lower()
    testnet = mode == "testnet"
    # Gerçek hesaplar (test kullanıcı değil) her zaman mainnet kullanır; yanlışlıkla testnet seçilse bile
    from app.services.test_account import is_test_account
    if not is_test_account(account_id, db):
        testnet = False
    return BinanceKeys(api_key=api_key, api_secret=api_secret, testnet=testnet)


async def fetch_prices_map(testnet: bool = False):
    """
    Legacy helper for finance_snapshot: return flat symbol -> price map from ticker/price.
    """
    from app.services.binance_spot import ticker_price_all
    rows = await ticker_price_all(testnet=testnet)
    return {r.get("symbol", ""): float(r.get("price", 0) or 0) for r in (rows or []) if r.get("symbol")}


def _convert_to_usd(asset: str, amount: float, prices: dict) -> float:
    """
    Convert asset amount to USD using prices map.
    - {asset}USDT (e.g. BTCUSDT): price = USDT per 1 asset -> value = amount * price
    - USDT{asset} (e.g. USDTTRY): price = asset per 1 USDT -> value = amount / price
    """
    if not amount or amount <= 0:
        return 0.0
    asset = (asset or "").upper()
    if asset in ("USDT", "BUSD", "USDC", "FDUSD", "TUSD", "DAI"):
        return amount
    try:
        p_usdt_per_asset = prices.get(f"{asset}USDT")
        if p_usdt_per_asset is not None and float(p_usdt_per_asset) > 0:
            return amount * float(p_usdt_per_asset)
        p_asset_per_usdt = prices.get(f"USDT{asset}")
        if p_asset_per_usdt is not None and float(p_asset_per_usdt) > 0:
            return amount / float(p_asset_per_usdt)
    except (TypeError, ValueError):
        pass
    return 0.0
