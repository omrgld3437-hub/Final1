"""Uyumluluk shim → scripts/perf/perf_snapshot_test.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "perf/perf_snapshot_test.py"), run_name="__main__")
