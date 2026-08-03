#!/bin/bash
# ayserose -- kalici arka plan bekci.
#
# Neden var: nohup yalnizca SIGHUP'i yok sayar; terminal/oturum kapanirken ya da
# Mac uyku/uyanma sirasinda surec GRUBUNA gonderilen bir sinyal (SIGTERM/SIGKILL)
# nohup'lanmis cocuklari da goturebilir. Bu script "(set -m; ... &)" tekniginin
# kendisiyle baslatildigi icin (bkz. start.command) KENDI bagimsiz surec grubunda
# calisir ve boyle bir grup-capi sinyalden etkilenmez; macOS'ta setsid olmadigi
# icin bu, en yakin tasinabilir esdeger.
#
# Ne yapar: her 5 saniyede manager(7999)/web(8000)/worker/html(8080) portlarini
# kontrol eder; biri kapaliysa VE ilgili "<servis>.disabled" bayragi yoksa o
# servisi yeniden baslatir. Bayraklari start.command (temizler) / stop.command
# (yazar) yonetir -- boylece kasitli "durdur" kalici olur, supervisor onu hemen
# geri getirmez.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
RUN="$ROOT/.run"
LOGS="$ROOT/logs"
mkdir -p "$RUN" "$LOGS"

_port_open() {
  command -v nc >/dev/null 2>&1 && nc -z -G 2 127.0.0.1 "$1" 2>/dev/null
}

_web_alive() {
  if _port_open 8000; then
    return 0
  fi
  if [ -f "$RUN/web.pid" ]; then
    local pid
    pid="$(cat "$RUN/web.pid" 2>/dev/null)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

_log() {
  echo "[supervisor] $(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGS/supervisor.log"
}

_last_log_maintain=0

if [ -z "${WEB_UVICORN_WORKERS:-}" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    WEB_UVICORN_WORKERS=1
  else
    WEB_UVICORN_WORKERS=2
  fi
fi
export WEB_UVICORN_WORKERS
export PARAM_POOL_WARMUP="${PARAM_POOL_WARMUP:-0}"

while true; do
  if [ ! -f "$RUN/manager.disabled" ] && ! _port_open 7999; then
    (set -m; nohup "$PY" -m manager_server >> "$LOGS/manager.log" 2>&1 & echo $! > "$RUN/manager.pid")
    _log "Manager (7999) kapaliydi, yeniden baslatildi (PID=$(cat "$RUN/manager.pid" 2>/dev/null))."
  fi

  if [ ! -f "$RUN/web.disabled" ] && ! _web_alive; then
    (set -m; nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers "$WEB_UVICORN_WORKERS" --loop uvloop --http httptools --log-level warning --no-access-log >> "$LOGS/web.log" 2>&1 & echo $! > "$RUN/web.pid")
    _log "Web (8000) kapaliydi, yeniden baslatildi (PID=$(cat "$RUN/web.pid" 2>/dev/null))."
  fi

  if [ ! -f "$RUN/worker.disabled" ] && { [ ! -f "$RUN/worker.pid" ] || ! kill -0 "$(cat "$RUN/worker.pid" 2>/dev/null)" 2>/dev/null; }; then
    (set -m; nohup "$PY" -m app.botengine.worker_main >> "$LOGS/worker.log" 2>&1 & echo $! > "$RUN/worker.pid")
    _log "Engine (worker) kapaliydi, yeniden baslatildi (PID=$(cat "$RUN/worker.pid" 2>/dev/null))."
  fi

  if [ ! -f "$RUN/html.disabled" ] && ! _port_open 8080; then
    HTML_DIR=""
    for d in "marketing" "omeraltinhtml" "Omeraltinhtml"; do
      if [ -d "$ROOT/$d" ] && [ -f "$ROOT/$d/start.py" ]; then
        HTML_DIR="$ROOT/$d"
        break
      fi
    done
    if [ -n "$HTML_DIR" ]; then
      (set -m; nohup "$PY" -u "$HTML_DIR/start.py" >> "$LOGS/html.log" 2>&1 & echo $! > "$RUN/html.pid")
      _log "HTML (8080) kapaliydi, yeniden baslatildi (PID=$(cat "$RUN/html.pid" 2>/dev/null))."
    fi
  fi

  # Gunluk log bakimi (90 gun saklama; throttle script icinde)
  _now_ts=$(date +%s)
  if [ -z "${_last_log_maintain:-}" ] || [ $((_now_ts - _last_log_maintain)) -ge 86400 ]; then
    "$PY" "$ROOT/scripts/maintenance/manage_logs.py" >> "$LOGS/supervisor.log" 2>&1 || true
    _last_log_maintain=$_now_ts
  fi

  sleep 5
done
