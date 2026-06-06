"""
Binance user data stream.

Supports Spot executionReport and Futures ORDER_TRADE_UPDATE. Events are
normalized, matched to order_intents by client_order_id, and persisted so REST
reconcile becomes a fallback instead of the primary source.

410 Gone: Binance listenKey süresi dolunca keepalive PUT → 410 döner.
Bu durumda mevcut listen key temizlenir ve WebSocket yeniden bağlanır
(yeni POST → yeni listenKey). Reconnect otomatik, state kaybı yok.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

OrderUpdateCallback = Callable[[int, Dict[str, Any]], Awaitable[None]]

# listenKey süresi dolunca Binance 410 döner — yeniden bağlan
_LISTEN_KEY_EXPIRED_STATUS = 410
# Keepalive aralığı: Binance listenKey 60 dak dolsa da 30'da bir yenile
_KEEPALIVE_INTERVAL_SEC = 25 * 60  # 25 dakika (güvenlik payı)


@dataclass
class UserStreamClient:
    account_id: int
    keys: Any
    market: str
    on_order_update: OrderUpdateCallback
    account_label: str = ""  # "HesapAdı #KOD" — log'larda hesap ID yerine
    listen_key: Optional[str] = None
    task: Optional[asyncio.Task] = None
    keepalive_task: Optional[asyncio.Task] = None
    stop_event: Optional[asyncio.Event] = None
    _force_reconnect: bool = field(default=False, repr=False)

    def _log_id(self) -> str:
        """Log için hesap tanımlayıcı: 'AdSoyad #ABC123 (id=3)'"""
        label = self.account_label or ""
        base = f"account_id={self.account_id}"
        return f"{label} ({base})" if label else base

    @property
    def testnet(self) -> bool:
        return bool(getattr(self.keys, "testnet", False))

    def _http_base(self) -> str:
        if self.market == "futures":
            return (
                "https://testnet.binancefuture.com"
                if self.testnet
                else "https://fapi.binance.com"
            )
        return (
            "https://testnet.binance.vision"
            if self.testnet
            else "https://api.binance.com"
        )

    def _ws_url(self) -> str:
        if self.market == "futures":
            base = (
                "wss://stream.binancefuture.com/ws"
                if self.testnet
                else "wss://fstream.binance.com/ws"
            )
        else:
            base = (
                "wss://testnet.binance.vision/ws"
                if self.testnet
                else "wss://stream.binance.com:9443/ws"
            )
        return f"{base}/{self.listen_key}"

    def _listen_key_path(self) -> str:
        return (
            "/fapi/v1/listenKey"
            if self.market == "futures"
            else "/api/v3/userDataStream"
        )

    async def _create_listen_key(self) -> str:
        url = self._http_base() + self._listen_key_path()
        headers = {"X-MBX-APIKEY": getattr(self.keys, "api_key", "")}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=headers)
            if not res.is_success:
                # JSON mu HTML mi? HTML → ağ/proxy engeli; JSON → Binance API hatası
                raw_text = res.text[:300] if res.text else ""
                is_html = raw_text.lstrip().startswith("<")
                try:
                    err_body = res.json() if not is_html else {}
                    binance_code = err_body.get("code")
                    binance_msg = err_body.get("msg", raw_text)
                except Exception:
                    binance_code, binance_msg = None, raw_text

                if is_html:
                    # HTML yanıt = istek Binance'e ulaşmadı (proxy/güvenlik duvarı/ISP engeli)
                    logger.warning(
                        "USER_STREAM_NETWORK_BLOCK %s market=%s status=%s — "
                        "Binance API'ye ulaşılamıyor: yanıt HTML (proxy/güvenlik duvarı/ISP engeli). "
                        "VPN, DNS veya ağ ayarları kontrol edilmeli.",
                        self._log_id(),
                        self.market,
                        res.status_code,
                    )
                else:
                    logger.warning(
                        "USER_STREAM_CREATE_410 %s market=%s status=%s — "
                        "Binance listenKey oluşturma reddedildi. "
                        "Binance code=%s msg=%s. API key izni veya IP kısıtlaması kontrol edin.",
                        self._log_id(),
                        self.market,
                        res.status_code,
                        binance_code,
                        binance_msg,
                    )
            res.raise_for_status()
            data = res.json()
        listen_key = data.get("listenKey")
        if not listen_key:
            raise RuntimeError("Binance listenKey response missing listenKey")
        return str(listen_key)

    async def _delete_listen_key(self) -> None:
        """Bağlantı kapatılırken Binance'e listenKey'i sil (temiz kapanış)."""
        if not self.listen_key:
            return
        try:
            url = self._http_base() + self._listen_key_path()
            headers = {"X-MBX-APIKEY": getattr(self.keys, "api_key", "")}
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.delete(
                    url, headers=headers, params={"listenKey": self.listen_key}
                )
        except Exception:
            pass  # Kapanışta hata olsa da devam et
        self.listen_key = None

    async def _keepalive_loop(self) -> None:
        """
        Her _KEEPALIVE_INTERVAL_SEC'te listenKey'i PUT ile yenile.

        410 Gone → listenKey süresi dolmuş veya Binance tarafından iptal edilmiş.
        Bu durumda listen_key temizlenir ve _force_reconnect bayrağı set edilir;
        run() döngüsü bunu fark edip yeni bir listenKey ile yeniden bağlanır.
        """
        assert self.stop_event is not None
        while not self.stop_event.is_set() and not self._force_reconnect:
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=_KEEPALIVE_INTERVAL_SEC
                )
                break  # stop_event tetiklendi
            except asyncio.TimeoutError:
                pass  # Normal — aralık doldu, keepalive zamanı

            if not self.listen_key or self._force_reconnect:
                continue

            try:
                url = self._http_base() + self._listen_key_path()
                headers = {"X-MBX-APIKEY": getattr(self.keys, "api_key", "")}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.put(
                        url, headers=headers, params={"listenKey": self.listen_key}
                    )
                    res.raise_for_status()
                logger.debug(
                    "USER_STREAM_KEEPALIVE %s market=%s",
                    self._log_id(),
                    self.market,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status == _LISTEN_KEY_EXPIRED_STATUS:
                    # 410: listenKey süresi doldu → yeni key ile yeniden bağlan
                    logger.info(
                        "USER_STREAM_KEY_EXPIRED %s market=%s — listenKey geçersiz, yeniden bağlanılıyor",
                        self._log_id(),
                        self.market,
                    )
                    self.listen_key = None
                    self._force_reconnect = True
                    # run() döngüsü _force_reconnect'i kontrol eder ve yeniden bağlanır
                    break
                else:
                    logger.warning(
                        "USER_STREAM_KEEPALIVE_FAILED %s market=%s status=%s err=%s",
                        self._log_id(),
                        self.market,
                        status,
                        exc,
                    )
            except Exception as exc:
                logger.warning(
                    "USER_STREAM_KEEPALIVE_FAILED %s market=%s err=%s",
                    self._log_id(),
                    self.market,
                    exc,
                )

    async def run(self) -> None:
        import websockets

        self.stop_event = asyncio.Event()
        backoff = 1.0
        # Ardışık listenKey oluşturma (POST) başarısızlıkları; tekrarlı log spam'ı önlemek için.
        _consecutive_create_failures = 0
        # Maksimum ardışık başarısızlık sonrası backoff süresi (saniye): 5 dakika.
        _MAX_CREATE_BACKOFF = 300.0
        # Servis başlangıcından itibaren geçen süre: ilk 120 saniye "başlangıç dönemi".
        # Bu süre içindeki ardışık başarısızlıklar ERROR yerine WARNING olarak kalır
        # (yeniden başlatma sırasındaki geçici bağlantı sorunları hata listesine düşmesin).
        _start_time = time.time()
        _STARTUP_GRACE_SEC = 120.0

        while not self.stop_event.is_set():
            self._force_reconnect = False
            try:
                self.listen_key = await self._create_listen_key()
                # Başarılı bağlantı — sayaçları sıfırla
                _consecutive_create_failures = 0
                backoff = 1.0

                # Keepalive'ı başlat (önceki varsa durdur)
                if self.keepalive_task and not self.keepalive_task.done():
                    self.keepalive_task.cancel()
                    try:
                        await self.keepalive_task
                    except (asyncio.CancelledError, Exception):
                        pass
                self.keepalive_task = asyncio.create_task(self._keepalive_loop())

                async with websockets.connect(
                    self._ws_url(),
                    ping_interval=30,
                    ping_timeout=20,
                    open_timeout=20,
                    close_timeout=5,
                ) as ws:
                    mark_stream_connected(self.account_id)
                    logger.info(
                        "USER_STREAM_CONNECTED %s market=%s",
                        self._log_id(),
                        self.market,
                    )
                    await self.on_order_update(
                        self.account_id,
                        {
                            "event_type": "USER_STREAM_CONNECTED",
                            "market": self.market,
                            "account_label": self.account_label,
                            "ts": int(time.time() * 1000),
                        },
                    )
                    # recv döngüsü — _force_reconnect bayrağını 5s'te bir kontrol et
                    while not self.stop_event.is_set() and not self._force_reconnect:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        except asyncio.TimeoutError:
                            continue  # Keepalive bayrağını kontrol etmek için döngü devam eder
                        event = json.loads(raw)
                        normalized = normalize_order_update(event, market=self.market)
                        if normalized:
                            await self.on_order_update(self.account_id, normalized)

                    if self._force_reconnect and not self.stop_event.is_set():
                        logger.info(
                            "USER_STREAM_RECONNECTING %s market=%s — listenKey yenilendi",
                            self._log_id(),
                            self.market,
                        )
                        continue  # Hemen yeniden bağlan, backoff yok

            except asyncio.CancelledError:
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                _consecutive_create_failures += 1
                mark_stream_down(self.account_id)
                # İlk 410 hatası veya bağlantı kopması: WARNING olarak logla ve bildir.
                # Ardışık başarısızlıklarda (3+): DEBUG seviyesine indir, log spam'ını önle.
                if _consecutive_create_failures == 1:
                    logger.warning(
                        "USER_STREAM_DISCONNECTED %s market=%s status=%s err=%s",
                        self._log_id(),
                        self.market,
                        status,
                        exc,
                    )
                    await self.on_order_update(
                        self.account_id,
                        {
                            "event_type": "USER_STREAM_DISCONNECTED",
                            "market": self.market,
                            "account_label": self.account_label,
                            "error": str(exc)[:300],
                            "ts": int(time.time() * 1000),
                        },
                    )
                elif _consecutive_create_failures == 3:
                    _in_startup = (time.time() - _start_time) < _STARTUP_GRACE_SEC
                    if _in_startup:
                        # Başlangıç dönemi: hata listesine düşmemesi için WARNING kullan
                        logger.warning(
                            "USER_STREAM_PERSISTENT_FAILURE %s market=%s status=%s consecutive=%s — "
                            "başlangıç dönemi, daha seyrek yeniden denenecek.",
                            self._log_id(),
                            self.market,
                            status,
                            _consecutive_create_failures,
                        )
                    else:
                        logger.error(
                            "USER_STREAM_PERSISTENT_FAILURE %s market=%s status=%s consecutive=%s — "
                            "API anahtarı izni veya Binance sorunu; daha seyrek yeniden denenecek.",
                            self._log_id(),
                            self.market,
                            status,
                            _consecutive_create_failures,
                        )
                else:
                    logger.debug(
                        "USER_STREAM_CREATE_RETRY %s market=%s status=%s consecutive=%s",
                        self._log_id(),
                        self.market,
                        status,
                        _consecutive_create_failures,
                    )
            except Exception as exc:
                _consecutive_create_failures += 1
                mark_stream_down(self.account_id)
                if _consecutive_create_failures <= 2:
                    logger.warning(
                        "USER_STREAM_DISCONNECTED %s market=%s err=%s",
                        self._log_id(),
                        self.market,
                        exc,
                    )
                    await self.on_order_update(
                        self.account_id,
                        {
                            "event_type": "USER_STREAM_DISCONNECTED",
                            "market": self.market,
                            "account_label": self.account_label,
                            "error": str(exc)[:300],
                            "ts": int(time.time() * 1000),
                        },
                    )
                else:
                    logger.debug(
                        "USER_STREAM_RETRY %s market=%s consecutive=%s err=%s",
                        self._log_id(),
                        self.market,
                        _consecutive_create_failures,
                        exc,
                    )

            if self.stop_event.is_set():
                break
            # Ardışık başarısızlıklarda backoff'u uzat; 3+ hatadan sonra max 5 dakika.
            if _consecutive_create_failures >= 3:
                delay = _MAX_CREATE_BACKOFF + random.uniform(0, 30.0)
            else:
                delay = min(60.0, backoff) + random.uniform(0, 0.3 * backoff)
                backoff = min(60.0, backoff * 2)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        for task in (self.task, self.keepalive_task):
            if task and not task.done():
                task.cancel()
        # Binance'e listenKey'i sil (temiz kapanış)
        try:
            await self._delete_listen_key()
        except Exception:
            pass


_clients: Dict[tuple[int, str], UserStreamClient] = {}

# account_id → stream'in son kopuş timestamp'i (float, epoch).
# health_watch bu değeri okuyarak wallet stale alert eşiğini artırır.
_stream_down_since: Dict[int, float] = {}


def mark_stream_down(account_id: int) -> None:
    _stream_down_since[account_id] = time.time()


def mark_stream_connected(account_id: int) -> None:
    _stream_down_since.pop(account_id, None)


def stream_down_since(account_id: int) -> Optional[float]:
    """Stream'in kopuş zamanını döner (epoch float). Bağlıysa None."""
    return _stream_down_since.get(account_id)


