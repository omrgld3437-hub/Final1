#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

if ! command -v lsof >/dev/null 2>&1; then
  printf 'lsof bulunamadı. Tüneli kapatmak için terminalde SSH sürecini kapatın.\n'
  exit 1
fi

PIDS="$(lsof -tiTCP:"$LOCAL_TUNNEL_PORT" -sTCP:LISTEN 2>/dev/null || true)"

if [ -z "$PIDS" ]; then
  printf 'Açık Final1 yerel tüneli bulunamadı.\n'
  exit 0
fi

for pid in $PIDS; do
  CMD="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  if printf '%s' "$CMD" | grep -q "${REMOTE_WEB_HOST}:${REMOTE_WEB_PORT}"; then
    kill "$pid"
    printf 'Tünel kapatıldı. PID: %s\n' "$pid"
  fi
done

