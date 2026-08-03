#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

printf 'Sunucudaki Final1 projesi başlatılıyor...\n'
run_service_command start
printf 'Sunucudaki Final1 projesi aktif.\n'