def normalize_order_update(
    event: Dict[str, Any], *, market: str
) -> Optional[Dict[str, Any]]:
    event_type = event.get("e")
    if event_type == "ORDER_TRADE_UPDATE":
        order = event.get("o") or {}
        status = (order.get("X") or "").upper()
        execution_type = (order.get("x") or "").upper()
        return {
            "event_type": "ORDER_TRADE_UPDATE",
            "market": market,
            "symbol": (order.get("s") or "").upper(),
            "side": (order.get("S") or "").upper(),
            "order_id": str(order.get("i") or ""),
            "client_order_id": order.get("c") or "",
            "status": status,
            "execution_type": execution_type,
            "last_qty": _float(order.get("l")),
            "cum_qty": _float(order.get("z")),
            "last_price": _float(order.get("L")),
            "avg_price": _float(order.get("ap")) or _float(order.get("L")),
            "reduce_only": bool(order.get("R")),
            "is_liquidation": execution_type == "CALCULATED"
            or str(order.get("c") or "").startswith("autoclose-"),
            "is_close": bool(order.get("cp")) or bool(order.get("R")),
            "ts": int(event.get("E") or time.time() * 1000),
            "raw": event,
        }
    if event_type == "executionReport":
        status = (event.get("X") or "").upper()
        execution_type = (event.get("x") or "").upper()
        return {
            "event_type": "executionReport",
            "market": market,
            "symbol": (event.get("s") or "").upper(),
            "side": (event.get("S") or "").upper(),
            "order_id": str(event.get("i") or ""),
            "client_order_id": event.get("c") or event.get("C") or "",
            "status": status,
            "execution_type": execution_type,
            "last_qty": _float(event.get("l")),
            "cum_qty": _float(event.get("z")),
            "last_price": _float(event.get("L")),
            "avg_price": _avg_spot_price(event),
            "reduce_only": False,
            "is_liquidation": False,
            "is_close": status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"),
            "ts": int(event.get("E") or time.time() * 1000),
            "raw": event,
        }
    return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _avg_spot_price(event: Dict[str, Any]) -> float:
    cum_qty = _float(event.get("z"))
    cum_quote = _float(event.get("Z"))
    if cum_qty > 0 and cum_quote > 0:
        return cum_quote / cum_qty
    return _float(event.get("L"))


