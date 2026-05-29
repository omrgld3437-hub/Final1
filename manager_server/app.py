"""
Manager Server v3 — FastAPI app: 127.0.0.1:7999, local-only, API + WS + /ui + metrics
"""
import logging
import os
import socket
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

# WebSocket normal kapanma ve sık karşılaşılan bağlantı kesintisi ERROR loglarını bastır
try:
    _uvicorn_err = logging.getLogger("uvicorn.error")
    _uvicorn_log = logging.getLogger("uvicorn")
    class _WSCloseFilter(logging.Filter):
        def filter(self, record):
            if record.levelno < logging.ERROR:
                return True
            msg = (record.getMessage() or "") + (getattr(record, "exc_text") or "")
            if "ConnectionClosedOK" in msg or "1001 (going away)" in msg:
                return False
            if "no close frame" in msg or "1012 (service restart)" in msg:
                return False
            if "IncompleteReadError" in msg or "0 bytes read" in msg or "CancelledError" in msg:
                return False
            if "ASGI application" in msg and ("websocket" in msg.lower() or "ConnectionClosed" in msg or "IncompleteRead" in msg):
                return False
            if "ConnectionResetError" in msg or "WinError 10054" in msg or "10054" in msg:
                return False
            if "forcibly closed" in msg or "_call_connection_lost" in msg or "_ProactorBasePipeTransport" in msg:
                return False
            if "Exception in callback" in msg and ("connection_lost" in msg or "ProactorBasePipeTransport" in msg or "PipeTransport" in msg):
                return False
            if record.exc_info and record.exc_info[1]:
                exc = record.exc_info[1]
                nm = type(exc).__name__
                if nm in ("ConnectionClosedOK", "ConnectionClosedError", "IncompleteReadError", "CancelledError", "ConnectionResetError"):
                    return False
                # Exception chain (cause)
                cause = getattr(exc, "__cause__", None)
                if cause and type(cause).__name__ in ("IncompleteReadError", "ConnectionClosedError", "ConnectionResetError"):
                    return False
            return True
    _uvicorn_err.addFilter(_WSCloseFilter())
    _uvicorn_log.addFilter(_WSCloseFilter())
except Exception:
    pass
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import csv
import io
import json as _json

from manager_server import state

APP_DIR = Path(__file__).resolve().parent
UI_DIR = APP_DIR / "ui"

app = FastAPI(title="Manager Panel", version="3.0")
_log = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Yakalanmamış tüm hataları logla ve 500 dön; ASGI 'Exception in ASGI application' zincirini kır."""
    tb = traceback.format_exc()
    _log.error("Unhandled exception: %s\n%s", exc, tb)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


class _WebSocketCloseSuppressMiddleware:
    """Catch normal WebSocket disconnects (IncompleteReadError, ConnectionClosedError) so they don't log as ASGI errors."""
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "websocket":
            return await self._app(scope, receive, send)
        try:
            return await self._app(scope, receive, send)
        except Exception as exc:
            _name = type(exc).__name__
            if _name in ("ConnectionClosedError", "ConnectionClosedOK", "IncompleteReadError", "CancelledError"):
                return
            if _name == "RuntimeError" and "deque mutated during iteration" in str(exc):
                return
            cause = getattr(exc, "__cause__", None)
            if cause and type(cause).__name__ in ("IncompleteReadError", "ConnectionClosedError"):
                return
            # Diğer hataları logla ama ASGI'ye zincirleme; böylece "Exception in ASGI application" tek satırda kalır
            tb = traceback.format_exc()
            _log.error("WebSocket exception: %s\n%s", exc, tb)
            raise


app.add_middleware(_WebSocketCloseSuppressMiddleware)

# Local-only: reject non-127.0.0.1 (MANAGER_ALLOW_REMOTE=1 ile Windows Server'dan uzaktan erişime izin)
_allow_remote = (os.environ.get("MANAGER_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes"))

@app.middleware("http")
async def local_only(request: Request, call_next):
    if _allow_remote:
        return await call_next(request)
    client = request.client
    if client and client.host not in ("127.0.0.1", "::1"):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


