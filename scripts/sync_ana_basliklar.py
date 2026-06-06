"""Uyumluluk shim → scripts/devops/sync_ana_basliklar.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "devops/sync_ana_basliklar.py"),
    run_name="__main__",
)
