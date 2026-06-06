"""
WebSocket Routes
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
import json
import asyncio
import logging

# Optional Binance imports - will be added later
try:
    from app.services.binance_market_data import get_market_data
except ImportError:
    get_market_data = None

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/price/{symbol}")
async def websocket_price(websocket: WebSocket, symbol: str):
    """WebSocket for price updates"""
    await websocket.accept()
    try:
        while True:
            # Placeholder - in real implementation would stream from Binance WS
            data = {"symbol": symbol, "price": 0.0, "timestamp": 0}
            await websocket.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


@router.websocket("/bot/{bot_id}")
async def websocket_bot(websocket: WebSocket, bot_id: int):
    """WebSocket for bot updates"""
    await websocket.accept()
    try:
        while True:
            data = {"bot_id": bot_id, "status": "connected"}
            await websocket.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


@router.websocket("/market-data/stream")
async def websocket_market_data(
    websocket: WebSocket, symbols: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for live market data updates
    Client sends: {"action": "subscribe", "symbols": ["BTCUSDT", "ETHUSDT"]}
    Server sends: {"type": "price_update", "symbol": "BTCUSDT", "data": {...}}
    """
    await websocket.accept()
    logger.info("[MarketDataWS] Client connected")

    if not get_market_data:
        await websocket.send_json(
            {"type": "error", "message": "Market data service not available"}
        )
        await websocket.close()
        return

    market_data = get_market_data()
    subscribed_symbols = []

    async def on_price_update(symbol: str, price_data: dict):
        """Callback for price updates"""
        try:
            await websocket.send_json(
                {"type": "price_update", "symbol": symbol, "data": price_data}
            )
        except Exception as e:
            logger.error(f"[MarketDataWS] Error sending update: {e}")
            raise

    try:
        # Wait for initial subscription message
        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
                action = data.get("action")

                if action == "subscribe":
                    symbols_list = data.get("symbols", [])
                    if isinstance(symbols_list, str):
                        symbols_list = [
                            s.strip().upper() for s in symbols_list.split(",")
                        ]
                    else:
                        symbols_list = [s.upper() for s in symbols_list]

                    subscribed_symbols = symbols_list
                    logger.info(
                        f"[MarketDataWS] Subscribing to {len(subscribed_symbols)} symbols"
                    )

                    # Get initial snapshot
                    snapshot = await market_data.get_snapshot(subscribed_symbols)
                    await websocket.send_json({"type": "snapshot", "prices": snapshot})

                    # Start stream
                    await market_data.start_stream(subscribed_symbols, on_price_update)
                    await websocket.send_json(
                        {
                            "type": "status",
                            "status": "connected",
                            "mode": "websocket"
                            if not market_data.fallback_mode
                            else "fallback",
                        }
                    )

                elif action == "unsubscribe":
                    await market_data.stop_stream()
                    await websocket.send_json(
                        {"type": "status", "status": "disconnected"}
                    )
                    break

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
            except Exception as e:
                logger.error(f"[MarketDataWS] Error: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        logger.info("[MarketDataWS] Client disconnected")
    except Exception as e:
        logger.error(f"[MarketDataWS] Error: {e}")
    finally:
        # Cleanup
        if subscribed_symbols:
            await market_data.stop_stream()
        logger.info("[MarketDataWS] Connection closed")
