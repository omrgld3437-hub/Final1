#!/usr/bin/env bash
set -euo pipefail

SUNUCU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$SUNUCU_DIR/.." && pwd)"

if [ -f "$SUNUCU_DIR/ayarlar.env" ]; then
  # shellcheck disable=SC1091
  source "$SUNUCU_DIR/ayarlar.env"
fi

SERVER_HOST="${SERVER_HOST:-178.210.168.102}"
SERVER_USER="${SERVER_USER:-root}"
SSH_PORT="${SSH_PORT:-22666}"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/aysegul_sunucu_ed25519}"
APP_NAME="${APP_NAME:-final1}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/opt/final1/current}"
REMOTE_WEB_HOST="${REMOTE_WEB_HOST:-127.0.0.1}"
REMOTE_WEB_PORT="${REMOTE_WEB_PORT:-8000}"
REMOTE_MANAGER_HOST="${REMOTE_MANAGER_HOST:-127.0.0.1}"
REMOTE_MANAGER_PORT="${REMOTE_MANAGER_PORT:-7999}"
LOCAL_TUNNEL_HOST="${LOCAL_TUNNEL_HOST:-127.0.0.1}"
LOCAL_TUNNEL_PORT="${LOCAL_TUNNEL_PORT:-18081}"
LOCAL_MANAGER_TUNNEL_HOST="${LOCAL_MANAGER_TUNNEL_HOST:-127.0.0.1}"
LOCAL_MANAGER_TUNNEL_PORT="${LOCAL_MANAGER_TUNNEL_PORT:-17999}"
STATUS_DASHBOARD_HOST="${STATUS_DASHBOARD_HOST:-127.0.0.1}"
STATUS_DASHBOARD_PORT="${STATUS_DASHBOARD_PORT:-18082}"

SSH_ARGS=(
  -p "$SSH_PORT"
  -i "$KEY_FILE"
  -o IdentitiesOnly=yes
  -o ForwardAgent=no
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=8
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
)

remote_target() {
  printf '%s@%s' "$SERVER_USER" "$SERVER_HOST"
}

open_in_browser() {
  local url="$1"
  if [ "${NO_OPEN:-0}" = "1" ]; then
    printf 'Tarayıcı testi kapalı. Adres: %s\n' "$url"
    return 0
  fi
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  else
    printf 'Tarayıcıda açın: %s\n' "$url"
  fi
}

is_final1_server_local() {
  [ -f "/etc/systemd/system/${APP_NAME}-web.service" ] && [ -d "$REMOTE_PROJECT_DIR" ]
}

run_service_command() {
  local action="$1"
  local cmd

  case "$action" in
    start|restart)
      cmd="systemctl ${action} ${APP_NAME}-web ${APP_NAME}-worker ${APP_NAME}-manager && systemctl is-active ${APP_NAME}-web ${APP_NAME}-worker ${APP_NAME}-manager"
      ;;
    stop)
      cmd="systemctl stop ${APP_NAME}-worker ${APP_NAME}-manager ${APP_NAME}-web || true; systemctl is-active ${APP_NAME}-web ${APP_NAME}-worker ${APP_NAME}-manager || true"
      ;;
    *)
      printf 'Desteklenmeyen servis islemi: %s\n' "$action" >&2
      return 2
      ;;
  esac

  if is_final1_server_local; then
    if [ "$(id -u)" -eq 0 ]; then
      bash -lc "$cmd"
    else
      sudo bash -lc "$cmd"
    fi
  else
    ssh "${SSH_ARGS[@]}" "$(remote_target)" "$cmd"
  fi
}
