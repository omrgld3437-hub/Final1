#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

printf 'Sunucudaki Final1 projesi durduruluyor...\n'
run_service_command stop
printf 'Sunucudaki Final1 projesi durduruldu. Aysegul ve Nginx çalışmaya devam eder.\n'

