#!/bin/bash
# ayserose — tum servisleri baslatir (Manager 7999, Web 8000, Worker, opsiyonel marketing :8080).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs .run

# Bu calistirma "her sey ayakta olsun" niyetini ifade eder: supervisor.sh'nin
# servisleri kalici olarak durdurulmus saymasini onlemek icin .disabled
# bayraklarini temizle (stop.command bunlari yazar).
rm -f "$ROOT/.run/manager.disabled" "$ROOT/.run/web.disabled" "$ROOT/.run/worker.disabled" "$ROOT/.run/html.disabled"

# urllib3/LibreSSL uyarisini bastir (macOS; format: action:message:category:module)
export PYTHONWARNINGS="${PYTHONWARNINGS:+$PYTHONWARNINGS,}ignore:::urllib3"
# PARAM_POOL_VERSION bos birakilirsa v4 sqlite varsa otomatik v4 yuklenir.
export PARAM_POOL_WARMUP="${PARAM_POOL_WARMUP:-0}"
export PARAM_POOL_WARMUP="${PARAM_POOL_WARMUP:-0}"
# Yerel macOS: tek worker = daha hizli acilis, cift havuz yuklemesi yok.
if [ -z "${WEB_UVICORN_WORKERS:-}" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    WEB_UVICORN_WORKERS=1
  else
    WEB_UVICORN_WORKERS=2
  fi
fi
export WEB_UVICORN_WORKERS

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

# Runtime log bakimi: aktif loglari arsivle; 90 gunluk saklama (LOG_RETENTION_DAYS).
# Her baslatmada zorla bir tur; gunluk tekrar supervisor/worker uzerinden.
"$PY" "$ROOT/scripts/maintenance/manage_logs.py" --force >/dev/null 2>&1 || true

STARTED=()

_port_open() {
  command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$1" 2>/dev/null
}

_kill_stale_pid() {
  local pidfile="$1"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$pid" ] || return 0
  kill -TERM "$pid" 2>/dev/null || true
  sleep 1
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$pidfile"
}

# Manager (7999) — "(set -m; ... &)" ile kendi bagimsiz surec grubunda baslatilir;
# terminal/oturum kapansa da bu nohup'lanmis surec ayakta kalir. Asil kalicilik
# garantisi supervisor.sh'den gelir (asagida baslatilir): bu servis beklenmedik
# sekilde duserse supervisor en fazla 5 saniye icinde yeniden baslatir.
MANAGER_PID="$ROOT/.run/manager.pid"
MANAGER_LOG="$ROOT/logs/manager.log"
if _port_open 7999; then
  STARTED+=("Manager (7999): zaten calisiyor (port acik)")
else
  _kill_stale_pid "$MANAGER_PID"
  P=$(lsof -ti:7999 2>/dev/null); [ -n "$P" ] && echo "$P" | xargs kill -KILL 2>/dev/null || true
  (set -m; nohup "$PY" -m manager_server >> "$MANAGER_LOG" 2>&1 & echo $! > "$MANAGER_PID")
  STARTED+=("Manager (7999): baslatildi, PID=$(cat "$MANAGER_PID" 2>/dev/null)")
  sleep 2
fi

# Web (8000)
WEB_PID="$ROOT/.run/web.pid"
WEB_LOG="$ROOT/logs/web.log"
if _port_open 8000; then
  STARTED+=("Web (8000): zaten calisiyor (port acik)")
else
  _kill_stale_pid "$WEB_PID"
  P=$(lsof -ti:8000 2>/dev/null); [ -n "$P" ] && echo "$P" | xargs kill -KILL 2>/dev/null || true
  (set -m; nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers "$WEB_UVICORN_WORKERS" --loop uvloop --http httptools --log-level warning --no-access-log >> "$WEB_LOG" 2>&1 & echo $! > "$WEB_PID")
  STARTED+=("Web (8000): baslatildi, PID=$(cat "$WEB_PID" 2>/dev/null)")
  sleep 2
fi

# Engine (worker)
ENGINE_PID="$ROOT/.run/worker.pid"
ENGINE_LOG="$ROOT/logs/worker.log"
if [ -f "$ENGINE_PID" ] && kill -0 "$(cat "$ENGINE_PID")" 2>/dev/null; then
  STARTED+=("Engine (worker): zaten calisiyor, PID=$(cat "$ENGINE_PID")")
else
  rm -f "$ENGINE_PID"
  (set -m; nohup "$PY" -m app.botengine.worker_main >> "$ENGINE_LOG" 2>&1 & echo $! > "$ENGINE_PID")
  STARTED+=("Engine (worker): baslatildi, PID=$(cat "$ENGINE_PID" 2>/dev/null)")
fi

# marketing sitesi (8080) — marketing/ birincil; eski klasor adlari geriye uyumlu
HTML_PID=""
HTML_DIR=""
for d in "marketing" "omeraltinhtml" "Omeraltinhtml"; do
  if [ -d "$ROOT/$d" ] && [ -f "$ROOT/$d/start.py" ]; then
    HTML_DIR="$ROOT/$d"
    break
  fi
done
if [ -n "$HTML_DIR" ]; then
  (set -m; nohup "$PY" -u "$HTML_DIR/start.py" >> "$ROOT/logs/html.log" 2>&1 & echo $! > "$ROOT/.run/html.pid")
  HTML_PID=$(cat "$ROOT/.run/html.pid" 2>/dev/null)
  STARTED+=("HTML (8080): baslatildi, PID=$HTML_PID")
  sleep 2
  if command -v nc >/dev/null 2>&1; then
    if nc -z 127.0.0.1 8080 2>/dev/null; then
      : # port acik, tamam
    else
      echo "  [UYARI] HTML (8080) hemen acilmadi. Log: $ROOT/logs/html.log"
    fi
  fi
elif [ -d "$ROOT/marketing" ] || [ -d "$ROOT/omeraltinhtml" ] || [ -d "$ROOT/Omeraltinhtml" ]; then
  HTML_DIR="$ROOT/marketing"
  [ -d "$ROOT/omeraltinhtml" ] && HTML_DIR="$ROOT/omeraltinhtml"
  [ -d "$ROOT/Omeraltinhtml" ] && HTML_DIR="$ROOT/Omeraltinhtml"
  if [ -f "$HTML_DIR/calistir.command" ] || [ -f "$HTML_DIR/calistir.sh" ]; then
    (cd "$HTML_DIR" && (./calistir.command 2>/dev/null || ./calistir.sh 2>/dev/null) >> "$ROOT/logs/html.log" 2>&1) &
    HTML_PID=$!
    STARTED+=("HTML (8080): baslatildi, PID=$HTML_PID")
    sleep 1
  fi
fi

# Supervisor — manager/web/worker/html'i izleyen kalici arka plan bekci. Kendi
# bagimsiz surec grubunda calistigi icin terminal/oturum kapansa, Mac uykuya
# gecse de hayatta kalir; izledigi servislerden biri beklenmedik sekilde duserse
# en fazla 5 saniye icinde otomatik yeniden baslatir.
SUPERVISOR_PID="$ROOT/.run/supervisor.pid"
if [ -f "$SUPERVISOR_PID" ] && kill -0 "$(cat "$SUPERVISOR_PID" 2>/dev/null)" 2>/dev/null; then
  STARTED+=("Supervisor: zaten calisiyor, PID=$(cat "$SUPERVISOR_PID")")
else
  (set -m; nohup bash "$ROOT/ops/supervisor.sh" >> "$ROOT/logs/supervisor.log" 2>&1 & echo $! > "$SUPERVISOR_PID")
  STARTED+=("Supervisor: baslatildi, PID=$(cat "$SUPERVISOR_PID" 2>/dev/null)")
fi

echo ""
echo "========================================="
echo "  Baslatilan processler:"
echo "========================================="
for line in "${STARTED[@]}"; do echo "  $line"; done
echo "========================================="
echo "  Manager:  http://127.0.0.1:7999"
echo "  Web:      http://127.0.0.1:8000"
echo "  HTML:     http://127.0.0.1:8080  (omeraltin.com icerigi)"
echo "========================================="
echo "  Giris:    http://127.0.0.1:8000/ui/login.html"
echo "========================================="
echo "Linux sunucuda: site icin http://SUNUCU_IP:8080 acin; domain (omeraltin.com) icin nginx reverse proxy gerekir."
echo "HTML acilmazsa: logs/html.log dosyasini kontrol edin."

WEB_URL="http://127.0.0.1:8000/ui/login.html"
if _port_open 8000; then
  if [ "$(uname -s)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
    open "$WEB_URL" 2>/dev/null || true
    echo "Tarayici acildi: $WEB_URL"
  fi
else
  echo ""
  echo "  [HATA] Web (8000) acilamadi. Son satirlar:"
  tail -n 8 "$WEB_LOG" 2>/dev/null || true
  echo "  Tam log: $ROOT/logs/web.log"
fi
