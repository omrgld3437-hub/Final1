#!/bin/bash
# DCA Bot Manager - Clean Version
# Run script for macOS
# Usage: ./run.sh [--fg]   (--fg = foreground, terminal açık kalır)

set -e

FG_MODE=0
[[ "$1" == "--fg" ]] && FG_MODE=1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
case "$(basename "$SCRIPT_DIR")" in
  runtime) DIR="$(cd "$SCRIPT_DIR/../.." && pwd)" ;;
  scripts) DIR="$(cd "$SCRIPT_DIR/.." && pwd)" ;;
  *) DIR="$SCRIPT_DIR" ;;
esac
cd "$DIR"

export PYTHONWARNINGS="${PYTHONWARNINGS:+$PYTHONWARNINGS,}ignore:::urllib3"

echo "========================================="
echo "DCA Bot Manager (Clean) Başlatılıyor..."
echo "========================================="
echo "📍 Proje klasörü: $DIR"
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 bulunamadı. Lütfen Python3 yükleyin."
    exit 1
fi

echo "📦 Virtual environment kontrol ediliyor..."

# venv - create if not exists or broken (e.g. copied from another project)
if [ -d "$DIR/.venv" ]; then
  UVICORN_SHEBANG=""
  [ -f "$DIR/.venv/bin/uvicorn" ] && UVICORN_SHEBANG=$(head -1 "$DIR/.venv/bin/uvicorn" 2>/dev/null || true)
  # Shebang must point to this project's .venv; if it points elsewhere, venv was copied
  if [[ -n "$UVICORN_SHEBANG" && "$UVICORN_SHEBANG" != "#!$DIR/"* ]]; then
    echo "⚠️  Sanal ortam başka projeden kopyalanmış. Yeniden oluşturuluyor..."
    rm -rf "$DIR/.venv"
  fi
fi

if [ ! -d "$DIR/.venv" ]; then
  echo "⚠️  .venv bulunamadı, oluşturuluyor..."
  python3 -m venv "$DIR/.venv"
  echo "✅ Virtual environment oluşturuldu"
  echo "📦 Paketler yükleniyor (ilerleme çubuğu aşağıda)..."
  echo ""
  source "$DIR/.venv/bin/activate"
  pip install --upgrade pip
  pip install -r "$DIR/requirements.txt" --progress-bar on
  echo ""
  echo "✅ Paketler yüklendi"
else
  source "$DIR/.venv/bin/activate"
fi

# Create necessary directories
mkdir -p "$DIR/logs"
mkdir -p "$DIR/.run"

PID_FILE="$DIR/.run/server.pid"
LOG_FILE="$DIR/.run/server.log"
ADMIN_URL="http://127.0.0.1:8000/ui/admin.html"
DASHBOARD_URL="http://127.0.0.1:8000/ui/dashboard.html"

# Worker PID (botlar için gerekli)
WORKER_PID_FILE="$DIR/.run/worker.pid"
WORKER_LOG="$DIR/logs/worker.log"

