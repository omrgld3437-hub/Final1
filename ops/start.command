#!/bin/bash
# TraderTrailing — tum servisleri baslatir (Manager 7999, Web 8000, Worker, opsiyonel marketing :8080).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs .run

# urllib3/LibreSSL uyarisini bastir (macOS; format: action:message:category:module)
export PYTHONWARNINGS="${PYTHONWARNINGS:+$PYTHONWARNINGS,}ignore:::urllib3"

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

STARTED=()

# Manager (7999)
MANAGER_PID="$ROOT/.run/manager.pid"
MANAGER_LOG="$ROOT/logs/manager.log"
if [ -f "$MANAGER_PID" ] && kill -0 "$(cat "$MANAGER_PID")" 2>/dev/null; then
  STARTED+=("Manager (7999): zaten calisiyor, PID=$(cat "$MANAGER_PID")")
else
  rm -f "$MANAGER_PID"
  nohup "$PY" -m manager_server >> "$MANAGER_LOG" 2>&1 &
  echo $! > "$MANAGER_PID"
  STARTED+=("Manager (7999): baslatildi, PID=$!")
  sleep 2
fi

# Web (8000)
WEB_PID="$ROOT/.run/web.pid"
WEB_LOG="$ROOT/logs/web.log"
if [ -f "$WEB_PID" ] && kill -0 "$(cat "$WEB_PID")" 2>/dev/null; then
  STARTED+=("Web (8000): zaten calisiyor, PID=$(cat "$WEB_PID")")
else
  rm -f "$WEB_PID"
  nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --loop uvloop --http httptools --log-level info >> "$WEB_LOG" 2>&1 &
  echo $! > "$WEB_PID"
  STARTED+=("Web (8000): baslatildi, PID=$!")
  sleep 1
fi

# Engine (worker)
ENGINE_PID="$ROOT/.run/worker.pid"
ENGINE_LOG="$ROOT/logs/worker.log"
if [ -f "$ENGINE_PID" ] && kill -0 "$(cat "$ENGINE_PID")" 2>/dev/null; then
  STARTED+=("Engine (worker): zaten calisiyor, PID=$(cat "$ENGINE_PID")")
else
  rm -f "$ENGINE_PID"
  nohup "$PY" -m app.botengine.worker_main >> "$ENGINE_LOG" 2>&1 &
  echo $! > "$ENGINE_PID"
  STARTED+=("Engine (worker): baslatildi, PID=$!")
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
  nohup "$PY" -u "$HTML_DIR/start.py" >> "$ROOT/logs/html.log" 2>&1 &
  HTML_PID=$!
  echo $HTML_PID > "$ROOT/.run/html.pid" 2>/dev/null || true
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
echo "Linux sunucuda: site icin http://SUNUCU_IP:8080 acin; domain (omeraltin.com) icin nginx reverse proxy gerekir."
echo "HTML acilmazsa: logs/html.log dosyasini kontrol edin."
