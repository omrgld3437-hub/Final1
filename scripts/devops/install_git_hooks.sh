#!/usr/bin/env bash
# Proje git hook'larını .git/hooks altına kurar.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/scripts/devops/git-hooks"
DST="$ROOT/.git/hooks"

if [ ! -d "$DST" ]; then
  echo "Hata: .git/hooks bulunamadı ($DST)" >&2
  exit 1
fi

for hook in post-commit; do
  install -m 755 "$SRC/$hook" "$DST/$hook"
  echo "Kuruldu: .git/hooks/$hook"
done

python3 "$ROOT/scripts/devops/sync_git_log.py"
echo "GIT.md güncellendi."
