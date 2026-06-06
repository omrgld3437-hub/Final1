"""Uyumluluk shim → scripts/perf/binance_weight_sim.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "perf/binance_weight_sim.py"),
    run_name="__main__",
)
