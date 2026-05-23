#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/runtime/run.sh" "$@"
