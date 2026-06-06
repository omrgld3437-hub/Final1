"""Uyumluluk shim → scripts/runtime/restart_server_win.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "runtime/restart_server_win.py"),
    run_name="__main__",
)