def _build_account_label(account_id: int, db: Optional[Session] = None) -> str:
    """
    Hesap için log etiket: 'AdSoyad #ABC123 (id=3)'.
    DB yoksa veya hata olursa sadece 'account_id=3' döner.
    """
    if db is None:
        return f"account_id={account_id}"
    try:
        from app.db.models import Account

        acc = db.query(Account).filter(Account.id == int(account_id)).first()
        if acc:
            name = (getattr(acc, "name", "") or "").strip()
            code = (getattr(acc, "account_code", "") or "").strip()
            parts = []
            if name:
                parts.append(name)
            if code:
                parts.append(f"#{code}")
            label = " ".join(parts)
            return f"{label} (id={account_id})" if label else f"account_id={account_id}"
    except Exception:
        pass
    return f"account_id={account_id}"


async def start_user_stream_for_account(
    account_id: int,
    on_execution_report: Optional[Callable[[Dict[str, Any]], None]] = None,
    *,
    keys: Any = None,
    market: Optional[str] = None,
    on_order_update: Optional[OrderUpdateCallback] = None,
    db: Optional[Session] = None,
) -> bool:
    """Start a user stream for one account. Safe to call repeatedly."""
    if keys is None:
        from app.db.session import SessionLocal
        from app.services.binance_assets import get_account_keys

        _db = SessionLocal()
        try:
            keys = await get_account_keys(account_id, _db)
            if not db:
                account_label = _build_account_label(account_id, _db)
        finally:
            _db.close()
    else:
        account_label = _build_account_label(account_id, db)

    if not keys:
        return False

    selected_market = (
        (market or os.getenv("BINANCE_USER_STREAM_MARKET", "spot")).strip().lower()
    )
    callback = on_order_update or _legacy_callback(on_execution_report)
    key = (int(account_id), selected_market)
    client = _clients.get(key)
    if client and client.task and not client.task.done():
        return True
    client = UserStreamClient(
        account_id=int(account_id),
        keys=keys,
        market=selected_market,
        on_order_update=callback,
        account_label=account_label,
    )
    client.task = asyncio.create_task(client.run())
    _clients[key] = client
    return True


