#!/bin/bash
# Sunucuda deploy: pull, venv, bağımlılıklar, stop, start, port kontrolü.
# Güncel commit çıktıda gösterilir; pull sonrası değiştiyse belirtilir.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "Pulling latest commit..."
BEFORE_COMMIT=""
if [ -d ".git" ]; then
  BEFORE_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || true)
fi
git pull
AFTER_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || true)

if [ -n "$AFTER_COMMIT" ]; then
  if [ -n "$BEFORE_COMMIT" ] && [ "$BEFORE_COMMIT" != "$AFTER_COMMIT" ]; then
    echo "Guncel commit: $AFTER_COMMIT (degisti; onceki: $BEFORE_COMMIT)"
  else
    echo "Guncel commit: $AFTER_COMMIT"
  fi
fi

echo "Activating venv..."
if [ -d "$ROOT/.venv" ]; then
  source "$ROOT/.venv/bin/activate"
else
  echo "Uyari: .venv yok, sistem python kullanilacak."
fi

echo "Installing dependencies..."
pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt

echo "Stopping services..."
if [ -f "$ROOT/stop.command" ]; then
  bash "$ROOT/stop.command" 2>/dev/null || true
elif [ -f "$ROOT/stop" ]; then
  bash "$ROOT/stop" 2>/dev/null || true
fi

echo "Starting services..."
if [ -f "$ROOT/start.command" ]; then
  bash "$ROOT/start.command"
elif [ -f "$ROOT/start" ]; then
  bash "$ROOT/start"
else
  echo "Hata: start.command veya start bulunamadi."
  exit 1
fi

echo "Checking ports..."
if command -v ss >/dev/null 2>&1; then
  ss -tlnp 2>/dev/null | grep -E ':(7999|8000|8080)\s' || true
elif command -v netstat >/dev/null 2>&1; then
  netstat -tlnp 2>/dev/null | grep -E '7999|8000|8080' || true
fi

if [ -n "$AFTER_COMMIT" ]; then
  if [ -n "$BEFORE_COMMIT" ] && [ "$BEFORE_COMMIT" != "$AFTER_COMMIT" ]; then
    echo "Guncel commit: $AFTER_COMMIT (pull ile degisti; onceki: $BEFORE_COMMIT)"
  else
    echo "Guncel commit: $AFTER_COMMIT"
  fi
fi
echo "Deploy completed."
