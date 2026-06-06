"""Uyumluluk shim → scripts/maintenance/fetch_binance_coin_logos.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "maintenance/fetch_binance_coin_logos.py"),
    run_name="__main__",
)