# HTTP isteklerinde yakalanmamış exception'ları yakala; ASGI "Exception in ASGI application" zincirini kır
@app.middleware("http")
async def catch_http_exceptions(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception as exc:
        tb = traceback.format_exc()
        _log.error("HTTP handler exception: %s\n%s", exc, tb)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": type(exc).__name__},
        )
    return response


# Bilinen / isteğe bağlı endpoint 404'leri log spam üretmesin (eski UI sürümü veya probe).
_SUPPRESS_404_PATHS = frozenset({
    "/",
    "/favicon.ico",
    "/api/issues/summary",
    "/api/security/blocked-ips",
    "/api/stack/restart",
    "/api/server/manager/restart",
})
# Tam yeniden başlatma — başarılı istek INFO; hata panelde zaten görünür, WARN spam olmasın.
_STACK_RESTART_PATHS = frozenset({"/api/stack/restart", "/api/server/manager/restart"})
_last_404_log_ts: dict[str, float] = {}
_404_LOG_THROTTLE_SEC = 60.0


# Sadece hata (4xx/5xx) istekleri logla; 200 OK loglanmaz. Düzeltilemeyen / bilinen 404'ler loglanmaz.
@app.middleware("http")
async def log_errors_only(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        path = (request.url.path or "").rstrip("/") or "/"
        if path in _STACK_RESTART_PATHS:
            return response
        if response.status_code == 404:
            if path in _SUPPRESS_404_PATHS or path.startswith("/api/security/"):
                return response
            now = time.time()
            last = _last_404_log_ts.get(path, 0.0)
            if now - last < _404_LOG_THROTTLE_SEC:
                return response
            _last_404_log_ts[path] = now
        logging.getLogger().warning(
            "%s %s %s %s",
            request.client.host if request.client else "-",
            request.method,
            request.url.path,
            response.status_code,
        )
    return response


@app.on_event("startup")
async def startup():
    state.init_state()
    state.start_tail_threads()
    state.start_metrics_thread()
    state.auto_start_if_needed()
    state.start_html_watchdog()


# --- Root: GET / -> /ui (404 log spam önlenir) ---

@app.get("/")
async def root_redirect():
    """GET / yönlendirmesi; 404 yerine /ui'ye gider."""
    return RedirectResponse(url="/ui/", status_code=302)


# --- API ---

@app.get("/favicon.ico")
async def favicon():
    """204 No Content – tarayıcı 404 log spam önlenir."""
    return Response(status_code=204)

@app.get("/api/status")
async def api_status():
    s = state.get_status()
    out = {k: {"running": v["running"], "pid": v["pid"], "locked": v.get("locked", False), "started_at": v.get("started_at"), "restart_count": v.get("restart_count", 0)} for k, v in s.items()}
    try:
        out["host"] = socket.gethostname()
    except Exception:
        out["host"] = "—"
    return out


@app.post("/api/stack/restart")
async def api_stack_restart():
    """Manager + Web + Engine + HTML tam yeniden başlatma."""
    ok = state.schedule_manager_restart()
    if not ok:
        return JSONResponse(status_code=500, content={"detail": "Stack restart failed"})
    return {"ok": True, "action": "restart", "restarting": True, "scope": "full_stack"}


@app.post("/api/server/manager/restart")
async def api_manager_restart():
    """Geriye uyumluluk — tam stack restart."""
    ok = state.schedule_manager_restart()
    if not ok:
        return JSONResponse(status_code=500, content={"detail": "Stack restart failed"})
    return {"ok": True, "service": "manager", "action": "restart", "restarting": True, "scope": "full_stack"}


@app.post("/api/server/{key}/start")
async def api_server_start(key: str):
    key = (key or "").strip().lower()
    if key not in ("web", "engine", "html"):
        return JSONResponse(status_code=400, content={"detail": "Invalid key"})
    ok = state.do_start(key)
    diagnosis = state.get_diagnosis(key)
    return {"ok": ok, "service": key, "action": "start", "status": state.get_status(), "diagnosis": diagnosis if diagnosis else None}


@app.post("/api/server/{key}/stop")
async def api_server_stop(key: str):
    key = (key or "").strip().lower()
    if key not in ("web", "engine", "html"):
        return JSONResponse(status_code=400, content={"detail": "Invalid key"})
    ok = state.do_stop(key)
    diagnosis = state.get_diagnosis(key)
    return {"ok": True, "service": key, "action": "stop", "status": state.get_status(), "diagnosis": diagnosis if diagnosis else None}


@app.post("/api/server/{key}/restart")
async def api_server_restart(key: str):
    key = (key or "").strip().lower()
    if key not in ("web", "engine", "html"):
        return JSONResponse(status_code=400, content={"detail": "Invalid key"})
    ok = state.do_restart(key)
    diagnosis = state.get_diagnosis(key)
    return {"ok": ok, "service": key, "action": "restart", "status": state.get_status(), "diagnosis": diagnosis if diagnosis else None}


@app.post("/api/global/start")
async def api_global_start():
    body = state.schedule_global_action("start")
    if body.get("busy"):
        return JSONResponse(status_code=409, content={"detail": "Başka bir toplu işlem sürüyor", "ok": False})
    return body


@app.post("/api/global/stop")
async def api_global_stop():
    body = state.schedule_global_action("stop")
    if body.get("busy"):
        return JSONResponse(status_code=409, content={"detail": "Başka bir toplu işlem sürüyor", "ok": False})
    return body


@app.post("/api/global/restart")
async def api_global_restart():
    body = state.schedule_global_action("restart")
    if body.get("busy"):
        return JSONResponse(status_code=409, content={"detail": "Başka bir toplu işlem sürüyor", "ok": False})
    return body


@app.get("/api/logs/{key}")
async def api_logs(key: str, tail: int = 300):
    if key not in ("web", "engine", "manager", "html"):
        return JSONResponse(status_code=400, content={"detail": "Invalid key"})
    return state.get_logs(key, tail=tail)


@app.post("/api/reset/{key}")
async def api_reset(key: str):
    if key not in ("web", "engine", "manager", "html", "all"):
        return JSONResponse(status_code=400, content={"detail": "Invalid key"})
    state.reset_logs(key)
    return {"ok": True}


@app.get("/api/metrics")
async def api_metrics():
    return state.get_metrics()


@app.get("/api/traffic")
async def api_traffic():
    return state.get_traffic()


@app.get("/api/security/blocked-ips")
async def api_security_blocked_ips():
    return {"blocked": state.get_blocked_ips()}


@app.post("/api/security/ban-ip")
async def api_security_ban_ip(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    ip = (body.get("ip") or "").strip() if isinstance(body, dict) else ""
    reason = (body.get("reason") or "Manager güvenlik paneli") if isinstance(body, dict) else "Manager güvenlik paneli"
    if not ip:
        return JSONResponse(status_code=400, content={"detail": "IP gerekli"})
    try:
        return state.ban_ip(ip, reason=reason)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@app.post("/api/security/unban-ip")
async def api_security_unban_ip(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    ip = (body.get("ip") or "").strip() if isinstance(body, dict) else ""
    if not ip:
        return JSONResponse(status_code=400, content={"detail": "IP gerekli"})
    try:
        return state.unban_ip(ip)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@app.get("/api/engine_metrics")
async def api_engine_metrics():
    return state.get_engine_metrics()


@app.get("/api/issues")
async def api_issues(service: str = None, status: str = None, limit: int = 50, q: str = None):
    limit = max(1, min(200, limit))
    return state.get_issues(service=service, status_filter=status, limit=limit, q=q)


@app.get("/api/issues/summary")
async def api_issues_summary():
    return state.get_issue_stats()


@app.get("/api/diagnosis")
async def api_diagnosis_all():
    return state.get_diagnosis(None)


@app.get("/api/diagnosis/{service}")
async def api_diagnosis_one(service: str):
    if service not in ("web", "engine", "manager", "html"):
        return JSONResponse(status_code=400, content={"detail": "Invalid service"})
    return state.get_diagnosis(service) or {}


@app.get("/api/issues/archive")
async def api_issues_archive(limit: int = 100, offset: int = 0, q: str = None, service: str = None):
    limit = max(1, min(500, limit))
    offset = max(0, offset)
    return state.get_issues_archive(limit=limit, offset=offset, q=q, service=service)


@app.get("/api/issues/{issue_id}")
async def api_issue_get(issue_id: str):
    out = state.get_issue_by_id(issue_id)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/ack")
async def api_issue_ack(issue_id: str):
    out = state.issue_ack(issue_id)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/resolve")
async def api_issue_resolve(issue_id: str):
    out = state.issue_resolve(issue_id)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/archive")
async def api_issue_archive(issue_id: str):
    out = state.issue_archive(issue_id)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/reopen")
async def api_issue_reopen(issue_id: str):
    out = state.issue_reopen(issue_id)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/assign")
async def api_issue_assign(issue_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    assignee = body.get("assignee") if isinstance(body, dict) else None
    out = state.issue_assign(issue_id, assignee)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/labels")
async def api_issue_labels(issue_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    labels = body.get("labels", []) if isinstance(body, dict) else []
    out = state.issue_labels(issue_id, labels)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/comment")
async def api_issue_comment(issue_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    text = body.get("text", "") if isinstance(body, dict) else ""
    author = (body.get("author") or "local") if isinstance(body, dict) else "local"
    out = state.issue_comment(issue_id, text, author)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.post("/api/issues/{issue_id}/sla")
async def api_issue_sla(issue_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    sla_note = body.get("sla_note") if isinstance(body, dict) else None
    out = state.issue_sla(issue_id, sla_note)
    if out is None:
        return JSONResponse(status_code=404, content={"detail": "Issue not found"})
    return out


@app.get("/api/alerts")
async def api_alerts(acked: bool = None):
    return state.get_alerts(acked=acked)


@app.post("/api/alerts/ack")
async def api_alerts_ack(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    aid = body.get("id") if isinstance(body, dict) else None
    if not aid:
        # 400 yerine 200 dönerek manager log’ta WARNING spam önlenir (UI bazen id göndermeyebilir)
        return {"acked": False, "reason": "id_required"}
    out = state.alert_ack(aid)
    if out is None:
        # Idempotent: zaten ack edilmiş veya silinmiş alert için 200 (404 log spam önler)
        return {"acked": False, "reason": "already_acked_or_expired"}
    state.audit_event("alert_ack", {"alert_id": aid})
    return out


@app.get("/api/audit")
async def api_audit(limit: int = 100):
    limit = max(1, min(300, limit))
    return state.get_audit_events(limit=limit)


@app.get("/api/audit/summary")
async def api_audit_summary():
    return state.get_audit_stats()


@app.get("/api/audit/archive")
async def api_audit_archive(limit: int = 100, offset: int = 0, q: str = None, service: str = None):
    limit = max(1, min(500, limit))
    offset = max(0, offset)
    return state.get_audit_archive(limit=limit, offset=offset, q=q, service=service)


# --- Export (streaming CSV/JSON) ---

@app.get("/api/export/logs")
async def api_export_logs(service: str = "web", tail: int = 1000, format: str = "csv"):
    if service not in ("web", "engine", "manager", "html"):
        return JSONResponse(status_code=400, content={"detail": "Invalid service"})
    tail = max(1, min(5000, tail))
    data = state.get_logs(service, tail=tail)
    lines = data.get("lines", [])
    state.audit_event("export_action", {"type": "logs", "service": service, "format": format})
    if format == "json":
        return JSONResponse(content={"service": service, "lines": lines, "errors": data.get("errors", []), "warns": data.get("warns", [])})
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["line"])
        yield buf.getvalue()
        for line in lines:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([line])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=logs_%s.csv" % service})


@app.get("/api/export/issues")
async def api_export_issues(service: str = None, status: str = None, format: str = "csv"):
    issues = state.get_issues(service=service, status_filter=status, limit=200)
    state.audit_event("export_action", {"type": "issues", "format": format})
    if format == "json":
        return JSONResponse(content=issues)
    columns = ["id", "fingerprint", "severity", "status", "first_seen", "last_seen", "count", "service", "assignee", "sla_note"]
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue()
        for i in issues:
            buf = io.StringIO()
            w = csv.writer(buf)
            svc = (i.get("tags") or {}).get("service", "")
            w.writerow([i.get("id"), i.get("fingerprint"), i.get("severity"), i.get("status"), i.get("first_seen"), i.get("last_seen"), i.get("count"), svc, i.get("assignee") or "", i.get("sla_note") or ""])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=issues.csv"})


@app.get("/api/export/metrics")
async def api_export_metrics(range: str = "5m", format: str = "csv"):
    # range 5m ~ 150 samples at 2s, 1h ~ 1800 but we cap at 900
    hist = state.get_metrics_history(limit=180)
    state.audit_event("export_action", {"type": "metrics", "range": range, "format": format})
    if format == "json":
        return JSONResponse(content=hist)
    columns = ["ts", "ts_epoch", "cpu_pct", "ram_used_mb", "ram_total_mb", "requests_per_min", "status_5xx", "error_rate", "active_bots", "last_tick_age_s"]
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue()
        for h in hist:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([h.get(c, "") for c in columns])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=metrics.csv"})


@app.get("/api/export/audit")
async def api_export_audit(format: str = "csv"):
    events = state.get_audit_events(limit=300)
    state.audit_event("export_action", {"type": "audit", "format": format})
    if format == "json":
        return JSONResponse(content=events)
    columns = ["zaman", "kategori", "islem", "aciklama", "servis", "action", "detail_json"]
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue()
        for e in reversed(events):
            buf = io.StringIO()
            w = csv.writer(buf)
            detail = e.get("detail") or {}
            action = e.get("action") or ""
            cat = state.audit_category(action)
            w.writerow([
                e.get("ts"),
                state.audit_category_label(cat),
                state.audit_action_label(action),
                state.audit_describe(action, detail),
                state.audit_service_label(state.audit_event_service(action, detail)),
                action,
                _json.dumps(detail, ensure_ascii=False),
            ])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=audit.csv"})


@app.get("/api/export/security")
async def api_export_security(format: str = "csv"):
    traffic = state.get_traffic()
    login_fails = traffic.get("last_login_fails") or []
    top_ips = traffic.get("top_ips") or []
    state.audit_event("export_action", {"type": "security", "format": format})
    if format == "json":
        return JSONResponse(content={"last_login_fails": login_fails, "top_ips": top_ips, "login_fail_total": traffic.get("login_fail_total")})
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["type", "ts", "ip", "user", "reason", "count"])
        yield buf.getvalue()
        for f in login_fails:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["login_fail", f.get("ts"), f.get("ip"), f.get("user"), f.get("reason"), ""])
            yield buf.getvalue()
        for t in top_ips:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["top_ip", "", t.get("ip"), "", "", t.get("count", "")])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=security.csv"})


@app.get("/api/export/alerts")
async def api_export_alerts(format: str = "csv"):
    alerts = state.get_alerts()
    state.audit_event("export_action", {"type": "alerts", "format": format})
    if format == "json":
        return JSONResponse(content=alerts)
    columns = ["id", "ts", "level", "kind", "message", "acked", "meta"]
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue()
        for a in alerts:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([a.get("id"), a.get("ts"), a.get("level"), a.get("kind"), a.get("message"), a.get("acked"), _json.dumps(a.get("meta", {}))])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=alerts.csv"})


@app.get("/api/export/diagnosis")
async def api_export_diagnosis(service: str = None, format: str = "json"):
    all_d = state.get_diagnosis(None)
    if service:
        all_d = {k: v for k, v in all_d.items() if k == service}
    state.audit_event("export_action", {"type": "diagnosis", "service": service or "all", "format": format})
    if format == "json":
        return JSONResponse(content=all_d)
    columns = ["service", "state", "reason_code", "title_tr", "summary_tr", "impact_tr", "actions_tr", "next_checks_tr", "ts", "exit_code", "signal", "confidence"]
    def gen():
        yield "\ufeff"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue()
        for svc, d in all_d.items():
            if not d:
                continue
            ev = d.get("evidence") or {}
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([
                svc,
                d.get("state", ""),
                d.get("reason_code", ""),
                (d.get("title_tr") or "").replace("\n", " "),
                (d.get("summary_tr") or "").replace("\n", " "),
                (d.get("impact_tr") or "").replace("\n", " "),
                " | ".join(d.get("actions_tr") or []),
                " | ".join(d.get("next_checks_tr") or []),
                d.get("ts", ""),
                ev.get("exit_code"),
                ev.get("signal") or "",
                d.get("confidence", ""),
            ])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=diagnosis.csv"})


@app.get("/api/locks")
async def api_locks_get():
    return state.load_locks()


@app.post("/api/locks")
async def api_locks_set(request: Request):
    body = await request.json()
    l = {"web": bool(body.get("web")), "engine": bool(body.get("engine"))}
    state.locks.update(l)
    state.save_locks(state.locks)
    state.audit_event("lock", l)
    return state.load_locks()


# --- WebSocket ---

_WS_BATCH_MS = 200
_WS_METRICS_INTERVAL_MS = 2000


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """Single channel: batched log lines (all 3 services), new_errors, new_warns, issue_events, metrics_update every 2s."""
    await websocket.accept()
    import asyncio
    last_metrics_ts = 0.0
    last_issue_fp = ""
    try:
        while True:
            lines_batched = []
            errors_by_service = {}
            warns_by_service = {}
            for key in ("manager", "web", "engine", "html"):
                batch = state.pop_ws_batch(key, max_lines=state.WS_BATCH_MAX)
                for item in batch:
                    lines_batched.append({"service": key, "ts": item.get("ts"), "level": item.get("level"), "text": item.get("text", "")})
                snap = state.get_logs(key, tail=0)
                errors_by_service[key] = (snap.get("errors") or [])[-50:]
                warns_by_service[key] = (snap.get("warns") or [])[-50:]
            open_issues = state.get_issues(status_filter="OPEN", limit=20)
            issue_fp = "|".join(
                f"{i.get('id', '')}:{i.get('count', 0)}"
                for i in open_issues
            )
            if issue_fp != last_issue_fp:
                last_issue_fp = issue_fp
                issue_events = [
                    {"id": i["id"], "count": i.get("count", 0), "service": i.get("tags", {}).get("service")}
                    for i in open_issues
                ]
            else:
                issue_events = []
            import time as _time
            now = _time.time()
            metrics_update = None
            if now - last_metrics_ts >= _WS_METRICS_INTERVAL_MS / 1000.0:
                last_metrics_ts = now
                metrics_update = state.get_metrics()
                st = state.get_status()
                if isinstance(metrics_update, dict):
                    metrics_update["status"] = st
            alert_events = state.get_alerts(acked=False)[-30:]
            payload = {
                "lines": lines_batched[:200],
                "errors_by_service": errors_by_service,
                "warns_by_service": warns_by_service,
                "issue_events": issue_events,
                "alert_events": alert_events,
            }
            if metrics_update is not None:
                payload["metrics_update"] = metrics_update
            has_err_wrn = any(errors_by_service.get(k) for k in ("web", "engine", "manager")) or any(warns_by_service.get(k) for k in ("web", "engine", "manager"))
            if payload["lines"] or has_err_wrn or payload["issue_events"] or payload.get("metrics_update") or payload["alert_events"]:
                await websocket.send_json(payload)
            await asyncio.sleep(_WS_BATCH_MS / 1000.0)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/logs/{key}")
async def ws_logs(websocket: WebSocket, key: str):
    if key not in ("web", "engine", "manager", "html"):
        await websocket.close(code=4000)
        return
    await websocket.accept()
    import asyncio
    try:
        while True:
            batch = state.pop_ws_batch(key, max_lines=state.WS_BATCH_MAX)
            snap = state.get_logs(key, tail=0)
            open_issues = state.get_issues(service=key, status_filter="OPEN")
            payload = {
                "lines": batch,
                "new_errors": snap.get("errors", [])[-50:],
                "new_warns": snap.get("warns", [])[-50:],
                "issue_events": [{"id": i["id"], "count": i.get("count", 0)} for i in open_issues[:10]],
            }
            if batch or payload["new_errors"] or payload["new_warns"] or payload["issue_events"]:
                await websocket.send_json(payload)
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass


# --- UI ---

if UI_DIR.exists():
    app.mount("/ui/assets", StaticFiles(directory=UI_DIR / "assets"), name="manager_assets")


@app.get("/ui")
@app.get("/ui/")
async def ui_index():
    index = UI_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(content={"message": "Manager UI not found"}, status_code=404)


@app.get("/ui/logs.html")
async def ui_logs_redirect():
    """Logs sayfası /ui/ içinde gömülü; redirect 404 önler."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/", status_code=302)
