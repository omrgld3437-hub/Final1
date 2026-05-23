#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/maintenance/fetch_coin_logos.sh" "$@"
