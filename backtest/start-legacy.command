#!/bin/zsh
# İlk yerel başlatıcı — kayıp olmaması için korundu ve yeni güvenli girişe yönlendirildi.
set -e

SCRIPT_DIR=${0:A:h}
exec "$SCRIPT_DIR/start.command"
