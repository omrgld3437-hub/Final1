"""Uyumluluk shim → scripts/perf/ram_analyze.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "perf/ram_analyze.py"), run_name="__main__")
