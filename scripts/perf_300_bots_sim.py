"""Uyumluluk shim → scripts/perf/perf_300_bots_sim.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "perf/perf_300_bots_sim.py"),
    run_name="__main__",
)
