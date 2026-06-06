"""Uyumluluk shim → scripts/perf/ram_stress_scenarios.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "perf/ram_stress_scenarios.py"),
    run_name="__main__",
)
