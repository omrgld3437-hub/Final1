#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

printf 'ayserose arayüzü doğrulanıyor ve yayınlanıyor...\n'
FRONTEND_ONLY=1 exec "$PROJECT_ROOT/deploy/sunucuya-yayinla.command"