def _legacy_callback(
    cb: Optional[Callable[[Dict[str, Any]], None]],
) -> OrderUpdateCallback:
    async def _inner(_account_id: int, event: Dict[str, Any]) -> None:
        if cb:
            cb(event)

    return _inner


async def stop_user_stream_for_account(
    account_id: int, market: Optional[str] = None
) -> None:
    markets = [market] if market else ["spot", "futures"]
    for m in markets:
        client = _clients.pop((int(account_id), str(m)), None)
        if client:
            await client.stop()


def apply_user_stream_event_to_db(
    db: Session, account_id: int, event: Dict[str, Any]
) -> None:
    """Persist normalized user stream event and update matching order_intent status."""
    event_type = event.get("event_type")
    if event_type in (
        "USER_STREAM_CONNECTED",
        "USER_STREAM_DISCONNECTED",
        "USER_STREAM_RECONNECTING",
    ):
        return
    client_order_id = (event.get("client_order_id") or "").strip()
    if not client_order_id:
        return
    from app.botengine.intent_ledger import (
        STATUS_CANCELED,
        STATUS_FILLED,
        STATUS_PARTIAL,
        STATUS_REJECTED,
        get_intent_by_client_order_id,
        update_intent_from_binance,
    )
    from app.botengine.state_store import append_event

    intent = get_intent_by_client_order_id(db, client_order_id)
    if not intent or int(intent.get("account_id") or 0) != int(account_id):
        return
    status_raw = (event.get("status") or "").upper()
    mapped_status = {
        "PARTIALLY_FILLED": STATUS_PARTIAL,
        "FILLED": STATUS_FILLED,
        "CANCELED": STATUS_CANCELED,
        "EXPIRED": STATUS_CANCELED,
        "REJECTED": STATUS_REJECTED,
    }.get(status_raw)
    if mapped_status:
        update_intent_from_binance(
            db,
            intent["intent_id"],
            binance_order_id=event.get("order_id"),
            status=mapped_status,
            executed_qty=event.get("cum_qty") or None,
            avg_price=event.get("avg_price") or None,
        )
    append_event(
        db,
        int(intent["bot_id"]),
        int(account_id),
        "ORDER_UPDATE",
        f"{event.get('event_type')} {status_raw} {event.get('symbol')}",
        {
            "source": "binance_user_stream",
            "market": event.get("market"),
            "symbol": event.get("symbol"),
            "side": event.get("side"),
            "order_id": event.get("order_id"),
            "client_order_id": client_order_id,
            "status": status_raw,
            "execution_type": event.get("execution_type"),
            "last_qty": event.get("last_qty"),
            "cum_qty": event.get("cum_qty"),
            "avg_price": event.get("avg_price"),
            "reduce_only": event.get("reduce_only"),
            "is_liquidation": event.get("is_liquidation"),
            "is_close": event.get("is_close"),
        },
    )
    db.commit()

    # Emir dolduğunda tx_history dosyasını anında güncelle —
    # hem bot emirleri (execution.py'deki record_bot_trade_fill için güvence)
    # hem Binance-direct emirler (myTrades sync beklenmeden) kapsanır.
    if status_raw == "FILLED":
        try:
            qty = float(event.get("cum_qty") or 0)
            price = float(event.get("avg_price") or event.get("last_price") or 0)
            if qty > 0 and price > 0:
                from datetime import datetime, timezone as _tz
                from app.services.transaction_history_file_store import (
                    upsert_trade_fill,
                )

                ts_ms = int(event.get("ts") or (time.time() * 1000))
                ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=_tz.utc).replace(
                    tzinfo=None
                )
                order_id_str = str(event.get("order_id") or client_order_id or "")
                upsert_trade_fill(
                    int(account_id),
                    trade_id=order_id_str or client_order_id,
                    order_id=order_id_str or None,
                    symbol=(event.get("symbol") or "").upper(),
                    side=(event.get("side") or "BUY").upper(),
                    qty=qty,
                    price=price,
                    quote_qty=round(qty * price, 8),
                    commission=0.0,
                    commission_asset="USDT",
                    is_maker=False,
                    time=ts_dt,
                    bot_id=int(intent.get("bot_id") or 0) or None,
                )
        except Exception as _ue:
            logger.debug(
                "user_stream tx_history upsert account_id=%s: %s", account_id, _ue
            )
