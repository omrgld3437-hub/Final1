"""
observability Python paketi.
"""
# RAM root cause analysis: measurement only, no optimization.
#
# Aktif etmek: RAM_PROBE_ENABLED=1 veya RAM_CAPTURE=1 (5 dk detaylı oturum)
# - RAM_CAPTURE: logs/ram_capture_{session}_{web|worker}.jsonl — python scripts/perf/ram_capture_5min.py --guide
# - Her 30s snapshot → logs/ram_snapshots.log (JSON satırları)
# - Bot start/stop/ORDER_FILLED/cycle_tick → probe_bot_event
# - Market data (60s) → probe_market_data
# - Event store (ORDER_FILLED öncesi/sonrası) → probe_event_store
# - GET /api/debug/ram-snapshot → tek snapshot + gc_collect
# Opsiyonel: pip install objgraph memory_profiler (derin analiz)
