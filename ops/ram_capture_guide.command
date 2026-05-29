#!/bin/bash
# RAM capture 5 dk — env talimatları (macOS: python değil python3 / .venv)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "python3 bulunamadı. Kurulum: ops/start.command veya brew install python3"
  exit 1
fi
exec "$PY" scripts/perf/ram_capture_5min.py --guide
