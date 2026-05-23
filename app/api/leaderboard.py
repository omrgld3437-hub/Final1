"""
Leaderboard API: top bots by structure / global. Auth required. No username/balance/bot_id in response.
"""
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db.session import get_db
from app.services.leaderboard_service import get_global_top, get_top_by_structure, refresh_bot_public_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("/structures/{structure_id}/top")
async def leaderboard_structure_top(
    structure_id: str,
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """Top 5 (or limit) bots by profit % for a structure. Response: profit_pct + params only."""
    items = get_top_by_structure(db, structure_id.strip(), limit)
    return {
        "structure_id": structure_id.strip(),
        "items": items,
        "server_ts": time.time(),
    }


@router.get("/global/top")
async def leaderboard_global_top(
    limit: int = Query(1, ge=1, le=20),
    db: Session = Depends(get_db),
    current: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """Global top bots by profit %. Response: structure_id, profit_pct, params only."""
    try:
        refresh_bot_public_metrics(db, batch_size=200)
    except Exception as e:
        logger.debug("leaderboard refresh before global/top: %s", e)
    items = get_global_top(db, limit)
    return {
        "items": items,
        "server_ts": time.time(),
    }
