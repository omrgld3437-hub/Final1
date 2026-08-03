#!/bin/zsh
# Yalnız bu klasörün kaydettiği Ayserose backtest sürecini durdurur.
set -u

SCRIPT_DIR=${0:A:h}
STATE_FILE="$SCRIPT_DIR/runtime/server.env"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "Kayıtlı çalışan backtest bulunamadı."
  exit 0
fi

SERVER_PID=$(sed -n 's/^PID=//p' "$STATE_FILE" | head -1)
SERVER_PORT=$(sed -n 's/^PORT=//p' "$STATE_FILE" | head -1)

if [[ ! "$SERVER_PID" =~ '^[0-9]+$' ]]; then
  echo "Backtest süreç kaydı geçersiz; hiçbir süreç durdurulmadı."
  exit 1
fi

PROCESS_LINE=$(ps -p "$SERVER_PID" -o command= 2>/dev/null || true)
if [[ "$PROCESS_LINE" != *"backtest.app"* && "$PROCESS_LINE" != *"backtest/app.py"* ]]; then
  printf 'PID=%s\nPORT=%s\nSTATUS=not_running\n' "$SERVER_PID" "$SERVER_PORT" >"$STATE_FILE"
  echo "Backtest zaten durmuş; başka bir sürece dokunulmadı."
  exit 0
fi

kill -TERM "$SERVER_PID"
for ATTEMPT in {1..30}; do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    printf 'PID=%s\nPORT=%s\nSTATUS=stopped\n' "$SERVER_PID" "$SERVER_PORT" >"$STATE_FILE"
    echo "Ayserose backtest durduruldu."
    exit 0
  fi
  sleep 0.2
done

echo "Backtest kapanış sinyalini aldı ancak süreç henüz tamamlanmadı."
exit 1
