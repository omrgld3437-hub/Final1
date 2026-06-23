#!/bin/bash
# ayserose — stop.command ardindan start.command.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop.command"
sleep 2
"$SCRIPT_DIR/start.command"
