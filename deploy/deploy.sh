#!/bin/bash
# Deploy script - Sadece DEĞİŞKEN dosyaları sunucuya kopyalar
# SABİT dosyalar (.env, *.db, logs, vb.) atlanır - sunucudaki mevcut hali korunur
#
# Kullanım:
#   ./deploy/deploy.sh user@sunucu.com:/var/www/final1
#   ./deploy/deploy.sh  (RSYNC_DEST ortam değişkeni kullanılır)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXCLUDE_FILE="$SCRIPT_DIR/SABIT_DOSYALAR.txt"

DEST="${1:-$RSYNC_DEST}"

if [ -z "$DEST" ]; then
    echo "Kullanım: $0 user@host:/path/to/project"
    echo "   veya:  export RSYNC_DEST=\"user@host:/path\" && $0"
    echo ""
    echo "SABİT dosyalar (.env, *.db, logs, vb.) atlanır."
    echo "DEĞİŞKEN dosyalar (app/, ui/, scripts/, vb.) kopyalanır."
    exit 1
fi

if [ ! -f "$EXCLUDE_FILE" ]; then
    echo "Hata: $EXCLUDE_FILE bulunamadı"
    exit 1
fi

echo "Deploy: $PROJECT_ROOT -> $DEST"
echo "SABİT dosyalar atlanıyor (sunucudaki mevcut hali korunacak)"
echo ""

rsync -avz --delete \
    --exclude-from="$EXCLUDE_FILE" \
    "$PROJECT_ROOT/" "$DEST/"

echo ""
echo "Deploy tamamlandı."
