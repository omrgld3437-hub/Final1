#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

mkdir -p "$PROJECT_ROOT/.run"

LOCAL_BASE_URL="http://${LOCAL_TUNNEL_HOST}:${LOCAL_TUNNEL_PORT}"
LOGIN_URL="${LOCAL_BASE_URL}/ui/login.html"
HEALTH_URL="${LOCAL_BASE_URL}/api/health"

printf 'Final1 yerel tünel kontrol ediliyor...\n'

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
    printf 'Tünel zaten açık: %s\n' "$LOGIN_URL"
    open_in_browser "$LOGIN_URL"
    exit 0
  fi
fi

printf 'SSH tüneli açılıyor: %s -> %s:%s\n' "$LOCAL_TUNNEL_PORT" "$REMOTE_WEB_HOST" "$REMOTE_WEB_PORT"

ssh "${SSH_ARGS[@]}" \
  -f -N \
  -o ExitOnForwardFailure=yes \
  -L "${LOCAL_TUNNEL_HOST}:${LOCAL_TUNNEL_PORT}:${REMOTE_WEB_HOST}:${REMOTE_WEB_PORT}" \
  "$(remote_target)"

if command -v curl >/dev/null 2>&1; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
      printf 'Tünel hazır: %s\n' "$LOGIN_URL"
      open_in_browser "$LOGIN_URL"
      exit 0
    fi
    sleep 1
  done
fi

printf 'Tünel açıldı. Tarayıcıda açılıyor: %s\n' "$LOGIN_URL"
open_in_browser "$LOGIN_URL"

