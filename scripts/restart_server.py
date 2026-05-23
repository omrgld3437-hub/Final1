"""Uyumluluk shim → scripts/runtime/restart_server.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "runtime/restart_server.py"), run_name="__main__")
