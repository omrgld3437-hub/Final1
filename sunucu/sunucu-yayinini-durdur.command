#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

printf 'Final1 sunucu yayını durduruluyor...\n'
run_service_command stop
printf 'Final1 yayını durduruldu.\n'

