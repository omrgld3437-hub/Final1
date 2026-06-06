"""
FILE: finance_snapshot.py
VERSION: v1.0
DATE: 2026-01-23
CHANGE: Asset snapshot service - portfolio zaman serisi
"""

from __future__ import annotations
from typing import Dict, List, Optional
import logging
from datetime import datetime
from sqlalchemy.orm import Session
import json

from app.db.models import Account, AssetSnapshot

# Optional Binance imports - will be added later
try:
    from app.services.binance_assets import (
        get_account_keys,
        fetch_prices_map,
        _convert_to_usd,
    )
except ImportError:
    get_account_keys = None
    fetch_prices_map = None
    _convert_to_usd = None

logger = logging.getLogger(__name__)


class SnapshotService:
    """Asset snapshot service - portfolio zaman serisi"""

    def __init__(self, db: Session):
        self.db = db

    async def create_snapshot(
        self, account_id: int, source: str = "rest_snapshot"
    ) -> Optional[AssetSnapshot]:
        """
        Create asset snapshot for account
        Returns: AssetSnapshot or None
        """
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            logger.error(f"[Snapshot] Account {account_id} not found")
            return None

        # Test hesabı: Binance API çağırma, paper bakiye ile snapshot oluştur
        try:
            from app.services.test_account import (
                is_test_account,
                TEST_PAPER_BALANCE_USDT,
            )

            if is_test_account(account_id, self.db):
                prices = {}
                try:
                    from app.services.data_hub import data_hub

                    prices = data_hub.get_all_prices() or {}
                except Exception:
                    pass
                price_map = (
                    {sym: float(d.get("price") or 0) for sym, d in prices.items()}
                    if prices
                    else {}
                )
                usd = price_map.get("USDT") or 1.0
                total_usd = float(TEST_PAPER_BALANCE_USDT) * usd
                breakdown = {
                    "USDT": {
                        "free": TEST_PAPER_BALANCE_USDT,
                        "locked": 0,
                        "total": TEST_PAPER_BALANCE_USDT,
                        "usdValue": total_usd,
                        "priceUsed": usd,
                    }
                }
                snapshot = AssetSnapshot(
                    account_id=account_id,
                    timestamp=datetime.utcnow(),
                    total_usd_value=total_usd,
                    breakdown_json=json.dumps(breakdown),
                    source=source + "_paper",
                )
                self.db.add(snapshot)
                self.db.commit()
                self.db.refresh(snapshot)
                logger.info(
                    f"[Snapshot] Created paper snapshot for test account {account_id}: ${total_usd:.2f}"
                )
                return snapshot
        except Exception as e:
            logger.debug(f"[Snapshot] Test account check failed: {e}")

        try:
            # Check if Binance services are available
            if not get_account_keys or not fetch_prices_map or not _convert_to_usd:
                logger.warning(
                    f"[Snapshot] Binance services not available, skipping snapshot for account {account_id}"
                )
                return None

            # Get wallet data
            try:
                from app.services.binance_spot import get_wallet
            except ImportError:
                logger.warning(
                    f"[Snapshot] binance_spot not available, skipping snapshot for account {account_id}"
                )
                return None

            keys = await get_account_keys(account_id, self.db)
            if not keys:
                logger.warning(
                    f"[Snapshot] Could not get keys for account {account_id}"
                )
                return None

            wallet_data = await get_wallet(keys, tag="finance_snapshot")
            balances = wallet_data.get("balances", [])

            # Get prices
            prices = await fetch_prices_map(testnet=keys.testnet)

            # Build breakdown
            breakdown = {}
            total_usd = 0.0

            for balance in balances:
                asset = balance.get("asset")
                free = float(balance.get("free", 0))
                locked = float(balance.get("locked", 0))
                total = free + locked

                if total <= 0:
                    continue

                # Get USD value
                usd_value = _convert_to_usd(asset, total, prices)
                price_used = (
                    prices.get(f"{asset}USDT") or prices.get(f"{asset}BUSD") or 0.0
                )

                breakdown[asset] = {
                    "free": free,
                    "locked": locked,
                    "total": total,
                    "usdValue": usd_value,
                    "priceUsed": price_used,
                }

                total_usd += usd_value

            # Create snapshot
            snapshot = AssetSnapshot(
                account_id=account_id,
                timestamp=datetime.utcnow(),
                total_usd_value=total_usd,
                breakdown_json=json.dumps(breakdown),
                source=source,
            )

            self.db.add(snapshot)
            self.db.commit()
            self.db.refresh(snapshot)

            logger.info(
                f"[Snapshot] Created snapshot for account {account_id}: ${total_usd:.2f}"
            )
            return snapshot

        except Exception as e:
            logger.error(
                f"[Snapshot] Error creating snapshot for account {account_id}: {e}"
            )
            self.db.rollback()
            return None

    async def create_snapshots_for_all_accounts(self) -> Dict:
        """Create snapshots for all accounts"""
        accounts = self.db.query(Account).all()
        results = {}

        for account in accounts:
            snapshot = await self.create_snapshot(account.id)
            results[account.id] = {
                "success": snapshot is not None,
                "total_usd": snapshot.total_usd_value if snapshot else 0.0,
            }

        return results

    def get_equity_curve(
        self,
        account_id: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Get equity curve data (time series)
        Returns: [{timestamp, total_usd_value}]
        """
        query = self.db.query(AssetSnapshot).filter(
            AssetSnapshot.account_id == account_id
        )

        if start_time:
            query = query.filter(AssetSnapshot.timestamp >= start_time)
        if end_time:
            query = query.filter(AssetSnapshot.timestamp <= end_time)

        snapshots = query.order_by(AssetSnapshot.timestamp.asc()).all()

        return [
            {"timestamp": s.timestamp.isoformat(), "total_usd_value": s.total_usd_value}
            for s in snapshots
        ]
