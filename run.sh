#!/bin/bash
# Proje kökünden scripts/run.sh çalıştırır (admin "Sunucuyu Yeniden Başlat" ve restart_server.py uyumu).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/run.sh" "$@"
