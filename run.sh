#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/ops/run.sh" "$@"
