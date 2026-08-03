#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

mkdir -p "$PROJECT_ROOT/.run"

LOCAL_MANAGER_BASE_URL="http://${LOCAL_MANAGER_TUNNEL_HOST}:${LOCAL_MANAGER_TUNNEL_PORT}"
MANAGER_URL="${LOCAL_MANAGER_BASE_URL}/ui/"
MANAGER_STATUS_URL="${LOCAL_MANAGER_BASE_URL}/api/status"

printf 'Final1 Manager Server yerel tünel kontrol ediliyor...\n'

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 2 "$MANAGER_STATUS_URL" >/dev/null 2>&1; then
    printf 'Manager tüneli zaten açık: %s\n' "$MANAGER_URL"
    open_in_browser "$MANAGER_URL"
    exit 0
  fi
fi

printf 'Manager tüneli açılıyor: %s -> %s:%s\n' "$LOCAL_MANAGER_TUNNEL_PORT" "$REMOTE_MANAGER_HOST" "$REMOTE_MANAGER_PORT"

ssh "${SSH_ARGS[@]}" \
  -f -N \
  -o ExitOnForwardFailure=yes \
  -L "${LOCAL_MANAGER_TUNNEL_HOST}:${LOCAL_MANAGER_TUNNEL_PORT}:${REMOTE_MANAGER_HOST}:${REMOTE_MANAGER_PORT}" \
  "$(remote_target)"

if command -v curl >/dev/null 2>&1; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --max-time 2 "$MANAGER_STATUS_URL" >/dev/null 2>&1; then
      printf 'Manager tüneli hazır: %s\n' "$MANAGER_URL"
      open_in_browser "$MANAGER_URL"
      exit 0
    fi
    sleep 1
  done
fi

printf 'Manager tüneli açıldı. Tarayıcıda açılıyor: %s\n' "$MANAGER_URL"
open_in_browser "$MANAGER_URL"
