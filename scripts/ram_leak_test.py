"""Uyumluluk shim → scripts/perf/ram_leak_test.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "perf/ram_leak_test.py"), run_name="__main__"
)
