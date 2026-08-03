#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

export SERVER_HOST SERVER_USER SSH_PORT KEY_FILE APP_NAME REMOTE_WEB_PORT STATUS_DASHBOARD_HOST STATUS_DASHBOARD_PORT

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf 'Python bulunamadı. Sunucu durum paneli başlatılamadı.\n'
  exit 1
fi

printf 'Sunucu durum paneli açılıyor: http://%s:%s\n' "$STATUS_DASHBOARD_HOST" "$STATUS_DASHBOARD_PORT"
exec "$PYTHON_BIN" "$SCRIPT_DIR/tools/sunucu_durumu_server.py"

