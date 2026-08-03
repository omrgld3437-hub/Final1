#!/bin/zsh
# Ayserose yerel backtest sunucusunu güvenli bir boş portta başlatır.
set -u

SCRIPT_DIR=${0:A:h}
PROJECT_DIR=${SCRIPT_DIR:h}
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
RUNTIME_DIR="$SCRIPT_DIR/runtime"
STATE_FILE="$RUNTIME_DIR/server.env"
LOG_FILE="$RUNTIME_DIR/server.log"

mkdir -p "$RUNTIME_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Ayserose Python ortamı bulunamadı: $PYTHON_BIN"
  read "?Kapatmak için Enter'a basın..."
  exit 1
fi

# Önceden çalışan kendi backtest sunucumuz varsa ikinci kopyayı açma.
for PORT_CANDIDATE in {8765..8795}; do
  HEALTH=$(curl -fsS --max-time 1 "http://127.0.0.1:${PORT_CANDIDATE}/api/health" 2>/dev/null || true)
  if [[ "$HEALTH" == *'"service":"ayserose-local-backtest"'* || "$HEALTH" == *'"service": "ayserose-local-backtest"'* ]]; then
    echo "Backtest zaten çalışıyor: http://127.0.0.1:${PORT_CANDIDATE}"
    if [[ "${NO_OPEN:-0}" != "1" ]]; then
      open "http://127.0.0.1:${PORT_CANDIDATE}"
    fi
    exit 0
  fi
done

SELECTED_PORT=8765
while [[ $SELECTED_PORT -le 8795 ]]; do
  if ! lsof -nP -iTCP:$SELECTED_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  SELECTED_PORT=$((SELECTED_PORT + 1))
done

if [[ $SELECTED_PORT -gt 8795 ]]; then
  echo "8765-8795 aralığında boş port bulunamadı."
  read "?Kapatmak için Enter'a basın..."
  exit 1
fi

cd "$PROJECT_DIR"
nohup env BACKTEST_PORT="$SELECTED_PORT" PYTHONPATH="$PROJECT_DIR" \
  "$PYTHON_BIN" -u -m backtest.app --no-open --port "$SELECTED_PORT" \
  </dev/null >>"$LOG_FILE" 2>&1 &
SERVER_PID=$!
printf 'PID=%s\nPORT=%s\nSTATUS=running\n' "$SERVER_PID" "$SELECTED_PORT" >"$STATE_FILE"

for ATTEMPT in {1..40}; do
  HEALTH=$(curl -fsS --max-time 1 "http://127.0.0.1:${SELECTED_PORT}/api/health" 2>/dev/null || true)
  if [[ "$HEALTH" == *'"service":"ayserose-local-backtest"'* || "$HEALTH" == *'"service": "ayserose-local-backtest"'* ]]; then
    # İlk yanıtın ardından süreç kapanıyorsa bunu başarı sayma.
    sleep 1
    HEALTH=$(curl -fsS --max-time 1 "http://127.0.0.1:${SELECTED_PORT}/api/health" 2>/dev/null || true)
    if ! kill -0 "$SERVER_PID" 2>/dev/null || [[ "$HEALTH" != *'"service":"ayserose-local-backtest"'* && "$HEALTH" != *'"service": "ayserose-local-backtest"'* ]]; then
      break
    fi
    echo "Ayserose backtest hazır: http://127.0.0.1:${SELECTED_PORT}"
    echo "Durdurmak için: backtest/stop.command"
    if [[ "${NO_OPEN:-0}" != "1" ]]; then
      open "http://127.0.0.1:${SELECTED_PORT}"
    fi
    exit 0
  fi
  sleep 0.25
done

printf 'PID=%s\nPORT=%s\nSTATUS=start_failed\n' "$SERVER_PID" "$SELECTED_PORT" >"$STATE_FILE"
echo "Backtest başlatılamadı. Kayıt: $LOG_FILE"
read "?Kapatmak için Enter'a basın..."
exit 1
