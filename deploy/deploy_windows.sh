#!/bin/bash
# Windows sunucuya deploy - Yolu duzenleyip calistirin.
# Windows sunucuda OpenSSH + rsync (Git for Windows / WSL) gerekir.
#
# Kullanim: SUNUCU_IP veya SUNUCU_HOST'u duzenleyin, sonra:
#   ./deploy/deploy_windows.sh
# veya:
#   SUNUCU_IP=192.168.1.100 ./deploy/deploy_windows.sh

set -e

# --- Windows sunucu IP (degistirmek icin: SUNUCU_IP=... ./deploy/deploy_windows.sh) ---
SUNUCU_IP="${SUNUCU_IP:-185.88.174.75}"
USER="Administrator"
# Windows yolunu Git Bash tarzinda: /c/Users/...
REMOTE_PATH="/c/Users/Administrator/Desktop/Final1"

if [ "$SUNUCU_IP" = "SUNUCU_IP_BURAYA" ]; then
    echo "Hata: SUNUCU_IP tanimli degil."
    echo "Kullanim: SUNUCU_IP=192.168.1.100 ./deploy/deploy_windows.sh"
    echo "  veya bu dosyada SUNUCU_IP_BURAYA yerine sunucu IP/host yazin."
    exit 1
fi

DEST="${USER}@${SUNUCU_IP}:${REMOTE_PATH}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXCLUDE_FILE="$SCRIPT_DIR/SABIT_DOSYALAR.txt"

if [ ! -f "$EXCLUDE_FILE" ]; then
    echo "Hata: $EXCLUDE_FILE bulunamadi"
    exit 1
fi

echo "Deploy: $PROJECT_ROOT -> $DEST"
echo "SABIT dosyalar atlanacak."
echo ""

rsync -avz --delete \
    --exclude-from="$EXCLUDE_FILE" \
    "$PROJECT_ROOT/" "$DEST/"

echo ""
echo "Deploy tamamlandi. Sunucuda start.bat calistirin."
