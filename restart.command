#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop.command"
sleep 2
"$SCRIPT_DIR/start.command"
