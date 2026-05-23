#!/bin/bash
# Proje kokunden ops/start.command cagirir (geriye uyumlu).
exec "$(cd "$(dirname "$0")" && pwd)/ops/start.command"
