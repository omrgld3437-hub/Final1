"""Uyumluluk shim → scripts/devops/sync_module_meta.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "devops/sync_module_meta.py"),
    run_name="__main__",
)
