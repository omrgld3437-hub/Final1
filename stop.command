#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
MANAGER_PID="$ROOT/.run/manager.pid"
WEB_PID="$ROOT/.run/web.pid"
ENGINE_PID="$ROOT/.run/worker.pid"

# Manager
if [ -f "$MANAGER_PID" ]; then
  PID=$(cat "$MANAGER_PID")
  kill -TERM "$PID" 2>/dev/null; sleep 2; kill -KILL "$PID" 2>/dev/null
  rm -f "$MANAGER_PID"
fi
P=$(lsof -ti:7999 2>/dev/null); [ -n "$P" ] && echo "$P" | xargs kill -KILL 2>/dev/null

# Web
if [ -f "$WEB_PID" ]; then
  PID=$(cat "$WEB_PID")
  kill -TERM "$PID" 2>/dev/null; sleep 2; kill -KILL "$PID" 2>/dev/null
  rm -f "$WEB_PID"
fi
P=$(lsof -ti:8000 2>/dev/null); [ -n "$P" ] && echo "$P" | xargs kill -KILL 2>/dev/null

# Engine
if [ -f "$ENGINE_PID" ]; then
  PID=$(cat "$ENGINE_PID")
  kill -TERM "$PID" 2>/dev/null; sleep 2; kill -KILL "$PID" 2>/dev/null
  rm -f "$ENGINE_PID"
fi

# marketing / omeraltinhtml (8080)
HTML_PIDFILE="$ROOT/.run/html.pid"
if [ -f "$HTML_PIDFILE" ]; then
  HPID=$(cat "$HTML_PIDFILE" 2>/dev/null)
  [ -n "$HPID" ] && kill -TERM "$HPID" 2>/dev/null; sleep 1; [ -n "$HPID" ] && kill -KILL "$HPID" 2>/dev/null
  rm -f "$HTML_PIDFILE"
fi
P=$(lsof -ti:8080 2>/dev/null); [ -n "$P" ] && echo "$P" | xargs kill -KILL 2>/dev/null

echo "Durduruldu (Manager, Web, Engine, HTML)."
