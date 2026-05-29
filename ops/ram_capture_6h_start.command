#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
exec "$PY" scripts/perf/ram_capture_6h.py --start
