"""Uyumluluk shim → scripts/maintenance/fix_manager_cgi.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "maintenance/fix_manager_cgi.py"),
    run_name="__main__",
)
