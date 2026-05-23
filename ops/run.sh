#!/bin/bash
# Dev: yalnizca Web + Worker (Manager yok). Admin restart ile uyumlu.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/runtime/run.sh" "$@"
