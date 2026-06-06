"""Uyumluluk shim → scripts/devops/annotate_file_headers.py"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "devops/annotate_file_headers.py"),
    run_name="__main__",
)