# Check if already running (skip when --fg)
if [ $FG_MODE -eq 0 ] && [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  if [ ! -f "$WORKER_PID_FILE" ] || ! kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
    rm -f "$WORKER_PID_FILE"
    nohup "$DIR/.venv/bin/python" -m app.botengine.worker_main >> "$WORKER_LOG" 2>&1 &
    echo $! > "$WORKER_PID_FILE"
    echo "✅ Bot Engine (worker) başlatıldı (server zaten çalışıyordu)"
  fi
  echo "✅ Server zaten çalışıyor. PID=$(cat "$PID_FILE")"
  echo "📋 Son loglar (son 20 satır):"
  echo "----------------------------------------"
  tail -20 "$LOG_FILE" 2>/dev/null || echo "— log dosyası bulunamadı"
  echo "----------------------------------------"
  echo ""
  echo "💡 Canlı logları görmek için: tail -f $LOG_FILE"
  echo "💡 Veya server'ı durdurup yeniden başlatın"
  echo ""
  echo "========================================="
  echo "✅ DCA Bot Manager (Clean) çalışıyor!"
  echo "========================================="
  echo "📌 Admin:     $ADMIN_URL"
  echo "📌 Dashboard: $DASHBOARD_URL"
  echo "🛑 Durdurmak: stop/stop.command"
  echo "========================================="
  exit 0
fi

# Worker (bot engine) - botların çalışması için gerekli
mkdir -p "$DIR/logs"
if [ $FG_MODE -eq 0 ]; then
  if [ -f "$WORKER_PID_FILE" ] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
    echo "✅ Bot Engine (worker) zaten çalışıyor"
  else
    rm -f "$WORKER_PID_FILE"
    nohup "$DIR/.venv/bin/python" -m app.botengine.worker_main >> "$WORKER_LOG" 2>&1 &
    echo $! > "$WORKER_PID_FILE"
    echo "✅ Bot Engine (worker) başlatıldı. PID=$(cat "$WORKER_PID_FILE")"
    sleep 1
  fi
fi

# Port 8000 doluysa önceki süreci kapat (address already in use önlemi)
OLD_PID=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
  echo "⚠️  Port 8000 kullanımda (PID: $OLD_PID). Eski süreç kapatılıyor..."
  kill $OLD_PID 2>/dev/null || true
  sleep 2
  # Hâlâ açıksa zorla kapat
  STILL=$(lsof -ti :8000 2>/dev/null || true)
  if [ -n "$STILL" ]; then
    kill -9 $STILL 2>/dev/null || true
    sleep 1
  fi
  echo "✅ Port 8000 serbest bırakıldı."
  echo ""
fi

WEB_HOST="${WEB_HOST:-127.0.0.1}"
if [ -z "${WEB_UVICORN_WORKERS:-}" ]; then
  WEB_UVICORN_WORKERS=1
fi
export PARAM_POOL_WARMUP="${PARAM_POOL_WARMUP:-0}"
echo "🚀 Backend başlatılıyor (FastAPI + Uvicorn, workers=$WEB_UVICORN_WORKERS)..."
echo "   URL: http://${WEB_HOST}:8000"
echo ""

# --workers 2: parallel API requests. Bot engine remains separate (worker_main.py).
if [ $FG_MODE -eq 1 ]; then
  # Foreground: worker arka planda, uvicorn ön planda
  if [ -f "$WORKER_PID_FILE" ] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
    : # worker zaten çalışıyor
  else
    rm -f "$WORKER_PID_FILE"
    nohup "$DIR/.venv/bin/python" -m app.botengine.worker_main >> "$WORKER_LOG" 2>&1 &
    echo $! > "$WORKER_PID_FILE"
    echo "✅ Bot Engine (worker) arka planda başlatıldı"
  fi
  echo "🌐 Tarayıcıda manuel açın: $ADMIN_URL"
  echo "🛑 Durdurmak: Ctrl+C"
  echo "========================================="
  echo ""
  "$DIR/.venv/bin/uvicorn" app.main:app --host "$WEB_HOST" --port 8000 --workers "$WEB_UVICORN_WORKERS" --loop uvloop --http httptools --log-level info || true
  echo ""
  echo "========================================="
  echo "Server kapandı. Pencereyi kapatmak için Enter'a basın."
  echo "========================================="
  read -r
  exit 0
else
  # Background: 2 API workers; bot engine remains separate (worker_main.py)
  nohup "$DIR/.venv/bin/uvicorn" app.main:app --host "$WEB_HOST" --port 8000 --workers "$WEB_UVICORN_WORKERS" --loop uvloop --http httptools --log-level info \
    > "$LOG_FILE" 2>&1 &

  PID=$!
  echo "$PID" > "$PID_FILE"
  disown "$PID" 2>/dev/null || true

  echo "✅ Server started. PID=$PID"
  echo "🧾 Log dosyası: $LOG_FILE"
  echo "📍 Çalışan proje: $DIR"
  echo ""
  echo "========================================="
  echo "✅ DCA Bot Manager (Clean) çalışıyor!"
  echo "========================================="
  echo "📌 Admin:     $ADMIN_URL"
  echo "📌 Dashboard: $DASHBOARD_URL"
  echo "🛑 Durdurmak: stop/stop.command"
  echo "💡 Hangi klasör çalışıyor: curl -s http://127.0.0.1:8000/api/health | grep project_path"
  echo "========================================="
fi
