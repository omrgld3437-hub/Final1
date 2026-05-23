"""Uyumluluk shim → scripts/runtime/local_web_worker_helper.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "runtime/local_web_worker_helper.py"), run_name="__main__")
